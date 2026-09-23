"""Deterministic entity-link backfill.

Closes a gap the interactive proposal flow (``proposals.py``) does not cover:
canonical entities created *after* documents were already ingested have zero
mention edges, even when the corpus clearly has evidence about them, because
nothing ever re-scans old documents once a new entity exists.

Only high-confidence evidence is auto-linked, and the two entity types have
different rules:

* Person: an exact verified participant email address, or an exact canonical
  full name.
* Company: an exact canonical name, or a verified participant email domain.

An alias match is never auto-linked, no matter how unique it looks. It is only
ever reported as a candidate for a human to confirm, because short aliases
("Dan", "Frank") are exactly the strings most likely to collide with someone
else. "Verified" means the address or domain came from a document's own
structured ingestion metadata (participant/header fields written by the
adapter), not from a guess about free-form prose.

No AI, no fuzzy matching, no role or relationship inference. A mention only
proves a document refers to an entity, never what the entity did in it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .documents import EntityDocument, EntityDocumentStore
from .model import (
    EntityRecord,
    clean_excerpt,
    email_domain,
    normalize_email,
    normalize_name,
    string_list,
    string_value,
)

REASON_VERIFIED_EMAIL = "verified-email"
REASON_CANONICAL_NAME = "canonical-name"
REASON_VERIFIED_DOMAIN = "verified-domain"

#: Entity types the deterministic matching rules below are defined for.
BACKFILL_ENTITY_TYPES = ("person", "company")

#: Shorter names match too much unrelated prose to be useful body evidence.
MIN_LABEL_LENGTH = 3

_EMAIL_PATTERN = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


@dataclass(frozen=True)
class EntityMatch:
    entity_id: str
    entity_type: str
    label: str
    reason: str
    evidence: str


@dataclass
class BackfillEntityReport:
    entity_id: str
    entity_name: str
    entity_type: str
    scanned: int = 0
    high_confidence: int = 0
    already_linked: int = 0
    new_mentions: int = 0
    ambiguous_skipped: int = 0
    matches: List[Dict[str, Any]] = field(default_factory=list)
    candidates: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_name": self.entity_name,
            "entity_type": self.entity_type,
            "scanned": self.scanned,
            "high_confidence": self.high_confidence,
            "already_linked": self.already_linked,
            "new_mentions": self.new_mentions,
            "ambiguous_skipped": self.ambiguous_skipped,
            "matches": list(self.matches),
            "candidates": list(self.candidates),
        }


def run_backfill(
    document_iter: Iterable[EntityDocument],
    records: Sequence[EntityRecord],
    *,
    documents: EntityDocumentStore,
    apply: bool = False,
) -> Tuple[Dict[str, BackfillEntityReport], bool]:
    """Scan documents once, matching every record in ``records`` per document.

    Every entity that matches the same document is applied in a single
    ``apply_references`` call so a document is only ever written once per
    pass, however many entities it turns out to reference.
    """
    reports = {
        record.id: BackfillEntityReport(
            entity_id=record.id, entity_name=record.name, entity_type=record.type
        )
        for record in records
    }
    changed = False

    for document in document_iter:
        # Public pages are in the corpus, but entity links are private knowledge.
        # Trying to write one raises, which used to abort the pass after earlier
        # private documents had already been updated and before the index rebuild.
        if not documents.accepts_entity_references(document):
            continue

        for report in reports.values():
            report.scanned += 1

        already_linked_ids = {string_value(item.get("entity_id")) for item in document.mentions}
        pending_mentions: List[Dict[str, Any]] = []

        for record in records:
            if record.status != "active":
                continue
            report = reports[record.id]

            match = _match_document(document, record)
            if match is not None:
                report.high_confidence += 1
                report.matches.append(
                    {
                        "document_id": document.document_id,
                        "reason": match.reason,
                        "label": match.label,
                        "evidence": match.evidence,
                    }
                )
                if record.id in already_linked_ids:
                    report.already_linked += 1
                else:
                    report.new_mentions += 1
                    pending_mentions.append(
                        {
                            "entity_id": record.id,
                            "entity_type": record.type,
                            "label": match.label,
                            "evidence": {"excerpt": match.evidence} if match.evidence else {},
                        }
                    )
                continue

            alias = _alias_candidate(document, record)
            if alias:
                report.ambiguous_skipped += 1
                report.candidates.append({"document_id": document.document_id, "alias": alias})

        if apply and pending_mentions:
            documents.apply_references(document, mentions=pending_mentions)
            changed = True

    return reports, changed


def _match_document(document: EntityDocument, record: EntityRecord) -> Optional[EntityMatch]:
    if record.type == "person":
        for email, evidence in _participant_emails(document):
            if email in record.emails:
                return EntityMatch(record.id, record.type, email, REASON_VERIFIED_EMAIL, evidence)
    elif record.type == "company":
        for email, evidence in _participant_emails(document):
            domain = email_domain(email)
            if domain and domain in record.domains:
                return EntityMatch(record.id, record.type, record.name, REASON_VERIFIED_DOMAIN, evidence)

    body_hit = _whole_word_excerpt(document.body, record.name)
    if body_hit is not None:
        return EntityMatch(record.id, record.type, record.name, REASON_CANONICAL_NAME, body_hit)

    for text in document.candidate_strings.get(record.type, []):
        if normalize_name(text) == record.normalized_name:
            return EntityMatch(record.id, record.type, text, REASON_CANONICAL_NAME, text)

    return None


def _alias_candidate(document: EntityDocument, record: EntityRecord) -> Optional[str]:
    for alias in record.aliases:
        if _whole_word_excerpt(document.body, alias) is not None:
            return alias
    for text in document.candidate_strings.get(record.type, []):
        if normalize_name(text) in record.normalized_aliases:
            return text
    return None


def _participant_emails(document: EntityDocument) -> List[Tuple[str, str]]:
    """Verified ``(email, source_text)`` pairs from structured envelope fields.

    Deliberately narrower than a body scan: these strings came from the
    ingestion adapter's own participant/header extraction (From/To/Cc/
    attendee), not from a guess about free-form prose, which is what makes an
    address here "verified" enough to auto-link.
    """
    raw_values: List[str] = []
    envelope = document.frontmatter.get("ingestion_envelope")
    if isinstance(envelope, dict):
        raw_values.extend(string_list(envelope.get("participants")))
    gmail = document.frontmatter.get("gmail")
    if isinstance(gmail, dict):
        raw_values.extend(string_list(gmail.get("participants")))

    pairs: List[Tuple[str, str]] = []
    seen: set = set()
    for value in raw_values:
        for match in _EMAIL_PATTERN.findall(value):
            email = normalize_email(match)
            if email and email not in seen:
                seen.add(email)
                pairs.append((email, value))
    return pairs


def _whole_word_excerpt(body: str, label: str) -> Optional[str]:
    if len(label) < MIN_LABEL_LENGTH:
        return None
    # `.` and `@` are not word characters, so a bare `(?<!\w)…(?!\w)` treats
    # `gang.tech` as the name "Gang" and `dan@example.com` as the name "Dan".
    # Those are addresses, not canonical-name evidence; a verified domain or
    # email only counts when it comes from structured participant metadata.
    pattern = re.compile(
        rf"(?<![\w.]){re.escape(label)}(?![\w@]|\.\w)",
        re.IGNORECASE,
    )
    match = pattern.search(body)
    if not match:
        return None
    start = max(0, match.start() - 80)
    end = min(len(body), match.end() + 80)
    return clean_excerpt(body[start:end])
