"""What kind of source is this document, and may it speak to identity?

Two layers need the same answer. Evidence facts need to know whether a
sentence came from a board record or a retail newsletter before they rank it,
and derived entity profiles need to know which of a person's thousand mailbox
appearances are worth citing at all. Both import this module, which is why it
sits at the top of ``core`` with nothing but the standard library under it:
the entity layer must not import the Ask layer, and neither may this.

The classes, most authoritative first:

``corporate-record``
    A non-email document whose title names a legal or corporate instrument —
    bylaws, an operating agreement, a formation certificate, an 83(b) — and
    whose own text, when it has any, names one too. A file called
    ``Bylaws.docx`` is not a record on its name alone.
``company-document``
    Any other non-email document: a Drive file, an email attachment, an
    uploaded note, a meeting transcript someone chose to ingest.
``meeting-notes``
    Formal notes, minutes, recaps, and meeting summaries, including ones that
    arrive by email.
``agenda``
    A forward-looking working document. Its "Decision" headings are questions
    still to be answered, so it never supplies a decision record.
``email``
    Ordinary authored correspondence.
``bulk``
    Newsletters, marketing, receipts, calendar notifications, and other
    automated mail. Never identity evidence, never a decision record: being
    the recipient of a newsletter says nothing about who someone is.

Classification reads the title, the source type, and the structured sender
headers ingestion recorded. Body text is consulted only ever to *demote* a
document: bulk mail by its unsubscribe and "you are receiving this"
boilerplate, and a legal-sounding title whose document never names the
instrument it claims to be. A document can argue its way down, never up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence


CORPORATE_RECORD = "corporate-record"
COMPANY_DOCUMENT = "company-document"
MEETING_NOTES = "meeting-notes"
AGENDA = "agenda"
EMAIL = "email"
BULK = "bulk"

SOURCE_CLASSES = (CORPORATE_RECORD, COMPANY_DOCUMENT, MEETING_NOTES, AGENDA, EMAIL, BULK)

#: Coarse bands, not a score. Higher is more authoritative.
SOURCE_RANKS: Dict[str, int] = {
    CORPORATE_RECORD: 100,
    COMPANY_DOCUMENT: 80,
    MEETING_NOTES: 70,
    AGENDA: 50,
    EMAIL: 40,
    BULK: 0,
}

SOURCE_DESCRIPTIONS = {
    CORPORATE_RECORD: "a corporate or legal record",
    COMPANY_DOCUMENT: "a company document",
    MEETING_NOTES: "formal meeting notes",
    AGENDA: "a working agenda",
    EMAIL: "an ordinary email",
    BULK: "bulk or automated mail",
}

#: Classes that may supply identity evidence (relationship facts, profile
#: citations). Bulk mail is the one exclusion.
IDENTITY_CLASSES = frozenset(
    {CORPORATE_RECORD, COMPANY_DOCUMENT, MEETING_NOTES, AGENDA, EMAIL}
)

#: Classes that may supply decision records. An agenda lists decisions still
#: to be taken; bulk mail takes none.
DECISION_CLASSES = frozenset({CORPORATE_RECORD, COMPANY_DOCUMENT, MEETING_NOTES, EMAIL})

_EMAIL_SOURCE_TYPES = ("gmail", "email", "mail")

#: A file that arrived attached to an email is a document, not correspondence.
_ATTACHMENT_SOURCE_SUFFIX = "-attachment"

#: How much of a document's own text may corroborate a legal title.
#: Instruments name themselves at the top.
CORROBORATION_WINDOW = 3000

_CORPORATE_TITLE = re.compile(
    r"\b(?:by-?\s?laws|operating\s+agreement|articles\s+of\s+(?:incorporation|organization)|"
    r"certificate\s+of\s+(?:formation|incorporation|organization)|"
    r"(?:shareholders?|stockholders?|founders?|partnership|membership)\s+agreement|"
    r"board\s+(?:consent|resolutions?)|written\s+consent|minutes\s+of|cap\s+table|"
    r"engagement\s+letter|s[-\s]?election|form\s+2553|ein\s+(?:letter|notice))\b"
    # Outside the \b group: a word boundary never follows the closing
    # parenthesis, so "83(b)" inside it could not match.
    r"|\b83\s*\(\s*b\s*\)",
    re.IGNORECASE,
)

#: A template or sample of an instrument is not the instrument.
_TEMPLATE_TITLE = re.compile(r"\b(?:template|sample|specimen|example)s?\b", re.IGNORECASE)

_MEETING_TITLE = re.compile(
    r"\b(?:meeting\s+(?:\w+\s+){0,2}notes|notes|minutes|recap|summary\s+of|"
    r"executive\s+board|board\s+meeting|transcript|debrief)\b",
    re.IGNORECASE,
)

_AGENDA_TITLE = re.compile(
    r"\b(?:agenda|working\s+version|draft)\b",
    re.IGNORECASE,
)

#: Calendar traffic is automated whatever address it comes from.
_NOTIFICATION_TITLE = re.compile(
    r"^\s*(?:(?:updated\s+|new\s+|accepted:\s*|declined:\s*|tentative:\s*)?invitation\b|"
    r"accepted:|declined:|tentatively\s+accepted:|reminder:|"
    r"your\s+receipt\b|receipt\s+from\b|order\s+(?:confirmation|summary)\b|"
    r"\[action\s+needed\])",
    re.IGNORECASE,
)

#: Local parts that belong to a system, not a person.
_AUTOMATED_LOCAL = re.compile(
    r"^(?:no-?reply|do-?not-?reply|donotreply|newsletters?|news|marketing|mailer|"
    r"mailer-daemon|notifications?|notify|updates?|info|hello|team|support|billing|"
    r"invoices?|receipts?|orders?|store|shop|digest|alerts?|calendar-notification|"
    r"jira|bounces?|postmaster|tickets?)(?:[+._-].*)?$",
    re.IGNORECASE,
)

_BULK_BODY = re.compile(
    r"\bunsubscribe\b|\bmanage\s+(?:your\s+)?(?:email\s+|subscription\s+)?preferences\b|"
    r"\bview\s+(?:this\s+(?:email|message)\s+)?in\s+(?:your\s+)?browser\b|"
    r"\byou(?:'re|’re|\s+are)\s+(?:receiving|getting)\s+this\b|"
    r"\binvitation\s+from\s+google\s+calendar\b|\bemail\s+preferences\b",
    re.IGNORECASE,
)

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")

#: ``From:`` as the Gmail adapter renders it into a thread body. Used only
#: where structured headers are unavailable (the generated index keeps the
#: body, not the frontmatter).
_FROM_LINE = re.compile(r"(?:^|[\s-])From:\s*(?P<value>.{1,160}?)(?=\s-\s[A-Z][a-z]+:|\n|$)")


@dataclass(frozen=True)
class SourceClass:
    """One document's class, rank, and the reason it was given them."""

    name: str
    reason: str

    @property
    def rank(self) -> int:
        return SOURCE_RANKS.get(self.name, 0)

    @property
    def identity_evidence(self) -> bool:
        return self.name in IDENTITY_CLASSES

    @property
    def decision_evidence(self) -> bool:
        return self.name in DECISION_CLASSES

    def to_dict(self) -> Dict[str, Any]:
        return {"class": self.name, "rank": self.rank, "reason": self.reason}


