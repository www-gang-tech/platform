"""One turn of a conversation, end to end. Still strictly read-only.

`AskService` answers a question. `ConversationService` extends it to answer a
*turn*: it resolves what the question refers to, infers what kind of answer it
wants, researches under bounds, synthesizes under the matching epistemic
contract, validates the claim ledger, and folds the result into working memory
for the next turn.

The pipeline, in order:

    question
      → follow-up resolution against session state      (followup.py)
      → intent and answer policy                        (intent.py)
      → typed query plan, deterministic first           (planner.py, inherited)
      → bounded multi-step research                     (research.py, tools.py)
      → bounded evidence bundle                         (evidence.py)
      → source authority and staleness                  (authority.py, session.py)
      → policy-aware synthesis                          (answer.py)
      → validated claim ledger                          (ledger.py)
      → recorded turn                                   (session.py)

Everything `AskService` guarantees still holds, because this subclasses it and
adds no write path: no canonical document is opened for writing, the index is
opened read-only, and the only things written anywhere are the session file
and the answer cache, both private, both generated, both disposable. A user
correction does not edit the corpus; it becomes session context and an
explanation of what the corpus actually says (§32).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import affiliation as affiliation_module
from . import authority as authority_module
from . import followup as followup_module
from . import intent as intent_module
from . import synthesis
from .answer import (
    AnswerContext,
    ConversationSynthesizer,
    deterministic_conversation_answer,
    validate_conversation_answer,
)
from .evidence import EvidenceBundle, build_bundle
from .plan import DEFAULT_LIMIT
from .planner import PlanOverrides
from .research import AnthropicResearchDirector, ResearchLimits, ResearchLoop
from .service import AskError, AskOptions, AskService
from .session import Session, SessionStore
from .synthesis import SynthesisError
from .timeline import build_timeline, to_payload as timeline_payload
from .tools import ResearchTools


CONVERSATION_RESULT_VERSION = "1"

#: Bumped when any conversational prompt changes, so cached answers never
#: outlive the prompt that produced them (§36).
CONVERSATION_PROMPT_VERSION = "ask-conversation-1"

#: Code-owned. A user telling us a fact is wrong does not change the corpus,
#: and the reply should say so before it says anything else.
READ_ONLY_NOTICE = (
    "I can't change what the corpus says — `gang ask` is read-only, and canonical "
    "knowledge is only ever changed by an explicit ingestion or edit. I've noted your "
    "correction for this conversation and re-checked the evidence below."
)


@dataclass(frozen=True)
class ConversationOptions:
    use_ai: bool = True
    use_cache: bool = True
    persist: bool = True
    mode_override: Optional[str] = None
    show_research: bool = False


class ConversationService(AskService):
    """Multi-turn, research-driven `gang ask`."""

    def __init__(
        self,
        *,
        root_path: Path | str = Path("."),
        private_home: Path | str | None = None,
        synthesizer: Optional[Any] = None,
        query_planner: Optional[Any] = None,
        director: Optional[Any] = None,
        clock: Optional[Any] = None,
        limits: Optional[ResearchLimits] = None,
    ):
        super().__init__(
            root_path=root_path,
            private_home=private_home,
            synthesizer=synthesizer,
            query_planner=query_planner,
            clock=clock,
        )
        self.limits = (limits or ResearchLimits()).clamped()
        self.sessions = SessionStore(self.paths.sessions_path)
        self._director = director

    # ------------------------------------------------------------- session

    def start(self, session_id: Optional[str] = None) -> Session:
        return self.sessions.create(session_id)

    def resume(self, session_id: str) -> Session:
        return self.sessions.load(session_id)

    # ------------------------------------------------------------------ ask

    def converse(
        self,
        question: str,
        *,
        session: Optional[Session] = None,
        overrides: Optional[PlanOverrides] = None,
        options: Optional[ConversationOptions] = None,
    ) -> Dict[str, Any]:
        """Answer one turn and fold it into the session."""
        options = options or ConversationOptions()
        session = session if session is not None else self.start()
        text = (question or "").strip()
        if not text:
            raise AskError("Ask requires a non-empty question")

        # --- what does this question refer to? ------------------------------
        resolution = followup_module.resolve(text, session)
        if resolution.needs_clarification:
            return self._clarification_result(session, text, resolution, options)

        intent = intent_module.infer_intent(text, override_mode=options.mode_override)
        for assumption in resolution.assumptions:
            session.add_assumption(assumption)
        assumptions = [item.to_dict() for item in session.assumptions]

        # --- "show me the receipts" reopens the last answer, not the corpus --
        if intent.policy == intent_module.RECEIPTS and session.last_claims:
            return self._receipts_result(session, text, intent, resolution, options)

        # --- plan, deterministically first ----------------------------------
        overrides = self._overrides(overrides, resolution)
        planning = self._plan(
            resolution.retrieval_text or text,
            overrides,
            AskOptions(use_ai=options.use_ai),
        )

        # --- bounded research ------------------------------------------------
        research = self._research(text, planning, intent, session, options)

        bundle = build_bundle(
            text,
            research.rows,
            planning.plan,
            ambiguities=planning.ambiguities,
            max_excerpts=self.limits.max_excerpts_per_document,
        )

        # --- context around the evidence -------------------------------------
        current_state = authority_module.is_current_state_question(text, intent.policy)
        assessed = authority_module.assess(
            bundle.items,
            current_state_question=current_state,
            purpose=(
                authority_module.DEFINITION
                if intent.wants_identity
                else authority_module.CURRENT_STATE
            ),
        )
        stale = session.stale_snapshots(self.retriever.content_hashes(session.active_document_ids))
        records = self._records(research, bundle, intent)

        # --- synthesize and validate -----------------------------------------
        answer, meta = self._synthesize(
            AnswerContext(
                question=text,
                bundle=bundle,
                intent=intent,
                session_context=session.context_summary(),
                authority=authority_module.guidance(assessed),
                records=records,
                assumptions=assumptions,
                resolved_references=resolution.references,
                stale_evidence=stale,
            ),
            planning,
            options,
            assessed,
        )

        if intent.policy == intent_module.CORRECTION:
            answer = {**answer, "answer": f"{READ_ONLY_NOTICE}\n\n{answer['answer']}"}

        # --- remember ---------------------------------------------------------
        topics = followup_module.topics_from(planning.resolved_entities, planning.plan.text_queries)
        session.record_turn(
            question=text,
            resolved_question=resolution.retrieval_text or text,
            policy=intent.policy,
            mode=intent.mode,
            answer=answer["answer"],
            evidence=self._snapshot_rows(bundle, research.rows),
            claims=answer["claims"],
            entities=planning.resolved_entities,
            topics=resolution.carried_topics or topics,
            time_range=planning.plan.date_range.to_dict() if planning.plan.date_range else None,
        )
        if options.persist:
            self.sessions.save(session)

        return self._conversation_result(
            session=session,
            question=text,
            resolution=resolution,
            intent=intent,
            planning=planning,
            bundle=bundle,
            answer=answer,
            meta=meta,
            research=research,
            assessed=assessed,
            stale=stale,
            records=records,
            assumptions=assumptions,
            options=options,
        )

    # ------------------------------------------------------------- research

    def _research(self, question, planning, intent, session, options):
        loop = ResearchLoop(
            self._tools(),
            limits=self.limits,
            director=self._director_provider() if options.use_ai else None,
        )
        return loop.run(
            question=question,
            plan=planning.plan,
            intent=intent,
            resolved_entities=planning.resolved_entities,
            session_context=session.context_summary(),
        )

    def _tools(self) -> ResearchTools:
        return ResearchTools(
            self.retriever,
            registry_path=self.paths.registry_path,
            resolver=self._resolver(),
            entities=self._entity_records(),
        )

    def _home_company_known(self) -> bool:
        """Whether a canonical company record with an email domain exists.

        Without one, internal and external cannot be separated reliably, and
        the answer has to say so rather than band people anyway.
        """
        return any(
            record.type == "company"
            and getattr(record, "foundational", False)
            and getattr(record, "domains", None)
            for record in self._entity_records()
        )

    def _entity_records(self):
        """Canonical entity records, or nothing if the layer is unavailable."""
        try:
            return self._store().load_all()
        except Exception:  # noqa: BLE001 - a missing entity layer is not fatal
            return []

    def _records(self, research, bundle: EvidenceBundle, intent) -> Dict[str, Any]:
        """Structured material for synthesis, beyond the excerpts themselves."""
        records: Dict[str, Any] = {
            key: value for key, value in research.records.items() if value
        }
        if "participants" in records:
            # Wrapped with its standing rule, so the bands travel with the
            # warning that they are bands and not a roster.
            records["participants"] = affiliation_module.payload_from_dicts(
                records["participants"], home_known=self._home_company_known()
            )
        if intent.wants_timeline and bundle.items:
            # Built over the bundle rather than over raw rows, so the timeline
            # carries the same citation ids the answer will use.
            records["timeline"] = timeline_payload(build_timeline(bundle.items))
        return records

    # ------------------------------------------------------------ synthesis

    def _synthesize(self, context: AnswerContext, planning, options, assessed):
        bundle = context.bundle
        if bundle.empty:
            reason = "no-searchable-terms" if planning.plan.is_empty else "no-evidence"
            return (
                deterministic_conversation_answer(bundle, reason=reason, intent=context.intent),
                {"mode": "deterministic", "reason": reason, "cached": False},
            )
        if context.intent.listing or planning.listing_question:
            return (
                deterministic_conversation_answer(
                    bundle, reason="listing-question", intent=context.intent
                ),
                {"mode": "deterministic", "reason": "listing-question", "cached": False},
            )
        if not options.use_ai:
            return (
                deterministic_conversation_answer(
                    bundle, reason="ai-disabled", intent=context.intent
                ),
                {"mode": "deterministic", "reason": "ai-disabled", "cached": False},
            )

        synthesizer = self._conversation_synthesizer()
        if synthesizer is None:
            return (
                deterministic_conversation_answer(
                    bundle, reason="no-provider", intent=context.intent
                ),
                {"mode": "deterministic", "reason": "no-provider", "cached": False},
            )

        model = getattr(synthesizer, "model", "")
        key = self._conversation_cache_key(context, model)
        if options.use_cache:
            cached = self._cache_read(key)
            if cached is not None:
                return cached, {
                    "mode": "ai",
                    "provider": getattr(synthesizer, "provider_name", "unknown"),
                    "model": model,
                    "cached": True,
                }

        try:
            payload = synthesizer.synthesize(context)
        except SynthesisError as exc:
            raise AskError(str(exc)) from exc

        answer = validate_conversation_answer(
            payload,
            bundle,
            intent=context.intent,
            assumptions=context.assumptions,
            preference_note=authority_module.preference_note(assessed),
        )
        notice = synthesis.ambiguity_notice(bundle.ambiguities)
        if notice:
            answer = {**answer, "answer": f"{notice}\n\n{answer['answer']}"}
        if options.use_cache:
            self._cache_write(key, answer)
        return answer, {
            "mode": "ai",
            "provider": getattr(synthesizer, "provider_name", "unknown"),
            "model": model,
            "cached": False,
        }

    def _conversation_synthesizer(self):
        if self._synthesizer is not None:
            return self._synthesizer
        provider = ConversationSynthesizer()
        return provider if provider.has_credentials else None

    def _director_provider(self):
        if self._director is not None:
            return self._director
        provider = AnthropicResearchDirector()
        return provider if provider.has_credentials else None

    def _conversation_cache_key(self, context: AnswerContext, model: str) -> str:
        """Keyed on evidence, mode, session shape, assumptions, and prompt.

        Evidence hashes are in ``bundle.fingerprint()``, so changed evidence
        misses the cache rather than serving an answer about text that no
        longer exists.
        """
        payload = json.dumps(
            {
                "prompt": CONVERSATION_PROMPT_VERSION,
                "model": model,
                "evidence": context.bundle.fingerprint(),
                "mode": context.intent.mode,
                "policy": context.intent.policy,
                "question": context.question,
                "assumptions": [item.get("text", "") for item in context.assumptions],
                "topics": context.session_context.get("active_topics", []),
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    # --------------------------------------------------------------- shapes

    def _overrides(self, overrides: Optional[PlanOverrides], resolution) -> PlanOverrides:
        """Carry the conversation's entities into retrieval, without overriding."""
        base = overrides or PlanOverrides(limit=DEFAULT_LIMIT)
        if not resolution.carried_entity_ids:
            return base
        merged = list(base.entity_ids) + [
            value for value in resolution.carried_entity_ids if value not in base.entity_ids
        ]
        return PlanOverrides(
            since=base.since,
            until=base.until,
            document_types=base.document_types,
            source_types=base.source_types,
            entity_ids=merged,
            visibility=base.visibility,
            order=base.order,
            limit=base.limit,
        )

    def _snapshot_rows(self, bundle: EvidenceBundle, rows: Sequence[Dict[str, Any]]):
        """Evidence items enriched with the content hash, for session snapshots."""
        hashes = {row.get("document_id"): row.get("content_hash", "") for row in rows}
        return [
            {
                "document_id": item.document_id,
                "title": item.title,
                "source_type": item.source_type,
                "updated": item.updated,
                "source_ids": item.source_ids,
                "citation_id": item.citation_id,
                "excerpts": item.excerpts,
                "content_hash": hashes.get(item.document_id, ""),
            }
            for item in bundle.items
        ]

    def _conversation_result(self, **kwargs) -> Dict[str, Any]:
        session: Session = kwargs["session"]
        bundle: EvidenceBundle = kwargs["bundle"]
        answer = kwargs["answer"]
        research = kwargs["research"]
        options: ConversationOptions = kwargs["options"]

        # Provided by validation, which saw the model's own prose before any
        # code-owned label was attached to it.
        cited = set(answer.get("cited_citation_ids") or [])
        sources = [
            {**source, "cited": source["citation_id"] in cited} for source in bundle.sources()
        ]
        authority_by_id = {item.citation_id: item.to_dict() for item in kwargs["assessed"]}
        for source in sources:
            entry = authority_by_id.get(source["citation_id"])
            if entry:
                source["authority"] = entry

        uncertainties = [value for value in [answer.get("uncertainty")] if value]
        for item in kwargs["stale"]:
            uncertainties.append(
                f"{item['title'] or item['document_id']}: {item['reason'].replace('-', ' ')}."
            )

        result = {
            "version": CONVERSATION_RESULT_VERSION,
            "session_id": session.session_id,
            "turn": session.turn_count,
            "question": kwargs["question"],
            "resolved_question": kwargs["resolution"].retrieval_text or kwargs["question"],
            "intent": intent_module.describe(kwargs["intent"]),
            "answer": answer["answer"],
            "claims": answer["claims"],
            "claim_ledger": answer["claim_ledger"],
            "conflicts": answer["conflicts"],
            "uncertainties": uncertainties,
            "uncertainty": answer.get("uncertainty", ""),
            "inference_count": answer.get("inference_count", 0),
            "diagnostics": answer.get("diagnostics", {}),
            "insufficient_evidence": answer["insufficient_evidence"],
            "scenario_assumptions": kwargs["assumptions"],
            "sources": sources,
            "cited_source_count": len(cited),
            "excluded_sources": [item.to_dict() for item in bundle.excluded],
            "evidence": [item.to_dict() for item in bundle.items],
            "evidence_count": len(bundle.items),
            "temporal_ordering": bundle.temporal_ordering(),
            "stale_evidence": kwargs["stale"],
            "active_context": session.context_summary(),
            "resolved_references": kwargs["resolution"].references,
            "plan": kwargs["planning"].plan.to_dict(),
            "planner": kwargs["planning"].planner,
            "resolved_entities": kwargs["planning"].resolved_entities,
            "ambiguities": kwargs["planning"].ambiguities,
            "synthesis": kwargs["meta"],
            "notes": kwargs["planning"].notes,
            "dropped_citations": answer.get("dropped_citations", []),
            "rejected_fields": answer.get("rejected_fields", []),
            "rejected_claims": answer.get("rejected_claims", []),
            "grounding_warnings": answer.get("grounding_warnings", []),
            "ungrounded_premises": answer.get("ungrounded_premises", []),
            "softened_negatives": answer.get("softened_negatives", []),
            "clarification": "",
            "research": research.to_dict(),
            "research_limits": self.limits.to_dict(),
        }
        if kwargs["records"]:
            result["structured_records"] = kwargs["records"]
        if not options.show_research:
            # The per-step trace is private diagnostics. Round counts, refusals
            # and limits stay — they explain the answer — but the step-by-step
            # record is only emitted when it was asked for.
            result["research"] = {**research.to_dict(), "trace": []}
        return result

    # ----------------------------------------------------- special policies

    def _clarification_result(self, session, question, resolution, options) -> Dict[str, Any]:
        """Ask rather than guess. No retrieval, no model, nothing recorded."""
        return {
            "version": CONVERSATION_RESULT_VERSION,
            "session_id": session.session_id,
            "turn": session.turn_count,
            "question": question,
            "resolved_question": question,
            "intent": intent_module.describe(intent_module.infer_intent(question)),
            "answer": resolution.clarification,
            "clarification": resolution.clarification,
            "claims": [],
            "claim_ledger": {"version": "1", "claims": [], "rejected_claims": [], "warnings": []},
            "conflicts": [],
            "uncertainties": [],
            "uncertainty": "",
            "insufficient_evidence": False,
            "scenario_assumptions": [item.to_dict() for item in session.assumptions],
            "sources": [],
            "cited_source_count": 0,
            "excluded_sources": [],
            "evidence": [],
            "evidence_count": 0,
            "temporal_ordering": [],
            "stale_evidence": [],
            "active_context": session.context_summary(),
            "resolved_references": [],
            "plan": {},
            "planner": "none",
            "resolved_entities": [],
            "ambiguities": [],
            "synthesis": {"mode": "clarification", "reason": "ambiguous-reference", "cached": False},
            "notes": [],
            "dropped_citations": [],
            "rejected_fields": [],
            "rejected_claims": [],
            "grounding_warnings": [],
            "ungrounded_premises": [],
            "softened_negatives": [],
            "research": {"rounds": 0, "stopped_because": "clarification-needed", "trace": []},
            "research_limits": self.limits.to_dict(),
        }

    def _receipts_result(self, session, question, intent, resolution, options) -> Dict[str, Any]:
        """Re-present the previous answer's evidence. Deterministic by design.

        This is a provenance dump, not a question: the claims and their
        citations are already recorded, so the documents are re-read from the
        index — giving the user current source text rather than a stale copy —
        and no broad search runs (§31).
        """
        document_ids = [
            value for value in session.last_citation_map.values() if value
        ]
        rows = self.retriever.documents(document_ids)
        hashes = {row["document_id"]: row.get("content_hash", "") for row in rows}

        entries: List[Dict[str, Any]] = []
        lines: List[str] = ["Here's what the previous answer rested on."]
        for claim in session.last_claims:
            citations = claim.get("citations") or []
            if not citations:
                continue
            documents = []
            for citation in citations:
                document_id = session.last_citation_map.get(str(citation))
                row = next((item for item in rows if item["document_id"] == document_id), None)
                if row is None:
                    continue
                snapshot = session.snapshot_for(document_id)
                changed = bool(
                    snapshot and snapshot.content_hash and snapshot.content_hash != hashes.get(document_id, "")
                )
                documents.append(
                    {
                        "citation_id": citation,
                        "document_id": document_id,
                        "title": row["title"],
                        "source_type": row["source_type"],
                        "updated": row["updated"],
                        "source_ids": row["source_ids"],
                        "excerpt": _first_excerpt(row.get("body") or ""),
                        "source_changed_since": changed,
                    }
                )
            if not documents:
                continue
            entries.append({"claim": claim.get("text", ""), "type": claim.get("type", ""), "sources": documents})
            lines.append(f"\n{claim.get('text', '')}")
            for document in documents:
                marker = " (source has changed since)" if document["source_changed_since"] else ""
                lines.append(f"  [{document['citation_id']}] {document['title']}{marker}")
                if document["excerpt"]:
                    lines.append(f"      {document['excerpt']}")

        if not entries:
            lines = [
                "The previous answer didn't cite any evidence I can re-open — it was either "
                "a recommendation, an idea, or a statement the corpus didn't support."
            ]

        return {
            "version": CONVERSATION_RESULT_VERSION,
            "session_id": session.session_id,
            "turn": session.turn_count,
            "question": question,
            "resolved_question": question,
            "intent": intent_module.describe(intent),
            "answer": "\n".join(lines),
            "claims": [],
            "claim_ledger": {"version": "1", "claims": [], "rejected_claims": [], "warnings": []},
            "conflicts": [],
            "uncertainties": [],
            "uncertainty": "",
            "insufficient_evidence": not entries,
            "scenario_assumptions": [item.to_dict() for item in session.assumptions],
            "receipts": entries,
            "sources": [
                {
                    "citation_id": document["citation_id"],
                    "document_id": document["document_id"],
                    "title": document["title"],
                    "type": "",
                    "source_type": document["source_type"],
                    "visibility": "private",
                    "updated": document["updated"],
                    "source_ids": document["source_ids"],
                    "enrichment_status": "",
                    "extraction_quality": "readable",
                    "cited": True,
                }
                for entry in entries
                for document in entry["sources"]
            ],
            "cited_source_count": sum(len(entry["sources"]) for entry in entries),
            "excluded_sources": [],
            "evidence": [],
            "evidence_count": 0,
            "temporal_ordering": [],
            "stale_evidence": [],
            "active_context": session.context_summary(),
            "resolved_references": resolution.references,
            "plan": {},
            "planner": "none",
            "resolved_entities": [],
            "ambiguities": [],
            "synthesis": {"mode": "deterministic", "reason": "receipts", "cached": False},
            "notes": [],
            "dropped_citations": [],
            "rejected_fields": [],
            "rejected_claims": [],
            "grounding_warnings": [],
            "ungrounded_premises": [],
            "softened_negatives": [],
            "clarification": "",
            "research": {"rounds": 0, "stopped_because": "receipts-from-session", "trace": []},
            "research_limits": self.limits.to_dict(),
        }


def _first_excerpt(body: str, limit: int = 280) -> str:
    import re

    text = re.sub(r"\s+", " ", body or "").strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."
