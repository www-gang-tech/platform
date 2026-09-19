"""Identifier helpers for ingestion."""

import hashlib
import secrets
import re
import time
import uuid
from pathlib import Path


def content_sha256(payload: bytes) -> str:
    """Return the hex SHA-256 hash for source content."""
    return hashlib.sha256(payload).hexdigest()


def stable_source_id(source_type: str, namespace: str, identity: str) -> str:
    """Create a stable source ID from type, namespace, and normalized identity."""
    digest = hashlib.sha256(f"{source_type}:{namespace}:{identity}".encode("utf-8")).hexdigest()
    return f"{source_type}_{digest[:32]}"


def normalize_file_identity(path: Path) -> str:
    """Normalize a local path for source identity without using the filename alone."""
    return str(path.expanduser().resolve())


def slugify(value: str, fallback: str = "untitled") -> str:
    slug = re.sub(r"[^\w\s-]", "", value.lower())
    slug = re.sub(r"[-\s]+", "-", slug).strip("-")
    return slug[:100] or fallback


def uuid7() -> str:
    """Generate an RFC 9562 UUIDv7 identifier without extra dependencies."""
    timestamp_ms = int(time.time() * 1000)
    random_bits = secrets.randbits(74)

    value = (timestamp_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= ((random_bits >> 62) & 0xFFF) << 64
    value |= 0b10 << 62
    value |= random_bits & ((1 << 62) - 1)

    return str(uuid.UUID(int=value))