def classify_source(
    *,
    title: str = "",
    source_type: str = "",
    document_type: str = "",
    senders: Sequence[str] = (),
    body: str = "",
    known_addresses: Iterable[str] = (),
    known_domains: Iterable[str] = (),
) -> SourceClass:
    """Classify one document. Deterministic, and never calls anything.

    ``known_addresses`` and ``known_domains`` are the canonical entity
    identifiers: mail from a person or organization the corpus has a record
    for is correspondence, whatever boilerplate it happens to carry.
    """
    title = str(title or "")
    source_type = str(source_type or "").casefold()
    document_type = str(document_type or "").casefold()
    is_email = (
        source_type.startswith(_EMAIL_SOURCE_TYPES) or document_type.startswith("email")
    ) and not source_type.endswith(_ATTACHMENT_SOURCE_SUFFIX)

    if not is_email:
        if _CORPORATE_TITLE.search(title):
            if _TEMPLATE_TITLE.search(title):
                return SourceClass(COMPANY_DOCUMENT, "title marks a template or sample, not an executed record")
            content = _content_without_title(body, title)
            if content and not _CORPORATE_TITLE.search(content[:CORROBORATION_WINDOW]):
                return SourceClass(
                    COMPANY_DOCUMENT, "title names a legal instrument the document's own text does not"
                )
            return SourceClass(CORPORATE_RECORD, "title names a corporate or legal instrument")
        if source_type == "meeting" or document_type in ("meeting", "meeting-note", "meeting-notes"):
            return SourceClass(MEETING_NOTES, "ingested as a meeting record")
        if _AGENDA_TITLE.search(title):
            return SourceClass(AGENDA, "title marks a working agenda or draft")
        return SourceClass(COMPANY_DOCUMENT, "non-email company document")

    # A meeting summary is often delivered by a no-reply assistant. Its title
    # says what it is, so it is read before the sender is.
    if _AGENDA_TITLE.search(title):
        return SourceClass(AGENDA, "title marks a working agenda or draft")
    if _MEETING_TITLE.search(title) and not _NOTIFICATION_TITLE.search(title):
        return SourceClass(MEETING_NOTES, "title marks formal notes, minutes, or a meeting summary")
    if _NOTIFICATION_TITLE.search(title):
        return SourceClass(BULK, "title marks an automated notification, invitation, or receipt")

    addresses = [address.casefold() for address in _sender_addresses(senders)]
    known = {str(value).casefold() for value in known_addresses if value}
    domains = {str(value).casefold() for value in known_domains if value}
    from_known = any(
        address in known or address.split("@")[-1] in domains for address in addresses
    )
    if from_known:
        return SourceClass(EMAIL, "sent by a person or organization with a canonical record")

    if addresses and all(_automated(address) for address in addresses):
        return SourceClass(BULK, "every sender is an automated or list address")
    if _BULK_BODY.search(body or ""):
        return SourceClass(BULK, "carries bulk-mail unsubscribe or notification boilerplate")
    return SourceClass(EMAIL, "ordinary correspondence")


