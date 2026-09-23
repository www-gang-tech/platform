"""Derived entity profiles: answering "who is X?" without an authored record.

A canonical entity with no description used to have nothing to say about
itself, even when the corpus plainly knew who it was. These tests cover the
reconstruction that fills that gap, and — more importantly — the lines it must
not cross: it never becomes canonical Markdown, it never invents a role out of
attendance, it cites everything it says, and it steps aside the moment a human
authors a description.

Everything runs against a temporary GANG_HOME with no AI provider configured,
and the provider is wired to explode if anything reaches for it.
"""

import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from click.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

import cli as gang_cli
from core.ask import ConversationOptions, ConversationService
from core.ask import deterministic as deterministic_module
from core.ask import intent as intent_module
from core.entities import EntityService
from core.entities.profiles import (
    PROFILE_BUILDER_VERSION,
    EntityProfileService,
    ProfileStore,
)
from core.private_index import FOUNDATIONAL_TYPE, PrivateKnowledgeIndex

from test_conversation import StubSynthesizer, tree_fingerprint, write_markdown


BOARD_ID = "01a0be00-0000-7000-a000-00000000b001"
MINUTES_ID = "01a0be00-0000-7000-a000-00000000b002"
SUPPLY_ID = "01a0be00-0000-7000-a000-00000000b003"
ATTENDEE_ID = "01a0be00-0000-7000-a000-00000000b004"


class ProfileTestCase(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        credentials = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False)
        credentials.start()
        self.addCleanup(credentials.stop)
        network = mock.patch(
            "urllib.request.urlopen",
            side_effect=AssertionError(
                "Unexpected provider network call; the derived profile path is deterministic."
            ),
        )
        network.start()
        self.addCleanup(network.stop)

        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name) / "repo"
        self.home = Path(self._temp.name) / "gang-home"
        (self.root / "brain/vault/public/posts").mkdir(parents=True)

        # A corpus that identifies one person outright, and another only by
        # having been in the room.
        write_markdown(
            self.home / "vault/documents/board-note.md",
            {
                "id": BOARD_ID,
                "type": "knowledge",
                "source_type": "drive-file",
                "title": "Corporate binder notes",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "drive-file_binder",
                "created": "2026-03-02",
                "updated": "2026-03-02",
            },
            "Frank Godchaux is a co-founder of GANG and signs the corporate binder.\n"
            "Reach him at frank@gang.example for anything on the binder.\n",
        )
        write_markdown(
            self.home / "vault/meetings/operating-minutes.md",
            {
                "id": MINUTES_ID,
                "type": "meeting",
                "source_type": "meeting",
                "title": "Weekly operating minutes",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "meeting_operating",
                "created": "2026-06-11",
                "updated": "2026-06-11",
            },
            "Attendees: Frank Godchaux, Dana Reyes\n\n"
            "The mounting review moved to Friday.\n",
        )
        write_markdown(
            self.home / "vault/emails/supply-thread.md",
            {
                "id": SUPPLY_ID,
                "type": "knowledge",
                "source_type": "gmail-thread",
                "title": "Qi2 enclosure tooling",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "gmail-thread_supply",
                "created": "2026-09-18",
                "updated": "2026-09-18",
            },
            "Frank Godchaux confirmed the enclosure tooling schedule.\n",
        )
        # Dana exists in exactly one place: an attendee list.
        write_markdown(
            self.home / "vault/meetings/kickoff-minutes.md",
            {
                "id": ATTENDEE_ID,
                "type": "meeting",
                "source_type": "meeting",
                "title": "Qi2 kickoff",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "meeting_kickoff",
                "created": "2026-05-04",
                "updated": "2026-05-04",
            },
            "Attendees: Dana Reyes, Frank Godchaux\n\n"
            "Tooling lead times were reviewed.\n",
        )

    # ------------------------------------------------------------- helpers

    def entities(self):
        return EntityService(root_path=self.root, private_home=self.home)

    def profiles(self):
        return EntityProfileService(root_path=self.root, private_home=self.home)

    def build_index(self):
        return PrivateKnowledgeIndex(root_path=self.root, private_home=self.home).build()

    def seed(self):
        """Frank, Dana, and the company — none of them described."""
        service = self.entities()
        company = service.create("company", "GANG", domains=["gang.example"])
        frank = service.create(
            "person", "Frank Godchaux", aliases=["Frank"], emails=["frank@gang.example"]
        )
        dana = service.create("person", "Dana Reyes", aliases=["Dana"])
        for document_id in (BOARD_ID, MINUTES_ID, SUPPLY_ID, ATTENDEE_ID):
            service.add_mention(document_id, frank.id, excerpt="Frank Godchaux")
        for document_id in (MINUTES_ID, ATTENDEE_ID):
            service.add_mention(document_id, dana.id, excerpt="Dana Reyes")
        self.build_index()
        return {"company": company, "frank": frank, "dana": dana}

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


