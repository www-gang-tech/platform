"""Execute a typed query plan against the generated SQLite index. Read only.

Every statement here is built from constants and parameter placeholders. Plan
values are bound, never interpolated, and the connection is opened in SQLite's
read-only mode, so a malicious plan value cannot reach DDL or DML even if plan
validation were somehow bypassed.

Ranking is deterministic and explainable. A document earns a place by how many
*kinds* of signal it satisfies — full-text, entity, relationship, metadata —
with BM25 and recency breaking ties inside a tier. The per-item `signals` are
reported verbatim as counts. Nothing here produces a number that looks like a
probability, because nothing here knows one.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .plan import QueryPlan


#: BM25 rank for a document that never matched full-text at all. Real bm25()
#: values are negative, so this sorts last without pretending to be a score.
NO_TEXT_RANK = 1e9

#: Cap on rows pulled from any single retrieval pass before ranking.
PASS_LIMIT = 200

#: Cap on alias forms carried per entity, so the bundle stays small.
MAX_ALIAS_FORMS = 8

#: The document projection every hydrate and lookup shares, so a column added
#: here reaches retrieval and the research tools together.
DOCUMENT_SELECT = """
    SELECT document_id, type, source_type, title, body, visibility, status,
           created, updated, source_ids, tags, people, companies, projects,
           content_hash, content_trust, enrichment_status, enrichment
    FROM documents