def senders_from_frontmatter(frontmatter: Dict[str, Any]) -> List[str]:
    """``From`` headers recorded by ingestion, one per message."""
    senders: List[str] = []
    envelope = frontmatter.get("ingestion_envelope")
    messages = envelope.get("messages") if isinstance(envelope, dict) else None
    for message in messages or []:
        if not isinstance(message, dict):
            continue
        headers = message.get("headers")
        if isinstance(headers, dict):
            value = str(headers.get("From") or headers.get("from") or "").strip()
            if value:
                senders.append(value)
    return senders


def senders_from_body(body: str, *, limit: int = 12) -> List[str]:
    """``From:`` lines as the Gmail adapter renders them into a thread body."""
    found: List[str] = []
    for match in _FROM_LINE.finditer(body or ""):
        value = match.group("value").strip()
        if value and value not in found:
            found.append(value)
        if len(found) >= limit:
            break
    return found


def _content_without_title(body: str, title: str) -> str:
    """The document's own words: its text minus headings that only echo the title.

    Empty when the caller supplied no body, in which case the title rule
    stands on its own as it always has.
    """
    text = str(body or "")
    if title:
        text = re.sub(re.escape(title), " ", text, flags=re.IGNORECASE)
    text = re.sub(r"(?m)^\s*#{1,6}\s*(?:extracted\s+text|page\s+\d+)?\s*$", " ", text, flags=re.IGNORECASE)
    return text.strip()


def _sender_addresses(senders: Sequence[str]) -> List[str]:
    addresses: List[str] = []
    for sender in senders:
        for address in _EMAIL.findall(str(sender or "")):
            if address not in addresses:
                addresses.append(address)
    return addresses


def _automated(address: str) -> bool:
    local, _, domain = address.partition("@")
    if _AUTOMATED_LOCAL.match(local):
        return True
    # ESP sending subdomains: mail.anthropic.com, email.claude.com, e.brand.com.
    return bool(re.match(r"^(?:mail|email|e|em|news|mailer|bounce|send)\.", domain))


def rank_of(name: Optional[str]) -> int:
    return SOURCE_RANKS.get(str(name or ""), 0)
