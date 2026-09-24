"""Build the bounded evidence bundle that synthesis is allowed to see.

Two jobs, both about restraint:

1. **Bound what leaves the machine.** A retrieved Gmail thread or Drive export
   can be enormous. Only a few short excerpts per document, chosen around the
   question's own terms, go into the bundle.
2. **Label what each item actually is.** Canonical body text, derived
   enrichment, and *stale* derived enrichment are carried in separate fields,
   so stale metadata can be shown as stale supporting material and can never be
   mistaken for current source evidence.

A document whose extracted text is binary residue rather than language is held
back entirely. The canonical document and its raw evidence are untouched — it
simply never reaches synthesis, and is reported separately so it stays visible
in diagnostics.

Citation IDs are assigned from the final rank order over *usable* evidence, so
the same evidence set always produces the same numbering and an unreadable
document can never be cited.

Excerpts and titles from a restricted or local-only document have any detected
identifier value (an SSN, a routing number) replaced by a marker. Each is a display
copy that travels into answers, session snapshots, and caches; the value is
almost never what a question is about, and the canonical document still holds
it for anyone who opens the file.

A bundle bound for a remote provider is a narrower copy
(`EvidenceBundle.for_remote_provider`): restricted and local-only items are
removed whole, before any request is built, and keep no place in it. Nothing is
cut out of an excerpt after the fact. Citation ids are preserved, so an answer
over the narrower bundle still points into the full source list.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, List, Optional, Sequence

from core import enrichment_state, sensitivity as sensitivity_module

from .grounding import (
    READABLE,
    TextQuality,
    assess_text_quality,
    first_readable_window,
)
from .plan import QueryPlan
from .temporal import date_prefix


MAX_EXCERPTS = 3
EXCERPT_CHARS = 320
MAX_ENTITY_REFS = 12
MAX_RELATIONSHIPS = 8
MAX_ENRICHMENT_ITEMS = 5

_WORD_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'._@-]*")


@dataclass(frozen=True)
class EvidenceItem:
    citation_id: int
    document_id: str
    title: str
    type: str
    source_type: str
    visibility: str
    created: str
    updated: str
    source_ids: List[str] = field(default_factory=list)
    entity_refs: List[Dict[str, Any]] = field(default_factory=list)
    relationships: List[Dict[str, Any]] = field(default_factory=list)
    excerpts: List[str] = field(default_factory=list)
    enrichment_status: str = enrichment_state.NONE
    enrichment: Dict[str, Any] = field(default_factory=dict)
    content_trust: str = "trusted"
    signals: Dict[str, Any] = field(default_factory=dict)
    extraction_quality: str = READABLE
    #: Alias forms per entity, used by grounding checks only. Deliberately not
    #: sent to the model: they widen matching, not understanding.
    entity_aliases: Dict[str, List[str]] = field(default_factory=dict)
    #: Disclosure level from the index. Empty means unknown, and unknown is
    #: never permitted to reach a remote provider. Not sent to any model.
    sensitivity: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "citation_id": self.citation_id,
            "document_id": self.document_id,
            "title": self.title,
            "type": self.type,
            "source_type": self.source_type,
            "visibility": self.visibility,
            "created": self.created,
            "updated": self.updated,
            "source_ids": list(self.source_ids),
            "entity_refs": list(self.entity_refs),
            "relationship_assertions": list(self.relationships),
            "excerpts": list(self.excerpts),
            "content_trust": self.content_trust,
            "enrichment_status": self.enrichment_status,
            "extraction_quality": self.extraction_quality,
            "signals": dict(self.signals),
        }
        if self.enrichment_status == enrichment_state.CURRENT and self.enrichment:
            payload["enrichment"] = dict(self.enrichment)
        elif self.enrichment_status == enrichment_state.STALE and self.enrichment:
            # Deliberately a different key. Stale derived metadata is offered as
            # historical context, never as a statement about the document now.
            payload["stale_enrichment"] = dict(self.enrichment)
            payload["stale_enrichment_warning"] = (
                "Derived from an older version of this document. Not current fact. "
                "Prefer the excerpts above."
            )
        return payload

    def source_entry(self) -> Dict[str, Any]:
        return {
            "citation_id": self.citation_id,
            "document_id": self.document_id,
            "title": self.title,
            "type": self.type,
            "source_type": self.source_type,
            "visibility": self.visibility,
            "updated": self.updated,
            "source_ids": list(self.source_ids),
            "enrichment_status": self.enrichment_status,
            "extraction_quality": self.extraction_quality,
            "sensitivity": self.sensitivity or "unknown",
        }

    def supporting_text(self) -> List[str]:
        """Text a claim about this item may legitimately be checked against.

        Source excerpts and relationship evidence, plus enrichment only while it
        is current. Titles and entity references are excluded on purpose: a
        title is not a statement, and a resolved entity is a retrieval artifact
        rather than a fact about the document.
        """
        texts = list(self.excerpts)
        texts.extend(item.get("excerpt", "") for item in self.relationships)
        if self.enrichment_status == enrichment_state.CURRENT:
            summary = self.enrichment.get("summary")
            if isinstance(summary, str):
                texts.append(summary)
        return [text for text in texts if text]

    def entity_forms(self) -> List[List[str]]:
        """Every surface form per entity: canonical name, label, and aliases."""
        groups: List[List[str]] = []
        for item in self.entity_refs:
            forms = [
                value
                for value in (_string(item.get("name")), _string(item.get("label")))
                if value
            ]
            forms.extend(self.entity_aliases.get(_string(item.get("entity_id")), []))
            forms = [value for index, value in enumerate(forms) if value not in forms[:index]]
            if forms and forms not in groups:
                groups.append(forms)
        for relationship in self.relationships:
            for value in (_string(relationship.get("subject")), _string(relationship.get("object"))):
                if value and [value] not in groups and not any(value in group for group in groups):
                    groups.append([value])
        return groups

    def linked_pairs(self) -> List[tuple]:
        """Entity pairs an evidence-backed relationship assertion connects."""
        return [
            (_string(item.get("subject")), _string(item.get("object")))
            for item in self.relationships
            if _string(item.get("subject")) and _string(item.get("object"))
        ]


@dataclass(frozen=True)
class ExcludedSource:
    """Retrieved, but held back from synthesis. Never deleted, never altered."""

    document_id: str
    title: str
    type: str
    source_type: str
    updated: str
    reason: str
    metrics: Dict[str, float] = field(default_factory=dict)
    sensitivity: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "title": self.title,
            "type": self.type,
            "source_type": self.source_type,
            "updated": self.updated,
            "excluded": True,
            "extraction_quality": "unreadable",
            "reason": self.reason,
            "metrics": {key: round(value, 4) for key, value in self.metrics.items()},
        }


@dataclass(frozen=True)
class EvidenceBundle:
    question: str
    items: List[EvidenceItem] = field(default_factory=list)
    ambiguities: List[Dict[str, Any]] = field(default_factory=list)
    date_range: Optional[Dict[str, str]] = None
    text_query_count: int = 0
    excluded: List[ExcludedSource] = field(default_factory=list)
    #: Retrieved sources held back from this bundle by sensitivity, as
    #: metadata for the local reader. Only the count ever reaches a model.
    withheld: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.items

    def for_remote_provider(self) -> "EvidenceBundle":
        """The copy of this bundle a remote provider may see.

        Items whose sensitivity does not permit remote disclosure are removed
        whole — excerpts, relationship evidence, enrichment, title, and all —
        along with any unreadable source that is not ``normal``. Nothing is
        edited, only left out.
        """
        kept = [item for item in self.items if sensitivity_module.permits_remote(item.sensitivity)]
        excluded = [
            item for item in self.excluded if sensitivity_module.permits_remote(item.sensitivity)
        ]
        withheld = [
            {
                "citation_id": item.citation_id,
                "document_id": item.document_id,
                "title": item.title,
                "sensitivity": item.sensitivity or "unknown",
            }
            for item in self.items
            if not sensitivity_module.permits_remote(item.sensitivity)
        ] + [
            {
                "citation_id": None,
                "document_id": item.document_id,
                "title": item.title,
                "sensitivity": item.sensitivity or "unknown",
            }
            for item in self.excluded
            if not sensitivity_module.permits_remote(item.sensitivity)
        ]
        return replace(self, items=kept, excluded=excluded, withheld=list(self.withheld) + withheld)

    @property
    def only_weak_matches(self) -> bool:
        """True when nothing matched on more than one of several search terms.

        Matching the single term in "documents mentioning Eliro" is complete
        coverage. Matching one term out of four — "decide", "zirconium",
        "supply", "contract" — is a coincidence, and presenting a list of those
        as results would imply the corpus holds an answer it does not.
        """
        if not self.items or self.text_query_count < 3:
            return False
        return all(
            item.signals.get("signal_classes", 0) <= 1
            and item.signals.get("text_term_hits", 0) <= 1
            for item in self.items
        )

    def by_citation(self) -> Dict[int, EvidenceItem]:
        return {item.citation_id: item for item in self.items}

    def supporting_texts(self, citation_ids: Sequence[int]) -> List[str]:
        by_id = self.by_citation()
        texts: List[str] = []
        for citation_id in citation_ids:
            item = by_id.get(citation_id)
            if item is not None:
                texts.extend(item.supporting_text())
        return texts

    def entity_forms(self) -> List[List[str]]:
        groups: List[List[str]] = []
        for item in self.items:
            for group in item.entity_forms():
                if group not in groups:
                    groups.append(group)
        return groups

    def linked_pairs(self, citation_ids: Sequence[int]) -> List[tuple]:
        by_id = self.by_citation()
        pairs: List[tuple] = []
        for citation_id in citation_ids:
            item = by_id.get(citation_id)
            if item is not None:
                pairs.extend(item.linked_pairs())
        return pairs

    def citation_ids(self) -> List[int]:
        return [item.citation_id for item in self.items]

    def temporal_ordering(self) -> List[Dict[str, str]]:
        """Newest-first view. Older evidence stays in the bundle, always."""
        ordered = sorted(
            self.items,
            key=lambda item: (date_prefix(item.updated or item.created), item.citation_id),
            reverse=True,
        )
        return [
            {
                "citation_id": item.citation_id,
                "document_id": item.document_id,
                "date": date_prefix(item.updated or item.created),
            }
            for item in ordered
        ]

    def sources(self) -> List[Dict[str, Any]]:
        return [item.source_entry() for item in self.items]

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "question": self.question,
            "evidence": [item.to_dict() for item in self.items],
            "temporal_ordering": self.temporal_ordering(),
            "ambiguous_names": list(self.ambiguities),
            "date_range": dict(self.date_range) if self.date_range else None,
            "only_weak_matches": self.only_weak_matches,
            # Metadata only. The corrupt text itself never reaches the model.
            "unreadable_sources": [
                {"title": item.title, "reason": item.reason} for item in self.excluded
            ],
        }
        if self.withheld:
            # A count, never a title: enough for the model to avoid reading
            # the gap as absence of evidence, nothing about what is in it.
            payload["withheld_sources"] = {
                "count": len(self.withheld),
                "rule": (
                    "This many retrieved sources are restricted or local-only and were "
                    "deliberately not provided to you. Do not speculate about their "
                    "content, and do not treat their absence as evidence that something "
                    "did not happen."
                ),
            }
        return payload

    def fingerprint(self) -> str:
        """Stable hash of the evidence content, for cache keying."""
        payload = [
            {
                "citation_id": item.citation_id,
                "document_id": item.document_id,
                "updated": item.updated,
                "excerpts": item.excerpts,
                "enrichment_status": item.enrichment_status,
            }
            for item in self.items
        ]
        return hashlib.sha256(
            json.dumps({"question": self.question, "items": payload}, sort_keys=True).encode("utf-8")
        ).hexdigest()


def build_bundle(
    question: str,
    rows: Sequence[Dict[str, Any]],
    plan: QueryPlan,
    *,
    ambiguities: Optional[Sequence[Dict[str, Any]]] = None,
    max_excerpts: int = MAX_EXCERPTS,
) -> EvidenceBundle:
    terms = _highlight_terms(plan)
    items: List[EvidenceItem] = []
    excluded: List[ExcludedSource] = []

    for row in rows:
        excerpts, quality = readable_excerpts(
            row.get("body") or "", terms, max_excerpts=max_excerpts
        )
        if not quality.readable:
            excluded.append(
                ExcludedSource(
                    document_id=row["document_id"],
                    title=_display_title(row),
                    type=row.get("type", ""),
                    source_type=row.get("source_type", ""),
                    updated=row.get("updated", ""),
                    reason=quality.reason,
                    metrics=quality.metrics,
                    sensitivity=_sensitivity(row),
                )
            )
            continue

        level = _sensitivity(row)
        relationships = _relationships(row.get("relationships") or [])
        if level in (sensitivity_module.RESTRICTED, sensitivity_module.LOCAL_ONLY):
            excerpts = [sensitivity_module.mask_identifiers(excerpt) for excerpt in excerpts]
            relationships = [
                {**item, "excerpt": sensitivity_module.mask_identifiers(item["excerpt"])}
                for item in relationships
            ]

        items.append(
            EvidenceItem(
                # Numbering runs over usable evidence only, so an unreadable
                # document has no citation id and cannot be cited.
                citation_id=len(items) + 1,
                document_id=row["document_id"],
                title=_display_title(row),
                type=row.get("type", ""),
                source_type=row.get("source_type", ""),
                visibility=row.get("visibility", ""),
                created=row.get("created", ""),
                updated=row.get("updated", ""),
                source_ids=list(row.get("source_ids") or []),
                entity_refs=_entity_refs(row.get("entity_refs") or []),
                entity_aliases=_entity_aliases(row.get("entity_refs") or []),
                relationships=relationships,
                excerpts=excerpts,
                enrichment_status=row.get("enrichment_status") or enrichment_state.NONE,
                enrichment=_bounded_enrichment(row.get("enrichment") or {}),
                content_trust=row.get("content_trust") or "trusted",
                signals=dict(row.get("signals") or {}),
                sensitivity=level,
            )
        )

    return EvidenceBundle(
        question=question,
        items=items,
        ambiguities=list(ambiguities or []),
        date_range=plan.date_range.to_dict() if plan.date_range else None,
        text_query_count=len(plan.text_queries),
        excluded=excluded,
    )


def readable_excerpts(
    body: str, terms: Sequence[str], *, max_excerpts: int = MAX_EXCERPTS
) -> tuple:
    """Excerpts that are actually language, plus the verdict on this document.

    Corruption is usually partial — an email whose header survives and whose
    body is a base64 blob. Excerpts chosen around query terms can land in the
    corrupt region even though readable text exists, so unreadable excerpts are
    dropped and a readable window is used instead. Only when nothing in the
    document reads as language is the document itself held back.
    """
    candidates = extract_excerpts(body, terms, max_excerpts=max_excerpts)
    kept = [excerpt for excerpt in candidates if assess_text_quality(excerpt).readable]
    if kept:
        return kept, TextQuality(READABLE, "", {})

    window = first_readable_window(body)
    if window:
        return [_truncate(window, EXCERPT_CHARS)], TextQuality(READABLE, "readable-window", {})
    return [], assess_text_quality(body)


def extract_excerpts(
    body: str, terms: Sequence[str], *, max_excerpts: int = MAX_EXCERPTS
) -> List[str]:
    """Bounded windows of the canonical body around the question's own terms."""
    text = re.sub(r"\s+", " ", body or "").strip()
    if not text:
        return []
    if not terms:
        return [_truncate(text, EXCERPT_CHARS)]

    lowered = text.lower()
    windows: List[tuple[int, int]] = []
    for term in terms:
        needle = term.lower().strip()
        if len(needle) < 2:
            continue
        position = lowered.find(needle)
        if position < 0:
            continue
        start = max(0, position - EXCERPT_CHARS // 3)
        end = min(len(text), position + len(needle) + (2 * EXCERPT_CHARS) // 3)
        windows.append((start, end))

    if not windows:
        return [_truncate(text, EXCERPT_CHARS)]

    excerpts: List[str] = []
    for start, end in _merge_windows(windows):
        excerpt = text[start:end].strip()
        if start > 0:
            excerpt = "... " + excerpt
        if end < len(text):
            excerpt = excerpt + " ..."
        if excerpt not in excerpts:
            excerpts.append(excerpt)
        if len(excerpts) >= max_excerpts:
            break
    return excerpts


def _merge_windows(windows: Sequence[tuple[int, int]]) -> List[tuple[int, int]]:
    merged: List[tuple[int, int]] = []
    for start, end in sorted(windows):
        if merged and start <= merged[-1][1]:
            previous_start, previous_end = merged[-1]
            merged[-1] = (previous_start, max(previous_end, end))
        else:
            merged.append((start, end))
    return merged


def _highlight_terms(plan: QueryPlan) -> List[str]:
    terms: List[str] = []
    for value in plan.text_queries:
        text = value.strip()
        if text and text not in terms:
            terms.append(text)
        for word in _WORD_PATTERN.findall(text):
            if len(word) > 3 and word not in terms:
                terms.append(word)
    return terms


def _entity_refs(values: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for value in values:
        entry = {
            "entity_id": value.get("entity_id", ""),
            "entity_type": value.get("entity_type", ""),
            "name": value.get("name") or value.get("label", ""),
            # The surface form the document actually used, which is what any
            # excerpt will contain.
            "label": value.get("label", "") or value.get("name", ""),
        }
        if entry not in result:
            result.append(entry)
        if len(result) >= MAX_ENTITY_REFS:
            break
    return result


def _entity_aliases(values: Iterable[Dict[str, Any]]) -> Dict[str, List[str]]:
    aliases: Dict[str, List[str]] = {}
    for value in values:
        entity_id = _string(value.get("entity_id"))
        forms = [_string(form) for form in (value.get("aliases") or []) if _string(form)]
        if entity_id and forms:
            aliases.setdefault(entity_id, []).extend(forms)
    return {key: sorted(set(value)) for key, value in aliases.items()}


def _relationships(values: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    result: List[Dict[str, Any]] = []
    for value in values:
        result.append(
            {
                "subject": value.get("subject", ""),
                "predicate": value.get("predicate", ""),
                "object": value.get("object", ""),
                "excerpt": _truncate(value.get("excerpt", ""), EXCERPT_CHARS),
            }
        )
        if len(result) >= MAX_RELATIONSHIPS:
            break
    return result


def _bounded_enrichment(value: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    summary = value.get("summary")
    if isinstance(summary, str) and summary.strip():
        payload["summary"] = _truncate(summary.strip(), EXCERPT_CHARS)
    for field_name in ("decisions", "action_items", "unresolved_questions"):
        items = value.get(field_name)
        if isinstance(items, list) and items:
            payload[field_name] = items[:MAX_ENRICHMENT_ITEMS]
    return payload


def _sensitivity(row: Dict[str, Any]) -> str:
    return sensitivity_module.normalize_level(row.get("sensitivity")) or ""


def _display_title(row: Dict[str, Any]) -> str:
    """The title as shown, masked like an excerpt for a sensitive document."""
    title = row.get("title") or row["document_id"]
    return sensitivity_module.mask_for_level(title, row.get("sensitivity"))


def _string(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."
