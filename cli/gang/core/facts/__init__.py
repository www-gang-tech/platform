"""Generated evidence facts: explicit statements, materialized with their quotes.

Entity linking establishes that a document refers to someone. This layer
records what documents *state* — "Daniel Hirunrusme is a co-founder of GANG",
"Outer shipping carton applied in China" — as structured, cited, rebuildable
records in ``GANG_HOME/generated/evidence-facts.sqlite``. It never writes
canonical Markdown and never calls a model.
"""

from .model import (
    ALLOWED_METHODS,
    CONFIDENCE_HIGH,
    CONFIDENCE_MEDIUM,
    DECISION_STATUSES,
    EXTRACTOR_VERSION,
    METHOD_DETERMINISTIC,
    METHOD_LOCAL_MODEL,
    RELATION_PREDICATES,
    ClaimProposal,
    ClaimValidationError,
    DecisionRecord,
    EvidenceFact,
    quote_in_source,
    validate_proposal,
)
from .service import EvidenceFactService, entity_fingerprint, topic_terms
from .store import FactStore

__all__ = [
    "ALLOWED_METHODS",
    "CONFIDENCE_HIGH",
    "CONFIDENCE_MEDIUM",
    "ClaimProposal",
    "ClaimValidationError",
    "DECISION_STATUSES",
    "DecisionRecord",
    "EXTRACTOR_VERSION",
    "EvidenceFact",
    "EvidenceFactService",
    "FactStore",
    "METHOD_DETERMINISTIC",
    "METHOD_LOCAL_MODEL",
    "RELATION_PREDICATES",
    "entity_fingerprint",
    "quote_in_source",
    "topic_terms",
    "validate_proposal",
]
