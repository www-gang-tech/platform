"""Who is involved with what — assembled from signals, never from a roster.

"Who is on the team?" has no answer in most corpora, because nobody writes a
roster and then keeps it current. What a corpus does hold is the residue of
people actually working: the same names in the same weekly meetings, an email
domain, a line saying who owns a deliverable, a relationship someone recorded
once. Read together those support a real answer.

Read together — and no further. This module gathers signals and sorts people
into coarse bands. It does not conclude that anyone is employed, and it has no
vocabulary for job titles, because a pattern of attendance is evidence of
participation and of nothing else. The bands are:

``likely-core-internal``
    Uses the company's own email domain, or turns up repeatedly across the
    operating record while owning deliverables.
``external-advisory``
    Identifies with a different organization that the corpus also knows.
``collaborator-vendor``
    Connected through supply or vendor language, or a ``supplied_by`` edge.
``unclear``
    Present in the record, but the signals do not separate.

Everything here is deterministic and every band carries the signals and
documents that produced it, because the statement built on top — "X appears to
be part of the core team" — is an *inference*, and an inference has to show
the facts it rests on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

from .temporal import date_prefix


# ------------------------------------------------------------------- bands

CORE_INTERNAL = "likely-core-internal"
EXTERNAL_ADVISORY = "external-advisory"
COLLABORATOR_VENDOR = "collaborator-vendor"
UNCLEAR = "unclear"

BANDS = (CORE_INTERNAL, EXTERNAL_ADVISORY, COLLABORATOR_VENDOR, UNCLEAR)

BAND_DESCRIPTIONS = {
    CORE_INTERNAL: "appears to work inside the company",
    EXTERNAL_ADVISORY: "appears to be external, advising or partnering",
    COLLABORATOR_VENDOR: "appears to be a collaborator or supplier",
    UNCLEAR: "present in the record, but the signals do not separate",
}

#: Recurrence thresholds for treating participation as a pattern rather than
#: a coincidence. Deliberately modest: three appearances across two distinct
#: months is a working relationship, not a cc.
MIN_RECURRING_DOCUMENTS = 3
MIN_RECURRING_MONTHS = 2

MAX_PARTICIPANTS = 25
MAX_EVIDENCE_PER_PERSON = 4
MAX_EXCERPT = 240

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

#: Lines an ingested thread or meeting note uses to record who was there.
#: Parsing them is reading structured metadata, not inferring attendance.
_PARTICIPANT_LINE = re.compile(
    r"(?:^|\s)(?:Participants|Attendees|Present|From|To|Cc|CC)\s*:\s*(?P<value>[^\n]{1,400})",
    re.IGNORECASE,
)

#: Whether a chunk from a participant line is plausibly a name.
#:
#: The index collapses whitespace, so a header and the paragraph after it can
#: end up on one line and a "name" can run off into prose. Four tokens is the
#: cutoff: past that, with no address to anchor it, the chunk is dropped
#: rather than guessed at. Losing an unrecorded participant is a small cost;
#: inventing a person named after a sentence is not.
MAX_NAME_TOKENS = 3
MAX_NAME_CHARS = 60

#: Language that assigns work to someone. Its presence near a name is a
#: signal; it is never a title.
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

_OWNERSHIP = re.compile(
    r"\b(?:owns?|owner|owned\s+by|responsible\s+for|accountable\s+for|"
    r"assigned\s+to|signs?\s+off|sign-?off|deliverable|action\s+item|"
    r"to\s+deliver|will\s+deliver|leads?\b|leading\b|driving\b)\b",
    re.IGNORECASE,
)

_VENDOR = re.compile(
    r"\b(?:vendor|supplier|supplied\s+by|quote|quotation|invoice|purchase\s+order|"
    r"factory|manufacturer|fabricator|contract\s+manufactur\w*)\b",
    re.IGNORECASE,
)

_ADVISORY = re.compile(
    r"\b(?:advis\w+|counsel|consultant|of\s+counsel|outside\s+firm|"
    r"managing\s+partner|law\s+firm|attorney|by\s*laws?|term\s+sheet)\b",
    re.IGNORECASE,
)

#: Not people. Participant lines pick up distribution addresses and the
#: occasional header fragment.
_NOT_A_PERSON = re.compile(
    r"^(?:undisclosed|recipients?|no-?reply|noreply|do-?not-?reply|team|all|everyone|"
    r"info|hello|support|admin|contact|sales|billing|"
    # Header labels the collapsed text drags in when one line runs into another.
    r"to|cc|bcc|from|sent|subject|date|participants|attendees|present)\b",
    re.IGNORECASE,
)

#: HTML entity residue. Ingested mail is full of `&lt;` and `&amp;`, and a
#: fragment of one is not part of anybody's name.
_ENTITY_RESIDUE = re.compile(r"&[a-z]{1,8};?|&#\d{1,5};?", re.IGNORECASE)

#: Addresses that belong to a system rather than a person. Automated mail is
#: a large share of any real inbox, and a notification sender is not a
#: participant however often it appears.
_AUTOMATED_LOCAL = re.compile(
    # Anchored at a boundary rather than the start: `workspace-noreply@` is
    # every bit as automated as `noreply@`.
    r"(?:^|[.\-_+])(?:no-?reply|do-?not-?reply|donotreply|notifications?|updates?|mailer|"
    r"bounce[sd]?|postmaster|daemon|forward|alerts?|digest|newsletter|"
    r"support|help|billing|invoices?|receipts?)\b",
    re.IGNORECASE,
)
_AUTOMATED_DOMAIN = re.compile(
    r"(?:^|\.)(?:updates|notifications?|mail|email|smtp|bounces?)\.", re.IGNORECASE
)


def _is_automated(email: str) -> bool:
    text = _fold(email)
    if not text or "@" not in text:
        return False
    local, _, domain = text.partition("@")
    return bool(_AUTOMATED_LOCAL.search(local) or _AUTOMATED_DOMAIN.search(domain))


@dataclass
class Participant:
    """One person and everything the corpus shows about their involvement."""

    key: str
    name: str
    entity_id: str = ""
    emails: List[str] = field(default_factory=list)
    domains: List[str] = field(default_factory=list)
    document_ids: List[str] = field(default_factory=list)
    meeting_documents: int = 0
    months: Set[str] = field(default_factory=set)
    first_seen: str = ""
    last_seen: str = ""
    ownership_hits: int = 0
    vendor_hits: int = 0
    advisory_hits: int = 0
    #: The document itself is a supplier or advisory thread, by its title.
    #: Kept apart from sentence hits: it says what the thread is about, which
    #: is stronger than a word appearing near a name.
    vendor_context: bool = False
    advisory_context: bool = False
    relationships: List[str] = field(default_factory=list)
    affiliated_org: str = ""
    evidence: List[Dict[str, str]] = field(default_factory=list)
    band: str = UNCLEAR
    reasons: List[str] = field(default_factory=list)

    @property
    def recurring(self) -> bool:
        return (
            len(self.document_ids) >= MIN_RECURRING_DOCUMENTS
            and len(self.months) >= MIN_RECURRING_MONTHS
        )

    @property
    def canonical(self) -> bool:
        """Whether a canonical entity record exists for this person."""
        return bool(self.entity_id)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "entity_id": self.entity_id,
            "has_canonical_record": self.canonical,
            "band": self.band,
            "band_description": BAND_DESCRIPTIONS.get(self.band, ""),
            "reasons": list(self.reasons),
            "signals": {
                "documents": len(self.document_ids),
                "meeting_documents": self.meeting_documents,
                "distinct_months": len(self.months),
                "ownership_language": self.ownership_hits,
                "vendor_language": self.vendor_hits,
                "advisory_language": self.advisory_hits,
                "vendor_document": self.vendor_context,
                "advisory_document": self.advisory_context,
                "recurring": self.recurring,
                "email_domains": sorted(self.domains),
                "relationships": list(self.relationships),
                "affiliated_org": self.affiliated_org,
            },
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "document_ids": list(self.document_ids),
            "evidence": list(self.evidence[:MAX_EVIDENCE_PER_PERSON]),
        }


def gather(
    rows: Sequence[Dict[str, Any]],
    *,
    people: Sequence[Any] = (),
    companies: Sequence[Any] = (),
    home_domains: Sequence[str] = (),
    limit: int = MAX_PARTICIPANTS,
) -> List[Participant]:
    """Assemble participants from a set of retrieved documents.

    ``people`` and ``companies`` are canonical entity records, used as the
    vocabulary for recognizing names and for telling one organization from
    another. People named in the documents who have no canonical record are
    still reported — they are in the corpus, and omitting them would answer
    "who is involved?" with "whoever has been filed".
    """
    known_people = {record.id: record for record in people}
    by_email, by_name = _person_lookup(people)
    org_domains = _org_domains(companies)
    home = {_domain(value) for value in home_domains if _domain(value)}

    found: Dict[str, Participant] = {}
    for row in rows:
        _absorb_document(row, found, by_email, by_name, known_people)

    _merge_duplicates(found)
    for participant in found.values():
        _classify(participant, home_domains=home, org_domains=org_domains)

    ordered = sorted(
        found.values(),
        key=lambda item: (
            BANDS.index(item.band),
            -len(item.document_ids),
            -len(item.months),
            item.name.casefold(),
        ),
    )
    return ordered[:limit]


# ------------------------------------------------------------------ signals


def _absorb_document(
    row: Dict[str, Any],
    found: Dict[str, Participant],
    by_email: Dict[str, Any],
    by_name: Dict[str, Any],
    known_people: Dict[str, Any],
) -> None:
    document_id = str(row.get("document_id") or "")
    body = str(row.get("body") or "")
    title = str(row.get("title") or "")
    date = date_prefix(row.get("updated") or row.get("created"))
    document_type = str(row.get("type") or "").lower()
    source_type = str(row.get("source_type") or "").lower()
    is_meeting = document_type in ("meeting", "agenda", "schedule") or source_type == "meeting"

    collapsed = re.sub(r"\s+", " ", body)
    #: Every person the corpus knows by name, so attribution can tell whether
    #: someone else stands between a name and a verb.
    other_names = [
        form
        for record in known_people.values()
        for form in [record.name, *(getattr(record, "aliases", []) or [])]
        if form
    ]

    # 1. Canonical mentions the entity layer already recorded.
    for ref in row.get("entity_refs") or []:
        if not isinstance(ref, dict):
            continue
        entity_id = str(ref.get("entity_id") or "")
        record = known_people.get(entity_id)
        if record is None:
            continue
        participant = _ensure(found, key=entity_id, name=record.name, record=record)
        _note(participant, document_id, date, is_meeting)

    # 2. People named in participant/attendee/From/To lines.
    for match in _PARTICIPANT_LINE.finditer(body):
        for name, email in _split_participants(match.group("value")):
            record = by_email.get(email) or by_name.get(_fold(name))
            if record is None and _is_automated(email):
                continue
            if record is None and not email and not _looks_like_a_name(name):
                continue
            key = record.id if record is not None else (email or _fold(name))
            if not key or _NOT_A_PERSON.match(name or email or ""):
                continue
            participant = _ensure(
                found,
                key=key,
                name=(record.name if record is not None else name or email),
                record=record,
            )
            if email:
                _add(participant.emails, email)
                domain = _domain(email)
                if domain:
                    _add(participant.domains, domain)
            _note(participant, document_id, date, is_meeting)

    # 3. Surface forms of known people appearing anywhere in the text.
    for record in known_people.values():
        forms = [record.name, *getattr(record, "aliases", [])]
        hit = _first_form(collapsed, forms)
        if not hit:
            continue
        participant = _ensure(found, key=record.id, name=record.name, record=record)
        _note(participant, document_id, date, is_meeting)
        for sentence in _sentences_naming(collapsed, hit):
            # Same sentence, and the name has to come before the verb. A
            # proximity window would credit Pat with "Dana owns the
            # certification deliverable" for standing next to it in the
            # minutes, which is the attribution error this avoids.
            if _attributes_ownership(sentence, hit, other_names):
                participant.ownership_hits += 1
                _evidence(participant, document_id, title, sentence)
            if _VENDOR.search(sentence):
                participant.vendor_hits += 1
            if _ADVISORY.search(sentence):
                participant.advisory_hits += 1
        if _ADVISORY.search(title):
            participant.advisory_hits += 1

    # 3b. Document-level context, for people the corpus has no record of.
    #
    # Someone appearing once in a supplier thread has no sentences of their
    # own to read. The document they turn up in is the only signal there is,
    # and it is a real one — but it is applied only where nothing stronger
    # exists, so it can never override an email domain.
    # Keyed on the title only. A board-meeting thread that mentions a factory
    # in passing is not a supplier thread, and treating it as one puts every
    # attendee in the vendor band.
    document_is_vendor = bool(_VENDOR.search(title))
    document_is_advisory = bool(_ADVISORY.search(title))
    if document_is_vendor or document_is_advisory:
        for participant in found.values():
            if participant.canonical or document_id not in participant.document_ids:
                continue
            if document_is_vendor:
                participant.vendor_context = True
            if document_is_advisory:
                participant.advisory_context = True

    # 4. Relationship assertions touching a person.
    for assertion in row.get("relationships") or []:
        if not isinstance(assertion, dict):
            continue
        for side in ("subject_entity_id", "object_entity_id"):
            record = known_people.get(str(assertion.get(side) or ""))
            if record is None:
                continue
            participant = _ensure(found, key=record.id, name=record.name, record=record)
            predicate = str(assertion.get("predicate") or "")
            if predicate:
                _add(participant.relationships, predicate)
            _note(participant, document_id, date, is_meeting)
            excerpt = str(assertion.get("excerpt") or "")
            if excerpt:
                _evidence(participant, document_id, title, excerpt)


def _ensure(
    found: Dict[str, Participant], *, key: str, name: str, record: Any = None
) -> Participant:
    participant = found.get(key)
    if participant is None:
        participant = Participant(key=key, name=name or key)
        found[key] = participant
    if record is not None and not participant.entity_id:
        participant.entity_id = record.id
        participant.name = record.name
        for email in getattr(record, "emails", []) or []:
            _add(participant.emails, email)
            domain = _domain(email)
            if domain:
                _add(participant.domains, domain)
        for domain in getattr(record, "domains", []) or []:
            _add(participant.domains, _domain(domain))
    return participant


def _note(participant: Participant, document_id: str, date: str, is_meeting: bool) -> None:
    if document_id and document_id not in participant.document_ids:
        participant.document_ids.append(document_id)
        if is_meeting:
            participant.meeting_documents += 1
    if date:
        participant.months.add(date[:7])
        if not participant.first_seen or date < participant.first_seen:
            participant.first_seen = date
        if not participant.last_seen or date > participant.last_seen:
            participant.last_seen = date


def _evidence(participant: Participant, document_id: str, title: str, text: str) -> None:
    if len(participant.evidence) >= MAX_EVIDENCE_PER_PERSON:
        return
    entry = {
        "document_id": document_id,
        "title": title,
        "excerpt": text.strip()[:MAX_EXCERPT],
    }
    if entry not in participant.evidence:
        participant.evidence.append(entry)


def _merge_duplicates(found: Dict[str, Participant]) -> None:
    """Fold entries that are obviously the same person into one.

    The same person arrives three ways from one collapsed header: as a name,
    as a bare address, and as a name with the address stripped off. Reporting
    them as three participants is worse than useless — it inflates every
    count the banding depends on.

    Merging is conservative. Two entries join only on an exact name match, or
    when an address's local part reconstructs a name that no one else shares.
    """
    by_name: Dict[str, str] = {}
    for key, participant in list(found.items()):
        if participant.entity_id:
            by_name.setdefault(_fold(participant.name), key)
    for key, participant in list(found.items()):
        if not participant.entity_id:
            by_name.setdefault(_fold(participant.name), key)

    #: "daniel.hirunrusme@…" and "dhirunrusme@…" both reduce to letters only,
    #: which is what a name reduces to as well.
    def squash(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", _fold(value))

    name_squash: Dict[str, List[str]] = {}
    _SQUASH_TOKENS.clear()
    for key, participant in found.items():
        if participant.name and not _EMAIL.fullmatch(participant.name):
            squashed = squash(participant.name)
            name_squash.setdefault(squashed, []).append(key)
            _SQUASH_TOKENS[squashed] = participant.name.split()

    for key, participant in list(found.items()):
        if key not in found:
            continue
        local = participant.emails[0].split("@")[0] if participant.emails else ""
        candidates: List[str] = []
        if _EMAIL.fullmatch(participant.name or "") or not participant.name:
            candidates = _name_matches(local, name_squash, squash)
        else:
            duplicates = name_squash.get(squash(participant.name), [])
            candidates = [other for other in duplicates if other != key]
        target = next((other for other in candidates if other != key and other in found), "")
        if target:
            _absorb_into(found[target], participant)
            del found[key]


def _name_matches(local: str, name_squash: Dict[str, List[str]], squash) -> List[str]:
    """Which names an address's local part plausibly belongs to.

    Addresses are built from names in a handful of predictable ways —
    ``daniel@``, ``danielhirunrusme@``, ``dhirunrusme@``. Each form is tried,
    and a form is only accepted when exactly one name answers to it, so a
    shared first name never silently merges two people.
    """
    target = squash(local)
    if not target:
        return []
    if target in name_squash and len(name_squash[target]) == 1:
        return name_squash[target]

    matches: List[str] = []
    for squashed, keys in name_squash.items():
        if len(keys) != 1 or not squashed:
            continue
        tokens = [squash(token) for token in _unsquash(squashed, name_squash)]
        if not tokens:
            continue
        forms = {
            tokens[0],
            "".join(tokens),
            (tokens[0][:1] + tokens[-1]) if len(tokens) > 1 else "",
            (tokens[0] + tokens[-1][:1]) if len(tokens) > 1 else "",
        }
        if target in {form for form in forms if form}:
            matches.append(keys[0])
    return matches if len(matches) == 1 else []


def _unsquash(squashed: str, name_squash: Dict[str, List[str]]) -> List[str]:
    """Recover a name's tokens. Stored alongside the squashed form."""
    return _SQUASH_TOKENS.get(squashed, [])


