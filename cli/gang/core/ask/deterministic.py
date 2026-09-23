"""Deterministic Ask-mode routing and prose for code-owned capabilities.

``--no-ai`` means no model should decide how to answer. For question shapes
that already have typed primitives, this module gives those primitives first
refusal and renders their structured records directly. Generic full-text
retrieval remains the fallback for everything else.

Identity questions are answered here twice over: from the authored canonical
description when one exists, and otherwise from a derived entity profile —
reconstructed from cited evidence and rendered as a reconstruction. Both are
deterministic prose over structured records, so neither costs a model call.

Ownership questions ("what does Daniel need to do?") are answered from work
the evidence explicitly assigns to that person, and never from an authored
description or from attendance. The route is chosen from the question's own
shape before identity routing is considered, because "what does X need to
do" also looks like "what does X do" to a looser reading — which is how it
once ended up asking the canonical-description lookup for a task list.
"""

from __future__ import annotations

import calendar
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Sequence

from . import affiliation as affiliation_module
from . import assignments as assignments_module
from . import intent as intent_module
from . import ledger as ledger_module
from .plan import MAX_TEXT_QUERIES


#: Research record key carrying a derived entity profile, when the canonical
#: record has no authored description to answer with.
ENTITY_PROFILE_KEY = "entity_profile"

#: Synthesis reason for a reconstructed identity, distinct from the authored
#: one so a caller can tell a derived answer from a canonical one without
#: reading the prose.
DERIVED_PROFILE_REASON = "derived-entity-profile"

PROFILE_HEADER = (
    "Derived profile — reconstructed from cited corpus evidence. "
    "Nobody has authored a description of this entity."
)

PROFILE_FOOTER = (
    "This reconstruction is generated and rebuildable, not canonical knowledge. "
    "`gang entity describe` authors the canonical account, which takes precedence."
)

PROFILE_UNCERTAINTY = (
    "Assembled from explicit corpus evidence at answer time rather than from an "
    "authored record. No role, title, employment, or ownership is asserted beyond "
    "what the cited evidence states."
)

#: Research record key carrying one person's assigned work.
ASSIGNMENTS_KEY = "assignments"

#: Synthesis reason for a task list, so a caller can tell it apart from other
#: deterministic answers without reading the prose.
ASSIGNMENTS_REASON = "deterministic-assignments"

#: A pseudo-tool for an ownership question whose person could not be pinned
#: down: an ambiguous name, or "me" with no known principal. Answered by
#: saying so, never by picking a candidate.
UNRESOLVED_PERSON_TOOL = "unresolved_person"

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


