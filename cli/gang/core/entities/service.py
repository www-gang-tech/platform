"""High-level façade over the entity layer, used by the CLI and acceptance tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from core.paths import GangPaths

from .backfill import BACKFILL_ENTITY_TYPES, run_backfill
from .candidates import collect_candidates, summarize
from .documents import EntityDocumentStore
from .graph import EntityGraph
from .model import EntityRecord, EntityValidationError, string_value, validate_entity_type, validate_predicate
from .proposals import (
    AnthropicEntityProposer,
    DeterministicEntityProposer,
    EntityProposalService,
    assert_relationship_evidence,
)
from .resolver import EntityResolver
from .store import EntityStore


class EntityService:
    def __init__(
        self,
        *,
        root_path: Path | str = Path("."),
        private_home: Path | str | None = None,
        vault_paths: Optional[Sequence[Path | str]] = None,
    ):
        self.root_path = Path(root_path).resolve()
        self.paths = GangPaths.from_env(repo_root=self.root_path, gang_home=private_home)
        self.store = EntityStore(root_path=self.root_path, private_home=self.paths.home)
        self.documents = EntityDocumentStore(
            root_path=self.root_path, private_home=self.paths.home, vault_paths=vault_paths
        )
        self.proposals = EntityProposalService(
            root_path=self.root_path, private_home=self.paths.home, vault_paths=vault_paths
        )

    # ------------------------------------------------------------- identity

    def resolver(self) -> EntityResolver:
        return EntityResolver(self.store.load_all())

    def create(self, entity_type: str, name: str, **kwargs) -> EntityRecord:
        record = self.store.create(entity_type, name, **kwargs)
        self.rebuild_index()
        return record

    def rename(self, entity_id: str, name: str) -> EntityRecord:
        record = self.store.rename(entity_id, name)
        self.rebuild_index()
        return record

    def add_alias(self, entity_id: str, alias: str, *, allow_ambiguous: bool = False) -> EntityRecord:
        record = self.store.add_alias(entity_id, alias, allow_ambiguous=allow_ambiguous)
        self.rebuild_index()
        return record

    def add_identifier(self, entity_id: str, *, email: str = "", domain: str = "") -> EntityRecord:
        record = self.store.add_identifier(entity_id, email=email, domain=domain)
        self.rebuild_index()
        return record

    def describe(
        self,
        entity_id: str,
        *,
        description: Optional[str] = None,
        body: Optional[str] = None,
    ) -> EntityRecord:
        """Author foundational knowledge for an entity. Human-authored only.

        Deliberately has no ``use_ai`` parameter and no provider. A company's
        account of itself is canonical knowledge, and canonical knowledge is
        not something a model is allowed to originate.
        """
        record = self.store.describe(entity_id, description=description, body=body)
        self.rebuild_index()
        return record

    def reclassify(self, entity_id: str, entity_type: str) -> Dict[str, Any]:
        """Change an entity's type, keeping its ID and rewriting every reference."""
        audit = self.store.reclassify(entity_id, entity_type, documents=self.documents)
        if audit["changed"]:
            self.rebuild_index()
        return audit

    def merge(self, source_id: str, target_id: str) -> Dict[str, Any]:
        """Explicit, audited merge: tombstone the source and rewrite references."""
        audit = self.store.merge(source_id, target_id)
        rewritten = self.documents.rewrite_entity_id(audit["source_entity_id"], audit["target_entity_id"])
        audit["rewritten_documents"] = [item["document_id"] for item in rewritten]
        self.store.record_audit({**audit, "event": "entity_merge_references_rewritten"})
        self.rebuild_index()
        return audit

    def resolve(self, text: str, *, entity_type: Optional[str] = None) -> Dict[str, Any]:
        return self.resolver().resolve(text, entity_type=entity_type).to_dict()

    # ------------------------------------------------------------- mentions

    def add_mention(
        self,
        document_id: str,
        entity_id: str,
        *,
        label: Optional[str] = None,
        excerpt: str = "",
    ) -> Dict[str, Any]:
        document = self.documents.load(document_id)
        record = self.store.follow_merges(entity_id)
        mention = {
            "entity_id": record.id,
            "entity_type": record.type,
            "label": string_value(label) or record.name,
        }
        if excerpt:
            mention["evidence"] = {"excerpt": excerpt}
        result = self.documents.apply_references(document, mentions=[mention])
        self.rebuild_index()
        return result

    # -------------------------------------------------------- relationships

    def assert_relationship(
        self,
        *,
        document_id: str,
        subject_entity_id: str,
        predicate: str,
        object_entity_id: str,
        excerpt: str,
        source_id: str = "",
    ) -> Dict[str, Any]:
        """Record an explicit, evidence-backed relationship on its source document."""
        document = self.documents.load(document_id)
        subject = self.store.follow_merges(subject_entity_id)
        object_ = self.store.follow_merges(object_entity_id)
        evidence: Dict[str, str] = {"excerpt": string_value(excerpt)}
        if source_id:
            evidence["source_id"] = source_id

        relationship = {
            "subject_entity_id": subject.id,
            "predicate": validate_predicate(predicate),
            "object_entity_id": object_.id,
            "document_id": document.document_id,
            "source_ids": document.source_ids,
            "evidence": evidence,
        }
        assert_relationship_evidence(document, [relationship])
        result = self.documents.apply_references(document, relationships=[relationship])
        self.rebuild_index()
        return result

    # -------------------------------------------------------------- backfill

    def backfill(self, entity_id: Optional[str] = None, *, apply: bool = False) -> Dict[str, Dict[str, Any]]:
        """Deterministically link existing documents to canonical entities.

        No AI, no fuzzy matching. See ``core.entities.backfill`` for the exact
        matching rules. Dry run unless ``apply=True``.
        """
        if entity_id:
            record = self.store.follow_merges(entity_id)
            if record.type not in BACKFILL_ENTITY_TYPES:
                raise EntityValidationError(
                    f"Backfill supports {' and '.join(BACKFILL_ENTITY_TYPES)} entities only, "
                    f"not {record.type!r}: {entity_id}"
                )
            records = [record]
        else:
            records = [record for record in self.store.list() if record.type in BACKFILL_ENTITY_TYPES]

        reports, changed = run_backfill(
            self.documents.iter_documents(), records, documents=self.documents, apply=apply
        )
        if apply and changed:
            self.rebuild_index()
        return {entity_id_: report.to_dict() for entity_id_, report in reports.items()}

    # ------------------------------------------------------------ proposals

    def propose(self, document_id: str, *, use_ai: bool = False, model: Optional[str] = None) -> Dict[str, Any]:
        provider = (
            AnthropicEntityProposer(model=model)
            if use_ai
            else DeterministicEntityProposer(self.resolver())
        )
        return self.proposals.create_proposal(document_id, provider=provider)

    def show_proposal(self, proposal_id: str) -> Dict[str, Any]:
        return self.proposals.load_proposal(proposal_id)

    def apply_proposal(self, proposal_id: str, *, create_new_entities: bool = False) -> Dict[str, Any]:
        return self.proposals.apply_proposal(proposal_id, create_new_entities=create_new_entities)

    # --------------------------------------------------------------- lookup

    def graph(self) -> EntityGraph:
        return EntityGraph(self.paths.index_path)

    def search(self, query: str, *, entity_type: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        try:
            return self.graph().search(query, entity_type=entity_type, limit=limit)
        except FileNotFoundError:
            self.rebuild_index()
            return self.graph().search(query, entity_type=entity_type, limit=limit)

    def show(self, entity_id: str) -> Dict[str, Any]:
        record = self.store.get(entity_id)
        try:
            return self.graph().show(record.id)
        except (FileNotFoundError, KeyError):
            self.rebuild_index()
            return self.graph().show(record.id)

    def candidates(self, *, entity_type: Optional[str] = None, unresolved_only: bool = False) -> Dict[str, Any]:
        """Read-only. Never mutates canonical data or the generated index.

        A document whose YAML frontmatter fails to parse is skipped by the
        underlying corpus scan (``EntityDocumentStore.iter_documents``), not
        repaired, and reported here as ``malformed_documents_skipped``.
        """
        rows = collect_candidates(
            self.documents,
            self.resolver(),
            entity_type=entity_type,
            unresolved_only=unresolved_only,
        )
        summary = summarize(rows)
        malformed = [item.to_dict() for item in self.documents.malformed_documents]
        summary["malformed_documents_skipped"] = len(malformed)
        return {"candidates": rows, "summary": summary, "malformed_documents": malformed}

    def rebuild_index(self) -> Any:
        from core.private_index import PrivateKnowledgeIndex

        return PrivateKnowledgeIndex(root_path=self.root_path, private_home=self.paths.home).build()