"""

#: Columns `ask` needs that older index builds do not have. The index is
#: disposable and rebuilt from canonical Markdown, so the fix is always the
#: same: rebuild it.
REQUIRED_DOCUMENT_COLUMNS = ("source_type", "content_trust", "enrichment_status", "enrichment")


class RetrievalError(RuntimeError):
    """Raised when the generated index is missing or unreadable."""


@dataclass
class Candidate:
    document_id: str
    text_rank: float = NO_TEXT_RANK
    text_term_hits: int = 0
    entity_matches: int = 0
    relationship_matches: int = 0
    metadata_match: bool = False
    matched_entity_ids: List[str] = field(default_factory=list)
    matched_relationship_ids: List[str] = field(default_factory=list)

    @property
    def signal_classes(self) -> int:
        return sum(
            1
            for value in (
                self.text_term_hits > 0,
                self.entity_matches > 0,
                self.relationship_matches > 0,
                self.metadata_match,
            )
            if value
        )

    def signals(self) -> Dict[str, Any]:
        return {
            "signal_classes": self.signal_classes,
            "text_match": self.text_term_hits > 0,
            "text_term_hits": self.text_term_hits,
            "text_rank": None if self.text_rank >= NO_TEXT_RANK else round(self.text_rank, 4),
            "entity_matches": self.entity_matches,
            "relationship_matches": self.relationship_matches,
            "metadata_match": self.metadata_match,
            "matched_entity_ids": list(self.matched_entity_ids),
            "matched_relationship_ids": list(self.matched_relationship_ids),
        }


class Retriever:
    """Runs a validated plan. Opens the index read-only and never writes."""

    def __init__(self, database_path: Path | str):
        self.database_path = Path(database_path)

    def connect(self) -> sqlite3.Connection:
        if not self.database_path.exists():
            raise RetrievalError(
                f"Private knowledge index not found: {self.database_path}. Run: gang index build"
            )
        uri = f"file:{self.database_path.as_posix()}?mode=ro"
        connection = sqlite3.connect(uri, uri=True)
        connection.row_factory = sqlite3.Row
        _assert_supported_schema(connection)
        return connection

    def vocabulary(self) -> Dict[str, List[str]]:
        """Document and source types present in the corpus, for plan sanitizing."""
        with closing(self.connect()) as connection:
            types = [
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT lower(type) FROM documents WHERE type != '' ORDER BY 1"
                )
            ]
            sources = [
                row[0]
                for row in connection.execute(
                    "SELECT DISTINCT lower(source_type) FROM documents WHERE source_type != '' ORDER BY 1"
                )
            ]
        return {"document_types": types, "source_types": sources}

    def retrieve(self, plan: QueryPlan) -> List[Dict[str, Any]]:
        """Return the bounded, ranked evidence rows this plan selects."""
        with closing(self.connect()) as connection:
            candidates: Dict[str, Candidate] = {}
            self._text_pass(connection, plan, candidates)
            self._entity_pass(connection, plan, candidates)
            self._relationship_pass(connection, plan, candidates)
            if not candidates and _has_metadata_filter(plan):
                self._metadata_pass(connection, plan, candidates)

            ordered = self._rank(connection, plan, _prune_weak_text_only(plan, candidates))
            return self._hydrate(connection, plan, ordered[: plan.limit])

    # ------------------------------------------------------------- passes

    def _text_pass(self, connection, plan: QueryPlan, candidates: Dict[str, Candidate]) -> None:
        """One indexed query per term, so term coverage is a countable signal.

        A single OR query would say only "something matched". Matching three of
        the question's terms is much stronger evidence than matching one, and
        `text_term_hits` is what makes that difference visible to ranking and
        to the answer.
        """
        if not plan.text_queries:
            return
        where, params = _filter_clause(plan)
        sql = f"""
            SELECT d.document_id AS document_id,
                   bm25(documents_fts, 4.0, 1.0, 2.0) AS rank
            FROM documents_fts
            JOIN documents d ON d.rowid = documents_fts.rowid
            WHERE documents_fts MATCH ?{where}
            ORDER BY rank ASC, d.document_id ASC
            LIMIT ?
        """
        for term in plan.text_queries:
            match = fts_match_expression([term])
            try:
                rows = connection.execute(sql, [match, *params, PASS_LIMIT]).fetchall()
            except sqlite3.OperationalError:
                # A term the FTS tokenizer rejects narrows results; it must not
                # take down the whole query.
                continue
            for row in rows:
                candidate = candidates.setdefault(row["document_id"], Candidate(row["document_id"]))
                candidate.text_term_hits += 1
                candidate.text_rank = min(candidate.text_rank, float(row["rank"]))

    def _entity_pass(self, connection, plan: QueryPlan, candidates: Dict[str, Candidate]) -> None:
        if not plan.entity_ids:
            return
        placeholders = ", ".join("?" for _ in plan.entity_ids)
        where, params = _filter_clause(plan)
        rows = connection.execute(
            f"""
            SELECT m.document_id AS document_id,
                   m.entity_id AS entity_id
            FROM document_entity_mentions m
            JOIN documents d ON d.document_id = m.document_id
            WHERE m.entity_id IN ({placeholders}){where}
            ORDER BY m.document_id ASC, m.entity_id ASC
            LIMIT ?
            """,
            [*plan.entity_ids, *params, PASS_LIMIT],
        ).fetchall()
        for row in rows:
            candidate = candidates.setdefault(row["document_id"], Candidate(row["document_id"]))
            if row["entity_id"] not in candidate.matched_entity_ids:
                candidate.matched_entity_ids.append(row["entity_id"])
                candidate.entity_matches += 1

    def _relationship_pass(self, connection, plan: QueryPlan, candidates: Dict[str, Candidate]) -> None:
        """Relationships widen recall; they never stand in for a document."""
        clauses: List[str] = []
        params: List[Any] = []

        for item in plan.relationship_filters:
            parts = ["r.status = 'active'"]
            if item.predicate:
                parts.append("r.predicate = ?")
                params.append(item.predicate)
            if item.entity_id:
                if item.direction == "outbound":
                    parts.append("r.subject_entity_id = ?")
                    params.append(item.entity_id)
                elif item.direction == "inbound":
                    parts.append("r.object_entity_id = ?")
                    params.append(item.entity_id)
                else:
                    parts.append("(r.subject_entity_id = ? OR r.object_entity_id = ?)")
                    params.extend([item.entity_id, item.entity_id])
            clauses.append("(" + " AND ".join(parts) + ")")

        if plan.entity_ids:
            placeholders = ", ".join("?" for _ in plan.entity_ids)
            clauses.append(
                f"(r.status = 'active' AND (r.subject_entity_id IN ({placeholders})"
                f" OR r.object_entity_id IN ({placeholders})))"
            )
            params.extend(list(plan.entity_ids) * 2)

        if not clauses:
            return

        where, filter_params = _filter_clause(plan)
        rows = connection.execute(
            f"""
            SELECT r.document_id AS document_id,
                   r.relationship_id AS relationship_id
            FROM relationships r
            JOIN documents d ON d.document_id = r.document_id
            WHERE ({" OR ".join(clauses)}){where}
            ORDER BY r.document_id ASC, r.relationship_id ASC
            LIMIT ?
            """,
            [*params, *filter_params, PASS_LIMIT],
        ).fetchall()
        for row in rows:
            candidate = candidates.setdefault(row["document_id"], Candidate(row["document_id"]))
            if row["relationship_id"] not in candidate.matched_relationship_ids:
                candidate.matched_relationship_ids.append(row["relationship_id"])
                candidate.relationship_matches += 1

    def _metadata_pass(self, connection, plan: QueryPlan, candidates: Dict[str, Candidate]) -> None:
        """Last resort: the plan is pure filters, so the filters are the query."""
        where, params = _filter_clause(plan)
        if not where:
            return
        rows = connection.execute(
            f"""
            SELECT d.document_id AS document_id
            FROM documents d
            WHERE 1 = 1{where}
            ORDER BY {_recency_expression()} DESC, d.document_id ASC
            LIMIT ?
            """,
            [*params, PASS_LIMIT],
        ).fetchall()
        for row in rows:
            candidate = candidates.setdefault(row["document_id"], Candidate(row["document_id"]))
            candidate.metadata_match = True

    # -------------------------------------------------------------- rank

    def _rank(self, connection, plan: QueryPlan, candidates: Dict[str, Candidate]) -> List[Candidate]:
        """Order by how many kinds of signal matched, then break ties.

        `recency_rank` is 0 for the newest candidate, so every component of the
        sort key ascends and the key stays readable.
        """
        if not candidates:
            return []
        recency_rank = self._recency_rank(connection, sorted(candidates))

        def by_relevance(item: Candidate):
            return (
                -item.signal_classes,
                -item.entity_matches,
                -item.relationship_matches,
                -item.text_term_hits,
                item.text_rank,
                recency_rank[item.document_id],
                item.document_id,
            )

        def by_recency(item: Candidate):
            return (
                recency_rank[item.document_id],
                -item.signal_classes,
                -item.entity_matches,
                -item.text_term_hits,
                item.text_rank,
                item.document_id,
            )

        key = by_recency if plan.order == "recency" else by_relevance
        return sorted(candidates.values(), key=key)

    def _recency_rank(self, connection, document_ids: Sequence[str]) -> Dict[str, int]:
        placeholders = ", ".join("?" for _ in document_ids)
        rows = connection.execute(
            f"""
            SELECT document_id, {_recency_expression()} AS sort_date
            FROM documents
            WHERE document_id IN ({placeholders})
            """,
            list(document_ids),
        ).fetchall()
        dates = {row["document_id"]: row["sort_date"] or "" for row in rows}
        ordered = sorted(document_ids, key=lambda value: (dates.get(value, ""), value), reverse=True)
        return {document_id: position for position, document_id in enumerate(ordered)}

    # ----------------------------------------------------------- hydrate

    def _hydrate(self, connection, plan: QueryPlan, ordered: Sequence[Candidate]) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for candidate in ordered:
            row = connection.execute(
                DOCUMENT_SELECT + " WHERE document_id = ?",
                (candidate.document_id,),
            ).fetchone()
            if row is None:
                continue
            results.append({**self._row(connection, row), "signals": candidate.signals()})
        return results

    def _row(self, connection, row) -> Dict[str, Any]:
        return {
            "document_id": row["document_id"],
            "type": row["type"],
            "source_type": row["source_type"],
            "title": row["title"],
            "body": row["body"],
            "visibility": row["visibility"],
            "status": row["status"],
            "created": row["created"],
            "updated": row["updated"],
            "source_ids": _json_list(row["source_ids"]),
            "tags": _json_list(row["tags"]),
            "people": _json_list(row["people"]),
            "companies": _json_list(row["companies"]),
            "projects": _json_list(row["projects"]),
            "content_hash": row["content_hash"] or "",
            "content_trust": row["content_trust"] or "trusted",
            "enrichment_status": row["enrichment_status"] or "none",
            "enrichment": _json_object(row["enrichment"]),
            "entity_refs": self._mentions(connection, row["document_id"]),
            "relationships": self._relationships(connection, row["document_id"]),
            "signals": {},
        }

    # ------------------------------------------------- read-only lookups
    #
    # The research tools in `tools.py` need to fetch a specific document, walk
    # from an entity to its documents, and check whether a document has moved
    # since a session snapshot was taken. Each of these is a bounded, indexed
    # lookup on the same read-only connection; none of them accepts free text
    # that reaches SQL.

    def documents(self, document_ids: Sequence[str]) -> List[Dict[str, Any]]:
        """Fetch specific documents by id, in the order requested."""
        wanted = [value for value in document_ids if value][:PASS_LIMIT]
        if not wanted:
            return []
        placeholders = ", ".join("?" for _ in wanted)
        with closing(self.connect()) as connection:
            rows = {
                row["document_id"]: self._row(connection, row)
                for row in connection.execute(
                    f"{DOCUMENT_SELECT} WHERE document_id IN ({placeholders})", wanted
                )
            }
        return [rows[value] for value in wanted if value in rows]

    def content_hashes(self, document_ids: Sequence[str]) -> Dict[str, str]:
        """Current content hash per document, for session staleness checks."""
        wanted = [value for value in document_ids if value][:PASS_LIMIT]
        if not wanted:
            return {}
        placeholders = ", ".join("?" for _ in wanted)
        with closing(self.connect()) as connection:
            return {
                row["document_id"]: row["content_hash"] or ""
                for row in connection.execute(
                    f"SELECT document_id, content_hash FROM documents "
                    f"WHERE document_id IN ({placeholders})",
                    wanted,
                )
            }

    def entity(self, entity_id: str) -> Optional[Dict[str, Any]]:
        """One canonical entity record with its aliases, or None."""
        with closing(self.connect()) as connection:
            row = connection.execute(
                "SELECT entity_id, type, name, status FROM entities WHERE entity_id = ?",
                (entity_id,),
            ).fetchone()
            if row is None:
                return None
            aliases = [
                item["value"]
                for item in connection.execute(
                    "SELECT value FROM entity_aliases WHERE entity_id = ? ORDER BY value",
                    (entity_id,),
                )
            ]
            mentions = connection.execute(
                "SELECT count(*) AS total FROM document_entity_mentions WHERE entity_id = ?",
                (entity_id,),
            ).fetchone()
        return {
            "entity_id": row["entity_id"],
            "type": row["type"],
            "name": row["name"],
            "status": row["status"],
            "aliases": aliases,
            "mention_count": int(mentions["total"] if mentions else 0),
        }

    def entity_document_ids(self, entity_id: str, *, limit: int = 25) -> List[str]:
        """Documents mentioning an entity, newest first."""
        with closing(self.connect()) as connection:
            return [
                row["document_id"]
                for row in connection.execute(
                    f"""
                    SELECT m.document_id AS document_id
                    FROM document_entity_mentions m
                    JOIN documents d ON d.document_id = m.document_id
                    WHERE m.entity_id = ?
                    GROUP BY m.document_id
                    ORDER BY {_recency_expression("d")} DESC, m.document_id ASC
                    LIMIT ?
                    """,
                    (entity_id, max(1, min(int(limit), PASS_LIMIT))),
                )
            ]

    def entity_relationships(self, entity_id: str, *, limit: int = 25) -> List[Dict[str, Any]]:
        """Active, evidence-backed relationship assertions touching an entity."""
        with closing(self.connect()) as connection:
            return [
                {
                    "relationship_id": row["relationship_id"],
                    "predicate": row["predicate"],
                    "subject_entity_id": row["subject_entity_id"],
                    "subject": row["subject_name"] or row["subject_entity_id"],
                    "object_entity_id": row["object_entity_id"],
                    "object": row["object_name"] or row["object_entity_id"],
                    "document_id": row["document_id"],
                    "excerpt": row["evidence_excerpt"],
                }
                for row in connection.execute(
                    """
                    SELECT r.relationship_id, r.predicate, r.subject_entity_id,
                           r.object_entity_id, r.document_id, r.evidence_excerpt,
                           s.name AS subject_name, o.name AS object_name
                    FROM relationships r
                    LEFT JOIN entities s ON s.entity_id = r.subject_entity_id
                    LEFT JOIN entities o ON o.entity_id = r.object_entity_id
                    WHERE r.status = 'active'
                      AND (r.subject_entity_id = ? OR r.object_entity_id = ?)
                    ORDER BY r.relationship_id ASC
                    LIMIT ?
                    """,
                    (entity_id, entity_id, max(1, min(int(limit), PASS_LIMIT))),
                )
            ]

    def foundational_documents(self, entity_ids: Sequence[str]) -> List[Dict[str, Any]]:
        """Authored identity records for these entities, if any exist.

        A foundational document is stored under the entity's own id, so this
        is an exact lookup rather than a search: either someone wrote down
        what the entity is, or nobody did.
        """
        wanted = [value for value in entity_ids if value]
        if not wanted:
            return []
        placeholders = ", ".join("?" for _ in wanted)
        with closing(self.connect()) as connection:
            rows = {
                row["document_id"]: self._row(connection, row)
                for row in connection.execute(
                    f"{DOCUMENT_SELECT} WHERE document_id IN ({placeholders}) AND type = 'entity'",
                    wanted,
                )
            }
        return [rows[value] for value in wanted if value in rows]

    def enriched_documents(self, *, limit: int = 50) -> List[Dict[str, Any]]:
        """Documents carrying derived decision/action/question structures.

        The structures themselves are read by `tools.py`; this only finds the
        documents that have any, newest first, so the structural primitives do
        not have to scan the whole corpus.
        """
        with closing(self.connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT document_id, title, type, source_type, created, updated,
                       enrichment_status, enrichment
                FROM documents
                WHERE enrichment != '' AND enrichment != '{{}}'
                ORDER BY {_recency_expression()} DESC, document_id ASC
                LIMIT ?
                """,
                (max(1, min(int(limit), PASS_LIMIT)),),
            ).fetchall()
        return [
            {
                "document_id": row["document_id"],
                "title": row["title"],
                "type": row["type"],
                "source_type": row["source_type"],
                "created": row["created"],
                "updated": row["updated"],
                "enrichment_status": row["enrichment_status"] or "none",
                "enrichment": _json_object(row["enrichment"]),
            }
            for row in rows
        ]

    def _mentions(self, connection, document_id: str) -> List[Dict[str, Any]]:
        """Mentions plus each entity's aliases.

        Documents write "Frank" where the canonical record says "Frank
        Godchaux". Grounding checks compare claims against excerpt text, so
        they need the forms that actually appear in prose.
        """
        return [
            {
                "entity_id": row["entity_id"],
                "entity_type": row["entity_type"],
                "label": row["label"],
                "name": row["name"] or row["label"],
                "aliases": sorted(
                    {value for value in (row["aliases"] or "").split("\x1f") if value}
                )[:MAX_ALIAS_FORMS],
            }
            for row in connection.execute(
                """
                SELECT m.entity_id, m.entity_type, m.label, e.name,
                       (SELECT group_concat(a.value, char(31))
                          FROM entity_aliases a
                         WHERE a.entity_id = m.entity_id) AS aliases
                FROM document_entity_mentions m
                LEFT JOIN entities e ON e.entity_id = m.entity_id
                WHERE m.document_id = ?
                ORDER BY m.entity_id ASC, m.label ASC
                """,
                (document_id,),
            )
        ]

    def _relationships(self, connection, document_id: str) -> List[Dict[str, Any]]:
        return [
            {
                "relationship_id": row["relationship_id"],
                "predicate": row["predicate"],
                "subject_entity_id": row["subject_entity_id"],
                "subject": row["subject_name"] or row["subject_entity_id"],
                "object_entity_id": row["object_entity_id"],
                "object": row["object_name"] or row["object_entity_id"],
                "excerpt": row["evidence_excerpt"],
            }
            for row in connection.execute(
                """
                SELECT r.relationship_id, r.predicate, r.subject_entity_id, r.object_entity_id,
                       r.evidence_excerpt, s.name AS subject_name, o.name AS object_name
                FROM relationships r
                LEFT JOIN entities s ON s.entity_id = r.subject_entity_id
                LEFT JOIN entities o ON o.entity_id = r.object_entity_id
                WHERE r.document_id = ? AND r.status = 'active'
                ORDER BY r.relationship_id ASC
                """,
                (document_id,),
            )
        ]


