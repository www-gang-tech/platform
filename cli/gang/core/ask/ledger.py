"""The claim ledger: what kind of statement is each sentence, and what backs it.

GANG may generate new ideas. It may not generate new company facts. Prose alone
cannot hold that line — "we should make certification the first gate" and "we
made certification the first gate" are one word apart and only one of them is
a claim about the company. So behind every answer sits a structured ledger in
which each claim declares its own epistemic type, and code checks whether the
evidence actually supports a claim of that type.

Four types are generated:

``fact``
    Directly stated by cited canonical evidence. Needs citations, and its
    figures, entity relationships, and any dependency it asserts must survive
    the deterministic grounding checks.
``synthesis``
    A conclusion drawn across several supported facts. Needs either its own
    citations or ``derived_from`` premises that are themselves grounded.
``recommendation``
    Normative advice. The advice itself needs no source — nobody wrote it down,
    that is the point — but any company fact it asserts does.
``idea``
    Novel creative output. May be genuinely new. May not be described as
    something the company already decided.

Two more are assigned by this module and never by a model:

``scenario``
    Follows from a user-supplied assumption rather than from the corpus (§25).
``uncertainty``
    What a fact or synthesis claim becomes when its grounding does not hold.
    Downgrading rather than deleting keeps the reasoning visible instead of
    quietly dropping the part that failed.

Nothing here invents a citation to satisfy a schema. A claim that cannot be
grounded is downgraded or rejected, and either way it is recorded.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Set

from . import diagnostics
from .grounding import (
    DEPENDENCY_NOT_APPLICABLE,
    DEPENDENCY_UNSUPPORTED,
    LINKAGE_NOT_APPLICABLE,
    LINKAGE_UNSUPPORTED,
    NUMERIC_NONE,
    NUMERIC_NOT_CONNECTED,
    NUMERIC_NOT_IN_EVIDENCE,
    check_dependency_grounding,
    check_entity_linkage,
    check_numeric_grounding,
    extract_numbers,
)


LEDGER_VERSION = "1"

FACT = "fact"
SYNTHESIS = "synthesis"
INFERENCE = "inference"
RECOMMENDATION = "recommendation"
IDEA = "idea"
SCENARIO = "scenario"
UNCERTAINTY = "uncertainty"

#: What a model is allowed to declare.
GENERATED_TYPES = (FACT, SYNTHESIS, INFERENCE, RECOMMENDATION, IDEA)
#: What may end up in a validated ledger.
CLAIM_TYPES = (FACT, SYNTHESIS, INFERENCE, RECOMMENDATION, IDEA, SCENARIO, UNCERTAINTY)

#: Types that state something as true of the company, and therefore need the
#: evidence to say it directly.
FACTUAL_TYPES = frozenset({FACT, SYNTHESIS})
#: Types that may be novel.
GENERATIVE_TYPES = frozenset({RECOMMENDATION, IDEA})

#: An inference needs at least this many grounded premises. One supported fact
#: restated with a hedge is not reasoning; it is a fact with a hedge on it.
MIN_INFERENCE_PREMISES = 2

ACCEPTED = "accepted"
DOWNGRADED = "downgraded"
FLAGGED = "flagged"

#: Where a claim came from. A ledger the model wrote and a ledger transcribed
#: from the model's own prose are both legitimate, and a reader auditing an
#: answer is entitled to know which one they are looking at.
MODEL = "model"
DETERMINISTIC_RECOVERY = "deterministic-recovery"

CLAIM_FIELDS = {"id", "type", "text", "citations", "derived_from", "based_on"}

MAX_CLAIMS = 24
MAX_CLAIM_TEXT = 600

_CITATION_MARKER = re.compile(r"\[(\d{1,3})\]")

#: A marker standing on its own, rather than one that is part of the text it
#: was copied from. Retrieved mail is full of "[1]00Start Certification.pdf" —
#: a numbered attachment list, not a citation — so a marker only reads as a
#: citation when nothing is glued to its right.
_STANDALONE_CITATION = re.compile(r"\[(\d{1,3})\](?![\w-])")
_CLAIM_ID = re.compile(r"^[A-Za-z0-9_-]{1,32}$")

#: Phrasing that presents a statement as reasoning rather than as record.
#: An inference must carry one of these, because the difference between
#: "X appears to be part of the core team" and "X is on the core team" is the
#: entire distinction the type exists to hold.
_INFERENCE_HEDGE = re.compile(
    r"\b(?:appears?\s+to|appear\s+to|seems?\s+to|seem\s+to|looks?\s+like|"
    r"suggests?|suggesting|indicates?|indicating|implies|implying|"
    r"consistent\s+with|points?\s+to|reads?\s+as|"
    r"likely|probably|apparently|presumably|evidently|"
    r"on\s+the\s+record|based\s+on\s+the\s+record|from\s+the\s+record|"
    r"the\s+(?:record|evidence|corpus)\s+(?:suggests?|indicates?|shows?|points)|"
    r"may\s+be|might\s+be|could\s+be|would\s+appear)\b",
    re.IGNORECASE,
)

#: Formal status the corpus has to state outright. Employment, titles, and
#: reporting lines are legal and organizational facts; a pattern of meeting
#: attendance is not evidence of any of them, however strong the pattern.
_FORMAL_STATUS = re.compile(
    r"\b(?:employee|employed|employment|staff\s+member|on\s+the\s+payroll|"
    r"hired|works\s+for|contractor\s+for|"
    r"(?:is|are|was|were|be|been|becomes?|became)\s+(?:the\s+|a\s+|an\s+)?"
    r"(?:ceo|cto|coo|cfo|founder|co-?founder|president|director|"
    r"vice\s+president|vp|head\s+of|chief\s+\w+|manager\s+of|"
    r"owner\s+of\s+the\s+company|partner\s+at)\b"
    r"|\breports?\s+to\b|\bdirect\s+report\b)",
    re.IGNORECASE,
)

#: Phrasing that turns a suggestion into a report of a decision already taken.
#: An idea may be anything except this.
_DECISION_ASSERTION = re.compile(
    r"\b(?:we|gang|the company|the team|the board|leadership)\s+"
    r"(?:have|has|had)?\s*(?:already\s+)?"
    r"(?:decided|adopted|agreed|approved|committed|chose|chosen|selected|"
    r"settled on|signed off|locked in|finali[sz]ed)\b"
    r"|\b(?:it\s+was|this\s+was)\s+(?:decided|agreed|approved)\b"
    r"|\bthe\s+decision\s+(?:was|has been)\b"
    r"|\bour\s+(?:current\s+)?(?:plan|decision|policy)\s+is\b"
    r"|\bis\s+(?:now\s+)?(?:our|the)\s+(?:plan|decision|policy|strategy)\b",
    re.IGNORECASE,
)

#: Hedges that make a generative claim read as generated. Their presence means
#: the decision-assertion pattern above was a false positive.
_GENERATIVE_HEDGE = re.compile(
    r"\b(?:i\s+would|i'd|we\s+could|you\s+could|consider|suggest|recommend|propose|"
    r"might|may\s+want|one\s+option|an\s+option|worth|if\s+it\s+were\s+me|"
    r"my\s+recommendation|idea|concept|what\s+if)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Claim:
    """One statement, its type, and everything backing it."""

    id: str
    type: str
    text: str
    citations: List[int] = field(default_factory=list)
    derived_from: List[str] = field(default_factory=list)
    based_on: List[str] = field(default_factory=list)
    numeric_check: str = NUMERIC_NONE
    entity_linkage: str = LINKAGE_NOT_APPLICABLE
    dependency_check: str = DEPENDENCY_NOT_APPLICABLE
    status: str = ACCEPTED
    origin: str = MODEL
    original_type: str = ""
    presented_as_decision: bool = False
    notes: List[str] = field(default_factory=list)

    @property
    def grounded(self) -> bool:
        """Whether this claim may be relied on as a premise by another claim.

        An inference is deliberately excluded. Reasoning may rest on facts; it
        may not rest on other reasoning, because that is how a chain of
        plausible steps ends up indistinguishable from a record.
        """
        if self.type in FACTUAL_TYPES:
            return bool(self.citations) and self.status == ACCEPTED
        return False

    @property
    def inferred(self) -> bool:
        return self.type == INFERENCE

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": self.id,
            "type": self.type,
            "text": self.text,
            "citations": list(self.citations),
            "status": self.status,
            "numeric_check": self.numeric_check,
            "entity_linkage": self.entity_linkage,
        }
        if self.dependency_check != DEPENDENCY_NOT_APPLICABLE:
            payload["dependency_check"] = self.dependency_check
        if self.origin != MODEL:
            payload["origin"] = self.origin
        if self.derived_from:
            payload["derived_from"] = list(self.derived_from)
        if self.based_on:
            payload["based_on"] = list(self.based_on)
        if self.original_type and self.original_type != self.type:
            payload["original_type"] = self.original_type
        if self.presented_as_decision:
            payload["presented_as_decision"] = True
        if self.notes:
            payload["notes"] = list(self.notes)
        return payload


@dataclass(frozen=True)
class LedgerResult:
    claims: List[Claim] = field(default_factory=list)
    rejected: List[Dict[str, Any]] = field(default_factory=list)
    warnings: List[Dict[str, Any]] = field(default_factory=list)

    def by_type(self, claim_type: str) -> List[Claim]:
        return [claim for claim in self.claims if claim.type == claim_type]

    @property
    def factual(self) -> List[Claim]:
        return [claim for claim in self.claims if claim.type in FACTUAL_TYPES]

    @property
    def cited_ids(self) -> Set[int]:
        cited: Set[int] = set()
        for claim in self.claims:
            cited.update(claim.citations)
        return cited

    def to_list(self) -> List[Dict[str, Any]]:
        return [claim.to_dict() for claim in self.claims]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": LEDGER_VERSION,
            "claims": self.to_list(),
            "rejected_claims": list(self.rejected),
            "warnings": list(self.warnings),
        }


def validate_ledger(
    payload: Any,
    bundle: Any,
    *,
    mode: str = "evidence",
    assumptions: Sequence[Dict[str, Any]] = (),
    answer_text: str = "",
    origin: str = MODEL,
) -> LedgerResult:
    """Sanitize an untrusted claim list against the evidence and the mode.

    ``mode`` is the epistemic policy inferred from the user's own question. It
    decides whether generative claims are admissible at all: a question asking
    what the corpus says does not get answered with recommendations, however
    the model chose to label them.

    ``answer_text`` is the prose the same response carried, used only to
    recover a citation the model wrote into the sentence but left out of the
    claim's ``citations`` array — a routine shape failure in smaller local
    models that would otherwise downgrade a properly sourced fact.

    ``origin`` records who wrote this claim list. Claims transcribed from the
    prose by ``recovery`` are validated on identical terms; the only thing the
    origin changes is that such a list may declare ``uncertainty`` outright,
    since the section it came from said so and a model is never trusted to.
    """
    raw_claims = [item for item in _list(payload) if isinstance(item, dict)][:MAX_CLAIMS]
    valid_ids = set(bundle.citation_ids())
    entity_forms = bundle.entity_forms()
    assumption_numbers = _assumption_numbers(assumptions)
    prose_citations = _prose_citations(answer_text, valid_ids)

    claims: List[Claim] = []
    rejected: List[Dict[str, Any]] = []
    warnings: List[Dict[str, Any]] = []
    grounded_ids: Set[str] = set()
    seen_ids: Set[str] = set()
    prior_types: Dict[str, str] = {}

    for position, item in enumerate(raw_claims, start=1):
        text = _text(item.get("text"))
        if not text:
            continue
        text = text[:MAX_CLAIM_TEXT]

        claim_id = _claim_id(item.get("id"), position, seen_ids)

        declared = _text(item.get("type")).lower()
        if declared not in GENERATED_TYPES and not (
            origin == DETERMINISTIC_RECOVERY and declared == UNCERTAINTY
        ):
            # An unrecognized label is not a free pass. Citations decide:
            # something cited reads as a fact, something uncited does not.
            declared = FACT if item.get("citations") else UNCERTAINTY

        citations = _citations(item.get("citations"), valid_ids)
        if not citations:
            # Smaller local models routinely write "[3]" beside the sentence
            # and leave the citations array empty, which would downgrade a
            # perfectly sourced fact. The marker is the model's own citation
            # and it still has to name evidence that was actually retrieved,
            # so reading it back invents nothing. The claim's own text is
            # checked first, then the sentence of the prose it restates.
            citations = _citations(_STANDALONE_CITATION.findall(text), valid_ids)
        if not citations:
            citations = _prose_citations_for(text, prose_citations)
        # Register this id only after resolving premises. `_references` keeps
        # ids already in `seen_ids`, and "already" must mean an earlier claim —
        # a claim that lists itself is not grounded in a prior fact.
        derived_from = _references(item.get("derived_from"), seen_ids)
        based_on = _references(item.get("based_on"), seen_ids)
        seen_ids.add(claim_id)
        based_on = [
            reference
            for reference in based_on
            if prior_types.get(reference) not in GENERATIVE_TYPES
        ]

        # Generative claims in an evidence-mode answer are out of contract.
        # The question asked what the corpus says.
        if declared in GENERATIVE_TYPES and mode == "evidence":
            rejected.append(
                {
                    "id": claim_id,
                    "type": declared,
                    "text": text,
                    "reason": f"{declared}-not-allowed-in-evidence-mode",
                }
            )
            continue
        if declared == IDEA and mode == "advisory":
            # Advisory may recommend; free invention belongs to ideation.
            declared = RECOMMENDATION

        supporting = bundle.supporting_texts(citations)
        numeric = check_numeric_grounding(text, supporting)
        linkage = check_entity_linkage(
            text, entity_forms, supporting, bundle.linked_pairs(citations)
        )
        dependency = check_dependency_grounding(text, supporting)

        claim = Claim(
            id=claim_id,
            type=declared,
            text=text,
            citations=citations,
            derived_from=derived_from,
            based_on=based_on,
            numeric_check=numeric,
            entity_linkage=linkage,
            dependency_check=dependency,
            original_type=declared,
            origin=origin,
        )

        claim, claim_warnings = _apply_rules(
            claim,
            grounded_ids=grounded_ids,
            assumption_numbers=assumption_numbers,
            supporting=supporting,
        )
        warnings.extend(claim_warnings)
        if claim.grounded:
            grounded_ids.add(claim.id)
        claims.append(claim)
        prior_types[claim.id] = claim.type

    return LedgerResult(claims=claims, rejected=rejected, warnings=warnings)


def _apply_rules(
    claim: Claim,
    *,
    grounded_ids: Set[str],
    assumption_numbers: Set[str],
    supporting: Sequence[str],
):
    """Every epistemic rule, applied in one place so they compose predictably."""
    warnings: List[Dict[str, Any]] = []
    notes: List[str] = []
    claim_type = claim.type
    status = ACCEPTED
    presented_as_decision = False

    def warn(check: str, detail: str) -> None:
        warnings.append(
            diagnostics.warning(check, detail, claim=claim.text, claim_id=claim.id)
        )

    # --- does this claim rest on something the user supposed? --------------
    #
    # Checked first, and before the citation rule. A scenario claim has no
    # citation *by construction* — the figure is not in the corpus, which is
    # the whole point — so letting the uncited-fact rule reach it first would
    # bury every scenario as generic uncertainty and lose the distinction §25
    # asks for.
    scenario_figures = False
    if claim.numeric_check in (NUMERIC_NOT_IN_EVIDENCE, NUMERIC_NOT_CONNECTED):
        claim_numbers = set(extract_numbers(_CITATION_MARKER.sub(" ", claim.text)))
        evidence_numbers: Set[str] = set()
        for text in supporting:
            evidence_numbers.update(extract_numbers(text))
        unsourced = claim_numbers - evidence_numbers
        scenario_figures = bool(unsourced) and unsourced <= assumption_numbers

    if scenario_figures and claim_type in FACTUAL_TYPES:
        claim_type = SCENARIO
        status = DOWNGRADED
        notes.append("Rests on a figure the user supplied as an assumption, not on the corpus.")
        warn("scenario", "figure-from-session-assumption")

    # --- an inference is reasoning across several supported facts ----------
    #
    # The failure this type exists to fix is over-suppression: three grounded
    # facts about someone's attendance, ownership, and email domain genuinely
    # do support "X appears to be part of the core team", and refusing to say
    # so is its own kind of inaccuracy. The failure it must not introduce is
    # "X is a GANG employee", which is a different claim entirely.
    if claim_type == INFERENCE:
        premises = [value for value in claim.derived_from if value in grounded_ids]
        support = len(premises) + (len(claim.citations) if not premises else 0)

        if _asserts_formal_status(claim.text):
            # Employment, titles, and reporting lines are matters of record.
            # No amount of circumstantial evidence establishes one.
            claim_type = UNCERTAINTY
            status = DOWNGRADED
            notes.append(
                "States a formal role or employment relationship, which needs a source that "
                "says so outright rather than a pattern of participation."
            )
            warn("inference_overreach", "formal-status-requires-explicit-evidence")
        elif support < MIN_INFERENCE_PREMISES:
            claim_type = UNCERTAINTY
            status = DOWNGRADED
            notes.append(
                "Presented as an inference but rests on fewer than two supported facts."
            )
            warn("inference_support", "insufficient-grounded-premises")
        elif not _reads_as_inference(claim.text):
            # An unhedged inference is simply an assertion. Code cannot
            # rewrite prose into a hedge safely, so the claim loses its
            # standing rather than quietly keeping an unearned one.
            claim_type = UNCERTAINTY
            status = DOWNGRADED
            notes.append(
                "Stated as established fact rather than as an inference drawn from the record."
            )
            warn("inference_framing", "inference-not-hedged")

    # --- a factual claim with nothing behind it is not a factual claim -----
    if claim_type in FACTUAL_TYPES:
        premises_grounded = bool(claim.derived_from) and all(
            reference in grounded_ids for reference in claim.derived_from
        )
        if not claim.citations and not (claim_type == SYNTHESIS and premises_grounded):
            claim_type = UNCERTAINTY
            status = DOWNGRADED
            notes.append("No citation supports this claim, so it is not stated as fact.")
            warn("citation", "uncited-factual-claim")

    # --- figures must be in, and connected by, the cited evidence ----------
    if claim.numeric_check in (NUMERIC_NOT_IN_EVIDENCE, NUMERIC_NOT_CONNECTED) and not scenario_figures:
        if claim_type in FACTUAL_TYPES:
            claim_type = UNCERTAINTY
            status = DOWNGRADED
            notes.append(
                "A figure in this claim is not in the cited evidence, or the evidence does "
                "not connect the figures."
            )
        warn("numeric", claim.numeric_check)

    # --- relating two entities needs a source that relates them ------------
    if claim.entity_linkage == LINKAGE_UNSUPPORTED:
        if claim_type in FACTUAL_TYPES:
            claim_type = UNCERTAINTY
            status = DOWNGRADED
            notes.append("No cited source mentions both entities, so the relationship is unproven.")
        warn("entity_linkage", LINKAGE_UNSUPPORTED)

    # --- a stated requirement needs a source that states it ----------------
    #
    # Two tasks printed on consecutive lines are two tasks. Nothing about the
    # layout says one gates the other, so a dependency the cited evidence
    # never expresses loses its standing as fact.
    if claim.dependency_check == DEPENDENCY_UNSUPPORTED:
        if claim_type in FACTUAL_TYPES:
            claim_type = UNCERTAINTY
            status = DOWNGRADED
            notes.append(
                "No cited source states this requirement or dependency. Items listed near "
                "each other are separate unless the evidence says one needs the other."
            )
        warn("dependency", DEPENDENCY_UNSUPPORTED)

    # --- a generated claim may not pose as an existing company decision ----
    if claim_type in GENERATIVE_TYPES and _asserts_existing_decision(claim.text):
        presented_as_decision = True
        status = FLAGGED
        notes.append(
            "Phrased as an existing company decision. It is generated advice, not a decision "
            "the corpus records."
        )
        warn("decision_framing", "generated-claim-phrased-as-decision")

    return (
        Claim(
            id=claim.id,
            type=claim_type,
            text=claim.text,
            citations=claim.citations,
            derived_from=claim.derived_from,
            based_on=claim.based_on,
            numeric_check=claim.numeric_check,
            entity_linkage=claim.entity_linkage,
            dependency_check=claim.dependency_check,
            status=status,
            origin=claim.origin,
            original_type=claim.original_type,
            presented_as_decision=presented_as_decision,
            notes=notes,
        ),
        warnings,
    )


def _reads_as_inference(text: str) -> bool:
    """Whether the wording presents this as reasoning rather than as record."""
    return bool(_INFERENCE_HEDGE.search(text or ""))


def _asserts_formal_status(text: str) -> bool:
    """Whether the claim asserts employment, a title, or a reporting line."""
    return bool(_FORMAL_STATUS.search(text or ""))


def _asserts_existing_decision(text: str) -> bool:
    """Does this read as a report of a decision rather than as a suggestion?"""
    if not _DECISION_ASSERTION.search(text or ""):
        return False
    # "I would recommend we commit to certification first" contains a decision
    # verb but is plainly a suggestion. The hedge settles it.
    return not _GENERATIVE_HEDGE.search(text or "")


def ungrounded_premises(result: LedgerResult) -> List[Dict[str, Any]]:
    """Generative claims resting on premises that are not themselves grounded.

    §5 and §29: an idea may be novel, but the company facts shaping it must be
    cited. A recommendation whose ``based_on`` points at a downgraded claim is
    advice built on something the corpus did not establish, and saying so is
    more useful than withholding the advice.
    """
    grounded = {claim.id for claim in result.claims if claim.grounded}
    issues: List[Dict[str, Any]] = []
    for claim in result.claims:
        if claim.type not in GENERATIVE_TYPES:
            continue
        dangling = [value for value in claim.based_on if value not in grounded]
        if dangling:
            issues.append({"claim_id": claim.id, "ungrounded_premises": dangling})
    return issues


def uncertainty_summary(result: LedgerResult) -> List[str]:
    """Validator detail. Diagnostics only — never shown in normal output.

    Each line names a claim and why it did not survive as stated. Useful when
    debugging a disappointing answer, and exactly the wrong thing to print
    underneath a conversational reply.
    """
    lines: List[str] = []
    for claim in result.claims:
        if claim.status == ACCEPTED:
            continue
        note = claim.notes[0] if claim.notes else "Not fully supported by the cited evidence."
        lines.append(f"{note} ({claim.text[:120]})")
    for item in result.rejected:
        lines.append(f"Dropped a {item['type']} claim: {item['reason']}.")
    return lines


def natural_uncertainty(result: LedgerResult) -> str:
    """One plain sentence about what is not settled. For the reader.

    Counts rather than catalogues. "Two statements are not fully supported" is
    something a person can act on; a list of validator statuses with claim
    text quoted back at them is not, and printing that under every answer is
    what made the system read as a linter rather than a colleague.
    """
    downgraded = [claim for claim in result.claims if claim.status == DOWNGRADED]
    inferences = [claim for claim in result.claims if claim.inferred]
    parts: List[str] = []

    if downgraded:
        parts.append(
            "I couldn't fully stand behind "
            + (
                "one statement"
                if len(downgraded) == 1
                else f"{len(downgraded)} statements"
            )
            + ", so I've left "
            + ("it" if len(downgraded) == 1 else "them")
            + " out of the confident parts of this answer"
        )
    if inferences:
        parts.append(
            ("one reading above is" if len(inferences) == 1 else f"{len(inferences)} readings above are")
            + " drawn from the pattern of the evidence rather than stated in it"
        )
    if not parts:
        return ""
    sentence = "; ".join(parts)
    return sentence[:1].upper() + sentence[1:] + "."


# ----------------------------------------------------------------- helpers


def _assumption_numbers(assumptions: Sequence[Dict[str, Any]]) -> Set[str]:
    numbers: Set[str] = set()
    for item in assumptions or ():
        numbers.update(extract_numbers(_text(item.get("text"))))
        for value in item.get("numbers") or ():
            numbers.update(extract_numbers(str(value)))
    return numbers


def _claim_id(value: Any, position: int, seen: Set[str]) -> str:
    text = _text(value)
    if text and _CLAIM_ID.fullmatch(text) and text not in seen:
        return text
    candidate = f"c{position}"
    while candidate in seen:
        position += 1
        candidate = f"c{position}"
    return candidate


#: How much of a claim has to line up with a sentence of the prose before its
#: citation is borrowed. Short fragments match too many sentences to be safe.
MIN_PROSE_MATCH_CHARS = 25

_PROSE_SENTENCE = re.compile(r"[^.!?\n]+")


def _prose_citations(answer_text: str, valid_ids: Set[int]) -> List[tuple]:
    """Each sentence of the answer that carries markers, and the ids it named."""
    rows: List[tuple] = []
    for sentence in _PROSE_SENTENCE.findall(answer_text or ""):
        ids = _citations(_STANDALONE_CITATION.findall(sentence), valid_ids)
        if ids:
            rows.append((_comparable(_STANDALONE_CITATION.sub(" ", sentence)), ids))
    return rows


def _prose_citations_for(claim_text: str, rows: Sequence[tuple]) -> List[int]:
    """The citation the prose gave the sentence this claim restates."""
    needle = _comparable(_STANDALONE_CITATION.sub(" ", claim_text))
    if len(needle) < MIN_PROSE_MATCH_CHARS:
        return []
    for sentence, ids in rows:
        if needle in sentence or (len(sentence) >= MIN_PROSE_MATCH_CHARS and sentence in needle):
            return list(ids)
    return []


def _comparable(text: str) -> str:
    """Letters and digits only, so punctuation drift does not break a match."""
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()


def _citations(value: Any, valid_ids: Set[int]) -> List[int]:
    result: List[int] = []
    for item in _list(value):
        try:
            citation = int(str(item).strip().strip("[]"))
        except (TypeError, ValueError):
            continue
        if citation in valid_ids and citation not in result:
            result.append(citation)
    return result


def _references(value: Any, known: Set[str]) -> List[str]:
    """Claim-id references, keeping only ids already defined above this claim."""
    result: List[str] = []
    for item in _list(value):
        text = _text(item)
        if text and text in known and text not in result:
            result.append(text)
    return result


def _list(value: Any) -> List[Any]:
    if isinstance(value, dict):
        inner = value.get("claims")
        return inner if isinstance(inner, list) else []
    return value if isinstance(value, list) else []


def _text(value: Any) -> str:
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value).strip()
