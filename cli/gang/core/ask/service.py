"""`gang ask`: plan, retrieve, bound, synthesize, cite. Strictly read-only.

This is the orchestration layer. It owns the guarantee that the command cannot
change anything: it never opens a canonical document for writing, never touches
the ingestion registry, raw store, entity records, or enrichment proposals, and
opens the generated index read-only. The one thing it may write is a disposable
answer cache under `GANG_HOME/generated/ask-cache/`, which is private, ignored
by git, and safe to delete at any time.

Natural-language *mutation* is deliberately not here and does not belong here.
It needs a typed-command architecture with its own review and audit trail.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from core.ai_provider import ProviderError, ProviderTimeoutError
from core.entities.resolver import EntityResolver
from core.entities.store import EntityStore
from core.paths import GangPaths

from . import disclosure, synthesis
from .evidence import EvidenceBundle, build_bundle
from .plan import DEFAULT_LIMIT
from .planner import (
    AnthropicQueryPlanner,
    DeterministicPlanner,
    PlanningResult,
    PlanOverrides,
    entity_catalog,
    merge_ai_plan,
)
from .retrieval import Retriever
from .synthesis import AnthropicAnswerSynthesizer, SynthesisError


RESULT_VERSION = "1"

#: Citation lines are scanned, not read. Real subject lines and Drive titles run
#: well past this.
MAX_CITATION_LABEL = 72

_PROSE_CITATION = re.compile(r"\[(\d{1,3})\]")

#: Bumped when the synthesis prompt changes, so cached answers do not outlive
#: the prompt that produced them.
PROMPT_VERSION = "ask-1"


class AskError(RuntimeError):
    """Raised when a question cannot be answered for an operational reason."""

    def __init__(self, message: str, *, provider_calls: Optional[List[Dict[str, Any]]] = None):
        super().__init__(message)
        self.provider_calls = list(provider_calls or [])


@dataclass(frozen=True)
class AskOptions:
    use_ai: bool = True
    use_cache: bool = True
    plan_only: bool = False
    provider: Optional[str] = None
    model: Optional[str] = None
    premium: bool = False
    local_only: Optional[bool] = None


class AskService:
    def __init__(
        self,
        *,
        root_path: Path | str = Path("."),
        private_home: Path | str | None = None,
        retriever: Optional[Retriever] = None,
        synthesizer: Optional[Any] = None,
        query_planner: Optional[Any] = None,
        clock: Optional[date] = None,
    ):
        self.root_path = Path(root_path).resolve()
        self.paths = GangPaths.from_env(repo_root=self.root_path, gang_home=private_home)
        self.retriever = retriever or Retriever(self.paths.index_path)
        self.clock = clock
        self._synthesizer = synthesizer
        self._query_planner = query_planner
        self._provider_calls: List[Dict[str, Any]] = []

    # ---------------------------------------------------------------- ask

    def ask(
        self,
        question: str,
        *,
        overrides: Optional[PlanOverrides] = None,
        options: Optional[AskOptions] = None,
    ) -> Dict[str, Any]:
        options = options or AskOptions()
        overrides = overrides or PlanOverrides(limit=DEFAULT_LIMIT)
        self._provider_calls = []

        planning = self._plan(question, overrides, options)
        if options.plan_only:
            return {
                "version": RESULT_VERSION,
                "question": question,
                **planning.to_dict(),
            }

        # A question made entirely of stopwords selects nothing, and saying
        # that is more useful than reporting an empty corpus search.
        rows = [] if planning.plan.is_empty else self.retriever.retrieve(planning.plan)
        bundle = build_bundle(
            question,
            rows,
            planning.plan,
            ambiguities=planning.ambiguities,
        )
        answer, synthesis_meta = self._answer(bundle, planning, options)
        return self._result(question, planning, bundle, answer, synthesis_meta)

    # ------------------------------------------------------------- planning

    def _plan(self, question: str, overrides: PlanOverrides, options: AskOptions) -> PlanningResult:
        planner = DeterministicPlanner(self._resolver(), clock=self.clock)
        planning = planner.plan(question, overrides)

        if not options.use_ai or not planning.ai_recommended:
            # Exact search never needs the model. This is the common path.
            return planning

        query_planner = self._planner_provider(options)
        if query_planner is None:
            return planning

        try:
            catalog = self._catalog()
            proposed = query_planner.propose(question, catalog)
        except Exception as exc:  # noqa: BLE001
            self._record_provider_call("planning", query_planner)
            if _caused_by_timeout(exc):
                raise AskError(str(exc), provider_calls=self._provider_calls) from exc
            # Planning assist is optional. Any provider or catalog failure
            # degrades to the deterministic plan rather than failing the
            # question, so retrieval still runs on the user's own terms.
            return PlanningResult(
                plan=planning.plan,
                planner="deterministic",
                ambiguities=planning.ambiguities,
                resolved_entities=planning.resolved_entities,
                listing_question=planning.listing_question,
                ai_recommended=planning.ai_recommended,
                notes=planning.notes + [f"AI query planning unavailable: {exc}"],
            )
        else:
            self._record_provider_call("planning", query_planner)
        return merge_ai_plan(planning, proposed, catalog)

    def _catalog(self) -> Dict[str, Any]:
        vocabulary = self.retriever.vocabulary()
        return {
            "entities": entity_catalog(self._store().load_all()),
            "document_types": vocabulary["document_types"],
            "source_types": vocabulary["source_types"],
            "today": (self.clock or date.today()).isoformat(),
        }

    # ------------------------------------------------------------ answering

    def _answer(self, bundle: EvidenceBundle, planning: PlanningResult, options: AskOptions):
        if bundle.empty:
            reason = "no-searchable-terms" if planning.plan.is_empty else "no-evidence"
            return (
                synthesis.deterministic_answer(bundle, reason=reason),
                {"mode": "deterministic", "reason": reason, "cached": False},
            )
        if planning.listing_question:
            return (
                synthesis.deterministic_answer(bundle, reason="listing-question"),
                {"mode": "deterministic", "reason": "listing-question", "cached": False},
            )
        if not options.use_ai:
            return (
                synthesis.deterministic_answer(bundle, reason="ai-disabled"),
                {"mode": "deterministic", "reason": "ai-disabled", "cached": False},
            )

        synthesizer = self._synthesis_provider(options)
        if synthesizer is None:
            return (
                synthesis.deterministic_answer(bundle, reason="no-provider"),
                {"mode": "deterministic", "reason": "no-provider", "cached": False},
            )

        withheld: Dict[str, Any] = {}
        if disclosure.applies(synthesizer):
            # Narrowed before anything is serialized for the provider. The
            # full bundle still backs the local source list.
            remote_bundle = bundle.for_remote_provider()
            withheld = {"withheld_sources": disclosure.withheld_summary(remote_bundle)}
            if remote_bundle.empty:
                answer = synthesis.deterministic_answer(
                    bundle, reason=disclosure.SENSITIVE_EVIDENCE_REASON
                )
                answer["answer"] = f"{disclosure.SENSITIVE_EVIDENCE_NOTICE}\n\n{answer['answer']}"
                return answer, {
                    "mode": "deterministic",
                    "reason": disclosure.SENSITIVE_EVIDENCE_REASON,
                    "cached": False,
                    **withheld,
                }
            bundle = remote_bundle

        model = getattr(synthesizer, "model", "")
        provider_name = getattr(synthesizer, "provider_name", "unknown")
        cache_key = self._cache_key(bundle, model)
        if options.use_cache:
            cached = self._cache_read(cache_key)
            if cached is not None:
                return cached, {
                    "mode": "ai",
                    "provider": provider_name,
                    "model": model,
                    "api_cost": "$0" if provider_name == "ollama" else "remote provider",
                    "cached": True,
                    **withheld,
                }

        try:
            payload = synthesizer.synthesize(bundle)
        except SynthesisError as exc:
            self._record_provider_call("synthesis", synthesizer)
            raise AskError(str(exc), provider_calls=self._provider_calls) from exc
        else:
            self._record_provider_call("synthesis", synthesizer)
        answer = synthesis.validate_answer(payload, bundle)
        if options.use_cache:
            self._cache_write(cache_key, answer)
        return answer, {
            "mode": "ai",
            "provider": provider_name,
            "model": model,
            "api_cost": "$0" if provider_name == "ollama" else "remote provider",
            "cached": False,
            **withheld,
        }

    # --------------------------------------------------------------- result

    def _result(
        self,
        question: str,
        planning: PlanningResult,
        bundle: EvidenceBundle,
        answer: Dict[str, Any],
        synthesis_meta: Dict[str, Any],
    ) -> Dict[str, Any]:
        notice = synthesis.ambiguity_notice(planning.ambiguities)
        answer_text = answer["answer"]
        if notice:
            # Code-owned, so an ambiguous name is surfaced whether or not the
            # model chose to mention it.
            answer_text = f"{notice}\n\n{answer_text}"

        cited = cited_citation_ids(answer, answer_text)
        sources = [
            {**source, "cited": source["citation_id"] in cited} for source in bundle.sources()
        ]

        return {
            "version": RESULT_VERSION,
            "question": question,
            "answer": answer_text,
            "claims": answer["claims"],
            "conflicts": answer["conflicts"],
            "uncertainty": answer["uncertainty"],
            "insufficient_evidence": answer["insufficient_evidence"],
            "ambiguities": planning.ambiguities,
            "sources": sources,
            "cited_source_count": len(cited),
            "excluded_sources": [item.to_dict() for item in bundle.excluded],
            "evidence": [item.to_dict() for item in bundle.items],
            "evidence_count": len(bundle.items),
            "temporal_ordering": bundle.temporal_ordering(),
            "plan": planning.plan.to_dict(),
            "planner": planning.planner,
            "resolved_entities": planning.resolved_entities,
            "synthesis": synthesis_meta,
            "provider_calls": list(self._provider_calls),
            "notes": planning.notes,
            "dropped_citations": answer.get("dropped_citations", []),
            "rejected_fields": answer.get("rejected_fields", []),
            "grounding_warnings": answer.get("grounding_warnings", []),
            "softened_negatives": answer.get("softened_negatives", []),
        }

    # -------------------------------------------------------------- helpers

    def _store(self) -> EntityStore:
        return EntityStore(root_path=self.root_path, private_home=self.paths.home)

    def _resolver(self) -> Optional[EntityResolver]:
        try:
            return EntityResolver(self._store().load_all())
        except Exception:  # noqa: BLE001 - a missing entity layer is not fatal
            return None

    def _synthesis_provider(self, options: Optional[AskOptions] = None):
        if self._synthesizer is not None:
            return self._synthesizer
        options = options or AskOptions()
        try:
            provider = AnthropicAnswerSynthesizer(
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

    def _planner_provider(self, options: Optional[AskOptions] = None):
        if self._query_planner is not None:
            return self._query_planner
        options = options or AskOptions()
        try:
            provider = AnthropicQueryPlanner(
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

    def _record_provider_call(self, purpose: str, provider: Any) -> None:
        telemetry = getattr(provider, "telemetry", {}) or {}
        if not isinstance(telemetry, dict) or not telemetry:
            return
        self._append_provider_call({"purpose": purpose, **telemetry})

    def _append_provider_call(self, call: Dict[str, Any]) -> None:
        self._provider_calls.append({"sequence": len(self._provider_calls) + 1, **call})

    # ---------------------------------------------------------------- cache

    def _cache_key(self, bundle: EvidenceBundle, model: str) -> str:
        return hashlib.sha256(
            "|".join([PROMPT_VERSION, model, bundle.fingerprint()]).encode("utf-8")
        ).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self.paths.ask_cache_path / f"{key}.json"

    def _cache_read(self, key: str) -> Optional[Dict[str, Any]]:
        path = self._cache_path(key)
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return value if isinstance(value, dict) else None

    def _cache_write(self, key: str, answer: Dict[str, Any]) -> None:
        # Best effort by design: the cache is an optimization, never canonical.
        try:
            path = self._cache_path(key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(answer, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        except OSError:
            pass


def _caused_by_timeout(exc: BaseException) -> bool:
    current: Optional[BaseException] = exc
    while current is not None:
        if isinstance(current, ProviderTimeoutError):
            return True
        current = current.__cause__
    return False


def cited_citation_ids(answer: Dict[str, Any], answer_text: str) -> Set[int]:
    """Which evidence the answer actually leaned on.

    A retrieved document that no claim, conflict, or sentence referenced did not
    support the answer, and displaying it beside the ones that did implies it
    contributed something.
    """
    cited: Set[int] = set()
    for claim in answer.get("claims", []) or []:
        cited.update(claim.get("citations", []) or [])
    for conflict in answer.get("conflicts", []) or []:
        cited.update(conflict.get("citations", []) or [])
    cited.update(int(match) for match in _PROSE_CITATION.findall(answer_text or ""))
    return cited


def citation_labels(sources: List[Dict[str, Any]]) -> Dict[int, str]:
    """Citation labels, disambiguated when two documents share a title.

    `[1] Qi2 Launch` and `[2] Qi2 Launch` are useless to a reader checking the
    evidence, so a repeated title gains its type and date.
    """
    counts: Dict[str, int] = {}
    for item in sources:
        counts[item["title"]] = counts.get(item["title"], 0) + 1

    labels: Dict[int, str] = {}
    for item in sources:
        label = _shorten(item["title"], MAX_CITATION_LABEL)
        if counts.get(item["title"], 0) > 1:
            qualifiers = [
                value
                for value in (item.get("source_type") or item.get("type"), _day(item.get("updated")))
                if value
            ]
            if qualifiers:
                label = f"{label} ({' · '.join(qualifiers)})"
        labels[item["citation_id"]] = label
    return labels


def _shorten(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _day(value: Any) -> str:
    return str(value or "")[:10]
