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
opened read-only, and the only things written anywhere are the session file,
the answer cache, the derived entity-profile cache, and the generated
evidence-facts store — all private, all generated, all disposable. A user correction does not edit the corpus; it
becomes session context and an explanation of what the corpus actually says
(§32).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from core.ai_provider import ProviderError
from core.entities.profiles import PREDICATE_PHRASES, EntityProfileService
from core.facts import EvidenceFactService
from core.facts.model import quote_in_source, readable
from core.source_classes import SOURCE_DESCRIPTIONS

from . import affiliation as affiliation_module
from . import authority as authority_module
from . import deterministic as deterministic_module
from . import disclosure
from . import followup as followup_module
from . import intent as intent_module
from . import ledger as ledger_module
from . import schema as schema_module
from . import synthesis
from .answer import (
    AnswerContext,
    ConversationSynthesizer,
    deterministic_conversation_answer,
    validate_conversation_answer,
)
from .evidence import EvidenceBundle, build_bundle
from .evidence_packet import estimate_tokens, select_for_local_synthesis
from .plan import DEFAULT_LIMIT
from .planner import PlanOverrides
from .research import AnthropicResearchDirector, ResearchLimits, ResearchLoop, ResearchResult
from .service import AskError, AskOptions, AskService
from .session import Session, SessionStore
from .synthesis import SynthesisError
from .timeline import build_timeline, to_payload as timeline_payload
from .tools import ResearchTools, ToolError, ToolResult


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
    provider: Optional[str] = None
    model: Optional[str] = None
    premium: bool = False
    local_only: Optional[bool] = None
    #: Who "I" and "me" are for this turn: the authenticated principal's name
    #: for the web service, the sole configured principal for the CLI. Only
    #: ever used to scope a first-person question; never a retrieval filter.
    principal_name: Optional[str] = None


def _preference_within_packet(assessed, packet_assessed):
    """Move the source preference onto a document the answer actually read.

    Roles and ranks are properties of a document and stay as they are for every
    retrieved source. Only the "preferred" mark moves, because that mark is a
    statement about the answer in front of the reader.
    """
    preferred = {entry.citation_id: entry for entry in packet_assessed if entry.preferred}
    if not preferred:
        return [replace(entry, preferred=False, reason="") for entry in assessed]
    return [
        preferred.get(entry.citation_id) or replace(entry, preferred=False, reason="")
        for entry in assessed
    ]


