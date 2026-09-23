"""Derived entity profiles: a reconstruction, never a canonical description.

An entity record may carry an authored ``description`` — a human's account of
what the thing is. Most entities never get one. Before this module, that meant
"who is X?" had nothing to answer with even when the corpus plainly showed who
X was: a recorded relationship, an email address on a known domain, a sentence
in a meeting note saying what they do.

This layer reads that evidence and assembles a *profile*: a short list of
statements, each one carrying the documents that support it. It exists beside
the canonical record and never inside it. Nothing here is ever written back to
Markdown, because a generated description filed as canonical knowledge is the
new company fact the entity layer exists to prevent
(see ``model.PROTECTED_IDENTITY_FIELDS``).

What counts as evidence
-----------------------

Four kinds, in descending order of how much they say about identity:

``statement``
    A sentence in a document that identifies the entity outright — "Frank
    Godchaux is a co-founder of GANG". Quoted verbatim and attributed to the
    document, because the corpus said it and we did not.
``relationship``
    An evidence-backed relationship assertion someone recorded against a
    document, using the controlled predicate vocabulary.
``identifier``
    A canonical email address or domain on the record, attested in a document
    body. Stated as an identifier — "uses this address" — and never promoted
    into employment.
``involvement``
    Where and when the entity turns up. Presence, and presence only.

What is deliberately not evidence
---------------------------------

Participation. Appearing in an attendee list, a cc line, or five meetings in a
row supports "appears in the record" and supports nothing else. There is no
path in this module from a pattern of attendance to a title, a job, an
employer, or an ownership stake — the same rule ``ask/affiliation.py`` holds
for bands, applied to identity. When the evidence contains no role statement
at all, the profile says so in as many words rather than going quiet about it.

Everything is deterministic. No model is called, here or anywhere downstream
of here: the statements are structured records and quoted source text, and
rendering them needs string formatting rather than language generation.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from core.paths import GangPaths

from core.source_classes import classify_source, senders_from_body

from .model import EntityRecord, normalize_domain, normalize_name, string_value
from .store import EntityStore


#: Bumped whenever the builder's output could change for unchanged evidence.
#: Stored with every row, so a code change invalidates cached profiles exactly
#: the way changed evidence does.
PROFILE_BUILDER_VERSION = 2

PROFILE_PAYLOAD_VERSION = 1

#: Statement kinds, strongest identity signal first. The order is also the
#: order statements are rendered in.
STATEMENT_STATEMENT = "statement"
STATEMENT_RELATIONSHIP = "relationship"
STATEMENT_IDENTIFIER = "identifier"
STATEMENT_INVOLVEMENT = "involvement"

STATEMENT_KINDS = (
    STATEMENT_STATEMENT,
    STATEMENT_RELATIONSHIP,
    STATEMENT_IDENTIFIER,
    STATEMENT_INVOLVEMENT,
)

#: Documents read per entity when building. Generous enough to find a role
#: sentence, small enough that a rebuild over a whole corpus stays quick.
MAX_EVIDENCE_DOCUMENTS = 40

#: Linked documents considered before source classification picks the ones
#: worth reading. A mailbox owner is linked to every thread in the mailbox,
#: most of them newsletters and receipts, so the window has to be wider than
#: the evidence it yields.
MAX_CANDIDATE_DOCUMENTS = 400

#: Characters from each end of a body used to classify its source. Sender
#: lines sit at the top of a thread; unsubscribe footers at the bottom.
CLASSIFY_WINDOW = 4000

#: Documents a finished profile may cite. Matches the research document bound
#: in `ask/research.py`, so no statement arrives at the answer uncitable.
MAX_CITED_DOCUMENTS = 12

MAX_STATEMENTS = 12
MAX_QUOTED_STATEMENTS = 4
MAX_RELATIONSHIPS = 8
MAX_IDENTIFIER_STATEMENTS = 4
MAX_CITATIONS_PER_STATEMENT = 4
MAX_QUOTE = 240

#: Body prefix scanned for identity sentences. A Drive export can run to
#: megabytes; an identity sentence is near the top or it is somewhere a
#: regular search should find instead.
MAX_BODY_SCAN = 20000

#: Lines that record who was on a thread or in a room. A name inside one of
#: these is a name on a list — never the subject of a statement about itself.
#: Mirrors ``ask/affiliation.py``; kept local because the entity layer must
#: not import the Ask layer, which imports it.
PARTICIPANT_LINE = re.compile(
    r"(?:^|\s)(?:Participants|Attendees|Present|From|To|Cc|CC|Bcc|Subject|Sent|Date)"
    r"\s*:\s*(?P<value>[^\n]{1,400})",
    re.IGNORECASE,
)

#: The same headers, but bounded for measuring *where a list ends*. The index
#: collapses newlines, so a header and the paragraph beneath it arrive as one
#: run of text; stopping at sentence punctuation keeps prose that merely
#: follows an attendee list from being counted as part of it. Narrower than
#: ``PARTICIPANT_LINE`` on purpose: a subject line is not a roster.
PARTICIPANT_SPAN = re.compile(
    r"(?:^|\s)(?:Participants|Attendees|Present|From|To|Cc|CC|Bcc)\s*:\s*[^.?!]{0,400}",
    re.IGNORECASE,
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

#: Verbs that introduce a statement of identity rather than a statement of
#: activity. "Leads" and "owns" are missing on purpose: they assign work, and
#: assigning work is not a title.
_COPULA = (
    r"(?:is|was|are|were|serves\s+as|served\s+as|acts\s+as|acted\s+as|"
    r"works\s+as|worked\s+as|joined\s+as|remains|became)"
)

#: Nouns that name a role, an affiliation, or a family relationship. Required
#: for a person: without one, "Frank is out Friday" reads as an identity.
_ROLE_NOUN = re.compile(
    r"\b(?:co-?founders?|founders?|ceo|cto|coo|cfo|c[a-z]o|president|vice\s+president|"
    r"chair(?:man|woman|person)?|board\s+members?|directors?|officers?|partners?|"
    r"principals?|heads?\s+of|managers?|engineers?|designers?|developers?|"
    r"architects?|attorneys?|lawyers?|counsel|advis[eo]rs?|consultants?|"
    r"contractors?|suppliers?|vendors?|investors?|shareholders?|co-?owners?|"
    r"owners?|employees?|staff|members?|clients?|customers?|representatives?|"
    r"accountants?|bookkeepers?|controllers?|treasurers?|secretary|interns?|"
    r"liaisons?|colleagues?|co-?workers?|"
    r"brothers?|sisters?|fathers?|mothers?|sons?|daughters?|wives|wife|husbands?|"
    r"spouses?|parents?|cousins?|uncles?|aunts?|nephews?|nieces?|"
    r"grand(?:father|mother|son|daughter)s?)\b",
    re.IGNORECASE,
)

#: Complements that describe a state rather than a kind. Guards the
#: non-person pattern, where any "X is a …" would otherwise read as a
#: definition.
_STATUS_COMPLEMENT = re.compile(
    r"^\s*(?:go|no-?go|mess|problem|priority|blocker|risk|concern|"
    r"few\s+days?|week|month|day)\b",
    re.IGNORECASE,
)

#: How a recorded predicate reads in a sentence. Keys are the controlled
#: vocabulary in ``model.PREDICATES``.
PREDICATE_PHRASES = {
    "affiliated_with": "is affiliated with",
    "involved_in": "is involved in",
    "works_on": "works on",
    "represents": "represents",
    "supplied_by": "is supplied by",
    "related_to": "is related to",
}

PROFILE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS entity_profiles (
    entity_id TEXT PRIMARY KEY,
    builder_version INTEGER NOT NULL,
    evidence_fingerprint TEXT NOT NULL,
    built_at TEXT NOT NULL,
    payload TEXT NOT NULL
);
"""


