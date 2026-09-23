"""Build, invalidate, and serve generated evidence facts.

``EvidenceFactService.build()`` walks the canonical vault, classifies each
document's source, runs the deterministic extractors over the documents that
changed, and passes every proposed claim through ``model.validate_proposal``.
Queries read the result: grouped identity claims for "who is X?", and
topic-matched decision records for "what did we decide about X?".

Nothing here writes canonical Markdown. The only durable, human-owned file is
the overrides list (``GANG_HOME/facts/overrides.yml``), which lets a person
suppress a generated fact or decision without touching the document it came
from, and which survives any number of rebuilds because fact ids are derived
from the claim and its words, not from the extractor run.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml

from core.entities.documents import EntityDocument, EntityDocumentStore
from core.entities.model import EntityRecord, string_value
from core.entities.store import EntityStore
from core.paths import GangPaths
from core.source_classes import (
    SourceClass,
    classify_source,
    rank_of,
    senders_from_frontmatter,
)

from . import model as model_module
from .decisions import extract_decisions
from .extract import EntityIndex, extract_relations
from .model import (
    CONFIDENCE_HIGH,
    EXTRACTOR_VERSION,
    FACTS_SCHEMA_VERSION,
    METHOD_DETERMINISTIC,
    PREDICATE_ORDER,
    ClaimProposal,
    ClaimValidationError,
    DecisionRecord,
    EvidenceFact,
    decision_id,
    fact_id,
    higher_confidence,
    normalized_statement,
    readable,
    validate_proposal,
)
from .store import (
    META_BUILT_AT,
    META_ENTITY_FINGERPRINT,
    META_EXTRACTOR_VERSION,
    META_SCHEMA_VERSION,
    FactStore,
)


MAX_CLAIM_CITATIONS = 4
MAX_REPORTED_REJECTIONS = 25

#: Words that say what kind of question it is rather than what it is about.
_TOPIC_STOPWORDS = frozenset(
    """
    a an the and or of to in on for with about regarding around re what which who whom
    whose when where why how did do does done we i you they our us it its is are was
    were be been being have has had decide decided decides deciding decision decisions
    agree agreed agreement settle settled choose chose chosen conclude concluded
    make made final finally actually ever so far yet recently latest last
    """.split()
)

_MONTHS = {
    name: index
    for index, names in enumerate(
        [
            ("jan", "january"), ("feb", "february"), ("mar", "march"), ("apr", "april"),
            ("may",), ("jun", "june"), ("jul", "july"), ("aug", "august"),
            ("sep", "sept", "september"), ("oct", "october"), ("nov", "november"),
            ("dec", "december"),
        ],
        start=1,
    )
    for name in names
}
_TITLE_DATE = re.compile(
    r"\b(?P<month>[A-Z][a-z]{2,8})\.?\s+(?P<day>\d{1,2}),?\s+(?P<year>20\d{2})\b"
)
_ISO_DATE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")


class EvidenceFactService:
    """The generated evidence-facts layer, end to end."""

    def __init__(
        self,
        *,
        root_path: Path | str = Path("."),
        private_home: Path | str | None = None,
        entities: Optional[EntityStore] = None,
        documents: Optional[EntityDocumentStore] = None,
    ):
        self.root_path = Path(root_path).resolve()
        self.paths = GangPaths.from_env(repo_root=self.root_path, gang_home=private_home)
        self.entities = entities or EntityStore(root_path=self.root_path, private_home=self.paths.home)
        self.documents = documents or EntityDocumentStore(
            root_path=self.root_path, private_home=self.paths.home
        )
        self.store = FactStore(self.paths.evidence_facts_path)
        self.overrides_path = self.paths.facts_overrides_path

    # -------------------------------------------------------------- build

    def build(self, *, force: bool = False, now: Optional[str] = None) -> Dict[str, Any]:
        """Bring the store up to date with the vault. Idempotent.

        Only documents whose source hash or extractor version changed are
        re-extracted; a changed entity registry, a new extractor version, or
        ``force`` re-extracts everything.
        """
        records = self.entities.load_all()
        index = EntityIndex(records)
        fingerprint = entity_fingerprint(records)
        known_addresses, known_domains = _identifiers(records)
        stamp = now or _now_iso()

        meta = self.store.metadata()
        full = (
            force
            or not self.store.exists()
            or meta.get(META_ENTITY_FINGERPRINT) != fingerprint
            or meta.get(META_EXTRACTOR_VERSION) != str(EXTRACTOR_VERSION)
            or meta.get(META_SCHEMA_VERSION) != str(FACTS_SCHEMA_VERSION)
        )

        report: Dict[str, Any] = {
            "database": str(self.store.database_path),
            "extractor_version": EXTRACTOR_VERSION,
            "full_rebuild": full,
            "scanned": 0,
            "extracted": 0,
            "unchanged": 0,
            "removed": 0,
            "malformed": 0,
            "rejected": 0,
            "rejections": [],
            "by_source_class": {},
        }

        connection = self.store.writer()
        malformed: List[str] = []
        try:
            if full:
                self.store.reset(connection)
            existing: Dict[str, Dict[str, Any]] = {
                row["document_id"]: dict(row)
                for row in connection.execute(
                    "SELECT document_id, source_hash, extractor_version, source_class, path, "
                    "file_mtime_ns, file_size FROM sources"
                )
            }
            by_path = {row["path"]: row for row in existing.values() if row.get("path")}
            seen: set = set()
            for path in self.documents.markdown_paths():
                try:
                    stat = path.stat()
                except OSError:
                    continue
                row = by_path.get(str(path))
                if (
                    row is not None
                    and row["document_id"] not in seen
                    and int(row["file_mtime_ns"]) == stat.st_mtime_ns
                    and int(row["file_size"]) == stat.st_size
                    and int(row["extractor_version"]) == EXTRACTOR_VERSION
                ):
                    # Untouched since it was last extracted: no need to even
                    # parse it. This is what keeps a refresh cheap enough to
                    # run before every question.
                    seen.add(row["document_id"])
                    report["scanned"] += 1
                    report["unchanged"] += 1
                    _count(report, row["source_class"])
                    continue

                document, broken = self.documents.read_path(path)
                if broken is not None:
                    malformed.append(str(path))
                    continue
                if document is None or document.document_id in seen:
                    continue
                seen.add(document.document_id)
                report["scanned"] += 1
                prepared = _prepare(document, known_addresses, known_domains)
                _count(report, prepared["source_class"].name)
                source_row = {
                    "document_id": document.document_id,
                    "source_hash": prepared["source_hash"],
                    "payload_hash": prepared["payload_hash"],
                    "source_class": prepared["source_class"].name,
                    "source_rank": prepared["source_class"].rank,
                    "source_reason": prepared["source_class"].reason,
                    "document_date": prepared["document_date"],
                    "title": document.title,
                    "path": str(path),
                    "file_mtime_ns": stat.st_mtime_ns,
                    "file_size": stat.st_size,
                    "extracted_at": stamp,
                }
                previous = existing.get(document.document_id)
                if (
                    previous is not None
                    and previous["source_hash"] == prepared["source_hash"]
                    and int(previous["extractor_version"]) == EXTRACTOR_VERSION
                ):
                    # Touched but not changed: remember where and when, keep
                    # the facts exactly as they are.
                    connection.execute(
                        "UPDATE sources SET path = ?, file_mtime_ns = ?, file_size = ? WHERE document_id = ?",
                        (str(path), stat.st_mtime_ns, stat.st_size, document.document_id),
                    )
                    report["unchanged"] += 1
                    continue

                facts, decisions, rejections = self._extract(document, prepared, index)
                report["rejected"] += len(rejections)
                for rejection in rejections:
                    if len(report["rejections"]) < MAX_REPORTED_REJECTIONS:
                        report["rejections"].append(rejection)
                self.store.replace_document(
                    connection, source=source_row, facts=facts, decisions=decisions
                )
                report["extracted"] += 1

            report["malformed"] = len(malformed)
            report["removed"] = self.store.remove_documents(connection, sorted(set(existing) - seen))
            changed = full or report["extracted"] or report["removed"]
            metadata = {
                META_SCHEMA_VERSION: str(FACTS_SCHEMA_VERSION),
                META_EXTRACTOR_VERSION: str(EXTRACTOR_VERSION),
                META_ENTITY_FINGERPRINT: fingerprint,
            }
            if changed or META_BUILT_AT not in meta:
                metadata[META_BUILT_AT] = stamp
            self.store.set_metadata(connection, metadata)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        report.update(self.store.counts())
        return report

    def ensure_current(self) -> bool:
        """Build if the store is missing or was built against a different
        extractor or entity registry. Returns whether the store is usable.

        Per-document staleness is not checked here — that would mean reading
        the whole vault on every question. It is caught at answer time
        instead, where every cited excerpt is re-verified against the current
        index text before it is shown.
        """
        try:
            meta = self.store.metadata()
            if (
                self.store.exists()
                and meta.get(META_SCHEMA_VERSION) == str(FACTS_SCHEMA_VERSION)
                and meta.get(META_EXTRACTOR_VERSION) == str(EXTRACTOR_VERSION)
                and meta.get(META_ENTITY_FINGERPRINT) == entity_fingerprint(self.entities.load_all())
            ):
                return True
            self.build()
            return True
        except Exception:  # noqa: BLE001 - a generated layer never fails an answer
            return False

    def _extract(
        self, document: EntityDocument, prepared: Dict[str, Any], index: EntityIndex
    ) -> Tuple[List[EvidenceFact], List[DecisionRecord], List[Dict[str, str]]]:
        source_class: SourceClass = prepared["source_class"]
        body = document.body
        facts: Dict[str, EvidenceFact] = {}
        decisions: Dict[str, DecisionRecord] = {}
        rejections: List[Dict[str, str]] = []

        if source_class.identity_evidence:
            proposals = extract_relations(
                document_id=document.document_id,
                body=body,
                index=index,
                sender_addresses=prepared["senders"],
            )
            forms = index.surface_forms()
            for proposal in proposals:
                try:
                    admitted = validate_proposal(
                        proposal, source_text=body, entities=index.records, surface_forms=forms
                    )
                except ClaimValidationError as exc:
                    rejections.append(
                        {"document_id": document.document_id, "rule": proposal.rule, "reason": str(exc)}
                    )
                    continue
                fact = _fact_from_proposal(admitted, prepared)
                facts.setdefault(fact.fact_id, fact)

        if source_class.decision_evidence:
            formal = source_class.name != "email"
            for candidate in extract_decisions(body, formal=formal):
                if not model_module.quote_in_source(candidate.text, body):
                    rejections.append(
                        {
                            "document_id": document.document_id,
                            "rule": candidate.rule,
                            "reason": "Decision text does not appear in the source document",
                        }
                    )
                    continue
                record = DecisionRecord(
                    decision_id=decision_id(document_id=document.document_id, text=candidate.text),
                    document_id=document.document_id,
                    text=candidate.text,
                    status=candidate.status,
                    method=METHOD_DETERMINISTIC,
                    rule=candidate.rule,
                    extractor_version=EXTRACTOR_VERSION,
                    source_hash=prepared["source_hash"],
                    source_class=source_class.name,
                    source_rank=source_class.rank,
                    decision_date=prepared["decision_date"],
                    context=candidate.context,
                )
                decisions.setdefault(record.decision_id, record)

        return list(facts.values()), list(decisions.values()), rejections

    # ------------------------------------------------------------ queries

    def facts_for(
        self,
        entity_id: str,
        *,
        min_confidence: str = CONFIDENCE_HIGH,
        include_suppressed: bool = False,
    ) -> List[EvidenceFact]:
        """Facts whose subject is this entity, names resolved, best first."""
        records = {record.id: record for record in self.entities.load_all()}
        suppressed = self.suppressed_ids()
        result: List[EvidenceFact] = []
        for fact in self.store.facts(subject_entity_id=entity_id):
            if not higher_confidence(fact.confidence, min_confidence):
                continue
            is_suppressed = fact.fact_id in suppressed
            if is_suppressed and not include_suppressed:
                continue
            subject = records.get(fact.subject_entity_id)
            target = records.get(fact.object_entity_id) if fact.object_entity_id else None
            if subject is None or subject.status != "active":
                continue
            if fact.object_entity_id and (target is None or target.status != "active"):
                continue
            result.append(
                replace(
                    fact,
                    subject_name=subject.name,
                    object_name=target.name if target else "",
                    suppressed=is_suppressed,
                )
            )
        return result

    def identity_claims(self, entity_id: str) -> List[Dict[str, Any]]:
        """High-confidence facts about one entity, one entry per distinct claim.

        The same claim stated in sixteen emails is one claim with sixteen
        supporting documents; the strongest sources are cited first.
        """
        groups: Dict[tuple, List[EvidenceFact]] = {}
        for fact in self.facts_for(entity_id):
            groups.setdefault(fact.claim_key(), []).append(fact)

        claims: List[Dict[str, Any]] = []
        for facts in groups.values():
            # Strongest source first; within one source, the plainest quote.
            facts.sort(
                key=lambda item: (-item.source_rank, _date_key(item.document_date), len(item.excerpt), item.fact_id)
            )
            best = facts[0]
            document_ids: List[str] = []
            for fact in facts:
                if fact.document_id not in document_ids:
                    document_ids.append(fact.document_id)
            claims.append(
                {
                    "sentence": best.sentence(),
                    "predicate": best.predicate,
                    "subject_entity_id": best.subject_entity_id,
                    "subject_name": best.subject_name,
                    "object_entity_id": best.object_entity_id,
                    "object_name": best.object_name,
                    "object_value": best.object_value,
                    "role": best.role,
                    "confidence": best.confidence,
                    "support": len(document_ids),
                    "document_ids": document_ids[:MAX_CLAIM_CITATIONS],
                    "fact_ids": [fact.fact_id for fact in facts],
                    "evidence": [
                        {
                            "fact_id": fact.fact_id,
                            "document_id": fact.document_id,
                            "document_title": fact.document_title,
                            "document_date": fact.document_date,
                            "excerpt": fact.excerpt,
                            "source_class": fact.source_class,
                            "rule": fact.rule,
                            "method": fact.method,
                            "extractor_version": fact.extractor_version,
                        }
                        for fact in facts[:MAX_CLAIM_CITATIONS]
                    ],
                    "generated": True,
                    "canonical": False,
                }
            )
        claims.sort(
            key=lambda item: (
                PREDICATE_ORDER.get(item["predicate"], 99),
                -max(entry_rank(item)),
                -item["support"],
                item["sentence"],
            )
        )
        return claims

    def decisions(
        self,
        *,
        topic: str = "",
        since: str = "",
        until: str = "",
        limit: int = 12,
        include_suppressed: bool = False,
    ) -> Dict[str, Any]:
        """Decision records matching a topic, one per distinct statement,
        newest first. ``total`` counts matches before the limit."""
        terms = topic_terms(topic)
        suppressed = self.suppressed_ids()
        groups: Dict[str, List[DecisionRecord]] = {}
        for record in self.store.decisions():
            if record.decision_id in suppressed and not include_suppressed:
                continue
            if terms and not matches_topic(record, terms):
                continue
            if since and record.decision_date and record.decision_date < since:
                continue
            if until and record.decision_date and record.decision_date > until:
                continue
            groups.setdefault(normalized_statement(record.text), []).append(record)

        merged: List[DecisionRecord] = []
        for records in groups.values():
            records.sort(key=lambda item: (-item.source_rank, _date_key(item.decision_date), item.decision_id))
            primary = records[0]
            others = [item.document_id for item in records[1:] if item.document_id != primary.document_id]
            merged.append(
                replace(
                    primary,
                    corroborating_document_ids=list(dict.fromkeys(others))[: MAX_CLAIM_CITATIONS - 1],
                    suppressed=primary.decision_id in suppressed,
                )
            )
        merged.sort(key=lambda item: (item.decision_date or "", item.source_rank), reverse=True)
        return {
            "topic": " ".join(terms),
            "total": len(merged),
            "decisions": [record.to_dict() for record in merged[: max(1, int(limit))]],
        }

    def status(self) -> Dict[str, Any]:
        meta = self.store.metadata()
        return {
            "database": str(self.store.database_path),
            "exists": self.store.exists(),
            "extractor_version": EXTRACTOR_VERSION,
            "built_extractor_version": meta.get(META_EXTRACTOR_VERSION, ""),
            "built_at": meta.get(META_BUILT_AT, ""),
            "suppressed": len(self.suppressed_ids()),
            **self.store.counts(),
        }

    def clear(self) -> bool:
        return self.store.clear()

    # ---------------------------------------------------------- overrides

    def suppressed_ids(self) -> set:
        return {entry["id"] for entry in self._overrides().get("suppressed", []) if entry.get("id")}

    def suppress(self, item_id: str, *, reason: str = "") -> Dict[str, Any]:
        """Hide one generated fact or decision from answers. The source
        document is not touched and the record stays in the generated store."""
        item_id = string_value(item_id)
        if not re.fullmatch(r"(?:fact|dec)_[0-9a-f]{32}", item_id):
            raise ValueError(f"Not a generated fact or decision id: {item_id!r}")
        overrides = self._overrides()
        entries = [entry for entry in overrides.get("suppressed", []) if entry.get("id") != item_id]
        entry = {"id": item_id, "reason": reason, "at": _now_iso()}
        entries.append(entry)
        overrides["suppressed"] = sorted(entries, key=lambda item: item["id"])
        self.overrides_path.parent.mkdir(parents=True, exist_ok=True)
        self.overrides_path.write_text(
            yaml.safe_dump(overrides, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        return entry

    def unsuppress(self, item_id: str) -> bool:
        overrides = self._overrides()
        entries = overrides.get("suppressed", [])
        kept = [entry for entry in entries if entry.get("id") != item_id]
        if len(kept) == len(entries):
            return False
        overrides["suppressed"] = kept
        self.overrides_path.write_text(
            yaml.safe_dump(overrides, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
        return True

    def _overrides(self) -> Dict[str, Any]:
        if not self.overrides_path.exists():
            return {"suppressed": []}
        try:
            payload = yaml.safe_load(self.overrides_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            return {"suppressed": []}
        if not isinstance(payload, dict):
            return {"suppressed": []}
        payload["suppressed"] = [
            entry for entry in payload.get("suppressed") or [] if isinstance(entry, dict)
        ]
        return payload


# ------------------------------------------------------------------ helpers


def _count(report: Dict[str, Any], source_class: str) -> None:
    classes = report["by_source_class"]
    classes[source_class] = classes.get(source_class, 0) + 1


def entity_fingerprint(records: Sequence[EntityRecord]) -> str:
    """Everything about the registry that changes what extraction can see."""
    payload = sorted(
        [
            record.id,
            record.type,
            record.name,
            record.status,
            record.merged_into or "",
            sorted(record.aliases),
            sorted(record.emails),
            sorted(record.domains),
        ]
        for record in records
    )
    return hashlib.sha256(
        json.dumps([EXTRACTOR_VERSION, payload], sort_keys=True).encode("utf-8")
    ).hexdigest()


def topic_terms(topic: str) -> List[str]:
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9'-]*", topic or "")
    terms: List[str] = []
    for word in words:
        folded = word.casefold().strip("'-")
        if folded and folded not in _TOPIC_STOPWORDS and folded not in terms:
            terms.append(folded)
    return terms


def matches_topic(record: DecisionRecord, terms: Sequence[str]) -> bool:
    """Every term, as a word stem, in the decision or the label it sits under."""
    haystack = readable(f"{record.text} {record.context}").casefold()
    return all(re.search(rf"\b{re.escape(_stem(term))}", haystack) for term in terms)


def _stem(term: str) -> str:
    """Enough stemming to let "packaging" find "package" and "packaged"."""
    for suffix in ("ing", "ed", "es", "s", "e"):
        if term.endswith(suffix) and len(term) - len(suffix) >= 4:
            return term[: -len(suffix)]
    return term


def entry_rank(claim: Dict[str, Any]) -> List[int]:
    return [rank_of(entry.get("source_class")) for entry in claim.get("evidence") or []] or [0]


def _prepare(document: EntityDocument, known_addresses: set, known_domains: set) -> Dict[str, Any]:
    frontmatter = document.frontmatter
    senders = senders_from_frontmatter(frontmatter)
    title = document.title
    source_type = string_value(frontmatter.get("source_type"))
    document_type = string_value(frontmatter.get("type"))
    source_class = classify_source(
        title=title,
        source_type=source_type,
        document_type=document_type,
        senders=senders,
        body=document.body,
        known_addresses=known_addresses,
        known_domains=known_domains,
    )
    created = string_value(frontmatter.get("created") or frontmatter.get("created_at"))
    updated = string_value(frontmatter.get("updated") or frontmatter.get("updated_at"))
    document_date = (created or updated)[:10]
    source_hash = hashlib.sha256(
        json.dumps(
            [title, source_type, document_type, created, updated, senders, document.body],
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "senders": senders,
        "source_class": source_class,
        "document_date": document_date,
        # A meeting's notes are dated by the meeting, not by when they were
        # mailed round; the title carries that date when there is one.
        "decision_date": _title_date(title) or document_date,
        "source_hash": source_hash,
        "payload_hash": string_value(frontmatter.get("payload_hash") or frontmatter.get("content_hash")),
    }


def _fact_from_proposal(proposal: ClaimProposal, prepared: Dict[str, Any]) -> EvidenceFact:
    source_class: SourceClass = prepared["source_class"]
    return EvidenceFact(
        fact_id=fact_id(
            document_id=proposal.document_id,
            subject_entity_id=proposal.subject_entity_id,
            predicate=proposal.predicate,
            object_entity_id=proposal.object_entity_id,
            object_value=proposal.object_value,
            role=proposal.role,
            excerpt=proposal.excerpt,
        ),
        document_id=proposal.document_id,
        subject_entity_id=proposal.subject_entity_id,
        predicate=proposal.predicate,
        excerpt=proposal.excerpt,
        method=proposal.method,
        rule=proposal.rule,
        confidence=proposal.confidence,
        extractor_version=EXTRACTOR_VERSION,
        source_hash=prepared["source_hash"],
        source_class=source_class.name,
        source_rank=source_class.rank,
        document_date=prepared["document_date"],
        object_entity_id=proposal.object_entity_id,
        object_value=proposal.object_value,
        object_value_type="text" if proposal.object_value else "",
        role=proposal.role,
    )


def _identifiers(records: Iterable[EntityRecord]) -> Tuple[set, set]:
    addresses: set = set()
    domains: set = set()
    for record in records:
        if record.status != "active":
            continue
        addresses.update(record.emails)
        domains.update(record.domains)
    return addresses, domains


def _title_date(title: str) -> str:
    iso = _ISO_DATE.search(title or "")
    if iso:
        return f"{iso.group(1)}-{iso.group(2)}-{iso.group(3)}"
    match = _TITLE_DATE.search(title or "")
    if not match:
        return ""
    month = _MONTHS.get(match.group("month").casefold())
    if not month:
        return ""
    try:
        return datetime(int(match.group("year")), month, int(match.group("day"))).date().isoformat()
    except ValueError:
        return ""


def _date_key(value: str) -> str:
    return value or "9999-99-99"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
