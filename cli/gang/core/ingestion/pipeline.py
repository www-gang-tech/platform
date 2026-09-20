"""Private ingestion pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import yaml

from core.entities.documents import preserved_entity_frontmatter
from core.paths import GangPaths

from .adapters import SourceAdapter
from .ids import content_sha256, slugify, uuid7
from .raw_store import RawRecord, RawStore
from .registry import IngestionRegistry


@dataclass(frozen=True)
class IngestionResult:
    document_id: str
    document_path: Path
    raw_record: RawRecord
    source_id: str
    content_hash: str
    version: int
    status: str


class IngestionPipeline:
    """Coordinates source adapters, raw evidence storage, and private markdown output."""

    def __init__(
        self,
        raw_store: RawStore,
        *,
        inbox_path: Path | str | None = None,
        meetings_path: Path | str | None = None,
        registry: IngestionRegistry | None = None,
    ):
        paths = GangPaths.from_env()
        default_private_paths = inbox_path is None
        self.raw_store = raw_store
        self.inbox_path = Path(inbox_path) if inbox_path is not None else paths.inbox_path
        self.meetings_path = Path(meetings_path) if meetings_path else self.inbox_path.parent / "meetings"
        if registry is not None:
            self.registry = registry
        elif default_private_paths:
            self.registry = IngestionRegistry(paths.registry_path, root_path=paths.home)
        else:
            self.registry = IngestionRegistry(self.inbox_path.parent / ".ingestion" / "registry.json")

    def ingest(self, adapter: SourceAdapter) -> List[IngestionResult]:
        results = []
        for source in adapter.discover():
            identity = adapter.identify(source)
            fetched = adapter.fetch(identity)
            digest = content_sha256(fetched.payload)
            previous = self.registry.get(identity.source_id)

            if previous and previous.get("content_hash") == digest:
                raw_record = self.raw_store.record(previous["raw_ref"])
                results.append(
                    IngestionResult(
                        document_id=previous["document_id"],
                        document_path=self.registry.resolve_path(previous["document_path"]),
                        raw_record=raw_record,
                        source_id=identity.source_id,
                        content_hash=digest,
                        version=int(previous["version"]),
                        status="unchanged",
                    )
                )
                continue

            raw_record = self.raw_store.put(
                identity.source_type,
                identity.source_id,
                fetched.payload,
                filename=fetched.filename,
                metadata=identity.metadata,
            )
            normalized = adapter.normalize(fetched)
            document_id = previous["document_id"] if previous else uuid7()
            now = datetime.now(timezone.utc).isoformat()
            created_at = previous.get("created_at", now) if previous else now
            envelope = {
                "source_type": identity.source_type,
                "source_id": identity.source_id,
                "source_ref": identity.source_url,
                "source_name": fetched.filename,
                "created_at": created_at,
                "updated_at": now,
                "participants": normalized.participants,
                "attachments": normalized.attachments,
                "raw_ref": raw_record.raw_ref,
                "content_hash": raw_record.content_hash,
                "version": raw_record.version,
                "metadata": normalized.metadata,
            }
            existing_document_path = self.registry.resolve_path(previous["document_path"]) if previous else None
            document_path = self._write_document(
                document_id=document_id,
                title=normalized.title,
                body=normalized.body,
                source_type=identity.source_type,
                raw_record=raw_record,
                envelope=envelope,
                created_at=created_at,
                updated_at=now,
                document_path=existing_document_path,
            )
            self.registry.upsert(
                identity.source_id,
                {
                    "source_id": identity.source_id,
                    "adapter": normalized.metadata.get("adapter", adapter.__class__.__name__),
                    "source_type": identity.source_type,
                    "source_name": fetched.filename,
                    "content_hash": raw_record.content_hash,
                    "version": raw_record.version,
                    "document_id": document_id,
                    "document_path": self.registry.relative_path(document_path),
                    "raw_ref": raw_record.raw_ref,
                    "ingested_at": now,
                    "created_at": created_at,
                    "updated_at": now,
                },
            )
            results.append(
                IngestionResult(
                    document_id=document_id,
                    document_path=document_path,
                    raw_record=raw_record,
                    source_id=identity.source_id,
                    content_hash=raw_record.content_hash,
                    version=raw_record.version,
                    status="updated" if previous else "created",
                )
            )
        return results

    def _write_document(
        self,
        *,
        document_id: str,
        title: str,
        body: str,
        source_type: str,
        raw_record: RawRecord,
        envelope: Dict[str, Any],
        created_at: str,
        updated_at: str,
        document_path: Path | None = None,
    ) -> Path:
        destination_path = self.meetings_path if source_type == "meeting" else self.inbox_path
        destination_path.mkdir(parents=True, exist_ok=True)
        frontmatter = {
            "id": document_id,
            "type": _canonical_document_type(source_type),
            "source_type": source_type,
            "title": title,
            "visibility": "private",
            "status": "active",
            "content_trust": "untrusted",
            "created_at": created_at,
            "updated_at": updated_at,
            "source_id": raw_record.source_id,
            "content_hash": raw_record.content_hash,
            "version": raw_record.version,
            "raw_ref": raw_record.raw_ref,
            "provenance": {
                "source_id": raw_record.source_id,
                "source_type": source_type,
                "raw_ref": raw_record.raw_ref,
                "content_hash": raw_record.content_hash,
                "version": raw_record.version,
            },
            "ingestion_envelope": envelope,
        }
        if document_path is None:
            filename = f"{document_id}-{slugify(title)}.md"
            document_path = destination_path / filename
        frontmatter.update(preserved_entity_frontmatter(document_path))
        frontmatter_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
        document_path.parent.mkdir(parents=True, exist_ok=True)
        document_path.write_text(f"---\n{frontmatter_text}---\n\n{body}", encoding="utf-8")
        return document_path


def _canonical_document_type(source_type: str) -> str:
    return "meeting" if source_type == "meeting" else "knowledge"
