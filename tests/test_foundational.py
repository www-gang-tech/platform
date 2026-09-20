"""Foundational canonical knowledge, and entity reclassification.

A company's basic identity must not have to be inferred from email traffic.
These tests cover the authored identity record, its route into retrieval, the
preference definitional questions give it, and the migration that changes an
entity's type without losing its identity or its references.

Everything runs against a temporary GANG_HOME with no AI provider configured.
"""

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import yaml
from click.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

import cli as gang_cli
from core.ask import ConversationOptions, ConversationService, infer_intent
from core.ask import authority as authority_module
from core.ask import intent as intent_module
from core.entities import EntityService
from core.entities.model import (
    MAX_DESCRIPTION,
    PROTECTED_IDENTITY_FIELDS,
    AliasCollisionError,
    DuplicateEntityError,
    EntityValidationError,
)
from core.private_index import FOUNDATIONAL_TYPE, PrivateKnowledgeIndex, foundational_document

from test_conversation import StubSynthesizer, write_markdown


GANG_DESCRIPTION = (
    "GANG is a design and manufacturing company building intentional objects, "
    "beginning with the Qi2 wireless charger. It operates a direct commercial "
    "system rather than selling through retail distribution."
)

EMAIL_ID = "01a0bdd1-7f14-7b41-a4e3-f4dbd6a38001"
AGENDA_ID = "01a0bdd1-7f14-7b41-a4e3-f4dbd6a38002"


class FoundationalTestCase(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        credentials = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False)
        credentials.start()
        self.addCleanup(credentials.stop)

        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name) / "repo"
        self.home = Path(self._temp.name) / "gang-home"
        (self.root / "brain/vault/public/posts").mkdir(parents=True)

        # Incidental traffic: exactly the kind of evidence that used to have to
        # stand in for an identity.
        write_markdown(
            self.home / "vault/emails/mounting-review.md",
            {
                "id": EMAIL_ID,
                "type": "knowledge",
                "source_type": "gmail-thread",
                "title": "GANG mounting review Friday",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "gmail-thread_mounting",
                "created": "2026-09-19",
                "updated": "2026-09-19",
            },
            "GANG Drive acceptance renamed. The GANG mounting review is scheduled for Friday.\n",
        )
        write_markdown(
            self.home / "vault/documents/operating-agenda.md",
            {
                "id": AGENDA_ID,
                "type": "schedule",
                "source_type": "drive-file",
                "title": "GANG Weekly Operating Schedule",
                "visibility": "private",
                "status": "active",
                "source_id": "drive-file_agenda",
                "created": "2026-09-18",
                "updated": "2026-09-18",
            },
            "GANG systems - Shopify synchronization. GANG Holdings corporate binder.\n",
        )

    # ------------------------------------------------------------- helpers

    def entities(self):
        return EntityService(root_path=self.root, private_home=self.home)

    def build_index(self):
        return PrivateKnowledgeIndex(root_path=self.root, private_home=self.home).build()

    def seed_company(self, *, described=True, entity_type="company"):
        service = self.entities()
        record = service.create(entity_type, "GANG", aliases=["GANG Systems"])
        if described:
            service.describe(record.id, description=GANG_DESCRIPTION)
        service.add_mention(EMAIL_ID, record.id, excerpt="The GANG mounting review")
        service.add_mention(AGENDA_ID, record.id, excerpt="GANG systems - Shopify")
        return record

    def service(self, **kwargs):
        kwargs.setdefault("synthesizer", StubSynthesizer())
        return ConversationService(root_path=self.root, private_home=self.home, **kwargs)

    def ask(self, question, **kwargs):
        service = self.service(**kwargs)
        return service.converse(
            question,
            session=service.start(),
            options=ConversationOptions(use_cache=False, persist=False),
        )

    def run_cli(self, args):
        return CliRunner().invoke(
            gang_cli.cli,
            args,
            env={"GANG_HOME": str(self.home), "ANTHROPIC_API_KEY": ""},
            catch_exceptions=False,
        )


# ================================================== the authored record


