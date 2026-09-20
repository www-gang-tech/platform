"""Generated entity/relationship tables inside the single private SQLite index.

There is exactly one database (``GANG_HOME/generated/brain.sqlite``) and it is
disposable. Every row here is derived from canonical Markdown: entity records in
the private vault, and ``entity_refs`` / ``entity_relationships`` frontmatter on
canonical documents. Nothing in SQLite is authoritative.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from .model import (
    EntityRecord,
    normalize_name,
    string_value,
)


ENTITY_SCHEMA_SQL = """
CREATE TABLE entities (
    entity_id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    visibility TEXT NOT NULL,
    status TEXT NOT NULL,
    merged_into TEXT NOT NULL,
    created TEXT NOT NULL,
    updated TEXT NOT NULL,
    source_path TEXT NOT NULL
);

CREATE TABLE entity_aliases (
    entity_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    value TEXT NOT NULL,
    normalized_value TEXT NOT NULL,
    PRIMARY KEY (entity_id, kind, normalized_value)
);

CREATE TABLE document_entity_mentions (
    document_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    label TEXT NOT NULL,
    evidence_excerpt TEXT NOT NULL,
    added TEXT NOT NULL,
    proposal_id TEXT NOT NULL,
    PRIMARY KEY (document_id, entity_id, label)
);

CREATE TABLE relationships (
    relationship_id TEXT PRIMARY KEY,
    subject_entity_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_entity_id TEXT NOT NULL,
    document_id TEXT NOT NULL,
    source_ids TEXT NOT NULL,
    evidence_excerpt TEXT NOT NULL,
    created TEXT NOT NULL,
    status TEXT NOT NULL,
    proposal_id TEXT NOT NULL
);

CREATE INDEX entity_aliases_lookup ON entity_aliases(normalized_value);
CREATE INDEX document_entity_mentions_entity ON document_entity_mentions(entity_id);
CREATE INDEX relationships_subject ON relationships(subject_entity_id);
CREATE INDEX relationships_object ON relationships(object_entity_id);
"""

GRAPH_TABLES = ("entities", "entity_aliases", "document_entity_mentions", "relationships")


def build_entity_tables(
    connection: sqlite3.Connection,
    entities: Sequence[EntityRecord],
    documents: Sequence[Any],
) -> Dict[str, int]:
    """Populate the generated graph tables. Caller owns the transaction."""
    counts = {"entities": 0, "entity_aliases": 0, "document_entity_mentions": 0, "relationships": 0}

    for record in sorted(entities, key=lambda item: item.id):
        connection.execute(
            """
            INSERT INTO entities (
                entity_id, type, name, normalized_name, visibility,
                status, merged_into, created, updated, source_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.id,
                record.type,
                record.name,
                record.normalized_name,
                record.visibility,
                record.status,
                record.merged_into or "",
                record.created,
                record.updated,
                record.path.name if record.path else "",
            ),
        )
        counts["entities"] += 1
        for kind, display, normalized in record.lookup_keys():
            connection.execute(
                """
                INSERT OR IGNORE INTO entity_aliases (entity_id, kind, value, normalized_value)
                VALUES (?, ?, ?, ?)
                """,
                (record.id, kind, display, normalized),
            )
            counts["entity_aliases"] += 1

    for document in sorted(documents, key=lambda item: item.document_id):
        for mention in getattr(document, "entity_refs", []) or []:
            if not isinstance(mention, dict):
                continue
            entity_id = string_value(mention.get("entity_id"))
            label = string_value(mention.get("label"))
            if not entity_id or not label:
                continue
            evidence = mention.get("evidence") if isinstance(mention.get("evidence"), dict) else {}
            connection.execute(
                """
                INSERT OR REPLACE INTO document_entity_mentions (
                    document_id, entity_id, entity_type, label, evidence_excerpt, added, proposal_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.document_id,
                    entity_id,
                    string_value(mention.get("entity_type")),
                    label,
                    string_value(evidence.get("excerpt")),
                    string_value(mention.get("added")),
                    string_value(mention.get("proposal_id")),
                ),
            )
            counts["document_entity_mentions"] += 1

        for relationship in getattr(document, "entity_relationships", []) or []:
            if not isinstance(relationship, dict):
                continue
            identifier = string_value(relationship.get("relationship_id"))
            if not identifier:
                continue
            evidence = (
                relationship.get("evidence") if isinstance(relationship.get("evidence"), dict) else {}
            )
            connection.execute(
                """
                INSERT OR REPLACE INTO relationships (
                    relationship_id, subject_entity_id, predicate, object_entity_id,
                    document_id, source_ids, evidence_excerpt, created, status, proposal_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    identifier,
                    string_value(relationship.get("subject_entity_id")),
                    string_value(relationship.get("predicate")),
                    string_value(relationship.get("object_entity_id")),
                    string_value(relationship.get("document_id")) or document.document_id,
                    json.dumps(list(relationship.get("source_ids") or [])),
                    string_value(evidence.get("excerpt")),
                    string_value(relationship.get("created")),
                    string_value(relationship.get("status")) or "active",
                    string_value(relationship.get("proposal_id")),
                ),
            )
            counts["relationships"] += 1

    return counts


