"""Which source to lean on when two of them disagree — and why.

A newer signed schedule is usually a better answer to "when do we ship?" than
an older passing remark in an email. *Usually*. This module encodes that as a
transparent, configurable preference and nothing stronger:

* Authority is **contextual**. It is consulted for current-state questions and
  ignored elsewhere, because "what did we originally plan?" wants the older
  document and a global ranking would bury it.
* Authority **never removes evidence**. Preference is recorded as an annotation
  on an item that stays in the bundle. §18's rule holds: conflicting sources
  are both kept, both cited, and the disagreement is explained.
* Authority **never outranks an explicit statement**. A casual email that
  explicitly contradicts a plan produces a conflict to be surfaced, not a
  silent loss. The preference is a tiebreak between sources, not a licence to
  drop the one that lost.
* Every preference carries a **reason string** that the answer can quote, so a
  reader can disagree with the ranking rather than wonder about it.

The ranks below are defaults. They are data, not logic, and callers may pass
their own map.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence


# ---------------------------------------------------------------- the roles

FOUNDATIONAL = "foundational"
SIGNED_FINAL = "signed-final"
OPERATING_PLAN = "operating-plan"
EXECUTIVE_NOTES = "executive-notes"
MEETING_RECAP = "meeting-recap"
WORKING_AGENDA = "working-agenda"
EMAIL = "email"
DERIVED_ENRICHMENT = "derived-enrichment"
UNCLASSIFIED = "unclassified"

ROLES = (
    FOUNDATIONAL,
    SIGNED_FINAL,
    OPERATING_PLAN,
    EXECUTIVE_NOTES,
    MEETING_RECAP,
    WORKING_AGENDA,
    EMAIL,
    DERIVED_ENRICHMENT,
    UNCLASSIFIED,
)

#: Higher means "more likely to be the deliberate, current record". The gaps
#: are wide on purpose: these are coarse bands, not a score.
DEFAULT_RANKS: Dict[str, int] = {
    # Above a signed document on purpose. Asked what something *is*, the
    # canonical record someone authored outranks a contract that happens to
    # mention it.
    FOUNDATIONAL: 120,
    SIGNED_FINAL: 100,
    OPERATING_PLAN: 90,
    EXECUTIVE_NOTES: 80,
    MEETING_RECAP: 70,
    WORKING_AGENDA: 60,
    UNCLASSIFIED: 50,
    EMAIL: 40,
    DERIVED_ENRICHMENT: 20,
}

ROLE_DESCRIPTIONS = {
    FOUNDATIONAL: "the canonical record for this entity",
    SIGNED_FINAL: "a signed or final document",
    OPERATING_PLAN: "the current operating plan",
    EXECUTIVE_NOTES: "executive meeting notes",
    MEETING_RECAP: "a meeting recap",
    WORKING_AGENDA: "a working agenda",
    EMAIL: "an ordinary email",
    DERIVED_ENRICHMENT: "derived enrichment rather than source text",
    UNCLASSIFIED: "an unclassified document",
}

_SIGNED_TITLE = re.compile(r"\b(signed|executed|final|countersigned|fully executed)\b", re.IGNORECASE)
_PLAN_TITLE = re.compile(
    r"\b(operating plan|schedule|master plan|launch plan|production plan|roadmap|timeline)\b",
    re.IGNORECASE,
)
_EXEC_TITLE = re.compile(r"\b(executive|exec|board|leadership)\b", re.IGNORECASE)
_RECAP_TITLE = re.compile(r"\b(recap|minutes|notes|summary|sync|debrief)\b", re.IGNORECASE)
_AGENDA_TITLE = re.compile(r"\b(agenda|working|draft|wip)\b", re.IGNORECASE)


def classify(item: Any, *, ranks: Optional[Dict[str, int]] = None) -> str:
    """Assign one source role from a document's own type and title.

    Reads only metadata the ingestion layer already recorded. No model, and no
    inspection of body text — a document does not get to argue for its own
    authority, which is what a prompt injection would try to do.
    """
    document_type = _lower(_attr(item, "type"))
    source_type = _lower(_attr(item, "source_type"))
    title = _attr(item, "title")
    status = _lower(_attr(item, "status"))

    if document_type == "entity" or source_type.startswith("entity-"):
        return FOUNDATIONAL
    if _SIGNED_TITLE.search(title) or status in ("signed", "final", "executed"):
        return SIGNED_FINAL
    if document_type in ("plan", "schedule") or _PLAN_TITLE.search(title):
        return OPERATING_PLAN
    if document_type in ("meeting", "meeting-note", "meeting-notes") or source_type == "meeting":
        return EXECUTIVE_NOTES if _EXEC_TITLE.search(title) else MEETING_RECAP
    if _EXEC_TITLE.search(title) and _AGENDA_TITLE.search(title):
        # "Weekly Executive Operating Agenda" is a working document that an
        # executive happens to own, not a signed decision record.
        return WORKING_AGENDA
    if document_type == "agenda" or _AGENDA_TITLE.search(title):
        return WORKING_AGENDA
    if _RECAP_TITLE.search(title):
        return MEETING_RECAP
    if source_type in ("gmail-thread", "gmail", "email") or document_type == "email":
        return EMAIL
    return UNCLASSIFIED


def rank_of(role: str, *, ranks: Optional[Dict[str, int]] = None) -> int:
    table = ranks or DEFAULT_RANKS
    return table.get(role, table.get(UNCLASSIFIED, 50))


@dataclass(frozen=True)
class SourceAuthority:
    """One item's role, rank, and — if it won — the reason it was preferred."""

    citation_id: int
    document_id: str
    role: str
    rank: int
    date: str = ""
    preferred: bool = False
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "citation_id": self.citation_id,
            "document_id": self.document_id,
            "role": self.role,
            "role_description": ROLE_DESCRIPTIONS.get(self.role, ""),
            "rank": self.rank,
            "date": self.date,
            "preferred": self.preferred,
            "reason": self.reason,
        }