def _assert_supported_schema(connection: sqlite3.Connection) -> None:
    """Fail with instructions rather than a column error on an older index."""
    try:
        columns = {row["name"] for row in connection.execute("PRAGMA table_info(documents)")}
    except sqlite3.DatabaseError as exc:
        raise RetrievalError(f"Private knowledge index is unreadable: {exc}. Run: gang index build") from exc

    if not columns:
        raise RetrievalError("Private knowledge index has no documents table. Run: gang index build")

    missing = sorted(set(REQUIRED_DOCUMENT_COLUMNS) - columns)
    if missing:
        raise RetrievalError(
            "Private knowledge index predates `gang ask` and is missing: "
            + ", ".join(missing)
            + ". Run: gang index build"
        )


def fts_match_expression(text_queries: Sequence[str]) -> str:
    """Build an FTS5 MATCH expression where every term is a quoted literal.

    Quoting everything means a query containing FTS operators, SQL punctuation,
    or a prompt-injection payload is searched for as text rather than parsed.
    """
    terms: List[str] = []
    for value in text_queries:
        text = (value or "").strip()
        if not text:
            continue
        literal = '"' + text.replace('"', '""') + '"'
        if literal not in terms:
            terms.append(literal)
    return " OR ".join(terms) if terms else '""'