# ===================================================== building the profile


class ProfileBuilderTests(ProfileTestCase):
    def test_an_undescribed_person_still_gets_a_profile(self):
        seeded = self.seed()

        profile = self.profiles().profile(seeded["frank"].id)

        self.assertIsNotNone(profile)
        self.assertEqual(profile.entity_id, seeded["frank"].id)
        self.assertEqual(profile.name, "Frank Godchaux")
        self.assertTrue(profile.statements)

    def test_a_direct_identifying_sentence_is_quoted_not_paraphrased(self):
        seeded = self.seed()

        profile = self.profiles().profile(seeded["frank"].id)
        quoted = [item for item in profile.statements if item.kind == "statement"]

        self.assertTrue(quoted)
        self.assertIn("co-founder of GANG", quoted[0].quote)
        self.assertIn("The record states", quoted[0].text)
        self.assertEqual(quoted[0].document_ids, [BOARD_ID])

    def test_every_statement_carries_supporting_documents(self):
        seeded = self.seed()

        profile = self.profiles().profile(seeded["frank"].id)

        for statement in profile.statements:
            with self.subTest(statement=statement.text):
                self.assertTrue(statement.document_ids)

    def test_a_verified_identifier_is_reported_with_its_domain_owner(self):
        seeded = self.seed()

        profile = self.profiles().profile(seeded["frank"].id)
        identifiers = [item for item in profile.statements if item.kind == "identifier"]

        self.assertTrue(identifiers)
        self.assertIn("frank@gang.example", identifiers[0].text)
        self.assertIn("GANG", identifiers[0].text)
        self.assertNotIn("works", identifiers[0].text.casefold())
        self.assertNotIn("employee", identifiers[0].text.casefold())

    def test_an_unattested_identifier_produces_no_statement(self):
        """A canonical identifier nobody's corpus mentions cannot be cited."""
        seeded = self.seed()
        service = self.entities()
        service.add_identifier(seeded["dana"].id, email="dana@elsewhere.example")
        self.build_index()

        profile = self.profiles().profile(seeded["dana"].id)

        self.assertEqual([item for item in profile.statements if item.kind == "identifier"], [])

    def test_a_recorded_relationship_becomes_a_cited_statement(self):
        seeded = self.seed()
        service = self.entities()
        service.assert_relationship(
            document_id=BOARD_ID,
            subject_entity_id=seeded["frank"].id,
            predicate="affiliated_with",
            object_entity_id=seeded["company"].id,
            excerpt="Frank Godchaux is a co-founder of GANG",
        )
        self.build_index()

        profile = self.profiles().profile(seeded["frank"].id)
        relationships = [item for item in profile.statements if item.kind == "relationship"]

        self.assertTrue(relationships)
        self.assertEqual(
            relationships[0].text, "Recorded relationship: Frank Godchaux is affiliated with GANG."
        )
        self.assertEqual(relationships[0].document_ids, [BOARD_ID])

    def test_involvement_reports_presence_with_a_date_span(self):
        seeded = self.seed()

        profile = self.profiles().profile(seeded["frank"].id)
        involvement = [item for item in profile.statements if item.kind == "involvement"]

        self.assertTrue(involvement)
        self.assertIn("Appears in 4 documents", involvement[0].text)
        self.assertIn("2026-03-02", involvement[0].text)
        self.assertIn("2026-09-18", involvement[0].text)

    def test_the_company_gets_a_definitional_sentence_when_one_exists(self):
        seeded = self.seed()
        service = self.entities()
        write_markdown(
            self.home / "vault/documents/about-note.md",
            {
                "id": "01a0be00-0000-7000-a000-00000000b010",
                "type": "knowledge",
                "source_type": "drive-file",
                "title": "Company overview",
                "visibility": "private",
                "status": "active",
                "created": "2026-04-01",
                "updated": "2026-04-01",
            },
            "GANG is a design and manufacturing company building intentional objects.\n",
        )
        service.add_mention(
            "01a0be00-0000-7000-a000-00000000b010", seeded["company"].id, excerpt="GANG is a"
        )
        self.build_index()

        profile = self.profiles().profile(seeded["company"].id)
        quoted = [item for item in profile.statements if item.kind == "statement"]

        self.assertTrue(quoted)
        self.assertIn("design and manufacturing company", quoted[0].quote)

    def test_an_entity_with_no_evidence_at_all_gets_no_profile(self):
        self.seed()
        stranger = self.entities().create("person", "Unmentioned Person")
        self.build_index()

        self.assertIsNone(self.profiles().profile(stranger.id))

    def test_an_authored_description_suppresses_derivation_entirely(self):
        seeded = self.seed()
        self.entities().describe(
            seeded["frank"].id, description="Frank Godchaux co-founded GANG in 2019."
        )
        self.build_index()

        self.assertIsNone(self.profiles().profile(seeded["frank"].id))