class AuthoredIdentityTests(FoundationalTestCase):
    def test_a_description_round_trips_through_the_record(self):
        record = self.seed_company()
        reloaded = self.entities().store.get(record.id)

        self.assertEqual(reloaded.description, GANG_DESCRIPTION)
        self.assertTrue(reloaded.foundational)
        self.assertIn(GANG_DESCRIPTION, reloaded.identity_text())

    def test_the_description_is_written_into_the_canonical_markdown(self):
        record = self.seed_company()
        text = record.path.read_text(encoding="utf-8")
        frontmatter = yaml.safe_load(text.split("---", 2)[1])

        self.assertEqual(frontmatter["description"], GANG_DESCRIPTION)
        self.assertEqual(frontmatter["id"], record.id)

    def test_an_undescribed_record_is_a_valid_identity_but_not_foundational(self):
        record = self.seed_company(described=False)
        reloaded = self.entities().store.get(record.id)

        self.assertEqual(reloaded.description, "")
        self.assertFalse(reloaded.foundational)
        self.assertEqual(reloaded.identity_text(), "")

    def test_a_bare_name_heading_does_not_count_as_authored_content(self):
        record = self.seed_company(described=False)
        service = self.entities()
        service.describe(record.id, body=f"# {record.name}")

        self.assertFalse(service.store.get(record.id).foundational)

    def test_a_longer_authored_account_lives_in_the_body(self):
        record = self.seed_company()
        service = self.entities()
        service.describe(record.id, body="GANG was founded to make one object at a time.")

        reloaded = service.store.get(record.id)
        self.assertIn(GANG_DESCRIPTION, reloaded.identity_text())
        self.assertIn("one object at a time", reloaded.identity_text())

    def test_an_overlong_description_is_refused(self):
        record = self.seed_company(described=False)
        with self.assertRaises(EntityValidationError):
            self.entities().describe(record.id, description="x" * (MAX_DESCRIPTION + 1))

    def test_a_description_can_be_cleared(self):
        record = self.seed_company()
        service = self.entities()
        service.describe(record.id, description="")

        self.assertFalse(service.store.get(record.id).foundational)

    def test_authoring_is_audited_as_human_authored(self):
        record = self.seed_company()
        audit = (self.home / "entities/audit.jsonl").read_text(encoding="utf-8")

        self.assertIn("entity_described", audit)
        self.assertIn('"authored_by": "human"', audit)
        self.assertIn(record.id, audit)


class NeverGeneratedTests(FoundationalTestCase):
    """Foundational knowledge is authored. There must be no AI path into it."""

    def test_the_authoring_api_takes_no_provider_or_model(self):
        import inspect

        for target in (EntityService.describe, type(self.entities().store).describe):
            with self.subTest(target=target.__qualname__):
                parameters = set(inspect.signature(target).parameters)
                self.assertNotIn("use_ai", parameters)
                self.assertNotIn("model", parameters)
                self.assertNotIn("provider", parameters)

    def test_entity_creation_cannot_set_a_description(self):
        with self.assertRaises(TypeError):
            self.entities().create("company", "Other", description="generated")

    def test_no_ai_provider_module_can_reach_the_description_field(self):
        proposals = (ROOT / "cli/gang/core/entities/proposals.py").read_text(encoding="utf-8")
        enrichment = (ROOT / "cli/gang/core/enrichment.py").read_text(encoding="utf-8")

        for name in PROTECTED_IDENTITY_FIELDS:
            with self.subTest(field=name):
                self.assertNotIn(f'"{name}"', proposals)
                self.assertNotIn(f"'{name}'", proposals)
                self.assertNotIn(f'"{name}"', enrichment)

    def test_the_cli_offers_no_generation_flag(self):
        result = self.run_cli(["entity", "describe", "--help"])
        self.assertNotIn("--use-ai", result.output)
        self.assertNotIn("--model", result.output)
        collapsed = " ".join(result.output.split())
        self.assertIn("never will be", collapsed)

    def test_an_applied_proposal_does_not_touch_the_description(self):
        record = self.seed_company()
        service = self.entities()
        proposal = service.propose(EMAIL_ID)
        if proposal.get("proposal_id"):
            service.apply_proposal(proposal["proposal_id"])

        self.assertEqual(service.store.get(record.id).description, GANG_DESCRIPTION)


# ============================================== reaching retrieval


