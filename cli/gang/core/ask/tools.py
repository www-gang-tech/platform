"""The complete vocabulary of actions the research loop may take. All read-only.

Multi-step research means a model gets to decide what to look at next. The
safety of that rests entirely on the *size of the vocabulary* it chooses from,
so the vocabulary is defined here, exhaustively, as typed schemas — and the
executor will only dispatch a name in this table.

Every tool:

* is **read-only**. Nothing in this module opens a file for writing, touches
  the registry, the raw store, entity records, or enrichment proposals. Index
  access goes through the same read-only SQLite connection `retrieval.py` uses.
* has a **typed schema** whose parameters are validated before execution. An
  unknown parameter is an error, not something to ignore, so a model talked
  into passing ``{"path": "/etc/passwd"}`` fails loudly.
* returns **bounded** results, with provenance on every row.
* exposes **no filesystem surface**. There is no parameter anywhere in this
  table that names a path.

The denied names in ``DENIED_TOOLS`` are listed explicitly rather than merely
omitted. A retrieved email asking for ``run_sql`` should produce a recorded
refusal that a test can assert on, not a quiet lookup miss.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from core import enrichment_state
from core.facts.model import quote_in_source

from . import affiliation as affiliation_module
from . import assignments as assignments_module
from . import timeline as timeline_module
from .plan import MAX_LIMIT, QueryPlanError, validate_plan
from .retrieval import Retriever


#: Capabilities `gang ask` must never acquire. Naming them makes the refusal
#: explicit and testable (§9).
DENIED_TOOLS = frozenset(
    {
        "run_sql",
        "execute_sql",
        "query_sql",
        "execute_shell",
        "shell",
        "bash",
        "run_command",
        "read_file",
        "read_arbitrary_file",
        "open_file",
        "list_files",
        "write_file",
        "edit_file",
        "delete_document",
        "publish",
        "deploy",
        "apply_enrichment",
        "create_entity",
        "merge_entity",
        "update_entity",
        "ingest",
        "http_get",
        "web_search",
        "fetch_url",
    }
)

MAX_TOOL_RESULTS = 12
MAX_EXCERPT_CHARS = 400
MAX_STRING_LENGTH = 200
MAX_LIST_ITEMS = 12

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SAFE_TEXT = re.compile(r"^[^\x00-\x08\x0b\x0c\x0e-\x1f]{1,200}$")

STRING = "string"
STRING_LIST = "string_list"
ID = "id"
ID_LIST = "id_list"
INTEGER = "integer"
DATE = "date"


class ToolError(ValueError):
    """Raised when a tool call is outside the supported vocabulary."""


@dataclass(frozen=True)
class Parameter:
    name: str
    type: str
    description: str
    required: bool = False
    minimum: int = 1
    maximum: int = MAX_TOOL_RESULTS
    choices: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: Tuple[Parameter, ...] = ()

    def schema(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": {
                item.name: {
                    "type": item.type,
                    "description": item.description,
                    "required": item.required,
                    **({"choices": list(item.choices)} if item.choices else {}),
                }
                for item in self.parameters
            },
        }


@dataclass(frozen=True)
class ToolResult:
    """What one tool call produced, plus where every row came from."""

    tool: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    documents: List[Dict[str, Any]] = field(default_factory=list)
    records: List[Dict[str, Any]] = field(default_factory=list)
    note: str = ""
    truncated: bool = False

    @property
    def document_ids(self) -> List[str]:
        return [str(item.get("document_id") or "") for item in self.documents]

    def trace_entry(self, reason: str = "") -> Dict[str, Any]:
        """The private, lightweight research trace (§10).

        Arguments and returned ids only. No prompts, no document bodies — a
        trace that carried source text would be a second copy of the corpus in
        a place nobody audits.
        """
        return {
            "tool": self.tool,
            "arguments": dict(self.arguments),
            "document_ids": self.document_ids,
            "record_count": len(self.records),
            "truncated": self.truncated,
            "reason": reason,
            **({"note": self.note} if self.note else {}),
        }


# ------------------------------------------------------------- the catalog

TOOLS: Tuple[ToolSpec, ...] = (
    ToolSpec(
        "search_documents",
        "Full-text and entity search over the private corpus. The primary way to find evidence.",
        (
            Parameter("text_queries", STRING_LIST, "Search terms, drawn from the question or from evidence already read."),
            Parameter("entity_ids", ID_LIST, "Restrict to documents mentioning these canonical entities."),
            Parameter("document_types", STRING_LIST, "Restrict to these document types."),
            Parameter("source_types", STRING_LIST, "Restrict to these source types, such as gmail-thread."),
            Parameter("since", DATE, "Only documents updated on or after this date (YYYY-MM-DD)."),
            Parameter("until", DATE, "Only documents updated on or before this date (YYYY-MM-DD)."),
            Parameter("order", STRING, "Ranking order.", choices=("relevance", "recency")),
            Parameter("limit", INTEGER, "Maximum documents to return.", maximum=MAX_TOOL_RESULTS),
        ),
    ),
    ToolSpec(
        "get_document",
        "Fetch one document already found, with more of its text than an excerpt shows.",
        (Parameter("document_id", ID, "The document id.", required=True),),
    ),
    ToolSpec(
        "get_document_excerpt",
        "Read the part of a document around a specific phrase, instead of the whole thing.",
        (
            Parameter("document_id", ID, "The document id.", required=True),
            Parameter("around", STRING, "Phrase to centre the excerpt on."),
            Parameter("max_excerpts", INTEGER, "How many windows to return.", maximum=5),
        ),
    ),
    ToolSpec(
        "get_document_history",
        "The immutable ingested version history of a document's source.",
        (Parameter("document_id", ID, "The document id.", required=True),),
    ),
    ToolSpec(
        "get_entity",
        "One canonical entity record: its type, aliases, and how often it is mentioned.",
        (
            Parameter("entity_id", ID, "The entity id."),
            Parameter("name", STRING, "A name or alias to resolve instead of an id."),
        ),
    ),
    ToolSpec(
        "get_entity_documents",
        "Documents that mention an entity, newest first.",
        (
            Parameter("entity_id", ID, "The entity id.", required=True),
            Parameter("limit", INTEGER, "Maximum documents.", maximum=MAX_TOOL_RESULTS),
        ),
    ),
    ToolSpec(
        "get_relationships",
        "Evidence-backed relationship assertions involving an entity.",
        (
            Parameter("entity_id", ID, "The entity id.", required=True),
            Parameter("predicate", STRING, "Restrict to one predicate."),
            Parameter("limit", INTEGER, "Maximum assertions.", maximum=MAX_TOOL_RESULTS),
        ),
    ),
    ToolSpec(
        "find_decisions",
        "Explicit decisions recorded in documents, with dates, status, and the words that "
        "record them; falls back to derived document structures. Stale entries stay marked stale.",
        (
            Parameter("topic", STRING, "Restrict to decisions about this subject."),
            Parameter("entity_id", ID, "Restrict to documents mentioning this entity."),
            Parameter("since", DATE, "Earliest decision date to include (YYYY-MM-DD)."),
            Parameter("until", DATE, "Latest decision date to include (YYYY-MM-DD)."),
            Parameter("limit", INTEGER, "Maximum decisions.", maximum=MAX_TOOL_RESULTS),
        ),
    ),
    ToolSpec(
        "find_action_items",
        "Action items recorded in derived document structures, with their owners where stated.",
        (
            Parameter("topic", STRING, "Restrict to action items mentioning this term."),
            Parameter("entity_id", ID, "Restrict to documents mentioning this entity."),
            Parameter("limit", INTEGER, "Maximum documents to draw from.", maximum=MAX_TOOL_RESULTS),
        ),
    ),
    ToolSpec(
        "find_assignments",
        "Tasks explicitly assigned to one person: owner fields, owner tables, action items, "
        "and sentences where the person is the subject of the obligation. Never attendance.",
        (
            Parameter("person", STRING, "The person's name as written, if no entity id resolves.", required=True),
            Parameter("entity_id", ID, "The person's canonical entity id, when one resolved."),
            Parameter("since", DATE, "Earliest deadline or evidence date to include (YYYY-MM-DD)."),
            Parameter("until", DATE, "Latest deadline or evidence date to include (YYYY-MM-DD)."),
            Parameter("limit", INTEGER, "Maximum tasks.", maximum=MAX_TOOL_RESULTS),
        ),
    ),
    ToolSpec(
        "find_open_questions",
        "Unresolved questions recorded in derived document structures.",
        (
            Parameter("topic", STRING, "Restrict to questions mentioning this term."),
            Parameter("entity_id", ID, "Restrict to documents mentioning this entity."),
            Parameter("limit", INTEGER, "Maximum documents to draw from.", maximum=MAX_TOOL_RESULTS),
        ),
    ),
    ToolSpec(
        "build_timeline",
        "Chronologically ordered evidence for a subject. Use for 'what changed' and history questions.",
        (
            Parameter("text_queries", STRING_LIST, "Search terms identifying the subject."),
            Parameter("entity_ids", ID_LIST, "Entities identifying the subject."),
            Parameter("since", DATE, "Earliest date to include (YYYY-MM-DD)."),
            Parameter("until", DATE, "Latest date to include (YYYY-MM-DD)."),
            Parameter("limit", INTEGER, "Maximum timeline entries.", maximum=MAX_TOOL_RESULTS),
        ),
    ),
    ToolSpec(
        "find_participants",
        "Who is involved with a topic, assembled from participation signals rather than a roster.",
        (
            Parameter("topic", STRING, "Subject to scope participation to, such as certification."),
            Parameter("entity_id", ID, "Scope to documents mentioning this entity."),
            Parameter("since", DATE, "Earliest document date to consider (YYYY-MM-DD)."),
            Parameter("until", DATE, "Latest document date to consider (YYYY-MM-DD)."),
            Parameter("limit", INTEGER, "Maximum people to return.", maximum=MAX_TOOL_RESULTS),
        ),
    ),
    ToolSpec(
        "compare_documents",
        "Put two documents side by side so their differences can be described.",
        (Parameter("document_ids", ID_LIST, "Exactly two document ids.", required=True),),
    ),
    ToolSpec(
        "compare_document_versions",
        "Compare the ingested versions of one document's source over time.",
        (Parameter("document_id", ID, "The document id.", required=True),),
    ),
)

TOOLS_BY_NAME: Dict[str, ToolSpec] = {spec.name: spec for spec in TOOLS}

ALLOWED_TOOLS = frozenset(TOOLS_BY_NAME)


def catalog() -> List[Dict[str, Any]]:
    """The tool schemas handed to the planning model."""
    return [spec.schema() for spec in TOOLS]


# ------------------------------------------------------------- the executor


class ResearchTools:
    """Executes validated tool calls against the read-only index."""

    def __init__(
        self,
        retriever: Retriever,
        *,
        registry_path: Optional[Path] = None,
        resolver: Optional[Any] = None,
        entities: Sequence[Any] = (),
        facts: Optional[Any] = None,
        max_results: int = MAX_TOOL_RESULTS,
    ):
        self.retriever = retriever
        #: The generated evidence-facts service, when one is available. Read
        #: only: nothing here builds, suppresses, or writes facts.
        self.facts = facts
        self.registry_path = Path(registry_path) if registry_path else None
        self.resolver = resolver
        #: Canonical entity records, used as the vocabulary for recognizing
        #: people and telling one organization from another.
        self.entities = list(entities)
        self.max_results = max(1, min(int(max_results), MAX_LIMIT))

    # ------------------------------------------------------------ dispatch

    def call(self, name: Any, arguments: Any = None) -> ToolResult:
        """Validate and run one tool call. Raises rather than improvising."""
        tool_name = str(name or "").strip()
        if tool_name in DENIED_TOOLS:
            raise ToolError(
                f"Tool {tool_name!r} is not available to `gang ask`, which is read-only "
                "and has no filesystem, shell, SQL, or mutation access."
            )
        spec = TOOLS_BY_NAME.get(tool_name)
        if spec is None:
            raise ToolError(
                f"Unknown research tool: {tool_name!r}. Available: " + ", ".join(sorted(ALLOWED_TOOLS))
            )

        values = _validate_arguments(spec, arguments)
        handler: Callable[[Dict[str, Any]], ToolResult] = getattr(self, f"_tool_{spec.name}")
        return handler(values)

    # -------------------------------------------------------------- search

    def _tool_search_documents(self, values: Dict[str, Any]) -> ToolResult:
        plan = self._plan(
            text_queries=values.get("text_queries") or [],
            entity_ids=values.get("entity_ids") or [],
            document_types=values.get("document_types") or [],
            source_types=values.get("source_types") or [],
            since=values.get("since", ""),
            until=values.get("until", ""),
            order=values.get("order") or "relevance",
            limit=values.get("limit") or self.max_results,
        )
        if plan.is_empty:
            return ToolResult(
                tool="search_documents",
                arguments=values,
                note="No searchable terms, entities, or filters in this call.",
            )
        rows = self.retriever.retrieve(plan)
        return ToolResult(tool="search_documents", arguments=values, documents=rows)

    def _tool_build_timeline(self, values: Dict[str, Any]) -> ToolResult:
        plan = self._plan(
            text_queries=values.get("text_queries") or [],
            entity_ids=values.get("entity_ids") or [],
            since=values.get("since", ""),
            until=values.get("until", ""),
            # Chronology needs the ends of the range, not the top of a
            # relevance ranking, so recency ordering is not optional here.
            order="recency",
            limit=values.get("limit") or self.max_results,
        )
        if plan.is_empty:
            return ToolResult(
                tool="build_timeline", arguments=values, note="No subject given for the timeline."
            )
        rows = self.retriever.retrieve(plan)
        entries = timeline_module.build_timeline(
            [{**row, "citation_id": 0, "excerpts": [_window(row.get("body") or "")]} for row in rows]
        )
        return ToolResult(
            tool="build_timeline",
            arguments=values,
            documents=rows,
            records=[entry.to_dict() for entry in entries],
            note="Ordered oldest first. Intermediate events not listed here are not in the corpus.",
        )

    # ----------------------------------------------------------- documents

    def _tool_get_document(self, values: Dict[str, Any]) -> ToolResult:
        rows = self.retriever.documents([values["document_id"]])
        if not rows:
            return ToolResult(
                tool="get_document", arguments=values, note="No such document in the index."
            )
        return ToolResult(tool="get_document", arguments=values, documents=rows)

    def _tool_get_document_excerpt(self, values: Dict[str, Any]) -> ToolResult:
        from .evidence import readable_excerpts

        rows = self.retriever.documents([values["document_id"]])
        if not rows:
            return ToolResult(
                tool="get_document_excerpt", arguments=values, note="No such document in the index."
            )
        row = rows[0]
        around = values.get("around", "")
        maximum = int(values.get("max_excerpts") or 3)
        excerpts, quality = readable_excerpts(row.get("body") or "", [around] if around else [])
        if not quality.readable:
            return ToolResult(
                tool="get_document_excerpt",
                arguments=values,
                note=f"This document's extracted text is not readable ({quality.reason}).",
            )
        return ToolResult(
            tool="get_document_excerpt",
            arguments=values,
            documents=[row],
            records=[
                _located_excerpt(row, text)
                for text in excerpts[:maximum]
            ],
            truncated=len(excerpts) > maximum,
        )

    def _tool_compare_documents(self, values: Dict[str, Any]) -> ToolResult:
        ids = values["document_ids"]
        if len(ids) != 2:
            raise ToolError("compare_documents needs exactly two document_ids")
        rows = self.retriever.documents(ids)
        if len(rows) < 2:
            return ToolResult(
                tool="compare_documents",
                arguments=values,
                documents=rows,
                note="At least one of those documents is not in the index.",
            )
        return ToolResult(
            tool="compare_documents",
            arguments=values,
            documents=rows,
            records=[
                {
                    "document_id": row["document_id"],
                    "title": row["title"],
                    "updated": row["updated"],
                    "source_type": row["source_type"],
                    "excerpt": _window(row.get("body") or ""),
                }
                for row in rows
            ],
            note="Both documents are shown in full standing. Describe differences; do not merge them.",
        )

    # ------------------------------------------------------------- history

    def _tool_get_document_history(self, values: Dict[str, Any]) -> ToolResult:
        rows = self.retriever.documents([values["document_id"]])
        if not rows:
            return ToolResult(
                tool="get_document_history", arguments=values, note="No such document in the index."
            )
        versions = self._versions(rows[0].get("source_ids") or [])
        return ToolResult(
            tool="get_document_history",
            arguments=values,
            documents=rows,
            records=versions,
            note=(
                "Ingested version history of the source. Each entry is immutable raw evidence."
                if versions
                else "No ingestion history recorded for this document's source."
            ),
        )

    def _tool_compare_document_versions(self, values: Dict[str, Any]) -> ToolResult:
        rows = self.retriever.documents([values["document_id"]])
        if not rows:
            return ToolResult(
                tool="compare_document_versions",
                arguments=values,
                note="No such document in the index.",
            )
        versions = self._versions(rows[0].get("source_ids") or [])
        if len(versions) < 2:
            return ToolResult(
                tool="compare_document_versions",
                arguments=values,
                documents=rows,
                records=versions,
                note="Only one ingested version exists, so there is nothing to compare.",
            )
        first, last = versions[0], versions[-1]
        return ToolResult(
            tool="compare_document_versions",
            arguments=values,
            documents=rows,
            records=versions,
            note=(
                f"The source changed across {len(versions)} ingested versions, from "
                f"{first.get('ingested_at', '?')} to {last.get('ingested_at', '?')}. "
                "Only the current version's text is in the index; earlier versions are "
                "recorded as immutable raw evidence and are not quoted here."
            ),
        )

    def _versions(self, source_ids: Sequence[str]) -> List[Dict[str, Any]]:
        """Version records from the ingestion registry. Read, never written."""
        if not self.registry_path or not self.registry_path.exists():
            return []
        try:
            payload = json.loads(self.registry_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        sources = payload.get("sources") if isinstance(payload, dict) else None
        if not isinstance(sources, dict):
            return []

        records: List[Dict[str, Any]] = []
        for source_id in source_ids:
            entry = sources.get(source_id)
            if not isinstance(entry, dict):
                continue
            for version in entry.get("versions") or []:
                if not isinstance(version, dict):
                    continue
                records.append(
                    {
                        "source_id": source_id,
                        "version": version.get("version"),
                        "content_hash": str(version.get("content_hash") or "")[:16],
                        "ingested_at": str(version.get("ingested_at") or ""),
                    }
                )
        return sorted(records, key=lambda item: (item["ingested_at"], str(item["version"])))[
            : self.max_results
        ]

    # ------------------------------------------------------------ entities

    def _tool_get_entity(self, values: Dict[str, Any]) -> ToolResult:
        entity_id = values.get("entity_id", "")
        name = values.get("name", "")
        if not entity_id and not name:
            raise ToolError("get_entity needs an entity_id or a name")

        if not entity_id and self.resolver is not None:
            from core.entities.resolver import AMBIGUOUS, RESOLVED

            resolution = self.resolver.resolve(name)
            if resolution.status == AMBIGUOUS:
                return ToolResult(
                    tool="get_entity",
                    arguments=values,
                    records=[
                        {"entity_id": item.entity_id, "name": item.name, "type": item.entity_type}
                        for item in resolution.candidates
                    ],
                    note=f"{name!r} is ambiguous. Do not pick one; report the ambiguity.",
                )
            if resolution.status == RESOLVED:
                entity_id = resolution.entity_id

        if not entity_id:
            return ToolResult(
                tool="get_entity", arguments=values, note=f"No canonical entity matches {name!r}."
            )

        record = self.retriever.entity(entity_id)
        if record is None:
            return ToolResult(
                tool="get_entity", arguments=values, note=f"No entity record for {entity_id!r}."
            )
        return ToolResult(tool="get_entity", arguments=values, records=[record])

    def _tool_get_entity_documents(self, values: Dict[str, Any]) -> ToolResult:
        limit = int(values.get("limit") or self.max_results)
        ids = self.retriever.entity_document_ids(values["entity_id"], limit=limit)
        rows = self.retriever.documents(ids)
        return ToolResult(
            tool="get_entity_documents",
            arguments=values,
            documents=rows,
            note=(
                "A mention means the document names this entity. It establishes nothing "
                "about roles, ownership, or how entities relate."
            ),
        )

    def _tool_get_relationships(self, values: Dict[str, Any]) -> ToolResult:
        limit = int(values.get("limit") or self.max_results)
        records = self.retriever.entity_relationships(values["entity_id"], limit=limit)
        predicate = values.get("predicate", "")
        if predicate:
            records = [item for item in records if item.get("predicate") == predicate]
        rows = self.retriever.documents(
            [item["document_id"] for item in records if item.get("document_id")][:limit]
        )
        return ToolResult(
            tool="get_relationships", arguments=values, documents=rows, records=records
        )

    def _tool_find_participants(self, values: Dict[str, Any]) -> ToolResult:
        """Assemble the people around a topic. Deterministic; bands, not titles.

        Participation is a breadth question — three appearances across two
        months is the signal — so this scans more documents than an answer
        would ever cite, and returns people rather than documents.
        """
        topic = values.get("topic", "")
        entity_id = values.get("entity_id", "")

        plan_arguments: Dict[str, Any] = {"limit": MAX_LIMIT, "order": "recency"}
        if topic:
            plan_arguments["text_queries"] = [topic]
        if entity_id:
            plan_arguments["entity_ids"] = [entity_id]
        for bound in ("since", "until"):
            if values.get(bound):
                plan_arguments[bound] = values[bound]

        plan = self._plan(**plan_arguments)
        rows = [] if plan.is_empty else self.retriever.retrieve(plan)
        if not rows:
            # No topic given, or nothing matched: fall back to the most recent
            # operating record, which is where participation actually shows.
            rows = self.retriever.recent_documents(limit=MAX_LIMIT)

        people = [record for record in self.entities if record.type == "person"]
        companies = [record for record in self.entities if record.type == "company"]
        home = [
            domain
            for record in companies
            if getattr(record, "foundational", False)
            for domain in (getattr(record, "domains", []) or [])
        ]

        participants = affiliation_module.gather(
            rows,
            people=people,
            companies=companies,
            home_domains=home,
            limit=int(values.get("limit") or self.max_results),
        )

        cited_ids: List[str] = []
        for participant in participants:
            for document_id in participant.document_ids:
                if document_id not in cited_ids:
                    cited_ids.append(document_id)

        return ToolResult(
            tool="find_participants",
            arguments=values,
            documents=self.retriever.documents(cited_ids[: self.max_results]),
            records=[participant.to_dict() for participant in participants],
            note=(
                "Bands assembled from participation, email domain, ownership language, "
                "recorded relationships, and time. Not a roster and not an org chart; "
                "any statement about someone's relationship to the company is an inference."
                if participants
                else "No participants could be identified in the documents for this topic."
            ),
        )

    # ---------------------------------------------------------- structured

    def _tool_find_decisions(self, values: Dict[str, Any]) -> ToolResult:
        derived = self._structured("decisions", "find_decisions", values)
        materialized = self._materialized_decisions(values)
        if materialized is None:
            return derived
        # Explicit statements first, then anything enrichment recorded that
        # they do not already say. Neither source replaces the other.
        known = {_statement_key(record["text"]) for record in materialized.records}
        extra = [record for record in derived.records if _statement_key(record.get("text") or "") not in known]
        limit = int(values.get("limit") or self.max_results)
        records = (materialized.records + extra)[:limit]
        cited = [
            document_id
            for record in records
            for document_id in (record.get("document_ids") or [record.get("document_id")])
            if document_id
        ]
        return ToolResult(
            tool="find_decisions",
            arguments=values,
            documents=self.retriever.documents(list(dict.fromkeys(cited))[:MAX_LIMIT]),
            records=records,
            truncated=materialized.truncated or derived.truncated or len(materialized.records) + len(extra) > limit,
            note=materialized.note
            + (" Derived decisions from document enrichment follow them." if extra else ""),
        )

    def _materialized_decisions(self, values: Dict[str, Any]) -> Optional[ToolResult]:
        """Explicit decision statements from the generated facts store.

        Each one is re-verified against the current text of the document it
        cites before it is returned: a decision whose words are no longer in
        its source is stale and is dropped, not shown. ``None`` means there
        were none, and the derived-structure fallback should run.
        """
        if self.facts is None:
            return None
        limit = int(values.get("limit") or self.max_results)
        try:
            found = self.facts.decisions(
                topic=values.get("topic", ""),
                since=values.get("since", ""),
                until=values.get("until", ""),
                limit=MAX_LIMIT,
            )
        except Exception:  # noqa: BLE001 - a generated layer never fails an answer
            return None

        allowed: Optional[set] = None
        if values.get("entity_id"):
            allowed = set(self.retriever.entity_document_ids(values["entity_id"], limit=MAX_LIMIT))

        candidates = [
            record
            for record in found.get("decisions") or []
            if allowed is None or set(record.get("document_ids") or []) & allowed
        ]
        wanted: List[str] = []
        for record in candidates:
            for document_id in record.get("document_ids") or []:
                if document_id not in wanted:
                    wanted.append(document_id)
        bodies = {row["document_id"]: row for row in self.retriever.documents(wanted)}

        records: List[Dict[str, Any]] = []
        cited: List[str] = []
        for record in candidates:
            verified = [
                document_id
                for document_id in record.get("document_ids") or []
                if document_id in bodies
                and quote_in_source(record.get("text") or "", bodies[document_id].get("body") or "")
            ]
            if not verified:
                continue
            primary = bodies[verified[0]]
            records.append(
                {
                    "text": record["text"],
                    "document_id": verified[0],
                    "document_ids": verified,
                    "title": primary.get("title") or record.get("document_title") or "",
                    "date": record.get("date") or "",
                    "status": record.get("status") or "",
                    "context": record.get("context") or "",
                    "source_class": record.get("source_class") or "",
                    "rule": record.get("rule") or "",
                    "decision_id": record.get("decision_id") or "",
                    "stale": False,
                    "generated": True,
                    "materialized": True,
                }
            )
            for document_id in verified:
                if document_id not in cited:
                    cited.append(document_id)
            if len(records) >= limit:
                break

        if not records:
            return None
        return ToolResult(
            tool="find_decisions",
            arguments=values,
            documents=self.retriever.documents(cited[:MAX_LIMIT]),
            records=records,
            truncated=len(candidates) > len(records),
            note=(
                "Explicit decision statements materialized from the cited documents: generated "
                "and rebuildable, not a canonical register. Each was re-verified against its source."
            ),
        )

    def _tool_find_action_items(self, values: Dict[str, Any]) -> ToolResult:
        return self._structured("action_items", "find_action_items", values)

    def _tool_find_assignments(self, values: Dict[str, Any]) -> ToolResult:
        """Work the evidence explicitly assigns to one person. Deterministic.

        Reads widely — the person's name across the newest documents, and
        alongside the words owner lists and task mail use — because a task list
        is a breadth question. Returns tasks, and only the documents those
        tasks cite.
        """
        person = self._assignment_person(values)
        rows: List[Dict[str, Any]] = []
        seen = set()
        for plan in self._assignment_plans(person):
            for row in self.retriever.retrieve(plan):
                if row["document_id"] not in seen:
                    seen.add(row["document_id"])
                    rows.append(row)
        # Structured action items live in enrichment, whether or not the body
        # happens to mention the owner in a searchable way.
        for row in self.retriever.enriched_documents(limit=50):
            if row["document_id"] not in seen:
                seen.add(row["document_id"])
                rows.append(row)

        everything = assignments_module.gather(
            rows,
            person,
            since=values.get("since", ""),
            until=values.get("until", ""),
        )
        found = everything[: int(values.get("limit") or self.max_results)]

        # The primary source of every task first, then corroboration, so the
        # document bound never costs a task its only citation.
        cited: List[str] = []
        depth = max((len(item.document_ids) for item in found), default=0)
        for index in range(depth):
            for item in found:
                if index < len(item.document_ids) and item.document_ids[index] not in cited:
                    cited.append(item.document_ids[index])

        return ToolResult(
            tool="find_assignments",
            arguments=values,
            documents=self.retriever.documents(cited[: self.max_results]),
            # Always one record, even when empty: "nothing is assigned to X"
            # is an answer about X, not an absence of evidence.
            records=[
                {
                    "person": person.to_dict(),
                    "assignments": [item.to_dict() for item in found],
                    "total": len(everything),
                    "since": values.get("since", ""),
                    "until": values.get("until", ""),
                }
            ],
            note=(
                "Tasks the evidence explicitly assigns to this person: owner fields, owner "
                "tables, derived action items, and sentences naming them as the subject of "
                "the obligation. Attendance and mentions are not assignments."
                if found
                else "No task in the evidence is explicitly assigned to this person."
            ),
        )

    def _assignment_person(self, values: Dict[str, Any]) -> "assignments_module.Person":
        entity_id = values.get("entity_id", "")
        record = self.retriever.entity(entity_id) if entity_id else None
        if record:
            return assignments_module.person_from(
                record["name"],
                aliases=record.get("aliases") or [],
                resolved=True,
                entity_id=record["entity_id"],
            )
        return assignments_module.person_from(values["person"])

    def _assignment_plans(self, person: "assignments_module.Person"):
        plans = []
        for form in person.forms[:3]:
            plans.append(self._scan_plan([form], "recency"))
            for cue in assignments_module.SEARCH_CUES:
                plans.append(self._scan_plan([form, cue], "relevance"))
        return plans

    def _scan_plan(self, text_queries: List[str], order: str):
        """A retrieval plan at the full index bound, for breadth scans."""
        try:
            return validate_plan(
                {
                    "version": "1",
                    "query": "assignment scan",
                    "text_queries": text_queries,
                    "order": order,
                    "limit": MAX_LIMIT,
                }
            )
        except QueryPlanError as exc:
            raise ToolError(str(exc)) from exc

    def _tool_find_open_questions(self, values: Dict[str, Any]) -> ToolResult:
        return self._structured("unresolved_questions", "find_open_questions", values)

    def _structured(self, field_name: str, tool_name: str, values: Dict[str, Any]) -> ToolResult:
        """Read one derived structure across documents, preserving staleness.

        The `stale` flag travels with each entry rather than being applied as a
        filter. A stale decision is still the last thing recorded; dropping it
        would silently answer "nothing was decided" (§13).
        """
        limit = int(values.get("limit") or self.max_results)
        topic = (values.get("topic") or "").strip().casefold()
        entity_id = values.get("entity_id", "")

        allowed: Optional[set] = None
        if entity_id:
            allowed = set(self.retriever.entity_document_ids(entity_id, limit=MAX_LIMIT))

        records: List[Dict[str, Any]] = []
        document_ids: List[str] = []
        for row in self.retriever.enriched_documents(limit=50):
            if allowed is not None and row["document_id"] not in allowed:
                continue
            entries = row["enrichment"].get(field_name)
            if not isinstance(entries, list) or not entries:
                continue
            stale = row["enrichment_status"] == enrichment_state.STALE
            for entry in entries:
                text = _entry_text(entry)
                if not text:
                    continue
                if topic and topic not in text.casefold() and topic not in row["title"].casefold():
                    continue
                records.append(
                    {
                        "text": text[:MAX_EXCERPT_CHARS],
                        "document_id": row["document_id"],
                        "title": row["title"],
                        "date": (row["updated"] or row["created"])[:10],
                        "enrichment_status": row["enrichment_status"],
                        "stale": stale,
                        **(
                            {
                                "stale_warning": (
                                    "Derived from an older version of this document. Not "
                                    "current fact; check the document's own text."
                                )
                            }
                            if stale
                            else {}
                        ),
                    }
                )
            if row["document_id"] not in document_ids:
                document_ids.append(row["document_id"])
            if len(records) >= limit:
                break

        rows = self.retriever.documents(document_ids[:limit])
        return ToolResult(
            tool=tool_name,
            arguments=values,
            documents=rows,
            records=records[:limit],
            truncated=len(records) > limit,
            note=(
                f"These are derived {field_name.replace('_', ' ')} extracted from documents, "
                "not a canonical register. Entries marked stale describe an older version of "
                "their document."
                if records
                else f"No derived {field_name.replace('_', ' ')} matched."
            ),
        )

    # ------------------------------------------------------------- helpers

    def _plan(self, **kwargs: Any):
        since = kwargs.pop("since", "") or ""
        until = kwargs.pop("until", "") or ""
        date_range = {"field": "updated", "start": since, "end": until} if (since or until) else None
        payload = {
            "version": "1",
            # The plan's `query` is provenance for the trace, never text sent
            # to FTS; retrieval reads `text_queries`.
            "query": kwargs.get("query") or "research tool call",
            "date_range": date_range,
            **{key: value for key, value in kwargs.items() if key != "query"},
        }
        payload["limit"] = max(1, min(int(payload.get("limit") or self.max_results), self.max_results))
        try:
            return validate_plan(payload)
        except QueryPlanError as exc:
            raise ToolError(str(exc)) from exc


# --------------------------------------------------------------- validation


def _statement_key(text: str) -> str:
    return re.sub(r"[^\w]+", " ", str(text or "").casefold()).strip()



def _validate_arguments(spec: ToolSpec, arguments: Any) -> Dict[str, Any]:
    """Type-check a tool call's arguments against its schema.

    Unknown keys are rejected rather than dropped. Silently ignoring an extra
    parameter is how an unsupported capability gets to look like it worked.
    """
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ToolError(f"{spec.name} arguments must be an object")

    known = {item.name for item in spec.parameters}
    unknown = sorted(set(arguments) - known)
    if unknown:
        raise ToolError(
            f"Unsupported parameter(s) for {spec.name}: " + ", ".join(unknown)
        )

    values: Dict[str, Any] = {}
    for parameter in spec.parameters:
        raw = arguments.get(parameter.name)
        if raw is None or raw == "" or raw == []:
            if parameter.required:
                raise ToolError(f"{spec.name} requires {parameter.name}")
            continue
        values[parameter.name] = _coerce(spec.name, parameter, raw)
    return values


def _coerce(tool_name: str, parameter: Parameter, raw: Any) -> Any:
    if parameter.type == INTEGER:
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ToolError(f"{tool_name}.{parameter.name} must be a number")
        return max(parameter.minimum, min(int(raw), parameter.maximum))

    if parameter.type == DATE:
        text = _string(tool_name, parameter, raw)
        if not _DATE.fullmatch(text):
            raise ToolError(f"{tool_name}.{parameter.name} must be YYYY-MM-DD, got {text!r}")
        return text

    if parameter.type == ID:
        text = _string(tool_name, parameter, raw)
        if not _SAFE_ID.fullmatch(text):
            raise ToolError(f"{tool_name}.{parameter.name} is not a valid identifier: {text!r}")
        return text

    if parameter.type == STRING:
        text = _string(tool_name, parameter, raw)
        if parameter.choices and text not in parameter.choices:
            raise ToolError(
                f"{tool_name}.{parameter.name} must be one of: " + ", ".join(parameter.choices)
            )
        return text

    if parameter.type in (STRING_LIST, ID_LIST):
        if not isinstance(raw, list):
            raise ToolError(f"{tool_name}.{parameter.name} must be a list of strings")
        pattern = _SAFE_ID if parameter.type == ID_LIST else _SAFE_TEXT
        result: List[str] = []
        for item in raw[:MAX_LIST_ITEMS]:
            if not isinstance(item, str):
                raise ToolError(f"{tool_name}.{parameter.name} must be a list of strings")
            text = item.strip()[:MAX_STRING_LENGTH]
            if not text:
                continue
            if not pattern.fullmatch(text):
                raise ToolError(f"{tool_name}.{parameter.name} contains an unsupported value: {text!r}")
            if text not in result:
                result.append(text)
        return result

    raise ToolError(f"Unsupported parameter type: {parameter.type}")


def _string(tool_name: str, parameter: Parameter, raw: Any) -> str:
    if not isinstance(raw, str):
        raise ToolError(f"{tool_name}.{parameter.name} must be a string")
    text = raw.strip()[:MAX_STRING_LENGTH]
    if not _SAFE_TEXT.fullmatch(text):
        raise ToolError(f"{tool_name}.{parameter.name} contains unsupported characters")
    return text


def _entry_text(entry: Any) -> str:
    """Derived structures are lists of strings or of small objects."""
    if isinstance(entry, str):
        return entry.strip()
    if isinstance(entry, dict):
        for key in ("text", "decision", "action", "item", "question", "summary"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                owner = entry.get("owner") or entry.get("assignee")
                suffix = f" (owner: {owner})" if isinstance(owner, str) and owner.strip() else ""
                return value.strip() + suffix
    return ""


def _located_excerpt(row: Dict[str, Any], text: str) -> Dict[str, Any]:
    """An excerpt plus where in the document it came from.

    A reader following a citation into a long Gmail thread needs somewhere to
    look, so an expanded excerpt carries its offset and range into the
    document body (§14).

    Offsets are into the whitespace-normalized body, which is the form the
    excerpt was cut from. Section and heading identifiers are deliberately
    absent rather than guessed: the generated index stores document text with
    Markdown structure already flattened, so there is no heading here to name,
    and reaching past the index to the canonical file would give a research
    tool the filesystem access this layer exists to withhold.
    """
    normalized, _ = _normalize_with_offsets(row.get("body") or "")
    probe = text.strip().lstrip(". ").rstrip(". ")
    position = normalized.find(probe) if probe else -1

    entry: Dict[str, Any] = {"document_id": row["document_id"], "excerpt": text}
    if position < 0:
        return entry

    entry["start"] = position
    entry["end"] = position + len(probe)
    entry["range"] = f"{position}-{position + len(probe)}"
    return entry


def _normalize_with_offsets(body: str) -> Tuple[str, List[int]]:
    r"""Collapse whitespace, keeping each kept character's original offset.

    Equivalent to ``re.sub(r"\s+", " ", body).strip()``, but it also returns
    the raw index every surviving character came from, so an offset into an
    excerpt can be mapped back to a position in the stored document rather
    than estimated.
    """
    characters: List[str] = []
    offsets: List[int] = []
    in_space = False
    for index, char in enumerate(body or ""):
        if char.isspace():
            if not in_space:
                characters.append(" ")
                offsets.append(index)
                in_space = True
        else:
            characters.append(char)
            offsets.append(index)
            in_space = False

    first = 0
    last = len(characters)
    while first < last and characters[first] == " ":
        first += 1
    while last > first and characters[last - 1] == " ":
        last -= 1
    return "".join(characters[first:last]), offsets[first:last]


def _window(body: str, limit: int = MAX_EXCERPT_CHARS) -> str:
    text = re.sub(r"\s+", " ", body or "").strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."