#: Populated as names are squashed, so the merge step can compare token
#: forms without re-parsing every participant.
_SQUASH_TOKENS: Dict[str, List[str]] = {}


def _absorb_into(target: Participant, source: Participant) -> None:
    """Fold one duplicate entry into the one being kept."""
    if not target.entity_id and source.entity_id:
        target.entity_id = source.entity_id
        target.name = source.name
    for email in source.emails:
        _add(target.emails, email)
    for domain in source.domains:
        _add(target.domains, domain)
    for document_id in source.document_ids:
        if document_id not in target.document_ids:
            target.document_ids.append(document_id)
    for predicate in source.relationships:
        _add(target.relationships, predicate)
    target.months |= source.months
    target.meeting_documents = max(target.meeting_documents, source.meeting_documents)
    target.ownership_hits += source.ownership_hits
    target.vendor_hits += source.vendor_hits
    target.advisory_hits += source.advisory_hits
    target.vendor_context = target.vendor_context or source.vendor_context
    target.advisory_context = target.advisory_context or source.advisory_context
    for entry in source.evidence:
        if entry not in target.evidence and len(target.evidence) < MAX_EVIDENCE_PER_PERSON:
            target.evidence.append(entry)
    for field_name in ("first_seen", "last_seen"):
        theirs = getattr(source, field_name)
        mine = getattr(target, field_name)
        if theirs and (not mine or (theirs < mine if field_name == "first_seen" else theirs > mine)):
            setattr(target, field_name, theirs)