class FoundationalIndexingTests(FoundationalTestCase):
    def test_a_described_record_becomes_a_citable_document(self):
        record = self.seed_company()
        self.build_index()

        rows = self.service().retriever.documents([record.id])

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["type"], FOUNDATIONAL_TYPE)
        self.assertEqual(rows[0]["source_type"], "entity-company")
        self.assertIn("design and manufacturing company", rows[0]["body"])

    def test_the_citation_points_at_the_canonical_record_id(self):
        record = self.seed_company()
        self.build_index()

        rows = self.service().retriever.foundational_documents([record.id])

        self.assertEqual(rows[0]["document_id"], record.id)

    def test_an_undescribed_record_produces_no_document(self):
        record = self.seed_company(described=False)
        self.build_index()

        self.assertEqual(self.service().retriever.documents([record.id]), [])
        self.assertIsNone(foundational_document(self.entities().store.get(record.id)))

    def test_authored_identity_is_trusted_unlike_ingested_mail(self):
        record = self.seed_company()
        self.build_index()

        identity = self.service().retriever.documents([record.id])[0]
        email = self.service().retriever.documents([EMAIL_ID])[0]

        self.assertEqual(identity["content_trust"], "trusted")
        self.assertEqual(email["content_trust"], "untrusted")

    def test_aliases_are_searchable_through_the_record(self):
        record = self.seed_company()
        self.build_index()

        body = self.service().retriever.documents([record.id])[0]["body"]
        self.assertIn("GANG Systems", body)

    def test_the_record_still_exists_as_an_identity_row(self):
        record = self.seed_company()
        self.build_index()

        entity = self.service().retriever.entity(record.id)
        self.assertEqual(entity["name"], "GANG")
        self.assertEqual(entity["type"], "company")

    def test_an_entity_record_never_reaches_the_public_build(self):
        self.seed_company()
        result = self.build_index()
        self.assertGreater(result.documents, 0)

        rows = self.service().retriever.retrieve(
            __import__("core.ask", fromlist=["validate_plan"]).validate_plan(
                {"version": "1", "query": "gang", "text_queries": ["gang"], "visibility": "public"}
            )
        )
        self.assertEqual([row for row in rows if row["type"] == FOUNDATIONAL_TYPE], [])


# ====================================== definitional questions (acceptance)


class DefinitionalQuestionTests(FoundationalTestCase):
    def test_what_is_gang_infers_a_definitional_policy(self):
        self.assertEqual(infer_intent("what is gang?").policy, intent_module.DEFINITION)
        self.assertTrue(infer_intent("what is gang?").wants_identity)

    def test_a_value_lookup_is_not_mistaken_for_a_definition(self):
        for question in (
            "What is our current BOM?",
            "What is the target ship date?",
            "What's happening with certification?",
            "What are we missing?",
        ):
            with self.subTest(question=question):
                self.assertNotEqual(
                    infer_intent(question).policy, intent_module.DEFINITION
                )

    def test_what_is_gang_answers_from_the_canonical_record(self):
        record = self.seed_company()
        self.build_index()

        result = self.ask("what is gang?")

        self.assertEqual(result["intent"]["policy"], intent_module.DEFINITION)
        first = result["sources"][0]
        self.assertEqual(first["citation_id"], 1)
        self.assertEqual(first["document_id"], record.id)
        self.assertEqual(first["type"], FOUNDATIONAL_TYPE)

    def test_the_canonical_record_outranks_incidental_traffic(self):
        self.seed_company()
        self.build_index()

        result = self.ask("what is gang?")

        roles = [source["authority"]["role"] for source in result["sources"]]
        self.assertEqual(roles[0], authority_module.FOUNDATIONAL)
        # The email is still retrieved and still cited — just not leading.
        self.assertIn(authority_module.EMAIL, roles)
        preferred = [item for item in result["sources"] if item["authority"]["preferred"]]
        self.assertEqual(len(preferred), 1)
        self.assertEqual(preferred[0]["authority"]["role"], authority_module.FOUNDATIONAL)

    def test_the_preference_reason_reads_as_a_definition_not_a_schedule(self):
        self.seed_company()
        self.build_index()

        result = self.ask("what is gang?")
        reason = [
            item["authority"]["reason"]
            for item in result["sources"]
            if item["authority"]["preferred"]
        ][0]

        self.assertIn("the definition", reason)
        self.assertNotIn("the current state", reason)

    def test_the_identity_text_is_what_synthesis_sees_first(self):
        self.seed_company()
        self.build_index()
        stub = StubSynthesizer()

        self.ask("what is gang?", synthesizer=stub)

        first = stub.contexts[-1].bundle.items[0]
        self.assertIn("design and manufacturing company", first.excerpts[0])

    def test_without_a_record_the_answer_does_not_invent_an_identity(self):
        self.seed_company(described=False)
        self.build_index()

        result = self.ask("what is gang?")

        cited_types = {source["type"] for source in result["sources"]}
        self.assertNotIn(FOUNDATIONAL_TYPE, cited_types)
        # Whatever it says, it is not built from a canonical identity that
        # does not exist.
        self.assertTrue(
            result["insufficient_evidence"] or cited_types <= {"knowledge", "schedule"}
        )

    def test_the_research_trace_names_the_identity_step(self):
        self.seed_company()
        self.build_index()
        service = self.service()

        result = service.converse(
            "what is gang?",
            session=service.start(),
            options=ConversationOptions(use_cache=False, persist=False, show_research=True),
        )

        reasons = " ".join(entry.get("reason", "") for entry in result["research"]["trace"])
        self.assertIn("authored canonical identity", reasons)

    def test_a_person_can_be_defined_the_same_way(self):
        service = self.entities()
        frank = service.create("person", "Frank Godchaux", aliases=["Frank"])
        service.describe(frank.id, description="Frank Godchaux is a co-founder of GANG.")
        self.build_index()

        result = self.ask("Who is Frank Godchaux?")

        self.assertEqual(result["sources"][0]["document_id"], frank.id)


