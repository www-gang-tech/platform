"""Deterministic entity resolution.

Resolution is intentionally boring: exact canonical name, then exact normalized
alias, then a strong deterministic identifier, then unresolved. Nothing here
guesses. Similar-looking names produce *suggestions* for a human to confirm,
never an automatic match or merge.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from .model import (
    EntityRecord,
    email_domain,
    normalize_domain,
    normalize_email,
    normalize_name,
    string_value,
    validate_entity_type,
)


#: Resolution outcomes.
RESOLVED = "resolved"
AMBIGUOUS = "ambiguous"
UNRESOLVED = "unresolved"

#: How a resolution was reached, in priority order.
METHOD_CANONICAL_NAME = "canonical_name"
METHOD_ALIAS = "alias"
METHOD_EMAIL = "email"
METHOD_DOMAIN = "domain"
METHOD_ENTITY_ID = "entity_id"

_TOKEN_PATTERN = re.compile(r"[\w'’-]+", re.UNICODE)


@dataclass(frozen=True)
class Candidate:
    entity_id: str
    entity_type: str
    name: str
    method: str
    reason: str


@dataclass(frozen=True)
class Resolution:
    text: str
    status: str
    entity_id: Optional[str] = None
    entity_type: Optional[str] = None
    name: Optional[str] = None
    method: Optional[str] = None
    reason: str = ""
    candidates: List[Candidate] = field(default_factory=list)
    redirected_from: Optional[str] = None

    @property
    def resolved(self) -> bool:
        return self.status == RESOLVED

    def to_dict(self) -> Dict[str, object]:
        return {
            "text": self.text,
            "status": self.status,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "name": self.name,
            "method": self.method,
            "reason": self.reason,
            "redirected_from": self.redirected_from,
            "candidates": [
                {
                    "entity_id": candidate.entity_id,
                    "entity_type": candidate.entity_type,
                    "name": candidate.name,
                    "method": candidate.method,
                    "reason": candidate.reason,
                }
                for candidate in self.candidates
            ],
        }


class EntityResolver:
    """Resolve free text or identifiers to a canonical entity ID."""

    def __init__(self, records: Sequence[EntityRecord]):
        self.records = list(records)
        self._by_id = {record.id: record for record in self.records}
        self._active = [record for record in self.records if record.status == "active"]

    @classmethod
    def from_store(cls, store) -> "EntityResolver":
        return cls(store.load_all())

    # ------------------------------------------------------------- resolving

    def resolve(self, text: str, *, entity_type: Optional[str] = None) -> Resolution:
        text = string_value(text)
        wanted = validate_entity_type(entity_type) if entity_type else None

        if not text:
            return Resolution(text=text, status=UNRESOLVED, reason="empty text")

        # An explicit entity ID always wins, including tombstone redirects.
        if text in self._by_id:
            return self._from_record(text, self._by_id[text], METHOD_ENTITY_ID, "explicit entity id")

        for method, matches in (
            (METHOD_CANONICAL_NAME, self._by_canonical_name(text, wanted)),
            (METHOD_ALIAS, self._by_alias(text, wanted)),
            (METHOD_EMAIL, self._by_email(text, wanted)),
            (METHOD_DOMAIN, self._by_domain(text, wanted)),
        ):
            if not matches:
                continue
            targets = {self._follow(record).id for record in matches}
            if len(targets) == 1:
                return self._from_record(text, matches[0], method, f"exact {method} match")
            return Resolution(
                text=text,
                status=AMBIGUOUS,
                method=method,
                reason=f"{len(targets)} entities share this {method}",
                candidates=[
                    Candidate(
                        entity_id=record.id,
                        entity_type=record.type,
                        name=record.name,
                        method=method,
                        reason=f"exact {method} match",
                    )
                    for record in matches
                ],
            )

        suggestions = self.suggest(text, entity_type=wanted)
        return Resolution(
            text=text,
            status=UNRESOLVED,
            reason="no exact canonical name, alias, or identifier match",
            candidates=suggestions,
        )

    def suggest(self, text: str, *, entity_type: Optional[str] = None, limit: int = 5) -> List[Candidate]:
        """Non-binding similarity hints for human review. Never auto-applied."""
        tokens = _tokens(text)
        if not tokens:
            return []

        scored: List[tuple[float, Candidate]] = []
        for record in self._active:
            if entity_type and record.type != entity_type:
                continue
            best = 0.0
            best_label = ""
            for label in [record.name, *record.aliases]:
                other = _tokens(label)
                if not other:
                    continue
                overlap = len(tokens & other)
                if not overlap:
                    continue
                score = overlap / max(len(tokens), len(other))
                if score > best:
                    best = score
                    best_label = label
            if best > 0:
                scored.append(
                    (
                        best,
                        Candidate(
                            entity_id=record.id,
                            entity_type=record.type,
                            name=record.name,
                            method="similarity",
                            reason=f"shares name tokens with {best_label!r}; requires confirmation",
                        ),
                    )
                )

        scored.sort(key=lambda item: (-item[0], item[1].name, item[1].entity_id))
        return [candidate for _, candidate in scored[:limit]]

    # --------------------------------------------------------------- lookups

    def _by_canonical_name(self, text: str, entity_type: Optional[str]) -> List[EntityRecord]:
        normalized = normalize_name(text)
        return self._filter(
            lambda record: record.normalized_name == normalized, entity_type
        )

    def _by_alias(self, text: str, entity_type: Optional[str]) -> List[EntityRecord]:
        normalized = normalize_name(text)
        return self._filter(
            lambda record: normalized in set(record.normalized_aliases), entity_type
        )

    def _by_email(self, text: str, entity_type: Optional[str]) -> List[EntityRecord]:
        email = normalize_email(text)
        if not email:
            return []
        return self._filter(lambda record: email in record.emails, entity_type)

    def _by_domain(self, text: str, entity_type: Optional[str]) -> List[EntityRecord]:
        domain = email_domain(text) or normalize_domain(text)
        if not domain or "." not in domain:
            return []
        return self._filter(lambda record: domain in record.domains, entity_type)

    def _filter(self, predicate, entity_type: Optional[str]) -> List[EntityRecord]:
        matches = [
            record
            for record in self.records
            if predicate(record) and (entity_type is None or record.type == entity_type)
        ]
        # Prefer active records; tombstones still resolve via their merge target.
        active = [record for record in matches if record.status == "active"]
        return active or matches

    def _follow(self, record: EntityRecord, depth: int = 0) -> EntityRecord:
        if record.status != "merged" or not record.merged_into or depth > 16:
            return record
        target = self._by_id.get(record.merged_into)
        if target is None:
            return record
        return self._follow(target, depth + 1)

    def _from_record(self, text: str, record: EntityRecord, method: str, reason: str) -> Resolution:
        target = self._follow(record)
        return Resolution(
            text=text,
            status=RESOLVED,
            entity_id=target.id,
            entity_type=target.type,
            name=target.name,
            method=method,
            reason=reason if target.id == record.id else f"{reason}; redirected through merge tombstone",
            redirected_from=None if target.id == record.id else record.id,
        )


def _tokens(value: str) -> set:
    return {token.casefold() for token in _TOKEN_PATTERN.findall(normalize_name(value))}
