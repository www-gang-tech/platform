"""Status and migration helpers for durable private brain home."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

from core.paths import GangPaths


PRIVATE_VAULT_DIRS = {
    "inbox",
    "meetings",
    "emails",
    "conversations",
    "people",
    "companies",
    "projects",
    "research",
    "documents",
}


@dataclass(frozen=True)
class MigrationItem:
    source: Path
    destination: Path
    kind: str
    status: str
    payload: bytes | None = None


class BrainHome:
    def __init__(self, *, repo_root: Path | str = Path("."), private_home: Path | str | None = None):
        self.paths = GangPaths.from_env(repo_root=repo_root, gang_home=private_home)

    def status(self) -> Dict[str, Any]:
        registry = _load_registry(self.paths.registry_path)
        gmail_threads = [
            record
            for record in registry.get("sources", {}).values()
            if record.get("source_type") == "gmail-thread" or record.get("adapter") == "GmailSyncService"
        ]
        return {
            "private_home": self.paths.display_home(),
            "private_home_path": self.paths.home,
            "private_documents": _count_markdown(self.paths.private_vault),
            "raw_sources": _count_raw_sources(self.paths.raw_path),
            "gmail_threads": len(gmail_threads),
            "generated_index": self.paths.index_path,
            "generated_index_exists": self.paths.index_path.exists(),
            "repository_public_documents": _count_markdown(self.paths.repo_public_vault),
        }

    def plan_migration(self, source_root: Path | str | None = None) -> Dict[str, Any]:
        source_root = Path(source_root).resolve() if source_root else self.paths.repo_root
        items = list(_migration_items(source_root, self.paths))
        conflicts = [item for item in items if item.status == "conflict"]
        return {
            "source_root": source_root,
            "private_home": self.paths.home,
            "items": items,
            "conflicts": conflicts,
            "will_copy": [item for item in items if item.status == "copy"],
            "unchanged": [item for item in items if item.status == "unchanged"],
        }

    def migrate(self, *, source_root: Path | str | None = None, apply: bool = False) -> Dict[str, Any]:
        plan = self.plan_migration(source_root)
        if plan["conflicts"]:
            return {**plan, "applied": False}
        if apply:
            for item in plan["will_copy"]:
                item.destination.parent.mkdir(parents=True, exist_ok=True)
                if item.kind == "registry":
                    item.destination.write_bytes(item.payload or _registry_payload(item.source))
                    shutil.copystat(item.source, item.destination)
                else:
                    shutil.copy2(item.source, item.destination)
        return {**plan, "applied": apply}


def _migration_items(source_root: Path, paths: GangPaths) -> Iterable[MigrationItem]:
    vault_root = source_root / "brain/vault"
    for dirname in sorted(PRIVATE_VAULT_DIRS):
        source_dir = vault_root / dirname
        if source_dir.exists():
            yield from _copy_tree_items(source_dir, paths.private_vault / dirname, "document")

    raw_root = source_root / "brain/raw"
    if raw_root.exists():
        yield from _copy_tree_items(raw_root, paths.raw_path, "raw")

    blobs_root = source_root / "brain/blobs"
    if blobs_root.exists():
        yield from _copy_tree_items(blobs_root, paths.blobs_path, "blob")

    ingestion_root = vault_root / ".ingestion"
    if ingestion_root.exists():
        registry = ingestion_root / "registry.json"
        for source in sorted(path for path in ingestion_root.rglob("*") if _migratable_file(path)):
            rel = source.relative_to(ingestion_root)
            kind = "registry" if source == registry else "ingestion"
            destination = paths.ingestion_path / rel
            if kind == "registry":
                payload = _registry_payload(source)
                yield _migration_item(source, destination, kind, payload=payload)
            else:
                yield _migration_item(source, destination, kind)

    enrichment_root = source_root / "brain/generated/enrichment"
    if enrichment_root.exists():
        yield from _copy_tree_items(enrichment_root, paths.enrichment_path, "enrichment")


def _copy_tree_items(source_root: Path, destination_root: Path, kind: str) -> Iterable[MigrationItem]:
    for source in sorted(path for path in source_root.rglob("*") if _migratable_file(path)):
        yield _migration_item(source, destination_root / source.relative_to(source_root), kind)


def _migratable_file(path: Path) -> bool:
    return path.is_file() and path.name != ".gitkeep"


def _migration_item(source: Path, destination: Path, kind: str, payload: bytes | None = None) -> MigrationItem:
    if destination.exists():
        source_hash = _sha256_bytes(payload) if payload is not None else _sha256_file(source)
        status = "unchanged" if source_hash == _sha256_file(destination) else "conflict"
    else:
        status = "copy"
    return MigrationItem(source=source, destination=destination, kind=kind, status=status, payload=payload)


def _registry_payload(source: Path) -> bytes:
    data = _rewrite_registry_paths(json.loads(source.read_text(encoding="utf-8")))
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _rewrite_registry_paths(data: Dict[str, Any]) -> Dict[str, Any]:
    sources = data.get("sources")
    if not isinstance(sources, dict):
        return data
    for record in sources.values():
        if not isinstance(record, dict):
            continue
        document_path = record.get("document_path")
        if isinstance(document_path, str) and document_path.startswith("brain/vault/"):
            parts = Path(document_path).parts
            if len(parts) >= 3 and parts[2] != "public":
                record["document_path"] = Path("vault").joinpath(*parts[2:]).as_posix()
    return data


def _load_registry(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"version": 1, "sources": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"version": 1, "sources": {}}
    return data if isinstance(data, dict) else {"version": 1, "sources": {}}


def _count_markdown(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(1 for path in root.rglob("*.md") if not any(part.startswith(".") for part in path.relative_to(root).parts))


def _count_raw_sources(root: Path) -> int:
    if not root.exists():
        return 0
    return sum(1 for path in root.rglob("metadata.json"))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
