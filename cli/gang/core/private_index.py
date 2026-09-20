"""Local private SQLite FTS index for canonical vault Markdown."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from core.paths import GangPaths


@dataclass(frozen=True)
class IndexedDocument:
    document_id: str
    type: str
    title: str
    body: str
    semantic_enrichment: str
    created: str
    updated: str
    visibility: str
    status: str
    tags: List[str]
    people: List[str]
    companies: List[str]
    projects: List[str]
    related: List[str]
    source_ids: List[str]
    content_hash: str


@dataclass(frozen=True)
class IndexBuildResult:
    database_path: Path
    documents: int
    generated_at: str


@dataclass(frozen=True)
class DocumentRoot:
    label: str
    path: Path


class PrivateKnowledgeIndex:
    """Build and query a disposable private FTS5 index from public+private Markdown."""

    def __init__(
        self,
        *,
        root_path: Path | str = Path("."),
        vault_path: Path | str | None = None,
        database_path: Path | str | None = None,
        private_home: Path | str | None = None,
        vault_paths: Optional[List[Path | str]] = None,
    ):
        self.root_path = Path(root_path).resolve()
        self.paths = GangPaths.from_env(repo_root=self.root_path, gang_home=private_home)
        if vault_paths is not None:
            self.document_roots = [
                DocumentRoot(f"vault-{index}", self._resolve(path))
                for index, path in enumerate(vault_paths)
            ]
        elif vault_path is not None:
            self.document_roots = [DocumentRoot("vault", self._resolve(vault_path))]
        else:
            self.document_roots = [
                DocumentRoot("repo-public", self.paths.repo_public_vault),
                DocumentRoot("private", self.paths.private_vault),
            ]
        self.database_path = self._resolve(database_path) if database_path is not None else self.paths.index_path

    def build(self) -> IndexBuildResult:
        documents = list(self.load_documents())
        generated_at = datetime.now(timezone.utc).isoformat()

        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.database_path.with_suffix(self.database_path.suffix + ".tmp")
        if temp_path.exists():
            temp_path.unlink()

        with closing(sqlite3.connect(temp_path)) as connection:
            connection.execute("PRAGMA foreign_keys = ON")
            self._create_schema(connection)
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                ("generated_at", generated_at),
            )
            connection.execute(
                "INSERT INTO metadata(key, value) VALUES (?, ?)",
                ("document_count", str(len(documents))),
            )
            for document in documents:
                self._insert_document(connection, document)
            connection.commit()

        temp_path.replace(self.database_path)
        return IndexBuildResult(self.database_path, len(documents), generated_at)

    def status(self) -> Dict[str, Any]:
        if not self.database_path.exists():
            return {
                "exists": False,
                "database": self.relative_database_path(),
                "documents": 0,
                "generated_at": None,
                "by_type": {},
                "by_visibility": {},
            }

        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.row_factory = sqlite3.Row
            metadata = dict(connection.execute("SELECT key, value FROM metadata").fetchall())
            by_type = {
                row["type"]: row["count"]
                for row in connection.execute(
                    "SELECT type, COUNT(*) AS count FROM documents GROUP BY type ORDER BY type"
                )
            }
            by_visibility = {
                row["visibility"]: row["count"]
                for row in connection.execute(
                    "SELECT visibility, COUNT(*) AS count FROM documents GROUP BY visibility ORDER BY visibility"
                )
            }
            count = connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        return {
            "exists": True,
            "database": self.relative_database_path(),
            "documents": count,
            "generated_at": metadata.get("generated_at"),
            "by_type": by_type,
            "by_visibility": by_visibility,
        }

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        type: Optional[str] = None,
        visibility: Optional[str] = None,
        tag: Optional[str] = None,
        project: Optional[str] = None,
        person: Optional[str] = None,
        source: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        if not self.database_path.exists():
            raise FileNotFoundError(f"Search index not found: {self.relative_database_path()}")

        match_query = self._match_query(query)
        params: List[Any] = [match_query]
        where = ["documents_fts MATCH ?"]

        if type:
            where.append("lower(d.type) = ?")
            params.append(type.lower())
        if visibility:
            where.append("lower(d.visibility) = ?")
            params.append(visibility.lower())
        for column, value in (
            ("tags_index", tag),
            ("projects_index", project),
            ("people_index", person),
            ("source_ids_index", source),
        ):
            if value:
                where.append(f"instr(char(10) || d.{column} || char(10), char(10) || ? || char(10)) > 0")
                params.append(value.lower())

        params.append(max(1, limit))
        sql = f"""
            SELECT
                d.document_id,
                d.type,
                d.title,
                d.visibility,
                d.updated,
                d.source_ids,
                snippet(documents_fts, -1, '', '', ' ... ', 18) AS excerpt,
                bm25(documents_fts, 4.0, 1.0, 2.0) AS rank
            FROM documents_fts
            JOIN documents d ON d.rowid = documents_fts.rowid
            WHERE {" AND ".join(where)}
            ORDER BY rank ASC, d.document_id ASC
            LIMIT ?
        """

        with closing(sqlite3.connect(self.database_path)) as connection:
            connection.row_factory = sqlite3.Row
            try:
                rows = connection.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                params[0] = self._match_query_from_terms(query)
                rows = connection.execute(sql, params).fetchall()

        return [
            {
                "title": row["title"],
                "excerpt": _compact(row["excerpt"]),
                "type": row["type"],
                "document_id": row["document_id"],
                "visibility": row["visibility"],
                "updated": row["updated"],
                "source_ids": json.loads(row["source_ids"]),
            }
            for row in rows
        ]

    def load_documents(self) -> Iterable[IndexedDocument]:
        seen_ids = set()
        for root, path in self._markdown_paths():
            text = path.read_text(encoding="utf-8")
            frontmatter, body = _parse_markdown(text)
            rel_path = path.resolve().relative_to(root.path.resolve()).as_posix()
            document = self._document_from_parts(frontmatter, body, rel_path)
            if document.document_id in seen_ids:
                raise ValueError(f"Duplicate document id in vault: {document.document_id}")
            seen_ids.add(document.document_id)
            yield document

    def relative_database_path(self) -> str:
        try:
            return self.database_path.resolve().relative_to(self.root_path.resolve()).as_posix()
        except ValueError:
            return self.database_path.as_posix()

    def _resolve(self, path: Path | str) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return self.root_path / candidate

    def _markdown_paths(self) -> List[tuple[DocumentRoot, Path]]:
        paths: List[tuple[DocumentRoot, Path]] = []
        for root in self.document_roots:
            if not root.path.exists():
                continue
            root_path = root.path.resolve()
            for path in root.path.rglob("*.md"):
                rel_parts = path.resolve().relative_to(root_path).parts
                if rel_parts and rel_parts[0].startswith("."):
                    continue
                paths.append((root, path))
        return sorted(
            paths,
            key=lambda item: (
                item[0].label,
                item[1].resolve().relative_to(item[0].path.resolve()).as_posix(),
            ),
        )

    def _document_from_parts(self, frontmatter: Dict[str, Any], body: str, rel_path: str) -> IndexedDocument:
        clean_body = _clean_markdown(body)
        title = _string(frontmatter.get("title")) or _first_heading(body) or Path(rel_path).stem.replace("-", " ").title()
        document_id = _string(frontmatter.get("id")) or f"vault_{hashlib.sha256(rel_path.encode('utf-8')).hexdigest()[:16]}"
        source_ids = _source_ids(frontmatter)

        return IndexedDocument(
            document_id=document_id,
            type=_string(frontmatter.get("type")) or "knowledge",
            title=title,
            body=clean_body,
            semantic_enrichment=_semantic_enrichment_text(frontmatter),
            created=_date_value(frontmatter.get("created")) or _date_value(frontmatter.get("created_at")),
            updated=_date_value(frontmatter.get("updated")) or _date_value(frontmatter.get("updated_at")),
            visibility=_string(frontmatter.get("visibility")) or "private",
            status=_string(frontmatter.get("status")),
            tags=_list_strings(frontmatter.get("tags")),
            people=_list_strings(frontmatter.get("people")),
            companies=_list_strings(frontmatter.get("companies")),
            projects=_list_strings(frontmatter.get("projects")),
            related=_list_strings(frontmatter.get("related")),
            source_ids=source_ids,
            content_hash=hashlib.sha256((json.dumps(frontmatter, sort_keys=True, default=str) + body).encode("utf-8")).hexdigest(),
        )

    def _create_schema(self, connection: sqlite3.Connection) -> None:
        connection.executescript(
            """
            CREATE TABLE metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE documents (
                document_id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                semantic_enrichment TEXT NOT NULL,
                created TEXT NOT NULL,
                updated TEXT NOT NULL,
                visibility TEXT NOT NULL,
                status TEXT NOT NULL,
                tags TEXT NOT NULL,
                people TEXT NOT NULL,
                companies TEXT NOT NULL,
                projects TEXT NOT NULL,
                related TEXT NOT NULL,
                source_ids TEXT NOT NULL,
                tags_index TEXT NOT NULL,
                people_index TEXT NOT NULL,
                companies_index TEXT NOT NULL,
                projects_index TEXT NOT NULL,
                related_index TEXT NOT NULL,
                source_ids_index TEXT NOT NULL,
                content_hash TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE documents_fts USING fts5(
                title,
                body,
                semantic_enrichment,
                tokenize='porter unicode61'
            );
            """
        )

    def _insert_document(self, connection: sqlite3.Connection, document: IndexedDocument) -> None:
        values = {
            "document_id": document.document_id,
            "type": document.type,
            "title": document.title,
            "body": document.body,
            "semantic_enrichment": document.semantic_enrichment,
            "created": document.created,
            "updated": document.updated,
            "visibility": document.visibility,
            "status": document.status,
            "tags": json.dumps(document.tags),
            "people": json.dumps(document.people),
            "companies": json.dumps(document.companies),
            "projects": json.dumps(document.projects),
            "related": json.dumps(document.related),
            "source_ids": json.dumps(document.source_ids),
            "tags_index": _membership_index(document.tags),
            "people_index": _membership_index(document.people),
            "companies_index": _membership_index(document.companies),
            "projects_index": _membership_index(document.projects),
            "related_index": _membership_index(document.related),
            "source_ids_index": _membership_index(document.source_ids),
            "content_hash": document.content_hash,
        }
        columns = ", ".join(values)
        placeholders = ", ".join("?" for _ in values)
        cursor = connection.execute(
            f"INSERT INTO documents ({columns}) VALUES ({placeholders})",
            list(values.values()),
        )
        rowid = cursor.lastrowid
        connection.execute(
            """
            INSERT INTO documents_fts (
                rowid, title, body, semantic_enrichment
            ) VALUES (?, ?, ?, ?)
            """,
            (
                rowid,
                document.title,
                document.body,
                document.semantic_enrichment,
            ),
        )

    def _match_query(self, query: str) -> str:
        return query.strip() or self._match_query_from_terms(query)

    def _match_query_from_terms(self, query: str) -> str:
        terms = re.findall(r"[\w-]+", query, flags=re.UNICODE)
        if not terms:
            return '""'
        return " ".join(f'"{term}"' for term in terms)


def _parse_markdown(text: str) -> tuple[Dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    frontmatter = yaml.safe_load(parts[1]) or {}
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return frontmatter, parts[2]


def _source_ids(frontmatter: Dict[str, Any]) -> List[str]:
    values: List[Any] = [frontmatter.get("source_id"), frontmatter.get("source_ids")]
    provenance = frontmatter.get("provenance")
    if isinstance(provenance, dict):
        values.extend([provenance.get("source_id"), provenance.get("source_ids")])
    envelope = frontmatter.get("ingestion_envelope")
    if isinstance(envelope, dict):
        values.extend([envelope.get("source_id"), envelope.get("source_ids")])
    return _list_strings(values)


def _semantic_enrichment_text(frontmatter: Dict[str, Any]) -> str:
    parts: List[str] = []

    summary = _string(frontmatter.get("summary"))
    if summary:
        parts.append(summary)

    for item in _dict_items(frontmatter.get("decisions")):
        decision = _string(item.get("decision"))
        if decision:
            parts.append(decision)

    for item in _dict_items(frontmatter.get("action_items")):
        task = _string(item.get("task"))
        owner = _string(item.get("owner"))
        if task:
            parts.append(task)
        if owner:
            parts.append(owner)

    for item in _dict_items(frontmatter.get("unresolved_questions")):
        question = _string(item.get("question"))
        if question:
            parts.append(question)

    for field in ("tags", "people", "companies", "projects"):
        parts.extend(_list_strings(frontmatter.get(field)))

    parts.extend(_human_readable_related(frontmatter.get("related")))
    return _compact(" ".join(parts))


def _dict_items(value: Any) -> Iterable[Dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _human_readable_related(value: Any) -> List[str]:
    result: List[str] = []

    def collect(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, (list, tuple, set)):
            for child in item:
                collect(child)
            return
        if isinstance(item, dict):
            for key in ("title", "name", "label"):
                if key in item:
                    collect(item[key])
                    return
            return
        text = _string(item)
        if text and not _looks_like_operational_identifier(text) and text not in result:
            result.append(text)

    collect(value)
    return result


def _looks_like_operational_identifier(value: str) -> bool:
    text = value.strip()
    if re.fullmatch(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", text):
        return True
    if re.fullmatch(r"[0-9a-fA-F]{32,64}", text):
        return True
    if re.match(r"^(?:local://|source_|meeting_|file_|enrich_)", text):
        return True
    if "/" in text or "\\" in text:
        return True
    return False


def _list_strings(value: Any) -> List[str]:
    result: List[str] = []

    def collect(item: Any) -> None:
        if item is None:
            return
        if isinstance(item, (list, tuple, set)):
            for child in item:
                collect(child)
            return
        if isinstance(item, dict):
            for key in ("id", "name", "title", "source_id"):
                if key in item:
                    collect(item[key])
                    return
            return
        text = _string(item)
        if text and text not in result:
            result.append(text)

    collect(value)
    return result


def _string(value: Any) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value).strip()


def _date_value(value: Any) -> str:
    return _string(value)


def _membership_index(values: List[str]) -> str:
    return "\n".join(value.lower() for value in values)


def _first_heading(body: str) -> str:
    for line in body.splitlines():
        match = re.match(r"^#\s+(.+)$", line.strip())
        if match:
            return match.group(1).strip()
    return ""


def _clean_markdown(text: str) -> str:
    text = re.sub(r"```[\s\S]*?```", " ", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _compact(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
