"""The typed query plan: the only thing a model may hand to the retriever.

A plan is inert, versioned, schema-validated JSON. Deterministic code turns it
into parameter-bound SQL; the plan itself can express nothing else. There is no
field for raw SQL, no field for a path, and no field that mutates. Anything a
model returns outside this vocabulary is rejected rather than ignored, so a
prompt injection that tries to widen the plan fails loudly instead of quietly
succeeding.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


PLAN_VERSION = "1"

#: Top-level keys. Anything else is a rejection, not a warning.
PLAN_FIELDS = {
    "version",
    "query",
    "text_queries",
    "entity_ids",
    "relationship_filters",
    "document_types",
    "source_types",
    "visibility",
    "date_range",
    "enrichment_status",
    "order",
    "limit",
}

DATE_RANGE_FIELDS = {"field", "start", "end"}
DATE_FIELDS = ("updated", "created")

RELATIONSHIP_FILTER_FIELDS = {"predicate", "entity_id", "direction"}
DIRECTIONS = ("any", "outbound", "inbound")

ORDERS = ("relevance", "recency")

VISIBILITIES = ("private", "public")

#: Open-corpus searches stay small so a loose question cannot dump the vault.
DEFAULT_LIMIT = 8
MAX_LIMIT = 25

#: An entity plus an explicit date window is already a slice, not a ranking
#: problem. Return every matching document in that window, up to the same cap
#: a single retrieval pass already uses (`PASS_LIMIT` in retrieval.py).
SLICE_LIMIT = 200

_DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ENTITY_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9 _.:/@+-]{1,128}$")

MAX_TEXT_QUERIES = 12
MAX_TEXT_QUERY_LENGTH = 200
MAX_LIST_ITEMS = 25


class QueryPlanError(ValueError):
    """Raised when a proposed plan is outside the supported vocabulary."""


@dataclass(frozen=True)
class DateRange:
    field: str = "updated"
    start: str = ""
    end: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"field": self.field, "start": self.start, "end": self.end}

    @property
    def empty(self) -> bool:
        return not self.start and not self.end


@dataclass(frozen=True)
class RelationshipFilter:
    predicate: str = ""
    entity_id: str = ""
    direction: str = "any"

    def to_dict(self) -> Dict[str, str]:
        return {"predicate": self.predicate, "entity_id": self.entity_id, "direction": self.direction}


@dataclass(frozen=True)
class QueryPlan:
    query: str
    version: str = PLAN_VERSION
    text_queries: List[str] = field(default_factory=list)
    entity_ids: List[str] = field(default_factory=list)
    relationship_filters: List[RelationshipFilter] = field(default_factory=list)
    document_types: List[str] = field(default_factory=list)
    source_types: List[str] = field(default_factory=list)
    visibility: Optional[str] = None
    date_range: Optional[DateRange] = None
    enrichment_status: List[str] = field(default_factory=list)
    order: str = "relevance"
    limit: int = DEFAULT_LIMIT

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "query": self.query,
            "text_queries": list(self.text_queries),
            "entity_ids": list(self.entity_ids),
            "relationship_filters": [item.to_dict() for item in self.relationship_filters],
            "document_types": list(self.document_types),
            "source_types": list(self.source_types),
            "visibility": self.visibility,
            "date_range": self.date_range.to_dict() if self.date_range else None,
            "enrichment_status": list(self.enrichment_status),
            "order": self.order,
            "limit": self.limit,
        }

    @property
    def is_empty(self) -> bool:
        """A plan with no retrieval signal at all cannot select evidence."""
        return not (
            self.text_queries
            or self.entity_ids
            or self.relationship_filters
            or self.document_types
            or self.source_types
            or (self.date_range and not self.date_range.empty)
        )

    @property
    def is_scoped_slice(self) -> bool:
        """Named entity inside an explicit date window — enumerate, don't rank-cut."""
        return is_scoped_slice(self.entity_ids, self.date_range)


def validate_plan(value: Any) -> QueryPlan:
    """Schema-validate an untrusted plan object into a `QueryPlan`."""
    if not isinstance(value, dict):
        raise QueryPlanError("Query plan must be an object")

    unknown = sorted(set(value) - PLAN_FIELDS)
    if unknown:
        raise QueryPlanError("Unsupported query plan field(s): " + ", ".join(unknown))

    version = _text(value.get("version")) or PLAN_VERSION
    if version != PLAN_VERSION:
        raise QueryPlanError(f"Unsupported query plan version: {version}")

    query = _text(value.get("query"))
    if not query:
        raise QueryPlanError("Query plan requires a non-empty query")

    order = _text(value.get("order")) or "relevance"
    if order not in ORDERS:
        raise QueryPlanError(f"Unsupported order: {order}")

    visibility = _text(value.get("visibility")).lower() or None
    if visibility is not None and visibility not in VISIBILITIES:
        raise QueryPlanError(f"Unsupported visibility: {visibility}")

    return QueryPlan(
        version=version,
        query=query,
        text_queries=_text_queries(value.get("text_queries")),
        entity_ids=_id_list(value.get("entity_ids"), "entity_ids", _ENTITY_ID_PATTERN),
        relationship_filters=_relationship_filters(value.get("relationship_filters")),
        document_types=_id_list(value.get("document_types"), "document_types", _IDENTIFIER_PATTERN, lower=True),
        source_types=_id_list(value.get("source_types"), "source_types", _IDENTIFIER_PATTERN, lower=True),
        visibility=visibility,
        date_range=_date_range(value.get("date_range")),
        enrichment_status=_enrichment_status(value.get("enrichment_status")),
        order=order,
        limit=_limit(value.get("limit"), cap=_limit_cap(value)),
    )