def capability_routes(
    question: str,
    plan: Any,
    intent: Any,
    *,
    resolved_entities: Sequence[Dict[str, Any]] = (),
    ambiguities: Sequence[Dict[str, Any]] = (),
    self_identity: Optional[Dict[str, Any]] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Return deterministic primitive calls for a cleanly mapped question.

    ``None`` means "no clean mapping"; callers should use ordinary retrieval.
    An empty list is not returned: a mapped question always has one or more
    code-owned operations.

    ``self_identity`` is who "I" and "me" are — the authenticated principal
    for the web service, the sole configured principal for the CLI — as
    ``{"name": …, "entity_id": …}``. Without one, a first-person ownership
    question is answered by saying who it could not identify.
    """
    text = _fold(question)
    if getattr(intent, "wants_assignments", False):
        return [
            _assignment_route(
                getattr(intent, "subject", ""),
                plan,
                resolved_entities=resolved_entities,
                ambiguities=ambiguities,
                self_identity=self_identity,
            )
        ]

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
                "key": ENTITY_PROFILE_KEY,
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

    if ASSIGNMENTS_KEY in records:
        return _assignments_answer(records[ASSIGNMENTS_KEY][0], context.bundle)
    if "participants" in records:
        return _participants_answer(records["participants"], context.bundle)
    if records.get(ENTITY_PROFILE_KEY):
        # No authored description exists, so the answer is a reconstruction
        # and has to arrive labelled as one.
        return _entity_profile_answer(records[ENTITY_PROFILE_KEY][0], context.bundle)
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


def answers_without_documents(context: Any) -> bool:
    """Whether a capability answers even when no document survived.

    "Nothing is assigned to Frank" is a statement about Frank, reached by
    reading his evidence; it is not the generic "no documents matched", and
    rendering it as that would make a scoped absence look like a failed
    search.
    """
    return bool((context.records or {}).get(ASSIGNMENTS_KEY))


# ------------------------------------------------------------- assignments


def _assignment_route(
    subject: str,
    plan: Any,
    *,
    resolved_entities: Sequence[Dict[str, Any]],
    ambiguities: Sequence[Dict[str, Any]],
    self_identity: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Pin the question's person to a name or entity, then route to their tasks.

    Resolution order: "I"/"me" to the principal; otherwise a canonical name or
    verified alias the planner already resolved; otherwise the name exactly as
    written, which is matched literally against owners in the evidence. An
    ambiguous name is reported rather than resolved to whichever candidate
    sorted first.
    """
    reason = "ownership question routed to explicitly assigned work"
    arguments: Dict[str, Any] = {}
    _date_bounds(arguments, plan)
    _deadline_period_end(arguments, getattr(plan, "query", "") or "")

    if assignments_module.is_first_person(subject):
        name = str((self_identity or {}).get("name") or "").strip()
        if not name:
            return _unresolved_route(subject, "no-principal", reason=reason)
        arguments["person"] = name
        if (self_identity or {}).get("entity_id"):
            arguments["entity_id"] = self_identity["entity_id"]
        return {"tool": "find_assignments", "arguments": arguments, "key": ASSIGNMENTS_KEY, "reason": reason}

    for item in ambiguities:
        if _name_in_subject(item.get("text"), subject):
            return _unresolved_route(
                subject,
                "ambiguous",
                candidates=[candidate.get("name", "") for candidate in item.get("candidates") or []],
                reason=reason,
            )

    arguments["person"] = subject
    for entity in resolved_entities:
        if entity.get("entity_type") not in ("person", None):
            continue
        if _name_in_subject(entity.get("text"), subject):
            arguments["entity_id"] = entity["entity_id"]
            break
    return {"tool": "find_assignments", "arguments": arguments, "key": ASSIGNMENTS_KEY, "reason": reason}


def _deadline_period_end(arguments: Dict[str, Any], question: str) -> None:
    """Carry "this week" / "this month" to the end of the period for deadlines.

    Evidence ranges for the current period stop at today, which is right for
    "what happened this week" and wrong for "what is due this week": a task
    due on Friday is due this week even when asked on Wednesday.
    """
    until = arguments.get("until") or ""
    try:
        end = date.fromisoformat(until)
    except ValueError:
        return
    if re.search(r"\bthis\s+week\b", question, re.IGNORECASE):
        end = end + timedelta(days=6 - end.weekday())
    elif re.search(r"\bthis\s+month\b", question, re.IGNORECASE):
        end = end.replace(day=calendar.monthrange(end.year, end.month)[1])
    else:
        return
    arguments["until"] = end.isoformat()


def _unresolved_route(subject: str, why: str, *, candidates: Sequence[str] = (), reason: str) -> Dict[str, Any]:
    return {
        "tool": UNRESOLVED_PERSON_TOOL,
        "arguments": {"subject": subject, "why": why, "candidates": list(candidates)},
        "key": ASSIGNMENTS_KEY,
        "reason": reason,
    }


def unresolved_person_record(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """The assignment record for a person who could not be identified."""
    return {
        "person": {"label": arguments.get("subject") or "", "forms": [], "resolved": False, "entity_id": ""},
        "assignments": [],
        "unresolved": arguments.get("why") or "",
        "candidates": list(arguments.get("candidates") or []),
    }


def _assignments_answer(payload: Dict[str, Any], bundle: Any) -> Dict[str, Any]:
    """Render one person's assigned work as a task list, every line cited.

    Current work first; completed or superseded work, where a source says so,
    in its own short section rather than mixed in or silently dropped. A task
    whose documents did not survive into the evidence bundle is omitted rather
    than shown uncited.
    """
    person = payload.get("person") or {}
    label = str(person.get("label") or "This person")

    if payload.get("unresolved") == "no-principal":
        return _empty_answer(
            f"I can't tell who \"{label}\" is here: no principal identity is configured for "
            "this session, so there is no one to scope the task list to. Ask with a name instead."
        )
    if payload.get("unresolved") == "ambiguous":
        names = ", ".join(name for name in payload.get("candidates") or [] if name)
        return _empty_answer(
            f"\"{label}\" matches more than one person ({names}). "
            "Name the one you mean and I'll list their tasks."
        )

    citation_by_doc = _citation_by_document(bundle)
    current: List[str] = []
    closed: List[str] = []
    claims: List[Dict[str, Any]] = []
    for item in payload.get("assignments") or []:
        citations = _record_citations(item.get("document_ids") or [], citation_by_doc)
        task = str(item.get("task") or "").strip()
        if not citations or not task:
            continue
        details = _assignment_details(item)
        line = f"- {task}{' — ' + details if details else ''}{_cite_text(citations)}"
        (closed if item.get("closed") else current).append(line)
        claims.append(
            _claim(
                len(claims) + 1,
                "fact",
                f"{item.get('owner') or label} is assigned: {task}"
                + (f" ({details})" if details else ""),
                citations,
            )
        )

    if not claims:
        return _empty_answer(
            f"I found no tasks explicitly assigned to {label} in the private corpus. "
            "Being mentioned in, sent, or present at something is not counted as an assignment."
        )

    lines = [f"{label} — current action items", ""]
    lines.extend(current or ["- Nothing open is explicitly assigned in the evidence."])
    if closed:
        lines.extend(["", "Completed or superseded", *closed])
    remaining = int(payload.get("total") or 0) - len(payload.get("assignments") or [])
    if remaining > 0:
        lines.extend(["", f"{remaining} more assigned task(s) not shown."])

    uncertainty = ""
    if not person.get("resolved"):
        uncertainty = (
            f"No canonical person record or verified alias matched \"{label}\"; tasks were "
            "matched on that name as written in the evidence."
        )
    return _answer("\n".join(lines), claims, uncertainty=uncertainty, reason=ASSIGNMENTS_REASON)


def _assignment_details(item: Dict[str, Any]) -> str:
    bits: List[str] = []
    co_owners = [value for value in item.get("co_owners") or [] if value]
    if co_owners:
        bits.append("shared with " + ", ".join(co_owners))
    if item.get("deadline"):
        bits.append(f"due {item['deadline']}")
    if item.get("status_text"):
        bits.append(f"status: {item['status_text']}")
    if item.get("stale"):
        bits.append("stale derived record")
    return "; ".join(bits)


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


def _entity_profile_answer(payload: Dict[str, Any], bundle: Any) -> Dict[str, Any]:
    """Render a derived profile: labelled, cited line by line, claimed as fact.

    Every line is a fact about the corpus — what a document says, what a
    relationship records, where a name appears — so every line is a ``fact``
    claim. What is *derived* is the assembly, which is why the header, the
    footer, and the uncertainty all say so. A statement whose supporting
    documents did not survive into the bundle is dropped rather than shown
    uncited.
    """
    citation_by_doc = _citation_by_document(bundle)
    lines = [PROFILE_HEADER, ""]
    name = payload.get("name") or "This entity"
    entity_type = payload.get("entity_type") or ""
    lines.append(f"{name} ({entity_type})" if entity_type else str(name))

    claims: List[Dict[str, Any]] = []
    for statement in payload.get("statements") or []:
        # Ascending, because a profile line is read as prose and [2][3][4][1]
        # reads as a typo. Elsewhere citation order follows record order.
        citations = sorted(
            _record_citations(statement.get("document_ids") or [], citation_by_doc)
        )
        text = str(statement.get("text") or "").strip()
        if not citations or not text:
            continue
        lines.append(f"- {text}{_cite_text(citations)}")
        claims.append(_claim(len(claims) + 1, "fact", text, citations))

    if not claims:
        return _empty_answer(
            "I found no canonical entity description, and no cited evidence to "
            "reconstruct one from."
        )

    lines.extend(["", PROFILE_FOOTER])
    return _answer(
        "\n".join(lines),
        claims,
        uncertainty=PROFILE_UNCERTAINTY,
        reason=DERIVED_PROFILE_REASON,
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
    reason: str = "deterministic-capability",
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
        "reason": reason,
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


def _name_in_subject(name: Any, subject: str) -> bool:
    """Whether ``name`` is the subject, or a whole word inside it.

    Character containment is wrong here: "dan" is inside "daniel" and "ai" is
    inside "daniel", but neither is the person the question named. A resolved
    "Daniel" still matches the subject "Daniel Hirunrusme".
    """
    candidate = _fold(name).strip()
    haystack = _fold(subject).strip()
    if not candidate or not haystack:
        return False
    return re.search(rf"(?<!\w){re.escape(candidate)}(?!\w)", haystack) is not None
