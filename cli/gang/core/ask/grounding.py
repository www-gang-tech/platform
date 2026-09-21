"""Deterministic grounding checks applied to text and to generated answers.

Everything here is code, not judgement. Each check answers a narrow, mechanical
question about whether a piece of text is supported by the evidence that was
actually retrieved, and none of them asks a model anything:

* **Extraction quality** — is this text natural language at all, or is it the
  binary residue of a failed PDF extraction?
* **Numeric alignment** — does every figure in a claim appear in the evidence
  the claim cites, and did the source actually put those figures together?
* **Entity linkage** — when a claim relates two entities, did any single cited
  source mention both, or is the relationship an artifact of both names having
  been resolved during retrieval?
* **Dependency claims** — when a claim says one thing is required by, blocks,
  or gates another, did a cited source say so, or were the two items merely
  adjacent in a list?
* **Categorical negatives** — is the answer converting "no evidence found" into
  "no", which is a different and much stronger statement?

These are conservative by design. A check that cannot verify a claim marks it
uncertain; it never deletes evidence and never edits a source.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Dict, List, Sequence, Set, Tuple


# --------------------------------------------------------------- extraction

READABLE = "readable"
UNREADABLE = "unreadable"

#: Thresholds calibrated against the real corpus. A failed PDF extraction there
#: measured 13.6% control characters, 2.6% whitespace, and a 36-character mean
#: token; every genuine document measured under 0.3% control characters, over
#: 4.8% whitespace, and a mean token under 20.
MAX_CONTROL_RATIO = 0.02
MAX_REPLACEMENT_RATIO = 0.005
MAX_MEAN_TOKEN_LENGTH = 25.0
MIN_WHITESPACE_RATIO = 0.05
MIN_ASSESSABLE_CHARS = 80

#: Cap on the readable region returned from a partly corrupt document, such as
#: an email whose header survives but whose body is base64.
READABLE_WINDOW = 400

#: Where extraction broke down. Two shapes, both acting as separators between
#: text that survived and text that did not: runs of control/replacement
#: characters (binary residue), and unbroken non-whitespace runs far longer
#: than any word (base64 blobs and encoded payloads in HTML mail).
_CORRUPT_RUN = re.compile(
    r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f-\u009f\ufffd]+|\S{40,}"
)

#: Unicode categories that mean "this was never text": C0/C1 controls,
#: surrogates, private use, unassigned. Deliberately excludes Cf (format) —
#: soft hyphens, zero-width spaces, and byte-order marks are ordinary in HTML
#: email, and counting them as corruption condemns perfectly readable mail.
_BINARY_CATEGORIES = frozenset({"Cc", "Cs", "Co", "Cn"})


@dataclass(frozen=True)
class TextQuality:
    quality: str
    reason: str
    metrics: Dict[str, float]

    @property
    def readable(self) -> bool:
        return self.quality == READABLE


def assess_text_quality(text: str) -> TextQuality:
    """Decide whether extracted text is natural language, by measurement only."""
    value = text or ""
    length = len(value)
    if not value.strip():
        return TextQuality(UNREADABLE, "empty", {})

    control = sum(
        1
        for char in value
        if unicodedata.category(char) in _BINARY_CATEGORIES and not char.isspace()
    )
    replacement = value.count("�")
    whitespace = sum(1 for char in value if char.isspace())
    tokens = value.split()
    mean_token = sum(len(token) for token in tokens) / len(tokens) if tokens else float(length)

    metrics = {
        "control_ratio": control / length,
        "replacement_ratio": replacement / length,
        "whitespace_ratio": whitespace / length,
        "mean_token_length": mean_token,
        "length": float(length),
    }

    # Short strings do not carry enough signal to measure; treating a one-line
    # note as corrupt would be worse than letting binary through.
    if length < MIN_ASSESSABLE_CHARS:
        return TextQuality(READABLE, "too-short-to-assess", metrics)

    if metrics["replacement_ratio"] > MAX_REPLACEMENT_RATIO:
        return TextQuality(UNREADABLE, "mojibake", metrics)
    if metrics["control_ratio"] > MAX_CONTROL_RATIO:
        return TextQuality(UNREADABLE, "binary-control-characters", metrics)
    if mean_token > MAX_MEAN_TOKEN_LENGTH and metrics["whitespace_ratio"] < MIN_WHITESPACE_RATIO:
        return TextQuality(UNREADABLE, "no-word-structure", metrics)
    return TextQuality(READABLE, "", metrics)


def first_readable_window(text: str, *, size: int = READABLE_WINDOW) -> str:
    """The first stretch of a partly corrupt document that reads as language.

    Corruption is localized, so the text is split on the runs of control and
    replacement characters that mark where extraction broke down, and each
    surviving segment is measured on its own. Scanning fixed windows instead
    would dilute a short readable header into the binary that follows it and
    discard a document that is perfectly usable.
    """
    if not (text or "").strip():
        return ""
    for segment in _CORRUPT_RUN.split(text):
        candidate = re.sub(r"\s+", " ", segment).strip()
        if len(candidate) < MIN_ASSESSABLE_CHARS:
            continue
        if assess_text_quality(candidate).readable:
            return candidate[:size]
    return ""


# ------------------------------------------------------------------ numbers

NUMERIC_ALIGNED = "aligned"
NUMERIC_NOT_IN_EVIDENCE = "number-not-in-evidence"
NUMERIC_NOT_CONNECTED = "figures-not-connected-in-source"
NUMERIC_NONE = "not-numeric"

#: How close two figures must sit in one source before treating the source as
#: having connected them. Adjacent-but-unrelated figures are the failure this
#: guards: a "$3–$4 per unit" target and a "1,000-unit" run are two facts until
#: the source says otherwise.
NUMERIC_PROXIMITY_CHARS = 160

_NUMBER_PATTERN = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)")
_CITATION_MARKER = re.compile(r"\[\d{1,3}\]")


def extract_numbers(text: str) -> List[str]:
    """Normalized figures in a piece of text, so `1,000` and `1000` compare equal."""
    return [value for _, value in _number_positions(text)]


def check_numeric_grounding(
    claim_text: str,
    cited_texts: Sequence[str],
    *,
    proximity: int = NUMERIC_PROXIMITY_CHARS,
) -> str:
    """Whether a claim's figures are present, and connected, in its own sources."""
    numbers = set(extract_numbers(_CITATION_MARKER.sub(" ", claim_text)))
    if not numbers:
        return NUMERIC_NONE

    available: Set[str] = set()
    for text in cited_texts:
        available.update(extract_numbers(text))
    if not numbers.issubset(available):
        return NUMERIC_NOT_IN_EVIDENCE

    if len(numbers) < 2:
        return NUMERIC_ALIGNED
    if any(_numbers_co_occur(text, numbers, proximity) for text in cited_texts):
        return NUMERIC_ALIGNED
    return NUMERIC_NOT_CONNECTED


