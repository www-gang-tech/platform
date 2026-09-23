"""Generated storage for evidence facts and decision records.

One SQLite file under ``GANG_HOME/generated``, separate from the knowledge
index for the same reason derived profiles are: the index is dropped and
rebuilt wholesale on every entity edit, and facts are invalidated per
document, not per rebuild. Deleting the file loses nothing that a rebuild
does not restore.

Invalidation is per source document. Each document row records the hash of
the text its facts were extracted from and the extractor version that did
the extracting; a rebuild re-extracts exactly the documents where either
differs, drops the facts of documents that are gone, and leaves every other
row untouched — which is what makes two rebuilds over unchanged evidence
byte-for-byte idempotent. A change to the entity registry (a new alias, a
new person) changes what can be recognized anywhere, so it invalidates
everything.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from .model import (
    EXTRACTOR_VERSION,
    FACTS_SCHEMA_VERSION,
    DecisionRecord,
    EvidenceFact,
)


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sources (
    document_id TEXT PRIMARY KEY,
    source_hash TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    extractor_version INTEGER NOT NULL,
    source_class TEXT NOT NULL,
    source_rank INTEGER NOT NULL,
    source_reason TEXT NOT NULL,
    document_date TEXT NOT NULL,
    title TEXT NOT NULL,
    path TEXT NOT NULL,
    file_mtime_ns INTEGER NOT NULL,
    file_size INTEGER NOT NULL,
    extracted_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS facts (
    fact_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    subject_entity_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_entity_id TEXT NOT NULL,
    object_value TEXT NOT NULL,
    object_value_type TEXT NOT NULL,
    role TEXT NOT NULL,
    excerpt TEXT NOT NULL,
    document_date TEXT NOT NULL,
    method TEXT NOT NULL,
    rule TEXT NOT NULL,
    confidence TEXT NOT NULL,
    extractor_version INTEGER NOT NULL,
    source_hash TEXT NOT NULL,
    source_class TEXT NOT NULL,
    source_rank INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS facts_subject ON facts(subject_entity_id);
CREATE INDEX IF NOT EXISTS facts_object ON facts(object_entity_id);
CREATE INDEX IF NOT EXISTS facts_document ON facts(document_id);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL,
    text TEXT NOT NULL,
    context TEXT NOT NULL,
    status TEXT NOT NULL,
    decision_date TEXT NOT NULL,
    method TEXT NOT NULL,
    rule TEXT NOT NULL,
    extractor_version INTEGER NOT NULL,
    source_hash TEXT NOT NULL,
    source_class TEXT NOT NULL,
    source_rank INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS decisions_document ON decisions(document_id);
"""

META_SCHEMA_VERSION = "schema_version"
META_EXTRACTOR_VERSION = "extractor_version"
META_ENTITY_FINGERPRINT = "entity_fingerprint"
META_BUILT_AT = "built_at"


