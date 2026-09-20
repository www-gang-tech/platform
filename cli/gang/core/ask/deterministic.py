"""Deterministic Ask-mode routing and prose for code-owned capabilities.

``--no-ai`` means no model should decide how to answer. For question shapes
that already have typed primitives, this module gives those primitives first
refusal and renders their structured records directly. Generic full-text
retrieval remains the fallback for everything else.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from . import affiliation as affiliation_module
from . import intent as intent_module
from . import ledger as ledger_module
from .plan import MAX_TEXT_QUERIES


GENERIC_PARTICIPANT_TOPICS = {
    "team",
    "group",
    "crew",
    "people",
    "participants",
    "participant",
    "players",
    "company",
    "project",
}

STRUCTURED_STOPWORDS = {
    "action",
    "actions",
    "item",
    "items",
    "decision",
    "decisions",
    "decided",
    "open",
    "question",
    "questions",
    "blocker",
    "blockers",
    "blocking",
    "blocked",
    "undecided",
    "record",
    "recorded",
    "records",
}


def capability_routes(question: str, plan: Any, intent: Any) -> Optional[List[Dict[str, Any]]]:
    """Return deterministic primitive calls for a cleanly mapped question.

    ``None`` means "no clean mapping"; callers should use ordinary retrieval.
    An empty list is not returned: a mapped question always has one or more
    code-owned operations.
    """
    text = _fold(question)
    if getattr(intent, "wants_people", False):
        arguments: Dict[str, Any] = {}
        topic = _topic(plan, generic=GENERIC_PARTICIPANT_TOPICS)
        if topic:
            arguments["topic"] = topic
        if getattr(plan, "entity_ids", None):
            arguments["entity_id"] = plan.entity_ids[0]
        _date_bounds(arguments, plan)
        return [
            {
                "tool": "find_participants",
                "arguments": arguments,
                "key": "participants",
                "reason": "participant question routed to deterministic participation signals",
            }
        ]

    if getattr(intent, "wants_identity", False):
        return [
            {
                "tool": "canonical_entity_description",
                "arguments": {},
                "key": "",
                "reason": "definition question routed to canonical entity description",
            }
        ]

    if _asks_open_questions(text):
        return [_structured_route("find_open_questions", "open_questions", plan, "open-question question")]

    if _asks_action_items(text):
        return [_structured_route("find_action_items", "action_items", plan, "action-item question")]

    if _asks_decisions(text) or getattr(intent, "policy", "") == intent_module.DECISION:
        return [_structured_route("find_decisions", "decisions", plan, "decision question")]

    if getattr(intent, "policy", "") == intent_module.TIMELINE:
        arguments = _timeline_arguments(plan)
        if arguments:
            return [
                {
                    "tool": "build_timeline",
                    "arguments": arguments,
                    "key": "timeline",
                    "reason": "timeline question routed to deterministic chronology",
                }
            ]

    return None


def capability_answer(context: Any) -> Optional[Dict[str, Any]]:
    """Render a deterministic primitive result in the normal answer shape."""
    records = context.records or {}
    question = context.question or ""

    if "participants" in records:
        return _participants_answer(records["participants"], context.bundle)
    if context.intent.policy == intent_module.DEFINITION:
        return _definition_answer(context.bundle)
    if "timeline" in records:
        return _timeline_answer(records["timeline"], context.bundle)

    structured_keys = [
        key for key in ("decisions", "action_items", "open_questions") if key in records
    ]
    if structured_keys:
        return _structured_answer({key: records.get(key) or [] for key in structured_keys}, context.bundle)

    return None


def _participants_answer(payload: Dict[str, Any], bundle: Any) -> Dict[str, Any]:
    grouped = payload.get("participants") or {}
    citation_by_doc = _citation_by_document(bundle)
    lines: List[str] = []
    claims: List[Dict[str, Any]] = []

    headings = [
        (affiliation_module.CORE_INTERNAL, "Likely core/internal"),
        (affiliation_module.EXTERNAL_ADVISORY, "External/advisory"),
        (affiliation_module.COLLABORATOR_VENDOR, "Collaborator/vendor"),
        (affiliation_module.UNCLEAR, "Unclear"),
    ]
    for band, heading in headings:
        rows = grouped.get(band) or []
        if band == affiliation_module.COLLABORATOR_VENDOR and not rows:
            continue
        lines.append(heading)
        if not rows:
            lines.append("- None found.")
            lines.append("")
            continue
        for row in rows:
            citations = _record_citations(row.get("document_ids") or [], citation_by_doc)
            signal = _participant_signal(row)
            cite_text = _cite_text(citations)
            lines.append(f"- {row.get('name', 'Unknown')} — {signal}{cite_text}")
            claims.append(
                _claim(
                    len(claims) + 1,
                    "inference" if band != affiliation_module.UNCLEAR else "fact",
                    f"{row.get('name', 'Unknown')} is listed under {heading} from deterministic participation signals.",
                    citations,
                )
            )
        lines.append("")

    uncertainty = ""
    if not payload.get("home_company_known", True):
        uncertainty = (
            "No canonical company record with an email domain exists, so internal and "
            "external cannot be separated reliably."
        )
    return _answer("\n".join(lines).strip(), claims, uncertainty=uncertainty)


def _definition_answer(bundle: Any) -> Dict[str, Any]:
    if bundle.empty:
        return _empty_answer("I found no canonical entity description for that question.")
    item = bundle.items[0]
    text = (item.excerpts[0] if item.excerpts else item.title).strip()
    answer = f"{text} [{item.citation_id}]"
    return _answer(
        answer,
        [_claim(1, "fact", text, [item.citation_id])],
    )


def _timeline_answer(payload: Any, bundle: Any) -> Dict[str, Any]:
    items = payload.get("items") if isinstance(payload, dict) else payload
    items = items if isinstance(items, list) else []
    if not items:
        return _empty_answer("I found no timeline entries for that question.")
    lines = ["Timeline"]
    claims: List[Dict[str, Any]] = []
    valid = set(bundle.citation_ids())
    for item in items:
        citation = _valid_citation(item.get("citation_id"), valid)
        date = item.get("timestamp") or "undated"
        excerpt = _short(item.get("excerpt") or item.get("title") or "", 180)
        lines.append(f"- {date} — {item.get('title') or item.get('document_id')}: {excerpt}{_cite_text([citation])}")
        claims.append(
            _claim(
                len(claims) + 1,
                "fact",
                f"{date}: {item.get('title') or item.get('document_id')}",
                [citation],
            )
        )
    return _answer("\n".join(lines), claims)


def _structured_answer(records: Dict[str, Sequence[Dict[str, Any]]], bundle: Any) -> Dict[str, Any]:
    citation_by_doc = _citation_by_document(bundle)
    labels = {
        "decisions": "Decisions",
        "action_items": "Action items",
        "open_questions": "Open questions",
    }
    lines: List[str] = []
    claims: List[Dict[str, Any]] = []
    for key, heading in labels.items():
        if key not in records:
            continue
        rows = list(records.get(key) or [])
        lines.append(heading)
        if not rows:
            lines.append("- None found.")
            lines.append("")
            continue
        for row in rows:
            citations = _record_citations([row.get("document_id")], citation_by_doc)
            stale = " (stale derived record)" if row.get("stale") else ""
            date = row.get("date") or "undated"
            text = row.get("text") or ""
            lines.append(f"- {date} — {text}{stale}{_cite_text(citations)}")
            claims.append(_claim(len(claims) + 1, "fact", text, citations))
        lines.append("")
    return _answer("\n".join(lines).strip(), claims)


def _empty_answer(text: str) -> Dict[str, Any]:
    return _answer(text, [], insufficient=True)


def _answer(
    text: str,
    claims: Sequence[Dict[str, Any]],
    *,
    uncertainty: str = "",
    insufficient: bool = False,
) -> Dict[str, Any]:
    cited = sorted({value for claim in claims for value in claim.get("citations", [])})
    claim_list = list(claims)
    return {
        "version": "1",
        "answer": text,
        "cited_citation_ids": cited,
        "claims": claim_list,
        "claim_ledger": {
            "version": ledger_module.LEDGER_VERSION,
            "claims": claim_list,
            "rejected_claims": [],
            "warnings": [],
        },
        "conflicts": [],
        "uncertainty": uncertainty,
        "insufficient_evidence": insufficient,
        "inference_count": len([claim for claim in claim_list if claim.get("type") == "inference"]),
        "diagnostics": {
            "validator_notes": [],
            "dropped_citations": [],
            "rejected_fields": [],
            "rejected_claims": [],
            "grounding_warnings": [],
            "ungrounded_premises": [],
            "softened_negatives": [],
        },
        "dropped_citations": [],
        "rejected_fields": [],
        "rejected_claims": [],
        "grounding_warnings": [],
        "ungrounded_premises": [],
        "softened_negatives": [],
        "reason": "deterministic-capability",
    }


def _claim(index: int, claim_type: str, text: str, citations: Sequence[int]) -> Dict[str, Any]:
    return {
        "id": f"c{index}",
        "type": claim_type,
        "text": text,
        "citations": [value for value in citations if value],
        "status": ledger_module.ACCEPTED,
        "numeric_check": "not-applicable",
        "entity_linkage": "not-applicable",
    }


def _participant_signal(row: Dict[str, Any]) -> str:
    reasons = [str(value) for value in row.get("reasons") or [] if value]
    if row.get("band") == affiliation_module.UNCLEAR:
        return "insufficient evidence to classify"
    if reasons:
        return "; ".join(reasons[:3])
    signals = row.get("signals") or {}
    bits = []
    if signals.get("documents"):
        bits.append(f"appears in {signals['documents']} document(s)")
    if signals.get("email_domains"):
        bits.append("email domain: " + ", ".join(signals["email_domains"]))
    return "; ".join(bits) if bits else "supporting deterministic signals"


def _structured_route(tool: str, key: str, plan: Any, label: str) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {}
    topic = _topic(plan, generic=STRUCTURED_STOPWORDS)
    if topic:
        arguments["topic"] = topic
    if getattr(plan, "entity_ids", None):
        arguments["entity_id"] = plan.entity_ids[0]
    return {
        "tool": tool,
        "arguments": arguments,
        "key": key,
        "reason": f"{label} routed to deterministic structured records",
    }


def _timeline_arguments(plan: Any) -> Dict[str, Any]:
    arguments: Dict[str, Any] = {}
    if getattr(plan, "text_queries", None):
        arguments["text_queries"] = list(plan.text_queries)[:MAX_TEXT_QUERIES]
    if getattr(plan, "entity_ids", None):
        arguments["entity_ids"] = list(plan.entity_ids)
    _date_bounds(arguments, plan)
    return arguments


def _topic(plan: Any, *, generic: set) -> str:
    for query in getattr(plan, "text_queries", []) or []:
        words = [word for word in re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", query) if _fold(word) not in generic]
        if words:
            return " ".join(words)
    return ""


def _date_bounds(arguments: Dict[str, Any], plan: Any) -> None:
    date_range = getattr(plan, "date_range", None)
    if not date_range:
        return
    if getattr(date_range, "start", ""):
        arguments["since"] = date_range.start
    if getattr(date_range, "end", ""):
        arguments["until"] = date_range.end


def _asks_decisions(text: str) -> bool:
    return bool(re.search(r"\b(decisions?|decided|agreed|settled)\b", text))


def _asks_action_items(text: str) -> bool:
    return bool(re.search(r"\b(action\s+items?|owners?|owned|responsible|accountable)\b", text))


def _asks_open_questions(text: str) -> bool:
    return bool(re.search(r"\b(open\s+questions?|unresolved|blockers?|blocking|blocked|undecided)\b", text))


def _citation_by_document(bundle: Any) -> Dict[str, int]:
    return {item.document_id: item.citation_id for item in bundle.items}


def _record_citations(document_ids: Sequence[Any], citation_by_doc: Dict[str, int]) -> List[int]:
    citations: List[int] = []
    for document_id in document_ids:
        citation = citation_by_doc.get(str(document_id or ""))
        if citation and citation not in citations:
            citations.append(citation)
    return citations


def _valid_citation(value: Any, valid: set) -> int:
    try:
        citation = int(value)
    except (TypeError, ValueError):
        return 0
    return citation if citation in valid else 0


def _cite_text(citations: Sequence[int]) -> str:
    values = [value for value in citations if value]
    return " " + "".join(f"[{value}]" for value in values) if values else ""


def _short(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "..."


def _fold(text: str) -> str:
    return str(text or "").casefold()
