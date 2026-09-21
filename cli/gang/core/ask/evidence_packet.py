"""Select the compact evidence packet sent to local synthesis.

Retrieval can stay broad; local inference cannot. This module ranks the full
evidence bundle deterministically, trims only the synthesis copy, and records
what was selected or rejected so `--show-research` can explain the packet.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from typing import Any, Dict, List, Sequence, Tuple

from core.ai_provider import SynthesisPacketBudget

from . import grounding as grounding_module
from . import intent as intent_module
from .evidence import EvidenceBundle, EvidenceItem


TOKEN_CHARS = 4

#: The source kinds, named once. ``PRIMARY`` is the correspondence itself —
#: what the certification body actually wrote — as opposed to a summary of it.
PRIMARY = "direct external authority / primary evidence"
FACTUAL_RECORD = "internal factual record"
SUMMARY = "internal summary"
TASK_NOTE = "task note"
PLAN = "plan / agenda / future document"

#: How much a source that states a requirement outright is worth when the
#: question asked what is required. Enough for a primary source to clear any
#: summary, and not enough to promote a summary past a primary source that
#: also states it. This reorders the synthesis packet only; source authority
#: (authority.py) and retrieval are untouched.
REQUIREMENT_PRIMARY_BONUS = 50
REQUIREMENT_SECONDARY_BONUS = 15

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9'._@-]*")
_FUTURE_DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")

_STOPWORDS = {
    "about",
    "actually",
    "after",
    "again",
    "against",
    "around",
    "because",
    "before",
    "being",
    "could",
    "doing",
    "going",
    "have",
    "next",
    "should",
    "that",
    "their",
    "there",
    "these",
    "thing",
    "what",
    "when",
    "where",
    "which",
    "with",
    "would",
}


def select_for_local_synthesis(
    bundle: EvidenceBundle,
    question: str,
    *,
    budget: SynthesisPacketBudget,
) -> Tuple[EvidenceBundle, Dict[str, Any]]:
    """Return a synthesis-sized copy of ``bundle`` and diagnostics.

    Citation ids are preserved so the answer still points back to the original
    retrieved source list. Only excerpts are shortened.
    """
    terms = _terms(question)
    wants_requirements = intent_module.asks_for_requirements(question)
    scored = [
        _score_item(item, terms, question, wants_requirements=wants_requirements)
        for item in bundle.items
    ]
    scored.sort(key=lambda entry: entry["sort"], reverse=True)
    kinds = {entry["item"].citation_id: entry["source_kind"] for entry in scored}

    selected: List[EvidenceItem] = []
    rejected: List[Dict[str, Any]] = []
    signatures: set[str] = set()
    evidence_tokens = 0
    primary_requirement = False

    for entry in scored:
        item = entry["item"]
        signature = _signature(item)
        if entry["relevance"] <= 0:
            rejected.append(_rejection(item, "insufficient-question-relevance", entry))
            continue
        if wants_requirements and primary_requirement and entry["source_kind"] == PLAN:
            # An agenda lists "certification prototype/test-lab requirements"
            # as a standing topic. That is a heading, not a requirement, and a
            # model asked what is required will cite it as one if it is in
            # front of it. Once the source that actually imposes requirements
            # is in the packet, the agenda is only a way to get this wrong.
            rejected.append(_rejection(item, "agenda-is-not-a-requirement-source", entry))
            continue
        if signature in signatures:
            rejected.append(_rejection(item, "duplicative-evidence", entry))
            continue
        if len(selected) >= budget.max_documents:
            rejected.append(_rejection(item, "outside-local-document-budget", entry))
            continue

        excerpts = _rank_excerpts(
            item.excerpts, terms, wants_requirements=wants_requirements
        )[: budget.max_excerpts_per_document]
        excerpts = [_truncate(excerpt, budget.max_excerpt_chars) for excerpt in excerpts if excerpt]
        if not excerpts:
            rejected.append(_rejection(item, "no-relevant-readable-excerpt", entry))
            continue

        estimated = _estimate_tokens(_compact_source_text(item, excerpts, entry["source_kind"]))
        if evidence_tokens + estimated > budget.max_evidence_tokens and selected:
            rejected.append(_rejection(item, "outside-local-evidence-token-budget", entry))
            continue

        selected.append(replace(item, excerpts=excerpts))
        signatures.add(signature)
        evidence_tokens += estimated
        if entry["source_kind"] == PRIMARY and any(
            grounding_module.states_requirement(excerpt) for excerpt in excerpts
        ):
            primary_requirement = True

    if not selected and bundle.items:
        entry = scored[0]
        item = entry["item"]
        excerpts = [_truncate(excerpt, budget.max_excerpt_chars) for excerpt in item.excerpts[:1]]
        if excerpts:
            selected.append(replace(item, excerpts=excerpts))
            evidence_tokens = _estimate_tokens(_compact_source_text(item, excerpts, entry["source_kind"]))

    selected_ids = {item.document_id for item in selected}
    for entry in scored:
        item = entry["item"]
        if item.document_id in selected_ids:
            continue
        if any(row["document_id"] == item.document_id for row in rejected):
            continue
        rejected.append(_rejection(item, "not-selected", entry))

    selected_bundle = EvidenceBundle(
        question=bundle.question,
        items=selected,
        ambiguities=bundle.ambiguities,
        date_range=bundle.date_range,
        text_query_count=bundle.text_query_count,
        excluded=bundle.excluded,
    )
    diagnostics = {
        "budget": {
            "max_prompt_tokens": budget.max_prompt_tokens,
            "max_evidence_tokens": budget.max_evidence_tokens,
            "max_documents": budget.max_documents,
            "max_excerpts_per_document": budget.max_excerpts_per_document,
            "max_output_tokens": budget.max_output_tokens,
            "max_excerpt_chars": budget.max_excerpt_chars,
        },
        "documents_retrieved": len(bundle.items),
        "documents_selected": len(selected),
        "evidence_token_estimate": evidence_tokens,
        "requirement_question": wants_requirements,
        "selected": [
            {
                "citation_id": item.citation_id,
                "document_id": item.document_id,
                "title": item.title,
                "source_kind": kinds.get(item.citation_id, FACTUAL_RECORD),
                "excerpt_count": len(item.excerpts),
                "states_requirement": any(
                    grounding_module.states_requirement(excerpt) for excerpt in item.excerpts
                ),
            }
            for item in selected
        ],
        "rejected": rejected,
    }
    return selected_bundle, diagnostics


def compact_evidence_data(
    bundle: EvidenceBundle,
    source_kinds: Dict[int, str] | None = None,
    *,
    mark_requirements: bool = False,
):
    """The packet as the model sees it, in the order the ranking put it.

    ``mark_requirements`` adds one derived flag per source, computed by the
    same check that did the ranking. Asked what is required, a model that can
    see which source actually states a requirement — and which one merely
    mentions the subject — has one less thing to guess at.
    """
    kinds = source_kinds or {}
    rows = []
    for item in bundle.items:
        row = {
            "citation_id": item.citation_id,
            "label": f"S{item.citation_id}",
            "title": item.title,
            "date": item.updated or item.created,
            "source_kind": kinds.get(item.citation_id) or classify_source(item, []),
            "excerpts": list(item.excerpts),
        }
        if mark_requirements:
            row["states_requirement"] = any(
                grounding_module.states_requirement(excerpt) for excerpt in item.excerpts
            )
        rows.append(row)
    return rows


def classify_source(item: EvidenceItem, terms: Sequence[str]) -> str:
    text = " ".join([item.title, item.type, item.source_type, *item.excerpts]).lower()
    title = item.title.lower()
    if "tasks.txt" in title or item.type in {"task", "tasks"}:
        return TASK_NOTE
    if _future_plan(item) or "agenda" in title or "schedule" in title or item.type in {"agenda", "plan", "schedule"}:
        return PLAN
    if "summary" in title or "recap" in title:
        return SUMMARY
    if _direct_external(item, text):
        return PRIMARY
    return FACTUAL_RECORD


def estimate_tokens(text: str) -> int:
    return _estimate_tokens(text)


def _score_item(
    item: EvidenceItem,
    terms: Sequence[str],
    question: str,
    *,
    wants_requirements: bool = False,
) -> Dict[str, Any]:
    title = item.title.lower()
    text = " ".join([item.title, *item.excerpts]).lower()
    relevance = sum(1 for term in terms if term in text)
    if "certification" in question.lower() and re.search(r"\b(wpc|qi|qi-27832|certification body)\b", text):
        relevance += 4
    if "qi" in question.lower() and re.search(r"\b(qi|qi-27832|wpc)\b", text):
        relevance += 3

    source_kind = classify_source(item, terms)
    kind_weight = {
        PRIMARY: 60,
        FACTUAL_RECORD: 40,
        SUMMARY: 30,
        TASK_NOTE: 20,
        PLAN: 10,
    }.get(source_kind, 20)
    temporal = -25 if _future_plan(item) else 0
    recency = _date_score(item.updated or item.created)
    redundancy = -10 if _generic_agenda(title) else 0

    # Asked what is required, a source that imposes the requirement beats one
    # that mentions it. The primary source wins outright; a summary that does
    # state a requirement still ranks above one that does not.
    requirement = 0
    if wants_requirements and any(
        grounding_module.states_requirement(excerpt) for excerpt in item.excerpts
    ):
        requirement = (
            REQUIREMENT_PRIMARY_BONUS if source_kind == PRIMARY else REQUIREMENT_SECONDARY_BONUS
        )

    score = relevance * 15 + kind_weight + temporal + recency + redundancy + requirement
    return {
        "item": item,
        "relevance": relevance,
        "source_kind": source_kind,
        "score": score,
        "sort": (score, relevance, kind_weight, recency, -item.citation_id),
    }


def _terms(question: str) -> List[str]:
    terms = []
    for raw in _WORD.findall((question or "").lower()):
        if len(raw) < 3 or raw in _STOPWORDS:
            continue
        terms.append(raw)
    if "qi" in (question or "").lower():
        terms.append("qi")
    return list(dict.fromkeys(terms))


def _rank_excerpts(
    excerpts: Sequence[str], terms: Sequence[str], *, wants_requirements: bool = False
) -> List[str]:
    def rank(excerpt: str):
        requirement = (
            1 if wants_requirements and grounding_module.states_requirement(excerpt) else 0
        )
        return (requirement, sum(1 for term in terms if term in excerpt.lower()), len(excerpt))

    return sorted(list(excerpts), key=rank, reverse=True)


def _direct_external(item: EvidenceItem, text: str) -> bool:
    title = item.title.lower()
    if "qi-27832" in title:
        return True
    return bool(
        re.search(
            r"\b(certification body|wpc cb|applicant initial editing|form03|qi-id)\b",
            text,
        )
    )


def _future_plan(item: EvidenceItem) -> bool:
    today = date.today().isoformat()
    values = [item.updated or "", item.created or "", item.title]
    for value in values:
        for match in _FUTURE_DATE.finditer(value or ""):
            found = "-".join(match.groups())
            if found > today:
                return True
    title = item.title.lower()
    return "future" in title or "final working version" in title


def _generic_agenda(title: str) -> bool:
    return "agenda" in title or "working version" in title or "template" in title


def _date_score(value: str) -> int:
    match = _FUTURE_DATE.search(value or "")
    if not match:
        return 0
    try:
        year, month, day = (int(part) for part in match.groups())
    except ValueError:
        return 0
    return min(12, max(0, (year - 2020) * 2 + month // 3 + day // 20))


def _signature(item: EvidenceItem) -> str:
    text = " ".join(item.excerpts).lower()
    words = [word for word in _WORD.findall(text) if len(word) > 4][0:30]
    return " ".join(words) or item.title.lower()


def _compact_source_text(item: EvidenceItem, excerpts: Sequence[str], source_kind: str) -> str:
    return f"[S{item.citation_id}] {item.title} - {item.updated or item.created} - {source_kind}\n" + "\n".join(excerpts)


def _rejection(item: EvidenceItem, reason: str, entry: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "citation_id": item.citation_id,
        "document_id": item.document_id,
        "title": item.title,
        "reason": reason,
        "score": round(float(entry["score"]), 3),
        "source_kind": entry["source_kind"],
    }


def _truncate(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 4)].rstrip() + " ..."


def _estimate_tokens(text: str) -> int:
    return max(1, (len(text or "") + TOKEN_CHARS - 1) // TOKEN_CHARS)