# --------------------------------------------------------------- banding


def _classify(
    participant: Participant, *, home_domains: Set[str], org_domains: Dict[str, str]
) -> None:
    """Sort one person into a band, recording why.

    Ordered by how much the signal actually settles. An email domain is near
    dispositive about which organization someone belongs to; a pattern of
    attendance plus ownership language is suggestive; everything else is not
    enough, and says so.
    """
    reasons: List[str] = []

    matched_home = [value for value in participant.domains if value in home_domains]
    external = [
        (value, org_domains[value])
        for value in participant.domains
        if value in org_domains and value not in home_domains
    ]

    if matched_home:
        participant.band = CORE_INTERNAL
        reasons.append(f"uses a company email address ({matched_home[0]})")
    elif external:
        domain, org = external[0]
        participant.band = EXTERNAL_ADVISORY
        participant.affiliated_org = org
        reasons.append(f"identifies with {org} ({domain})")
        if participant.advisory_hits or participant.advisory_context:
            reasons.append("appears in advisory or legal context")
    elif participant.recurring and participant.ownership_hits:
        # Checked before the vendor signal. Someone who turns up across the
        # operating record owning deliverables is doing the work, even if a
        # thread they are on also mentions a factory.
        participant.band = CORE_INTERNAL
        reasons.append(
            f"appears in {len(participant.document_ids)} documents across "
            f"{len(participant.months)} months"
        )
        reasons.append("named alongside ownership of deliverables")
    elif (
        "supplied_by" in participant.relationships
        or participant.vendor_context
        or participant.vendor_hits >= 2
    ):
        participant.band = COLLABORATOR_VENDOR
        reasons.append("appears alongside supply, quoting, or manufacturing language")
    else:
        participant.band = UNCLEAR
        if participant.recurring:
            reasons.append(
                f"appears repeatedly ({len(participant.document_ids)} documents) but "
                "nothing states their relationship to the company"
            )
        elif participant.document_ids:
            reasons.append(
                f"appears in {len(participant.document_ids)} document(s) with no other signal"
            )

    if participant.meeting_documents:
        reasons.append(f"present in {participant.meeting_documents} meeting or agenda document(s)")
    if participant.relationships:
        reasons.append("has recorded relationship(s): " + ", ".join(participant.relationships))
    if not participant.canonical:
        reasons.append("no canonical entity record exists for this person")

    participant.reasons = reasons


