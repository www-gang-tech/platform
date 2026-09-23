"""Answer "where did this come from, and is it still true to its source?"

Given a canonical document ID (or an evidence fact that cites one), report:

* the original source — the Gmail attachment and every message and thread
  it arrived in, or the Drive file with its folder and revision;
* the raw evidence reference for the original bytes;
* whether those bytes still hash to what was recorded at extraction, and
  whether the extraction was made by the current extractor.

Read-only. It never modifies raw evidence, the registry, or the vault.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from core.paths import GangPaths

from .extract import EXTRACTOR_VERSION
from .ids import content_sha256
from .raw_store import RawStore
from .registry import IngestionRegistry


class ProvenanceError(Exception):
    """Raised when a document cannot be located."""


def locate_document(document_id: str, *, paths: GangPaths, registry: IngestionRegistry) -> Path:
    """The canonical file for a document ID, via the registry, then the vault."""
    for record in registry.all_sources().values():
        if record.get("document_id") == document_id and record.get("document_path"):
            candidate = registry.resolve_path(record["document_path"])
            if candidate.exists():
                return candidate
    # Ingestion names canonical files ``{document_id}-{slug}.md``.
    matches = sorted(paths.private_vault.rglob(f"{document_id}-*.md")) if paths.private_vault.exists() else []
    if matches:
        return matches[0]
    raise ProvenanceError(f"No canonical document with ID {document_id}")


def document_provenance(
    document_id: str,
    *,
    paths: GangPaths,
    registry: IngestionRegistry,
    raw_store: RawStore,
    drive_provider: Any = None,
) -> Dict[str, Any]:
    path = locate_document(document_id, paths=paths, registry=registry)
    frontmatter = _frontmatter(path)
    source_type = str(frontmatter.get("source_type") or "")
    report: Dict[str, Any] = {
        "document_id": str(frontmatter.get("id") or document_id),
        "title": frontmatter.get("title"),
        "path": str(path),
        "source_type": source_type,
        "source_id": frontmatter.get("source_id"),
        "raw_ref": frontmatter.get("raw_ref"),
        "content_hash": frontmatter.get("content_hash"),
        "content_trust": frontmatter.get("content_trust"),
    }
    if source_type == "gmail-attachment":
        report.update(_attachment_provenance(frontmatter, registry=registry, raw_store=raw_store))
    elif source_type == "drive-file":
        report.update(_drive_provenance(frontmatter, registry=registry, raw_store=raw_store, drive_provider=drive_provider))
    elif source_type == "gmail-thread":
        report.update(_thread_provenance(frontmatter, raw_store=raw_store))
    else:
        report["raw_integrity"] = _verify(raw_store, frontmatter.get("raw_ref"), frontmatter.get("content_hash"))
    report["source_changed"] = _source_changed(report)
    return report


# ----------------------------------------------------------------- sources


def _attachment_provenance(frontmatter: Dict[str, Any], *, registry: IngestionRegistry, raw_store: RawStore) -> Dict[str, Any]:
    provenance = frontmatter.get("provenance") or {}
    attachment = frontmatter.get("attachment") or {}
    content_hash = frontmatter.get("content_hash")
    occurrences: List[Dict[str, Any]] = []
    for item in provenance.get("occurrences") or []:
        thread = registry.get(str(item.get("thread_source_id") or "")) or {}
        occurrences.append(
            {
                "attachment_source_id": item.get("source_id"),
                "filename": item.get("filename"),
                "mime_type": item.get("mime_type"),
                "part_id": item.get("part_id") or "",
                "gmail_message_id": item.get("gmail_message_id"),
                "gmail_thread_id": item.get("gmail_thread_id"),
                "thread_subject": thread.get("source_name") or "",
                "thread_document_id": item.get("thread_document_id") or thread.get("document_id") or "",
                "thread_document_path": thread.get("document_path") or "",
                "received_at": item.get("received_at"),
                "source_account": item.get("source_account") or "",
                "raw_ref": item.get("raw_ref"),
                "raw_integrity": _verify(raw_store, item.get("raw_ref"), content_hash),
            }
        )
    extraction = attachment.get("extraction") or {}
    return {
        "origin": "gmail-attachment",
        "filename": attachment.get("filename"),
        "mime_type": attachment.get("mime_type"),
        "extraction": extraction,
        "extraction_current": extraction.get("extractor_version") == EXTRACTOR_VERSION,
        "occurrences": occurrences,
        "raw_integrity": _verify(raw_store, frontmatter.get("raw_ref"), content_hash),
    }


def _drive_provenance(
    frontmatter: Dict[str, Any],
    *,
    registry: IngestionRegistry,
    raw_store: RawStore,
    drive_provider: Any,
) -> Dict[str, Any]:
    drive = frontmatter.get("drive") or {}
    provenance = frontmatter.get("provenance") or {}
    envelope = frontmatter.get("ingestion_envelope") or {}
    extraction = (envelope.get("normalization") or {}).get("extraction") or {}
    record = registry.get(str(frontmatter.get("source_id") or "")) or {}
    payload_hash = frontmatter.get("payload_hash") or frontmatter.get("content_hash")
    report: Dict[str, Any] = {
        "origin": "drive-file",
        "drive_file_id": drive.get("drive_file_id"),
        "name": drive.get("original_name"),
        "mime_type": drive.get("mime_type"),
        "folder_path": drive.get("folder_path") or "",
        "source_url": drive.get("source_url"),
        "modified_time": drive.get("modified_time"),
        "source_version": provenance.get("source_version") or drive.get("source_version"),
        "extraction": extraction,
        "extraction_current": (not extraction) or extraction.get("extractor_version") == EXTRACTOR_VERSION,
        "raw_integrity": _verify(raw_store, frontmatter.get("raw_ref"), payload_hash),
        "newer_revision_ingested": bool(record) and (record.get("payload_hash") or record.get("content_hash")) != payload_hash,
    }
    if drive_provider is not None and drive.get("drive_file_id"):
        try:
            current = drive_provider.get_file(drive["drive_file_id"])
        except Exception as exc:  # noqa: BLE001 - remote check is advisory
            report["remote"] = {"checked": False, "error": " ".join(str(exc).split())[:200]}
        else:
            current_version = current.head_revision_id or current.version or current.md5_checksum
            report["remote"] = {
                "checked": True,
                "current_version": current_version,
                "current_modified_time": current.modified_time,
                "trashed": current.trashed,
                "changed": str(current_version) != str(report["source_version"] or ""),
            }
    return report


def _thread_provenance(frontmatter: Dict[str, Any], *, raw_store: RawStore) -> Dict[str, Any]:
    provenance = frontmatter.get("provenance") or {}
    messages = []
    for item in provenance.get("messages") or []:
        messages.append(
            {
                "gmail_message_id": item.get("gmail_message_id"),
                "raw_ref": item.get("raw_ref"),
                "raw_integrity": _verify(raw_store, item.get("raw_ref"), None),
            }
        )
    return {
        "origin": "gmail-thread",
        "gmail_thread_id": provenance.get("gmail_thread_id"),
        "messages": messages,
        "raw_integrity": _verify(raw_store, frontmatter.get("raw_ref"), frontmatter.get("content_hash")),
    }


# ------------------------------------------------------------------ helpers


def _verify(raw_store: RawStore, raw_ref: Optional[str], expected_hash: Optional[str]) -> Dict[str, Any]:
    """Re-hash raw evidence. ``expected_hash`` falls back to the raw record's own."""
    if not raw_ref:
        return {"status": "no-raw-ref"}
    try:
        payload = raw_store.read(str(raw_ref))
        recorded = raw_store.metadata(str(raw_ref)).get("content_hash")
    except FileNotFoundError:
        return {"status": "missing"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "unreadable", "error": " ".join(str(exc).split())[:200]}
    actual = content_sha256(payload)
    expected = expected_hash or recorded
    return {
        "status": "intact" if actual == expected and actual == recorded else "mismatch",
        "sha256": actual,
        "expected": expected,
    }


def _source_changed(report: Dict[str, Any]) -> bool:
    checks = [report.get("raw_integrity") or {}]
    checks.extend(item.get("raw_integrity") or {} for item in report.get("occurrences") or [])
    if any(check.get("status") not in {None, "intact", "no-raw-ref"} for check in checks):
        return True
    if report.get("newer_revision_ingested"):
        return True
    return bool((report.get("remote") or {}).get("changed"))


def _frontmatter(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    data = yaml.safe_load(parts[1]) or {}
    return data if isinstance(data, dict) else {}