#: What the preference is being made *for*. Appears verbatim in the reason a
#: reader sees, because "preferred for the current state" is the wrong thing
#: to say about "what is GANG?".
CURRENT_STATE = "the current state"
DEFINITION = "the definition"


def assess(
    items: Sequence[Any],
    *,
    current_state_question: bool = False,
    purpose: str = CURRENT_STATE,
    ranks: Optional[Dict[str, int]] = None,
) -> List[SourceAuthority]:
    """Classify every evidence item, and for current-state questions mark one.

    The winner is the newest item in the highest authority band present, which
    is the ordering people actually mean by "what does it say now". Everything
    else keeps its place in the bundle with its own role recorded, so the
    answer can still cite an older or more casual source and explain why it
    differs.
    """
    assessed: List[SourceAuthority] = []
    for item in items:
        role = classify(item, ranks=ranks)
        assessed.append(
            SourceAuthority(
                citation_id=int(_attr(item, "citation_id") or 0),
                document_id=_attr(item, "document_id"),
                role=role,
                rank=rank_of(role, ranks=ranks),
                date=_date(item),
            )
        )

    if not current_state_question or len(assessed) < 2:
        return assessed

    best = max(assessed, key=lambda entry: (entry.rank, entry.date, -entry.citation_id))
    rivals = [entry for entry in assessed if entry.citation_id != best.citation_id]
    return [
        _with_preference(entry, best, rivals, purpose)
        if entry.citation_id == best.citation_id
        else entry
        for entry in assessed
    ]


def _with_preference(
    winner: SourceAuthority,
    best: SourceAuthority,
    rivals: Sequence[SourceAuthority],
    purpose: str = CURRENT_STATE,
) -> SourceAuthority:
    newer_than = [entry for entry in rivals if entry.date and entry.date < best.date]
    outranks = [entry for entry in rivals if entry.rank < best.rank]

    reasons: List[str] = []
    if outranks:
        lowest = min(outranks, key=lambda entry: entry.rank)
        reasons.append(
            f"it is {ROLE_DESCRIPTIONS.get(best.role, best.role)} rather than "
            f"{ROLE_DESCRIPTIONS.get(lowest.role, lowest.role)}"
        )
    if newer_than:
        reasons.append(f"it is the most recent ({best.date})")
    if not reasons:
        return winner

    return SourceAuthority(
        citation_id=winner.citation_id,
        document_id=winner.document_id,
        role=winner.role,
        rank=winner.rank,
        date=winner.date,
        preferred=True,
        reason=(
            f"Preferred for {purpose} because "
            + " and ".join(reasons)
            + ". Older and less formal sources remain cited where they differ."
        ),
    )


def preference_note(assessed: Sequence[SourceAuthority]) -> str:
    """Code-owned sentence naming the preferred source, or empty."""
    for entry in assessed:
        if entry.preferred and entry.reason:
            return f"[{entry.citation_id}] {entry.reason}"
    return ""


def guidance(assessed: Sequence[SourceAuthority]) -> Dict[str, Any]:
    """The authority picture handed to synthesis, as DATA.

    Includes the explicit reminder that authority is a tiebreak. Without it a
    model reads a ranking as permission to discard the loser, which is exactly
    the failure §18 and §40 describe.
    """
    return {
        "sources": [entry.to_dict() for entry in assessed],
        "rule": (
            "Source authority is a tiebreak for which source describes the CURRENT state. "
            "It never deletes or overrides evidence. If a lower-authority source explicitly "
            "contradicts a higher-authority one, report both, cite both, say which is newer, "
            "and explain the disagreement. Never silently drop the losing source."
        ),
    }


# --------------------------------------------------------- current-state fit

_CURRENT_WORDS = re.compile(
    r"\b(current|currently|now|today|latest|newest|at the moment|right now|as it stands|still)\b",
    re.IGNORECASE,
)


def is_current_state_question(question: str, policy: str = "") -> bool:
    """Whether "which source is current?" is a question worth asking here."""
    from . import intent as intent_module

    if policy in (
        intent_module.STATUS,
        intent_module.PLAN,
        intent_module.ADVISORY,
        intent_module.DEFINITION,
    ):
        return True
    return bool(_CURRENT_WORDS.search(question or ""))


# ----------------------------------------------------------------- helpers


def _attr(item: Any, name: str) -> str:
    if isinstance(item, dict):
        return str(item.get(name) or "")
    return str(getattr(item, name, "") or "")


def _date(item: Any) -> str:
    updated = _attr(item, "updated")
    created = _attr(item, "created")
    return (updated or created)[:10]


def _lower(value: str) -> str:
    return (value or "").strip().lower()
