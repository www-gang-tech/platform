"""Source adapters for private ingestion."""

from __future__ import annotations

import json
import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml

from .ids import normalize_file_identity, stable_source_id


SUPPORTED_FILE_SUFFIXES = {".md", ".txt", ".json", ".jsonl"}
MAX_SOURCE_BYTES = 10 * 1024 * 1024


@dataclass(frozen=True)
class SourceIdentity:
    source: str
    source_type: str
    source_id: str
    source_url: str
    title: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class FetchedSource:
    identity: SourceIdentity
    payload: bytes
    filename: str


@dataclass(frozen=True)
class NormalizedSource:
    title: str
    body: str
    participants: List[str] = field(default_factory=list)
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


class SourceAdapter(ABC):
    """Minimal interface future source adapters can implement."""

    @abstractmethod
    def discover(self) -> Iterable[Path]:
        """Return source handles this adapter can ingest."""

    @abstractmethod
    def identify(self, source: Path) -> SourceIdentity:
        """Return a stable source identity independent of canonical docs."""

    @abstractmethod
    def fetch(self, identity: SourceIdentity) -> FetchedSource:
        """Fetch raw source material."""

    @abstractmethod
    def normalize(self, fetched: FetchedSource) -> NormalizedSource:
        """Normalize raw source material into private canonical markdown."""


class FileAdapter(SourceAdapter):
    """Generic local file adapter."""

    source_type = "file"

    def __init__(self, path: Path | str, *, source_namespace: str = "local-file"):
        self.path = Path(path)
        self.source_namespace = source_namespace

    def discover(self) -> Iterable[Path]:
        _reject_traversal(self.path)
        if self.path.is_dir():
            for child in sorted(self.path.rglob("*")):
                if child.is_symlink():
                    raise ValueError(f"Unsafe symlink rejected: {child}")
                if child.is_file() and child.suffix.lower() in SUPPORTED_FILE_SUFFIXES:
                    _validate_source_file(child)
                    yield child
        elif self.path.is_file():
            _validate_source_file(self.path)
            yield self.path
        else:
            raise FileNotFoundError(self.path)

    def identify(self, source: Path) -> SourceIdentity:
        normalized = normalize_file_identity(source)
        return SourceIdentity(
            source=str(source),
            source_type=self.source_type,
            source_id=stable_source_id(self.source_type, self.source_namespace, normalized),
            source_url=f"local-source://{stable_source_id(self.source_type, self.source_namespace, normalized)}",
            title=source.stem.replace("-", " ").replace("_", " ").strip().title() or "Imported File",
            metadata={
                "source_namespace": self.source_namespace,
                "source_identity_hash": stable_source_id("identity", self.source_namespace, normalized),
                "source_name": source.name,
                "extension": source.suffix.lower(),
            },
        )

    def fetch(self, identity: SourceIdentity) -> FetchedSource:
        path = Path(identity.source)
        _validate_source_file(path)
        return FetchedSource(identity=identity, payload=path.read_bytes(), filename=path.name)

    def normalize(self, fetched: FetchedSource) -> NormalizedSource:
        suffix = Path(fetched.filename).suffix.lower()
        text = _decode_text_payload(fetched.payload)

        if suffix == ".md":
            title = _extract_markdown_title(text) or fetched.identity.title
            body = text.rstrip() + "\n"
        elif suffix == ".txt":
            title = _extract_text_title(text) or fetched.identity.title
            body = text.rstrip() + "\n"
        elif suffix == ".json":
            title = fetched.identity.title
            body = _normalize_json(text)
        elif suffix == ".jsonl":
            title = fetched.identity.title
            body = _normalize_jsonl(text)
        else:
            raise ValueError(f"Unsupported file type: {suffix}")

        return NormalizedSource(
            title=title,
            body=body,
            metadata={"adapter": "FileAdapter", **fetched.identity.metadata},
        )


