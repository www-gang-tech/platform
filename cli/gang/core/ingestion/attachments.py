"""Gmail attachments as canonical private documents.

An attachment is evidence in its own right: a signed engagement letter says
more than the email that carried it. This module turns attachment bytes that
Gmail ingestion has already put in raw custody into canonical documents under
``vault/attachments/``, each linked back to every message and thread it
arrived in.

Identity is deliberate:

* An **occurrence** is one attachment on one message, identified by the Gmail
  message ID and the SHA-256 of its bytes. Gmail's ``attachmentId`` changes on
  every API response and is never used for identity.
* A **payload** is a distinct byte sequence. The same PDF attached to five
  replies is one payload with five occurrences, so it is extracted once and
  becomes one canonical document whose provenance lists all five.

Nothing here calls a model or the network. Backfill reads thread manifests
and raw bytes already in custody, so historical attachments need no API
calls. Every outcome other than a successful extraction (unsupported type, no
text layer, password, corrupt file) is recorded and reported; none aborts the
batch.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

import yaml

from core.entities.documents import preserved_entity_frontmatter

from .extract import (
    EXTRACTOR_VERSION,
    RETRYABLE_STATUSES,
    STATUS_EXTRACTED,
    STATUS_MALFORMED,
    STATUS_REQUIRES_OCR,
    STATUS_UNSUPPORTED,
    Extraction,
    extract_text,
    extraction_kind,
    sanitize_extracted_text,
)
from .ids import content_sha256, slugify, stable_source_id, uuid7
from .raw_store import RawStore
from .registry import IngestionRegistry


ATTACHMENT_SOURCE_TYPE = "gmail-attachment"
ATTACHMENT_CONTENT_SOURCE_TYPE = "gmail-attachment-content"
ATTACHMENT_ADAPTER = "GmailAttachmentIngestion"


def attachment_source_id(message_id: str, content_hash: str) -> str:
    """Stable identity for one attachment on one Gmail message."""
    return stable_source_id(ATTACHMENT_SOURCE_TYPE, "gmail", f"{message_id}:sha256:{content_hash}")


def attachment_content_source_id(content_hash: str) -> str:
    """Stable identity for one distinct attachment payload."""
    return stable_source_id(ATTACHMENT_CONTENT_SOURCE_TYPE, "sha256", content_hash)


def gmail_thread_source_id(thread_id: str) -> str:
    return stable_source_id("gmail-thread", "gmail", thread_id)


@dataclass(frozen=True)
class AttachmentOccurrence:
    """One attachment on one message, with its bytes already in raw custody."""

    gmail_message_id: str
    gmail_thread_id: str
    filename: str
    mime_type: str
    content_hash: str
    raw_ref: str
    received_at: str = ""
    source_account: str = ""
    part_id: str = ""

    @property
    def source_id(self) -> str:
        return attachment_source_id(self.gmail_message_id, self.content_hash)

    @property
    def thread_source_id(self) -> str:
        return gmail_thread_source_id(self.gmail_thread_id)


@dataclass(frozen=True)
class AttachmentResult:
    """What happened to one distinct payload."""

    content_source_id: str
    content_hash: str
    filename: str
    mime_type: str
    extraction_status: str
    document_status: str
    occurrences: int
    document_id: str = ""
    document_path: Optional[Path] = None
    detail: str = ""
    source_ids: List[str] = field(default_factory=list)
    thread_ids: List[str] = field(default_factory=list)


@dataclass
class AttachmentReport:
    """Counts for one attachment run.

    ``discovered`` counts occurrences. ``duplicates`` counts occurrences whose
    bytes another occurrence already carries. The outcome counts
    (``extracted``, ``unsupported``, ``requires_ocr``, ``failed``) count
    distinct payloads, so ``discovered == duplicates + extracted + unsupported
    + requires_ocr + failed``.
    """

    dry_run: bool = False
    discovered: int = 0
    duplicates: int = 0
    extracted: int = 0
    unsupported: int = 0
    requires_ocr: int = 0
    failed: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    unsupported_types: Counter = field(default_factory=Counter)
    results: List[AttachmentResult] = field(default_factory=list)

    @property
    def distinct_payloads(self) -> int:
        return self.extracted + self.unsupported + self.requires_ocr + self.failed

    @property
    def changed_document_ids(self) -> List[str]:
        return [
            result.document_id
            for result in self.results
            if result.document_id and result.document_status in {"created", "updated"}
        ]

    @property
    def problems(self) -> List[AttachmentResult]:
        """Payloads that need a human: no text layer, or unreadable."""
        return [
            result
            for result in self.results
            if result.extraction_status not in {STATUS_EXTRACTED, STATUS_UNSUPPORTED}
        ]

    def merge(self, other: "AttachmentReport") -> None:
        for name in (
            "discovered", "duplicates", "extracted", "unsupported", "requires_ocr",
            "failed", "created", "updated", "unchanged",
        ):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        self.unsupported_types.update(other.unsupported_types)
        self.results.extend(other.results)

    def summary(self) -> Dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "discovered": self.discovered,
            "distinct_payloads": self.distinct_payloads,
            "duplicates": self.duplicates,
            "extracted": self.extracted,
            "unsupported": self.unsupported,
            "requires_ocr": self.requires_ocr,
            "failed": self.failed,
            "documents_created": self.created,
            "documents_updated": self.updated,
            "documents_unchanged": self.unchanged,
            "unsupported_types": dict(self.unsupported_types.most_common()),
        }


class AttachmentIngestionService:
    """Extract attachment payloads into canonical documents, idempotently."""

    def __init__(
        self,
        *,
        raw_store: RawStore,
        registry: IngestionRegistry,
        attachments_path: Path,
        now_fn: Callable[[], str] | None = None,
    ):
        self.raw_store = raw_store
        self.registry = registry
        self.attachments_path = Path(attachments_path)
        self.now_fn = now_fn or (lambda: datetime.now(timezone.utc).isoformat())

    def ingest(
        self,
        occurrences: Iterable[AttachmentOccurrence],
        *,
        dry_run: bool = False,
        retry_failed: bool = False,
    ) -> AttachmentReport:
        report = AttachmentReport(dry_run=dry_run)
        groups: Dict[str, List[AttachmentOccurrence]] = {}
        seen_sources = set()
        for occurrence in occurrences:
            if occurrence.source_id in seen_sources:
                continue
            seen_sources.add(occurrence.source_id)
            report.discovered += 1
            groups.setdefault(occurrence.content_hash, []).append(occurrence)
        report.duplicates = report.discovered - len(groups)

        with self.registry.batch():
            for content_hash in sorted(groups, key=lambda value: _group_order(groups[value])):
                try:
                    result = self._ingest_payload(content_hash, groups[content_hash], dry_run=dry_run, retry_failed=retry_failed)
                except Exception as exc:  # noqa: BLE001 - one bad payload never stops the batch
                    first = _ordered(groups[content_hash])[0]
                    result = AttachmentResult(
                        content_source_id=attachment_content_source_id(content_hash),
                        content_hash=content_hash,
                        filename=first.filename,
                        mime_type=first.mime_type,
                        extraction_status=STATUS_MALFORMED,
                        document_status="failed",
                        occurrences=len(groups[content_hash]),
                        detail=_safe_error(exc),
                    )
                _count(report, result)
                report.results.append(result)
        return report

    # ------------------------------------------------------------ payloads

    def _ingest_payload(
        self,
        content_hash: str,
        new_occurrences: Sequence[AttachmentOccurrence],
        *,
        dry_run: bool,
        retry_failed: bool,
    ) -> AttachmentResult:
        content_source_id = attachment_content_source_id(content_hash)
        previous = self.registry.get(content_source_id) or {}
        occurrences = _merge_occurrences(previous.get("occurrences") or [], new_occurrences, self.registry)
        representative = _representative(occurrences)
        filename = representative["filename"] or "attachment"
        mime_type = representative["mime_type"]

        extraction = self._extraction_for(content_hash, representative, previous, retry_failed=retry_failed)
        document_id = previous.get("document_id", "")
        document_path_value = previous.get("document_path", "")
        document_status = "none"
        text_hash = previous.get("text_hash", "")
        now = self.now_fn()

        if extraction is None:
            # Unchanged extraction outcome from a previous run; only provenance may move.
            status = previous.get("extraction_status", STATUS_UNSUPPORTED)
            detail = previous.get("extraction_detail", "")
            extraction_meta = previous.get("extraction") or {}
        else:
            status = extraction.status
            detail = extraction.detail
            extraction_meta = extraction.to_dict()
            if extraction.extracted:
                text_hash = content_sha256(extraction.text.encode("utf-8"))

        manifest = {
            "source_type": ATTACHMENT_CONTENT_SOURCE_TYPE,
            "source_id": content_source_id,
            "content_hash": content_hash,
            "filename": filename,
            "mime_type": mime_type,
            "extraction": extraction_meta,
            "text_hash": text_hash if status == STATUS_EXTRACTED else "",
            "occurrences": occurrences,
        }
        manifest_hash = content_sha256(json.dumps(manifest, sort_keys=True).encode("utf-8"))
        existing_path = self.registry.resolve_path(document_path_value) if document_path_value else None

        if status == STATUS_EXTRACTED:
            unchanged = (
                previous.get("manifest_hash") == manifest_hash
                and existing_path is not None
                and existing_path.exists()
            )
            if unchanged:
                document_status = "unchanged"
            else:
                if extraction is None:
                    # Provenance changed but the text is already extracted; re-read
                    # the bytes rather than trusting a document we are about to rewrite.
                    extraction = self._extract(content_hash, representative)
                    if not extraction.extracted:
                        status, detail = extraction.status, extraction.detail
                if extraction.extracted:
                    document_status = "updated" if document_id and existing_path is not None else "created"
                    if not dry_run:
                        document_id = document_id or uuid7()
                        existing_path = self._write_document(
                            document_id=document_id,
                            content_source_id=content_source_id,
                            content_hash=content_hash,
                            representative=representative,
                            occurrences=occurrences,
                            extraction=extraction,
                            manifest=manifest,
                            created_at=previous.get("created_at") or now,
                            updated_at=now,
                            document_path=existing_path,
                        )
                        document_path_value = self.registry.relative_path(existing_path)

        if not dry_run:
            self._record(
                content_source_id=content_source_id,
                content_hash=content_hash,
                previous=previous,
                representative=representative,
                occurrences=occurrences,
                status=status,
                detail=detail,
                extraction_meta=extraction_meta,
                text_hash=text_hash if status == STATUS_EXTRACTED else "",
                manifest_hash=manifest_hash,
                document_id=document_id,
                document_path=document_path_value,
                now=now,
            )

        return AttachmentResult(
            content_source_id=content_source_id,
            content_hash=content_hash,
            filename=filename,
            mime_type=mime_type,
            extraction_status=status,
            document_status=document_status,
            occurrences=len(new_occurrences),
            document_id=document_id if status == STATUS_EXTRACTED else "",
            document_path=existing_path if status == STATUS_EXTRACTED else None,
            detail=detail,
            source_ids=[item["source_id"] for item in occurrences],
            thread_ids=sorted({item["gmail_thread_id"] for item in occurrences}),
        )

    def _extraction_for(
        self,
        content_hash: str,
        representative: Dict[str, Any],
        previous: Dict[str, Any],
        *,
        retry_failed: bool,
    ) -> Optional[Extraction]:
        """A fresh extraction, or ``None`` when the stored outcome still holds."""
        if previous and previous.get("extractor_version") == EXTRACTOR_VERSION:
            status = previous.get("extraction_status")
            retry = status in RETRYABLE_STATUSES or (retry_failed and status not in {STATUS_EXTRACTED, STATUS_UNSUPPORTED})
            if status and not retry:
                return None
        if extraction_kind(representative["mime_type"], representative["filename"]) is None and not _generic(
            representative["mime_type"]
        ):
            # Declared as a type we never read (images, calendars, archives):
            # no reason to load the bytes at all.
            return Extraction(STATUS_UNSUPPORTED, detail=f"no extractor for {representative['mime_type']}")
        return self._extract(content_hash, representative)

    def _extract(self, content_hash: str, representative: Dict[str, Any]) -> Extraction:
        payload = self.raw_store.read(representative["raw_ref"])
        actual = content_sha256(payload)
        if actual != content_hash:
            return Extraction(
                STATUS_MALFORMED,
                detail=f"raw bytes hash {actual[:12]} does not match recorded {content_hash[:12]}",
            )
        return extract_text(payload, mime_type=representative["mime_type"], filename=representative["filename"])

    # ------------------------------------------------------------- writing

    def _write_document(
        self,
        *,
        document_id: str,
        content_source_id: str,
        content_hash: str,
        representative: Dict[str, Any],
        occurrences: List[Dict[str, Any]],
        extraction: Extraction,
        manifest: Dict[str, Any],
        created_at: str,
        updated_at: str,
        document_path: Optional[Path],
    ) -> Path:
        self.attachments_path.mkdir(parents=True, exist_ok=True)
        # The filename is sender-controlled: one line, no markup.
        title = sanitize_extracted_text(re.sub(r"\s*[\r\n]+\s*", " ", representative["filename"] or "")) or "Attachment"
        if document_path is None:
            document_path = self.attachments_path / f"{document_id}-{slugify(title, 'attachment')}.md"
        received = sorted(item["received_at"] for item in occurrences if item.get("received_at"))
        thread_documents = sorted({item["thread_document_id"] for item in occurrences if item.get("thread_document_id")})
        frontmatter = {
            "id": document_id,
            "type": "document",
            "source_type": ATTACHMENT_SOURCE_TYPE,
            "title": title,
            "created": received[0] if received else created_at,
            "updated": received[-1] if received else updated_at,
            "created_at": created_at,
            "updated_at": updated_at,
            "visibility": "private",
            "status": "active",
            "content_trust": "untrusted",
            "people": [],
            "companies": [],
            "projects": [],
            "tags": [],
            "sources": [
                {"source_id": item["source_id"], "type": ATTACHMENT_SOURCE_TYPE, "raw_ref": item["raw_ref"]}
                for item in occurrences
            ],
            "source_id": content_source_id,
            "source_ids": [content_source_id, *[item["source_id"] for item in occurrences]],
            "related": thread_documents,
            "attachment": {
                "filename": title,
                "mime_type": representative["mime_type"],
                "content_hash": content_hash,
                "extraction": extraction.to_dict(),
                "occurrence_count": len(occurrences),
            },
            "content_hash": content_hash,
            "payload_hash": content_hash,
            "version": 1,
            "raw_ref": representative["raw_ref"],
            "provenance": {
                "source_id": content_source_id,
                "source_type": ATTACHMENT_SOURCE_TYPE,
                "raw_ref": representative["raw_ref"],
                "content_hash": content_hash,
                "extractor_version": EXTRACTOR_VERSION,
                "extraction_method": extraction.method,
                "occurrences": occurrences,
            },
            "ingestion_envelope": manifest,
        }
        frontmatter.update(preserved_entity_frontmatter(document_path))
        body = f"# {title}\n\n## Extracted Text\n\n{extraction.text.rstrip()}\n"
        frontmatter_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
        document_path.write_text(f"---\n{frontmatter_text}---\n\n{body}", encoding="utf-8")
        return document_path

    def _record(
        self,
        *,
        content_source_id: str,
        content_hash: str,
        previous: Dict[str, Any],
        representative: Dict[str, Any],
        occurrences: List[Dict[str, Any]],
        status: str,
        detail: str,
        extraction_meta: Dict[str, Any],
        text_hash: str,
        manifest_hash: str,
        document_id: str,
        document_path: str,
        now: str,
    ) -> None:
        created_at = previous.get("created_at") or now
        record = {
            "source_id": content_source_id,
            "adapter": ATTACHMENT_ADAPTER,
            "source_type": ATTACHMENT_CONTENT_SOURCE_TYPE,
            "source_name": representative["filename"],
            "mime_type": representative["mime_type"],
            "content_hash": content_hash,
            "raw_ref": representative["raw_ref"],
            "version": 1,
            "document_id": document_id,
            "document_path": document_path,
            "extraction_status": status,
            "extraction_detail": detail,
            "extraction": extraction_meta,
            "extractor_version": EXTRACTOR_VERSION,
            "text_hash": text_hash,
            "manifest_hash": manifest_hash,
            "occurrences": occurrences,
            "created_at": created_at,
            "updated_at": previous.get("updated_at", now) if previous.get("manifest_hash") == manifest_hash else now,
            "ingested_at": previous.get("ingested_at", now) if previous.get("manifest_hash") == manifest_hash else now,
        }
        if {key: value for key, value in previous.items() if key != "versions"} != record:
            self.registry.upsert(content_source_id, record, append_version=False)
        for item in occurrences:
            occurrence_record = {
                "source_id": item["source_id"],
                "adapter": ATTACHMENT_ADAPTER,
                "source_type": ATTACHMENT_SOURCE_TYPE,
                "source_name": item["filename"],
                "mime_type": item["mime_type"],
                "content_hash": content_hash,
                "raw_ref": item["raw_ref"],
                "version": 1,
                "gmail_message_id": item["gmail_message_id"],
                "gmail_thread_id": item["gmail_thread_id"],
                "thread_source_id": item["thread_source_id"],
                "part_id": item.get("part_id", ""),
                "received_at": item.get("received_at", ""),
                "source_account": item.get("source_account", ""),
                "content_source_id": content_source_id,
                "document_id": document_id,
                "document_path": document_path,
                "extraction_status": status,
            }
            existing = self.registry.get(item["source_id"]) or {}
            comparable = {key: value for key, value in existing.items() if key not in {"versions", "ingested_at", "created_at", "updated_at"}}
            if comparable != occurrence_record:
                self.registry.upsert(
                    item["source_id"],
                    {
                        **occurrence_record,
                        "created_at": existing.get("created_at") or now,
                        "updated_at": now,
                        "ingested_at": now,
                    },
                    append_version=False,
                )


# ------------------------------------------------------------------ discovery


def occurrences_from_thread_manifests(
    registry: IngestionRegistry,
    raw_store: RawStore,
    *,
    thread_ids: Optional[Sequence[str]] = None,
    since: Optional[str] = None,
    source_account: str = "",
) -> Iterable[AttachmentOccurrence]:
    """Every attachment Gmail ingestion has already put in raw custody.

    Reads each thread's latest manifest; manifests list every message in the
    thread, so older messages are covered too. ``since`` is an ISO date and
    filters by the message's received date.
    """
    wanted = {str(item) for item in thread_ids} if thread_ids else None
    for source_id, record in sorted(registry.all_sources().items()):
        if record.get("source_type") != "gmail-thread" or not record.get("raw_ref"):
            continue
        thread_id = str(record.get("gmail_thread_id") or "")
        if wanted is not None and thread_id not in wanted:
            continue
        try:
            manifest = json.loads(raw_store.read(record["raw_ref"]).decode("utf-8"))
        except Exception:  # noqa: BLE001 - an unreadable manifest is skipped, not fatal
            continue
        yield from occurrences_from_manifest(manifest, since=since, source_account=source_account)


def occurrences_from_manifest(
    manifest: Dict[str, Any],
    *,
    since: Optional[str] = None,
    source_account: str = "",
) -> Iterable[AttachmentOccurrence]:
    thread_id = str(manifest.get("gmail_thread_id") or "")
    for message in manifest.get("messages") or []:
        received_at = _iso_from_ms(message.get("internal_date_ms"))
        if since and received_at and received_at[:10] < since:
            continue
        for attachment in message.get("attachments") or []:
            content_hash = str(attachment.get("content_hash") or "")
            raw_ref = str(attachment.get("raw_ref") or "")
            if not content_hash or not raw_ref:
                continue
            yield AttachmentOccurrence(
                gmail_message_id=str(attachment.get("parent_gmail_message_id") or message.get("gmail_message_id") or ""),
                gmail_thread_id=str(message.get("gmail_thread_id") or thread_id),
                filename=str(attachment.get("filename") or ""),
                mime_type=str(attachment.get("mime_type") or "application/octet-stream"),
                content_hash=content_hash,
                raw_ref=raw_ref,
                received_at=received_at,
                source_account=str(attachment.get("source_account") or source_account or ""),
                part_id=str(attachment.get("part_id") or ""),
            )


# -------------------------------------------------------------------- helpers


def _merge_occurrences(
    previous: Sequence[Dict[str, Any]],
    new: Sequence[AttachmentOccurrence],
    registry: IngestionRegistry,
) -> List[Dict[str, Any]]:
    merged: Dict[str, Dict[str, Any]] = {
        str(item.get("source_id")): dict(item) for item in previous if isinstance(item, dict) and item.get("source_id")
    }
    for occurrence in new:
        entry = asdict(occurrence)
        entry.pop("content_hash", None)
        entry["source_id"] = occurrence.source_id
        entry["thread_source_id"] = occurrence.thread_source_id
        thread_record = registry.get(occurrence.thread_source_id) or {}
        entry["thread_document_id"] = str(thread_record.get("document_id") or "")
        earlier = merged.get(occurrence.source_id)
        if earlier:
            # Keep what an earlier run knew that this one does not (e.g. the
            # MIME part ID from a live sync, or the account).
            for key in ("part_id", "source_account", "thread_document_id", "received_at"):
                if not entry.get(key) and earlier.get(key):
                    entry[key] = earlier[key]
        merged[occurrence.source_id] = entry
    return sorted(merged.values(), key=lambda item: (item.get("received_at") or "", item["source_id"]))


def _representative(occurrences: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """The earliest occurrence whose declared type we can read, else the earliest."""
    for item in occurrences:
        if extraction_kind(item["mime_type"], item["filename"]) is not None:
            return item
    return occurrences[0]


def _ordered(occurrences: Sequence[AttachmentOccurrence]) -> List[AttachmentOccurrence]:
    return sorted(occurrences, key=lambda item: (item.received_at, item.source_id))


def _group_order(occurrences: Sequence[AttachmentOccurrence]) -> tuple:
    first = _ordered(occurrences)[0]
    return (first.received_at, first.source_id)


def _generic(mime_type: str) -> bool:
    return (mime_type or "").split(";", 1)[0].strip().casefold() in {"", "application/octet-stream", "binary/octet-stream"}


def _count(report: AttachmentReport, result: AttachmentResult) -> None:
    status = result.extraction_status
    if status == STATUS_EXTRACTED:
        report.extracted += 1
    elif status == STATUS_UNSUPPORTED:
        report.unsupported += 1
        report.unsupported_types[result.mime_type or "unknown"] += 1
    elif status == STATUS_REQUIRES_OCR:
        report.requires_ocr += 1
    else:
        report.failed += 1
    if result.document_status == "created":
        report.created += 1
    elif result.document_status == "updated":
        report.updated += 1
    elif result.document_status == "unchanged":
        report.unchanged += 1


def _iso_from_ms(value: Any) -> str:
    try:
        millis = int(value or 0)
    except (TypeError, ValueError):
        return ""
    if millis <= 0:
        return ""
    return datetime.fromtimestamp(millis / 1000, timezone.utc).isoformat()


def _safe_error(exc: Exception) -> str:
    return " ".join(str(exc).split())[:240] or exc.__class__.__name__
