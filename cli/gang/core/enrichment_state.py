"""Deterministic answer to one question: is a document's enrichment current?

Canonical source content is always authoritative. Derived enrichment — the
``summary`` / ``decisions`` / ``action_items`` / ``unresolved_questions``
frontmatter written by an applied enrichment proposal — is not. When the
document changes after enrichment was applied, that derived metadata describes
an older version of the document and must never be presented as current fact.

Status is derived, never stored as new canonical state:

``none``
    The document carries no derived enrichment.
``current``
    Either a human authored the enrichment, or the most recent applied
    proposal's resulting hash still matches the document on disk.
``stale``
    An enrichment proposal was applied, and the document has changed since.

A document may also declare ``enrichment_state.status`` in its frontmatter. If
it does, that declaration wins — it lets an ingestion adapter mark derived
metadata stale without this module having to guess.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


CURRENT = "current"
STALE = "stale"
NONE = "none"

STATUSES = (CURRENT, STALE, NONE)

#: Frontmatter fields written by enrichment. Their presence means "derived".
ENRICHMENT_FIELDS = ("summary", "decisions", "action_items", "unresolved_questions")


class EnrichmentLedger:
    """Applied-proposal history, read once per index build.

    The ledger is the append-only audit trail ``EnrichmentService`` already
    writes to ``GANG_HOME/enrichment/audit.jsonl``. Nothing here writes to it.
    """

    def __init__(self, applied_hashes: Optional[Dict[str, str]] = None):
        self._applied_hashes = dict(applied_hashes or {})

    @classmethod
    def from_audit_log(cls, audit_path: Path | str) -> "EnrichmentLedger":
        path = Path(audit_path)
        if not path.exists():
            return cls()
        applied: Dict[str, str] = {}
        for record in _read_jsonl(path):
            if record.get("event") != "apply" or record.get("apply_status") != "applied":
                continue
            document_id = _text(record.get("document_id"))
            resulting_hash = _text(record.get("resulting_hash"))
            if document_id and resulting_hash:
                # Later records win: the newest successful apply is the baseline.
                applied[document_id] = resulting_hash
        return cls(applied)

    def applied_hash(self, document_id: str) -> str:
        return self._applied_hashes.get(document_id, "")

    def status_for(
        self,
        *,
        document_id: str,
        frontmatter: Dict[str, Any],
        raw_text: str,
    ) -> str:
        declared = declared_status(frontmatter)
        if declared:
            return declared
        if not has_enrichment(frontmatter):
            return NONE
        baseline = self.applied_hash(document_id)
        if not baseline:
            # Enrichment exists but no proposal was ever applied to this
            # document, so a human authored it. Authored metadata is current.
            return CURRENT
        return CURRENT if baseline == document_hash(raw_text) else STALE


def declared_status(frontmatter: Dict[str, Any]) -> str:
    """Honor an explicit ``enrichment_state.status`` declaration, if present."""
    state = frontmatter.get("enrichment_state")
    if not isinstance(state, dict):
        return ""
    status = _text(state.get("status")).lower()
    return status if status in STATUSES else ""


def has_enrichment(frontmatter: Dict[str, Any]) -> bool:
    return any(not _empty(frontmatter.get(field)) for field in ENRICHMENT_FIELDS)


def enrichment_payload(frontmatter: Dict[str, Any]) -> Dict[str, Any]:
    """The derived fields themselves, for display alongside their status."""
    payload: Dict[str, Any] = {}
    for field in ENRICHMENT_FIELDS:
        value = frontmatter.get(field)
        if not _empty(value):
            payload[field] = value
    return payload


def document_hash(raw_text: str) -> str:
    """Hash of the full Markdown file, matching what an apply records."""
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()


def _read_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()