# ---------------------------------------------------------------- payload


def to_payload(
    participants: Sequence[Participant], *, home_known: bool = True
) -> Dict[str, Any]:
    """The participant picture as DATA for synthesis, with its standing rules."""
    return payload_from_dicts(
        [participant.to_dict() for participant in participants], home_known=home_known
    )


def payload_from_dicts(
    rows: Sequence[Dict[str, Any]], *, home_known: bool = True
) -> Dict[str, Any]:
    """Same, for participants already serialized by a tool call."""
    grouped: Dict[str, List[Dict[str, Any]]] = {band: [] for band in BANDS}
    for row in rows:
        grouped.setdefault(str(row.get("band") or UNCLEAR), []).append(row)

    return {
        "participants": {band: rows for band, rows in grouped.items() if rows},
        "band_descriptions": dict(BAND_DESCRIPTIONS),
        "home_company_known": home_known,
        "rule": (
            "These bands are assembled from participation, email domains, ownership "
            "language, recorded relationships, and time. They are NOT a roster and NOT "
            "an org chart.\n"
            "- Any statement about who someone is to the company is an INFERENCE. Type it "
            "'inference', hedge it ('appears to', 'based on the record'), and cite the "
            "documents behind it.\n"
            "- Never state or imply employment, a job title, or a reporting line. Those are "
            "matters of record and no amount of attendance establishes one.\n"
            "- A person in 'unclear' is someone the evidence does not place. Say so plainly "
            "rather than guessing a band for them.\n"
            + (
                ""
                if home_known
                else "- No canonical company record with an email domain exists, so internal "
                "and external cannot be separated reliably. Say that.\n"
            )
        ),
    }


