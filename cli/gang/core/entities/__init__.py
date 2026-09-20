"""Stable entities and evidence-backed relationships over the knowledge corpus.

Canonical entity records are Markdown files under ``GANG_HOME/vault/{people,
companies,projects,products}``. Documents reference them through additive
``entity_refs`` frontmatter, and relationship assertions live with the document
that carries their evidence. SQLite only ever holds a rebuildable index.
"""

from .candidates import collect_candidates, summarize
from .documents import (
    EntityDocument,
    EntityDocumentStore,
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
    MergeConflictError,
    normalize_name,
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
    "Candidate",
    "DeterministicEntityProposer",
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
    "EntityProposalError",
    "EntityProposalService",
    "EntityRecord",
    "EntityResolver",
    "EntityService",
    "EntityStore",
    "EntityValidationError",
    "MergeConflictError",
    "PREDICATES",
    "PREDICATE_VOCABULARY_VERSION",
    "ProposalValidationError",
    "PublicDocumentError",
    "RESOLVED",
    "Resolution",
    "StaleProposalError",
    "UNRESOLVED",
    "build_entity_tables",
    "collect_candidates",
    "normalize_mention",
    "normalize_name",
    "normalize_relationship",
    "relationship_id",
    "summarize",
]