class FactStore:
    """Read and write the generated facts database. Safe to delete."""

    def __init__(self, database_path: Path | str):
        self.database_path = Path(database_path)

    def exists(self) -> bool:
        return self.database_path.exists()

    # --------------------------------------------------------------- meta

    def metadata(self) -> Dict[str, str]:
        if not self.exists():
            return {}
        try:
            with closing(self._connect()) as connection:
                return {row["key"]: row["value"] for row in connection.execute("SELECT key, value FROM metadata")}
        except sqlite3.DatabaseError:
            return {}

    # -------------------------------------------------------------- write

    def replace_document(
        self,
        connection: sqlite3.Connection,
        *,
        source: Dict[str, Any],
        facts: Sequence[EvidenceFact],
        decisions: Sequence[DecisionRecord],
    ) -> None:
        document_id = source["document_id"]
        connection.execute("DELETE FROM facts WHERE document_id = ?", (document_id,))
        connection.execute("DELETE FROM decisions WHERE document_id = ?", (document_id,))
        connection.execute(
            """
            INSERT OR REPLACE INTO sources (
                document_id, source_hash, payload_hash, extractor_version, source_class,
                source_rank, source_reason, document_date, title, path, file_mtime_ns,
                file_size, extracted_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                document_id,
                source["source_hash"],
                source.get("payload_hash") or "",
                EXTRACTOR_VERSION,
                source["source_class"],
                int(source["source_rank"]),
                source.get("source_reason") or "",
                source.get("document_date") or "",
                source.get("title") or "",
                source.get("path") or "",
                int(source.get("file_mtime_ns") or 0),
                int(source.get("file_size") or 0),
                source["extracted_at"],
            ),
        )
        connection.executemany(
            """
            INSERT OR REPLACE INTO facts (
                fact_id, document_id, subject_entity_id, predicate, object_entity_id,
                object_value, object_value_type, role, excerpt, document_date, method, rule,
                confidence, extractor_version, source_hash, source_class, source_rank
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    fact.fact_id,
                    fact.document_id,
                    fact.subject_entity_id,
                    fact.predicate,
                    fact.object_entity_id,
                    fact.object_value,
                    fact.object_value_type,
                    fact.role,
                    fact.excerpt,
                    fact.document_date,
                    fact.method,
                    fact.rule,
                    fact.confidence,
                    fact.extractor_version,
                    fact.source_hash,
                    fact.source_class,
                    fact.source_rank,
                )
                for fact in facts
            ],
        )
        connection.executemany(
            """
            INSERT OR REPLACE INTO decisions (
                decision_id, document_id, text, context, status, decision_date, method, rule,
                extractor_version, source_hash, source_class, source_rank
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    decision.decision_id,
                    decision.document_id,
                    decision.text,
                    decision.context,
                    decision.status,
                    decision.decision_date,
                    decision.method,
                    decision.rule,
                    decision.extractor_version,
                    decision.source_hash,
                    decision.source_class,
                    decision.source_rank,
                )
                for decision in decisions
            ],
        )

    def remove_documents(self, connection: sqlite3.Connection, document_ids: Iterable[str]) -> int:
        removed = 0
        for document_id in document_ids:
            connection.execute("DELETE FROM facts WHERE document_id = ?", (document_id,))
            connection.execute("DELETE FROM decisions WHERE document_id = ?", (document_id,))
            removed += connection.execute(
                "DELETE FROM sources WHERE document_id = ?", (document_id,)
            ).rowcount
        return removed

    def reset(self, connection: sqlite3.Connection) -> None:
        connection.execute("DELETE FROM facts")
        connection.execute("DELETE FROM decisions")
        connection.execute("DELETE FROM sources")

    def set_metadata(self, connection: sqlite3.Connection, values: Dict[str, str]) -> None:
        connection.executemany(
            "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
            sorted(values.items()),
        )

    def writer(self) -> sqlite3.Connection:
        """A connection for one build. The caller commits or rolls back."""
        connection = self._connect(create=True)
        if not self._schema_current(connection):
            # A schema from another version is not worth migrating: every row
            # in it is regenerable. Start over.
            connection.close()
            self.database_path.unlink(missing_ok=True)
            connection = self._connect(create=True)
        connection.executescript(SCHEMA_SQL)
        return connection

    # --------------------------------------------------------------- read

    def facts(
        self,
        *,
        subject_entity_id: str = "",
        entity_id: str = "",
    ) -> List[EvidenceFact]:
        if not self.exists():
            return []
        clauses: List[str] = []
        params: List[Any] = []
        if subject_entity_id:
            clauses.append("f.subject_entity_id = ?")
            params.append(subject_entity_id)
        if entity_id:
            clauses.append("(f.subject_entity_id = ? OR f.object_entity_id = ?)")
            params.extend([entity_id, entity_id])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    f"""
                    SELECT f.*, s.title AS document_title
                    FROM facts f LEFT JOIN sources s ON s.document_id = f.document_id
                    {where}
                    ORDER BY f.source_rank DESC, f.document_date DESC, f.fact_id ASC
                    """,
                    params,
                ).fetchall()
        except sqlite3.DatabaseError:
            return []
        return [_fact_from_row(row) for row in rows]

    def decisions(self) -> List[DecisionRecord]:
        if not self.exists():
            return []
        try:
            with closing(self._connect()) as connection:
                rows = connection.execute(
                    """
                    SELECT d.*, s.title AS document_title
                    FROM decisions d LEFT JOIN sources s ON s.document_id = d.document_id
                    ORDER BY d.decision_date DESC, d.source_rank DESC, d.decision_id ASC
                    """
                ).fetchall()
        except sqlite3.DatabaseError:
            return []
        return [_decision_from_row(row) for row in rows]

    def counts(self) -> Dict[str, int]:
        if not self.exists():
            return {"sources": 0, "facts": 0, "decisions": 0}
        try:
            with closing(self._connect()) as connection:
                return {
                    table: int(connection.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
                    for table in ("sources", "facts", "decisions")
                }
        except sqlite3.DatabaseError:
            return {"sources": 0, "facts": 0, "decisions": 0}

    def snapshot(self) -> Dict[str, List[tuple]]:
        """Every generated row, ordered. For idempotency checks and tests."""
        if not self.exists():
            return {}
        with closing(self._connect()) as connection:
            return {
                "facts": [tuple(row) for row in connection.execute("SELECT * FROM facts ORDER BY fact_id")],
                "decisions": [
                    tuple(row) for row in connection.execute("SELECT * FROM decisions ORDER BY decision_id")
                ],
                "sources": [
                    tuple(row)
                    for row in connection.execute(
                        "SELECT document_id, source_hash, extractor_version, source_class "
                        "FROM sources ORDER BY document_id"
                    )
                ],
            }

    def clear(self) -> bool:
        if self.exists():
            self.database_path.unlink()
            return True
        return False

    # ------------------------------------------------------------ helpers

    def _schema_current(self, connection: sqlite3.Connection) -> bool:
        try:
            tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            if not tables:
                return True
            if "metadata" not in tables:
                return False
            row = connection.execute(
                "SELECT value FROM metadata WHERE key = ?", (META_SCHEMA_VERSION,)
            ).fetchone()
        except sqlite3.DatabaseError:
            return False
        return row is None or row[0] == str(FACTS_SCHEMA_VERSION)

    def _connect(self, *, create: bool = False) -> sqlite3.Connection:
        if create:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(self.database_path)
        else:
            connection = sqlite3.connect(f"file:{self.database_path}?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        return connection


def _fact_from_row(row: sqlite3.Row) -> EvidenceFact:
    return EvidenceFact(
        fact_id=row["fact_id"],
        document_id=row["document_id"],
        subject_entity_id=row["subject_entity_id"],
        predicate=row["predicate"],
        excerpt=row["excerpt"],
        method=row["method"],
        rule=row["rule"],
        confidence=row["confidence"],
        extractor_version=int(row["extractor_version"]),
        source_hash=row["source_hash"],
        source_class=row["source_class"],
        source_rank=int(row["source_rank"]),
        document_date=row["document_date"],
        object_entity_id=row["object_entity_id"],
        object_value=row["object_value"],
        object_value_type=row["object_value_type"],
        role=row["role"],
        document_title=row["document_title"] or "",
    )


def _decision_from_row(row: sqlite3.Row) -> DecisionRecord:
    return DecisionRecord(
        decision_id=row["decision_id"],
        document_id=row["document_id"],
        text=row["text"],
        status=row["status"],
        method=row["method"],
        rule=row["rule"],
        extractor_version=int(row["extractor_version"]),
        source_hash=row["source_hash"],
        source_class=row["source_class"],
        source_rank=int(row["source_rank"]),
        decision_date=row["decision_date"],
        context=row["context"],
        document_title=row["document_title"] or "",
    )