# ----------------------------------------------------------------- the model


@dataclass(frozen=True)
class ProfileStatement:
    """One cited assertion in a derived profile.

    ``document_ids`` is not decoration. A statement that loses its supporting
    documents is dropped rather than shown, both here and at render time.
    """

    kind: str
    text: str
    document_ids: List[str] = field(default_factory=list)
    quote: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "kind": self.kind,
            "text": self.text,
            "document_ids": list(self.document_ids),
        }
        if self.quote:
            payload["quote"] = self.quote
        return payload

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "ProfileStatement":
        return cls(
            kind=string_value(payload.get("kind")),
            text=string_value(payload.get("text")),
            document_ids=[string_value(value) for value in payload.get("document_ids") or []],
            quote=string_value(payload.get("quote")),
        )


@dataclass(frozen=True)
class DerivedProfile:
    """A reconstructed account of an entity. Generated, citable, disposable."""

    entity_id: str
    entity_type: str
    name: str
    statements: List[ProfileStatement] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    evidence_fingerprint: str = ""
    built_at: str = ""
    builder_version: int = PROFILE_BUILDER_VERSION

    @property
    def role_evidence(self) -> bool:
        """Whether anything in the evidence states a role or a relationship.

        ``False`` is the ordinary case for someone who only ever appears on a
        list, and the answer says so out loud rather than leaving the reader
        to assume the silence means something.
        """
        return any(
            statement.kind in (STATEMENT_STATEMENT, STATEMENT_RELATIONSHIP)
            for statement in self.statements
        )

    @property
    def basis(self) -> List[str]:
        kinds = {statement.kind for statement in self.statements}
        return [kind for kind in STATEMENT_KINDS if kind in kinds]

    def document_ids(self) -> List[str]:
        """Supporting documents, strongest statement first, bounded."""
        ordered: List[str] = []
        for kind in STATEMENT_KINDS:
            for statement in self.statements:
                if statement.kind != kind:
                    continue
                for document_id in statement.document_ids:
                    if document_id and document_id not in ordered:
                        ordered.append(document_id)
        return ordered[:MAX_CITED_DOCUMENTS]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": PROFILE_PAYLOAD_VERSION,
            "entity_id": self.entity_id,
            "entity_type": self.entity_type,
            "name": self.name,
            "aliases": list(self.aliases),
            "statements": [statement.to_dict() for statement in self.statements],
            "document_ids": self.document_ids(),
            "basis": self.basis,
            "role_evidence": self.role_evidence,
            # Carried in the payload itself so that anything reading a profile
            # — the CLI, the Ask records, a JSON dump — sees what it is
            # without having to know where it came from.
            "derived": True,
            "canonical": False,
            "builder_version": self.builder_version,
            "evidence_fingerprint": self.evidence_fingerprint,
            "built_at": self.built_at,
        }

    @classmethod
    def from_dict(cls, payload: Dict[str, Any]) -> "DerivedProfile":
        return cls(
            entity_id=string_value(payload.get("entity_id")),
            entity_type=string_value(payload.get("entity_type")),
            name=string_value(payload.get("name")),
            statements=[
                ProfileStatement.from_dict(item)
                for item in payload.get("statements") or []
                if isinstance(item, dict)
            ],
            aliases=[string_value(value) for value in payload.get("aliases") or []],
            evidence_fingerprint=string_value(payload.get("evidence_fingerprint")),
            built_at=string_value(payload.get("built_at")),
            builder_version=int(payload.get("builder_version") or 0),
        )


