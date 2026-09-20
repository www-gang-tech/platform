"""Stable entity references and relationship assertions on canonical documents.

Two different things live here, and keeping them apart is the whole point of
this layer:

* A **mention** (``entity_refs``) records that a document refers to an entity.
  It proves nothing about how entities relate to each other.
* A **relationship assertion** (``entity_relationships``) claims that two
  entities relate in a typed way. It requires an evidence excerpt drawn from the
  document that carries it.

Both are additive. Legacy string fields (``people``, ``companies``, ``projects``)
are left untouched for compatibility.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from core.paths import GangPaths

from .model import (
    MENTION_FIELD,
    RELATIONSHIP_FIELD,
    EntityError,
    EntityValidationError,
    clean_excerpt,
    dump_markdown,
    is_entity_frontmatter,
    now_iso,
    parse_markdown,
    string_list,
    string_value,
    validate_entity_type,
    validate_predicate,
)


#: Frontmatter that identity and provenance depend on. Applying entity data must
#: never touch these, mirroring the Epic 05 enrichment guarantee.
PROTECTED_FRONTMATTER_FIELDS = {
    "id",
    "visibility",
    "status",
    "url",
    "created",
    "created_at",
    "source_id",
    "source_ids",
    "sources",
    "provenance",
    "raw_ref",
    "content_hash",
    "version",
    "ingestion_envelope",
    "type",
    "title",
}


class PublicDocumentError(EntityError):
    """Raised when private entity data would be written to a public document."""


@dataclass(frozen=True)
class EntityDocument:
    document_id: str
    path: Path
    frontmatter: Dict[str, Any]
    body: str
    raw_text: str
    document_hash: str

    @property
    def title(self) -> str:
        return string_value(self.frontmatter.get("title")) or self.path.stem

    @property
    def visibility(self) -> str:
        return string_value(self.frontmatter.get("visibility")) or "private"

    @property
    def source_ids(self) -> List[str]:
        values = [self.frontmatter.get("source_id"), self.frontmatter.get("source_ids")]
        provenance = self.frontmatter.get("provenance")
        if isinstance(provenance, dict):
            values.append(provenance.get("source_id"))
        envelope = self.frontmatter.get("ingestion_envelope")
        if isinstance(envelope, dict):
            values.append(envelope.get("source_id"))
        return string_list(values)

    @property
    def mentions(self) -> List[Dict[str, Any]]:
        return [item for item in (self.frontmatter.get(MENTION_FIELD) or []) if isinstance(item, dict)]

    @property
    def relationships(self) -> List[Dict[str, Any]]:
        return [item for item in (self.frontmatter.get(RELATIONSHIP_FIELD) or []) if isinstance(item, dict)]

    @property
    def candidate_strings(self) -> Dict[str, List[str]]:
        """Legacy Epic 05 enrichment strings, offered as resolution candidates only."""
        return {
            "person": string_list(self.frontmatter.get("people")),
            "company": string_list(self.frontmatter.get("companies")),
            "project": string_list(self.frontmatter.get("projects")),
        }


class EntityDocumentStore:
    """Read canonical documents and apply entity references to them."""

    def __init__(
        self,
        *,
        root_path: Path | str = Path("."),
        private_home: Path | str | None = None,
        vault_paths: Optional[Sequence[Path | str]] = None,
    ):
        self.root_path = Path(root_path).resolve()
        self.paths = GangPaths.from_env(repo_root=self.root_path, gang_home=private_home)
        if vault_paths is not None:
            self.vault_paths = [self._resolve(path) for path in vault_paths]
        else:
            self.vault_paths = [self.paths.private_vault, self.paths.repo_public_vault]

    # ------------------------------------------------------------------ read

    def iter_documents(self) -> Iterable[EntityDocument]:
        for path in self._markdown_paths():
            raw_text = path.read_text(encoding="utf-8")
            frontmatter, body = parse_markdown(raw_text)
            if is_entity_frontmatter(frontmatter):
                continue
            document_id = string_value(frontmatter.get("id"))
            if not document_id:
                continue
            yield EntityDocument(
                document_id=document_id,
                path=path,
                frontmatter=frontmatter,
                body=body,
                raw_text=raw_text,
                document_hash=sha256_text(raw_text),
            )

    def load(self, document_id: str) -> EntityDocument:
        document_id = string_value(document_id)
        matches = [document for document in self.iter_documents() if document.document_id == document_id]
        if not matches:
            raise EntityError(f"Document not found: {document_id}")
        if len(matches) > 1:
            raise EntityError(f"Duplicate document id in vault: {document_id}")
        return matches[0]

    # ----------------------------------------------------------------- write

    def apply_references(
        self,
        document: EntityDocument,
        *,
        mentions: Sequence[Dict[str, Any]] = (),
        relationships: Sequence[Dict[str, Any]] = (),
    ) -> Dict[str, Any]:
        """Additively merge mentions and relationships into a private document."""
        self._assert_private(document)

        frontmatter = dict(document.frontmatter)
        existing_mentions = [dict(item) for item in document.mentions]
        existing_relationships = [dict(item) for item in document.relationships]

        added_mentions: List[Dict[str, Any]] = []
        mention_keys = {_mention_key(item) for item in existing_mentions}
        for mention in mentions:
            normalized = normalize_mention(mention)
            key = _mention_key(normalized)
            if key in mention_keys:
                continue
            mention_keys.add(key)
            existing_mentions.append(normalized)
            added_mentions.append(normalized)

        added_relationships: List[Dict[str, Any]] = []
        relationship_ids = {string_value(item.get("relationship_id")) for item in existing_relationships}
        for relationship in relationships:
            normalized = normalize_relationship(relationship, document_id=document.document_id)
            if normalized["relationship_id"] in relationship_ids:
                continue
            relationship_ids.add(normalized["relationship_id"])
            existing_relationships.append(normalized)
            added_relationships.append(normalized)

        if not added_mentions and not added_relationships:
            return {
                "changed": False,
                "path": document.path,
                "added_mentions": [],
                "added_relationships": [],
                "resulting_hash": document.document_hash,
            }

        if existing_mentions:
            frontmatter[MENTION_FIELD] = sort_mentions(existing_mentions)
        if existing_relationships:
            frontmatter[RELATIONSHIP_FIELD] = sort_relationships(existing_relationships)

        assert_protected_fields_unchanged(document.frontmatter, frontmatter)
        text = dump_markdown(frontmatter, document.body)
        document.path.write_text(text, encoding="utf-8")
        return {
            "changed": True,
            "path": document.path,
            "added_mentions": added_mentions,
            "added_relationships": added_relationships,
            "resulting_hash": sha256_text(text),
        }

    def rewrite_entity_id(self, source_entity_id: str, target_entity_id: str) -> List[Dict[str, Any]]:
        """Point every stable reference at ``target_entity_id`` after a merge."""
        source_entity_id = string_value(source_entity_id)
        target_entity_id = string_value(target_entity_id)
        rewritten: List[Dict[str, Any]] = []

        for document in list(self.iter_documents()):
            frontmatter = dict(document.frontmatter)
            changed = False

            mentions = [dict(item) for item in document.mentions]
            if any(string_value(item.get("entity_id")) == source_entity_id for item in mentions):
                for item in mentions:
                    if string_value(item.get("entity_id")) == source_entity_id:
                        item["entity_id"] = target_entity_id
                        item["merged_from"] = source_entity_id
                deduped: List[Dict[str, Any]] = []
                seen = set()
                for item in mentions:
                    key = _mention_key(item)
                    if key in seen:
                        continue
                    seen.add(key)
                    deduped.append(item)
                frontmatter[MENTION_FIELD] = sort_mentions(deduped)
                changed = True

            relationships = [dict(item) for item in document.relationships]
            if any(
                source_entity_id in (
                    string_value(item.get("subject_entity_id")),
                    string_value(item.get("object_entity_id")),
                )
                for item in relationships
            ):
                updated: List[Dict[str, Any]] = []
                seen_ids = set()
                for item in relationships:
                    subject = string_value(item.get("subject_entity_id"))
                    object_ = string_value(item.get("object_entity_id"))
                    if source_entity_id not in (subject, object_):
                        updated.append(item)
                        seen_ids.add(string_value(item.get("relationship_id")))
                        continue
                    item = dict(item)
                    item["merged_from"] = source_entity_id
                    if subject == source_entity_id:
                        item["subject_entity_id"] = target_entity_id
                    if object_ == source_entity_id:
                        item["object_entity_id"] = target_entity_id
                    if item["subject_entity_id"] == item["object_entity_id"]:
                        # The merge collapsed both ends of this edge. Keep the
                        # assertion for provenance, but drop it from the graph.
                        item["status"] = "superseded_by_merge"
                    item["relationship_id"] = relationship_id(
                        document_id=string_value(item.get("document_id")) or document.document_id,
                        subject_entity_id=item["subject_entity_id"],
                        predicate=string_value(item.get("predicate")),
                        object_entity_id=item["object_entity_id"],
                        excerpt=clean_excerpt((item.get("evidence") or {}).get("excerpt")),
                    )
                    if item["relationship_id"] in seen_ids:
                        continue
                    seen_ids.add(item["relationship_id"])
                    updated.append(item)
                frontmatter[RELATIONSHIP_FIELD] = sort_relationships(updated)
                changed = True

            if not changed:
                continue

            assert_protected_fields_unchanged(document.frontmatter, frontmatter)
            document.path.write_text(dump_markdown(frontmatter, document.body), encoding="utf-8")
            rewritten.append({"document_id": document.document_id, "path": document.path})

        return rewritten

    # --------------------------------------------------------------- helpers

    def _assert_private(self, document: EntityDocument) -> None:
        if document.visibility != "private":
            raise PublicDocumentError(
                f"Refusing to write private entity references to a {document.visibility} document: "
                f"{document.document_id}"
            )
        public_root = self.paths.repo_public_vault.resolve()
        try:
            document.path.resolve().relative_to(public_root)
        except ValueError:
            return
        raise PublicDocumentError(
            f"Refusing to write private entity references under the public vault: {document.path}"
        )

    def _markdown_paths(self) -> List[Path]:
        paths: List[Path] = []
        for vault_path in self.vault_paths:
            if not vault_path.exists():
                continue
            vault_root = vault_path.resolve()
            for path in vault_path.rglob("*.md"):
                rel_parts = path.resolve().relative_to(vault_root).parts
                if any(part.startswith(".") for part in rel_parts):
                    continue
                paths.append(path)
        return sorted(set(paths))

    def _resolve(self, path: Path | str) -> Path:
        candidate = Path(path)
        return candidate if candidate.is_absolute() else (self.root_path / candidate)


# ------------------------------------------------------------- normalization


def normalize_mention(mention: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(mention, dict):
        raise EntityValidationError("Mention must be an object")
    entity_id = string_value(mention.get("entity_id"))
    if not entity_id:
        raise EntityValidationError("Mention requires entity_id")
    entity_type = validate_entity_type(mention.get("entity_type"))
    label = string_value(mention.get("label"))
    if not label:
        raise EntityValidationError("Mention requires the label text found in the document")

    normalized: Dict[str, Any] = {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "label": label,
        "added": string_value(mention.get("added")) or now_iso(),
    }
    evidence = normalize_evidence(mention.get("evidence"), required=False)
    if evidence:
        normalized["evidence"] = evidence
    proposal_id = string_value(mention.get("proposal_id"))
    if proposal_id:
        normalized["proposal_id"] = proposal_id
    return normalized


def normalize_relationship(relationship: Dict[str, Any], *, document_id: str) -> Dict[str, Any]:
    if not isinstance(relationship, dict):
        raise EntityValidationError("Relationship must be an object")

    subject = string_value(relationship.get("subject_entity_id"))
    object_ = string_value(relationship.get("object_entity_id"))
    predicate = validate_predicate(relationship.get("predicate"))
    if not subject or not object_:
        raise EntityValidationError("Relationship requires subject_entity_id and object_entity_id")
    if subject == object_:
        raise EntityValidationError("Relationship subject and object must be different entities")

    host_document_id = string_value(relationship.get("document_id")) or string_value(document_id)
    if host_document_id != string_value(document_id):
        raise EntityValidationError(
            "Relationship document_id must match the document that carries the evidence"
        )

    evidence = normalize_evidence(relationship.get("evidence"), required=True)
    status = string_value(relationship.get("status")) or "active"
    if status not in ("active", "superseded_by_merge"):
        raise EntityValidationError(f"Unsupported relationship status {status!r}")

    normalized: Dict[str, Any] = {
        "relationship_id": relationship_id(
            document_id=host_document_id,
            subject_entity_id=subject,
            predicate=predicate,
            object_entity_id=object_,
            excerpt=evidence["excerpt"],
        ),
        "subject_entity_id": subject,
        "predicate": predicate,
        "object_entity_id": object_,
        "document_id": host_document_id,
        "source_ids": string_list(relationship.get("source_ids")),
        "evidence": evidence,
        "created": string_value(relationship.get("created")) or now_iso(),
        "status": status,
    }
    proposal_id = string_value(relationship.get("proposal_id"))
    if proposal_id:
        normalized["proposal_id"] = proposal_id
    return normalized


def normalize_evidence(value: Any, *, required: bool) -> Dict[str, str]:
    if value is None or value == {}:
        if required:
            raise EntityValidationError("Relationship requires an evidence excerpt")
        return {}
    if isinstance(value, str):
        value = {"excerpt": value}
    if not isinstance(value, dict):
        raise EntityValidationError("evidence must be an object")

    unknown = sorted(set(value) - {"excerpt", "source_id", "document_id", "section"})
    if unknown:
        raise EntityValidationError("Unsupported evidence field(s): " + ", ".join(unknown))

    excerpt = clean_excerpt(value.get("excerpt"))
    if required and not excerpt:
        raise EntityValidationError("Relationship requires a non-empty evidence excerpt")

    evidence = {"excerpt": excerpt} if excerpt else {}
    for key in ("source_id", "document_id", "section"):
        text = string_value(value.get(key))
        if text:
            evidence[key] = text
    return evidence


def relationship_id(
    *,
    document_id: str,
    subject_entity_id: str,
    predicate: str,
    object_entity_id: str,
    excerpt: str,
) -> str:
    digest = hashlib.sha256(
        "|".join([document_id, subject_entity_id, predicate, object_entity_id, excerpt]).encode("utf-8")
    ).hexdigest()
    return f"rel_{digest[:32]}"


def sort_mentions(mentions: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        mentions,
        key=lambda item: (
            string_value(item.get("entity_type")),
            string_value(item.get("entity_id")),
            string_value(item.get("label")).casefold(),
        ),
    )


def sort_relationships(relationships: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        relationships,
        key=lambda item: (
            string_value(item.get("subject_entity_id")),
            string_value(item.get("predicate")),
            string_value(item.get("object_entity_id")),
            string_value(item.get("relationship_id")),
        ),
    )


def assert_protected_fields_unchanged(before: Dict[str, Any], after: Dict[str, Any]) -> None:
    changed = sorted(
        field for field in PROTECTED_FRONTMATTER_FIELDS if before.get(field) != after.get(field)
    )
    if changed:
        raise EntityValidationError("Protected frontmatter field changed: " + ", ".join(changed))


def preserved_entity_frontmatter(path: Optional[Path]) -> Dict[str, Any]:
    """Return applied entity references already present in a document.

    Connectors regenerate canonical documents from immutable source evidence
    whenever a thread or file changes. Stable entity references are human-applied
    knowledge layered on top, so they must survive that regeneration.
    """
    if path is None or not Path(path).exists():
        return {}
    frontmatter, _ = parse_markdown(Path(path).read_text(encoding="utf-8"))
    preserved: Dict[str, Any] = {}
    for field in (MENTION_FIELD, RELATIONSHIP_FIELD):
        values = [item for item in (frontmatter.get(field) or []) if isinstance(item, dict)]
        if values:
            preserved[field] = values
    return preserved


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _mention_key(mention: Dict[str, Any]) -> tuple:
    return (
        string_value(mention.get("entity_id")),
        string_value(mention.get("label")).casefold(),
    )