# ======================================== participation is not a role (§)


class NoInventedRoleTests(ProfileTestCase):
    def test_an_attendee_list_person_gets_a_profile_without_a_role(self):
        seeded = self.seed()

        profile = self.profiles().profile(seeded["dana"].id)

        self.assertIsNotNone(profile)
        self.assertFalse(profile.role_evidence)
        self.assertEqual([item for item in profile.statements if item.kind == "statement"], [])
        self.assertEqual([item for item in profile.statements if item.kind == "relationship"], [])

    def test_the_profile_says_out_loud_that_no_role_is_recorded(self):
        seeded = self.seed()

        profile = self.profiles().profile(seeded["dana"].id)
        text = " ".join(item.text for item in profile.statements)

        self.assertIn("No document in this evidence states a role", text)
        self.assertIn("Every appearance is inside a participant", text)

    def test_no_statement_names_a_title_employer_or_ownership(self):
        seeded = self.seed()

        profile = self.profiles().profile(seeded["dana"].id)
        stated = " ".join(
            item.text
            for item in profile.statements
            if "none is claimed here" not in item.text
        ).casefold()

        for forbidden in ("works at", "employed", "employee", "owns", "leads", "manager", "title"):
            with self.subTest(term=forbidden):
                self.assertNotIn(forbidden, stated)

    def test_prose_after_an_attendee_list_is_not_counted_as_the_list(self):
        """The index collapses newlines; the list must still end where it ends."""
        seeded = self.seed()
        write_markdown(
            self.home / "vault/meetings/review-minutes.md",
            {
                "id": "01a0be00-0000-7000-a000-00000000b022",
                "type": "meeting",
                "source_type": "meeting",
                "title": "Packaging review",
                "visibility": "private",
                "status": "active",
                "created": "2026-08-03",
                "updated": "2026-08-03",
            },
            "Attendees: Frank Godchaux, Dana Reyes.\n\n"
            "Dana Reyes walked through the packaging options.\n",
        )
        self.entities().add_mention(
            "01a0be00-0000-7000-a000-00000000b022", seeded["dana"].id, excerpt="Dana Reyes walked"
        )
        self.build_index()

        profile = self.profiles().profile(seeded["dana"].id)
        text = " ".join(item.text for item in profile.statements)

        self.assertNotIn("Every appearance is inside a participant", text)

    def test_a_status_sentence_about_a_person_is_not_read_as_an_identity(self):
        seeded = self.seed()
        write_markdown(
            self.home / "vault/emails/out-of-office.md",
            {
                "id": "01a0be00-0000-7000-a000-00000000b020",
                "type": "knowledge",
                "source_type": "gmail-thread",
                "title": "Schedule",
                "visibility": "private",
                "status": "active",
                "created": "2026-07-01",
                "updated": "2026-07-01",
            },
            "Dana Reyes is out of office until Monday.\n",
        )
        self.entities().add_mention(
            "01a0be00-0000-7000-a000-00000000b020", seeded["dana"].id, excerpt="Dana Reyes is out"
        )
        self.build_index()

        profile = self.profiles().profile(seeded["dana"].id)

        self.assertEqual([item for item in profile.statements if item.kind == "statement"], [])

    def test_a_role_sentence_about_someone_else_is_not_attributed(self):
        """The name has to precede the verb, not merely share the sentence."""
        seeded = self.seed()
        write_markdown(
            self.home / "vault/documents/misattribution.md",
            {
                "id": "01a0be00-0000-7000-a000-00000000b021",
                "type": "knowledge",
                "source_type": "drive-file",
                "title": "Certification note",
                "visibility": "private",
                "status": "active",
                "created": "2026-07-02",
                "updated": "2026-07-02",
            },
            "With Dana Reyes copied, Frank Godchaux is the certification owner.\n",
        )
        self.entities().add_mention(
            "01a0be00-0000-7000-a000-00000000b021", seeded["dana"].id, excerpt="Dana Reyes copied"
        )
        self.build_index()

        profile = self.profiles().profile(seeded["dana"].id)
        quoted = [item for item in profile.statements if item.kind == "statement"]

        self.assertEqual(quoted, [])


