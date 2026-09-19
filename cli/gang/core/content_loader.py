"""
Canonical public content loading.

This module is the one boundary where public build content is selected from
legacy Markdown or the canonical public vault.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml


PUBLIC_TYPES = {
    "articles": "post",
    "newsletters": "newsletter",
    "pages": "page",
    "posts": "post",
    "projects": "project",
}
TYPE_TO_COLLECTION = {
    "newsletter": "newsletters",
    "page": "pages",
    "post": "posts",
    "project": "projects",
}
PRIVATE_PATTERNS = (
    re.compile(r"\bcontent/", re.IGNORECASE),
    re.compile(r"\braw archive\b", re.IGNORECASE),
)
SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"\b(?:api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{12,}", re.IGNORECASE),
)
LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")


class PublicContentError(Exception):
    """Raised when public content cannot be loaded or validated."""


@dataclass(frozen=True)
class PublicDocument:
    id: Optional[str]
    type: str
    collection: str
    slug: str
    title: str
    url: str
    created: Optional[str]
    updated: Optional[str]
    status: str
    visibility: str
    body: str
    frontmatter: Dict[str, Any]
    source_path: Path
    source: str

    @property
    def date(self) -> Optional[str]:
        value = self.frontmatter.get("date")
        return normalize_value(value)

    @property
    def summary(self) -> str:
        return self.frontmatter.get("summary") or self.frontmatter.get("description") or ""

    @property
    def tags(self) -> List[str]:
        tags = self.frontmatter.get("tags") or []
        return tags if isinstance(tags, list) else []

    def to_page_data(self, content_html: str = "") -> Dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "summary": self.summary,
            "date": self.date,
            "type": self.collection,
            "document_type": self.type,
            "content_html": content_html,
            "tags": self.tags,
            "slug": self.slug,
        }


def normalize_value(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return value
    return str(value)


def parse_markdown(text: str) -> Tuple[Dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    frontmatter = yaml.safe_load(parts[1]) or {}
    if not isinstance(frontmatter, dict):
        frontmatter = {}
    return frontmatter, parts[2]


def dump_markdown(frontmatter: Dict[str, Any], body: str) -> str:
    rendered = yaml.safe_dump(frontmatter, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return f"---\n{rendered}---{body}"


def is_uuidv7(value: str) -> bool:
    try:
        parsed = uuid.UUID(str(value))
    except (ValueError, TypeError):
        return False
    return parsed.version == 7


def load_public_content(
    config: Dict[str, Any],
    source: str = "vault",
    root_path: Path = Path("."),
) -> List[PublicDocument]:
    """Load and validate the public document collection."""
    if source not in {"legacy", "vault"}:
        raise PublicContentError(f"Unknown public content source: {source}")

    root_path = root_path.resolve()
    if source == "legacy":
        source_root = root_path / config.get("build", {}).get("content", "content")
    else:
        source_root = root_path / "brain" / "vault" / "public"

    if not source_root.exists():
        raise PublicContentError(f"Public content source does not exist: {source_root}")

    documents = [_load_markdown_file(path, source_root, source) for path in _iter_public_markdown(source_root)]
    documents = [doc for doc in documents if doc is not None]
    validate_public_documents(documents, source=source)
    return sorted(documents, key=lambda item: (item.collection, item.slug))


def validate_public_documents(documents: List[PublicDocument], source: str = "vault") -> None:
    errors: List[str] = []
    urls = {}

    for doc in documents:
        if doc.url in urls:
            errors.append(f"Duplicate public URL {doc.url}: {urls[doc.url]} and {doc.source_path}")
        urls[doc.url] = doc.source_path

        if not doc.url.startswith("/") or not doc.url.endswith("/"):
            errors.append(f"{doc.source_path}: url must be an absolute slash path ending in /")
        if not doc.title:
            errors.append(f"{doc.source_path}: title is required")
        if doc.visibility != "public":
            errors.append(f"{doc.source_path}: visibility must be public")
        if doc.status != "published":
            errors.append(f"{doc.source_path}: status must be published")
        if source == "vault" and not doc.created:
            errors.append(f"{doc.source_path}: created date is required")

        if source == "vault":
            if not doc.id or not is_uuidv7(doc.id):
                errors.append(f"{doc.source_path}: id must be a UUIDv7")
            if "migration_source" in doc.frontmatter or "source_path" in doc.frontmatter:
                errors.append(f"{doc.source_path}: migration provenance must not be public frontmatter")

        haystack = "\n".join([doc.body, yaml.safe_dump(doc.frontmatter, sort_keys=False)])
        for pattern in PRIVATE_PATTERNS:
            if pattern.search(haystack):
                errors.append(f"{doc.source_path}: private or legacy source reference found")
        for pattern in SECRET_PATTERNS:
            if pattern.search(haystack):
                errors.append(f"{doc.source_path}: possible secret found")

    allowed_internal = set(urls) | {"/", "/posts/", "/projects/", "/newsletters/", "/products/", "/cart/"}
    for doc in documents:
        for target in _internal_links(doc.body):
            if target not in allowed_internal:
                errors.append(f"{doc.source_path}: broken internal link {target}")

    if errors:
        raise PublicContentError("\n".join(errors))


def _iter_public_markdown(source_root: Path) -> Iterable[Path]:
    for collection in PUBLIC_TYPES:
        category_dir = source_root / collection
        if category_dir.exists():
            yield from sorted(category_dir.glob("*.md"))


def _load_markdown_file(path: Path, source_root: Path, source: str) -> Optional[PublicDocument]:
    text = path.read_text()
    frontmatter, body = parse_markdown(text)

    collection = path.parent.name
    if collection == "articles":
        collection = "posts"
    content_type = frontmatter.get("type") or PUBLIC_TYPES.get(collection)
    collection = TYPE_TO_COLLECTION.get(content_type, collection)
    slug = path.stem
    status = str(frontmatter.get("status", "published"))
    visibility = str(frontmatter.get("visibility", "public" if status == "published" else "private"))

    if status != "published" or visibility != "public":
        return None

    url = frontmatter.get("url") or _legacy_url(collection, slug)
    title = frontmatter.get("title") or slug.replace("-", " ").title()
    created = normalize_value(frontmatter.get("created") or frontmatter.get("date"))
    updated = normalize_value(frontmatter.get("updated") or frontmatter.get("date") or created)

    return PublicDocument(
        id=frontmatter.get("id"),
        type=content_type,
        collection=collection,
        slug=slug,
        title=str(title),
        url=str(url),
        created=created,
        updated=updated,
        status=status,
        visibility=visibility,
        body=body,
        frontmatter=dict(frontmatter),
        source_path=path,
        source=source,
    )


def _legacy_url(collection: str, slug: str) -> str:
    return f"/{collection}/{slug}/"


def _internal_links(body: str) -> List[str]:
    links: List[str] = []
    for match in LINK_RE.finditer(body):
        target = match.group(1).split()[0].strip()
        if not target.startswith("/") or target.startswith("//"):
            continue
        target = target.split("#", 1)[0].split("?", 1)[0]
        if not target.endswith("/"):
            target = f"{target}/"
        links.append(target)
    return links
