"""Deterministic extraction of explicit relationship statements.

Only statements the document makes outright produce a claim:

* "Daniel Hirunrusme is a co-founder of GANG."
* "GANG co-founders Daniel Hirunrusme and Frank Godchaux …"
* "Daniel Hirunrusme, co-founder of GANG, …"
* a signature block — name, ``Organization, Title``, and the person's own
  canonical address, in a message that address sent.

Everything else produces nothing. Being on a thread, in an attendee list, on
a shared email domain, or in fifty meetings is presence, and presence has no
path to a role here. There is no proximity window: the entity has to sit in
the grammatical slot the pattern names, with nothing but the pattern between
it and the role.

How it works: known entity names, aliases, and addresses in a sentence are
replaced by placeholder tokens, and a small set of patterns runs over the
tokenized sentence. A pattern that matches yields a :class:`ClaimProposal`
whose excerpt is the sentence itself; ``model.validate_proposal`` decides
whether it is stored.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from core.entities.model import EntityRecord, normalize_email, normalize_name

from .model import (
    ADVISOR_TO,
    COFOUNDER_OF,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    FOUNDER_OF,
    MANUFACTURER_FOR,
    METHOD_DETERMINISTIC,
    PARTNER_AT,
    PREDICATE_SHAPES,
    RESPONSIBLE_FOR,
    VENDOR_FOR,
    WORKS_FOR,
    ClaimProposal,
    display_text,
)


RULE_COPULAR = "copular-role"
RULE_APPOSITIVE = "appositive-role"
RULE_ORG_PREFIX = "organization-role-prefix"
RULE_FOUNDERS_OF = "founders-of-list"
RULE_SIGNATURE = "signature-block"
RULE_RESPONSIBLE = "responsible-for"

#: Header lines that record who was on a thread or in a room. A name inside
#: one is a name on a list. Mirrors ``entities.profiles.PARTICIPANT_LINE``.
_HEADER_LINE = re.compile(
    r"^\s*[-*]?\s*(?:Participants|Attendees|Present|From|To|Cc|CC|Bcc|Subject|Sent|Date|"
    r"Gmail\s+(?:message|thread)\s+ID|Message\s+count|First\s+message|Last\s+message)\s*:",
    re.IGNORECASE,
)

_QUOTED_LINE = re.compile(r"^\s*(?:>|&gt;)")
_ADDRESS = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
_BULLET = re.compile(r"^\s*(?:[-*•▪◦]|\d{1,2}[.)])\s+")
_SEPARATOR = re.compile(r"^\s*[-=_*]{5,}\s*$")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"“(A-Z0-9])")

#: Placeholder for an entity mention inside a tokenized sentence.
_TOKEN = "⟦{}⟧"


def _e(name: str) -> str:
    return rf"⟦(?P<{name}>\d+)⟧"

#: Qualifiers that turn a statement of role into something else: a denial, a
#: former role, a possibility, a plan.
_BLOCKING_QUALIFIER = re.compile(
    r"\b(?:not|never|no\s+longer|former(?:ly)?|ex|previous(?:ly)?|potential|prospective|"
    r"possible|proposed|future|would|could|might|may|should|wants?\s+to|hopes?\s+to|"
    r"plans?\s+to|to\s+be|if|interim|acting|candidate)\b",
    re.IGNORECASE,
)

_COPULA = (
    r"(?:is|was|are|were|remains|remain|serves\s+as|served\s+as|serve\s+as|acts\s+as|"
    r"acted\s+as|has\s+been|have\s+been|became|becomes)"
)

_DETERMINER = r"(?:(?:a|an|the|one\s+of\s+the|our|its|their|his|her)\s+)?"

#: Up to two words of modifier before a role noun ("technical co-founder",
#: "managing partner"). Checked against ``_BLOCKING_QUALIFIER`` afterwards.
_MODIFIER = r"(?P<mod>(?:[A-Za-z][\w-]*\s+){0,2}?)"

#: Role nouns, most specific first. Each maps to a predicate family.
_ROLE_TERMS: Tuple[Tuple[str, str], ...] = (
    ("cofounder", r"co-?\s?founders?"),
    ("founder", r"founders?"),
    (
        "officer",
        r"(?:chief\s+[a-z]+(?:\s+[a-z]+)?\s+officer|ceo|cto|coo|cfo|cmo|cpo|president|"
        r"vice\s+president|vp(?:\s+of\s+[a-z]+)?|head\s+of\s+[a-z]+(?:\s+[a-z]+)?|"
        r"general\s+manager|managing\s+director|chair(?:man|woman|person)?|"
        r"employees?|engineers?|designers?|product\s+managers?)",
    ),
    ("partner", r"(?:managing\s+|senior\s+|founding\s+|equity\s+)?partners?"),
    ("advisor", r"advis[eo]rs?"),
    ("counsel", r"(?:outside\s+|legal\s+|general\s+|corporate\s+)?counsel|attorneys?|lawyers?|accountants?|cpas?"),
    ("vendor", r"vendors?|suppliers?"),
    ("manufacturer", r"(?:contract\s+)?manufacturers?|factory|fabricators?"),
)

_ROLE = "(?P<role>" + "|".join(pattern for _, pattern in _ROLE_TERMS) + ")"
_PREP = r"(?P<prep>of|at|for|to|with)"


@dataclass(frozen=True)
class Mention:
    start: int
    end: int
    entity_id: str
    entity_type: str
    kind: str  # "name", "alias", or "email"
    text: str


class EntityIndex:
    """Surface forms of active canonical entities, for matching in text.

    Only unambiguous keys are used: a name or alias shared by two entities is
    dropped rather than resolved to whichever sorted first. Names are matched
    as written (or fully upper-cased), so "Frank" the alias does not match
    "frank" the adjective and ``GANG`` does not match "gang".
    """

    def __init__(self, records: Sequence[EntityRecord]):
        self.records: Dict[str, EntityRecord] = {
            record.id: record for record in records if record.status == "active"
        }
        owners: Dict[Tuple[str, str], set] = {}
        for record in self.records.values():
            for kind, value in self._forms(record):
                owners.setdefault(_key(kind, value), set()).add(record.id)

        entries: List[Tuple[str, str, str]] = []
        for record in self.records.values():
            for kind, value in self._forms(record):
                if len(owners.get(_key(kind, value), ())) != 1:
                    continue
                if kind != "email" and len(value) < 3:
                    continue
                entries.append((value, record.id, kind))
        # Longest first, so "Daniel Hirunrusme" beats "Daniel".
        entries.sort(key=lambda item: (-len(item[0]), item[0]))
        self._entries = entries
        self._patterns = [
            (re.compile(_form_pattern(value, kind)), entity_id, kind)
            for value, entity_id, kind in entries
        ]

    @staticmethod
    def _forms(record: EntityRecord) -> List[Tuple[str, str]]:
        forms: List[Tuple[str, str]] = [("name", record.name)]
        forms.extend(("alias", alias) for alias in record.aliases)
        forms.extend(("email", email) for email in record.emails)
        seen: set = set()
        unique: List[Tuple[str, str]] = []
        for kind, value in forms:
            value = str(value or "").strip()
            key = _key(kind, value)
            if not value or key in seen:
                continue
            seen.add(key)
            unique.append((kind, value))
        return unique

    def surface_forms(self) -> Dict[str, List[str]]:
        forms: Dict[str, List[str]] = {}
        for value, entity_id, _ in self._entries:
            forms.setdefault(entity_id, []).append(value)
        return forms

    def find(self, text: str) -> List[Mention]:
        taken: List[Tuple[int, int]] = []
        found: List[Mention] = []
        for pattern, entity_id, kind in self._patterns:
            for match in pattern.finditer(text):
                start, end = match.span()
                if any(start < other_end and end > other_start for other_start, other_end in taken):
                    continue
                taken.append((start, end))
                found.append(
                    Mention(
                        start=start,
                        end=end,
                        entity_id=entity_id,
                        entity_type=self.records[entity_id].type,
                        kind=kind,
                        text=match.group(0),
                    )
                )
        return sorted(found, key=lambda item: item.start)

    def email_owner(self, address: str) -> Optional[str]:
        normalized = normalize_email(address)
        for record in self.records.values():
            if normalized and normalized in record.emails:
                return record.id
        return None


def _key(kind: str, value: str) -> str:
    # Names and aliases share one namespace: an alias that is someone else's
    # name is exactly as ambiguous as two identical aliases.
    return "email:" + normalize_email(value) if kind == "email" else "label:" + normalize_name(value)


def _form_pattern(value: str, kind: str) -> str:
    if kind == "email":
        return rf"(?i)(?<![\w.+-]){re.escape(value)}(?![\w-])"
    variants = {re.escape(value), re.escape(value.upper())}
    alternation = "|".join(sorted(variants, key=len, reverse=True))
    # A hyphen on either side makes a different name: "GANG-Tech" is not GANG.
    return rf"(?<![\w'’-])(?:{alternation})(?![\w-])"


# ------------------------------------------------------------ document text


@dataclass(frozen=True)
class Paragraph:
    lines: Tuple[str, ...]

    @property
    def text(self) -> str:
        return re.sub(r"\s+", " ", " ".join(self.lines)).strip()


def paragraphs(body: str) -> List[Paragraph]:
    """Blank-line paragraphs, with quoted-reply and header lines removed and
    each bullet item its own paragraph."""
    result: List[Paragraph] = []
    current: List[str] = []

    def flush() -> None:
        if current:
            result.append(Paragraph(tuple(current)))
            current.clear()

    for raw in (body or "").splitlines():
        line = raw.rstrip()
        if (
            not line.strip()
            or _QUOTED_LINE.match(line)
            or _HEADER_LINE.match(line)
            or _SEPARATOR.match(line)
        ):
            flush()
            continue
        if _BULLET.match(line):
            flush()
        current.append(line.strip())
    flush()
    return result


def sentences(text: str) -> List[str]:
    return [part.strip() for part in _SENTENCE_SPLIT.split(text or "") if part.strip()]


# --------------------------------------------------------------- extraction


def extract_relations(
    *,
    document_id: str,
    body: str,
    index: EntityIndex,
    sender_addresses: Sequence[str] = (),
) -> List[ClaimProposal]:
    """Every explicit relationship statement in one document, as proposals."""
    proposals: List[ClaimProposal] = []
    seen: set = set()

    def add(proposal: Optional[ClaimProposal]) -> None:
        if proposal is None:
            return
        key = (
            proposal.subject_entity_id,
            proposal.predicate,
            proposal.object_entity_id,
            proposal.object_value.casefold(),
            proposal.role.casefold(),
            display_text(proposal.excerpt),
        )
        if key in seen:
            return
        seen.add(key)
        proposals.append(proposal)

    for proposal in _signature_claims(document_id, body, index, sender_addresses):
        add(proposal)

    for paragraph in paragraphs(body):
        for sentence in sentences(paragraph.text):
            if len(sentence) > 600 or "?" in sentence:
                continue
            for proposal in _sentence_claims(document_id, sentence, index):
                add(proposal)
    return proposals


def _sentence_claims(document_id: str, sentence: str, index: EntityIndex) -> Iterable[ClaimProposal]:
    mentions = index.find(sentence)
    if len(mentions) < 1:
        return []
    tokenized, by_token = _tokenize(sentence, mentions)
    excerpt = display_text(sentence)
    claims: List[ClaimProposal] = []

    def emit(subject: Mention, target: Mention, role_text: str, prep: str, rule: str, modifier: str = "") -> None:
        if modifier and _BLOCKING_QUALIFIER.search(modifier):
            return
        predicate, role = _predicate_for(role_text, prep)
        if predicate is None:
            return
        proposal = _proposal(document_id, subject, predicate, excerpt, rule, target=target, role=role)
        if proposal is not None:
            claims.append(proposal)

    # "X is a co-founder of Y" / "X and Z are co-founders of Y"
    copular = re.compile(
        rf"{_e('s1')}(?:\s*,?\s*(?:and|&)\s*{_e('s2')})?\s+(?P<between>(?:(?:also|still|currently|now|officially)\s+)?){_COPULA}\s+"
        rf"{_DETERMINER}{_MODIFIER}{_ROLE}\s+{_PREP}\s+(?:the\s+)?{_e('o')}",
        re.IGNORECASE,
    )
    for match in copular.finditer(tokenized):
        if _BLOCKING_QUALIFIER.search(match.group("between") or ""):
            continue
        for group in ("s1", "s2"):
            if match.group(group) is None:
                continue
            emit(by_token[int(match.group(group))], by_token[int(match.group("o"))],
                 match.group("role"), match.group("prep"), RULE_COPULAR, match.group("mod") or "")

    # "X, co-founder of Y," — the appositive must close.
    appositive = re.compile(
        rf"{_e('s1')}\s*,\s+{_DETERMINER}{_MODIFIER}{_ROLE}\s+{_PREP}\s+(?:the\s+)?{_e('o')}\s*(?:[,.;:)]|$)",
        re.IGNORECASE,
    )
    for match in appositive.finditer(tokenized):
        emit(by_token[int(match.group("s1"))], by_token[int(match.group("o"))],
             match.group("role"), match.group("prep"), RULE_APPOSITIVE, match.group("mod") or "")

    # "Y co-founders X and Z" / "Y's founders, X and Z" / "Y CEO X"
    prefix = re.compile(
        rf"{_e('o')}(?:['’]s)?\s+(?P<role>co-?\s?founders?|founders?|ceo|cto|coo|cfo|cmo|president)"
        rf"\s*,?\s+{_e('s1')}(?:\s*,?\s*(?:and|&)\s+{_e('s2')})?",
        re.IGNORECASE,
    )
    for match in prefix.finditer(tokenized):
        for group in ("s1", "s2"):
            if match.group(group) is None:
                continue
            emit(by_token[int(match.group(group))], by_token[int(match.group("o"))],
                 match.group("role"), "of", RULE_ORG_PREFIX)

    # "the co-founders of Y, X and Z"
    founders_of = re.compile(
        rf"\b(?P<role>co-?\s?founders?|founders?)\s+of\s+{_e('o')}\s*,?\s+{_e('s1')}"
        rf"(?:\s*,?\s*(?:and|&)\s+{_e('s2')})?",
        re.IGNORECASE,
    )
    for match in founders_of.finditer(tokenized):
        for group in ("s1", "s2"):
            if match.group(group) is None:
                continue
            emit(by_token[int(match.group(group))], by_token[int(match.group("o"))],
                 match.group("role"), "of", RULE_FOUNDERS_OF)

    # "X is responsible for <stated thing>." Present tense only; a plan to be
    # responsible is not a responsibility, and task lists are the assignment
    # layer's job, not this one's.
    responsible = re.compile(
        rf"{_e('s1')}\s+(?:is|remains)\s+(?:solely\s+|primarily\s+|directly\s+)?responsible\s+for\s+"
        rf"(?P<value>[^.;:!?⟦⟧]{{3,120}}?)\s*(?:[.;:!]|$)",
        re.IGNORECASE,
    )
    for match in responsible.finditer(tokenized):
        subject = by_token[int(match.group("s1"))]
        value = match.group("value").strip().rstrip(",")
        if not value or _BLOCKING_QUALIFIER.search(value):
            continue
        proposal = _proposal(document_id, subject, RESPONSIBLE_FOR, excerpt, RULE_RESPONSIBLE, value=value)
        if proposal is not None:
            claims.append(proposal)
    return claims


def _signature_claims(
    document_id: str, body: str, index: EntityIndex, sender_addresses: Sequence[str]
) -> List[ClaimProposal]:
    """A signature block: the person's name, ``Organization, Title``, and their
    own canonical address, in a message that address sent.

    All three lines are required. The name alone is someone being addressed;
    the address alone is a mailbox; the organization line alone could be
    anyone's. Together, in mail from that address, they are the person saying
    who they are.
    """
    senders = {
        normalize_email(address)
        for value in sender_addresses
        for address in _ADDRESS.findall(str(value or ""))
    }
    lines = [line.strip() for line in (body or "").splitlines()]
    raw_lines = (body or "").splitlines()
    claims: List[ClaimProposal] = []
    for position, line in enumerate(lines[:-2]):
        if not line or _QUOTED_LINE.match(raw_lines[position]):
            continue
        name_mentions = index.find(line)
        if len(name_mentions) != 1:
            continue
        person = name_mentions[0]
        if person.kind != "name" or person.entity_type != "person":
            continue
        if line.rstrip(",").strip() != person.text:
            continue
        record = index.records[person.entity_id]
        title_line = lines[position + 1]
        window = lines[position + 2 : position + 4]
        address = next(
            (
                email
                for email in record.emails
                if any(normalize_email(candidate) == email for text in window for candidate in _ADDRESS.findall(text))
            ),
            None,
        )
        if address is None:
            continue
        if senders and address not in senders:
            # The block names someone who did not send this message: a
            # quoted signature, a forward, a template. Not a self-statement.
            continue
        parsed = _parse_title_line(title_line, index)
        if parsed is None:
            continue
        organization, role_text = parsed
        predicate, role = _predicate_for(role_text, "of")
        if predicate is None:
            continue
        address_line = next(text for text in window if address in text.casefold())
        excerpt = display_text(" ".join([line, title_line, address_line]))
        proposal = _proposal(
            document_id, person, predicate, excerpt, RULE_SIGNATURE, target=organization, role=role
        )
        if proposal is not None:
            claims.append(proposal)
    return claims


def _parse_title_line(line: str, index: EntityIndex) -> Optional[Tuple[Mention, str]]:
    """``GANG, Co-Founder`` / ``Co-Founder, GANG`` / ``Co-Founder | GANG`` /
    ``Co-Founder at GANG``. Exactly one organization and one role, nothing else."""
    if not line or len(line) > 80:
        return None
    mentions = [item for item in index.find(line) if item.entity_type == "company"]
    if len(mentions) != 1:
        return None
    organization = mentions[0]
    before = line[: organization.start].strip()
    after = line[organization.end :].strip()
    role_pattern = re.compile(rf"^{_ROLE}$", re.IGNORECASE)
    if not before and after:
        match = re.match(r"^[,|–—-]\s*(?P<rest>.+)$", after)
        role_text = match.group("rest").strip() if match else ""
    elif before and not after:
        match = re.match(r"^(?P<rest>.+?)\s*(?:[,|–—-]|\bat\b)$", before, re.IGNORECASE)
        role_text = match.group("rest").strip() if match else ""
    else:
        return None
    if not role_text or not role_pattern.match(role_text):
        return None
    return organization, role_text


def _predicate_for(role_text: str, prep: str) -> Tuple[Optional[str], str]:
    """Map a stated role noun and its preposition to a predicate and a
    verbatim role qualifier (kept only where the predicate needs one)."""
    role_text = re.sub(r"\s+", " ", role_text or "").strip()
    prep = (prep or "").casefold()
    family = _role_family(role_text)
    if family == "cofounder":
        return (COFOUNDER_OF, "") if prep in ("of", "at") else (None, "")
    if family == "founder":
        return (FOUNDER_OF, "") if prep in ("of", "at") else (None, "")
    if family == "officer":
        return (WORKS_FOR, role_text) if prep in ("of", "at", "for", "with") else (None, "")
    if family == "partner":
        return (PARTNER_AT, "") if prep in ("at", "with", "of") else (None, "")
    if family == "advisor":
        return (ADVISOR_TO, "") if prep in ("to", "for", "of") else (None, "")
    if family == "counsel":
        if prep in ("to", "for"):
            return ADVISOR_TO, ""
        if prep in ("at", "with"):
            return WORKS_FOR, role_text
        return None, ""
    if family == "vendor":
        return (VENDOR_FOR, "") if prep in ("to", "for", "of") else (None, "")
    if family == "manufacturer":
        return (MANUFACTURER_FOR, "") if prep in ("for", "to", "of") else (None, "")
    return None, ""


def _role_family(role_text: str) -> Optional[str]:
    for family, pattern in _ROLE_TERMS:
        if re.fullmatch(pattern, role_text, re.IGNORECASE):
            return family
    return None


def _tokenize(sentence: str, mentions: Sequence[Mention]) -> Tuple[str, Dict[int, Mention]]:
    parts: List[str] = []
    by_token: Dict[int, Mention] = {}
    cursor = 0
    for number, mention in enumerate(mentions):
        parts.append(sentence[cursor : mention.start])
        parts.append(_TOKEN.format(number))
        by_token[number] = mention
        cursor = mention.end
    parts.append(sentence[cursor:])
    return "".join(parts), by_token


def _proposal(
    document_id: str,
    subject: Mention,
    predicate: str,
    excerpt: str,
    rule: str,
    *,
    target: Optional[Mention] = None,
    role: str = "",
    value: str = "",
) -> Optional[ClaimProposal]:
    subject_types, object_types = PREDICATE_SHAPES[predicate]
    if subject.entity_type not in subject_types:
        return None
    if target is not None and (target.entity_type not in object_types or target.entity_id == subject.entity_id):
        return None
    return ClaimProposal(
        document_id=document_id,
        subject_entity_id=subject.entity_id,
        predicate=predicate,
        excerpt=excerpt,
        method=METHOD_DETERMINISTIC,
        rule=rule,
        object_entity_id=target.entity_id if target is not None else "",
        object_value=value,
        role=role,
        confidence=_confidence(subject, target),
    )


def _confidence(subject: Mention, target: Optional[Mention]) -> str:
    """A person named by a short alias ("Dan", "Frank") could be someone else
    of the same first name; that claim is kept, but below what Ask states."""
    if subject.entity_type == "person" and subject.kind == "alias":
        return CONFIDENCE_MEDIUM
    if target is not None and target.entity_type == "person" and target.kind == "alias":
        return CONFIDENCE_MEDIUM
    return CONFIDENCE_HIGH
