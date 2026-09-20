"""Core types, vocabulary, and normalization for stable entities and relationships.

Identity rules enforced here:

* An entity's identity is its opaque UUIDv7 ``id``. Names, aliases, slugs, paths,
  email addresses, and domains are *lookup keys*, never identity.
* Normalization is deliberately conservative. It folds case, unicode form, and
  whitespace only. It never strips punctuation or corporate suffixes, so
  ``"Eliro"`` and ``"Eliro Inc."`` stay distinct while ``"ELIRO"`` and ``"Eliro"``
  match exactly.

Foundational knowledge
----------------------

An entity record may also carry an authored ``description``: the company's or
project's own account of what it is. This exists because the alternative is
worse. Asked "what is GANG?", a system with no authored identity has to
reconstruct the company from whatever email happens to mention it, which is
how a scheduling thread becomes a definition.

The ``description`` is authored or approved by a human and is never written by
a model. Enrichment and entity proposals cannot set it — see
``PROTECTED_IDENTITY_FIELDS`` — because a generated description is exactly the
new company fact the whole system exists to prevent.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml


ENTITY_SCHEMA_VERSION = 1
PREDICATE_VOCABULARY_VERSION = 1

#: Deliberately small ontology. Expanding it is a future epic, not a config knob.
ENTITY_TYPES = ("person", "company", "project", "product")

#: Vault directory per entity type, relative to the private vault root.
ENTITY_DIRECTORIES = {
    "person": "people",
    "company": "companies",
    "project": "projects",
    "product": "products",
}

#: Frontmatter marker distinguishing a canonical entity record from a knowledge
#: document. Documents that predate this epic have no marker and stay documents.
ENTITY_RECORD_MARKER = "entity"

#: Controlled predicate vocabulary. Model-invented predicates are rejected.
PREDICATES = (
    "affiliated_with",
    "involved_in",
    "works_on",
    "represents",
    "supplied_by",
    "related_to",
)

ENTITY_STATUSES = ("active", "merged")
RELATIONSHIP_STATUSES = ("active", "superseded_by_merge")

MENTION_FIELD = "entity_refs"
RELATIONSHIP_FIELD = "entity_relationships"

MAX_EVIDENCE_EXCERPT = 500

#: A definition, not an essay. Long enough for "what it is, and what it does",
#: short enough to quote whole in an answer.
MAX_DESCRIPTION = 1200

#: Authored identity. No AI-assisted flow may write these: enrichment and
#: entity proposals are checked against this set before they are applied.
PROTECTED_IDENTITY_FIELDS = ("description",)


class EntityError(Exception):
    """Base error for the entity and relationship layer."""


class EntityValidationError(EntityError):
    """Raised when an entity, mention, or relationship fails schema validation."""


class EntityNotFoundError(EntityError):
    """Raised when an entity ID cannot be resolved to a canonical record."""


class DuplicateEntityError(EntityError):
    """Raised when creating an entity whose canonical name is already taken."""


class AliasCollisionError(EntityError):
    """Raised when an alias already resolves to a different entity of the same type."""

    def __init__(self, alias: str, owners: Iterable[str]):
        self.alias = alias
        self.owners = list(owners)
        super().__init__(
            f"Alias {alias!r} already resolves to: " + ", ".join(self.owners)
        )


class MergeConflictError(EntityError):
    """Raised when a merge would be unsafe."""


@dataclass
class EntityRecord:
    """A canonical entity. The Markdown file on disk is the source of truth."""

    id: str
    type: str
    name: str
    aliases: List[str] = field(default_factory=list)
    emails: List[str] = field(default_factory=list)
    domains: List[str] = field(default_factory=list)
    visibility: str = "private"
    status: str = "active"
    merged_into: Optional[str] = None
    created: str = ""
    updated: str = ""
    sources: List[Dict[str, Any]] = field(default_factory=list)
    related: List[str] = field(default_factory=list)
    #: Authored, human-approved account of what this entity is. Never generated.
    description: str = ""
    body: str = ""
    path: Optional[Path] = None

    @property
    def normalized_name(self) -> str:
        return normalize_name(self.name)

    @property
    def foundational(self) -> bool:
        """Whether this record says anything authoritative about what it is.

        An identity with no authored content is still a valid identity — it
        anchors mentions and relationships — but it has nothing to tell anyone
        who asks what the thing *is*, so it is not offered as a definition.
        """
        return bool(self.description.strip() or self.authored_body.strip())

    @property
    def authored_body(self) -> str:
        """Body prose, minus the bare ``# Name`` heading a new record gets."""
        text = (self.body or "").strip()
        if not text:
            return ""
        lines = [line for line in text.splitlines() if line.strip()]
        if len(lines) == 1 and lines[0].lstrip("# ").strip().casefold() == self.name.casefold():
            return ""
        return text

    def identity_text(self) -> str:
        """The authored identity, as the prose an answer may quote and cite."""
        parts = [self.description.strip(), self.authored_body.strip()]
        return "\n\n".join(part for part in parts if part)

    @property
    def normalized_aliases(self) -> List[str]:
        return [normalize_name(alias) for alias in self.aliases]

    def lookup_keys(self) -> List[tuple[str, str, str]]:
        """Return ``(kind, display, normalized)`` triples for every lookup key."""
        keys = [("name", self.name, normalize_name(self.name))]
        keys.extend(("alias", alias, normalize_name(alias)) for alias in self.aliases)
        keys.extend(("email", email, normalize_email(email)) for email in self.emails)
        keys.extend(("domain", domain, normalize_domain(domain)) for domain in self.domains)
        return [(kind, display, normalized) for kind, display, normalized in keys if normalized]

    def to_frontmatter(self) -> Dict[str, Any]:
        frontmatter: Dict[str, Any] = {
            "id": self.id,
            "record": ENTITY_RECORD_MARKER,
            "schema_version": ENTITY_SCHEMA_VERSION,
            "type": self.type,
            "name": self.name,
            "aliases": list(self.aliases),
            "visibility": self.visibility,
            "status": self.status,
            "created": self.created,
            "updated": self.updated,
            "sources": [dict(source) for source in self.sources],
            "related": list(self.related),
        }
        if self.description:
            frontmatter["description"] = self.description
        identifiers: Dict[str, Any] = {}
        if self.emails:
            identifiers["emails"] = list(self.emails)
        if self.domains:
            identifiers["domains"] = list(self.domains)
        if identifiers:
            frontmatter["identifiers"] = identifiers
        if self.merged_into:
            frontmatter["merged_into"] = self.merged_into
        return frontmatter

    def to_markdown(self) -> str:
        body = self.body if self.body.strip() else f"\n# {self.name}\n"
        return dump_markdown(self.to_frontmatter(), body)

    @classmethod
    def from_frontmatter(cls, frontmatter: Dict[str, Any], body: str, path: Path) -> "EntityRecord":
        identifiers = frontmatter.get("identifiers")
        identifiers = identifiers if isinstance(identifiers, dict) else {}
        record = cls(
            id=string_value(frontmatter.get("id")),
            type=string_value(frontmatter.get("type")),
            name=string_value(frontmatter.get("name")),
            aliases=string_list(frontmatter.get("aliases")),
            emails=[normalize_email(value) for value in string_list(identifiers.get("emails"))],
            domains=[normalize_domain(value) for value in string_list(identifiers.get("domains"))],
            visibility=string_value(frontmatter.get("visibility")) or "private",
            status=string_value(frontmatter.get("status")) or "active",
            merged_into=string_value(frontmatter.get("merged_into")) or None,
            created=string_value(frontmatter.get("created")),
            updated=string_value(frontmatter.get("updated")),
            sources=[item for item in (frontmatter.get("sources") or []) if isinstance(item, dict)],
            related=string_list(frontmatter.get("related")),
            description=string_value(frontmatter.get("description")),
            body=body,
            path=path,
        )
        validate_entity(record)
        return record