def _filter_clause(plan: QueryPlan) -> Tuple[str, List[Any]]:
    clauses: List[str] = []
    params: List[Any] = []

    if plan.document_types:
        placeholders = ", ".join("?" for _ in plan.document_types)
        clauses.append(f"lower(d.type) IN ({placeholders})")
        params.extend(plan.document_types)
    if plan.source_types:
        placeholders = ", ".join("?" for _ in plan.source_types)
        clauses.append(f"lower(d.source_type) IN ({placeholders})")
        params.extend(plan.source_types)
    if plan.visibility:
        clauses.append("lower(d.visibility) = ?")
        params.append(plan.visibility)
    if plan.enrichment_status:
        placeholders = ", ".join("?" for _ in plan.enrichment_status)
        clauses.append(f"lower(d.enrichment_status) IN ({placeholders})")
        params.extend(plan.enrichment_status)
    if plan.date_range and not plan.date_range.empty:
        column = "d.created" if plan.date_range.field == "created" else _recency_expression("d")
        if plan.date_range.start:
            clauses.append(f"substr({column}, 1, 10) >= ?")
            params.append(plan.date_range.start)
        if plan.date_range.end:
            clauses.append(f"substr({column}, 1, 10) <= ?")
            params.append(plan.date_range.end)

    if not clauses:
        return "", []
    return " AND " + " AND ".join(clauses), params


