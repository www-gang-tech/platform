"""Private ingestion registry."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from core.paths import GangPaths


class IngestionRegistry:
    """Durable map from source identity to canonical private knowledge docs."""

    def __init__(self, path: Path | str | None = None, *, root_path: Path | str | None = None):
        paths = GangPaths.from_env()
        self.path = Path(path) if path is not None else paths.registry_path
        self.root_path = Path(root_path) if root_path is not None else self._infer_root_path(self.path)

    def get(self, source_id: str) -> Optional[Dict[str, Any]]:
        return self._load()["sources"].get(source_id)

    def all_sources(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._load()["sources"])

    def upsert(
        self,
        source_id: str,
        record: Dict[str, Any],
        *,
        append_version: bool = True,
        version_record: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        data = self._load()
        previous = data["sources"].get(source_id)
        versions = list(previous.get("versions", [])) if previous else []
        if append_version:
            entry = version_record or {
                "version": record["version"],
                "content_hash": record["content_hash"],
                "raw_ref": record["raw_ref"],
                "ingested_at": record["ingested_at"],
            }
            if not _has_version_record(versions, entry):
                versions.append(entry)
        data["sources"][source_id] = {**record, "versions": versions}
        self._save(data)
        return data["sources"][source_id]

    def replace(self, source_id: str, record: Dict[str, Any]) -> Dict[str, Any]:
        data = self._load()
        data["sources"][source_id] = record
        self._save(data)
        return data["sources"][source_id]

    def remove(self, source_id: str) -> None:
        data = self._load()
        if source_id in data["sources"]:
            del data["sources"][source_id]
            self._save(data)

    def relative_path(self, path: Path) -> str:
        try:
            return path.resolve().relative_to(self.root_path.resolve()).as_posix()
        except ValueError:
            return path.as_posix()

    def resolve_path(self, path_value: str) -> Path:
        path = Path(path_value)
        if path.is_absolute():
            return path
        return self.root_path / path

    def _load(self) -> Dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "sources": {}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if "sources" not in data or not isinstance(data["sources"], dict):
            raise ValueError(f"Invalid ingestion registry: {self.path}")
        return data

    def _save(self, data: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp_path.replace(self.path)

    @staticmethod
    def _infer_root_path(path: Path) -> Path:
        # Current default: <GANG_HOME>/ingestion/registry.json
        if path.name == "registry.json" and path.parent.name == "ingestion":
            return path.parent.parent
        # Legacy default: <root>/brain/vault/.ingestion/registry.json
        if len(path.parents) >= 4:
            return path.parents[3]
        return Path(".")


def _has_version_record(versions: list[Dict[str, Any]], entry: Dict[str, Any]) -> bool:
    for previous in versions:
        previous_version = previous.get("raw_version", previous.get("version"))
        entry_version = entry.get("raw_version", entry.get("version"))
        previous_hash = previous.get("payload_hash", previous.get("content_hash"))
        entry_hash = entry.get("payload_hash", entry.get("content_hash"))
        if (
            previous.get("raw_ref") == entry.get("raw_ref")
            and previous_version == entry_version
            and previous_hash == entry_hash
        ):
            return True
    return False
