"""Chronology as a retrieval primitive, not as something a model reconstructs.

"How did the BOM get from $160 to $130?" is a question about order. Answering
it by handing a model a relevance-ranked pile and asking it to work out the
sequence invites invented intermediate steps — a plausible middle value nobody
ever wrote down.

So the ordering is computed here, from the dates the documents already carry,
and the model's job is narration over a fixed sequence. Two properties matter:

* **Every item is a real document.** A timeline entry is a document id, its
  date, and an excerpt from it. There is no entry type for "and then presumably
  …", so there is nothing for an inferred event to be represented as.
* **Gaps stay gaps.** ``gaps()`` reports the intervals where the corpus simply
  holds nothing, so an answer can say the record is silent between two dates
  rather than smoothing over it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence

from .temporal import date_prefix


#: A timeline longer than this stops being a chronology and becomes a dump.
MAX_TIMELINE_ITEMS = 20

#: Months of silence between two entries before the gap is worth reporting.
GAP_DAYS = 30


@dataclass(frozen=True)
class TimelineItem:
    timestamp: str
    document_id: str
    title: str
    source: str = ""
    excerpt: str = ""
    entities: List[str] = field(default_factory=list)
    evidence_type: str = "document"
    citation_id: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "document_id": self.document_id,
            "title": self.title,
            "source": self.source,
            "excerpt": self.excerpt,
            "entities": list(self.entities),
            "evidence_type": self.evidence_type,
            "citation_id": self.citation_id,
        }


class Timeline(list):
    """Oldest-first timeline. Omission counts are documents left out by the cap."""

    def __init__(
        self,
        items: Sequence[TimelineItem] = (),
        *,
        dated_omitted: int = 0,
        undated_omitted: int = 0,
    ):
        super().__init__(items)
        self.dated_omitted = dated_omitted
        self.undated_omitted = undated_omitted

    @property
    def omitted(self) -> int:
        return self.dated_omitted + self.undated_omitted


def build_timeline(items: Sequence[Any], *, limit: int = MAX_TIMELINE_ITEMS) -> Timeline:
    """Order evidence oldest-first by the date each document carries.

    Undated documents sort last rather than being dropped: their content is
    still evidence, and silently discarding them would be a worse distortion
    than admitting we do not know when they happened.

    A list longer than ``limit`` keeps a contiguous window of the newest dated
    documents, oldest first inside that window, then any undated ones that
    still fit. Reported gaps are silences inside that window.
    """
    entries: List[TimelineItem] = []
    for item in items:
        timestamp = date_prefix(_get(item, "updated") or _get(item, "created"))
        excerpts = _get(item, "excerpts") or []
        entries.append(
            TimelineItem(
                timestamp=timestamp,
                document_id=str(_get(item, "document_id") or ""),
                title=str(_get(item, "title") or ""),
                source=str(_get(item, "source_type") or _get(item, "type") or ""),
                excerpt=str(excerpts[0]) if excerpts else "",
                entities=[
                    str(ref.get("name") or ref.get("label") or "")
                    for ref in (_get(item, "entity_refs") or [])
                    if isinstance(ref, dict)
                ][:6],
                evidence_type=str(_get(item, "type") or "document"),
                citation_id=int(_get(item, "citation_id") or 0),
            )
        )

    dated = sorted(
        (entry for entry in entries if entry.timestamp),
        key=lambda entry: (entry.timestamp, entry.citation_id),
    )
    undated = [entry for entry in entries if not entry.timestamp]
    return _cap_timeline(dated, undated, limit)


def _cap_timeline(
    dated: Sequence[TimelineItem],
    undated: Sequence[TimelineItem],
    limit: int,
) -> Timeline:
    if limit < 1:
        return Timeline(dated_omitted=len(dated), undated_omitted=len(undated))
    if len(dated) + len(undated) <= limit:
        return Timeline([*dated, *undated])

    dated_keep = list(dated[-limit:]) if len(dated) > limit else list(dated)
    room = limit - len(dated_keep)
    undated_keep = list(undated[:room])
    return Timeline(
        [*dated_keep, *undated_keep],
        dated_omitted=len(dated) - len(dated_keep),
        undated_omitted=len(undated) - len(undated_keep),
    )


def gaps(items: Sequence[TimelineItem], *, threshold_days: int = GAP_DAYS) -> List[Dict[str, str]]:
    """Intervals the corpus says nothing about, so the answer need not guess."""
    dated = [entry for entry in items if entry.timestamp]
    found: List[Dict[str, str]] = []
    for earlier, later in zip(dated, dated[1:]):
        span = _days_between(earlier.timestamp, later.timestamp)
        if span is not None and span >= threshold_days:
            found.append(
                {
                    "from": earlier.timestamp,
                    "to": later.timestamp,
                    "days": str(span),
                    "note": "No retrieved document covers this interval.",
                }
            )
    return found


def to_payload(items: Sequence[TimelineItem]) -> Dict[str, Any]:
    """The chronology as DATA for synthesis, with its own standing rule."""
    dated_omitted = int(getattr(items, "dated_omitted", 0) or 0)
    undated_omitted = int(getattr(items, "undated_omitted", 0) or 0)
    if dated_omitted or undated_omitted:
        if dated_omitted and not undated_omitted:
            left_out = (
                f"{dated_omitted} older retrieved document(s) are not listed. "
                "Do not treat the first date as the beginning of the record, "
                "and do not invent the documents that were left out. "
            )
        else:
            left_out = (
                f"{dated_omitted + undated_omitted} retrieved document(s) are not listed. "
                "Do not invent the documents that were left out. "
            )
        opening = (
            "This chronology is the newest window of what was retrieved, oldest first. "
            + left_out
        )
    else:
        opening = "This is the complete chronology retrieved for this question, oldest first. "
    rule = (
        opening
        + "Narrate only these events. Do not infer intermediate events, decisions, or "
        "values that no listed item states. Where 'gaps' reports an interval, say the "
        "record is silent rather than filling it in."
    )
    return {
        "items": [entry.to_dict() for entry in items],
        "gaps": gaps(items),
        "rule": rule,
    }


def _days_between(first: str, second: str) -> Optional[int]:
    try:
        start = datetime.strptime(first[:10], "%Y-%m-%d").date()
        end = datetime.strptime(second[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    return (end - start).days


def _get(item: Any, name: str) -> Any:
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)