def validate_entity(record: EntityRecord) -> EntityRecord:
    if not is_uuid_like(record.id):
        raise EntityValidationError(f"Entity id must be a UUID: {record.id!r}")
    if record.type not in ENTITY_TYPES:
        raise EntityValidationError(
            f"Unsupported entity type {record.type!r}. Supported: " + ", ".join(ENTITY_TYPES)
        )
    if not record.name.strip():
        raise EntityValidationError("Entity name is required")
    if record.status not in ENTITY_STATUSES:
        raise EntityValidationError(f"Unsupported entity status {record.status!r}")
    if record.visibility != "private":
        raise EntityValidationError(
            "Entity visibility must be private. Public entity publishing is out of scope."
        )
    if record.status == "merged" and not record.merged_into:
        raise EntityValidationError("Merged entities must record merged_into")
    if len(record.description) > MAX_DESCRIPTION:
        raise EntityValidationError(
            f"Entity description is limited to {MAX_DESCRIPTION} characters; "
            "put the longer account in the record body."
        )
    return record


def validate_entity_type(entity_type: str) -> str:
    value = string_value(entity_type).lower()
    if value not in ENTITY_TYPES:
        raise EntityValidationError(
            f"Unsupported entity type {entity_type!r}. Supported: " + ", ".join(ENTITY_TYPES)
        )
    return value


