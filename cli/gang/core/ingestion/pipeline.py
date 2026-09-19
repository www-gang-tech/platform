"""Private ingestion pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import yaml

from .adapters import SourceAdapter
from .ids import slugify, uuid7
from .raw_store import RawRecord, RawStore


@dataclass(frozen=True)
class IngestionResult:
    document_id: str
    document_path: Path
    raw_record: RawRecord
    source_id: str
    content_hash: str
    version: int


class IngestionPipeline:
    """Coordinates source adapters, raw evidence storage, and private markdown output."""

    def __init__(
        self,
        raw_store: RawStore,
        *,
        inbox_path: Path | str = Path("brain/vault/inbox"),
    ):
        self.raw_store = raw_store
        self.inbox_path = Path(inbox_path)

    def ingest(self, adapter: SourceAdapter) -> List[IngestionResult]:
        results = []
        for source in adapter.discover():
            identity = adapter.identify(source)
            fetched = adapter.fetch(identity)
            raw_record = self.raw_store.put(
                identity.source_type,
                identity.source_id,
                fetched.payload,
                filename=fetched.filename,
                metadata=identity.metadata,
            )
            normalized = adapter.normalize(fetched)
            document_id = uuid7()
            now = datetime.now(timezone.utc).isoformat()
            envelope = {
                "source": identity.source,
                "source_type": identity.source_type,
                "source_id": identity.source_id,
                "source_url": identity.source_url,
                "created_at": now,
                "updated_at": now,
                "participants": normalized.participants,
                "attachments": normalized.attachments,
                "raw_ref": raw_record.raw_ref,
                "content_hash": raw_record.content_hash,
                "version": raw_record.version,
                "metadata": normalized.metadata,
            }
            document_path = self._write_document(
                document_id=document_id,
                title=normalized.title,
                body=normalized.body,
                source_type=identity.source_type,
                raw_record=raw_record,
                envelope=envelope,
                created_at=now,
                updated_at=now,
            )
            results.append(
                IngestionResult(
                    document_id=document_id,
                    document_path=document_path,
                    raw_record=raw_record,
                    source_id=identity.source_id,
                    content_hash=raw_record.content_hash,
                    version=raw_record.version,
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
    ) -> Path:
        self.inbox_path.mkdir(parents=True, exist_ok=True)
        frontmatter = {
            "id": document_id,
            "type": "knowledge",
            "source_type": source_type,
            "title": title,
            "visibility": "private",
            "status": "active",
            "created_at": created_at,
            "updated_at": updated_at,
            "source_id": raw_record.source_id,
            "content_hash": raw_record.content_hash,
            "version": raw_record.version,
            "raw_ref": raw_record.raw_ref,
            "ingestion_envelope": envelope,
        }
        frontmatter_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
        filename = f"{document_id}-{slugify(title)}.md"
        document_path = self.inbox_path / filename
        document_path.write_text(f"---\n{frontmatter_text}---\n\n{body}", encoding="utf-8")
        return document_path
