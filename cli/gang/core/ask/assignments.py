"""What is explicitly on one person's plate — read from evidence, never inferred.

"What does Daniel need to do?" is not a definition question and not a
participation question. It asks for work the record *assigns* to someone: an
action item with their name in the owner field, a schedule line reading
``Owner: Daniel | Due: … | Status: …``, a meeting note saying "Daniel will
confirm the registration source", a task email addressed ``@Daniel: get CE the
art file``.

This module finds exactly those, and nothing looser. The rules that keep it
honest:

* **The name has to be the subject of the assignment.** "Daniel will send" is
  an assignment; "Daniel noted that GANG-Tech owns the work product" is not,
  and neither is "meet with Daniel to discuss". The owner is the name directly
  in front of the obligation, or the value of an owner field.
* **Attendance is never ownership.** A name on a ``To:``, ``Cc:`` or
  ``Attendees:`` line is masked out before anything is read, and an item in a
  bulleted list is only assigned if its own line names the owner — the bullets
  after "Daniel to obtain 3PL pricing" are not Daniel's by proximity.
* **Status comes from the source.** Where a schedule or owner table states a
  status, it is carried through, and the newest statement of an item's status
  wins. Completed and superseded work is kept apart from current work rather
  than silently dropped.
* **One task, one line.** A task repeated across a meeting recap, a daily
  schedule email, and a forwarded thread collapses into one entry that cites
  every document it came from.

Everything is deterministic. No model reads, extracts, or phrases any of it.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from core import enrichment_state

from .temporal import date_prefix


# ------------------------------------------------------------------ bounds

MAX_TASK_CHARS = 220
MAX_SCAN_CHARS = 60000
MAX_DOCUMENTS_PER_ASSIGNMENT = 6

#: Words that sit next to a name in the documents that assign work: owner
#: fields, task mail, deliverable tables, and "Daniel will…". Each is searched
#: alongside the person's name, so older assignment records are found and not
#: just the newest mail that happens to mention them.
SEARCH_CUES = ("owner", "tasks", "will", "action items", "deliverables", "due")

#: Two task phrasings sharing this share of their content words are the same
#: task stated twice. High on purpose: merging two different tasks loses one.
DUPLICATE_OVERLAP = 0.75


# ------------------------------------------------------------------ status

OPEN = "open"
IN_PROGRESS = "in-progress"
BLOCKED = "blocked"
DONE = "done"
SUPERSEDED = "superseded"

CLOSED_STATES = frozenset({DONE, SUPERSEDED})

#: "not started", "not yet started", "not  started". Checked before a bare
#: "started" is read as in progress.
_NOT_YET_STARTED = r"not(?:\s+\w+){0,3}\s+started"
_NOT_YET_STARTED_PATTERN = re.compile(r"\b" + _NOT_YET_STARTED + r"\b", re.I)

_STATUS_WORDS: Tuple[Tuple[str, re.Pattern], ...] = (
    (SUPERSEDED, re.compile(r"\b(?:superseded|cancell?ed|dropped|obsolete|replaced|no\s+longer\s+needed|withdrawn)\b", re.I)),
    (DONE, re.compile(r"\b(?:done|complete|completed|closed|finished|resolved|delivered)\b", re.I)),
    (BLOCKED, re.compile(r"\b(?:blocked|delayed|dependent|at\s+risk|on\s+hold)\b", re.I)),
    (IN_PROGRESS, re.compile(r"\b(?:in\s+progress|ongoing|underway|(?<!not\s)started|critical|near\s+completion)\b", re.I)),
    (OPEN, re.compile(r"\b(?:open|" + _NOT_YET_STARTED + r"|pending|to\s*do|new(?:\s+responsibility)?|aligned)\b", re.I)),
)


def normalize_status(text: Any) -> str:
    """Map a source's own status wording onto a small vocabulary, or ``""``.

    A bare "started" is in progress, but "not started" and "not yet started"
    are open. The in-progress pattern can only look one space behind "started",
    so a longer "not … started" is skipped here and falls through to open.
    """
    value = str(text or "")
    not_yet = _NOT_YET_STARTED_PATTERN.search(value)
    for status, pattern in _STATUS_WORDS:
        found = pattern.search(value)
        if not found:
            continue
        if status == IN_PROGRESS and found.group(0).casefold() == "started" and not_yet:
            continue
        return status
    return ""


# ------------------------------------------------------------------ grammar

#: Header lines recording who was on a thread or in a room. Masked before
#: anything is read, so a name on one can never be the subject of a task.
#: A header's value is a run of names, addresses, and separators, so the span
#: ends at the first word that is none of those — which also bounds it when
#: ingested mail arrives with its line breaks collapsed.
_PARTICIPANT_SPAN = re.compile(
    r"(?:^|(?<=\s))(?:Participants|Attendees|Present|From|To|Cc|CC|Bcc|BCC)[ \t]*:"
    r"(?:[ \t]*(?:[A-Z][\w'’.-]*|[\w.+-]+@[\w-]+(?:\.[\w-]+)+|<[^>\n]{0,120}>|and|&|[,;()]))*"
)

#: An obligation starting right where a participant list stops. In collapsed
#: minutes, "Attendees: Frank Godchaux, Dana Reyes Daniel will confirm…" ends
#: its list with the subject of the next sentence.
_OBLIGATION_AHEAD = re.compile(r"\s+(?:will|shall|to|should|must|needs\s+to|is\s+to|owns)\s+[a-z]")

#: Obligation phrases that make the name in front of them the owner. Lower
#: case only: in collapsed mail "Hi Daniel Will you…" is a greeting running
#: into a question, not an assignment.
_OBLIGATION = (
    r"(?:will|shall|is\s+to|is\s+going\s+to|needs\s+to|need\s+to|has\s+to|must|should|"
    r"agreed\s+to|committed\s+to|offered\s+to|volunteered\s+to|to|"
    r"owns|is\s+responsible\s+for|is\s+accountable\s+for|is\s+assigned\s+to|"
    r"is\s+handling|is\s+taking)"
)

#: Adverbs that may sit between the name and the obligation.
_ADVERB = r"(?:(?:also|then|now|still|first|therefore|next|separately)\s+)?"

#: A word before the name that makes someone *else* the subject: "meet with
#: Daniel to discuss", "thanks Daniel to…", "cc Daniel to keep him posted".
_NOT_SUBJECT_BEFORE = re.compile(
    r"(?:\b(?:with|cc|bcc|copy|copying|copied|from|by|via|per|thank|thanks|hi|hello|hey|dear|"
    r"cheers|regards|best|sincerely|and\s+cc)\s*,?\s*)$",
    re.I,
)

#: Verbs after an obligation that describe a state or participation, not work.
_NOT_WORK = re.compile(
    r"^(?:be|been|being|have|had|probably|likely|not|never|also\s+be|attend|join|see|like|"
    r"love|want|know|think|feel|find|arrive|return|travel|miss|do|do\s+it|do\s+that|"
    r"you|we|i|he|she|they|it|the|a|an)\b",
    re.I,
)

_OWNER_LABEL = re.compile(
    r"\b(?:Owner|Owners|Assignee|Assigned\s+to|Responsible|Action\s+owner|DRI)\s*[:=]\s*",
    re.I,
)

#: Field labels that may follow a name without being read as its surname.
_FIELD_LABEL = r"(?:Due|Deadline|Status|Tips|Notes?|Owner|Timing)\b"

_SEGMENT_START = re.compile(r"(?:^|\s)(?:\d{1,2}[.)]|[-•*–])\s+|[.!?:]\s+")

#: Where a pipe-delimited field ends: the next pipe or label, the next list
#: item, or the end of a sentence.
_FIELD = r"(?=\s*\||\s+(?:Due|Deadline|Status|Tips|Notes?|Owner)\s*:|\s+\d{1,2}[.)]\s|[.!?](?:\s|$)|$)"
_DUE_FIELD = re.compile(r"\b(?:Due|Deadline|Due\s+date)\s*:\s*(?P<value>[^|]{1,60}?)" + _FIELD)
_STATUS_FIELD = re.compile(r"\bStatus\s*:\s*(?P<value>[^|]{1,40}?)" + _FIELD)

_MONTH_WORD = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d"

#: One capitalized word of a name, taken whole. The possessive quantifier
#: stops a surname check from succeeding by ending mid-word ("Finalize" must
#: not shrink to "Finaliz"). A second word is a surname only when the owner
#: value ends there ("Creative Engineering", "Frank Godchaux"). A second word
#: followed by another capitalized word is the next task ("Daniel Finalize
#: Qi Certification"), and a month is the next row's date ("Frank Sep 21").
_NAME_TOKEN = r"[A-Z][\w’'.-]*+"
_OWNER_SURNAME = (
    r"(?:[ \t]+(?!" + _MONTH_WORD + r")(?!" + _FIELD_LABEL + r")" + _NAME_TOKEN + r"(?![ \t]+[A-Z]))"
)
_OWNER_NAME = _NAME_TOKEN + _OWNER_SURNAME + r"?"

#: Any owner field's value — names separated by ``/``, ``,``, ``&`` or
#: "and" — whoever it names. Only used to find where the value ends, so the
#: next row's task does not begin with the previous row's owners.
_ANY_OWNER_LIST = re.compile(
    r"\s*" + _OWNER_NAME
    + r"(?:[ \t]*(?:/|,|&|\band\b)[ \t]*" + _OWNER_NAME + r"){0,5}"
)

#: A schedule's own trailing note on a task: "— scheduled end Sep 18;
#: baseline status In progress —". Its values are the row's deadline and
#: status, not part of the task.
_SCHEDULE_NOTE = re.compile(
    r"\s*[—–-]\s*(?=scheduled\s+end|baseline\s+status)"
    r"(?:scheduled\s+end\s+(?P<end>(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}|\d{4}-\d{2}-\d{2}))?"
    r"\s*;?\s*(?:baseline\s+status\s*:?\s*(?P<status>[A-Za-z][A-Za-z /-]{1,30}?))?\s*[—–-]?\s*$",
    re.I,
)

_BY_DEADLINE = re.compile(
    r"\bby\s+(?P<value>(?:mon|tues|wednes|thurs|fri|satur|sun)day|tomorrow|today|tonight|"
    r"end\s+of\s+(?:day|week|month|quarter)|eod|eow|next\s+week|"
    r"\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}(?:/\d{2,4})?|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}(?:st|nd|rd|th)?)\b",
    re.I,
)

_ISO_DATE = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

#: The header of a flattened owner table: "Owner Deliverable Deadline / Timing
#: Status". Rows follow as "<owner> <deliverable> <timing> <status>".
_TABLE_HEADER = re.compile(
    r"\bOwner\s+(?:Deliverable|Task|Action(?:\s+Item)?|Item)s?\b"
    r"(?:\s+(?:Deadline(?:\s*/\s*Timing)?|Due(?:\s+Date)?|Timing|Dependency|Dependencies|Notes?|Status))*",
)
_TABLE_END = re.compile(r"-{5,}|\s(?:The|This|These|Next)\s")
_TABLE_STATUS = (
    r"(?P<status>(?:Critical\s*/\s*)?(?:In\s+Progress|Not\s+Started|New\s+Responsibility|"
    r"Near\s+Completion|Delayed(?:\s*/\s*Dependent)?|Dependent|At\s+Risk|On\s+Hold|"
    r"Open|Done|Complete[d]?|Closed|Aligned|Critical|Blocked|Pending|Superseded|Cancell?ed)\b)"
)
#: The timing cell of a row. Whatever follows a keyword timing is a later
#: column (a dependency, a note) and is not part of the deadline.
_TABLE_TIMING = re.compile(
    r"\s+(?P<timing>(?:Before|By|Due|After|Until|Once)\s+.+|Immediate(?:ly)?|Ongoing|Near\s+term|"
    r"Weekly|Monthly|TBD|"
    r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2}\b(?:\s*[—–-]\s*\w+)?|"
    r"\d{4}-\d{2}-\d{2})(?:\s+.*)?$"
)

#: Abbreviations whose period does not end a sentence ("incl.", "approx.").
_ABBREVIATIONS = (
    "incl", "approx", "etc", "vs", "est", "no", "Mr", "Ms", "Mrs", "Dr", "St", "Inc", "Ltd", "Co",
    "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep", "Sept", "Oct", "Nov", "Dec",
)
_NOT_A_STOP = (
    r"(?:[^.!?]|\.(?=\S)|(?:" + "|".join(r"(?<=\b" + word + r")" for word in _ABBREVIATIONS) + r")\.)"
)

_TOKEN = re.compile(r"[a-z0-9]+")
_TASK_STOPWORDS = frozenset(
    """
    a an and the to of for on in at by with from as is are be this that it its
    will should must need needs soon possible asap please also then
    """.split()
)

_FIRST_PERSON = re.compile(r"^(?:i|me|my|myself)$", re.I)


# ------------------------------------------------------------------ records


@dataclass
class Assignment:
    """One task, the person it is assigned to, and everywhere it is stated."""

    task: str
    owner: str
    basis: str
    co_owners: List[str] = field(default_factory=list)
    deadline: str = ""
    status: str = ""
    status_text: str = ""
    document_ids: List[str] = field(default_factory=list)
    titles: List[str] = field(default_factory=list)
    date: str = ""
    status_date: str = ""
    stale: bool = False
    excerpt: str = ""

    @property
    def closed(self) -> bool:
        return self.status in CLOSED_STATES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "owner": self.owner,
            "co_owners": list(self.co_owners),
            "basis": self.basis,
            "deadline": self.deadline,
            "status": self.status,
            "status_text": self.status_text,
            "closed": self.closed,
            "document_ids": list(self.document_ids),
            "titles": list(self.titles),
            "date": self.date,
            "stale": self.stale,
            "excerpt": self.excerpt,
        }


@dataclass(frozen=True)
class Person:
    """Who the question is about, as the forms their name is written in.

    ``resolved`` is whether those forms came from a canonical entity (name and
    verified aliases) rather than from the question's own wording. An
    unresolved given name may be followed by a surname in the evidence
    ("Daniel Hirunrusme will…"), and is allowed to be; a resolved one may not,
    because "Frank Smith" is not Frank Godchaux just for sharing a first name.
    """

    label: str
    forms: Tuple[str, ...]
    resolved: bool = False
    entity_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "label": self.label,
            "forms": list(self.forms),
            "resolved": self.resolved,
            "entity_id": self.entity_id,
        }


def is_first_person(subject: str) -> bool:
    return bool(_FIRST_PERSON.match((subject or "").strip()))


def person_from(
    label: str,
    *,
    aliases: Iterable[str] = (),
    resolved: bool = False,
    entity_id: str = "",
) -> Person:
    forms: List[str] = []
    for value in [label, *aliases]:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) >= 2 and text.casefold() not in {item.casefold() for item in forms}:
            forms.append(text)
    # Longest first, so "Frank Godchaux" is tried before "Frank".
    forms.sort(key=len, reverse=True)
    return Person(label=label, forms=tuple(forms), resolved=resolved, entity_id=entity_id)


# ------------------------------------------------------------------ gather


def gather(
    rows: Sequence[Dict[str, Any]],
    person: Person,
    *,
    since: str = "",
    until: str = "",
    limit: Optional[int] = None,
) -> List[Assignment]:
    """Every task the evidence explicitly assigns to ``person``, deduplicated.

    Rows are index rows: ``document_id``, ``title``, ``body``, dates, and the
    derived ``enrichment`` payload. Documents without a body (the enriched-row
    shape) contribute their structured action items only.
    """
    if not person.forms:
        return []
    name = _name_pattern(person)
    found: List[Assignment] = []
    seen_documents = set()
    for row in rows:
        document_id = str(row.get("document_id") or "")
        if not document_id or document_id in seen_documents:
            continue
        seen_documents.add(document_id)
        found.extend(_structured(row, person))
        body = row.get("body")
        if body:
            found.extend(_textual(row, str(body), person, name))

    merged = _deduplicate(found)
    merged = [item for item in merged if _within(item, since, until)]
    merged.sort(key=_order)
    return merged if limit is None else merged[: max(1, int(limit))]


# ------------------------------------------------------------- structured


def _structured(row: Dict[str, Any], person: Person) -> List[Assignment]:
    """Action items an existing extraction already attributes to this owner."""
    enrichment = row.get("enrichment") or {}
    entries = enrichment.get("action_items") if isinstance(enrichment, dict) else None
    if not isinstance(entries, list):
        return []
    stale = (row.get("enrichment_status") or "") == enrichment_state.STALE
    results: List[Assignment] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        owner_text = str(entry.get("owner") or entry.get("assignee") or "").strip()
        owners = _split_owners(owner_text)
        mine = [owner for owner in owners if _owner_matches(owner, person)]
        if not mine:
            continue
        task = _clean_task(
            next(
                (
                    str(entry.get(key))
                    for key in ("task", "action", "text", "item")
                    if isinstance(entry.get(key), str) and entry.get(key).strip()
                ),
                "",
            )
        )
        if not task:
            continue
        status_text = str(entry.get("status") or "").strip()
        results.append(
            _assignment(
                row,
                task=task,
                owner=mine[0],
                co_owners=[owner for owner in owners if owner not in mine],
                basis="action-item",
                deadline=str(entry.get("deadline") or entry.get("due") or "").strip(),
                status_text=status_text,
                excerpt=f"{task} (owner: {owner_text})",
                stale=stale,
            )
        )
    return results


# ---------------------------------------------------------------- textual


def _textual(row: Dict[str, Any], body: str, person: Person, name: re.Pattern) -> List[Assignment]:
    text = _prepare(body)
    results: List[Assignment] = []
    results.extend(_owner_tables(row, text, person))
    results.extend(_owner_labels(row, text, person))
    results.extend(_mentions(row, text, person, name))
    results.extend(_subject_obligations(row, text, person, name))
    results.extend(_passive_assignments(row, text, person, name))
    return results


def _prepare(body: str) -> str:
    text = html.unescape(body[:MAX_SCAN_CHARS])
    text = _PARTICIPANT_SPAN.sub(_mask_participants, text)
    text = re.sub(r"(?:^|\s)(?:>\s*)+", " ", text)  # quoted-reply markers
    return re.sub(r"\s+", " ", text).strip()


def _mask_participants(match: "re.Match") -> str:
    """Blank a participant header, except the subject of a following sentence.

    Only the last chunk of the list is ever kept — the capitalized words after
    its final separator — and only when an obligation follows immediately.
    A list item is never followed by "will confirm"; a sentence subject is.
    """
    value = match.group(0)
    if not _OBLIGATION_AHEAD.match(match.string, match.end()):
        return " "
    cut = max(value.rfind(mark) for mark in (",", ";", ">", ":", "&"))
    tail = value[cut + 1 :].strip()
    tokens = tail.split()
    if 1 <= len(tokens) <= 3 and all(token[:1].isupper() for token in tokens):
        return " " + tail
    return " "


def _subject_obligations(
    row: Dict[str, Any], text: str, person: Person, name: re.Pattern
) -> List[Assignment]:
    """"Daniel will confirm the registration source." The name owns the verb."""
    pattern = re.compile(
        name.pattern
        + r"(?:\s*\([^)]{0,40}\))?\s+"
        + _ADVERB
        + r"(?P<obligation>"
        + _OBLIGATION
        + r")\s+(?P<task>[a-z]" + _NOT_A_STOP + r"{3,400})"
    )
    results: List[Assignment] = []
    for match in pattern.finditer(text):
        if _NOT_SUBJECT_BEFORE.search(text[max(0, match.start() - 24) : match.start()]):
            continue
        task_text = match.group("task")
        if _NOT_WORK.match(task_text):
            continue
        obligation = re.sub(r"\s+", " ", match.group("obligation"))
        task = _clean_task(_obligation_task(obligation, task_text))
        if len(task.split()) < 2:
            continue
        sentence = _sentence_around(text, match.start(), match.end())
        results.append(
            _assignment(
                row,
                task=task,
                owner=match.group("name"),
                basis="assignment-language",
                deadline=_deadline_in(task_text),
                excerpt=sentence,
            )
        )
    return results


_LEADING_ADVERB = re.compile(
    r"^(?:therefore|also|then|now|still|first|next|ultimately|separately|immediately)\s+", re.I
)


def _obligation_task(obligation: str, task: str) -> str:
    task = _LEADING_ADVERB.sub("", task)
    if obligation == "owns":
        return f"Own {task}"
    if obligation.endswith("responsible for") or obligation.endswith("accountable for"):
        return f"Responsible for {task}"
    if obligation in ("is handling", "is taking"):
        return f"{obligation.split()[-1].capitalize()} {task}"
    return task


def _owner_labels(row: Dict[str, Any], text: str, person: Person) -> List[Assignment]:
    """"WPC Qi Certification Owner: Daniel | Due: 2026-09-20 | Status: in progress"."""
    owners_after = re.compile(r"\s*" + _owner_list_pattern(person))
    results: List[Assignment] = []
    # Where the previous owner field's value ended. In a flattened schedule
    # ("… — Owner: Frank/Daniel [Vendor] Next task — Owner: Daniel") the next
    # task starts there, not at the previous label.
    floor = 0
    for label in _OWNER_LABEL.finditer(text):
        previous_floor = floor
        value = _ANY_OWNER_LIST.match(text, label.end())
        floor = value.end() if value else label.end()
        owners_match = owners_after.match(text, label.end())
        if owners_match is None:
            continue
        owners = _split_owners(owners_match.group(0))
        mine = [owner for owner in owners if _owner_matches(owner, person)]
        if not mine:
            continue
        segment = _segment_before(text, label.start(), floor=previous_floor)
        tail = text[owners_match.end() : owners_match.end() + 240]
        due = _DUE_FIELD.search(tail)
        status = _STATUS_FIELD.search(tail)
        deadline = due.group("value").strip() if due else ""
        status_text = status.group("value").strip() if status else ""
        note = _SCHEDULE_NOTE.search(segment)
        if note and (note.group("end") or note.group("status")):
            segment = segment[: note.start()]
            deadline = deadline or (note.group("end") or "").strip()
            status_text = status_text or (note.group("status") or "").strip()
        task = _clean_task(segment)
        if len(task.split()) < 2:
            continue
        results.append(
            _assignment(
                row,
                task=task,
                owner=mine[0],
                co_owners=[owner for owner in owners if owner not in mine],
                basis="owner-field",
                deadline=deadline,
                status_text=status_text,
                excerpt=_short(f"{task} Owner: {owners_match.group(0).strip()}{' ' + tail[:120].strip() if tail.strip() else ''}"),
            )
        )
    return results


def _owner_tables(row: Dict[str, Any], text: str, person: Person) -> List[Assignment]:
    """Rows of a flattened ``Owner | Deliverable | Timing | Status`` table.

    A row is only read as this person's when it *starts* with their name —
    immediately after the header or after the previous row's status — so a
    name in some other row's deliverable ("Include Steven on future calls")
    never makes that row theirs.
    """
    forms = "|".join(re.escape(form) for form in person.forms)
    owner = r"[A-Z][\w’'-]+(?:\s+[A-Z][\w’'-]+)?"
    row_pattern = re.compile(
        r"\s*(?P<owners>(?:" + owner + r"\s*/\s*)*(?:" + forms + r")(?:\s*/\s*" + owner + r")*)"
        r"\s+(?P<body>[A-Z][^|]{3,300}?)\s+" + _TABLE_STATUS + r"(?=\s+[A-Z]|\s*$|\s*-)"
    )
    status = re.compile(_TABLE_STATUS)
    results: List[Assignment] = []
    for header in _TABLE_HEADER.finditer(text):
        end = _TABLE_END.search(text, header.end())
        region = text[header.end() : end.start() if end else header.end() + 3000]
        # A row starts right after the header or right after a status cell.
        starts = [0] + [found.end() for found in status.finditer(region)]
        for position in starts:
            match = row_pattern.match(region, position)
            if match is None:
                continue
            owners = _split_owners(match.group("owners"))
            mine = [value for value in owners if _owner_matches(value, person)]
            if not mine:
                continue
            body = match.group("body").strip()
            timing = _TABLE_TIMING.search(body)
            deadline = timing.group("timing").strip() if timing else ""
            task = _clean_task(body[: timing.start()] if timing else body)
            if len(task.split()) < 2:
                continue
            results.append(
                _assignment(
                    row,
                    task=task,
                    owner=mine[0],
                    co_owners=[value for value in owners if value not in mine],
                    basis="owner-table",
                    deadline=deadline,
                    status_text=match.group("status"),
                    excerpt=_short(match.group(0)),
                )
            )
    return results


def _mentions(row: Dict[str, Any], text: str, person: Person, name: re.Pattern) -> List[Assignment]:
    """"@Daniel Hirunrusme <daniel@…>: Get CE the art file." — a task addressed by name."""
    pattern = re.compile(
        r"@" + _name_core(person)
        + r"(?:\s*<[^>]{0,80}>)?\s*:\s*(?P<task>[^@]{3,400}?)(?=\s@|[.!?](?:\s|$)|$)"
    )
    results: List[Assignment] = []
    for match in pattern.finditer(text):
        task = _clean_task(match.group("task"))
        if len(task.split()) < 2:
            continue
        results.append(
            _assignment(
                row,
                task=task,
                owner=match.group("name"),
                basis="addressed-task",
                deadline=_deadline_in(match.group("task")),
                excerpt=_short(match.group(0)),
            )
        )
    return results


def _passive_assignments(
    row: Dict[str, Any], text: str, person: Person, name: re.Pattern
) -> List[Assignment]:
    """"… with Daniel as owner" and "The UPC purchase is assigned to Daniel"."""
    results: List[Assignment] = []
    as_owner = re.compile(r"\bwith\s+" + name.pattern + r"\s+as\s+(?:the\s+)?(?:owner|lead|DRI)\b")
    assigned = re.compile(
        r"(?:\bis|\bwas|\bare|\bhas\s+been|\bhave\s+been)?\s*\b(?:assigned\s+to|owned\s+by)\s+" + name.pattern + r"\b"
    )
    for pattern in (as_owner, assigned):
        for match in pattern.finditer(text):
            start = _sentence_start(text, match.start())
            before = text[start : match.start()]
            after = text[match.end() : _sentence_end(text, match.end())]
            task = _clean_task(re.sub(r"[—–-]\s*$", "", before.strip()) or after)
            if len(task.split()) < 2:
                continue
            results.append(
                _assignment(
                    row,
                    task=task,
                    owner=match.group("name"),
                    basis="assignment-language",
                    deadline=_deadline_in(before + after),
                    excerpt=_sentence_around(text, match.start(), match.end()),
                )
            )
    return results


# ---------------------------------------------------------------- helpers


def _name_pattern(person: Person) -> re.Pattern:
    """The person's name as a regex group named ``name``, never inside a word
    or an address ("daniel@gang.tech")."""
    return re.compile(r"(?<![\w@.])" + _name_core(person))


def _name_core(person: Person) -> str:
    """The name group without its left boundary, for ``@mentions``.

    A resolved name must not run on into another surname — "Frank Smith" is not
    Frank Godchaux — so a following capitalized word rejects the match. An
    unresolved given name may instead pick up the surname the evidence writes
    ("Daniel Hirunrusme will…"), since nothing canonical says otherwise.
    """
    forms = "|".join(re.escape(form) for form in person.forms)
    capitalized = r"\s+(?!" + _FIELD_LABEL + r")[A-Z][a-z][\w’'-]*"
    given_name_only = not person.resolved and len(person.forms) == 1 and " " not in person.forms[0]
    if given_name_only:
        return r"(?P<name>(?:" + forms + r")(?:" + capitalized + r")?)(?![\w@]|\.\w)"
    return r"(?P<name>(?:" + forms + r"))(?![\w@]|\.\w)(?!" + capitalized + r")"


def _owner_field_name(person: Person) -> str:
    """The person's name as it appears in an owner list, not in a sentence.

    A resolved given name still refuses a surname that ends the value
    ("Daniel Smith" is not Daniel Hirunrusme). It does not refuse the next
    task, which keeps going in further capitalized words ("Daniel Finalize
    Qi Certification"). Prose matching keeps its own rule, in ``_name_core``.
    """
    forms = "|".join(re.escape(form) for form in person.forms)
    ending_surname = ""
    if person.resolved:
        ending_surname = r"(?!" + _OWNER_SURNAME + r")"
    return (
        r"(?<![\w@.])(?P<name>(?:" + forms + r"))(?![\w@]|\.\w)" + ending_surname
    )


def _owner_list_pattern(person: Person) -> str:
    # A month after a name starts the next row's date ("Frank Sep 21:"); it
    # is not a surname. A capitalized word followed by another is the next
    # task, not a second given name.
    other = _OWNER_NAME
    return (
        r"(?:(?:" + other + r")[ \t]*(?:/|,|&|and)[ \t]*)*"
        + _owner_field_name(person)
        + r"(?:[ \t]*(?:/|,|&|and)[ \t]*(?:" + other + r"))*"
    )


def _split_owners(text: str) -> List[str]:
    parts = re.split(r"\s*(?:/|,|&|\band\b|;)\s*", text or "")
    return [part.strip() for part in parts if part and part.strip()]


def _owner_matches(owner: str, person: Person) -> bool:
    value = re.sub(r"\s+", " ", owner or "").strip().casefold()
    value = re.sub(r"\s*[<(].*$", "", value)
    if not value:
        return False
    for form in person.forms:
        folded = form.casefold()
        if value == folded:
            return True
        # An unresolved given name matches the same given name with a surname.
        if not person.resolved and " " not in folded and value.split(" ")[0] == folded and len(value.split(" ")) <= 3:
            return True
    return False


def _segment_before(text: str, position: int, *, floor: int = 0) -> str:
    window = text[max(0, floor, position - 300) : position]
    starts = list(_SEGMENT_START.finditer(window))
    return window[starts[-1].end() :] if starts else window


def _sentence_start(text: str, position: int) -> int:
    window_start = max(0, position - 300)
    starts = list(re.finditer(r"[.!?]\s+|\s-\s", text[window_start:position]))
    return window_start + starts[-1].end() if starts else window_start


def _sentence_end(text: str, position: int) -> int:
    match = re.search(r"[.!?](?:\s|$)", text[position : position + 400])
    return position + match.start() if match else min(len(text), position + 400)


def _sentence_around(text: str, start: int, end: int) -> str:
    return _short(text[_sentence_start(text, start) : _sentence_end(text, end) + 1])


_MONTH_DAY = re.compile(
    r"\b(?P<month>jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(?P<day>\d{1,2})(?:st|nd|rd|th)?\b",
    re.I,
)
_MONTHS = {name: index for index, name in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}


def deadline_date(deadline: str, stated: str = "") -> Optional[date]:
    """The calendar date a deadline names, or ``None`` when it names none.

    Reads an ISO date, or a month and day ("Sep. 18 — Noon", "Before Sep 18
    meeting"). A month and day takes its year from ``stated`` — the date of
    the evidence that set it. A deadline more than half a year *before* that
    date is read as next year's, so a December schedule's "Jan 10" is January
    after it. A deadline later in the same year stays there, including one
    more than half a year ahead: a January schedule's "Sep 18" is this
    September, not last year's. "Near term" and "Ongoing" are not dates, and
    stay ``None``.
    """
    text = str(deadline or "")
    iso = _ISO_DATE.search(text)
    if iso:
        try:
            return date.fromisoformat(iso.group(1))
        except ValueError:
            return None
    found = _MONTH_DAY.search(text)
    if not found:
        return None
    try:
        anchor = date.fromisoformat(str(stated or "")[:10])
    except ValueError:
        return None
    try:
        value = date(anchor.year, _MONTHS[found.group("month").casefold()], int(found.group("day")))
    except ValueError:
        return None
    if (anchor - value).days > 183:
        # Feb 29 cannot move into a non-leap year; keep the leap day itself.
        try:
            value = value.replace(year=value.year + 1)
        except ValueError:
            pass
    return value


def task_tokens(text: str) -> frozenset:
    """A task's content words, as deduplication compares them."""
    return _task_tokens(text)


def _deadline_in(text: str) -> str:
    match = _BY_DEADLINE.search(text or "")
    return match.group("value") if match else ""


def _clean_task(text: str) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    value = re.sub(r"^(?:[-•*–]|\d{1,2}[.)])\s+", "", value)
    value = value.strip(" -–—:;,")
    if len(value) > MAX_TASK_CHARS:
        cut = value[: MAX_TASK_CHARS - 1]
        value = cut[: cut.rfind(" ")] + "…" if " " in cut else cut + "…"
    return value[:1].upper() + value[1:] if value else ""


def _short(text: str, limit: int = 240) -> str:
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    return value if len(value) <= limit else value[: limit - 1].rstrip() + "…"


def _assignment(
    row: Dict[str, Any],
    *,
    task: str,
    owner: str,
    basis: str,
    co_owners: Sequence[str] = (),
    deadline: str = "",
    status_text: str = "",
    excerpt: str = "",
    stale: bool = False,
) -> Assignment:
    date = date_prefix(row.get("updated") or row.get("created") or "")
    return Assignment(
        task=task,
        owner=re.sub(r"\s+", " ", owner).strip(),
        basis=basis,
        co_owners=list(co_owners),
        deadline=deadline,
        status=normalize_status(status_text),
        status_text=status_text,
        document_ids=[str(row.get("document_id") or "")],
        titles=[str(row.get("title") or "")],
        date=date,
        status_date=date if status_text else "",
        stale=stale,
        excerpt=excerpt,
    )


# ----------------------------------------------------------- deduplication


def _task_tokens(task: str) -> frozenset:
    return frozenset(
        token for token in _TOKEN.findall(task.casefold()) if token not in _TASK_STOPWORDS
    )


def _same_task(left: frozenset, right: frozenset) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    smaller = min(len(left), len(right))
    # The second test stops a short phrase ("send the deck") from absorbing a
    # longer, different task that merely contains its words.
    return smaller >= 2 and len(left & right) / smaller >= DUPLICATE_OVERLAP and (
        len(left & right) / len(left | right) >= 0.4
    )


def _deduplicate(items: Sequence[Assignment]) -> List[Assignment]:
    """One entry per task, citing every document that states it.

    The newest dated statement of a status wins, so a schedule that later
    marks a task done supersedes the recap that first assigned it.
    """
    merged: List[Tuple[frozenset, Assignment]] = []
    for item in items:
        tokens = _task_tokens(item.task)
        target = next((entry for key, entry in merged if _same_task(key, tokens)), None)
        if target is None:
            merged.append((tokens, _copy(item)))
            continue
        for document_id, title in zip(item.document_ids, item.titles):
            if document_id not in target.document_ids:
                target.document_ids.append(document_id)
                target.titles.append(title)
        for owner in item.co_owners:
            if owner not in target.co_owners:
                target.co_owners.append(owner)
        if item.status_text and item.status_date >= target.status_date:
            target.status_text = item.status_text
            target.status = item.status
            target.status_date = item.status_date
        if item.deadline and (not target.deadline or item.date >= target.date):
            target.deadline = item.deadline
        if item.date > target.date:
            target.date = item.date
        # A structured field beats a sentence as the thing to show.
        if _BASIS_RANK.get(item.basis, 9) < _BASIS_RANK.get(target.basis, 9):
            target.task, target.basis, target.excerpt = item.task, item.basis, item.excerpt
        target.stale = target.stale and item.stale
    for _, entry in merged:
        del entry.document_ids[MAX_DOCUMENTS_PER_ASSIGNMENT:]
        del entry.titles[MAX_DOCUMENTS_PER_ASSIGNMENT:]
    return [entry for _, entry in merged]


_BASIS_RANK = {
    "action-item": 0,
    "owner-field": 1,
    "owner-table": 2,
    "addressed-task": 3,
    "assignment-language": 4,
}


def _copy(item: Assignment) -> Assignment:
    return Assignment(**{**item.__dict__, "co_owners": list(item.co_owners), "document_ids": list(item.document_ids), "titles": list(item.titles)})


def _within(item: Assignment, since: str, until: str) -> bool:
    """Date scoping reads the deadline when the source gives one as a date."""
    if not since and not until:
        return True
    match = _ISO_DATE.search(item.deadline or "")
    anchor = match.group(1) if match else item.date
    if not anchor:
        return False
    if since and anchor < since[:10]:
        return False
    if until and anchor > until[:10]:
        return False
    return True


def _order(item: Assignment):
    """Current work first; dated deadlines soonest first; then newest evidence."""
    match = _ISO_DATE.search(item.deadline or "")
    return (
        item.closed,
        0 if match else 1,
        match.group(1) if match else "",
        _negated(item.date),
    )


def _negated(date: str) -> str:
    """Sort key that orders ISO dates newest first, undated last."""
    if not date:
        return "\x7f"
    return "".join(chr(0x7F - ord(character)) for character in date)
