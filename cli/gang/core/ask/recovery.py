"""Rebuild a claim ledger out of the answer's own labelled sections.

Smaller local models sometimes return a well-formed, correctly cited advisory
answer and an empty ``claims`` array. The turn is not wrong — the prose is
sourced and the sections are there — but the ledger is the part that holds the
line between what the corpus says and what GANG made up, and an empty one is
not something to print silently.

So when, and only when, synthesis succeeded, prose exists, and the model
supplied no claims at all, the labelled sections the advisory schema already
asks for are read back into claims. This is transcription, not analysis:

* Only the four known section labels are read. There is no sentence
  classifier, and nothing outside a recognized section is looked at.
* A sentence becomes a factual claim only if it carries a standalone citation
  marker that resolves to evidence actually in the bundle.
* Nothing is added. No citation, dependency, entity, date, owner, or
  proposition appears in a recovered claim that is not literally in the
  sentence it came from.
* Recovered claims go through ``validate_ledger`` exactly as model claims do,
  so the numeric, entity-linkage, dependency, and citation rules all apply.

Recovered claims carry ``origin: deterministic-recovery`` so observability can
tell them apart from a ledger the model actually produced, and a recovery that
yields nothing leaves the ledger marked incomplete rather than merely empty.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Set, Tuple

from . import ledger as ledger_module


#: The shortest sentence worth transcribing. Below this a "sentence" is a
#: fragment of a label or a stray marker, not a statement.
MIN_CLAIM_CHARS = 12

#: Prefix for generated claim ids, distinct from the c1/r1 shapes models use.
RECOVERED_ID_PREFIX = "d"

_STANDALONE_CITATION = re.compile(r"\[(\d{1,3})\](?![\w-])")

#: A terminator only ends a sentence when something follows it — "3.5" and
#: "QI-27832)" are not boundaries.
_TERMINATOR = re.compile(r"[.!?]+(?=\s|$)")
_TRAILING_WORD = re.compile(r"([A-Za-z]+)\.$")

#: Abbreviations that end in a period without ending a sentence. Splitting on
#: "Steven will intervene (incl. Mandarin outreach)" produced a claim that
#: began mid-clause, and a half-sentence is not a statement anyone can audit.
#: Single letters are covered separately, for initials.
_ABBREVIATIONS = frozenset(
    {
        "incl", "excl", "approx", "est", "etc", "e.g", "eg", "i.e", "ie", "vs",
        "no", "nos", "fig", "cf", "al", "dept", "mgmt", "qty",
        "inc", "corp", "co", "ltd", "llc", "plc",
        "dr", "mr", "mrs", "ms", "prof", "jr", "sr", "st",
        "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept", "oct",
        "nov", "dec",
    }
)


@dataclass(frozen=True)
class Section:
    """One labelled part of an advisory answer, and what it may become."""

    key: str
    title: str
    claim_type: str
    requires_citation: bool


CURRENT_EVIDENCE = Section(
    "current-evidence", "Current evidence", ledger_module.FACT, requires_citation=True
)
EXISTING_ACTIONS = Section(
    "existing-actions",
    "Existing actions already underway",
    ledger_module.FACT,
    requires_citation=True,
)
OPEN_RISKS = Section(
    "open-risks", "Open risks and unknowns", ledger_module.UNCERTAINTY, requires_citation=False
)
RECOMMENDATION = Section(
    "recommendation", "GANG recommendation", ledger_module.RECOMMENDATION, requires_citation=False
)

SECTIONS = (CURRENT_EVIDENCE, EXISTING_ACTIONS, OPEN_RISKS, RECOMMENDATION)

#: Longest label first within each group: "existing actions already underway"
#: has to win over "already underway", and "gang recommendation" over
#: "recommendation", because alternation is leftmost-first.
_LABELS: Tuple[Tuple[str, Section], ...] = (
    (r"current\s+evidence", CURRENT_EVIDENCE),
    (r"current\s+state", CURRENT_EVIDENCE),
    (r"existing\s+actions(?:\s+already\s+underway)?", EXISTING_ACTIONS),
    (r"already\s+underway", EXISTING_ACTIONS),
    (r"open\s+risks(?:\s+and\s+unknowns)?", OPEN_RISKS),
    (r"risks\s+and\s+unknowns", OPEN_RISKS),
    (r"unknowns", OPEN_RISKS),
    (r"gang\s+recommendation", RECOMMENDATION),
    (r"what\s+i\s+would\s+do", RECOMMENDATION),
    (r"recommendation", RECOMMENDATION),
)

_LABEL = re.compile(
    "(?:" + "|".join(f"(?P<s{index}>{pattern})" for index, (pattern, _) in enumerate(_LABELS)) + r")\s*:",
    re.IGNORECASE,
)


def recover_claims(answer_text: str, valid_ids: Set[int]) -> List[Dict[str, Any]]:
    """Raw claim dicts read out of the answer's labelled sections.

    Returns claims in the shape ``validate_ledger`` takes, so the caller
    validates them on exactly the same terms as a model's own ledger. Returns
    an empty list when there is nothing the rules allow recovering.
    """
    claims: List[Dict[str, Any]] = []
    for section, body in _sections(answer_text):
        for sentence in _sentences(body):
            citations = _citation_ids(sentence, valid_ids)
            if section.requires_citation and not citations:
                # An uncited sentence in an evidence section is a statement the
                # model did not source. Recovery does not get to source it.
                continue
            claims.append(
                {
                    "id": f"{RECOVERED_ID_PREFIX}{len(claims) + 1}",
                    "type": section.claim_type,
                    "text": sentence,
                    "citations": citations,
                }
            )
    return claims


def _sections(answer_text: str) -> List[Tuple[Section, str]]:
    """Each recognized label, paired with the text up to the next one."""
    text = answer_text or ""
    matches = list(_LABEL.finditer(text))
    found: List[Tuple[Section, str]] = []
    for position, match in enumerate(matches):
        section = _section_of(match)
        if section is None:
            continue
        end = matches[position + 1].start() if position + 1 < len(matches) else len(text)
        found.append((section, text[match.end() : end]))
    return found


def _section_of(match: "re.Match[str]") -> Section | None:
    for index, (_, section) in enumerate(_LABELS):
        if match.group(f"s{index}") is not None:
            return section
    return None


def _sentences(body: str) -> List[str]:
    sentences: List[str] = []
    for raw in _split_sentences(body or ""):
        sentence = re.sub(r"\s+", " ", raw).strip()
        if len(_STANDALONE_CITATION.sub(" ", sentence).strip()) < MIN_CLAIM_CHARS:
            continue
        sentences.append(sentence)
    return sentences


def _split_sentences(body: str) -> List[str]:
    """Whole sentences, keeping abbreviations intact."""
    parts: List[str] = []
    start = 0
    for match in _TERMINATOR.finditer(body):
        head = body[start : match.end()]
        if _ends_in_abbreviation(head):
            continue
        parts.append(head)
        start = match.end()
    tail = body[start:]
    if tail.strip():
        parts.append(tail)
    return parts


def _ends_in_abbreviation(head: str) -> bool:
    word = _TRAILING_WORD.search(head.rstrip())
    if word is None:
        return False
    return len(word.group(1)) == 1 or word.group(1).lower() in _ABBREVIATIONS


def _citation_ids(sentence: str, valid_ids: Set[int]) -> List[int]:
    """Markers in this sentence that name evidence actually in the bundle."""
    found: List[int] = []
    for value in _STANDALONE_CITATION.findall(sentence):
        try:
            citation = int(value)
        except (TypeError, ValueError):
            continue
        if citation in valid_ids and citation not in found:
            found.append(citation)
    return found


def section_titles() -> Sequence[str]:
    """The labels the advisory schema asks the model to write."""
    return [section.title for section in SECTIONS]