class MeetingTranscriptAdapter(FileAdapter):
    """Local meeting transcript adapter."""

    source_type = "meeting"

    def __init__(self, path: Path | str, *, source_namespace: str = "local-meeting"):
        super().__init__(path, source_namespace=source_namespace)

    def normalize(self, fetched: FetchedSource) -> NormalizedSource:
        suffix = Path(fetched.filename).suffix.lower()
        text = _decode_text_payload(fetched.payload)

        if suffix == ".json":
            parsed = json.loads(text)
            return self._normalize_json_meeting(parsed, fetched)

        title = _extract_markdown_title(text) or _extract_text_title(text) or fetched.identity.title
        participants = _extract_participants(text)
        body = text.rstrip() + "\n"
        if not body.lstrip().startswith("#"):
            body = f"# {title}\n\n{body}"

        return NormalizedSource(
            title=title,
            body=body,
            participants=participants,
            metadata={"adapter": "MeetingTranscriptAdapter", **fetched.identity.metadata},
        )

    def _normalize_json_meeting(self, parsed: Any, fetched: FetchedSource) -> NormalizedSource:
        if not isinstance(parsed, dict):
            return NormalizedSource(
                title=fetched.identity.title,
                body=_normalize_json(json.dumps(parsed)),
                metadata={"adapter": "MeetingTranscriptAdapter", **fetched.identity.metadata},
            )

        title = str(parsed.get("title") or parsed.get("meeting_title") or fetched.identity.title)
        participants = parsed.get("participants") or []
        if isinstance(participants, str):
            participants = [p.strip() for p in participants.split(",") if p.strip()]

        transcript = parsed.get("transcript") or parsed.get("text") or parsed.get("body") or ""
        if isinstance(transcript, list):
            transcript = "\n".join(_format_transcript_item(item) for item in transcript)

        metadata = {
            key: value
            for key, value in parsed.items()
            if key not in {"title", "meeting_title", "participants", "transcript", "text", "body"}
        }
        body = f"# {title}\n\n"
        if participants:
            body += "## Participants\n\n" + "\n".join(f"- {p}" for p in participants) + "\n\n"
        body += "## Transcript\n\n" + str(transcript).rstrip() + "\n"

        return NormalizedSource(
            title=title,
            body=body,
            participants=[str(p) for p in participants],
            metadata={"adapter": "MeetingTranscriptAdapter", **fetched.identity.metadata, **metadata},
        )


def _extract_markdown_title(text: str) -> Optional[str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
                if frontmatter.get("title"):
                    return str(frontmatter["title"])
            except yaml.YAMLError:
                pass
    match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
    return match.group(1).strip() if match else None


def _extract_text_title(text: str) -> Optional[str]:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped[:100]
    return None


def _normalize_json(text: str) -> str:
    parsed = json.loads(text)
    pretty = json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=True)
    return f"# JSON Import\n\n```json\n{pretty}\n```\n"


def _normalize_jsonl(text: str) -> str:
    sections = ["# JSONL Import", ""]
    for index, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        parsed = json.loads(line)
        pretty = json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=True)
        sections.extend([f"## Record {index}", "", "```json", pretty, "```", ""])
    return "\n".join(sections).rstrip() + "\n"


def _extract_participants(text: str) -> List[str]:
    participants = set()
    frontmatter = {}
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            try:
                frontmatter = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                frontmatter = {}

    raw_participants = frontmatter.get("participants")
    if isinstance(raw_participants, list):
        participants.update(str(p).strip() for p in raw_participants if str(p).strip())
    elif isinstance(raw_participants, str):
        participants.update(p.strip() for p in raw_participants.split(",") if p.strip())

    for match in re.finditer(r"^(?:\*\*)?([A-Z][A-Za-z0-9 ._-]{1,60})(?:\*\*)?:\s+", text, re.MULTILINE):
        participants.add(match.group(1).strip())

    return sorted(participants)


def _format_transcript_item(item: Any) -> str:
    if isinstance(item, dict):
        speaker = item.get("speaker") or item.get("name")
        text = item.get("text") or item.get("body") or item.get("content") or ""
        return f"{speaker}: {text}" if speaker else str(text)
    return str(item)


def _reject_traversal(path: Path) -> None:
    if ".." in Path(os.fspath(path)).parts:
        raise ValueError(f"Path traversal rejected: {path}")


def _validate_source_file(path: Path) -> None:
    _reject_traversal(path)
    if path.is_symlink():
        raise ValueError(f"Unsafe symlink rejected: {path}")
    if path.suffix.lower() not in SUPPORTED_FILE_SUFFIXES:
        raise ValueError(f"Unsupported file type: {path.suffix}")
    size = path.stat().st_size
    if size > MAX_SOURCE_BYTES:
        raise ValueError(f"Oversized input rejected: {path} ({size} bytes)")


def _decode_text_payload(payload: bytes) -> str:
    if b"\x00" in payload:
        raise ValueError("Unsupported binary payload rejected")
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError("Unsupported binary payload rejected") from exc
