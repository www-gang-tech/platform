"""How sensitive is this document, and why?

Every document has exactly one of three levels:

``normal``
    Existing behavior everywhere.
``restricted``
    Retrievable locally by anyone the existing access rules already trust, and
    kept out of remote-provider contexts.
``local-only``
    Never sent to a remote provider under any configuration. Deterministic
    answers and local models may still use it.

The level controls *disclosure*, not custody. Nothing here edits, redacts, or
relocates a canonical document or its raw evidence; the canonical copy stays
exactly where ingestion put it. What changes is which contexts a document is
allowed to enter.

Two inputs decide the level, in this order:

1. **An explicit override.** ``sensitivity: restricted`` (or ``normal``, or
   ``local-only``) in a document's frontmatter is a human decision and wins
   outright, in either direction, so a false positive can be corrected. An
   optional ``sensitivity_reason`` records why. Connectors carry both across
   re-ingestion, like entity references.
2. **Deterministic detection.** A small set of strongly structured patterns —
   a formatted Social Security number, an ITIN, a labelled taxpayer, bank,
   passport, or driver's license number, an IBAN or payment card that passes
   its checksum, the printed title *and* field labels of a tax form. Any hit
   makes the document ``local-only``. There is deliberately no probabilistic
   PII scoring: a detector either matches a rigid shape or it says nothing.

Diagnostics report which detectors fired and how often. They never carry the
matched values, so a sensitivity report is safe to print.

Like ``source_classes``, this sits at the top of ``core`` with only the
standard library under it, because the index, the Ask layer, the entity layer,
enrichment, and the provider boundary all need the same answer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional, Pattern, Tuple


NORMAL = "normal"
RESTRICTED = "restricted"
LOCAL_ONLY = "local-only"

#: Least to most sensitive.
LEVELS = (NORMAL, RESTRICTED, LOCAL_ONLY)

#: Canonical frontmatter fields for the manual override.
OVERRIDE_FIELD = "sensitivity"
OVERRIDE_REASON_FIELD = "sensitivity_reason"

BASIS_OVERRIDE = "override"
BASIS_DETECTED = "detected"
BASIS_DEFAULT = "default"

#: What a detector hit implies. Every current detector is strong enough that
#: the document should never leave the machine.
DETECTED_LEVEL = LOCAL_ONLY


# ---------------------------------------------------------------- results


@dataclass(frozen=True)
class Finding:
    """One detector that fired, and how many times. Never the value itself."""

    detector: str
    category: str
    description: str
    count: int

    def to_dict(self) -> Dict[str, Any]:
        return {
            "detector": self.detector,
            "category": self.category,
            "description": self.description,
            "count": self.count,
        }


@dataclass(frozen=True)
class Assessment:
    """The level a document was given, and the reason for it."""

    level: str = NORMAL
    basis: str = BASIS_DEFAULT
    findings: Tuple[Finding, ...] = ()
    override: str = ""
    override_reason: str = ""
    invalid_override: str = ""

    @property
    def detected_level(self) -> str:
        return DETECTED_LEVEL if self.findings else NORMAL

    @property
    def permits_remote(self) -> bool:
        return permits_remote(self.level)

    def reasons(self) -> List[str]:
        """Human-readable reasons, safe to print: no matched values."""
        reasons: List[str] = []
        if self.basis == BASIS_OVERRIDE:
            text = f"explicit override in frontmatter: {OVERRIDE_FIELD}: {self.override}"
            if self.override_reason:
                text += f" ({self.override_reason})"
            reasons.append(text)
        for finding in self.findings:
            plural = "" if finding.count == 1 else "s"
            reasons.append(f"detected {finding.description} ({finding.count} match{plural})")
        if self.basis == BASIS_OVERRIDE and self.findings and self.level != self.detected_level:
            reasons.append(
                f"the override replaces the detected level ({self.detected_level})"
            )
        if self.invalid_override:
            reasons.append(
                f"ignored unrecognized {OVERRIDE_FIELD} value {self.invalid_override!r}; "
                f"expected one of {', '.join(LEVELS)}"
            )
        if not reasons:
            reasons.append("no override and no sensitive identifiers detected")
        return reasons

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "basis": self.basis,
            "detected_level": self.detected_level,
            "override": self.override,
            "override_reason": self.override_reason,
            "invalid_override": self.invalid_override,
            "findings": [finding.to_dict() for finding in self.findings],
            "reasons": self.reasons(),
        }

    @classmethod
    def from_dict(cls, value: Any) -> "Assessment":
        if not isinstance(value, Mapping):
            return cls()
        findings = tuple(
            Finding(
                detector=str(item.get("detector") or ""),
                category=str(item.get("category") or ""),
                description=str(item.get("description") or ""),
                count=int(item.get("count") or 0),
            )
            for item in value.get("findings") or []
            if isinstance(item, Mapping)
        )
        level = normalize_level(value.get("level")) or NORMAL
        return cls(
            level=level,
            basis=str(value.get("basis") or BASIS_DEFAULT),
            findings=findings,
            override=str(value.get("override") or ""),
            override_reason=str(value.get("override_reason") or ""),
            invalid_override=str(value.get("invalid_override") or ""),
        )


# ----------------------------------------------------------------- policy


def normalize_level(value: Any) -> Optional[str]:
    """A recognized level, tolerant of case and ``local_only`` spelling."""
    if not isinstance(value, str):
        return None
    text = value.strip().lower().replace("_", "-").replace(" ", "-")
    return text if text in LEVELS else None


def permits_remote(level: Any) -> bool:
    """Only ``normal`` may enter a remote-provider context.

    Anything unrecognized — including a missing level — is treated as not
    permitted. A document whose sensitivity cannot be established is not one
    to guess about.
    """
    return normalize_level(level) == NORMAL


def classify(frontmatter: Optional[Mapping[str, Any]], *texts: Any) -> Assessment:
    """Assess one document from its frontmatter and its text.

    Detection reads every string in the frontmatter as well as ``texts``:
    derived summaries and titles travel into model contexts too, so they are
    held to the same standard as the body.
    """
    frontmatter = frontmatter if isinstance(frontmatter, Mapping) else {}
    findings = tuple(detect("\n".join([_frontmatter_text(frontmatter), *map(_text, texts)])))

    raw_override = frontmatter.get(OVERRIDE_FIELD)
    override = normalize_level(raw_override)
    invalid = "" if override or raw_override in (None, "") else str(raw_override)[:40]
    reason = _text(frontmatter.get(OVERRIDE_REASON_FIELD))[:200]

    if override:
        return Assessment(
            level=override,
            basis=BASIS_OVERRIDE,
            findings=findings,
            override=override,
            override_reason=reason,
        )
    if findings:
        return Assessment(level=DETECTED_LEVEL, basis=BASIS_DETECTED, findings=findings, invalid_override=invalid)
    return Assessment(invalid_override=invalid)


def preserved_override(frontmatter: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    """The override fields a connector must carry across re-ingestion."""
    if not isinstance(frontmatter, Mapping):
        return {}
    return {
        key: frontmatter[key]
        for key in (OVERRIDE_FIELD, OVERRIDE_REASON_FIELD)
        if frontmatter.get(key) not in (None, "")
    }


def empty_counts() -> Dict[str, int]:
    return {level: 0 for level in LEVELS}


# -------------------------------------------------------------- detection
#
# Every detector is anchored on shape, and the loose shapes are anchored on a
# label as well. "123-45-6789" is an SSN by format alone; nine bare digits are
# only a routing number when the text says "routing" and the ABA checksum
# agrees. A customer account number on an invoice is not bank data, so a bare
# "Account number" label is not enough — it has to say bank, checking,
# savings, or beneficiary.

#: Between a label and its value: punctuation, whitespace, line breaks, and at
#: most a linking "is"/"was". Never another word, so a label cannot reach
#: across a sentence to an unrelated number.
_SEP = r"[^0-9A-Za-z]{0,30}?(?:(?:is|was)[^0-9A-Za-z]{1,10}?)?"

_SSN_FORMATTED = re.compile(
    r"(?<![\d-])(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}(?![\d-])"
)
_SSN_LABELED = re.compile(
    r"(?:\bSSN\b|\bSS#|\bSS\s?No\b\.?|(?i:\bsocial\s+security(?:\s+(?:number|no\b\.?|#))?))"
    + _SEP
    + r"(?<!\d)((?!000|666|9\d\d)\d{3}[ -]?(?!00)\d{2}[ -]?(?!0000)\d{4})(?![\d-])"
)
_ITIN = re.compile(
    r"(?<![\d-])9\d{2}-(?:5\d|6[0-5]|7\d|8[0-8]|9[0-2]|9[4-9])-\d{4}(?![\d-])"
)
_TAXPAYER_ID_LABELED = re.compile(
    r"(?:\b(?:F?EIN|TIN|ITIN)\b|(?i:\bemployer\s+identification\s+(?:number|no\b\.?)"
    r"|\btaxpayer\s+identification\s+(?:number|no\b\.?)"
    r"|\bfederal\s+(?:tax|employer)\s+(?:id|identification)(?:\s+(?:number|no\b\.?))?"
    r"|\b(?:payer|recipient|employer|partner|partnership)['’]?s\s+(?:TIN|identifying\s+number)))"
    + _SEP
    + r"(?<!\d)(\d{2}-?\d{7}|\d{3}-?\d{2}-?\d{4})(?![\d-])"
)
_ROUTING_LABELED = re.compile(
    r"(?:\bRTN\b|\bABA\b(?:\s+(?:number|no\b\.?|#|routing))?"
    r"|(?i:\brouting(?:\s+(?:and|&)\s+transit)?(?:\s+(?:number|no\b\.?|#))?))"
    + _SEP
    + r"(?<!\d)(\d{9})(?!\d)"
)
_BANK_ACCOUNT_LABELED = re.compile(
    r"(?i:\b(?:bank|checking|savings|deposit|beneficiary|DDA)\s+(?:account|acct\b\.?)"
    r"(?:\s+(?:number|no\b\.?|#))?)"
    + _SEP
    + r"(?<![\dA-Za-z])(\d(?:[ -]?\d){5,16})(?![\d])"
)
_IBAN = re.compile(
    r"(?<![A-Z0-9])([A-Z]{2}\d{2}(?:[A-Z0-9]{11,30}|(?: [A-Z0-9]{4}){2,7}(?: [A-Z0-9]{1,4})?))(?![A-Z0-9])"
)
_PAYMENT_CARD = re.compile(
    r"(?<![\d-])(\d{4}([ -])\d{4}\2\d{4}\2\d{4}|3[47]\d{2}([ -])\d{6}\3\d{5})(?![\d-])"
)
_PASSPORT_LABELED = re.compile(
    r"(?i:\bpassport\s+(?:number|no\b\.?|#))"
    + _SEP
    + r"(?<![A-Z0-9])((?=[A-Z0-9]*\d{6})[A-Z0-9]{6,9})(?![A-Z0-9])"
)
_DRIVERS_LICENSE_LABELED = re.compile(
    r"(?:(?i:\bdriver['’]?s?\s+licen[cs]e(?:\s+(?:number|no\b\.?|#))?)|\bDL\s?(?:#|No\b\.?|Number))"
    + _SEP
    + r"(?<![A-Z0-9])((?=[A-Z0-9-]*\d{4})[A-Z0-9][A-Z0-9-]{4,18}[A-Z0-9])(?![A-Z0-9])"
)

#: A tax form is recognized by its printed title AND at least one of the field
#: labels printed on the form itself. An email that merely says "attached is
#: my W-2" has neither, and stays normal unless its attachment says otherwise.
_TAX_FORMS: Tuple[Tuple[str, str, Tuple[str, ...]], ...] = (
    (
        "W-2",
        "wage and tax statement",
        (
            "wages, tips, other compensation",
            "federal income tax withheld",
            "employee's social security number",
            "employer identification number",
        ),
    ),
    (
        "W-9",
        "request for taxpayer identification number and certification",
        ("taxpayer identification number (tin)", "social security number", "employer identification number"),
    ),
    (
        "W-4",
        "employee's withholding certificate",
        ("social security number", "filing status", "single or married filing separately"),
    ),
    (
        "1040",
        "u.s. individual income tax return",
        ("adjusted gross income", "filing status", "taxable income"),
    ),
    (
        "1099",
        "form 1099",
        ("payer's tin", "recipient's tin", "nonemployee compensation", "federal income tax withheld"),
    ),
    (
        "K-1",
        "schedule k-1",
        ("partner's share of income", "partner's identifying number", "partnership's employer identification number"),
    ),
)


def _valid_ssn(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    return len(digits) == 9 and not digits.startswith(("000", "666", "9")) and digits[3:5] != "00" and digits[5:] != "0000"


def _aba_checksum(value: str) -> bool:
    digits = [int(character) for character in value]
    if len(digits) != 9 or not any(digits):
        return False
    total = (
        3 * (digits[0] + digits[3] + digits[6])
        + 7 * (digits[1] + digits[4] + digits[7])
        + (digits[2] + digits[5] + digits[8])
    )
    return total % 10 == 0


def _iban(value: str) -> bool:
    """A checksum-valid IBAN, allowing for one trailing word the pattern ate.

    In the grouped form an uppercase word after the number ("... 3000 FROM")
    looks exactly like one more group, so the last group gets a second chance
    to be dropped rather than the whole number being missed.
    """
    groups = value.split(" ")
    return _iban_checksum(value) or (len(groups) > 3 and _iban_checksum(" ".join(groups[:-1])))


def _iban_checksum(value: str) -> bool:
    compact = value.replace(" ", "")
    if not 15 <= len(compact) <= 34:
        return False
    rearranged = compact[4:] + compact[:4]
    try:
        number = "".join(str(int(character, 36)) for character in rearranged)
    except ValueError:
        return False
    return int(number) % 97 == 1


def _luhn(value: str) -> bool:
    digits = [int(character) for character in re.sub(r"\D", "", value)]
    total = 0
    for index, digit in enumerate(reversed(digits)):
        if index % 2:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return total % 10 == 0


def _card_prefix(value: str) -> bool:
    digits = re.sub(r"\D", "", value)
    return bool(
        re.match(r"4|5[1-5]|2(?:2[2-9]|[3-6]\d|7[01]|720)|3[47]|6(?:011|5)", digits)
    )


def _bank_account_digits(value: str) -> bool:
    return 6 <= len(re.sub(r"\D", "", value)) <= 17


@dataclass(frozen=True)
class _Detector:
    name: str
    category: str
    description: str
    pattern: Pattern[str]
    valid: Callable[[str], bool] = field(default=lambda value: True)

    def spans(self, text: str) -> List[Tuple[int, int]]:
        """Where each valid value sits in ``text`` — the value, not its label."""
        found: List[Tuple[int, int]] = []
        for match in self.pattern.finditer(text):
            group = 1 if match.groups() else 0
            value = match.group(group)
            if value and self.valid(value):
                found.append(match.span(group))
        return found

    def count(self, text: str) -> int:
        return len(self.spans(text))


_DETECTORS: Tuple[_Detector, ...] = (
    _Detector("us-ssn", "ssn", "US Social Security number", _SSN_FORMATTED),
    _Detector(
        "us-ssn-labeled",
        "ssn",
        "labelled US Social Security number",
        _SSN_LABELED,
        # A dash-formatted value is already counted by `us-ssn`; this one is
        # for the bare and space-separated forms only a label makes safe.
        lambda value: _valid_ssn(value) and not _SSN_FORMATTED.fullmatch(value),
    ),
    _Detector("us-itin", "taxpayer-id", "US individual taxpayer identification number", _ITIN),
    _Detector(
        "us-taxpayer-id-labeled",
        "taxpayer-id",
        "labelled taxpayer identification number (EIN/TIN)",
        _TAXPAYER_ID_LABELED,
    ),
    _Detector("bank-routing-labeled", "bank-account", "labelled ABA routing number", _ROUTING_LABELED, _aba_checksum),
    _Detector(
        "bank-account-labeled",
        "bank-account",
        "labelled bank account number",
        _BANK_ACCOUNT_LABELED,
        _bank_account_digits,
    ),
    _Detector("iban", "bank-account", "IBAN with a valid checksum", _IBAN, _iban),
    _Detector(
        "payment-card",
        "payment-card",
        "payment card number with a valid checksum",
        _PAYMENT_CARD,
        lambda value: _card_prefix(value) and _luhn(value),
    ),
    _Detector("passport-labeled", "government-id", "labelled passport number", _PASSPORT_LABELED),
    _Detector(
        "drivers-license-labeled",
        "government-id",
        "labelled driver's license number",
        _DRIVERS_LICENSE_LABELED,
    ),
)

def detect(text: Any) -> List[Finding]:
    """Which detectors fire on ``text``, with counts. Deterministic."""
    value = _normalize(_text(text))
    if not value:
        return []
    findings: List[Finding] = []
    for detector in _DETECTORS:
        count = detector.count(value)
        if count:
            findings.append(Finding(detector.name, detector.category, detector.description, count))
    forms = _tax_forms(value)
    if forms:
        findings.append(
            Finding(
                "tax-form",
                "tax-form",
                "tax form (" + ", ".join(forms) + ")",
                len(forms),
            )
        )
    return findings


def mask_identifiers(text: Any) -> str:
    """``text`` with every detected identifier value replaced by a marker.

    For display copies only — excerpts shown as provenance, session snapshots,
    answer caches. A canonical document is never passed through this. Labels
    and surrounding words stay, so the excerpt still reads as what it is.
    """
    value = _text(text)
    if not value:
        return value
    # Same-length normalization only, so spans index the original text.
    scanned = value.replace("’", "'").replace("‘", "'").replace("\u00a0", " ")
    spans: List[Tuple[int, int, str]] = []
    for detector in _DETECTORS:
        spans.extend((start, end, detector.category) for start, end in detector.spans(scanned))
    masked = value
    last_start = len(value) + 1
    for start, end, category in sorted(spans, key=lambda item: (item[0], -item[1]), reverse=True):
        if end > last_start:
            continue
        masked = masked[:start] + f"[{category} withheld]" + masked[end:]
        last_start = start
    return masked


def mask_for_level(text: Any, level: Any) -> Any:
    """``text`` masked when ``level`` is restricted or local-only, else unchanged.

    The display-copy rule for anything read out of such a document — excerpts
    and titles alike. Never applied to a canonical document.
    """
    if normalize_level(level) in (RESTRICTED, LOCAL_ONLY):
        return mask_identifiers(text)
    return text


def contains_sensitive_identifier(text: Any) -> List[str]:
    """Detector names that fire on ``text``; empty when it is clean."""
    return [finding.detector for finding in detect(text)]


def _tax_forms(text: str) -> List[str]:
    lowered = re.sub(r"\s+", " ", text.lower())
    found: List[str] = []
    for name, title, fields in _TAX_FORMS:
        if title in lowered and any(label in lowered for label in fields):
            found.append(name)
    return found


def _normalize(text: str) -> str:
    # Curly apostrophes are how the forms are printed and how most extractors
    # emit them. JSON-escaped whitespace is how text looks inside a serialized
    # provider request, which the egress check scans.
    return (
        text.replace("’", "'")
        .replace("‘", "'")
        .replace("\\n", "\n")
        .replace("\\t", " ")
        .replace("\\r", " ")
        .replace("\u00a0", " ")
    )


def _frontmatter_text(frontmatter: Mapping[str, Any]) -> str:
    parts: List[str] = []

    def collect(value: Any) -> None:
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, Mapping):
            for key, child in value.items():
                if key not in (OVERRIDE_FIELD, OVERRIDE_REASON_FIELD):
                    collect(child)
        elif isinstance(value, (list, tuple, set)):
            for child in value:
                collect(child)

    collect(frontmatter)
    return "\n".join(parts)


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ("" if value is None else str(value))
