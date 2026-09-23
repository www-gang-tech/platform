"""Central path resolution for durable private GANG state."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


GANG_HOME_ENV = "GANG_HOME"
DEFAULT_GANG_HOME = Path.home() / ".gang"
REPO_PUBLIC_VAULT = Path("brain/vault/public")


@dataclass(frozen=True)
class GangPaths:
    """Resolved repository and private-home paths.

    The repository owns code and explicitly public vault content. GANG_HOME owns
    private canonical documents plus generated/runtime state.
    """

    repo_root: Path
    home: Path

    @classmethod
    def from_env(
        cls,
        *,
        repo_root: Path | str = Path("."),
        gang_home: Path | str | None = None,
    ) -> "GangPaths":
        configured = gang_home if gang_home is not None else os.environ.get(GANG_HOME_ENV)
        home = _resolve_home(configured)
        return cls(repo_root=Path(repo_root).resolve(), home=home)

    @property
    def repo_public_vault(self) -> Path:
        return self.repo_root / REPO_PUBLIC_VAULT

    @property
    def private_vault(self) -> Path:
        return self.home / "vault"

    @property
    def inbox_path(self) -> Path:
        return self.private_vault / "inbox"

    @property
    def meetings_path(self) -> Path:
        return self.private_vault / "meetings"

    @property
    def emails_path(self) -> Path:
        return self.private_vault / "emails"

    @property
    def documents_path(self) -> Path:
        return self.private_vault / "documents"

    @property
    def raw_path(self) -> Path:
        return self.home / "raw"

    @property
    def blobs_path(self) -> Path:
        return self.home / "blobs"

    @property
    def generated_path(self) -> Path:
        return self.home / "generated"

    @property
    def index_path(self) -> Path:
        return self.generated_path / "brain.sqlite"

    @property
    def sessions_path(self) -> Path:
        """Conversational working memory. Private, disposable, never in git."""
        return self.home / "sessions"

    @property
    def access_path(self) -> Path:
        """Local access configuration. Private, never in git."""
        return self.home / "access"

    @property
    def principals_path(self) -> Path:
        return self.access_path / "principals.yml"

    @property
    def entity_profiles_path(self) -> Path:
        """Derived entity profiles. Generated, rebuildable, never canonical.

        Deliberately its own database rather than a table in ``brain.sqlite``:
        the knowledge index is dropped and rebuilt wholesale on every entity
        edit, and a profile that has to be rebuilt every time an alias changes
        is not a cache. Deleting this file loses nothing.
        """
        return self.generated_path / "entity-profiles.sqlite"

    @property
    def evidence_facts_path(self) -> Path:
        """Generated evidence facts and decision records. Rebuildable, never canonical.

        Its own database for the same reason as entity profiles: facts are
        invalidated per source document, while the knowledge index is rebuilt
        wholesale on every entity edit.
        """
        return self.generated_path / "evidence-facts.sqlite"

    @property
    def facts_overrides_path(self) -> Path:
        """Human suppressions of generated facts. Durable, private, never generated.

        Lives outside ``generated/`` so that deleting the generated store never
        deletes a person's decision to hide one of its claims.
        """
        return self.home / "facts" / "overrides.yml"

    @property
    def ask_cache_path(self) -> Path:
        """Disposable cache for `gang ask`. Private, generated, never canonical."""
        return self.generated_path / "ask-cache"

    @property
    def ingestion_path(self) -> Path:
        return self.home / "ingestion"

    @property
    def registry_path(self) -> Path:
        return self.ingestion_path / "registry.json"

    @property
    def gmail_path(self) -> Path:
        return self.ingestion_path / "gmail"

    @property
    def gmail_checkpoint_path(self) -> Path:
        return self.gmail_path / "checkpoint.json"

    @property
    def gmail_token_path(self) -> Path:
        return self.gmail_path / "token.json"

    @property
    def gmail_credentials_path(self) -> Path:
        return self.gmail_path / "oauth_client_secret.json"

    @property
    def drive_path(self) -> Path:
        return self.ingestion_path / "drive"

    @property
    def drive_checkpoint_path(self) -> Path:
        return self.drive_path / "checkpoint.json"

    @property
    def drive_token_path(self) -> Path:
        return self.drive_path / "token.json"

    @property
    def drive_credentials_path(self) -> Path:
        return self.drive_path / "oauth_client_secret.json"

    @property
    def enrichment_path(self) -> Path:
        return self.home / "enrichment"

    @property
    def entities_generated_path(self) -> Path:
        """Generated entity proposals and audit trail (never canonical)."""
        return self.home / "entities"

    @property
    def entity_proposals_path(self) -> Path:
        return self.entities_generated_path / "proposals"

    def entity_vault_path(self, directory: str) -> Path:
        """Canonical entity records live inside the private vault, one dir per type."""
        return self.private_vault / directory

    def display_home(self) -> str:
        default = DEFAULT_GANG_HOME.expanduser()
        try:
            if self.home == default.resolve():
                return "~/.gang"
        except OSError:
            pass
        return self.home.as_posix()


def _resolve_home(value: Path | str | None) -> Path:
    raw = Path(value).expanduser() if value else DEFAULT_GANG_HOME.expanduser()
    if raw.is_absolute():
        return raw.resolve()
    return (Path.cwd() / raw).resolve()
