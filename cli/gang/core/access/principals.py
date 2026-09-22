"""Minimal local principal directory for owner-trust HTTP access.

Stage 2 deliberately has no generalized RBAC. Every principal in this file is
trusted for the full corpus; the directory only answers two questions:
"who owns this bearer token?" and "where should this person's sessions live?"
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


FULL_CORPUS_SCOPE = "full"
PRINCIPALS_VERSION = 1
_PRINCIPAL_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,62}$")
_SHA256_HEX = re.compile(r"^[a-f0-9]{64}$")


class PrincipalError(ValueError):
    """Raised when the local principal directory is malformed."""


@dataclass(frozen=True)
class TokenRecord:
    label: str
    sha256: str
    created: str

    @classmethod
    def from_dict(cls, value: Any) -> "TokenRecord":
        if not isinstance(value, dict):
            raise PrincipalError("Token record must be an object")
        label = _text(value.get("label"))
        digest = _text(value.get("sha256")).lower()
        created = _text(value.get("created"))
        if not label:
            raise PrincipalError("Token label is required")
        if not _SHA256_HEX.fullmatch(digest):
            raise PrincipalError("Token sha256 must be a full SHA-256 digest")
        if not created:
            raise PrincipalError("Token created timestamp is required")
        return cls(label=label, sha256=digest, created=created)

    def to_dict(self) -> Dict[str, str]:
        return {"label": self.label, "sha256": self.sha256, "created": self.created}


@dataclass(frozen=True)
class Principal:
    principal_id: str
    display_name: str
    scope: str = FULL_CORPUS_SCOPE
    tokens: tuple[TokenRecord, ...] = ()

    @classmethod
    def from_dict(cls, value: Any) -> "Principal":
        if not isinstance(value, dict):
            raise PrincipalError("Principal must be an object")
        principal_id = _text(value.get("id"))
        if not is_valid_principal_id(principal_id):
            raise PrincipalError(f"Invalid principal id: {principal_id!r}")
        display_name = _text(value.get("name"))
        if not display_name:
            raise PrincipalError("Principal name is required")
        scope = _text(value.get("scope")) or FULL_CORPUS_SCOPE
        if scope != FULL_CORPUS_SCOPE:
            raise PrincipalError("Stage 2 supports only full corpus scope")
        tokens = tuple(TokenRecord.from_dict(item) for item in value.get("tokens") or [])
        return cls(
            principal_id=principal_id,
            display_name=display_name,
            scope=scope,
            tokens=tokens,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.principal_id,
            "name": self.display_name,
            "scope": self.scope,
            "tokens": [token.to_dict() for token in self.tokens],
        }


class PrincipalDirectory:
    """YAML-backed directory at ``GANG_HOME/access/principals.yml``."""

    def __init__(self, path: Path | str):
        self.path = Path(path)

    def load(self) -> List[Principal]:
        if not self.path.exists():
            raise PrincipalError("Principal directory is missing")
        self._ensure_private_mode()
        data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise PrincipalError("Principal directory must be an object")
        if data.get("version") != PRINCIPALS_VERSION:
            raise PrincipalError("Unsupported principal directory version")
        principals = [Principal.from_dict(item) for item in data.get("principals") or []]
        seen = set()
        for principal in principals:
            if principal.principal_id in seen:
                raise PrincipalError(f"Duplicate principal id: {principal.principal_id}")
            seen.add(principal.principal_id)
        return principals

    def save(self, principals: List[Principal]) -> None:
        seen = set()
        for principal in principals:
            if principal.principal_id in seen:
                raise PrincipalError(f"Duplicate principal id: {principal.principal_id}")
            seen.add(principal.principal_id)
        payload = {
            "version": PRINCIPALS_VERSION,
            "principals": [principal.to_dict() for principal in principals],
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".yml.tmp")
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            yaml.safe_dump(payload, handle, sort_keys=False)
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        temporary.replace(self.path)
        self._ensure_private_mode()

    def add_principal(self, principal_id: str, display_name: str) -> Principal:
        if not is_valid_principal_id(principal_id):
            raise PrincipalError(f"Invalid principal id: {principal_id!r}")
        display_name = _text(display_name)
        if not display_name:
            raise PrincipalError("Principal name is required")
        try:
            principals = self.load()
        except PrincipalError:
            if self.path.exists():
                raise
            principals = []
        if any(item.principal_id == principal_id for item in principals):
            raise PrincipalError(f"Principal already exists: {principal_id}")
        principal = Principal(
            principal_id=principal_id,
            display_name=display_name,
            scope=FULL_CORPUS_SCOPE,
            tokens=(),
        )
        self.save([*principals, principal])
        return principal

    def issue_token(self, principal_id: str, label: str) -> str:
        label = _text(label)
        if not label:
            raise PrincipalError("Token label is required")
        principals = self.load()
        token = secrets.token_urlsafe(32)
        digest = sha256_token(token)
        updated = []
        found = False
        for principal in principals:
            if principal.principal_id != principal_id:
                updated.append(principal)
                continue
            found = True
            record = TokenRecord(label=label, sha256=digest, created=_now())
            updated.append(
                Principal(
                    principal_id=principal.principal_id,
                    display_name=principal.display_name,
                    scope=principal.scope,
                    tokens=(*principal.tokens, record),
                )
            )
        if not found:
            raise PrincipalError(f"Unknown principal: {principal_id}")
        self.save(updated)
        return token

    def resolve_token(self, token: str) -> Optional[Principal]:
        supplied = sha256_token(token)
        for principal in self.load():
            for record in principal.tokens:
                if hmac.compare_digest(supplied, record.sha256):
                    return principal
        return None

    def _ensure_private_mode(self) -> None:
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass


def is_valid_principal_id(value: str) -> bool:
    return bool(_PRINCIPAL_ID.fullmatch(value or ""))


def sha256_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value: Any) -> str:
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value).strip()