class ConversationService(AskService):
    """Multi-turn, research-driven `gang ask`."""

    def __init__(
        self,
        *,
        root_path: Path | str = Path("."),
        private_home: Path | str | None = None,
        retriever: Optional[Any] = None,
        synthesizer: Optional[Any] = None,
        query_planner: Optional[Any] = None,
        director: Optional[Any] = None,
        clock: Optional[Any] = None,
        limits: Optional[ResearchLimits] = None,
    ):
        super().__init__(
            root_path=root_path,
            private_home=private_home,
            retriever=retriever,
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
        self._provider_calls = []
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
            AskOptions(
                # Ownership, definition, and decision questions are answered
                # by code-owned primitives that read their own evidence; a
                # model-proposed plan would change nothing they do, and a
                # factual answer must not cost a model call.
                use_ai=options.use_ai
                and not intent.wants_assignments
                and not intent.wants_identity
                and intent.policy != intent_module.DECISION,
                provider=options.provider,
                model=options.model,
                premium=options.premium,
                local_only=options.local_only,
            ),
        )

        # --- bounded research ------------------------------------------------
        research = self._research(text, planning, intent, session, options)
        for call in research.provider_calls:
            self._append_provider_call(call)
        if research.stopped_because == "provider-timeout":
            raise AskError(
                "AI provider timed out during research. No additional model calls were made.",
                provider_calls=self._provider_calls,
            )

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
        answer, meta, assessed = self._synthesize(
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
            current_state=current_state,
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
        deterministic = self._deterministic_research(question, planning, intent, options)
        if deterministic is not None:
            return deterministic

        loop = ResearchLoop(
            self._tools(),
            limits=self.limits,
            director=self._director_provider(options) if options.use_ai else None,
        )
        return loop.run(
            question=question,
            plan=planning.plan,
            intent=intent,
            resolved_entities=planning.resolved_entities,
            session_context=session.context_summary(),
        )

    def _deterministic_research(self, question, planning, intent, options=None):
        """Use typed deterministic capabilities before generic retrieval.

        Returning ``None`` means no clean deterministic operation maps to the
        question, so the normal retrieval-only fallback is still appropriate.
        """
        routes = deterministic_module.capability_routes(
            question,
            planning.plan,
            intent,
            resolved_entities=planning.resolved_entities,
            ambiguities=planning.ambiguities,
            self_identity=(
                self._self_identity(options.principal_name)
                if options is not None and intent.wants_assignments
                else None
            ),
        )
        if routes is None:
            return None

        if any(
            route.get("tool") in ("canonical_entity_description", "find_decisions") for route in routes
        ):
            # Cheap when nothing changed: unchanged documents are recognized
            # by file stat and never re-read.
            self._facts_service(refresh=True)
        tools = self._tools()
        result = ResearchResult(rounds=1, stopped_because="deterministic-capability")
        seen = set()
        for route in routes:
            outcome = self._deterministic_call(tools, route, planning)
            if outcome is None:
                continue
            added: List[str] = []
            for row in outcome.documents:
                document_id = str(row.get("document_id") or "")
                if not document_id or document_id in seen:
                    continue
                if len(result.rows) >= self.limits.max_documents:
                    result.stopped_because = "max-documents"
                    break
                seen.add(document_id)
                result.rows.append(row)
                added.append(document_id)
            key = route.get("key") or ""
            if key and outcome.records:
                result.records.setdefault(key, []).extend(outcome.records)
            entry = outcome.trace_entry(route.get("reason") or "")
            entry["document_ids"] = added
            result.trace.append(entry)
        return result

    def _deterministic_call(self, tools: ResearchTools, route, planning):
        tool_name = route.get("tool")
        try:
            if tool_name == deterministic_module.UNRESOLVED_PERSON_TOOL:
                arguments = route.get("arguments") or {}
                return ToolResult(
                    tool=tool_name,
                    arguments=arguments,
                    records=[deterministic_module.unresolved_person_record(arguments)],
                    note=(
                        "The name matches more than one person; none was chosen."
                        if arguments.get("why") == "ambiguous"
                        else "No principal identity is configured, so \"me\" cannot be scoped."
                    ),
                )
            if tool_name == "canonical_entity_description":
                entity_ids: List[str] = [
                    str(entity.get("entity_id") or "")
                    for entity in planning.resolved_entities
                    if entity.get("entity_id")
                ]
                for value in planning.plan.entity_ids:
                    if value not in entity_ids:
                        entity_ids.append(value)
                rows = self.retriever.foundational_documents(entity_ids)
                if rows:
                    return ToolResult(
                        tool="get_entity",
                        arguments={"entity_ids": entity_ids},
                        documents=rows,
                        note="Authored canonical identity.",
                    )
                # Nobody wrote a description. Next best is what the corpus
                # states outright: human relationship assertions, then
                # high-confidence generated evidence facts, each quoted.
                stated = self._evidence_facts_result(entity_ids)
                if stated is not None:
                    return stated
                # Nothing stated either. Rather than answering "no
                # evidence" about an entity the corpus plainly knows, fall
                # back to a reconstruction assembled from that evidence —
                # labelled as derived, and never written back as canonical.
                return self._derived_profile_result(entity_ids)
            return tools.call(tool_name, route.get("arguments") or {})
        except ToolError as exc:
            return ToolResult(
                tool=str(tool_name or ""),
                arguments=route.get("arguments") or {},
                note=str(exc),
            )

    def _evidence_facts_result(self, entity_ids: Sequence[str]) -> Optional[ToolResult]:
        """What the corpus explicitly states about the first entity it states
        anything about, or ``None``.

        Two sources, in precedence order: relationship assertions a person
        recorded against a document, then high-confidence generated evidence
        facts. Every generated claim is re-verified against the current text
        of each document it cites; a quote that is no longer there is stale,
        and its document is not cited.
        """
        facts = self._facts_service()
        for entity_id in entity_ids:
            statements: List[Dict[str, Any]] = []
            try:
                relationships = self.retriever.entity_relationships(entity_id)
            except Exception:  # noqa: BLE001 - an old index without relationships
                relationships = []
            for relationship in relationships:
                phrase = PREDICATE_PHRASES.get(relationship.get("predicate") or "")
                if not phrase or not relationship.get("document_id"):
                    continue
                statements.append(
                    {
                        "kind": "relationship",
                        "text": f"{relationship['subject']} {phrase} {relationship['object']}.",
                        "document_ids": [relationship["document_id"]],
                        "quote": readable(relationship.get("excerpt") or ""),
                        "source_label": "recorded relationship assertion",
                        "canonical": True,
                    }
                )

            claims: List[Dict[str, Any]] = []
            if facts is not None:
                try:
                    claims = facts.identity_claims(entity_id)
                except Exception:  # noqa: BLE001 - a generated layer never fails an answer
                    claims = []
            wanted = [document_id for claim in claims for document_id in claim.get("document_ids") or []]
            bodies = {row["document_id"]: row for row in self.retriever.documents(wanted)}
            for claim in claims:
                evidence = [
                    entry
                    for entry in claim.get("evidence") or []
                    if entry.get("document_id") in bodies
                    and quote_in_source(entry.get("excerpt") or "", bodies[entry["document_id"]].get("body") or "")
                ]
                if not evidence:
                    continue
                best = evidence[0]
                statements.append(
                    {
                        "kind": "generated-fact",
                        "text": claim["sentence"],
                        "document_ids": [entry["document_id"] for entry in evidence],
                        "quote": readable(best.get("excerpt") or ""),
                        "source_label": _evidence_label(best),
                        "predicate": claim.get("predicate"),
                        "confidence": claim.get("confidence"),
                        "fact_ids": [entry.get("fact_id") for entry in evidence],
                        "canonical": False,
                    }
                )

            if not statements:
                continue
            record = self._entity_record(entity_id)
            cited: List[str] = []
            for statement in statements:
                for document_id in statement["document_ids"]:
                    if document_id not in cited:
                        cited.append(document_id)
            return ToolResult(
                tool="evidence_facts",
                arguments={"entity_id": entity_id},
                documents=self.retriever.documents(cited),
                records=[
                    {
                        "kind": deterministic_module.EVIDENCE_FACTS_KIND,
                        "entity_id": entity_id,
                        "name": getattr(record, "name", "") or "",
                        "entity_type": getattr(record, "type", "") or "",
                        "statements": statements,
                        "generated": any(not item.get("canonical") for item in statements),
                        "canonical": False,
                    }
                ],
                note="Explicit statements about this entity, each quoted from and verified against its source.",
            )
        return None

    def _entity_record(self, entity_id: str):
        return next((record for record in self._entity_records() if record.id == entity_id), None)

    def _facts_service(self, *, refresh: bool = False) -> Optional[EvidenceFactService]:
        """The generated evidence-facts service, or nothing if it cannot be built.

        ``refresh`` brings the store up to date first. It is incremental —
        only documents whose files changed are re-read — so running it before
        a definition or decision question is cheap; a missing store is built
        on first use, the same way derived profiles are.
        """
        service = getattr(self, "_facts", None)
        if service is None:
            try:
                service = EvidenceFactService(root_path=self.root_path, private_home=self.paths.home)
            except Exception:  # noqa: BLE001 - a missing facts layer is not fatal
                return None
            self._facts = service
        if refresh:
            try:
                service.build()
            except Exception:  # noqa: BLE001 - serve what is already built, if anything
                pass
        return service if service.store.exists() else None

    def _derived_profile_result(self, entity_ids: Sequence[str]) -> ToolResult:
        """A derived entity profile and the documents that support it.

        Built lazily. `gang entity profiles build` precomputes the same thing
        into the same generated store, so a precomputed corpus answers faster
        and an unprepared one answers identically.
        """
        service = self._profiles()
        profile = None
        if service is not None:
            for entity_id in entity_ids:
                try:
                    profile = service.profile(entity_id)
                except Exception:  # noqa: BLE001 - a derived layer never fails an answer
                    profile = None
                if profile is not None:
                    break

        if profile is None:
            return ToolResult(
                tool="get_entity",
                arguments={"entity_ids": list(entity_ids)},
                note="No canonical entity description matched.",
            )

        documents = self.retriever.documents(profile.document_ids())
        return ToolResult(
            tool="entity_profile",
            arguments={"entity_id": profile.entity_id},
            documents=documents,
            records=[profile.to_dict()],
            note="Derived entity profile reconstructed from cited evidence (not canonical).",
        )

    def _self_identity(self, principal_name: Optional[str]) -> Optional[Dict[str, str]]:
        """Who "I" is, as a name and — when it resolves exactly — an entity.

        Resolution is the same exact canonical-name-or-alias lookup every other
        name gets. A principal whose name matches no entity is still a name,
        and is matched literally against owners in the evidence.
        """
        name = (principal_name or "").strip()
        if not name:
            return None
        identity = {"name": name, "entity_id": ""}
        resolver = self._resolver()
        if resolver is not None:
            try:
                resolution = resolver.resolve(name)
            except Exception:  # noqa: BLE001 - an unavailable entity layer is not fatal
                resolution = None
            if resolution is not None and resolution.resolved and resolution.entity_type == "person":
                identity["entity_id"] = resolution.entity_id or ""
        return identity

    def _profiles(self):
        """The derived-profile service, or nothing if it cannot be built."""
        try:
            return EntityProfileService(root_path=self.root_path, private_home=self.paths.home)
        except Exception:  # noqa: BLE001 - a missing entity layer is not fatal
            return None

    def _tools(self) -> ResearchTools:
        return ResearchTools(
            self.retriever,
            registry_path=self.paths.registry_path,
            resolver=self._resolver(),
            entities=self._entity_records(),
            facts=self._facts_service(),
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

    def _synthesize(
        self, context: AnswerContext, planning, options, assessed, *, current_state: bool = False
    ):
        """Answer one turn, returning the answer, how it was produced, and the
        source-authority picture that actually applied to it."""
        bundle = context.bundle
        if bundle.empty and not deterministic_module.answers_without_documents(context):
            reason = "no-searchable-terms" if planning.plan.is_empty else "no-evidence"
            return (
                deterministic_conversation_answer(bundle, reason=reason, intent=context.intent),
                {"mode": "deterministic", "reason": reason, "cached": False},
                assessed,
            )
        if (context.intent.listing or planning.listing_question) and not context.intent.wants_assignments:
            return (
                deterministic_conversation_answer(
                    bundle, reason="listing-question", intent=context.intent
                ),
                {"mode": "deterministic", "reason": "listing-question", "cached": False},
                assessed,
            )
        deterministic = deterministic_module.capability_answer(context)
        if deterministic is not None:
            return (
                deterministic,
                {
                    "mode": "deterministic",
                    "reason": deterministic.get("reason") or "deterministic-capability",
                    "cached": False,
                },
                assessed,
            )
        if not options.use_ai:
            return (
                deterministic_conversation_answer(
                    bundle, reason="ai-disabled", intent=context.intent
                ),
                {"mode": "deterministic", "reason": "ai-disabled", "cached": False},
                assessed,
            )

        synthesizer = self._conversation_synthesizer(options)
        if synthesizer is None:
            return (
                deterministic_conversation_answer(
                    bundle, reason="no-provider", intent=context.intent
                ),
                {"mode": "deterministic", "reason": "no-provider", "cached": False},
                assessed,
            )

        remote = disclosure.applies(synthesizer)
        withheld: Dict[str, Any] = {}
        if remote:
            # Restricted and local-only evidence leaves the context here,
            # before any packet selection or request building sees it. The
            # full bundle still backs the local source list and session.
            remote_bundle = bundle.for_remote_provider()
            withheld = {"withheld_sources": disclosure.withheld_summary(remote_bundle)}
            if remote_bundle.empty:
                answer = deterministic_conversation_answer(
                    bundle, reason=disclosure.SENSITIVE_EVIDENCE_REASON, intent=context.intent
                )
                answer["answer"] = f"{disclosure.SENSITIVE_EVIDENCE_NOTICE}\n\n{answer['answer']}"
                return (
                    answer,
                    {
                        "mode": "deterministic",
                        "reason": disclosure.SENSITIVE_EVIDENCE_REASON,
                        "cached": False,
                        **withheld,
                    },
                    assessed,
                )
            bundle = remote_bundle
            assessed = _preference_within_packet(
                assessed,
                authority_module.assess(
                    bundle.items,
                    current_state_question=current_state,
                    purpose=(
                        authority_module.DEFINITION
                        if context.intent.wants_identity
                        else authority_module.CURRENT_STATE
                    ),
                ),
            )
            context = replace(context, bundle=bundle)

        packet_diagnostics: Dict[str, Any] = {}
        if getattr(synthesizer, "uses_local_ollama", False):
            selected_bundle, packet_diagnostics = select_for_local_synthesis(
                bundle,
                context.question,
                budget=synthesizer.local_synthesis_budget,
            )
            # The source-preference sentence names a document to the reader as
            # the one to lean on. It has to be a document the answer actually
            # saw: naming a source the packet dropped points a reader at
            # evidence that played no part in what they just read. Every
            # retrieved source keeps its own role and rank; only the
            # preference moves.
            assessed = _preference_within_packet(
                assessed,
                authority_module.assess(
                    selected_bundle.items,
                    current_state_question=current_state,
                    purpose=(
                        authority_module.DEFINITION
                        if context.intent.wants_identity
                        else authority_module.CURRENT_STATE
                    ),
                ),
            )
            context = AnswerContext(
                question=context.question,
                bundle=selected_bundle,
                intent=context.intent,
                session_context=context.session_context,
                authority=authority_module.guidance(assessed),
                records=context.records,
                assumptions=context.assumptions,
                resolved_references=context.resolved_references,
                stale_evidence=context.stale_evidence,
            )

        if remote:
            context = self._remote_context(context)

        model = getattr(synthesizer, "model", "")
        provider_name = getattr(synthesizer, "provider_name", "unknown")
        key = self._conversation_cache_key(context, model)
        if options.use_cache:
            cached = self._cache_read(key)
            if cached is not None:
                return (
                    cached,
                    {
                        "mode": "ai",
                        "provider": provider_name,
                        "model": model,
                        "api_cost": "$0" if provider_name == "ollama" else "remote provider",
                        "cached": True,
                        "evidence_packet": packet_diagnostics,
                        **withheld,
                    },
                    assessed,
                )

        request = None
        if hasattr(synthesizer, "build_request"):
            request = synthesizer.build_request(context)
        if packet_diagnostics:
            system_text = request.get("system", "") if request else ""
            message_text = " ".join(
                str(message.get("content") or "") for message in (request or {}).get("messages", [])
            )
            packet_diagnostics = {
                **packet_diagnostics,
                "prompt_token_estimate": estimate_tokens(f"{system_text}\n{message_text}"),
            }

        try:
            if request is not None and isinstance(synthesizer, ConversationSynthesizer):
                payload = synthesizer.synthesize(context, request=request)
            else:
                payload = synthesizer.synthesize(context)
        except SynthesisError as exc:
            self._record_provider_call("synthesis", synthesizer)
            raise AskError(str(exc), provider_calls=self._provider_calls) from exc
        else:
            self._record_provider_call("synthesis", synthesizer)

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
        return (
            answer,
            {
                "mode": "ai",
                "provider": provider_name,
                "model": model,
                "api_cost": "$0" if provider_name == "ollama" else "remote provider",
                "cached": False,
                "evidence_packet": packet_diagnostics,
                "structured_output": getattr(
                    synthesizer, "structured_output", schema_module.STRUCTURED_NOT_REQUESTED
                ),
                **withheld,
            },
            assessed,
        )

    def _remote_context(self, context: AnswerContext) -> AnswerContext:
        """Everything around the evidence, minus what cites a withheld document.

        The bundle was narrowed already. Records, authority guidance,
        conversation state, resolved references, and stale-evidence notices
        can each carry a quote or a summary from a sensitive source, so each
        loses the entries that cite one.
        """
        lookup = self.retriever.sensitivity
        return replace(
            context,
            session_context=disclosure.remote_data(context.session_context, lookup),
            authority=disclosure.remote_data(context.authority, lookup),
            records=disclosure.remote_data(context.records, lookup),
            resolved_references=disclosure.remote_data(context.resolved_references, lookup),
            stale_evidence=disclosure.remote_data(context.stale_evidence, lookup),
        )

    def _conversation_synthesizer(self, options: Optional[ConversationOptions] = None):
        if self._synthesizer is not None:
            return self._synthesizer
        options = options or ConversationOptions()
        try:
            provider = ConversationSynthesizer(
                root_path=self.root_path,
                provider=options.provider,
                model=options.model,
                premium=options.premium,
                local_only=options.local_only,
            )
        except ProviderError as exc:
            raise AskError(str(exc)) from exc
        if not provider.has_credentials and (options.premium or options.provider == "anthropic"):
            raise AskError(
                "ANTHROPIC_API_KEY is required for explicit premium/Anthropic Ask. "
                "No remote fallback was used."
            )
        return provider if provider.has_credentials else None

    def _director_provider(self, options: Optional[ConversationOptions] = None):
        if self._director is not None:
            return self._director
        options = options or ConversationOptions()
        try:
            provider = AnthropicResearchDirector(
                root_path=self.root_path,
                provider=options.provider,
                model=options.model,
                premium=options.premium,
                local_only=options.local_only,
            )
        except ProviderError as exc:
            raise AskError(str(exc)) from exc
        if not provider.has_credentials and (options.premium or options.provider == "anthropic"):
            raise AskError(
                "ANTHROPIC_API_KEY is required for explicit premium/Anthropic Ask. "
                "No remote fallback was used."
            )
        if provider.provider_name == "ollama" and not options.premium:
            return None
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
            "claim_ledger_origin": answer.get("claim_ledger_origin", ledger_module.MODEL),
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
            "provider_calls": list(self._provider_calls),
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
            "claim_ledger_origin": ledger_module.MODEL,
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
            "claim_ledger_origin": ledger_module.MODEL,
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


def _evidence_label(entry: Dict[str, Any]) -> str:
    """Where a quoted fact came from, in words: "email signature in 'X'
    (2026-02-12, an ordinary email)"."""
    rule = entry.get("rule") or ""
    lead = "email signature in" if rule == "signature-block" else "stated in"
    title = readable(entry.get("document_title") or entry.get("document_id") or "")
    if len(title) > 70:
        title = title[:69].rstrip() + "…"
    details = [
        bit
        for bit in (entry.get("document_date") or "", SOURCE_DESCRIPTIONS.get(entry.get("source_class") or "", ""))
        if bit
    ]
    return f"{lead} “{title}”" + (f" ({', '.join(details)})" if details else "")


def _first_excerpt(body: str, limit: int = 280) -> str:
    import re

    text = re.sub(r"\s+", " ", body or "").strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."
