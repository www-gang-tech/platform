"""Shared website-file access for Studio and the in-page editor.

Reads and writes stay inside the canonical public vault. Body edits keep the
existing frontmatter bytes, including unknown fields. Saves are local only.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .content_loader import parse_markdown
from .paths import GangPaths

PROTECTED_FRONTMATTER = ("id", "url", "created", "date")
VISUAL_UNSAFE_RE = re.compile(
    r"(```|~~~|^\s*\|.+\|\s*$|^\s*<[a-zA-Z]|\[\^[^\]]+\]|^\s*\[[^\]]+\]:\s+\S+)",
    re.MULTILINE,
)


class FileAccessError(Exception):
    """Raised when a website file cannot be read or written."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class ConflictError(FileAccessError):
    """Raised when the on-disk revision does not match the editor's hash."""

    def __init__(self, message: str, current: "WebsiteFile"):
        super().__init__(message, status_code=409)
        self.current = current


@dataclass(frozen=True)
class WebsiteFile:
    relative_path: str
    text: str
    body: str
    frontmatter: Dict[str, Any]
    revision: str
    visual_safe: bool

    def to_payload(self) -> Dict[str, Any]:
        return {
            "path": self.relative_path,
            "text": self.text,
            "body": self.body,
            "frontmatter": self.frontmatter,
            "revision": self.revision,
            "visual_safe": self.visual_safe,
            "title": self.frontmatter.get("title") or Path(self.relative_path).stem,
            "status": self.frontmatter.get("status"),
            "url": self.frontmatter.get("url"),
        }


def website_root(repo_root: Path | str = ".") -> Path:
    return GangPaths.from_env(repo_root=repo_root).repo_public_vault


def revision_for(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_frontmatter_raw(text: str) -> tuple[str, str]:
    """Return (header including fences, body) without rewriting YAML."""
    if not text.startswith("---"):
        return "", text
    closer = text.find("\n---", 3)
    if closer < 0:
        return "", text
    header_end = closer + 4
    return text[:header_end], text[header_end:]


def visual_editor_safe(body: str) -> bool:
    return VISUAL_UNSAFE_RE.search(body) is None


def resolve_website_path(root: Path, relative_path: str) -> Path:
    if not relative_path or relative_path.startswith("/") or "\\" in relative_path:
        raise FileAccessError("Invalid file path")
    candidate = (root / relative_path).resolve()
    root_resolved = root.resolve()
    if not _is_within(candidate, root_resolved):
        raise FileAccessError("Path is outside the website content directory")
    if candidate.suffix != ".md":
        raise FileAccessError("Only Markdown files can be edited")
    return candidate


def list_website_files(root: Path) -> List[Dict[str, Any]]:
    if not root.exists():
        return []
    files = []
    for path in sorted(root.rglob("*.md")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        text = path.read_text(encoding="utf-8")
        frontmatter, _body = parse_markdown(text)
        files.append(
            {
                "path": relative,
                "type": path.parent.name,
                "name": path.stem,
                "title": frontmatter.get("title") or path.stem,
                "status": frontmatter.get("status", "unknown"),
                "url": frontmatter.get("url"),
                "draft": str(frontmatter.get("status", "published")) != "published"
                or str(frontmatter.get("visibility", "public")) != "public",
            }
        )
    return files


def read_website_file(root: Path, relative_path: str) -> WebsiteFile:
    path = resolve_website_path(root, _ensure_markdown(relative_path))
    if not path.exists():
        raise FileAccessError("File not found", status_code=404)
    text = path.read_text(encoding="utf-8")
    frontmatter, body = parse_markdown(text)
    return WebsiteFile(
        relative_path=path.relative_to(root.resolve()).as_posix(),
        text=text,
        body=body,
        frontmatter=dict(frontmatter),
        revision=revision_for(text),
        visual_safe=visual_editor_safe(body),
    )


def save_website_file(
    root: Path,
    relative_path: str,
    *,
    revision: str,
    body: Optional[str] = None,
    text: Optional[str] = None,
) -> WebsiteFile:
    current = read_website_file(root, relative_path)
    if not revision:
        raise FileAccessError("A revision hash is required to save")
    if revision != current.revision:
        raise ConflictError(
            "This file changed in another editor. Your unsaved text was not overwritten.",
            current=current,
        )

    if body is not None:
        header, _old_body = split_frontmatter_raw(current.text)
        next_text = f"{header}{body}" if header else body
    elif text is not None:
        next_text = _restore_protected_frontmatter(current.text, text)
    else:
        raise FileAccessError("Save requires body or text")

    if next_text != current.text:
        path = resolve_website_path(root, current.relative_path)
        path.write_text(next_text, encoding="utf-8")
    return read_website_file(root, current.relative_path)


def save_payload_from_request(root: Path, relative_path: str, raw_body: str, content_type: str, if_match: str = "") -> WebsiteFile:
    payload: Dict[str, Any]
    if "json" in (content_type or "").lower():
        try:
            payload = json.loads(raw_body) if raw_body else {}
        except json.JSONDecodeError as exc:
            raise FileAccessError("Save body must be JSON") from exc
    else:
        payload = {"body": raw_body, "revision": if_match}

    revision = str(payload.get("revision") or if_match or "")
    if "body" in payload and payload.get("text") is None:
        return save_website_file(root, relative_path, revision=revision, body=payload.get("body"))
    return save_website_file(root, relative_path, revision=revision, text=payload.get("text"))


def _ensure_markdown(relative_path: str) -> str:
    cleaned = relative_path.lstrip("/")
    if cleaned.endswith(".md"):
        return cleaned
    return f"{cleaned}.md"


def _is_within(path: Path, root: Path) -> bool:
    try:
        return path.is_relative_to(root)
    except AttributeError:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False


def _restore_protected_frontmatter(original: str, incoming: str) -> str:
    original_fm, _ = parse_markdown(original)
    incoming_fm, incoming_body = parse_markdown(incoming)
    if not original_fm:
        return incoming
    changed = False
    for key in PROTECTED_FRONTMATTER:
        if key in original_fm and incoming_fm.get(key) != original_fm[key]:
            incoming_fm[key] = original_fm[key]
            changed = True
    for key, value in original_fm.items():
        if key not in incoming_fm:
            incoming_fm[key] = value
            changed = True
    if not changed:
        return incoming
    from .content_loader import dump_markdown

    return dump_markdown(incoming_fm, incoming_body)