# =========================================== generated, never canonical


class NeverCanonicalTests(ProfileTestCase):
    def test_building_profiles_does_not_touch_canonical_markdown(self):
        self.seed()
        before = tree_fingerprint(self.home / "vault")

        self.profiles().build_all()

        self.assertEqual(tree_fingerprint(self.home / "vault"), before)

    def test_a_derived_profile_never_becomes_a_description(self):
        seeded = self.seed()

        self.profiles().build_all()

        self.assertEqual(self.entities().store.get(seeded["frank"].id).description, "")
        self.assertFalse(self.entities().store.get(seeded["frank"].id).foundational)

    def test_the_profile_payload_declares_itself_derived(self):
        seeded = self.seed()

        payload = self.profiles().profile(seeded["frank"].id).to_dict()

        self.assertTrue(payload["derived"])
        self.assertFalse(payload["canonical"])

    def test_profiles_live_outside_the_knowledge_index(self):
        seeded = self.seed()
        self.profiles().profile(seeded["frank"].id)

        paths = self.profiles().paths
        self.assertTrue(paths.entity_profiles_path.exists())
        self.assertNotEqual(paths.entity_profiles_path, paths.index_path)
        self.assertEqual(paths.entity_profiles_path.parent, paths.generated_path)

    def test_a_derived_profile_produces_no_foundational_document(self):
        self.seed()
        self.profiles().build_all()
        self.build_index()

        rows = self.service().retriever.foundational_documents(
            [record.id for record in self.entities().store.load_all()]
        )

        self.assertEqual(rows, [])

    def test_deleting_the_store_loses_nothing(self):
        seeded = self.seed()
        service = self.profiles()
        first = service.profile(seeded["frank"].id)

        service.clear()
        self.assertFalse(service.paths.entity_profiles_path.exists())

        rebuilt = self.profiles().profile(seeded["frank"].id)
        self.assertEqual(
            [item.text for item in rebuilt.statements], [item.text for item in first.statements]
        )


# ================================================ precompute and rebuild


