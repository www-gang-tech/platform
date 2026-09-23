"""Stable entities and evidence-backed relationships over the knowledge corpus.

Canonical entity records are Markdown files under ``GANG_HOME/vault/{people,
companies,projects,products}``. Documents reference them through additive
``entity_refs`` frontmatter, and relationship assertions live with the document
that carries their evidence. SQLite only ever holds a rebuildable index.
"""

from .backfill import (
    BACKFILL_ENTITY_TYPES,
    REASON_CANONICAL_NAME,
    REASON_VERIFIED_DOMAIN,
    REASON_VERIFIED_EMAIL,
    BackfillEntityReport,
    run_backfill,
)
from .candidates import collect_candidates, summarize
from .documents import (
    EntityDocument,
    EntityDocumentStore,
    MalformedDocument,
    PublicDocumentError,
    normalize_mention,
    normalize_relationship,
    relationship_id,
)
from .graph import ENTITY_SCHEMA_SQL, EntityGraph, build_entity_tables
from .model import (
    ENTITY_DIRECTORIES,
    ENTITY_SCHEMA_VERSION,
    ENTITY_TYPES,
    PREDICATE_VOCABULARY_VERSION,
    PREDICATES,
    AliasCollisionError,
    DuplicateEntityError,
    EntityError,
    EntityNotFoundError,
    EntityRecord,
    EntityValidationError,
    MarkdownParseError,
    MergeConflictError,
    normalize_name,
)
from .profiles import (
    PROFILE_BUILDER_VERSION,
    DerivedProfile,
    EntityProfileService,
    ProfileStatement,
    ProfileStore,
    build_profile,
)
from .proposals import (
    AIProviderError,
    AnthropicEntityProposer,
    DeterministicEntityProposer,
    EntityProposalError,
    EntityProposalService,
    ProposalValidationError,
    StaleProposalError,
)
from .resolver import AMBIGUOUS, RESOLVED, UNRESOLVED, Candidate, EntityResolver, Resolution
from .service import EntityService
from .store import EntityStore

__all__ = [
    "AIProviderError",
    "AMBIGUOUS",
    "AliasCollisionError",
    "AnthropicEntityProposer",
    "BACKFILL_ENTITY_TYPES",
    "BackfillEntityReport",
    "Candidate",
    "DeterministicEntityProposer",
    "DerivedProfile",
    "DuplicateEntityError",
    "ENTITY_DIRECTORIES",
    "ENTITY_SCHEMA_SQL",
    "ENTITY_SCHEMA_VERSION",
    "ENTITY_TYPES",
    "EntityDocument",
    "EntityDocumentStore",
    "EntityError",
    "EntityGraph",
    "EntityNotFoundError",
    "EntityProfileService",
    "EntityProposalError",
    "EntityProposalService",
    "EntityRecord",
    "EntityResolver",
    "EntityService",
    "EntityStore",
    "EntityValidationError",
    "MalformedDocument",
    "MarkdownParseError",
    "MergeConflictError",
    "PREDICATES",
    "PREDICATE_VOCABULARY_VERSION",
    "PROFILE_BUILDER_VERSION",
    "ProfileStatement",
    "ProfileStore",
    "ProposalValidationError",
    "PublicDocumentError",
    "REASON_CANONICAL_NAME",
    "REASON_VERIFIED_DOMAIN",
    "REASON_VERIFIED_EMAIL",
    "RESOLVED",
    "Resolution",
    "StaleProposalError",
    "UNRESOLVED",
    "build_entity_tables",
    "build_profile",
    "collect_candidates",
    "normalize_mention",
    "normalize_name",
    "normalize_relationship",
    "relationship_id",
    "run_backfill",
    "summarize",
]
