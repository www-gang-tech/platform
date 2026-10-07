"""Resolve temporal language to explicit date ranges, once, before retrieval.

"this month" means one thing at plan time and must keep meaning it through
retrieval, synthesis, and the printed answer. Resolving it here — deterministic
code, one clock read, an explicit `YYYY-MM-DD` range on the plan — means the
model never gets a chance to reinterpret it halfway through.

Weeks start Monday. Ranges are inclusive on both ends.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple


ISO_DATE = "%Y-%m-%d"

_DATE_PATTERN = re.compile(r"\b(\d{4}-\d{2}-\d{2})\b")

#: A date the questioner wrote: day, month, or year. Year-only forms are how
#: people actually ask "since 2026" / "in 2026"; requiring YYYY-MM-DD left
#: those questions with no range at all.
_DATE_ATOM = r"(\d{4}-\d{2}-\d{2}|\d{4}-\d{2}|\d{4})"

#: Phrases whose meaning is fixed relative to "today". Longest match wins.
_RELATIVE_PHRASES = (
    "today",
    "yesterday",
    "this week",
    "last week",
    "this month",
    "last month",
    "this quarter",
    "this year",
    "last year",
)

_SINCE_PATTERN = re.compile(
    rf"\b(?:since|after|from)\s+{_DATE_ATOM}\b", re.IGNORECASE
)
_BEFORE_PATTERN = re.compile(
    rf"\b(?:before|until|up to|through)\s+{_DATE_ATOM}\b", re.IGNORECASE
)
_IN_YEAR_PATTERN = re.compile(r"\b(?:in|during)\s+(\d{4})\b", re.IGNORECASE)
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'._@-]*")
_LAST_N_PATTERN = re.compile(
    r"\b(?:in\s+the\s+)?(?:last|past)\s+(\d{1,4})\s*(day|days|week|weeks|month|months)\b",
    re.IGNORECASE,
)
_RELATIVE_SHORTHAND = re.compile(r"^(\d{1,4})\s*([dwmy])$", re.IGNORECASE)


class TemporalError(ValueError):
    """Raised when an explicit date the caller supplied cannot be parsed."""


def today(clock: Optional[date] = None) -> date:
    return clock or datetime.now(timezone.utc).date()


def resolve_question_range(question: str, *, clock: Optional[date] = None) -> Optional[Dict[str, str]]:
    """Extract a date range from natural-language temporal phrasing.

    Returns ``{"field": "updated", "start": ..., "end": ...}`` or ``None`` when
    the question carries no temporal signal. Either bound may be an empty
    string, meaning unbounded on that side.
    """
    now = today(clock)
    text = question.lower()

    since = _SINCE_PATTERN.search(question)
    before = _BEFORE_PATTERN.search(question)
    if since or before:
        return _range(
            _parse_date_atom(since.group(1), role="start") if since else None,
            _parse_date_atom(before.group(1), role="end") if before else None,
        )

    in_year = _IN_YEAR_PATTERN.search(question)
    if in_year:
        year = _parse_date_atom(in_year.group(1), role="start")
        return _range(year, min(now, date(year.year, 12, 31)))

    window = _LAST_N_PATTERN.search(text)
    if window:
        return _range(_shift(now, int(window.group(1)), window.group(2)), now)

    for phrase in sorted(_RELATIVE_PHRASES, key=len, reverse=True):
        if re.search(rf"\b{re.escape(phrase)}\b", text):
            start, end = _phrase_range(phrase, now)
            return _range(start, end)

    return None


def consumed_temporal_terms(question: str) -> set:
    """Tokens that built the date range, so they are not also searched as text.

    "since 2026" is a window, not a request to FTS-match the words "since" and
    "2026" — those two terms were ranking 2025 mail that happened to say
    "since we last spoke".
    """
    if resolve_question_range(question) is None:
        return set()
    terms: set = set()
    for pattern in (_SINCE_PATTERN, _BEFORE_PATTERN, _IN_YEAR_PATTERN):
        match = pattern.search(question or "")
        if match:
            terms.update(token.lower() for token in _TOKEN_PATTERN.findall(match.group(0)))
    return terms


def resolve_bound(value: str, *, clock: Optional[date] = None) -> str:
    """Resolve one explicit CLI bound (`--since` / `--until`) to `YYYY-MM-DD`.

    Accepts an ISO date, a `30d` / `6w` / `3m` / `1y` shorthand, or one of the
    relative phrases. Raises rather than guessing.
    """
    text = (value or "").strip()
    if not text:
        return ""
    now = today(clock)

    if _DATE_PATTERN.fullmatch(text):
        return _parse_date(text).strftime(ISO_DATE)

    shorthand = _RELATIVE_SHORTHAND.match(text)
    if shorthand:
        unit = {"d": "days", "w": "weeks", "m": "months", "y": "years"}[shorthand.group(2).lower()]
        return _shift(now, int(shorthand.group(1)), unit).strftime(ISO_DATE)

    lowered = text.lower()
    if lowered in _RELATIVE_PHRASES:
        start, _ = _phrase_range(lowered, now)
        return start.strftime(ISO_DATE) if start else ""

    raise TemporalError(
        f"Could not parse date {value!r}. Use YYYY-MM-DD, a window such as 30d, or a phrase such as 'last week'."
    )


def _phrase_range(phrase: str, now: date) -> Tuple[Optional[date], Optional[date]]:
    if phrase == "today":
        return now, now
    if phrase == "yesterday":
        previous = now - timedelta(days=1)
        return previous, previous
    if phrase == "this week":
        start = now - timedelta(days=now.weekday())
        return start, now
    if phrase == "last week":
        this_week = now - timedelta(days=now.weekday())
        start = this_week - timedelta(days=7)
        return start, this_week - timedelta(days=1)
    if phrase == "this month":
        return now.replace(day=1), now
    if phrase == "last month":
        first_of_this = now.replace(day=1)
        end = first_of_this - timedelta(days=1)
        return end.replace(day=1), end
    if phrase == "this quarter":
        first_month = 3 * ((now.month - 1) // 3) + 1
        return now.replace(month=first_month, day=1), now
    if phrase == "this year":
        return now.replace(month=1, day=1), now
    if phrase == "last year":
        return date(now.year - 1, 1, 1), date(now.year - 1, 12, 31)
    return None, None


def _shift(now: date, amount: int, unit: str) -> date:
    unit = unit.lower().rstrip("s")
    if unit == "day":
        return now - timedelta(days=amount)
    if unit == "week":
        return now - timedelta(weeks=amount)
    if unit == "month":
        return _subtract_months(now, amount)
    if unit == "year":
        return _subtract_months(now, amount * 12)
    raise TemporalError(f"Unsupported time unit: {unit}")


def _subtract_months(value: date, months: int) -> date:
    total = (value.year * 12 + value.month - 1) - months
    year, month = divmod(total, 12)
    day = min(value.day, _days_in_month(year, month + 1))
    return date(year, month + 1, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def _parse_date(text: str) -> date:
    try:
        return datetime.strptime(text, ISO_DATE).date()
    except ValueError as exc:
        raise TemporalError(f"Could not parse date {text!r}") from exc


def _parse_date_atom(text: str, *, role: str) -> date:
    """Turn a day, month, or year atom into a bound.

    ``since 2026`` starts at 1 January. ``before 2026`` ends at 31 December
    2025's successor year-end — the atom itself is the year 2026, so the
    *end* bound is 2026-12-31. Callers that mean "until the year begins"
    should write ``before 2026-01-01``.
    """
    value = (text or "").strip()
    if _DATE_PATTERN.fullmatch(value):
        return _parse_date(value)
    month = re.fullmatch(r"(\d{4})-(\d{2})", value)
    if month:
        year, month_n = int(month.group(1)), int(month.group(2))
        if not 1 <= month_n <= 12:
            raise TemporalError(f"Could not parse date {text!r}")
        if role == "end":
            return date(year, month_n, _days_in_month(year, month_n))
        return date(year, month_n, 1)
    year_match = re.fullmatch(r"(\d{4})", value)
    if year_match:
        year = int(year_match.group(1))
        if year < 1900 or year > 2100:
            raise TemporalError(f"Could not parse date {text!r}")
        if role == "end":
            return date(year, 12, 31)
        return date(year, 1, 1)
    raise TemporalError(f"Could not parse date {text!r}")


def _range(start: Optional[date], end: Optional[date]) -> Dict[str, str]:
    return {
        "field": "updated",
        "start": start.strftime(ISO_DATE) if start else "",
        "end": end.strftime(ISO_DATE) if end else "",
    }


def date_prefix(value: Any) -> str:
    """The `YYYY-MM-DD` prefix of a stored timestamp, for range comparison."""
    text = "" if value is None else str(value).strip()
    match = _DATE_PATTERN.search(text)
    return match.group(1) if match else text[:10]