def validate_predicate(predicate: str) -> str:
    value = string_value(predicate).lower()
    if value not in PREDICATES:
        raise EntityValidationError(
            f"Unsupported predicate {predicate!r}. Supported: " + ", ".join(PREDICATES)
        )
    return value


def normalize_name(value: Any) -> str:
    """Casefold and collapse whitespace without stripping meaningful punctuation."""
    text = unicodedata.normalize("NFKC", string_value(value))
    text = re.sub(r"\s+", " ", text).strip()
    return text.casefold()


def normalize_email(value: Any) -> str:
    text = unicodedata.normalize("NFKC", string_value(value)).strip().casefold()
    text = text.lstrip("<").rstrip(">")
    return text if "@" in text else ""


def normalize_domain(value: Any) -> str:
    text = unicodedata.normalize("NFKC", string_value(value)).strip().casefold()
    text = text.split("@")[-1]
    text = re.sub(r"^https?://", "", text).split("/")[0]
    if text.startswith("www."):
        text = text[4:]
    return text


def email_domain(value: Any) -> str:
    email = normalize_email(value)
    return normalize_domain(email.split("@")[-1]) if email else ""


def is_uuid_like(value: Any) -> bool:
    return bool(
        re.fullmatch(
            r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}",
            string_value(value),
        )
    )


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def string_value(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value).strip()


def string_list(value: Any) -> List[str]:
    result: List[str] = []

    def collect(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, (list, tuple, set)):
            for child in item:
                collect(child)
            return
        if isinstance(item, dict):
            for key in ("name", "id", "label", "title"):
                if key in item:
                    collect(item[key])
                    return
            return
        text = string_value(item)
        if text and text not in result:
            result.append(text)

    collect(value)
    return result


def parse_markdown(text: str) -> tuple[Dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    frontmatter = yaml.safe_load(parts[1]) or {}
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return frontmatter, parts[2]


def dump_markdown(frontmatter: Dict[str, Any], body: str) -> str:
    rendered = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
    return f"---\n{rendered}---{body}"


def is_entity_frontmatter(frontmatter: Dict[str, Any]) -> bool:
    return string_value(frontmatter.get("record")) == ENTITY_RECORD_MARKER


def clean_excerpt(value: Any) -> str:
    text = re.sub(r"\s+", " ", string_value(value)).strip()
    return text[:MAX_EVIDENCE_EXCERPT]