class RebuildTests(ProfileTestCase):
    def test_build_all_precomputes_every_derivable_profile(self):
        # GANG is seeded as a canonical company that no document mentions, so
        # it is the "not enough evidence" case in the same run.
        self.seed()

        report = self.profiles().build_all()

        self.assertEqual(report["built"], 2)
        self.assertEqual(report["insufficient"], 1)
        self.assertEqual(self.profiles().profiles.count(), 2)

    def test_build_all_skips_entities_with_an_authored_description(self):
        seeded = self.seed()
        self.entities().describe(seeded["frank"].id, description="Frank Godchaux co-founded GANG.")
        self.build_index()

        report = self.profiles().build_all()

        self.assertEqual(report["authored"], 1)
        self.assertNotIn(seeded["frank"].id, self.profiles().profiles.entity_ids())

    def test_a_precomputed_profile_is_reused_while_the_evidence_is_unchanged(self):
        seeded = self.seed()
        service = self.profiles()
        service.build_all()

        with mock.patch(
            "core.entities.profiles.build_profile",
            side_effect=AssertionError("cached profile should not be rebuilt"),
        ):
            reused = self.profiles().profile(seeded["frank"].id)

        self.assertIsNotNone(reused)
        self.assertIn("co-founder of GANG", " ".join(item.quote for item in reused.statements))

    def test_new_evidence_invalidates_a_precomputed_profile(self):
        seeded = self.seed()
        self.profiles().build_all()

        write_markdown(
            self.home / "vault/documents/counsel-note.md",
            {
                "id": "01a0be00-0000-7000-a000-00000000b030",
                "type": "knowledge",
                "source_type": "drive-file",
                "title": "Counsel note",
                "visibility": "private",
                "status": "active",
                "created": "2026-09-20",
                "updated": "2026-09-20",
            },
            "Dana Reyes is the outside counsel for the Qi2 filing.\n",
        )
        self.entities().add_mention(
            "01a0be00-0000-7000-a000-00000000b030", seeded["dana"].id, excerpt="Dana Reyes is the"
        )
        self.build_index()

        profile = self.profiles().profile(seeded["dana"].id)

        self.assertTrue(profile.role_evidence)
        self.assertIn("outside counsel", " ".join(item.quote for item in profile.statements))

    def test_a_builder_version_bump_invalidates_the_cache(self):
        seeded = self.seed()
        self.profiles().build_all()
        store = ProfileStore(self.profiles().paths.entity_profiles_path)

        with mock.patch("core.entities.profiles.PROFILE_BUILDER_VERSION", PROFILE_BUILDER_VERSION + 1):
            self.assertIsNone(store.read(seeded["frank"].id))

    def test_lazy_and_precomputed_profiles_are_identical(self):
        seeded = self.seed()
        lazy = self.profiles().profile(seeded["frank"].id, persist=False)

        self.profiles().build_all(force=True)
        precomputed = self.profiles().profile(seeded["frank"].id)

        self.assertEqual(
            [item.to_dict() for item in lazy.statements],
            [item.to_dict() for item in precomputed.statements],
        )


# ================================================ "who is X?" (acceptance)