def _recency_expression(alias: str = "") -> str:
    prefix = f"{alias}." if alias else ""
    return f"CASE WHEN {prefix}updated != '' THEN {prefix}updated ELSE {prefix}created END"


def _prune_weak_text_only(plan: QueryPlan, candidates: Dict[str, Candidate]) -> Dict[str, Candidate]:
    """Drop the weak tail once a question has a stronger signal to go on.

    "What has Frank been working on with Eliro?" resolves two entities and
    leaves one loose term, "working". Every document containing that word would
    otherwise fill the evidence set alongside the documents that actually
    mention Frank. When entity or relationship retrieval succeeded, a text-only
    candidate has to match at least two distinct query terms to earn a slot.

    If the rule would empty the set it is abandoned, because returning thin
    evidence beats returning none.
    """
    if not (plan.entity_ids or plan.relationship_filters):
        return candidates
    if not any(
        item.entity_matches or item.relationship_matches for item in candidates.values()
    ):
        return candidates

    kept = {
        document_id: item
        for document_id, item in candidates.items()
        if item.entity_matches
        or item.relationship_matches
        or item.metadata_match
        or item.text_term_hits >= 2
    }
    return kept or candidates


def _has_metadata_filter(plan: QueryPlan) -> bool:
    return bool(
        plan.document_types
        or plan.source_types
        or plan.enrichment_status
        or (plan.date_range and not plan.date_range.empty)
    )


def _json_list(value: Any) -> List[str]:
    if not value:
        return []
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return [str(item) for item in data] if isinstance(data, list) else []


def _json_object(value: Any) -> Dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}
