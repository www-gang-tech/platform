"""Evidence-backed natural-language questions over the private knowledge corpus.

`gang ask` is a query engine, not a chat surface. A question becomes a typed,
schema-validated query plan; deterministic code runs that plan against the
existing SQLite FTS index, entity mentions, and relationship assertions; the
result is a small bounded evidence set; and only then does a model write prose
over it. Every substantive claim carries a citation back to a canonical
document, and an answer the corpus cannot support says so.

No vector database, no embeddings, no hosted search, no graph database, and no
autonomous agents. The substrate already built does the retrieving.
"""

from .evidence import EvidenceBundle, EvidenceItem, build_bundle, extract_excerpts
from .plan import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    PLAN_VERSION,
    DateRange,
    QueryPlan,
    QueryPlanError,
    RelationshipFilter,
    validate_plan,
)
from .planner import (
    AnthropicQueryPlanner,
    DeterministicPlanner,
    PlanningResult,
    PlanOverrides,
    entity_catalog,
    merge_ai_plan,
)
from .retrieval import RetrievalError, Retriever, fts_match_expression
from .service import (
    RESULT_VERSION,
    AskError,
    AskOptions,
    AskService,
    citation_labels,
)
from .synthesis import (
    ANSWER_SCHEMA_VERSION,
    INSUFFICIENT_EVIDENCE,
    NO_SEARCHABLE_TERMS,
    AnthropicAnswerSynthesizer,
    SynthesisError,
    ambiguity_notice,
    deterministic_answer,
    validate_answer,
)
from .temporal import TemporalError, resolve_bound, resolve_question_range

__all__ = [
    "ANSWER_SCHEMA_VERSION",
    "AnthropicAnswerSynthesizer",
    "AnthropicQueryPlanner",
    "AskError",
    "AskOptions",
    "AskService",
    "DEFAULT_LIMIT",
    "DateRange",
    "DeterministicPlanner",
    "EvidenceBundle",
    "EvidenceItem",
    "INSUFFICIENT_EVIDENCE",
    "MAX_LIMIT",
    "NO_SEARCHABLE_TERMS",
    "PLAN_VERSION",
    "PlanOverrides",
    "PlanningResult",
    "QueryPlan",
    "QueryPlanError",
    "RESULT_VERSION",
    "RelationshipFilter",
    "RetrievalError",
    "Retriever",
    "SynthesisError",
    "TemporalError",
    "ambiguity_notice",
    "build_bundle",
    "citation_labels",
    "deterministic_answer",
    "entity_catalog",
    "extract_excerpts",
    "fts_match_expression",
    "merge_ai_plan",
    "resolve_bound",
    "resolve_question_range",
    "validate_answer",
    "validate_plan",
]