def _text_queries(value: Any) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise QueryPlanError("text_queries must be a list of strings")
    result: List[str] = []
    for item in value:
        if not isinstance(item, str):
            raise QueryPlanError("text_queries must be a list of strings")
        text = item.strip()
        if not text:
            continue
        if len(text) > MAX_TEXT_QUERY_LENGTH:
            raise QueryPlanError("text_queries entries are limited to "
                                 f"{MAX_TEXT_QUERY_LENGTH} characters")
        if text not in result:
            result.append(text)
    if len(result) > MAX_TEXT_QUERIES:
        raise QueryPlanError(f"text_queries is limited to {MAX_TEXT_QUERIES} entries")
    return result


def _id_list(value: Any, field_name: str, pattern: re.Pattern, *, lower: bool = False) -> List[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise QueryPlanError(f"{field_name} must be a list of strings")
    result: List[str] = []
    for item in value:
        if not isinstance(item, str):
            raise QueryPlanError(f"{field_name} must be a list of strings")
        text = item.strip()
        if not text:
            continue
        if lower:
            text = text.lower()
        if not pattern.fullmatch(text):
            raise QueryPlanError(f"Unsupported value in {field_name}: {text!r}")
        if text not in result:
            result.append(text)
    if len(result) > MAX_LIST_ITEMS:
        raise QueryPlanError(f"{field_name} is limited to {MAX_LIST_ITEMS} entries")
    return result


def _relationship_filters(value: Any) -> List[RelationshipFilter]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise QueryPlanError("relationship_filters must be a list of objects")
    result: List[RelationshipFilter] = []
    for item in value:
        if not isinstance(item, dict):
            raise QueryPlanError("relationship_filters must be a list of objects")
        unknown = sorted(set(item) - RELATIONSHIP_FILTER_FIELDS)
        if unknown:
            raise QueryPlanError("Unsupported relationship filter field(s): " + ", ".join(unknown))
        predicate = _text(item.get("predicate"))
        entity_id = _text(item.get("entity_id"))
        direction = _text(item.get("direction")) or "any"
        if direction not in DIRECTIONS:
            raise QueryPlanError(f"Unsupported relationship direction: {direction}")
        if predicate and not _IDENTIFIER_PATTERN.fullmatch(predicate):
            raise QueryPlanError(f"Unsupported relationship predicate: {predicate!r}")
        if entity_id and not _ENTITY_ID_PATTERN.fullmatch(entity_id):
            raise QueryPlanError(f"Unsupported relationship entity_id: {entity_id!r}")
        if not predicate and not entity_id:
            raise QueryPlanError("relationship_filters entries need a predicate or an entity_id")
        candidate = RelationshipFilter(predicate=predicate, entity_id=entity_id, direction=direction)
        if candidate not in result:
            result.append(candidate)
    if len(result) > MAX_LIST_ITEMS:
        raise QueryPlanError(f"relationship_filters is limited to {MAX_LIST_ITEMS} entries")
    return result


def _date_range(value: Any) -> Optional[DateRange]:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise QueryPlanError("date_range must be an object")
    unknown = sorted(set(value) - DATE_RANGE_FIELDS)
    if unknown:
        raise QueryPlanError("Unsupported date_range field(s): " + ", ".join(unknown))

    date_field = _text(value.get("field")) or "updated"
    if date_field not in DATE_FIELDS:
        raise QueryPlanError(f"Unsupported date_range field: {date_field}")

    start = _text(value.get("start"))
    end = _text(value.get("end"))
    for label, bound in (("start", start), ("end", end)):
        if bound and not _DATE_PATTERN.fullmatch(bound):
            raise QueryPlanError(f"date_range {label} must be YYYY-MM-DD, got {bound!r}")
    if start and end and start > end:
        raise QueryPlanError("date_range start must not be after end")
    if not start and not end:
        return None
    return DateRange(field=date_field, start=start, end=end)


def _enrichment_status(value: Any) -> List[str]:
    from core import enrichment_state

    if value is None:
        return []
    if not isinstance(value, list):
        raise QueryPlanError("enrichment_status must be a list of strings")
    result: List[str] = []
    for item in value:
        text = _text(item).lower()
        if not text:
            continue
        if text not in enrichment_state.STATUSES:
            raise QueryPlanError(f"Unsupported enrichment_status: {text}")
        if text not in result:
            result.append(text)
    return result


def is_scoped_slice(entity_ids: Optional[Sequence[str]], date_range: Any) -> bool:
    """True when retrieval can enumerate a named entity inside a date window.

    "Dorf Nelson from 2026" is that kind of question: the bound is the slice
    itself (every invoice, thread, attachment in the window), not a top-k
    ranking cut. An open search with no entity still cannot request the vault.
    """
    if not entity_ids:
        return False
    if isinstance(date_range, DateRange):
        return not date_range.empty
    if isinstance(date_range, dict):
        return bool(date_range.get("start") or date_range.get("end"))
    return False


def _limit_cap(value: Dict[str, Any]) -> int:
    if is_scoped_slice(value.get("entity_ids") or [], value.get("date_range")):
        return SLICE_LIMIT
    return MAX_LIMIT


def _limit(value: Any, *, cap: int = MAX_LIMIT) -> int:
    if value is None:
        return DEFAULT_LIMIT
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QueryPlanError("limit must be a number")
    return max(1, min(int(value), cap))


def _text(value: Any) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise QueryPlanError(f"Expected a string, got {type(value).__name__}")
    return value.strip()