def _numbers_co_occur(text: str, wanted: Set[str], proximity: int) -> bool:
    occurrences = [(pos, value) for pos, value in _number_positions(text) if value in wanted]
    for index, (anchor, _) in enumerate(occurrences):
        found: Set[str] = set()
        for position, value in occurrences[index:]:
            if position - anchor > proximity:
                break
            found.add(value)
        if wanted.issubset(found):
            return True
    return False


def _number_positions(text: str) -> List[Tuple[int, str]]:
    result: List[Tuple[int, str]] = []
    for match in _NUMBER_PATTERN.finditer(text or ""):
        normalized = _normalize_number(match.group(1))
        if normalized:
            result.append((match.start(), normalized))
    return result


def _normalize_number(raw: str) -> str:
    try:
        return f"{float(raw.replace(',', '')):g}"
    except ValueError:
        return ""


# ----------------------------------------------------------------- entities

LINKAGE_NOT_APPLICABLE = "single-entity"
LINKAGE_GROUNDED = "grounded"
LINKAGE_UNSUPPORTED = "entities-not-linked-in-source"


def check_entity_linkage(
    claim_text: str,
    entity_forms: Sequence[Any],
    cited_texts: Sequence[str],
    linked_pairs: Sequence[Tuple[str, str]] = (),
) -> str:
    """Whether a claim relating several entities has a source that links them.

    Two names resolving during retrieval says only that both appear somewhere in
    the corpus. Turning that into "GANG is a project at Eliro Inc." needs a
    source that mentions both, or a relationship assertion — which the entity
    layer already requires evidence for. Titles and entity types do not count.

    `entity_forms` is one entry per entity: either a name, or the group of
    surface forms that entity is known by. Grouping matters because documents
    write "Frank" where the canonical record says "Frank Godchaux", and
    demanding the canonical spelling would report almost every real link as
    unsupported.
    """
    named = _named_entities(claim_text, entity_forms)
    if len(named) < 2:
        return LINKAGE_NOT_APPLICABLE

    for first, second in linked_pairs:
        sides = [_text(first), _text(second)]
        if len(named) == 2 and all(
            any(_mentions_any(side, group) for side in sides) for group in named
        ):
            return LINKAGE_GROUNDED

    for text in cited_texts:
        if all(_mentions_any(text, group) for group in named):
            return LINKAGE_GROUNDED
    return LINKAGE_UNSUPPORTED


