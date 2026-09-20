"""Evidence-backed natural-language questions over the private knowledge corpus.

`gang ask` is a query engine with a conversation on top of it, not a chat
surface with a search tool bolted on. A question becomes a typed,
schema-validated query plan; deterministic code runs that plan against the
existing SQLite FTS index, entity mentions, and relationship assertions;
bounded multi-step research may read further using a small vocabulary of typed
read-only tools; and only then does a model write prose over the result. Every
substantive claim carries a citation back to a canonical document, and an
answer the corpus cannot support says so.

Two rules govern everything here:

    GANG may generate new ideas. It may not generate new company facts.
    Conversation state is working memory, not evidence.

Recommendations and ideas may be genuinely novel, and are typed as such in the
claim ledger so they can never be mistaken for something the company decided.
Conversation state resolves "it" and "that"; it is never a source.

No vector database, no embeddings, no hosted search, no graph database, no web
access, and no autonomous agents. The substrate already built does the
retrieving, and `ask` never writes to it.
"""

from .answer import (
    CONVERSATION_ANSWER_VERSION,
    AnswerContext,
    ConversationSynthesizer,
    deterministic_conversation_answer,
    system_prompt,
    validate_conversation_answer,
)
from .authority import (
    DEFAULT_RANKS,
    ROLES,
    SourceAuthority,
    assess as assess_authority,
    classify as classify_source,
    is_current_state_question,
)
from .conversation import (
    CONVERSATION_PROMPT_VERSION,
    CONVERSATION_RESULT_VERSION,
    ConversationOptions,
    ConversationService,
)
from .diagnostics import (
    CHECKS,
    GroundingWarning,
    describe as describe_warning,
    describe_all as describe_warnings,
    normalize as normalize_warning,
    warning as grounding_warning,
)
from .evidence import EvidenceBundle, EvidenceItem, build_bundle, extract_excerpts
from .followup import Resolution, extract_assumptions, resolve as resolve_followup
from .intent import (
    ADVISORY,
    ADVISORY_MODE,
    COMPARE,
    CORRECTION,
    DECISION,
    DISCOVER,
    EVIDENCE,
    EXPLAIN,
    IDEATE,
    IDEATION,
    LOOKUP,
    MODES,
    PLAN,
    POLICIES,
    RECEIPTS,
    REPORT,
    STATUS,
    TIMELINE,
    Intent,
    infer_intent,
)
from .ledger import (
    CLAIM_TYPES,
    FACT,
    IDEA,
    LEDGER_VERSION,
    RECOMMENDATION,
    SCENARIO,
    SYNTHESIS,
    UNCERTAINTY,
    Claim,
    LedgerResult,
    validate_ledger,
)
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
from .research import (
    DECISIONS,
    ENOUGH_EVIDENCE,
    AnthropicResearchDirector,
    ResearchLimits,
    ResearchLoop,
    ResearchResult,
    refine_plan,
    validate_step,
)
from .retrieval import RetrievalError, Retriever, fts_match_expression
from .service import (
    RESULT_VERSION,
    AskError,
    AskOptions,
    AskService,
    citation_labels,
)
from .session import (
    SESSION_VERSION,
    Assumption,
    EvidenceSnapshot,
    Session,
    SessionError,
    SessionStore,
    Turn,
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
from .timeline import TimelineItem, build_timeline, gaps as timeline_gaps
from .tools import (
    ALLOWED_TOOLS,
    DENIED_TOOLS,
    TOOLS,
    ResearchTools,
    ToolError,
    ToolResult,
    catalog as tool_catalog,
)

__all__ = [
    "ADVISORY",
    "ADVISORY_MODE",
    "ALLOWED_TOOLS",
    "ANSWER_SCHEMA_VERSION",
    "AnswerContext",
    "AnthropicAnswerSynthesizer",
    "AnthropicQueryPlanner",
    "AnthropicResearchDirector",
    "AskError",
    "AskOptions",
    "AskService",
    "Assumption",
    "CHECKS",
    "CLAIM_TYPES",
    "COMPARE",
    "CONVERSATION_ANSWER_VERSION",
    "CONVERSATION_PROMPT_VERSION",
    "CONVERSATION_RESULT_VERSION",
    "CORRECTION",
    "Claim",
    "ConversationOptions",
    "ConversationService",
    "ConversationSynthesizer",
    "DECISION",
    "DECISIONS",
    "DEFAULT_LIMIT",
    "DEFAULT_RANKS",
    "DENIED_TOOLS",
    "DISCOVER",
    "DateRange",
    "DeterministicPlanner",
    "ENOUGH_EVIDENCE",
    "EVIDENCE",
    "EXPLAIN",
    "EvidenceBundle",
    "EvidenceItem",
    "EvidenceSnapshot",
    "FACT",
    "GroundingWarning",
    "IDEA",
    "IDEATE",
    "IDEATION",
    "INSUFFICIENT_EVIDENCE",
    "Intent",
    "LEDGER_VERSION",
    "LOOKUP",
    "LedgerResult",
    "MAX_LIMIT",
    "MODES",
    "NO_SEARCHABLE_TERMS",
    "PLAN",
    "PLAN_VERSION",
    "POLICIES",
    "PlanOverrides",
    "PlanningResult",
    "QueryPlan",
    "QueryPlanError",
    "RECEIPTS",
    "RECOMMENDATION",
    "REPORT",
    "RESULT_VERSION",
    "ROLES",
    "RelationshipFilter",
    "ResearchLimits",
    "ResearchLoop",
    "ResearchResult",
    "ResearchTools",
    "Resolution",
    "RetrievalError",
    "Retriever",
    "SCENARIO",
    "SESSION_VERSION",
    "STATUS",
    "SYNTHESIS",
    "Session",
    "SessionError",
    "SessionStore",
    "SourceAuthority",
    "SynthesisError",
    "TIMELINE",
    "TOOLS",
    "TemporalError",
    "TimelineItem",
    "ToolError",
    "ToolResult",
    "Turn",
    "UNCERTAINTY",
    "ambiguity_notice",
    "assess_authority",
    "build_bundle",
    "build_timeline",
    "citation_labels",
    "classify_source",
    "describe_warning",
    "describe_warnings",
    "deterministic_answer",
    "deterministic_conversation_answer",
    "entity_catalog",
    "extract_assumptions",
    "extract_excerpts",
    "fts_match_expression",
    "grounding_warning",
    "infer_intent",
    "is_current_state_question",
    "merge_ai_plan",
    "normalize_warning",
    "refine_plan",
    "resolve_bound",
    "resolve_followup",
    "resolve_question_range",
    "system_prompt",
    "timeline_gaps",
    "tool_catalog",
    "validate_answer",
    "validate_conversation_answer",
    "validate_ledger",
    "validate_plan",
    "validate_step",
]
