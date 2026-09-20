"""Raw evidence storage for private ingestion."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from core.paths import GangPaths

from .ids import content_sha256, slugify


@dataclass(frozen=True)
class RawRecord:
    source_type: str
    source_id: str
    content_hash: str
    version: int
    raw_ref: str
    path: Path
    metadata: Dict[str, Any]


class RawStore(ABC):
    """Small interface around raw evidence storage."""

    @abstractmethod
    def put(
        self,
        source_type: str,
        source_id: str,
        payload: bytes,
        *,
        filename: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RawRecord:
        """Store immutable raw evidence and return its record."""

    @abstractmethod
    def exists(self, source_type: str, source_id: str, version: Optional[int] = None) -> bool:
        """Return whether a source/version exists."""

    @abstractmethod
    def read(self, raw_ref: str) -> bytes:
        """Read raw evidence by reference."""

    @abstractmethod
    def metadata(self, raw_ref: str) -> Dict[str, Any]:
        """Read raw evidence metadata by reference."""

    @abstractmethod
    def record(self, raw_ref: str) -> RawRecord:
        """Return a raw evidence record by reference."""


class LocalRawStore(RawStore):
    """Filesystem-backed raw store rooted in GANG_HOME by default."""

    def __init__(self, root: Path | str | None = None):
        self.root = Path(root) if root is not None else GangPaths.from_env().raw_path

    def put(
        self,
        source_type: str,
        source_id: str,
        payload: bytes,
        *,
        filename: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> RawRecord:
        self.root.mkdir(parents=True, exist_ok=True)
        source_dir = self._confined_path(slugify(source_type, "source"), source_id)
        source_dir.mkdir(parents=True, exist_ok=True)

        digest = content_sha256(payload)
        existing = self._record_for_hash(source_dir, digest)
        if existing:
            return existing

        version = self._next_version(source_dir)
        version_dir = source_dir / f"v{version:06d}"
        version_dir.mkdir(exist_ok=False)

        safe_name = slugify(Path(filename or "payload").stem, "payload") + Path(filename or ".bin").suffix
        payload_path = version_dir / safe_name
        with payload_path.open("xb") as payload_file:
            payload_file.write(payload)

        now = datetime.now(timezone.utc).isoformat()
        record_metadata = {
            "source_type": source_type,
            "source_id": source_id,
            "content_hash": digest,
            "version": version,
            "stored_at": now,
            "filename": filename,
            "payload_path": payload_path.name,
            "metadata": metadata or {},
        }
        (version_dir / "metadata.json").write_text(
            json.dumps(record_metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

        return self._record_from_metadata(version_dir / "metadata.json")

    def exists(self, source_type: str, source_id: str, version: Optional[int] = None) -> bool:
        source_dir = self._confined_path(slugify(source_type, "source"), source_id)
        if version is None:
            return source_dir.exists()
        return (source_dir / f"v{version:06d}").exists()

    def read(self, raw_ref: str) -> bytes:
        metadata_path = self._metadata_path_from_ref(raw_ref)
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        return (metadata_path.parent / data["payload_path"]).read_bytes()

    def metadata(self, raw_ref: str) -> Dict[str, Any]:
        metadata_path = self._metadata_path_from_ref(raw_ref)
        return json.loads(metadata_path.read_text(encoding="utf-8"))

    def record(self, raw_ref: str) -> RawRecord:
        return self._record_from_metadata(self._metadata_path_from_ref(raw_ref))

    def _record_for_hash(self, source_dir: Path, digest: str) -> Optional[RawRecord]:
        for metadata_path in sorted(source_dir.glob("v*/metadata.json")):
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
            if data.get("content_hash") == digest:
                return self._record_from_metadata(metadata_path)
        return None

    def _next_version(self, source_dir: Path) -> int:
        versions = []
        for child in source_dir.iterdir():
            if child.is_dir() and child.name.startswith("v"):
                try:
                    versions.append(int(child.name[1:]))
                except ValueError:
                    continue
        return max(versions, default=0) + 1

    def _record_from_metadata(self, metadata_path: Path) -> RawRecord:
        data = json.loads(metadata_path.read_text(encoding="utf-8"))
        payload_path = metadata_path.parent / data["payload_path"]
        raw_ref = self._ref_for_payload(payload_path)
        return RawRecord(
            source_type=data["source_type"],
            source_id=data["source_id"],
            content_hash=data["content_hash"],
            version=int(data["version"]),
            raw_ref=raw_ref,
            path=payload_path,
            metadata=data,
        )

    def _ref_for_payload(self, payload_path: Path) -> str:
        rel_path = payload_path.resolve().relative_to(self.root.resolve())
        return f"local://{rel_path.as_posix()}"

    def _metadata_path_from_ref(self, raw_ref: str) -> Path:
        if not raw_ref.startswith("local://"):
            raise ValueError(f"Unsupported raw_ref: {raw_ref}")
        payload_path = Path(raw_ref.removeprefix("local://"))
        if payload_path.is_absolute() or ".." in payload_path.parts:
            raise ValueError(f"Unsafe raw_ref: {raw_ref}")
        payload_path = self._confined_path(*payload_path.parts)
        metadata_path = payload_path.parent / "metadata.json"
        if not metadata_path.exists():
            raise FileNotFoundError(f"Missing raw metadata for {raw_ref}")
        return metadata_path

    def _confined_path(self, *parts: str) -> Path:
        root = self.root.resolve()
        candidate = (self.root.joinpath(*parts)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"Path escapes raw store: {candidate}") from exc
        return candidate