def _mentions_any(haystack: str, forms: Sequence[str]) -> bool:
    lowered = (haystack or "").casefold()
    return any(form and form.casefold() in lowered for form in forms)


def _named_entities(claim_text: str, entity_forms: Sequence[Any]) -> List[List[str]]:
    """Entity groups the claim names, longest surface form winning."""
    matched: List[Tuple[str, List[str]]] = []
    for entry in entity_forms:
        group = [entry] if isinstance(entry, str) else [value for value in entry if value]
        hits = [form for form in group if len(form) >= 2 and form.casefold() in (claim_text or "").casefold()]
        if not hits:
            continue
        matched.append((max(hits, key=len), group))

    # "Eliro" inside "Eliro Inc." is one mention, not two entities.
    result: List[List[str]] = []
    for form, group in matched:
        if any(form.casefold() in other.casefold() and form.casefold() != other.casefold() for other, _ in matched):
            continue
        if group not in result:
            result.append(group)
    return result


# -------------------------------------------------------------- dependencies

DEPENDENCY_NOT_APPLICABLE = "not-applicable"
DEPENDENCY_GROUNDED = "grounded"
DEPENDENCY_UNSUPPORTED = "unsupported"

#: Claim wording that asserts one thing is required by, blocks, or gates
#: another. These are the statements that change what somebody does next, so
#: they need a source that says it rather than a source that happens to list
#: the two items near each other.
_DEPENDENCY_ASSERTION = re.compile(
    r"\b(?:is|are|was|were|will\s+be|remains?)\s+(?:\w+\s+){0,2}required\b"
    r"|\brequired\s+(?:for|to|before|by|prior\s+to|in\s+order)\b"
    r"|\brequirement\s+(?:for|of|before)\b"
    r"|\brequires?\b"
    r"|\bdepends?\s+on\b|\bdependent\s+(?:on|upon)\b|\bdependency\b"
    r"|\bprerequisite\b|\bpre-?condition\b"
    r"|\bblock(?:s|ed|ing|er)\b"
    r"|\bcontingent\s+(?:on|upon)\b|\bgated\s+(?:on|by)\b|\bgating\b"
    r"|\bneeded\s+(?:for|to|before)\b|\bnecessary\s+(?:for|to|before)\b"
    r"|\b(?:must|needs?\s+to|has\s+to|have\s+to)\b[^.]{0,60}?\bbefore\b"
    r"|\b(?:cannot|can'?t|could\s+not)\b[^.]{0,60}?\b(?:until|without)\b",
    re.IGNORECASE,
)

#: Evidence wording that states a dependency outright. Deliberately broader
#: than the claim pattern: the question here is only "did any cited source
#: talk about one thing needing another at all", and a near miss should cost
#: the reader a warning rather than a true statement.
_DEPENDENCY_EVIDENCE = re.compile(
    r"\brequir\w*\b|\bdepend\w*\b|\bprerequisite\b|\bpre-?condition\b"
    r"|\bblock(?:s|ed|ing|er)\b|\bcontingent\b|\bgat(?:ed|ing)\b"
    r"|\bmandatory\b|\bnecessary\b|\bneeded\b|\bwaiting\s+on\b"
    r"|\bbefore\s+(?:we|you|they|the|any|final|submission|resubmission)\b"
    r"|\buntil\b|\bmust\b",
    re.IGNORECASE,
)


def asserts_dependency(claim_text: str) -> bool:
    """Whether the claim says one thing requires, blocks, or gates another."""
    return bool(_DEPENDENCY_ASSERTION.search(claim_text or ""))