# -------------------------------------------------------------- the evidence


@dataclass(frozen=True)
class EvidenceDocument:
    document_id: str
    title: str
    type: str
    source_type: str
    created: str
    updated: str
    body: str

    @property
    def date(self) -> str:
        return (self.updated or self.created or "")[:10]


@dataclass(frozen=True)
class RelationshipEvidence:
    relationship_id: str
    predicate: str
    direction: str
    other_name: str
    other_entity_id: str
    document_id: str
    excerpt: str


@dataclass(frozen=True)
class EntityEvidence:
    documents: List[EvidenceDocument] = field(default_factory=list)
    relationships: List[RelationshipEvidence] = field(default_factory=list)
    #: Canonical domain -> the company that owns it. Lets an address be
    #: reported as being on a known organization's domain, which is a fact
    #: about the address and not a fact about anyone's employment.
    domain_owners: Dict[str, str] = field(default_factory=dict)


class ProfileEvidenceReader:
    """Read-only evidence lookups against the generated knowledge index."""

    def __init__(self, index_path: Path | str):
        self.index_path = Path(index_path)

    def available(self) -> bool:
        if not self.index_path.exists():
            return False
        try:
            with closing(self._connect()) as connection:
                names = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    )
                }
        except sqlite3.DatabaseError:
            return False
        return {"documents", "document_entity_mentions", "relationships"}.issubset(names)

    def fingerprint(self, record: EntityRecord, *, records: Sequence[EntityRecord] = ()) -> str:
        """A cheap hash of everything a profile is built from.

        Indexed lookups only — no document bodies — so checking whether a
        cached profile is still good costs far less than rebuilding it.
        """
        with closing(self._connect()) as connection:
            mentions = connection.execute(
                """
                SELECT m.document_id AS document_id, d.content_hash AS content_hash
                FROM document_entity_mentions m
                JOIN documents d ON d.document_id = m.document_id
                WHERE m.entity_id = ?
                ORDER BY m.document_id ASC
                """,
                (record.id,),
            ).fetchall()
            relationships = connection.execute(
                """
                SELECT relationship_id, predicate, subject_entity_id, object_entity_id,
                       document_id, evidence_excerpt
                FROM relationships
                WHERE status = 'active' AND (subject_entity_id = ? OR object_entity_id = ?)
                ORDER BY relationship_id ASC
                """,
                (record.id, record.id),
            ).fetchall()

        payload = {
            "builder_version": PROFILE_BUILDER_VERSION,
            "entity": [
                record.id,
                record.type,
                record.name,
                record.status,
                record.updated,
                sorted(record.aliases),
                sorted(record.emails),
                sorted(record.domains),
            ],
            "mentions": [[row["document_id"], row["content_hash"] or ""] for row in mentions],
            "relationships": [list(row) for row in relationships],
            "domain_owners": sorted(_domain_owners(records, exclude=record.id).items()),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    def collect(
        self, record: EntityRecord, *, records: Sequence[EntityRecord] = ()
    ) -> EntityEvidence:
        with closing(self._connect()) as connection:
            documents = self._evidence_documents(connection, record, records)
            relationships = [
                RelationshipEvidence(
                    relationship_id=row["relationship_id"],
                    predicate=row["predicate"] or "",
                    direction="outbound" if row["subject_entity_id"] == record.id else "inbound",
                    other_name=(
                        row["object_name"] or row["object_entity_id"]
                        if row["subject_entity_id"] == record.id
                        else row["subject_name"] or row["subject_entity_id"]
                    ),
                    other_entity_id=(
                        row["object_entity_id"]
                        if row["subject_entity_id"] == record.id
                        else row["subject_entity_id"]
                    ),
                    document_id=row["document_id"] or "",
                    excerpt=row["evidence_excerpt"] or "",
                )
                for row in connection.execute(
                    """
                    SELECT r.relationship_id, r.predicate, r.subject_entity_id,
                           r.object_entity_id, r.document_id, r.evidence_excerpt,
                           s.name AS subject_name, o.name AS object_name
                    FROM relationships r
                    LEFT JOIN entities s ON s.entity_id = r.subject_entity_id
                    LEFT JOIN entities o ON o.entity_id = r.object_entity_id
                    WHERE r.status = 'active'
                      AND (r.subject_entity_id = ? OR r.object_entity_id = ?)
                    ORDER BY r.relationship_id ASC
                    LIMIT ?
                    """,
                    (record.id, record.id, MAX_RELATIONSHIPS),
                )
            ]

        return EntityEvidence(
            documents=documents,
            relationships=relationships,
            domain_owners=_domain_owners(records, exclude=record.id),
        )

    def _evidence_documents(
        self, connection: sqlite3.Connection, record: EntityRecord, records: Sequence[EntityRecord]
    ) -> List[EvidenceDocument]:
        """The linked documents worth reading, most authoritative first.

        Bulk and automated mail is dropped before anything is read from it:
        being the recipient of a newsletter is not evidence of who someone
        is, however recent the newsletter. Among what remains, corporate
        records and company documents come ahead of meeting notes, and
        meeting notes ahead of ordinary email; recency breaks ties.
        """
        known_addresses = {email for item in records if item.status == "active" for email in item.emails}
        known_domains = {domain for item in records if item.status == "active" for domain in item.domains}
        candidates = connection.execute(
            """
            SELECT d.document_id, d.title, d.type, d.source_type, d.created, d.updated,
                   substr(d.body, 1, ?) AS head,
                   CASE WHEN length(d.body) > ? THEN substr(d.body, -?) ELSE '' END AS tail
            FROM document_entity_mentions m
            JOIN documents d ON d.document_id = m.document_id
            WHERE m.entity_id = ?
            GROUP BY d.document_id
            ORDER BY COALESCE(NULLIF(d.updated, ''), d.created) DESC,
                     d.document_id ASC
            LIMIT ?
            """,
            (CLASSIFY_WINDOW, CLASSIFY_WINDOW, CLASSIFY_WINDOW, record.id, MAX_CANDIDATE_DOCUMENTS),
        ).fetchall()

        ranked: List[tuple] = []
        for position, row in enumerate(candidates):
            sample = f"{row['head'] or ''}\n{row['tail'] or ''}"
            source = classify_source(
                title=row["title"] or "",
                source_type=row["source_type"] or "",
                document_type=row["type"] or "",
                senders=senders_from_body(row["head"] or ""),
                body=sample,
                known_addresses=known_addresses,
                known_domains=known_domains,
            )
            if not source.identity_evidence:
                continue
            ranked.append((-source.rank, position, row["document_id"]))
        chosen = [document_id for _, _, document_id in sorted(ranked)[:MAX_EVIDENCE_DOCUMENTS]]
        if not chosen:
            return []

        placeholders = ", ".join("?" for _ in chosen)
        rows = {
            row["document_id"]: row
            for row in connection.execute(
                f"""
                SELECT document_id, title, type, source_type, created, updated,
                       substr(body, 1, ?) AS body
                FROM documents WHERE document_id IN ({placeholders})
                """,
                (MAX_BODY_SCAN, *chosen),
            )
        }
        return [
            EvidenceDocument(
                document_id=row["document_id"],
                title=row["title"] or row["document_id"],
                type=row["type"] or "",
                source_type=row["source_type"] or "",
                created=row["created"] or "",
                updated=row["updated"] or "",
                body=row["body"] or "",
            )
            for row in (rows[document_id] for document_id in chosen if document_id in rows)
        ]

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(f"file:{self.index_path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection


def _domain_owners(records: Sequence[EntityRecord], *, exclude: str = "") -> Dict[str, str]:
    owners: Dict[str, str] = {}
    for record in records:
        if record.id == exclude or record.status != "active":
            continue
        for domain in record.domains:
            normalized = normalize_domain(domain)
            if normalized and normalized not in owners:
                owners[normalized] = record.name
    return owners


# --------------------------------------------------------------- the builder


def build_profile(
    record: EntityRecord,
    evidence: EntityEvidence,
    *,
    fingerprint: str = "",
    now: Optional[str] = None,
) -> Optional[DerivedProfile]:
    """Assemble a profile, or ``None`` when the evidence does not support one.

    ``None`` is a real answer. An entity with a canonical record and nothing
    else is an identity with no account of itself, and the caller's job then
    is to say so, not to fill the gap.
    """
    if record.foundational:
        # An authored description exists. Deriving over it would be inventing
        # a second, competing identity for the same entity.
        return None

    forms = _surface_forms(record)
    statements: List[ProfileStatement] = []
    statements.extend(_quoted_statements(record, evidence, forms))
    statements.extend(_relationship_statements(record, evidence))
    statements.extend(_identifier_statements(record, evidence))
    statements.extend(_involvement_statements(record, evidence, forms, statements))

    statements = [statement for statement in statements if statement.document_ids][:MAX_STATEMENTS]
    if not statements:
        return None

    return DerivedProfile(
        entity_id=record.id,
        entity_type=record.type,
        name=record.name,
        statements=statements,
        aliases=list(record.aliases),
        evidence_fingerprint=fingerprint,
        built_at=now or _now_iso(),
    )


def _quoted_statements(
    record: EntityRecord, evidence: EntityEvidence, forms: Sequence[str]
) -> List[ProfileStatement]:
    """Sentences that identify the entity, quoted rather than paraphrased.

    Quoting matters. "The record states: 'Frank Godchaux is a co-founder'" is
    a fact about the corpus and is checkable against the cited document.
    "Frank Godchaux is a co-founder" would be a new company fact asserted by
    a program, which is not ours to assert.
    """
    found: List[ProfileStatement] = []
    seen: set = set()
    for document in evidence.documents:
        for sentence in _identity_sentences(document.body, forms, record.type):
            key = normalize_name(sentence)
            if key in seen:
                continue
            seen.add(key)
            found.append(
                ProfileStatement(
                    kind=STATEMENT_STATEMENT,
                    text=f"The record states: “{sentence}”",
                    document_ids=[document.document_id],
                    quote=sentence,
                )
            )
            if len(found) >= MAX_QUOTED_STATEMENTS:
                return found
    return found


def _relationship_statements(
    record: EntityRecord, evidence: EntityEvidence
) -> List[ProfileStatement]:
    statements: List[ProfileStatement] = []
    for relationship in evidence.relationships:
        phrase = PREDICATE_PHRASES.get(relationship.predicate)
        if not phrase or not relationship.document_id:
            continue
        subject, object_ = (
            (record.name, relationship.other_name)
            if relationship.direction == "outbound"
            else (relationship.other_name, record.name)
        )
        statements.append(
            ProfileStatement(
                kind=STATEMENT_RELATIONSHIP,
                text=f"Recorded relationship: {subject} {phrase} {object_}.",
                document_ids=[relationship.document_id],
                quote=_short(relationship.excerpt, MAX_QUOTE),
            )
        )
    return statements


def _identifier_statements(
    record: EntityRecord, evidence: EntityEvidence
) -> List[ProfileStatement]:
    """Canonical identifiers, reported only where a document attests them.

    The domain clause is the sharp edge here. Saying an address sits on a
    known company's domain is a statement about the address. Saying the
    person therefore works there would be a statement about their employment,
    which no address can support on its own — so the sentence stops.
    """
    statements: List[ProfileStatement] = []
    for value, kind in [(email, "email") for email in record.emails] + [
        (domain, "domain") for domain in record.domains
    ]:
        if not value:
            continue
        needle = value.casefold()
        document_ids = [
            document.document_id
            for document in evidence.documents
            if needle in document.body.casefold()
        ][:MAX_CITATIONS_PER_STATEMENT]
        if not document_ids:
            continue
        owner = evidence.domain_owners.get(
            normalize_domain(value.split("@")[-1] if kind == "email" else value)
        )
        if kind == "email":
            text = f"Uses the email address {value}"
            text += (
                f", which is on {owner}’s canonical email domain."
                if owner
                else "."
            )
        else:
            text = f"Associated with the domain {value}."
        statements.append(
            ProfileStatement(kind=STATEMENT_IDENTIFIER, text=text, document_ids=document_ids)
        )
        if len(statements) >= MAX_IDENTIFIER_STATEMENTS:
            break
    return statements


def _involvement_statements(
    record: EntityRecord,
    evidence: EntityEvidence,
    forms: Sequence[str],
    so_far: Sequence[ProfileStatement],
) -> List[ProfileStatement]:
    documents = list(evidence.documents)
    if not documents:
        return []

    cited = [document.document_id for document in documents[:MAX_CITATIONS_PER_STATEMENT]]
    dates = sorted(document.date for document in documents if document.date)
    span = ""
    if dates:
        span = f" between {dates[0]} and {dates[-1]}" if dates[0] != dates[-1] else f" on {dates[0]}"
    count = len(documents)
    noun = "document" if count == 1 else "documents"
    statements = [
        ProfileStatement(
            kind=STATEMENT_INVOLVEMENT,
            text=f"Appears in {count} {noun} in the private corpus{span}.",
            document_ids=cited,
        )
    ]

    listed = [
        document
        for document in documents
        if _named_only_in_participant_lines(document.body, forms)
    ]
    if listed and len(listed) == count:
        statements.append(
            ProfileStatement(
                kind=STATEMENT_INVOLVEMENT,
                text=(
                    "Every appearance is inside a participant, attendee, or address "
                    "line, which records presence only."
                ),
                document_ids=[document.document_id for document in listed][
                    :MAX_CITATIONS_PER_STATEMENT
                ],
            )
        )

    has_role = any(
        statement.kind in (STATEMENT_STATEMENT, STATEMENT_RELATIONSHIP) for statement in so_far
    )
    if not has_role:
        statements.append(
            ProfileStatement(
                kind=STATEMENT_INVOLVEMENT,
                text=(
                    "No document in this evidence states a role, title, employment, "
                    "or ownership for this entity, so none is claimed here."
                ),
                document_ids=cited,
            )
        )
    return statements


# ------------------------------------------------------------ sentence rules


def _surface_forms(record: EntityRecord) -> List[str]:
    """Name and aliases, longest first so a full name beats a bare one."""
    forms: List[str] = []
    for value in [record.name, *record.aliases]:
        text = string_value(value)
        if text and normalize_name(text) not in {normalize_name(item) for item in forms}:
            forms.append(text)
    return sorted(forms, key=lambda item: (-len(item), item.casefold()))


def _identity_sentences(body: str, forms: Sequence[str], entity_type: str) -> List[str]:
    """Sentences in which the entity is identified, not merely mentioned."""
    collapsed = re.sub(r"\s+", " ", body or "").strip()
    if not collapsed or not forms:
        return []

    found: List[str] = []
    for sentence in _SENTENCE_SPLIT.split(collapsed):
        sentence = sentence.strip()
        if not sentence or len(sentence) > 600:
            continue
        # A name on a header line is a name on a list. Nothing in such a
        # sentence identifies anybody, and reading it as though it did is
        # exactly how an attendee acquires a job title.
        if PARTICIPANT_LINE.search(sentence):
            continue
        for form in forms:
            complement = _identity_complement(sentence, form, entity_type)
            if complement is None:
                continue
            found.append(_short(sentence, MAX_QUOTE))
            break
    return found


def _identity_complement(sentence: str, form: str, entity_type: str) -> Optional[str]:
    """The complement of an identity clause about ``form``, if there is one.

    The name has to sit immediately before the verb. A proximity window would
    read "Dana is the certification owner" as a statement about Frank for
    standing in the same sentence, which is the attribution error that puts
    people in jobs they do not hold.
    """
    anchor = rf"(?<![\w'’-]){re.escape(form)}(?![\w'’-])"

    copular = re.search(
        rf"{anchor}\s+{_COPULA}\s+(?P<complement>[^.?!]{{1,180}})", sentence, re.IGNORECASE
    )
    appositive = re.search(
        rf"{anchor}\s*,\s*(?P<complement>(?:our|the|a|an)?\s*[^,.?!]{{1,140}}),",
        sentence,
        re.IGNORECASE,
    )

    for match in (copular, appositive):
        if match is None:
            continue
        complement = match.group("complement").strip()
        if not complement:
            continue
        if entity_type == "person":
            # A person needs a named role or relationship. Everything else a
            # person "is" in a working corpus is a status, a mood, or a
            # calendar entry.
            if _ROLE_NOUN.search(complement):
                return complement
            continue
        if match is copular:
            determined = re.match(
                r"(?:a|an|the)\s+(?P<rest>.+)", complement, re.IGNORECASE
            )
            if not determined:
                continue
            rest = determined.group("rest").strip()
            if _STATUS_COMPLEMENT.match(rest):
                continue
            if re.search(r"[A-Za-z]{3}", rest):
                return complement
        elif _ROLE_NOUN.search(complement):
            return complement
    return None


def _named_only_in_participant_lines(body: str, forms: Sequence[str]) -> bool:
    """Whether every occurrence of the entity's name sits on a header line."""
    collapsed = re.sub(r"\s+", " ", body or "")
    if not collapsed:
        return False
    spans = [match.span() for match in PARTICIPANT_SPAN.finditer(collapsed)]
    occurrences = 0
    for form in forms:
        for match in re.finditer(
            rf"(?<![\w'’-]){re.escape(form)}(?![\w'’-])", collapsed, re.IGNORECASE
        ):
            occurrences += 1
            if not any(start <= match.start() < end for start, end in spans):
                return False
    return occurrences > 0


# ----------------------------------------------------------------- the store


class ProfileStore:
    """Generated storage for derived profiles. Safe to delete at any time."""

    def __init__(self, database_path: Path | str):
        self.database_path = Path(database_path)

    def read(self, entity_id: str, *, fingerprint: str = "") -> Optional[DerivedProfile]:
        """A cached profile, but only while it still matches its evidence."""
        if not self.database_path.exists():
            return None
        try:
            with closing(self._connect()) as connection:
                row = connection.execute(
                    "SELECT payload, builder_version, evidence_fingerprint "
                    "FROM entity_profiles WHERE entity_id = ?",
                    (entity_id,),
                ).fetchone()
        except sqlite3.DatabaseError:
            return None
        if row is None:
            return None
        if int(row["builder_version"] or 0) != PROFILE_BUILDER_VERSION:
            return None
        if fingerprint and (row["evidence_fingerprint"] or "") != fingerprint:
            return None
        try:
            payload = json.loads(row["payload"])
        except (TypeError, ValueError):
            return None
        return DerivedProfile.from_dict(payload)

    def write(self, profile: DerivedProfile) -> None:
        with closing(self._connect(create=True)) as connection:
            connection.executescript(PROFILE_SCHEMA_SQL)
            connection.execute(
                """
                INSERT OR REPLACE INTO entity_profiles (
                    entity_id, builder_version, evidence_fingerprint, built_at, payload
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    profile.entity_id,
                    profile.builder_version,
                    profile.evidence_fingerprint,
                    profile.built_at,
                    json.dumps(profile.to_dict(), sort_keys=True),
                ),
            )
            connection.commit()

    def delete(self, entity_id: str) -> None:
        if not self.database_path.exists():
            return
        with closing(self._connect()) as connection:
            connection.executescript(PROFILE_SCHEMA_SQL)
            connection.execute("DELETE FROM entity_profiles WHERE entity_id = ?", (entity_id,))
            connection.commit()

    def entity_ids(self) -> List[str]:
        if not self.database_path.exists():
            return []
        with closing(self._connect()) as connection:
            connection.executescript(PROFILE_SCHEMA_SQL)
            return [
                row["entity_id"]
                for row in connection.execute(
                    "SELECT entity_id FROM entity_profiles ORDER BY entity_id ASC"
                )
            ]

    def count(self) -> int:
        return len(self.entity_ids())

    def clear(self) -> int:
        removed = self.count()
        if self.database_path.exists():
            self.database_path.unlink()
        return removed

    def _connect(self, *, create: bool = False) -> sqlite3.Connection:
        if create:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection


# --------------------------------------------------------------- the service


class EntityProfileService:
    """Build, cache, and serve derived profiles.

    The cache is an optimization and nothing more: ``profile()`` produces the
    same answer whether or not ``build_all()`` has ever run, which is what
    makes "who is X?" work on a machine that has never precomputed anything.
    """

    def __init__(
        self,
        *,
        root_path: Path | str = Path("."),
        private_home: Path | str | None = None,
        store: Optional[EntityStore] = None,
    ):
        self.root_path = Path(root_path).resolve()
        self.paths = GangPaths.from_env(repo_root=self.root_path, gang_home=private_home)
        self.entities = store or EntityStore(
            root_path=self.root_path, private_home=self.paths.home
        )
        self.reader = ProfileEvidenceReader(self.paths.index_path)
        self.profiles = ProfileStore(self.paths.entity_profiles_path)

    def profile(
        self,
        entity_id: str,
        *,
        refresh: bool = False,
        persist: bool = True,
        records: Optional[Sequence[EntityRecord]] = None,
    ) -> Optional[DerivedProfile]:
        """The derived profile for one entity, built on demand if need be."""
        loaded = list(records) if records is not None else self.entities.load_all()
        record = next((item for item in loaded if item.id == string_value(entity_id)), None)
        if record is None or record.status != "active" or record.foundational:
            return None
        if not self.reader.available():
            return None

        fingerprint = self.reader.fingerprint(record, records=loaded)
        if not refresh:
            cached = self.profiles.read(record.id, fingerprint=fingerprint)
            if cached is not None:
                return cached

        profile = build_profile(
            record, self.reader.collect(record, records=loaded), fingerprint=fingerprint
        )
        if persist:
            self._remember(record.id, profile)
        return profile

    def build_all(
        self, *, entity_type: Optional[str] = None, force: bool = False
    ) -> Dict[str, Any]:
        """Precompute every profile the evidence supports."""
        records = self.entities.load_all()
        rows: List[Dict[str, Any]] = []
        counts = {"built": 0, "authored": 0, "insufficient": 0, "skipped": 0}

        for record in sorted(records, key=lambda item: (item.type, item.name.casefold())):
            if entity_type and record.type != entity_type:
                continue
            if record.status != "active":
                counts["skipped"] += 1
                self.profiles.delete(record.id)
                continue
            if record.foundational:
                # The authored description is the answer. A derived profile
                # beside it would only ever be the wrong one to reach for.
                counts["authored"] += 1
                self.profiles.delete(record.id)
                continue

            profile = self.profile(record.id, refresh=force, records=records)
            if profile is None:
                counts["insufficient"] += 1
                rows.append(
                    {
                        "entity_id": record.id,
                        "name": record.name,
                        "type": record.type,
                        "status": "insufficient-evidence",
                        "statements": 0,
                    }
                )
                continue
            counts["built"] += 1
            rows.append(
                {
                    "entity_id": record.id,
                    "name": record.name,
                    "type": record.type,
                    "status": "built",
                    "statements": len(profile.statements),
                    "basis": profile.basis,
                    "role_evidence": profile.role_evidence,
                }
            )

        return {
            "database": str(self.paths.entity_profiles_path),
            "index_available": self.reader.available(),
            "entities": len(rows) + counts["authored"] + counts["skipped"],
            **counts,
            "profiles": rows,
        }

    def clear(self) -> int:
        return self.profiles.clear()

    def _remember(self, entity_id: str, profile: Optional[DerivedProfile]) -> None:
        """Cache, or forget. A failed write is not worth failing an answer for."""
        try:
            if profile is None:
                self.profiles.delete(entity_id)
            else:
                self.profiles.write(profile)
        except (OSError, sqlite3.DatabaseError):
            pass


# ------------------------------------------------------------------- helpers


def _short(text: str, limit: int) -> str:
    value = re.sub(r"\s+", " ", string_value(text)).strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
