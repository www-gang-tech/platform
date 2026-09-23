"""The shape of a generated evidence fact, and the one gate every fact passes.

An entity mention says a document refers to someone. An evidence fact says
what the document *states* about them — "Daniel Hirunrusme is a co-founder of
GANG" — and carries the exact words that state it. The difference matters:
a thousand mentions in a mailbox are presence, and one signature line is a
role.

Facts are generated. They live in their own SQLite file under
``GANG_HOME/generated``, they are rebuilt from canonical documents whenever
those documents or the extractor change, and nothing here ever writes to
canonical Markdown. A fact the extractor gets wrong is fixed by fixing the
extractor or by suppressing the fact, never by editing the source.

The proposal boundary
---------------------

Every fact enters the store as a :class:`ClaimProposal` and leaves
:func:`validate_proposal` as an :class:`EvidenceFact` or not at all. The
deterministic rules in ``extract.py`` are one proposer. A future local
enrichment worker would be another, producing the same proposal for the
documents rules cannot parse — and it would pass the same gate: an allowed
predicate, resolved active entities of the right types, and a supporting
quote that is verified against the source text rather than trusted. Remote
models are not a permitted method at all, and anything that is not a
deterministic rule is capped below the confidence Ask will show.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, List, Mapping, Sequence


#: Bumped whenever extraction output could change for unchanged evidence.
#: Stored with every source row, so a code change invalidates generated facts
#: exactly the way changed evidence does.
EXTRACTOR_VERSION = 1

FACTS_SCHEMA_VERSION = 1

# ------------------------------------------------------------- vocabulary

COFOUNDER_OF = "cofounder_of"
FOUNDER_OF = "founder_of"
WORKS_FOR = "works_for"
PARTNER_AT = "partner_at"
ADVISOR_TO = "advisor_to"
VENDOR_FOR = "vendor_for"
MANUFACTURER_FOR = "manufacturer_for"
RESPONSIBLE_FOR = "responsible_for"

#: Deliberately small. Expanding it is a future epic, not a config knob, and
#: it is separate from the canonical relationship vocabulary in
#: ``entities.model.PREDICATES`` because these are generated claims, not
#: human assertions.
RELATION_PREDICATES = (
    COFOUNDER_OF,
    FOUNDER_OF,
    WORKS_FOR,
    PARTNER_AT,
    ADVISOR_TO,
    VENDOR_FOR,
    MANUFACTURER_FOR,
    RESPONSIBLE_FOR,
)

#: ``(subject types, object types)`` per predicate. ``"value"`` means the
#: object may be a typed text value instead of an entity.
PREDICATE_SHAPES: Dict[str, tuple] = {
    COFOUNDER_OF: (("person",), ("company",)),
    FOUNDER_OF: (("person",), ("company",)),
    WORKS_FOR: (("person",), ("company",)),
    PARTNER_AT: (("person",), ("company",)),
    ADVISOR_TO: (("person", "company"), ("company", "person")),
    VENDOR_FOR: (("person", "company"), ("company",)),
    MANUFACTURER_FOR: (("company",), ("company", "product")),
    RESPONSIBLE_FOR: (("person", "company"), ("project", "product", "value")),
}

#: How a predicate reads in an answer sentence.
PREDICATE_PHRASES = {
    COFOUNDER_OF: "is a co-founder of",
    FOUNDER_OF: "is a founder of",
    WORKS_FOR: "works for",
    PARTNER_AT: "is a partner at",
    ADVISOR_TO: "is an advisor to",
    VENDOR_FOR: "is a vendor for",
    MANUFACTURER_FOR: "is a manufacturer for",
    RESPONSIBLE_FOR: "is responsible for",
}

#: Role facts first when rendering an identity: they answer "who is X?".
PREDICATE_ORDER = {predicate: index for index, predicate in enumerate(RELATION_PREDICATES)}

# ---------------------------------------------------------------- methods

METHOD_DETERMINISTIC = "deterministic-rule"
#: Reserved for a future on-device enrichment worker (Phase 4). Nothing in V1
#: produces it; the validator already knows how to hold it to account.
METHOD_LOCAL_MODEL = "local-model"
ALLOWED_METHODS = (METHOD_DETERMINISTIC, METHOD_LOCAL_MODEL)

CONFIDENCE_HIGH = "high"
CONFIDENCE_MEDIUM = "medium"
CONFIDENCE_LOW = "low"
CONFIDENCE_LEVELS = (CONFIDENCE_HIGH, CONFIDENCE_MEDIUM, CONFIDENCE_LOW)
CONFIDENCE_RANK = {CONFIDENCE_HIGH: 3, CONFIDENCE_MEDIUM: 2, CONFIDENCE_LOW: 1}

# ------------------------------------------------------------- decisions

STATUS_DECIDED = "decided"
STATUS_APPROVED = "approved"
STATUS_ALIGNED = "aligned"
STATUS_AGREED = "agreed"
STATUS_REJECTED = "rejected"
STATUS_NOT_DECIDED = "not decided"
DECISION_STATUSES = (
    STATUS_DECIDED,
    STATUS_APPROVED,
    STATUS_ALIGNED,
    STATUS_AGREED,
    STATUS_REJECTED,
    STATUS_NOT_DECIDED,
)

MAX_EXCERPT = 500
MAX_VALUE = 160
MAX_DECISION_TEXT = 600
MAX_CONTEXT = 120


class ClaimValidationError(ValueError):
    """A proposed claim failed the gate and was not stored."""


# ------------------------------------------------------------------ text


def display_text(value: Any) -> str:
    """Source text as stored in an excerpt: emphasis markers dropped,
    whitespace collapsed, nothing else touched."""
    text = str(value or "").replace("*", "")
    return re.sub(r"\s+", " ", text).strip()


def verification_text(value: Any) -> str:
    """The form a quote is verified in.

    Whitespace, Markdown emphasis, and inline-code markers are presentation;
    everything else must match character for character. The generated index
    stores bodies with exactly those markers stripped and whitespace
    collapsed, so the same check works against a canonical file and against
    the index row that cites it.
    """
    text = re.sub(r"[*_`]", "", str(value or ""))
    return re.sub(r"\s+", " ", text).strip()


def quote_in_source(quote: str, source: str) -> bool:
    needle = verification_text(quote)
    return bool(needle) and needle in verification_text(source)


def readable(value: Any) -> str:
    """For display only: undo the HTML escaping mail bodies arrive with."""
    return html.unescape(str(value or ""))


# ----------------------------------------------------------------- records


@dataclass(frozen=True)
class ClaimProposal:
    """A claim offered for storage. Untrusted until validated."""

    document_id: str
    subject_entity_id: str
    predicate: str
    excerpt: str
    method: str
    rule: str = ""
    object_entity_id: str = ""
    object_value: str = ""
    #: A title or role qualifier stated in the evidence ("Chief Executive
    #: Officer"), kept verbatim. Never promoted into the predicate.
    role: str = ""
    confidence: str = CONFIDENCE_HIGH


@dataclass(frozen=True)
class EvidenceFact:
    """A validated generated fact. Citable, rebuildable, never canonical."""

    fact_id: str
    document_id: str
    subject_entity_id: str
    predicate: str
    excerpt: str
    method: str
    rule: str
    confidence: str
    extractor_version: int
    source_hash: str
    source_class: str
    source_rank: int
    document_date: str = ""
    object_entity_id: str = ""
    object_value: str = ""
    object_value_type: str = ""
    role: str = ""
    #: Filled at read time from the entity registry; not stored.
    subject_name: str = ""
    object_name: str = ""
    document_title: str = ""
    suppressed: bool = False

    @property
    def object_label(self) -> str:
        return self.object_name or self.object_value or self.object_entity_id

    def sentence(self) -> str:
        """The claim as one sentence of prose, from structure alone."""
        subject = self.subject_name or self.subject_entity_id
        if self.predicate == WORKS_FOR and self.role:
            return f"{subject} is {_article_role(self.role)} at {self.object_label}."
        phrase = PREDICATE_PHRASES.get(self.predicate, self.predicate.replace("_", " "))
        return f"{subject} {phrase} {self.object_label}."

    def claim_key(self) -> tuple:
        """What the fact asserts, independent of which document asserts it."""
        return (
            self.subject_entity_id,
            self.predicate,
            self.object_entity_id or self.object_value.casefold(),
            self.role.casefold() if self.predicate == WORKS_FOR else "",
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "document_id": self.document_id,
            "document_title": self.document_title,
            "document_date": self.document_date,
            "subject_entity_id": self.subject_entity_id,
            "subject_name": self.subject_name,
            "predicate": self.predicate,
            "object_entity_id": self.object_entity_id,
            "object_name": self.object_name,
            "object_value": self.object_value,
            "object_value_type": self.object_value_type,
            "role": self.role,
            "excerpt": self.excerpt,
            "method": self.method,
            "rule": self.rule,
            "confidence": self.confidence,
            "extractor_version": self.extractor_version,
            "source_hash": self.source_hash,
            "source_class": self.source_class,
            "source_rank": self.source_rank,
            "suppressed": self.suppressed,
            "sentence": self.sentence(),
            "generated": True,
            "canonical": False,
        }


@dataclass(frozen=True)
class DecisionRecord:
    """An explicit decision statement, materialized from its source."""

    decision_id: str
    document_id: str
    text: str
    status: str
    method: str
    rule: str
    extractor_version: int
    source_hash: str
    source_class: str
    source_rank: int
    decision_date: str = ""
    #: The label or section the decision was recorded under ("Packaging",
    #: "6. Double-Box Packaging Strategy"). Part of what a topic matches.
    context: str = ""
    document_title: str = ""
    #: Other documents recording the same decision verbatim (forwards,
    #: re-sends). Filled when records are grouped for display.
    corroborating_document_ids: List[str] = field(default_factory=list)
    suppressed: bool = False

    def document_ids(self) -> List[str]:
        ordered = [self.document_id]
        for value in self.corroborating_document_ids:
            if value and value not in ordered:
                ordered.append(value)
        return ordered

    def to_dict(self) -> Dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "document_id": self.document_id,
            "document_ids": self.document_ids(),
            "document_title": self.document_title,
            "text": self.text,
            "status": self.status,
            "context": self.context,
            "date": self.decision_date,
            "method": self.method,
            "rule": self.rule,
            "extractor_version": self.extractor_version,
            "source_hash": self.source_hash,
            "source_class": self.source_class,
            "source_rank": self.source_rank,
            "suppressed": self.suppressed,
            "generated": True,
            "canonical": False,
        }


# ----------------------------------------------------------------- ids


def fact_id(
    *,
    document_id: str,
    subject_entity_id: str,
    predicate: str,
    object_entity_id: str,
    object_value: str,
    role: str,
    excerpt: str,
) -> str:
    """Stable across rebuilds and extractor versions, so a suppression keyed
    on it keeps applying to the same claim from the same words."""
    digest = hashlib.sha256(
        "|".join(
            [
                document_id,
                subject_entity_id,
                predicate,
                object_entity_id,
                object_value.casefold(),
                role.casefold(),
                verification_text(excerpt),
            ]
        ).encode("utf-8")
    ).hexdigest()
    return f"fact_{digest[:32]}"


def decision_id(*, document_id: str, text: str) -> str:
    digest = hashlib.sha256(
        "|".join([document_id, normalized_statement(text)]).encode("utf-8")
    ).hexdigest()
    return f"dec_{digest[:32]}"


def normalized_statement(text: str) -> str:
    """Compare decision statements across documents: case, punctuation, and
    spacing folded, words kept."""
    folded = verification_text(readable(text)).casefold()
    return re.sub(r"[^\w]+", " ", folded).strip()


# ------------------------------------------------------------ validation


def validate_proposal(
    proposal: ClaimProposal,
    *,
    source_text: str,
    entities: Mapping[str, Any],
    surface_forms: Mapping[str, Sequence[str]],
) -> ClaimProposal:
    """Admit a proposal or raise :class:`ClaimValidationError`.

    ``entities`` maps entity id to a record with ``type`` and ``status``;
    ``surface_forms`` maps entity id to the names, aliases, and addresses the
    excerpt may use to refer to it. Returns the proposal, possibly with its
    confidence lowered — never raised.
    """
    if proposal.method not in ALLOWED_METHODS:
        raise ClaimValidationError(
            f"Unsupported extraction method {proposal.method!r}. Remote models are not a "
            "permitted source of generated facts."
        )
    if proposal.predicate not in RELATION_PREDICATES:
        raise ClaimValidationError(f"Predicate {proposal.predicate!r} is not in the controlled vocabulary")
    if proposal.confidence not in CONFIDENCE_LEVELS:
        raise ClaimValidationError(f"Unsupported confidence {proposal.confidence!r}")
    if not proposal.document_id:
        raise ClaimValidationError("A claim must name the document that supports it")

    subject_types, object_types = PREDICATE_SHAPES[proposal.predicate]
    subject = _active_entity(entities, proposal.subject_entity_id, "subject")
    if subject.type not in subject_types:
        raise ClaimValidationError(
            f"{proposal.predicate} needs a {' or '.join(subject_types)} subject, not a {subject.type}"
        )

    has_entity = bool(proposal.object_entity_id)
    has_value = bool(proposal.object_value.strip())
    if has_entity == has_value:
        raise ClaimValidationError("A claim needs exactly one object: an entity or a typed value")
    if has_entity:
        target = _active_entity(entities, proposal.object_entity_id, "object")
        if target.type not in object_types:
            raise ClaimValidationError(
                f"{proposal.predicate} cannot take a {target.type} object"
            )
        if proposal.object_entity_id == proposal.subject_entity_id:
            raise ClaimValidationError("A claim's subject and object must differ")
    else:
        if "value" not in object_types:
            raise ClaimValidationError(f"{proposal.predicate} requires an entity object")
        if len(proposal.object_value) > MAX_VALUE:
            raise ClaimValidationError("Typed object value is too long to be a stated value")

    excerpt = proposal.excerpt.strip()
    if not excerpt:
        raise ClaimValidationError("A claim requires an exact supporting excerpt")
    if len(excerpt) > MAX_EXCERPT:
        raise ClaimValidationError("Supporting excerpt exceeds the excerpt limit")
    if not quote_in_source(excerpt, source_text):
        raise ClaimValidationError("Supporting excerpt does not appear in the source document")

    # The quote has to be *about* these entities, not merely from the same
    # document: both ends must be named inside the words that are cited.
    if not _names_entity(excerpt, surface_forms.get(proposal.subject_entity_id) or ()):
        raise ClaimValidationError("Supporting excerpt does not name the subject")
    if has_entity and not _names_entity(excerpt, surface_forms.get(proposal.object_entity_id) or ()):
        raise ClaimValidationError("Supporting excerpt does not name the object")
    if has_value and verification_text(proposal.object_value).casefold() not in verification_text(excerpt).casefold():
        raise ClaimValidationError("Supporting excerpt does not state the object value")
    if proposal.role and verification_text(proposal.role).casefold() not in verification_text(excerpt).casefold():
        raise ClaimValidationError("Supporting excerpt does not state the role")

    if proposal.method != METHOD_DETERMINISTIC and proposal.confidence == CONFIDENCE_HIGH:
        # A model-proposed claim can be useful and still not be the kind of
        # thing an answer states without a human having looked at it.
        proposal = replace(proposal, confidence=CONFIDENCE_MEDIUM)
    return proposal


def _active_entity(entities: Mapping[str, Any], entity_id: str, role: str):
    record = entities.get(entity_id or "")
    if record is None:
        raise ClaimValidationError(f"Claim {role} {entity_id!r} is not a resolved canonical entity")
    if getattr(record, "status", "active") != "active":
        raise ClaimValidationError(f"Claim {role} {entity_id!r} is not an active entity")
    return record


def _names_entity(excerpt: str, forms: Sequence[str]) -> bool:
    text = verification_text(excerpt)
    for form in forms:
        value = verification_text(form)
        if not value:
            continue
        if re.search(rf"(?<![\w-]){re.escape(value)}(?![\w-])", text, re.IGNORECASE):
            return True
    return False


def _article_role(role: str) -> str:
    role = role.strip()
    if re.match(r"(?i)^(?:the|a|an)\s", role):
        return role
    # "Chief Executive Officer" reads as a title; "engineer" needs an article.
    if role[:1].isupper():
        return role
    return ("an " if role[:1].lower() in "aeiou" else "a ") + role


def higher_confidence(value: str, floor: str) -> bool:
    return CONFIDENCE_RANK.get(value, 0) >= CONFIDENCE_RANK.get(floor, 0)