def check_dependency_grounding(claim_text: str, cited_texts: Sequence[str]) -> str:
    """Whether a stated requirement is actually stated by the cited evidence.

    Task lists are the motivating case. ``tasks.txt`` puts "resubmit the Qi
    certification" one line above "procure a permanent UPC code", and a model
    reading the two together will happily report that the UPC blocks the
    certification. Nothing in the source says that. Adjacency is layout, not
    logic, so a dependency claim whose cited sources never use the vocabulary
    of dependence is reported as unsupported.

    The check is one-directional on purpose: it can tell that no cited source
    talks about anything requiring anything, which is the failure seen in
    practice. It does not try to verify that a real dependency statement is
    about the same two items.
    """
    if not asserts_dependency(claim_text):
        return DEPENDENCY_NOT_APPLICABLE
    for text in cited_texts:
        if _DEPENDENCY_EVIDENCE.search(_text(text)):
            return DEPENDENCY_GROUNDED
    return DEPENDENCY_UNSUPPORTED


# ---------------------------------------------------------------- negatives

ABSENCE_NOT_DENIAL = (
    "I found no evidence in the retrieved corpus about this. That is an absence of "
    "evidence, not a denial: it does not establish that the answer is no."
)

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

_NEGATIVE_OPENING = re.compile(r"^\s*(?:no|nope|never|negative)\b[\s.,!:;—-]", re.IGNORECASE)
_NEGATIVE_BARE = re.compile(r"^\s*(?:no|nope|never|negative)\s*[.!]?\s*$", re.IGNORECASE)
_NEGATIVE_ASSERTION = re.compile(
    r"(?:"
    r"\b(?:we|they|you|it|the team|the company|the board|the group)\s+"
    r"(?:did|do|does|have|has|had|was|were|is|are|will|would)\s*n[o']t\b"
    r"|\bthere\s+(?:is|was|are|were)\s+no\b"
    r"|\bnever\s+(?:decided|agreed|discussed|considered|happened|occurred|made|planned)\b"
    r"|\bdid\s+not\s+(?:decide|happen|occur|agree|discuss|consider|make|plan)\b"
    r"|\bno\s+(?:such\s+)?(?:decision|plan|agreement|discussion|meeting)\s+(?:was|were|has|have)\b"
    r")",
    re.IGNORECASE,
)

#: Phrasings that are already about the corpus rather than about the world.
#: These are the shapes we *want*, so they must survive the filter.
_EVIDENCE_HEDGE = re.compile(
    r"\b(?:evidence|corpus|retrieved|record(?:s|ed)?|document(?:s|ed)?|source(?:s)?|"
    r"establish(?:es|ed)?|indicat\w+|couldn'?t find|could not find|didn'?t find|did not find|"
    r"no mention|not mentioned|nothing (?:in|about))\b",
    re.IGNORECASE,
)


def is_unsupported_categorical_negative(sentence: str) -> bool:
    """A flat denial about the world, rather than a statement about the corpus."""
    text = (sentence or "").strip()
    if not text:
        return False
    if _EVIDENCE_HEDGE.search(text):
        return False
    return bool(
        _NEGATIVE_BARE.match(text) or _NEGATIVE_OPENING.match(text) or _NEGATIVE_ASSERTION.search(text)
    )


def soften_unsupported_negatives(answer: str) -> Tuple[str, List[str]]:
    """Strip flat denials from an answer the evidence cannot support.

    Absence of evidence is not evidence of absence. When nothing retrieved backs
    a negative, "No." is removed and replaced with what is actually true: that
    nothing was found. Surviving sentences are kept, so useful context about
    what the corpus *does* contain is not thrown away with the denial.
    """
    text = (answer or "").strip()
    if not text:
        return ABSENCE_NOT_DENIAL, []

    kept: List[str] = []
    removed: List[str] = []
    for line in text.splitlines():
        if not line.strip():
            kept.append(line)
            continue
        survivors = []
        for sentence in _SENTENCE_SPLIT.split(line.strip()):
            if is_unsupported_categorical_negative(sentence):
                removed.append(sentence.strip())
            else:
                survivors.append(sentence.strip())
        if survivors:
            kept.append(" ".join(survivors))

    if not removed:
        return text, []

    body = "\n".join(kept).strip()
    return (f"{ABSENCE_NOT_DENIAL}\n\n{body}" if body else ABSENCE_NOT_DENIAL), removed


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()

