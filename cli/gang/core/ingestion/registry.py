"""Private ingestion registry."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


class IngestionRegistry:
    """Durable map from source identity to canonical private knowledge docs."""

    def __init__(self, path: Path | str = Path("brain/vault/.ingestion/registry.json"), *, root_path: Path | str | None = None):
        self.path = Path(path)
        self.root_path = Path(root_path) if root_path is not None else self._infer_root_path(self.path)

    def get(self, source_id: str) -> Optional[Dict[str, Any]]:
        return self._load()["sources"].get(source_id)

    def all_sources(self) -> Dict[str, Dict[str, Any]]:
        return dict(self._load()["sources"])

    def upsert(self, source_id: str, record: Dict[str, Any]) -> Dict[str, Any]:
        data = self._load()
        previous = data["sources"].get(source_id)
        versions = list(previous.get("versions", [])) if previous else []
        versions.append(
            {
                "version": record["version"],
                "content_hash": record["content_hash"],
                "raw_ref": record["raw_ref"],
                "ingested_at": record["ingested_at"],
            }
        )
        data["sources"][source_id] = {**record, "versions": versions}
        self._save(data)
        return data["sources"][source_id]

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
        # Expected default: <root>/brain/vault/.ingestion/registry.json
        if len(path.parents) >= 4:
            return path.parents[3]
        return Path(".")
