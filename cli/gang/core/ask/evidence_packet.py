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

from .evidence import EvidenceBundle, EvidenceItem


TOKEN_CHARS = 4

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
    scored = [_score_item(item, terms, question) for item in bundle.items]
    scored.sort(key=lambda entry: entry["sort"], reverse=True)

    selected: List[EvidenceItem] = []
    rejected: List[Dict[str, Any]] = []
    signatures: set[str] = set()
    evidence_tokens = 0

    for entry in scored:
        item = entry["item"]
        signature = _signature(item)
        if entry["relevance"] <= 0:
            rejected.append(_rejection(item, "insufficient-question-relevance", entry))
            continue
        if signature in signatures:
            rejected.append(_rejection(item, "duplicative-evidence", entry))
            continue
        if len(selected) >= budget.max_documents:
            rejected.append(_rejection(item, "outside-local-document-budget", entry))
            continue

        excerpts = _rank_excerpts(item.excerpts, terms)[: budget.max_excerpts_per_document]
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
        "selected": [
            {
                "citation_id": item.citation_id,
                "document_id": item.document_id,
                "title": item.title,
                "source_kind": _score_item(item, terms, question)["source_kind"],
                "excerpt_count": len(item.excerpts),
            }
            for item in selected
        ],
        "rejected": rejected,
    }
    return selected_bundle, diagnostics


def compact_evidence_data(bundle: EvidenceBundle, source_kinds: Dict[int, str] | None = None):
    kinds = source_kinds or {}
    return [
        {
            "citation_id": item.citation_id,
            "label": f"S{item.citation_id}",
            "title": item.title,
            "date": item.updated or item.created,
            "source_kind": kinds.get(item.citation_id) or classify_source(item, []),
            "excerpts": list(item.excerpts),
        }
        for item in bundle.items
    ]


def classify_source(item: EvidenceItem, terms: Sequence[str]) -> str:
    text = " ".join([item.title, item.type, item.source_type, *item.excerpts]).lower()
    title = item.title.lower()
    if "tasks.txt" in title or item.type in {"task", "tasks"}:
        return "task note"
    if _future_plan(item) or "agenda" in title or "schedule" in title or item.type in {"agenda", "plan", "schedule"}:
        return "plan / agenda / future document"
    if "summary" in title or "recap" in title:
        return "internal summary"
    if _direct_external(item, text):
        return "direct external authority / primary evidence"
    if item.source_type in {"gmail-thread", "gmail", "email"}:
        return "internal factual record"
    return "internal factual record"


def estimate_tokens(text: str) -> int:
    return _estimate_tokens(text)


def _score_item(item: EvidenceItem, terms: Sequence[str], question: str) -> Dict[str, Any]:
    title = item.title.lower()
    text = " ".join([item.title, *item.excerpts]).lower()
    relevance = sum(1 for term in terms if term in text)
    if "certification" in question.lower() and re.search(r"\b(wpc|qi|qi-27832|certification body)\b", text):
        relevance += 4
    if "qi" in question.lower() and re.search(r"\b(qi|qi-27832|wpc)\b", text):
        relevance += 3

    source_kind = classify_source(item, terms)
    kind_weight = {
        "direct external authority / primary evidence": 60,
        "internal factual record": 40,
        "internal summary": 30,
        "task note": 20,
        "plan / agenda / future document": 10,
    }.get(source_kind, 20)
    temporal = -25 if _future_plan(item) else 0
    recency = _date_score(item.updated or item.created)
    redundancy = -10 if _generic_agenda(title) else 0
    score = relevance * 15 + kind_weight + temporal + recency + redundancy
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


def _rank_excerpts(excerpts: Sequence[str], terms: Sequence[str]) -> List[str]:
    return sorted(
        list(excerpts),
        key=lambda excerpt: (sum(1 for term in terms if term in excerpt.lower()), len(excerpt)),
        reverse=True,
    )


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
