"""Read-only corpus analysis of unresolved entity strings.

Answers "which canonical entities should I create first?" without touching
anything. Extraction is deterministic: it reads the Epic 05 enrichment strings
and existing stable references already present in canonical frontmatter. No AI.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from .documents import EntityDocumentStore
from .model import normalize_name, string_value, validate_entity_type
from .resolver import AMBIGUOUS, RESOLVED, EntityResolver


def collect_candidates(
    documents: EntityDocumentStore,
    resolver: EntityResolver,
    *,
    entity_type: Optional[str] = None,
    unresolved_only: bool = False,
) -> List[Dict[str, Any]]:
    wanted = validate_entity_type(entity_type) if entity_type else None
    buckets: Dict[tuple, Dict[str, Any]] = {}

    for document in documents.iter_documents():
        already_referenced = {
            (string_value(ref.get("entity_type")), normalize_name(ref.get("label")))
            for ref in document.mentions
        }
        for candidate_type, values in document.candidate_strings.items():
            if wanted and candidate_type != wanted:
                continue
            for text in values:
                key = (candidate_type, normalize_name(text))
                bucket = buckets.setdefault(
                    key,
                    {
                        "text": text,
                        "entity_type": candidate_type,
                        "documents": 0,
                        "document_ids": [],
                        "already_referenced": 0,
                    },
                )
                bucket["documents"] += 1
                bucket["document_ids"].append(document.document_id)
                if key in already_referenced:
                    bucket["already_referenced"] += 1

    rows: List[Dict[str, Any]] = []
    for bucket in buckets.values():
        resolution = resolver.resolve(bucket["text"], entity_type=bucket["entity_type"])
        row = {
            **bucket,
            "document_ids": sorted(bucket["document_ids"]),
            "status": resolution.status,
            "entity_id": resolution.entity_id,
            "entity_name": resolution.name,
            "reason": resolution.reason,
            "candidates": [
                {
                    "entity_id": candidate.entity_id,
                    "name": candidate.name,
                    "entity_type": candidate.entity_type,
                    "reason": candidate.reason,
                }
                for candidate in resolution.candidates
            ],
        }
        if unresolved_only and row["status"] == RESOLVED:
            continue
        rows.append(row)

    return sorted(rows, key=lambda row: (-row["documents"], row["entity_type"], row["text"].casefold()))


def summarize(rows: Iterable[Dict[str, Any]]) -> Dict[str, int]:
    rows = list(rows)
    return {
        "candidates": len(rows),
        "resolved": sum(1 for row in rows if row["status"] == RESOLVED),
        "ambiguous": sum(1 for row in rows if row["status"] == AMBIGUOUS),
        "unresolved": sum(1 for row in rows if row["status"] not in (RESOLVED, AMBIGUOUS)),
    }