# ----------------------------------------------------------------- helpers


def _person_lookup(people: Sequence[Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    by_email: Dict[str, Any] = {}
    by_name: Dict[str, Any] = {}
    for record in people:
        for email in getattr(record, "emails", []) or []:
            by_email[_fold(email)] = record
        by_name[_fold(record.name)] = record
        for alias in getattr(record, "aliases", []) or []:
            by_name.setdefault(_fold(alias), record)
    return by_email, by_name


def _org_domains(companies: Sequence[Any]) -> Dict[str, str]:
    domains: Dict[str, str] = {}
    for record in companies:
        for value in getattr(record, "domains", []) or []:
            domain = _domain(value)
            if domain:
                domains[domain] = record.name
        for email in getattr(record, "emails", []) or []:
            domain = _domain(email)
            if domain:
                domains.setdefault(domain, record.name)
    return domains


def _split_participants(value: str) -> List[Tuple[str, str]]:
    """Split a participant line into (name, email) pairs."""
    people: List[Tuple[str, str]] = []
    for chunk in re.split(r"[;,]", value):
        chunk = chunk.strip()
        # A collapsed header runs the whole first paragraph into one chunk,
        # so length is not a useful filter here. The name is bounded below,
        # after the address has been used to find where it ends.
        if not chunk or len(chunk) > 400:
            continue
        email_match = _EMAIL.search(chunk)
        email = _fold(email_match.group(0)) if email_match else ""
        if email_match:
            # `Name <addr>` is the standard form, so the name is what comes
            # *before* the address. Taking everything except the address
            # would trail off into the paragraph that follows a collapsed
            # header line.
            name = chunk[: email_match.start()]
        else:
            name = chunk
        name = _ENTITY_RESIDUE.sub(" ", name)
        name = name.replace("<", " ").replace(">", " ")
        # A collapsed header can prefix a name with the label of the line it
        # ran into: "- To: Frank Godchaux".
        name = re.sub(r"^[\s\-*>]*(?:to|cc|bcc|from|sent|subject|date)\s*:\s*", "", name,
                      flags=re.IGNORECASE)
        name = name.strip(" \t\"'()-").strip()
        tokens = name.split()
        if len(tokens) > MAX_NAME_TOKENS:
            name = " ".join(tokens[:MAX_NAME_TOKENS]) if not email else ""
        if not name and not email:
            continue
        people.append((name, email))
    return people


def _looks_like_a_name(name: str) -> str:
    """Whether a chunk with no address attached reads as a person's name."""
    text = (name or "").strip()
    if not text or len(text) > MAX_NAME_CHARS:
        return False
    tokens = text.split()
    if not 1 <= len(tokens) <= MAX_NAME_TOKENS:
        return False
    if not tokens[0][:1].isalpha():
        # Dates and subject fragments arrive looking like short capitalized
        # phrases; a person's name does not start with a digit.
        return False
    if _fold(tokens[-1]) in ("team", "group", "list", "support", "notifications"):
        return False
    if any(character in text for character in ".!?"):
        # Initials are fine; sentence punctuation is not.
        if not all(len(token.rstrip(".")) <= 2 or not token.endswith(".") for token in tokens):
            return False
    return all(token[:1].isupper() for token in tokens if token[:1].isalpha())


def _sentences_naming(text: str, needle: str) -> List[str]:
    """Sentences that actually contain this name."""
    lowered = needle.casefold()
    return [
        sentence
        for sentence in _SENTENCE.split(text)
        if lowered in sentence.casefold()
    ][:6]


def _attributes_ownership(sentence: str, needle: str, other_names: Sequence[str] = ()) -> bool:
    """Whether the sentence assigns work *to this person*, not merely near them.

    Two conditions, and the second is the one that matters. The name has to
    come before the verb, and no *other* known person may stand between them.
    A collapsed attendee list running into the first line of the minutes puts
    everyone who was present immediately before "owns the deliverable"; only
    the name nearest the verb is its subject.
    """
    match = _OWNERSHIP.search(sentence)
    if not match:
        return False
    lowered = sentence.casefold()
    # The occurrence nearest the verb is the candidate subject. A name can
    # appear twice in one collapsed sentence — once in the attendee list,
    # once as the actual subject — and only the second one is doing any work.
    position = lowered.rfind(needle.casefold(), 0, match.start())
    if position < 0:
        return False

    between = lowered[position + len(needle) : match.start()]
    return not any(
        other.casefold() in between
        for other in other_names
        if other and other.casefold() != needle.casefold()
    )


def _first_form(text: str, forms: Iterable[str]) -> str:
    """The longest surface form of a name that the text actually contains."""
    lowered = text.casefold()
    hits = [form for form in forms if form and len(form) >= 3 and form.casefold() in lowered]
    return max(hits, key=len) if hits else ""


def _window_around(text: str, needle: str, size: int = 200) -> str:
    position = text.casefold().find(needle.casefold())
    if position < 0:
        return ""
    start = max(0, position - size // 2)
    return text[start : position + len(needle) + size // 2]


def _domain(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = text.split("@")[-1]
    text = re.sub(r"^https?://", "", text).split("/")[0]
    return text[4:] if text.startswith("www.") else text


def _fold(value: Any) -> str:
    return str(value or "").strip().casefold()


def _add(values: List[str], value: str) -> None:
    text = _fold(value)
    if text and text not in values:
        values.append(text)