class EntityGraph:
    """Read-only queries over the generated entity tables."""

    def __init__(self, database_path: Path | str):
        self.database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        if not self.database_path.exists():
            raise FileNotFoundError(f"Entity index not found: {self.database_path}")
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        return connection

    def counts(self) -> Dict[str, int]:
        if not self.database_path.exists():
            return {table: 0 for table in GRAPH_TABLES}
        with closing(self._connect()) as connection:
            if not _has_graph_tables(connection):
                return {table: 0 for table in GRAPH_TABLES}
            return {
                table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in GRAPH_TABLES
            }

    def search(self, query: str, *, entity_type: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """Substring lookup over canonical names, aliases, emails, and domains."""
        normalized = normalize_name(query)
        params: List[Any] = [f"%{normalized}%"]
        where = ["a.normalized_value LIKE ?"]
        if entity_type:
            where.append("e.type = ?")
            params.append(entity_type)
        params.append(max(1, limit))

        with closing(self._connect()) as connection:
            rows = connection.execute(
                f"""
                SELECT
                    e.entity_id,
                    e.type,
                    e.name,
                    e.status,
                    e.merged_into,
                    GROUP_CONCAT(DISTINCT a.kind) AS matched_kinds,
                    (SELECT COUNT(*) FROM document_entity_mentions m WHERE m.entity_id = e.entity_id) AS mentions
                FROM entity_aliases a
                JOIN entities e ON e.entity_id = a.entity_id
                WHERE {" AND ".join(where)}
                GROUP BY e.entity_id
                ORDER BY e.type ASC, e.normalized_name ASC, e.entity_id ASC
                LIMIT ?
                """,
                params,
            ).fetchall()

        return [
            {
                "entity_id": row["entity_id"],
                "type": row["type"],
                "name": row["name"],
                "status": row["status"],
                "merged_into": row["merged_into"] or None,
                "matched": sorted((row["matched_kinds"] or "").split(",")),
                "mentions": row["mentions"],
            }
            for row in rows
        ]

    def show(self, entity_id: str) -> Dict[str, Any]:
        with closing(self._connect()) as connection:
            entity = connection.execute(
                "SELECT * FROM entities WHERE entity_id = ?", (entity_id,)
            ).fetchone()
            if entity is None:
                raise KeyError(f"Entity not in generated index: {entity_id}")

            aliases = [
                {"kind": row["kind"], "value": row["value"]}
                for row in connection.execute(
                    "SELECT kind, value FROM entity_aliases WHERE entity_id = ? AND kind != 'name'"
                    " ORDER BY kind ASC, normalized_value ASC",
                    (entity_id,),
                )
            ]

            documents = [
                {
                    "document_id": row["document_id"],
                    "title": row["title"] or row["document_id"],
                    "type": row["type"] or "",
                    "visibility": row["visibility"] or "",
                    "updated": row["updated"] or "",
                    "label": row["label"],
                    "source_ids": json.loads(row["source_ids"]) if row["source_ids"] else [],
                    "evidence_excerpt": row["evidence_excerpt"],
                }
                for row in connection.execute(
                    """
                    SELECT
                        m.document_id, m.label, m.evidence_excerpt,
                        d.title, d.type, d.visibility, d.updated, d.source_ids
                    FROM document_entity_mentions m
                    LEFT JOIN documents d ON d.document_id = m.document_id
                    WHERE m.entity_id = ?
                    ORDER BY d.updated DESC, m.document_id ASC, m.label ASC
                    """,
                    (entity_id,),
                )
            ]

            relationships = [
                {
                    "relationship_id": row["relationship_id"],
                    "direction": row["direction"],
                    "predicate": row["predicate"],
                    "other_entity_id": row["other_entity_id"],
                    "other_entity_name": row["other_entity_name"] or row["other_entity_id"],
                    "document_id": row["document_id"],
                    "document_title": row["document_title"] or row["document_id"],
                    "source_ids": json.loads(row["source_ids"]) if row["source_ids"] else [],
                    "evidence_excerpt": row["evidence_excerpt"],
                    "created": row["created"],
                }
                for row in connection.execute(
                    """
                    SELECT
                        r.relationship_id,
                        CASE WHEN r.subject_entity_id = :id THEN 'outbound' ELSE 'inbound' END AS direction,
                        r.predicate,
                        CASE WHEN r.subject_entity_id = :id THEN r.object_entity_id
                             ELSE r.subject_entity_id END AS other_entity_id,
                        other.name AS other_entity_name,
                        r.document_id,
                        d.title AS document_title,
                        r.source_ids,
                        r.evidence_excerpt,
                        r.created
                    FROM relationships r
                    LEFT JOIN entities other
                        ON other.entity_id = CASE WHEN r.subject_entity_id = :id
                                                  THEN r.object_entity_id ELSE r.subject_entity_id END
                    LEFT JOIN documents d ON d.document_id = r.document_id
                    WHERE (r.subject_entity_id = :id OR r.object_entity_id = :id)
                      AND r.status = 'active'
                    ORDER BY direction ASC, r.predicate ASC, other_entity_name ASC, r.relationship_id ASC
                    """,
                    {"id": entity_id},
                )
            ]

            source_ids = sorted({source for document in documents for source in document["source_ids"]})

        return {
            "entity_id": entity["entity_id"],
            "type": entity["type"],
            "name": entity["name"],
            "status": entity["status"],
            "merged_into": entity["merged_into"] or None,
            "visibility": entity["visibility"],
            "created": entity["created"],
            "updated": entity["updated"],
            "aliases": aliases,
            "documents": documents,
            "relationships": relationships,
            "provenance": {
                "documents": len({document["document_id"] for document in documents}),
                "mentions": len(documents),
                "relationships": len(relationships),
                "source_ids": len(source_ids),
            },
        }

    def fingerprint(self) -> str:
        """Stable hash of the generated graph, ignoring build timestamps."""
        payload: Dict[str, List[List[Any]]] = {}
        with closing(self._connect()) as connection:
            for table in GRAPH_TABLES:
                columns = [
                    row["name"]
                    for row in connection.execute(f"PRAGMA table_info({table})")
                ]
                rows = connection.execute(
                    f"SELECT {', '.join(columns)} FROM {table}"
                ).fetchall()
                payload[table] = sorted([list(row) for row in rows], key=lambda item: json.dumps(item, default=str))
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()


def _has_graph_tables(connection: sqlite3.Connection) -> bool:
    names = {
        row[0]
        for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    return set(GRAPH_TABLES).issubset(names)