class WhoIsQuestionTests(ProfileTestCase):
    def test_who_is_frank_answers_from_evidence_without_a_description(self):
        self.seed()

        result = self.ask("Who is Frank?")

        self.assertEqual(result["intent"]["policy"], intent_module.DEFINITION)
        self.assertFalse(result["insufficient_evidence"])
        self.assertIn("co-founder of GANG", result["answer"])
        self.assertTrue(result["sources"])

    def test_the_full_name_resolves_to_the_same_answer(self):
        self.seed()

        short = self.ask("Who is Frank?")
        full = self.ask("Who is Frank Godchaux?")

        self.assertEqual(short["answer"], full["answer"])
        self.assertEqual(
            [source["document_id"] for source in short["sources"]],
            [source["document_id"] for source in full["sources"]],
        )

    def test_the_answer_is_marked_derived_rather_than_canonical(self):
        self.seed()

        result = self.ask("Who is Frank?")

        self.assertEqual(
            result["synthesis"]["reason"], deterministic_module.DERIVED_PROFILE_REASON
        )
        self.assertIn("Derived profile", result["answer"])
        self.assertIn("not canonical knowledge", result["answer"])
        self.assertIn("No role, title, employment, or ownership", result["uncertainty"])

    def test_every_claim_in_a_derived_answer_carries_a_citation(self):
        self.seed()

        result = self.ask("Who is Frank?")

        self.assertTrue(result["claims"])
        for claim in result["claims"]:
            with self.subTest(claim=claim["text"]):
                self.assertTrue(claim["citations"])

    def test_an_authored_description_takes_precedence_once_written(self):
        seeded = self.seed()
        derived = self.ask("Who is Frank?")
        self.assertIn("Derived profile", derived["answer"])

        self.entities().describe(
            seeded["frank"].id,
            description="Frank Godchaux is a co-founder of GANG and chairs its board.",
        )
        self.build_index()
        authored = self.ask("Who is Frank?")

        self.assertEqual(authored["synthesis"]["reason"], "deterministic-capability")
        self.assertNotIn("Derived profile", authored["answer"])
        self.assertIn("chairs its board", authored["answer"])
        self.assertEqual(authored["sources"][0]["document_id"], seeded["frank"].id)
        self.assertEqual(authored["sources"][0]["type"], FOUNDATIONAL_TYPE)

    def test_an_attendee_only_person_is_answered_without_a_role(self):
        self.seed()

        result = self.ask("Who is Dana Reyes?")

        self.assertIn("Derived profile", result["answer"])
        self.assertIn("No document in this evidence states a role", result["answer"])
        for forbidden in ("works at", "employee", "owns", "manager"):
            with self.subTest(term=forbidden):
                self.assertNotIn(forbidden, result["answer"].casefold())

    def test_an_entity_with_no_evidence_falls_back_to_the_no_evidence_answer(self):
        self.seed()
        self.entities().create("person", "Unmentioned Person")
        self.build_index()

        result = self.ask("Who is Unmentioned Person?")

        self.assertTrue(result["insufficient_evidence"])
        self.assertNotIn("Derived profile", result["answer"])

    def test_the_derived_answer_costs_no_model_call(self):
        self.seed()
        stub = StubSynthesizer()

        result = self.ask("Who is Frank?", synthesizer=stub)

        self.assertEqual(stub.contexts, [])
        self.assertEqual(result["provider_calls"], [])
        self.assertEqual(result["synthesis"]["mode"], "deterministic")

    def test_the_answer_works_with_no_profile_precomputed(self):
        self.seed()
        self.assertEqual(self.profiles().profiles.count(), 0)

        result = self.ask("Who is Frank?")

        self.assertIn("co-founder of GANG", result["answer"])
        self.assertGreaterEqual(self.profiles().profiles.count(), 1)

    def test_a_precomputed_profile_gives_the_same_answer(self):
        self.seed()
        lazy = self.ask("Who is Frank?")

        self.profiles().clear()
        self.profiles().build_all()
        precomputed = self.ask("Who is Frank?")

        self.assertEqual(lazy["answer"], precomputed["answer"])

    def test_the_research_trace_names_the_derived_profile(self):
        self.seed()
        service = self.service()

        result = service.converse(
            "Who is Frank?",
            session=service.start(),
            options=ConversationOptions(use_cache=False, persist=False, show_research=True),
        )

        notes = " ".join(entry.get("note", "") for entry in result["research"]["trace"])
        self.assertIn("Derived entity profile", notes)
        self.assertIn("not canonical", notes)


# ================================================================== the CLI


class ProfilesCliTests(ProfileTestCase):
    def test_build_reports_what_it_derived(self):
        self.seed()

        result = self.run_cli(["entity", "profiles", "build"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("derived profile", result.output)
        self.assertIn("Frank Godchaux", result.output)
        self.assertIn("never canonical", result.output)

    def test_build_marks_a_person_with_no_stated_role(self):
        self.seed()

        result = self.run_cli(["entity", "profiles", "build"])

        self.assertIn("no role stated in evidence", result.output)

    def test_build_can_be_limited_to_one_type(self):
        self.seed()

        result = self.run_cli(["entity", "profiles", "build", "--type", "person"])

        self.assertIn("Frank Godchaux", result.output)
        self.assertIn("Built 2 derived profile(s)", result.output)

    def test_show_renders_a_profile_for_one_entity(self):
        seeded = self.seed()

        result = self.run_cli(["entity", "profiles", "show", seeded["frank"].id])

        self.assertIn("derived, not canonical", result.output)
        self.assertIn("co-founder of GANG", result.output)

    def test_show_defers_to_an_authored_description(self):
        seeded = self.seed()
        self.entities().describe(seeded["frank"].id, description="Frank Godchaux co-founded GANG.")
        self.build_index()

        result = self.run_cli(["entity", "profiles", "show", seeded["frank"].id])

        self.assertIn("human-authored description", result.output)
        self.assertIn("co-founded GANG", result.output)

    def test_clear_removes_every_derived_profile(self):
        self.seed()
        self.run_cli(["entity", "profiles", "build"])

        result = self.run_cli(["entity", "profiles", "clear"])

        self.assertIn("Nothing canonical was touched", result.output)
        self.assertEqual(self.profiles().profiles.count(), 0)


if __name__ == "__main__":
    unittest.main()
