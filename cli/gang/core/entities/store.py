"""Canonical entity records on disk under GANG_HOME.

The Markdown file is authoritative. SQLite is a disposable index rebuilt from
these files, so every mutation here writes canonical Markdown first.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from core.paths import GangPaths

from .model import (
    ENTITY_DIRECTORIES,
    ENTITY_TYPES,
    AliasCollisionError,
    DuplicateEntityError,
    EntityNotFoundError,
    EntityRecord,
    EntityValidationError,
    MergeConflictError,
    is_entity_frontmatter,
    normalize_domain,
    normalize_email,
    normalize_name,
    now_iso,
    parse_markdown,
    string_value,
    validate_entity,
    validate_entity_type,
)


class EntityStore:
    """Create, read, and safely mutate canonical entity records."""

    def __init__(
        self,
        *,
        root_path: Path | str = Path("."),
        private_home: Path | str | None = None,
        vault_path: Path | str | None = None,
    ):
        self.root_path = Path(root_path).resolve()
        self.paths = GangPaths.from_env(repo_root=self.root_path, gang_home=private_home)
        self.vault_path = Path(vault_path).resolve() if vault_path else self.paths.private_vault
        self.audit_path = self.paths.entities_generated_path / "audit.jsonl"

    # ------------------------------------------------------------------ read

    def directory_for(self, entity_type: str) -> Path:
        return self.vault_path / ENTITY_DIRECTORIES[validate_entity_type(entity_type)]

    def load_all(self) -> List[EntityRecord]:
        records: List[EntityRecord] = []
        seen: Dict[str, Path] = {}
        for entity_type in ENTITY_TYPES:
            directory = self.vault_path / ENTITY_DIRECTORIES[entity_type]
            if not directory.exists():
                continue
            for path in sorted(directory.rglob("*.md")):
                if any(part.startswith(".") for part in path.relative_to(directory).parts):
                    continue
                frontmatter, body = parse_markdown(path.read_text(encoding="utf-8"))
                if not is_entity_frontmatter(frontmatter):
                    continue
                record = EntityRecord.from_frontmatter(frontmatter, body, path)
                if record.id in seen:
                    raise EntityValidationError(
                        f"Duplicate entity id {record.id}: {seen[record.id]} and {path}"
                    )
                seen[record.id] = path
                records.append(record)
        return sorted(records, key=lambda record: (record.type, record.normalized_name, record.id))

    def list(self, *, entity_type: Optional[str] = None, include_merged: bool = False) -> List[EntityRecord]:
        wanted = validate_entity_type(entity_type) if entity_type else None
        return [
            record
            for record in self.load_all()
            if (wanted is None or record.type == wanted)
            and (include_merged or record.status == "active")
        ]

    def get(self, entity_id: str) -> EntityRecord:
        entity_id = string_value(entity_id)
        for record in self.load_all():
            if record.id == entity_id:
                return record
        raise EntityNotFoundError(f"Entity not found: {entity_id}")

    def try_get(self, entity_id: str) -> Optional[EntityRecord]:
        try:
            return self.get(entity_id)
        except EntityNotFoundError:
            return None

    def follow_merges(self, entity_id: str, *, _depth: int = 0) -> EntityRecord:
        """Resolve a tombstone to its surviving target."""
        record = self.get(entity_id)
        if record.status != "merged" or not record.merged_into:
            return record
        if _depth > 16:
            raise MergeConflictError(f"Merge chain for {entity_id} is cyclic")
        return self.follow_merges(record.merged_into, _depth=_depth + 1)

    # ----------------------------------------------------------------- write

    def create(
        self,
        entity_type: str,
        name: str,
        *,
        aliases: Iterable[str] = (),
        emails: Iterable[str] = (),
        domains: Iterable[str] = (),
        sources: Iterable[Dict[str, Any]] = (),
        allow_duplicate_name: bool = False,
        allow_ambiguous_alias: bool = False,
        entity_id: Optional[str] = None,
    ) -> EntityRecord:
        entity_type = validate_entity_type(entity_type)
        name = string_value(name)
        if not name:
            raise EntityValidationError("Entity name is required")

        existing = self.load_all()
        normalized = normalize_name(name)
        if not allow_duplicate_name:
            clashes = [
                record.id
                for record in existing
                if record.type == entity_type
                and record.status == "active"
                and record.normalized_name == normalized
            ]
            if clashes:
                raise DuplicateEntityError(
                    f"A {entity_type} named {name!r} already exists: " + ", ".join(clashes)
                )

        clean_aliases: List[str] = []
        for alias in aliases:
            alias = string_value(alias)
            if not alias or normalize_name(alias) == normalized:
                continue
            if normalize_name(alias) in {normalize_name(item) for item in clean_aliases}:
                continue
            if not allow_ambiguous_alias:
                owners = _alias_owners(existing, entity_type, alias)
                if owners:
                    raise AliasCollisionError(alias, owners)
            clean_aliases.append(alias)

        timestamp = now_iso()
        record = EntityRecord(
            id=entity_id or _ids().uuid7(),
            type=entity_type,
            name=name,
            aliases=clean_aliases,
            emails=_unique([normalize_email(value) for value in emails]),
            domains=_unique([normalize_domain(value) for value in domains]),
            visibility="private",
            status="active",
            created=timestamp,
            updated=timestamp,
            sources=[dict(item) for item in sources],
            body="",
        )
        validate_entity(record)
        record.path = self._path_for(record)
        self._write(record)
        self._audit({"event": "entity_created", "entity_id": record.id, "type": record.type, "name": record.name})
        return record

    def rename(self, entity_id: str, name: str, *, keep_previous_alias: bool = True) -> EntityRecord:
        """Change the display name. The entity ID and all references are untouched."""
        record = self.get(entity_id)
        name = string_value(name)
        if not name:
            raise EntityValidationError("Entity name is required")
        previous = record.name
        if normalize_name(previous) == normalize_name(name):
            return record

        record.name = name
        if keep_previous_alias and normalize_name(previous) not in {
            normalize_name(alias) for alias in record.aliases
        }:
            record.aliases.append(previous)
        record.aliases = [
            alias for alias in record.aliases if normalize_name(alias) != normalize_name(name)
        ]
        record.updated = now_iso()
        validate_entity(record)

        old_path = record.path
        record.path = self._path_for(record)
        self._write(record)
        if old_path and old_path.exists() and old_path != record.path:
            old_path.unlink()
        self._audit(
            {
                "event": "entity_renamed",
                "entity_id": record.id,
                "previous_name": previous,
                "name": record.name,
            }
        )
        return record

    def add_alias(self, entity_id: str, alias: str, *, allow_ambiguous: bool = False) -> EntityRecord:
        record = self.get(entity_id)
        alias = string_value(alias)
        if not alias:
            raise EntityValidationError("Alias is required")

        normalized = normalize_name(alias)
        if normalized == record.normalized_name or normalized in set(record.normalized_aliases):
            return record

        if not allow_ambiguous:
            owners = _alias_owners(self.load_all(), record.type, alias, exclude=record.id)
            if owners:
                raise AliasCollisionError(alias, owners)

        record.aliases.append(alias)
        record.updated = now_iso()
        self._write(record)
        self._audit({"event": "alias_added", "entity_id": record.id, "alias": alias})
        return record

    def remove_alias(self, entity_id: str, alias: str) -> EntityRecord:
        record = self.get(entity_id)
        normalized = normalize_name(alias)
        record.aliases = [item for item in record.aliases if normalize_name(item) != normalized]
        record.updated = now_iso()
        self._write(record)
        self._audit({"event": "alias_removed", "entity_id": record.id, "alias": string_value(alias)})
        return record

    def add_identifier(self, entity_id: str, *, email: str = "", domain: str = "") -> EntityRecord:
        record = self.get(entity_id)
        changed = False
        if email:
            normalized = normalize_email(email)
            if not normalized:
                raise EntityValidationError(f"Not an email address: {email!r}")
            owners = _identifier_owners(self.load_all(), "email", normalized, exclude=record.id)
            if owners:
                raise AliasCollisionError(normalized, owners)
            if normalized not in record.emails:
                record.emails.append(normalized)
                changed = True
        if domain:
            normalized = normalize_domain(domain)
            if not normalized:
                raise EntityValidationError(f"Not a domain: {domain!r}")
            owners = _identifier_owners(self.load_all(), "domain", normalized, exclude=record.id)
            if owners:
                raise AliasCollisionError(normalized, owners)
            if normalized not in record.domains:
                record.domains.append(normalized)
                changed = True
        if changed:
            record.updated = now_iso()
            self._write(record)
            self._audit(
                {
                    "event": "identifier_added",
                    "entity_id": record.id,
                    "email": normalize_email(email) if email else "",
                    "domain": normalize_domain(domain) if domain else "",
                }
            )
        return record

    def add_source(self, entity_id: str, source: Dict[str, Any]) -> EntityRecord:
        record = self.get(entity_id)
        entry = {key: string_value(value) for key, value in source.items() if string_value(value)}
        if entry and entry not in record.sources:
            record.sources.append(entry)
            record.updated = now_iso()
            self._write(record)
        return record

    def merge(self, source_id: str, target_id: str) -> Dict[str, Any]:
        """Explicitly merge ``source_id`` into ``target_id``.

        The source record survives as a tombstone so historical references keep
        resolving. Reference rewriting in documents is handled by the caller
        (``EntityDocumentStore.rewrite_entity_id``) so this module stays focused
        on canonical entity files.
        """
        source = self.get(source_id)
        target = self.get(target_id)

        if source.id == target.id:
            raise MergeConflictError("Cannot merge an entity into itself")
        if source.type != target.type:
            raise MergeConflictError(
                f"Cannot merge a {source.type} into a {target.type}; types must match"
            )
        if source.status == "merged":
            raise MergeConflictError(f"Entity {source.id} is already merged into {source.merged_into}")
        if target.status == "merged":
            raise MergeConflictError(f"Target {target.id} is a tombstone merged into {target.merged_into}")

        timestamp = now_iso()
        absorbed_aliases: List[str] = []
        for candidate in [source.name, *source.aliases]:
            normalized = normalize_name(candidate)
            if not normalized or normalized == target.normalized_name:
                continue
            if normalized in {normalize_name(alias) for alias in target.aliases}:
                continue
            target.aliases.append(candidate)
            absorbed_aliases.append(candidate)

        for email in source.emails:
            if email and email not in target.emails:
                target.emails.append(email)
        for domain in source.domains:
            if domain and domain not in target.domains:
                target.domains.append(domain)
        for entry in source.sources:
            if entry not in target.sources:
                target.sources.append(entry)
        if source.id not in target.related:
            target.related.append(source.id)
        target.updated = timestamp
        self._write(target)

        source.status = "merged"
        source.merged_into = target.id
        source.updated = timestamp
        if target.id not in source.related:
            source.related.append(target.id)
        self._write(source)

        audit = {
            "event": "entity_merged",
            "source_entity_id": source.id,
            "source_name": source.name,
            "target_entity_id": target.id,
            "target_name": target.name,
            "absorbed_aliases": absorbed_aliases,
            "merged_at": timestamp,
        }
        self._audit(audit)
        return audit

    # --------------------------------------------------------------- helpers

    def _path_for(self, record: EntityRecord) -> Path:
        directory = self.directory_for(record.type)
        return directory / f"{record.id}-{_ids().slugify(record.name, fallback=record.type)}.md"

    def _write(self, record: EntityRecord) -> Path:
        validate_entity(record)
        path = record.path or self._path_for(record)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record.to_markdown(), encoding="utf-8")
        record.path = path
        return path

    def record_audit(self, payload: Dict[str, Any]) -> None:
        """Append an audit line for an explicit, human-initiated entity change."""
        self._audit(payload)

    def _audit(self, payload: Dict[str, Any]) -> None:
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        record = {"recorded_at": now_iso(), **payload}
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")


def _ids():
    """Imported lazily: ingestion depends on this package for reference carry-over."""
    from core.ingestion import ids

    return ids


def _alias_owners(
    records: Iterable[EntityRecord],
    entity_type: str,
    alias: str,
    *,
    exclude: Optional[str] = None,
) -> List[str]:
    normalized = normalize_name(alias)
    owners = []
    for record in records:
        if record.type != entity_type or record.id == exclude or record.status != "active":
            continue
        if normalized == record.normalized_name or normalized in set(record.normalized_aliases):
            owners.append(f"{record.name} ({record.id})")
    return owners


def _identifier_owners(
    records: Iterable[EntityRecord],
    kind: str,
    value: str,
    *,
    exclude: Optional[str] = None,
) -> List[str]:
    owners = []
    for record in records:
        if record.id == exclude or record.status != "active":
            continue
        pool = record.emails if kind == "email" else record.domains
        if value in pool:
            owners.append(f"{record.name} ({record.id})")
    return owners


def _unique(values: Iterable[str]) -> List[str]:
    result: List[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result