# ================================================ reclassification (item 3)


class ReclassificationTests(FoundationalTestCase):
    def test_reclassify_preserves_the_entity_id(self):
        record = self.seed_company(entity_type="project")
        service = self.entities()

        audit = service.reclassify(record.id, "company")

        self.assertTrue(audit["changed"])
        self.assertEqual(audit["entity_id"], record.id)
        self.assertEqual(service.store.get(record.id).id, record.id)
        self.assertEqual(service.store.get(record.id).type, "company")

    def test_reclassify_moves_the_record_into_the_new_directory(self):
        record = self.seed_company(entity_type="project")
        original = record.path
        self.assertEqual(original.parent.name, "projects")

        audit = self.entities().reclassify(record.id, "company")

        self.assertEqual(audit["path"].parent.name, "companies")
        self.assertTrue(audit["path"].exists())
        self.assertFalse(original.exists(), "the old file must not linger as a duplicate")

    def test_reclassify_rewrites_the_denormalized_type_on_every_mention(self):
        record = self.seed_company(entity_type="project")
        service = self.entities()

        audit = service.reclassify(record.id, "company")

        self.assertEqual(len(audit["documents_updated"]), 2)
        for document_id in (EMAIL_ID, AGENDA_ID):
            with self.subTest(document=document_id):
                document = service.documents.load(document_id)
                types = {
                    item["entity_type"]
                    for item in document.mentions
                    if item["entity_id"] == record.id
                }
                self.assertEqual(types, {"company"})

    def test_reclassify_preserves_mentions_relationships_and_provenance(self):
        record = self.seed_company(entity_type="project")
        service = self.entities()
        shopify = service.create("product", "Shopify synchronization")
        service.add_mention(AGENDA_ID, shopify.id, excerpt="Shopify synchronization")
        service.assert_relationship(
            document_id=AGENDA_ID,
            subject_entity_id=record.id,
            predicate="involved_in",
            object_entity_id=shopify.id,
            excerpt="GANG systems - Shopify synchronization.",
        )
        before = service.show(record.id)

        service.reclassify(record.id, "company")
        after = service.show(record.id)

        self.assertEqual(after["provenance"]["mentions"], before["provenance"]["mentions"])
        self.assertEqual(
            after["provenance"]["relationships"], before["provenance"]["relationships"]
        )
        self.assertEqual(
            sorted(item["document_id"] for item in after["documents"]),
            sorted(item["document_id"] for item in before["documents"]),
        )

    def test_reclassify_preserves_the_authored_description(self):
        record = self.seed_company(entity_type="project")
        self.entities().reclassify(record.id, "company")

        self.assertEqual(self.entities().store.get(record.id).description, GANG_DESCRIPTION)

    def test_reclassify_keeps_the_record_retrievable_and_citable(self):
        record = self.seed_company(entity_type="project")
        self.entities().reclassify(record.id, "company")
        self.build_index()

        rows = self.service().retriever.foundational_documents([record.id])

        self.assertEqual(rows[0]["document_id"], record.id)
        self.assertEqual(rows[0]["source_type"], "entity-company")

    def test_reclassify_to_the_same_type_is_a_no_op(self):
        record = self.seed_company(entity_type="company")
        audit = self.entities().reclassify(record.id, "company")

        self.assertFalse(audit["changed"])
        self.assertEqual(audit["documents_updated"], [])

    def test_reclassify_refuses_a_name_collision_rather_than_merging(self):
        record = self.seed_company(entity_type="project")
        service = self.entities()
        service.create("company", "GANG")

        with self.assertRaises(DuplicateEntityError):
            service.reclassify(record.id, "company")
        self.assertEqual(service.store.get(record.id).type, "project")

    def test_reclassify_refuses_an_alias_collision(self):
        record = self.seed_company(entity_type="project")
        service = self.entities()
        other = service.create("company", "Other Co")
        service.add_alias(other.id, "GANG Systems")

        with self.assertRaises(AliasCollisionError):
            service.reclassify(record.id, "company")

    def test_reclassify_refuses_an_unsupported_type(self):
        record = self.seed_company(entity_type="project")
        with self.assertRaises(EntityValidationError):
            self.entities().reclassify(record.id, "organisation")

    def test_reclassify_is_audited_with_both_types_and_both_paths(self):
        record = self.seed_company(entity_type="project")
        self.entities().reclassify(record.id, "company")

        audit = (self.home / "entities/audit.jsonl").read_text(encoding="utf-8")
        self.assertIn("entity_reclassified", audit)
        self.assertIn('"from_type": "project"', audit)
        self.assertIn('"to_type": "company"', audit)

    def test_the_cli_requires_confirmation_before_reclassifying(self):
        record = self.seed_company(entity_type="project")

        result = CliRunner().invoke(
            gang_cli.cli,
            ["entity", "reclassify", record.id, "company"],
            env={"GANG_HOME": str(self.home), "ANTHROPIC_API_KEY": ""},
            input="n\n",
            catch_exceptions=False,
        )

        self.assertIn("Aborted", result.output)
        self.assertEqual(self.entities().store.get(record.id).type, "project")

    def test_the_cli_reports_what_it_changed(self):
        record = self.seed_company(entity_type="project")

        result = self.run_cli(["entity", "reclassify", record.id, "company", "--yes"])

        self.assertIn("project -> company", result.output)
        self.assertIn("ID unchanged", result.output)
        self.assertEqual(self.entities().store.get(record.id).type, "company")


class DescribeCliTests(FoundationalTestCase):
    def test_describe_writes_the_canonical_description(self):
        record = self.seed_company(described=False)

        result = self.run_cli(
            ["entity", "describe", record.id, "--description", GANG_DESCRIPTION]
        )

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("human-authored", result.output)
        self.assertIn("Foundational: yes", result.output)
        self.assertEqual(self.entities().store.get(record.id).description, GANG_DESCRIPTION)

    def test_describe_with_nothing_to_write_fails_clearly(self):
        record = self.seed_company(described=False)
        result = self.run_cli(["entity", "describe", record.id])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("Nothing to write", result.output)

    def test_describe_can_read_a_longer_account_from_a_file(self):
        record = self.seed_company(described=False)
        source = Path(self._temp.name) / "about.md"
        source.write_text("GANG builds one object at a time.\n", encoding="utf-8")

        self.run_cli(["entity", "describe", record.id, "--from-file", str(source)])

        self.assertIn("one object at a time", self.entities().store.get(record.id).identity_text())


if __name__ == "__main__":
    unittest.main()
