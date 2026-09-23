"""Deterministic extraction of explicit decision records.

A decision record is materialized only where the document marks something as
decided. Four markers count:

``decision-section``
    A heading that says so — ``Decision``, ``Decisions``, ``Key Decisions``,
    ``Decisions / Alignment`` — and the items recorded under it, up to the
    next section. A singular ``Decision`` heading contributes its first
    paragraph only; the paragraphs after it are usually the rationale.
``decision-inline``
    ``Decision made: …`` or ``Decision: …`` on the line itself.
``decision-topic``
    A meeting-summary topic named "… decisions" followed by its ``: …``
    paragraph, from which the sentences carrying a decision verb are kept.
``group-agreement``
    In formal notes only: a sentence whose subject is the team, the group,
    the board, management, or named people, and whose verb is agreed,
    decided, approved, rejected, aligned on, or chose. "No decision was made
    to …" is recorded too, as an explicit *non*-decision.

What never counts: a question (the ``Decision`` headings in a forward agenda
are questions still to be answered), "Decision required", anything in bulk
mail, and anything in a quoted reply. Topic words appearing near the word
"decide" are not a decision.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple

from .extract import paragraphs, sentences
from .model import (
    MAX_CONTEXT,
    MAX_DECISION_TEXT,
    STATUS_AGREED,
    STATUS_ALIGNED,
    STATUS_APPROVED,
    STATUS_DECIDED,
    STATUS_NOT_DECIDED,
    STATUS_REJECTED,
    display_text,
)


RULE_SECTION = "decision-section"
RULE_INLINE = "decision-inline"
RULE_TOPIC = "decision-topic"
RULE_GROUP = "group-agreement"

_QUOTED_LINE = re.compile(r"^\s*(?:>|&gt;)")

#: ``Decision``, ``Decisions``, ``Key Decisions``, ``Decision made``,
#: ``Decisions / Alignment``, ``Decisions and next steps``. What follows the
#: heading on the same line is either nothing, an inline ``: statement``, or
#: a short label (HTML-to-text conversion often glues the first label on).
_HEADING = re.compile(
    r"^\s*(?:[-*•]\s+)?(?:#{1,6}\s*)?[*_]*\s*"
    r"(?P<head>(?:key\s+|final\s+)?decisions?(?P<made>\s+made)?"
    r"(?:\s*(?:/|and|&)\s*(?P<align>alignment|agreements?|next\s+steps))?)"
    r"[*_]*\s*(?P<rest>.*)$",
    re.IGNORECASE,
)

#: Words that turn a "Decision" heading into a request for one.
_NOT_A_DECISION_HEADING = re.compile(
    r"^(?:required|requested|needed|pending|point|points|rights|making|maker|makers|tree|"
    r"log|framework|criteria|deadline|date|matrix|gate|to\s+be\s+made)\b",
    re.IGNORECASE,
)

_STATUS_LINE = re.compile(
    r"^\s*[*_]*\s*(?P<status>approved\s*/\s*aligned|approved|aligned|agreed|confirmed|"
    r"ongoing\s+aligned)\s*[*_:]*\s*$",
    re.IGNORECASE,
)

#: Where a decision section ends.
_BOUNDARY = re.compile(
    r"^\s*[*_#]*\s*(?:open\s+(?:items|questions|issues)|matters\s+requiring|requires?\s+follow[\s-]?up|"
    r"remaining\s+work|next\s+steps|action\s+items|deliverables|owner\b|risks?\b|"
    r"follow[\s-]?ups?|discussion|attendees|participants|agenda|actions\s+for|"
    r"operating\s+consideration|expected\s+output|not\s+approved|deferred|pending|"
    r"parking\s+lot|questions\b|summary\b|key\s+topics|needs?\s+further\s+discussion|"
    r"further\s+discussion|unresolved|to\s+be\s+determined|tbd\b|open\b)",
    re.IGNORECASE,
)
_SEPARATOR = re.compile(r"^\s*[-=_*]{5,}\s*$")
_SECTION_HEADER = re.compile(r"^(?:#{1,6}\s+.+|\d{1,2}\.\s+[A-Z][^.]{2,80})$")
_BULLET = re.compile(r"^\s*(?:[-*•▪◦]|\d{1,2}[.)])\s+")

#: The ``: …`` line under a meeting-summary topic.
_TOPIC_LINE = re.compile(r"^\s*(?P<topic>[^:]{3,80}?)\s+decisions?\s*$", re.IGNORECASE)
_TOPIC_BODY = re.compile(r"^\s*:\s*(?P<text>\S.*)$")

_DECISION_VERB = re.compile(
    r"\b(?:agreed|decided|approved|rejected|aligned\s+(?:on|around)|chose|selected|"
    r"settled\s+on|resolved\s+to|will\s+use|opted)\b",
    re.IGNORECASE,
)

_GROUP_SUBJECT = (
    r"(?:(?i:(?:the\s+)?(?:team|group|board|management|founders|executive\s+team|leadership)|"
    r"we|both\s+founders|all\s+parties|everyone)|"
    r"[A-Z][a-z]+(?:\s*,\s*[A-Z][a-z]+)*\s+(?:and|&)\s+[A-Z][a-z]+)"
)
_GROUP_AGREEMENT = re.compile(
    rf"^(?:{_GROUP_SUBJECT})\b[^.?!]{{0,40}}?\b"
    r"(?P<verb>agreed|decided|approved|rejected|aligned\s+(?:on|around)|chose|selected|settled\s+on)\b",
)
_PROCEDURAL = re.compile(
    r"\b(?:agreed|decided)\s+to\s+(?:discuss|revisit|meet|follow\s+up|review|consider|think|"
    r"continue\s+discussing|reconvene|circle\s+back|table|defer|schedule)\b",
    re.IGNORECASE,
)
_NEGATED = re.compile(r"\b(?:not|never|no|didn['’]t|did\s+not|hasn['’]t|haven['’]t|yet\s+to)\b", re.IGNORECASE)
_NON_DECISION = re.compile(
    r"^(?:no\s+(?:final\s+)?decision\s+(?:was|has\s+been)\s+(?:made|reached|taken)|"
    r"no\s+(?:final\s+)?[\w-]+(?:\s+[\w-]+){0,4}\s+(?:was|has\s+been)\s+approved)\b",
    re.IGNORECASE,
)

MIN_DECISION_CHARS = 12
MAX_SECTION_LINES = 60


@dataclass(frozen=True)
class DecisionCandidate:
    text: str
    status: str
    rule: str
    context: str = ""


def extract_decisions(body: str, *, formal: bool) -> List[DecisionCandidate]:
    """Every explicit decision in one document body.

    ``formal`` enables the group-agreement rule, which is only trusted in
    meeting notes and company documents: in ordinary email prose, "we agreed"
    is as often a pleasantry as a record.
    """
    lines = [line.rstrip() for line in (body or "").splitlines()]
    found: List[DecisionCandidate] = []
    seen: set = set()

    def add(candidate: Optional[DecisionCandidate]) -> None:
        if candidate is None:
            return
        text = display_text(candidate.text).lstrip(": ").strip()
        if len(text) < MIN_DECISION_CHARS or len(text) > MAX_DECISION_TEXT:
            return
        if text.endswith(("?", ":")):
            # A question is not a decision, and "consisting of:" introduces
            # one without stating it.
            return
        key = re.sub(r"[^\w]+", " ", text.casefold()).strip()
        if key in seen:
            return
        seen.add(key)
        found.append(
            DecisionCandidate(
                text=text,
                status=candidate.status,
                rule=candidate.rule,
                context=display_text(candidate.context)[:MAX_CONTEXT],
            )
        )

    index = 0
    while index < len(lines):
        line = lines[index]
        if _QUOTED_LINE.match(line):
            index += 1
            continue

        topic = _TOPIC_LINE.match(line)
        if topic and index + 1 < len(lines) and _TOPIC_BODY.match(lines[index + 1]):
            text = _TOPIC_BODY.match(lines[index + 1]).group("text")
            for candidate in _topic_decisions(text, topic.group("topic")):
                add(candidate)
            index += 2
            continue

        heading = _HEADING.match(line)
        if heading and _is_decision_heading(heading):
            consumed = _read_heading(lines, index, heading, add)
            index = max(index + 1, consumed)
            continue
        index += 1

    if formal:
        for paragraph in paragraphs(body):
            if _HEADING.match(paragraph.lines[0]):
                continue
            for sentence in sentences(paragraph.text):
                add(_group_agreement(sentence))
    return found


def _is_decision_heading(heading: "re.Match") -> bool:
    rest = (heading.group("rest") or "").strip()
    if not rest or rest == ":":
        return True
    if rest.startswith(":"):
        return bool(rest[1:].strip())
    if _NOT_A_DECISION_HEADING.match(rest):
        return False
    # A glued-on label ("Decisions / AlignmentFractional CFO") or a status
    # word ("DecisionsAligned"): short, no sentence punctuation, capitalized.
    return len(rest) <= 60 and rest[:1].isupper() and not re.search(r"[.?!,;]\s*$", rest)


def _read_heading(lines: Sequence[str], start: int, heading: "re.Match", add) -> int:
    rest = (heading.group("rest") or "").strip()
    if rest == ":":
        rest = ""
    status = _status_from_heading(heading)
    context = _enclosing_section(lines, start)

    # "Decision made: we will use the thicker handled screwdriver. Jess …"
    inline = rest[1:].strip() if rest.startswith(":") else ""
    if not inline and not rest and start + 1 < len(lines):
        follow = _TOPIC_BODY.match(lines[start + 1])
        if follow and heading.group("made"):
            inline = follow.group("text")
            start += 1
    if inline:
        text_lines = [inline]
        cursor = start + 1
        while cursor < len(lines) and lines[cursor].strip() and not _BULLET.match(lines[cursor]):
            if _HEADING.match(lines[cursor]) or len(text_lines) >= 6:
                break
            if re.search(r"[.!?][*_]*$", text_lines[-1]) and lines[cursor].strip()[:1].isupper():
                # The statement finished on the previous line.
                break
            text_lines.append(lines[cursor].strip())
            cursor += 1
        add(DecisionCandidate(" ".join(text_lines), status, RULE_INLINE, context))
        return cursor

    plural = bool(re.search(r"decisions", heading.group("head"), re.IGNORECASE))
    label = ""
    if rest:
        status_match = _STATUS_LINE.match(rest)
        if status_match:
            status = _status_word(status_match.group("status"))
        else:
            label = rest

    items: List[Tuple[str, str, str]] = []  # (text, label, status)
    buffer: List[str] = []

    def flush() -> None:
        if buffer:
            items.append((" ".join(buffer), label, status))
            buffer.clear()

    cursor = start + 1
    seen_content = False
    while cursor < len(lines) and cursor - start <= MAX_SECTION_LINES:
        raw = lines[cursor]
        line = raw.strip()
        cursor += 1
        if _QUOTED_LINE.match(raw):
            break
        if not line:
            flush()
            if seen_content and not plural:
                break
            continue
        if _SEPARATOR.match(line) or _BOUNDARY.match(line):
            break
        if not raw.startswith((" ", "\t")) and _SECTION_HEADER.match(line) and not _BULLET.match(raw):
            break
        if _HEADING.match(line) and _is_decision_heading(_HEADING.match(line)):
            cursor -= 1
            break
        status_match = _STATUS_LINE.match(line)
        if status_match:
            flush()
            status = _status_word(status_match.group("status"))
            continue
        if _BULLET.match(raw):
            flush()
            buffer.append(_BULLET.sub("", raw).strip())
            seen_content = True
            continue
        if _is_label(line, lines, cursor):
            flush()
            label = line.strip("*_: ")
            continue
        if buffer and re.search(r"[.!?][*_]*$", buffer[-1]) and line[:1].isupper():
            # The previous line finished a statement; this one starts the next.
            flush()
        buffer.append(line)
        seen_content = True
    flush()

    for text, item_label, item_status in items:
        add(DecisionCandidate(text, item_status, RULE_SECTION, item_label or context))
    return cursor


def _is_label(line: str, lines: Sequence[str], next_index: int) -> bool:
    """A short heading-like line that names what the next statement is about:
    ``*Packaging*``, ``Formation Valuation``, ``3PL``."""
    text = line.strip()
    bare = text.strip("*_: ")
    if not bare or len(bare) > 48 or re.search(r"[.!?,;]$", bare):
        return False
    words = bare.split()
    if len(words) > 6:
        return False
    if not (bare[:1].isupper() or bare[:1].isdigit()):
        return False
    emphasized = text.startswith("*") and text.rstrip(":").endswith("*")
    capitalized = sum(1 for word in words if word[:1].isupper() or word[:1].isdigit())
    if not emphasized and capitalized < max(1, len(words) - 1):
        return False
    # A label introduces something: the next non-blank line must be a statement.
    for following in lines[next_index : next_index + 3]:
        if following.strip():
            return len(following.strip()) > len(bare)
    return False


def _enclosing_section(lines: Sequence[str], start: int) -> str:
    """The numbered or Markdown section a ``Decision`` heading sits inside."""
    for cursor in range(start - 1, max(-1, start - 40), -1):
        line = lines[cursor].strip()
        if _SEPARATOR.match(line):
            break
        raw = lines[cursor]
        if not raw.startswith((" ", "\t")) and _SECTION_HEADER.match(line):
            return re.sub(r"^#{1,6}\s+", "", line)
    return ""


def _topic_decisions(text: str, topic: str) -> List[DecisionCandidate]:
    parts = sentences(display_text(text))
    chosen = [part for part in parts if _DECISION_VERB.search(part)]
    candidates = []
    for sentence in chosen:
        status = STATUS_REJECTED if re.search(r"\brejected\b", sentence, re.IGNORECASE) and not re.search(
            r"\b(?:agreed|approved|decided)\b", sentence, re.IGNORECASE
        ) else STATUS_AGREED
        candidates.append(DecisionCandidate(sentence, status, RULE_TOPIC, topic))
    return candidates


def _group_agreement(sentence: str) -> Optional[DecisionCandidate]:
    text = display_text(sentence)
    if not text or text.endswith("?"):
        return None
    if _NON_DECISION.match(text):
        return DecisionCandidate(text, STATUS_NOT_DECIDED, RULE_GROUP)
    match = _GROUP_AGREEMENT.match(text)
    if not match:
        return None
    lead = text[: match.start("verb")]
    if _NEGATED.search(lead) or _PROCEDURAL.search(text):
        return None
    if len(re.findall(r"\w+", text[match.end("verb") :])) < 3:
        # "Daniel and Frank agreed." records that people agreed, not what.
        return None
    verb = match.group("verb").casefold()
    if verb.startswith("rejected"):
        status = STATUS_REJECTED
    elif verb.startswith("approved"):
        status = STATUS_APPROVED
    elif verb.startswith("aligned"):
        status = STATUS_ALIGNED
    elif verb.startswith("agreed"):
        status = STATUS_AGREED
    else:
        status = STATUS_DECIDED
    return DecisionCandidate(text, status, RULE_GROUP)


def _status_from_heading(heading: "re.Match") -> str:
    if heading.group("made"):
        return STATUS_DECIDED
    if heading.group("align"):
        align = heading.group("align").casefold()
        if align.startswith("alignment"):
            return STATUS_ALIGNED
        if align.startswith("agreement"):
            return STATUS_AGREED
    return STATUS_DECIDED


def _status_word(value: str) -> str:
    folded = re.sub(r"\s+", " ", value.casefold())
    if "approved" in folded:
        return STATUS_APPROVED
    if "aligned" in folded:
        return STATUS_ALIGNED
    if "agreed" in folded:
        return STATUS_AGREED
    return STATUS_DECIDED
