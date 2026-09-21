"""Genuine quantities, and the identifiers that merely contain digits.

The numeric grounding check exists to catch a model quoting a figure the
evidence never stated. It was doing that with a regex for "run of digits",
which cannot tell 27832 units from certification QI-27832 — so every answer
that correctly named the certification was warned about an unverified numeric
claim, and the warning channel started costing more attention than it earned.

Two layers, in order:

1. **An identifier mask.** A small, explicit list of shapes GANG's corpus
   actually contains: part and certification codes, FCC IDs, SKUs and other
   labelled product identifiers, and version strings. This is a GANG layer on
   purpose. It is not a general parser, it does not learn, and every pattern
   here is one somebody can read and argue with.
2. **``quantulum3`` on what is left.** Recognizing that "$3–4 per unit" is one
   ranged price and "a 60-minute call" is a duration is exactly the work a
   quantity parser already does well, and not work worth reimplementing.

Identifiers are masked with spaces rather than removed, so every span the
parser reports still lines up with the original text and the proximity check
above still measures real distance.
"""

from __future__ import annotations

import re
import warnings
from functools import lru_cache
from typing import List, Sequence, Tuple


#: Parsed texts repeat constantly — the same cited excerpt is checked once per
#: claim in an answer — and quantity parsing is the expensive part of
#: validation. The cache is per-process and keyed on the text itself.
PARSE_CACHE_SIZE = 512

#: Certification and part codes: letters running straight into digits
#: (``Form03``, ``PTx3600``), or an upper-case prefix joined by a separator
#: (``QI-27832``, ``GN-4001``). The separator form insists on an upper-case
#: prefix so that ordinary hyphenated text — ``pre-2026``, ``sub-299`` — keeps
#: its number.
_CODE_LETTERS_FIRST = r"\b[A-Za-z]{1,12}\d[A-Za-z0-9]*\b"
_CODE_SEPARATED = r"\b[A-Z][A-Za-z0-9]{0,11}[-_]\d[A-Za-z0-9-]*\b"
_CODE_DIGITS_FIRST = r"\b\d+[A-Z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*\b"

#: Dotted version strings. ``3.1.2`` is a version, not the number three.
_VERSION = r"\bv(?:ersion)?[\s.]?\d+(?:\.\d+){1,3}\b|\b\d+(?:\.\d+){2,3}\b"

#: A code that only reads as one because of the word in front of it. Pure
#: digits — a UPC, an EAN — look like a quantity to any parser, so the label
#: is what settles it.
_LABELLED = (
    r"\b(?:fcc\s*id|sku|upc|ean|gtin|isbn|mpn|imei|asin|"
    r"serial(?:\s*(?:no\.?|number))?|model(?:\s*(?:no\.?|number))?|"
    r"part\s*(?:no\.?|number)?|lot\s*(?:no\.?|number)?|"
    r"(?:reference|ref|order|invoice|ticket)\s*(?:no\.?|number|#)?)"
    r"\s*[:#]?\s*(?P<code>[A-Za-z0-9][A-Za-z0-9._-]*)"
)

_UUID = r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"

_IDENTIFIER = re.compile(
    "|".join(
        (
            _UUID,
            _LABELLED,
            _VERSION,
            _CODE_SEPARATED,
            _CODE_DIGITS_FIRST,
            _CODE_LETTERS_FIRST,
        )
    ),
    re.IGNORECASE,
)

_CITATION_MARKER = re.compile(r"\[\d{1,3}\]")

#: ``$3-$4`` repeats the currency symbol, and quantulum3 reads the whole span
#: as a single $3 rather than as a range. Blanking the second symbol turns it
#: into ``$3- 4``, which parses as the range it plainly is. One character out,
#: one space in, so every offset still points where it did.
_REPEATED_CURRENCY = re.compile(r"(?<=\d)\s*[-\u2010-\u2015]\s*(?P<symbol>[$£€¥])(?=\d)")


def identifier_spans(text: str) -> List[Tuple[int, int]]:
    """Where in ``text`` an identifier sits, as ``(start, end)`` pairs.

    For a labelled identifier only the code itself is reported; the label is
    ordinary prose and masking it would change nothing but readability.
    """
    spans: List[Tuple[int, int]] = []
    for match in _IDENTIFIER.finditer(text or ""):
        code = match.span("code")
        spans.append(code if code != (-1, -1) else match.span())
    return spans


def is_identifier(token: str) -> bool:
    """Whether a bare token reads as an identifier rather than a quantity."""
    text = (token or "").strip()
    if not text:
        return False
    return any(start == 0 and end == len(text) for start, end in identifier_spans(text))


def mask_identifiers(text: str) -> str:
    """``text`` with every identifier blanked, offsets preserved."""
    value = text or ""
    if not value:
        return ""
    characters = list(value)
    for start, end in identifier_spans(value):
        for position in range(start, end):
            characters[position] = " "
    return "".join(characters)


def quantity_positions(text: str) -> List[Tuple[int, str]]:
    """Every genuine quantity in ``text``, as ``(offset, normalized value)``.

    A ranged quantity contributes its endpoints as well as its midpoint, so a
    claim of "$3" and a source that said "$3–4" still line up.
    """
    return list(_parse(text or ""))


def quantities(text: str) -> List[str]:
    """Normalized quantity values in ``text``, in order of appearance."""
    return [value for _, value in quantity_positions(text)]


def strip_citations(text: str) -> str:
    """Citation markers are provenance, never figures in the claim."""
    return _CITATION_MARKER.sub(" ", text or "")


@lru_cache(maxsize=PARSE_CACHE_SIZE)
def _parse(text: str) -> Tuple[Tuple[int, str], ...]:
    masked = _blank_repeated_currency(mask_identifiers(text))
    if not any(character.isdigit() for character in masked):
        return ()

    found: List[Tuple[int, str]] = []
    for quantity in _parse_quantities(masked):
        start = _start_of(quantity)
        for value in _values(quantity):
            normalized = _normalize(value)
            if normalized:
                found.append((start, normalized))
    found.sort(key=lambda entry: entry[0])
    return tuple(found)


def _blank_repeated_currency(text: str) -> str:
    characters = list(text)
    for match in _REPEATED_CURRENCY.finditer(text):
        characters[match.start("symbol")] = " "
    return "".join(characters)


def _parse_quantities(masked: str) -> Sequence[object]:
    try:
        with warnings.catch_warnings():
            # quantulum3 warns at import that its optional unit-disambiguation
            # classifier is absent, and its own regex use trips a deprecation
            # warning on 3.13. GANG reads values, not units, and neither
            # belongs in the middle of an answer.
            warnings.simplefilter("ignore")
            from quantulum3 import parser

            return parser.parse(masked)
    except ImportError:  # pragma: no cover - quantulum3 is a hard dependency
        return ()
    except Exception:  # noqa: BLE001 - a parser failure must not fail a turn
        return ()


def _start_of(quantity: object) -> int:
    span = getattr(quantity, "span", None)
    if isinstance(span, tuple) and span:
        return int(span[0])
    return 0


def _values(quantity: object) -> List[float]:
    value = getattr(quantity, "value", None)
    if value is None:
        return []
    uncertainty = getattr(quantity, "uncertainty", None)
    if uncertainty:
        # quantulum3 reports "$3-4" as 3.5 ± 0.5. A source and a claim quote
        # the endpoints at each other, never the midpoint, so the range is
        # carried as the two figures that were actually written down.
        return [float(value) - float(uncertainty), float(value) + float(uncertainty)]
    return [float(value)]


def _normalize(value: float) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):  # pragma: no cover - defensive
        return ""
