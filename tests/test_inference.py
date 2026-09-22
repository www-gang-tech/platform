"""Inference claims, group questions, and keeping diagnostics out of answers.

The corpus here is shaped like the real one rather than like a fixture: weekly
operating meetings with collapsed attendee lines, an outside firm whose people
sign off with their own domain, a supplier thread, and a person who turns up
constantly without anything ever saying who they are. That last case is the
one worth having — the honest answer is "present throughout, unplaced", and a
system that guesses a band for them is worse than one that says so.
"""

import contextlib
import io
import json
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
from core.ask import ConversationOptions, ConversationService, infer_intent
from core.ask import affiliation as affiliation_module
from core.ask import intent as intent_module
from core.ask import ledger as ledger_module
from core.ask.evidence import build_bundle
from core.ask.planner import PlanOverrides
from core.ask.tools import ResearchTools
from core.entities import EntityService
from core.private_index import PrivateKnowledgeIndex

from test_conversation import StubSynthesizer, write_markdown


OPS_IDS = [f"01a0bee1-7f14-7b41-a4e3-f4dbd6a390{index:02d}" for index in range(1, 5)]
QUOTE_ID = "01a0bee1-7f14-7b41-a4e3-f4dbd6a39101"
CERT_ID = "01a0bee1-7f14-7b41-a4e3-f4dbd6a39102"


class InferenceTestCase(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        credentials = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False)
        credentials.start()
        self.addCleanup(credentials.stop)
        network = mock.patch(
            "core.ai_provider._urlopen",
            side_effect=AssertionError(
                "Unexpected provider network call in inference tests; inject a fake provider."
            ),
        )
        network.start()
        self.addCleanup(network.stop)

        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name) / "repo"
        self.home = Path(self._temp.name) / "gang-home"
        (self.root / "brain/vault/public/posts").mkdir(parents=True)

        self.seed_entities()
        self.write_corpus()

    def seed_entities(self):
        service = EntityService(root_path=self.root, private_home=self.home)
        self.gang = service.create("company", "GANG", domains=["gang.tech"])
        service.describe(
            self.gang.id,
            description="GANG is a design and manufacturing company building intentional objects.",
        )
        self.eliro = service.create(
            "company", "Eliro Inc.", aliases=["Eliro"], domains=["eliroinc.com"]
        )
        self.dana = service.create(
            "person", "Dana Okonkwo", aliases=["Dana"], emails=["dana@gang.tech"]
        )
        self.steven = service.create(
            "person", "Steven Gormley", aliases=["Steven"], emails=["steven@eliroinc.com"]
        )
        # Constantly present, never explained. The interesting case.
        self.pat = service.create("person", "Pat Reyes", aliases=["Pat"])

    def write_corpus(self):
        for index, (month, day) in enumerate(
            [("08", "05"), ("08", "19"), ("09", "02"), ("09", "16")], start=1
        ):
            write_markdown(
                self.home / f"vault/meetings/ops-{index}.md",
                {
                    "id": OPS_IDS[index - 1],
                    "type": "meeting",
                    "source_type": "meeting",
                    "title": f"GANG Weekly Operating Meeting {index}",
                    "visibility": "private",
                    "status": "active",
                    "source_id": f"meeting_ops{index}",
                    "created": f"2026-{month}-{day}",
                    "updated": f"2026-{month}-{day}",
                },
                "Participants: Dana Okonkwo <dana@gang.tech>, "
                "Steven Gormley <steven@eliroinc.com>, Pat Reyes\n\n"
                "Dana Okonkwo owns the certification deliverable and will deliver the "
                "sample pack.\n"
                "Steven Gormley advised on the bylaws and the term sheet.\n"
                "Pat Reyes joined the packaging discussion.\n",
            )

        write_markdown(
            self.home / "vault/emails/tooling-quote.md",
            {
                "id": QUOTE_ID,
                "type": "knowledge",
                "source_type": "gmail-thread",
                "title": "Tooling quote",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "gmail_quote",
                "created": "2026-09-03",
                "updated": "2026-09-03",
            },
            "From: Jae Lin <jae@precisiontool.example>\n\n"
            "Please find the supplier quote for the mounting plate tooling. Our factory "
            "can hold the purchase order price until October.\n",
        )
        write_markdown(
            self.home / "vault/emails/certification.md",
            {
                "id": CERT_ID,
                "type": "knowledge",
                "source_type": "gmail-thread",
                "title": "Qi2 certification restart",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "gmail_cert",
                "created": "2026-09-10",
                "updated": "2026-09-10",
            },
            "Dana Okonkwo confirmed the Qi2 certification application was restarted on "
            "September 10. The unit cost is $130 per unit.\n",
        )

    # ------------------------------------------------------------- helpers

    def build_index(self):
        return PrivateKnowledgeIndex(root_path=self.root, private_home=self.home).build()

    def service(self, **kwargs):
        kwargs.setdefault("synthesizer", StubSynthesizer())
        return ConversationService(root_path=self.root, private_home=self.home, **kwargs)

    def ask(self, question, *, show_research=False, **kwargs):
        service = self.service(**kwargs)
        return service.converse(
            question,
            session=service.start(),
            options=ConversationOptions(
                use_cache=False, persist=False, show_research=show_research
            ),
        )

    def tools(self):
        service = self.service()
        return ResearchTools(
            service.retriever,
            registry_path=service.paths.registry_path,
            resolver=service._resolver(),
            entities=service._entity_records(),
        )

    def bundle(self, document_ids):
        service = self.service()
        planning = service._plan(
            "evidence",
            PlanOverrides(),
            __import__("core.ask", fromlist=["AskOptions"]).AskOptions(use_ai=False),
        )
        return build_bundle("evidence", service.retriever.documents(document_ids), planning.plan)

    def run_cli(self, args):
        return CliRunner().invoke(
            gang_cli.cli,
            args,
            env={"GANG_HOME": str(self.home), "ANTHROPIC_API_KEY": ""},
            catch_exceptions=False,
        )


# ============================================== the inference claim class


class InferenceClaimTests(InferenceTestCase):
    def facts_and(self, inference, **kwargs):
        """Two grounded facts, then the inference resting on them."""
        self.build_index()
        bundle = self.bundle([OPS_IDS[0], CERT_ID])
        claims = [
            {
                "id": "c1",
                "type": "fact",
                "text": "Dana Okonkwo owns the certification deliverable.",
                "citations": [1],
            },
            {
                "id": "c2",
                "type": "fact",
                "text": "Dana Okonkwo confirmed the Qi2 certification application was restarted.",
                "citations": [2],
            },
            {**{"id": "c3", "type": "inference", "derived_from": ["c1", "c2"]}, **inference},
        ]
        return ledger_module.validate_ledger(claims, bundle, **kwargs)

    def test_a_hedged_inference_from_two_facts_is_accepted(self):
        result = self.facts_and(
            {"text": "Dana appears to be part of GANG's core team."}
        )

        claim = result.claims[-1]
        self.assertEqual(claim.type, ledger_module.INFERENCE)
        self.assertEqual(claim.status, ledger_module.ACCEPTED)
        self.assertEqual(claim.derived_from, ["c1", "c2"])

    def test_an_inference_retains_the_evidence_under_its_premises(self):
        result = self.facts_and({"text": "Dana appears to lead certification work."})

        premises = {claim.id: claim for claim in result.claims}
        for reference in premises["c3"].derived_from:
            with self.subTest(premise=reference):
                self.assertTrue(premises[reference].citations)
                self.assertTrue(premises[reference].grounded)

    def test_an_unhedged_inference_is_not_stated_as_established(self):
        result = self.facts_and({"text": "Dana is part of GANG's core team."})

        claim = result.claims[-1]
        self.assertEqual(claim.type, ledger_module.UNCERTAINTY)
        self.assertEqual(claim.original_type, ledger_module.INFERENCE)
        self.assertTrue(
            any(item["check"] == "inference_framing" for item in result.warnings)
        )

    def test_an_inference_on_one_fact_is_not_an_inference(self):
        self.build_index()
        bundle = self.bundle([OPS_IDS[0]])
        result = ledger_module.validate_ledger(
            [
                {"id": "c1", "type": "fact", "text": "Dana owns the deliverable.", "citations": [1]},
                {
                    "id": "c2",
                    "type": "inference",
                    "text": "Dana appears to be central to the company.",
                    "derived_from": ["c1"],
                },
            ],
            bundle,
        )

        self.assertEqual(result.claims[-1].type, ledger_module.UNCERTAINTY)
        self.assertTrue(
            any(item["check"] == "inference_support" for item in result.warnings)
        )

    def test_employment_is_never_inferred_however_strong_the_pattern(self):
        for text in (
            "Dana appears to be a GANG employee.",
            "Dana seems to be employed by GANG.",
            "Dana appears to be the Head of Certification.",
            "Dana appears to report to Steven.",
            "Steven appears to be a co-founder of GANG.",
        ):
            with self.subTest(text=text):
                result = self.facts_and({"text": text})
                claim = result.claims[-1]
                self.assertEqual(claim.type, ledger_module.UNCERTAINTY, text)
                self.assertTrue(
                    any(item["check"] == "inference_overreach" for item in result.warnings)
                )

    def test_the_permitted_and_forbidden_example_pair_behave_as_documented(self):
        permitted = self.facts_and({"text": "Dana appears to be part of GANG's core team."})
        forbidden = self.facts_and({"text": "Dana is a GANG employee."})

        self.assertEqual(permitted.claims[-1].type, ledger_module.INFERENCE)
        self.assertEqual(forbidden.claims[-1].type, ledger_module.UNCERTAINTY)

    def test_an_inference_is_never_a_premise_for_another_claim(self):
        self.build_index()
        bundle = self.bundle([OPS_IDS[0], CERT_ID])
        result = ledger_module.validate_ledger(
            [
                {"id": "c1", "type": "fact", "text": "Dana owns the deliverable.", "citations": [1]},
                {"id": "c2", "type": "fact", "text": "Dana confirmed the restart.", "citations": [2]},
                {
                    "id": "c3",
                    "type": "inference",
                    "text": "Dana appears to lead certification.",
                    "derived_from": ["c1", "c2"],
                },
                {
                    "id": "c4",
                    "type": "synthesis",
                    "text": "Certification is therefore well owned.",
                    "derived_from": ["c3"],
                },
            ],
            bundle,
        )

        by_id = {claim.id: claim for claim in result.claims}
        self.assertFalse(by_id["c3"].grounded, "reasoning must not ground further reasoning")
        self.assertEqual(by_id["c4"].type, ledger_module.UNCERTAINTY)

    def test_inferences_are_allowed_in_every_mode(self):
        for mode in (
            intent_module.EVIDENCE,
            intent_module.ADVISORY_MODE,
            intent_module.IDEATION,
        ):
            with self.subTest(mode=mode):
                result = self.facts_and(
                    {"text": "Dana appears to be part of the core team."}, mode=mode
                )
                self.assertEqual(result.claims[-1].type, ledger_module.INFERENCE)

    def test_the_hedge_vocabulary_covers_natural_phrasings(self):
        for text in (
            "Dana appears to be part of the core team.",
            "Dana seems to be part of the core team.",
            "Based on the record, Dana is part of the core team.",
            "The evidence suggests Dana is part of the core team.",
            "Dana is likely part of the core team.",
            "Dana may be part of the core team.",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    self.facts_and({"text": text}).claims[-1].type,
                    ledger_module.INFERENCE,
                    text,
                )


class InferenceNeverHardensTests(InferenceTestCase):
    """An inference stays an inference however often it is repeated."""

    def inference_payload(self, context):
        ids = context.bundle.citation_ids()
        return {
            "answer": f"Dana appears to be central here [{ids[0]}].",
            "claims": [
                {
                    "id": "c1",
                    "type": "fact",
                    "text": "Dana Okonkwo owns the certification deliverable.",
                    "citations": [ids[0]],
                },
                {
                    "id": "c2",
                    "type": "fact",
                    "text": "Dana Okonkwo confirmed the certification restart.",
                    "citations": ids[:2],
                },
                {
                    "id": "c3",
                    "type": "inference",
                    "text": "Dana appears to be part of GANG's core team.",
                    "derived_from": ["c1", "c2"],
                },
            ],
        }

    def test_an_inference_is_stored_as_an_inference(self):
        self.build_index()
        service = self.service(synthesizer=StubSynthesizer(self.inference_payload))
        session = service.start()
        service.converse(
            "explain certification ownership",
            session=session,
            options=ConversationOptions(use_cache=False, persist=False),
        )

        stored = {item.text: item.type for item in session.conclusions}
        self.assertEqual(
            stored.get("Dana appears to be part of GANG's core team."),
            ledger_module.INFERENCE,
        )

    def test_repetition_across_turns_never_promotes_it_to_fact(self):
        self.build_index()
        stub = StubSynthesizer(self.inference_payload)
        service = self.service(synthesizer=stub)
        session = service.start()

        for _ in range(4):
            service.converse(
                "explain certification ownership",
                session=session,
                options=ConversationOptions(use_cache=False, persist=False),
            )

        types = {item.type for item in session.conclusions if "core team" in item.text}
        self.assertEqual(types, {ledger_module.INFERENCE})
        self.assertNotIn(ledger_module.FACT, types)

    def test_the_conversation_state_rule_says_inferences_stay_inferences(self):
        self.build_index()
        stub = StubSynthesizer(self.inference_payload)
        service = self.service(synthesizer=stub)
        session = service.start()
        service.converse(
            "explain certification ownership",
            session=session,
            options=ConversationOptions(use_cache=False, persist=False),
        )
        service.converse(
            "and what about packaging?",
            session=session,
            options=ConversationOptions(use_cache=False, persist=False),
        )

        state = stub.contexts[-1].to_data()["conversation_state"]
        self.assertIn("prior_conclusion_rule", state)
        self.assertIn("stays an inference", state["prior_conclusion_rule"])

    def test_canonical_knowledge_can_replace_an_inference(self):
        """An authored record outranks a reading of the evidence."""
        self.build_index()
        EntityService(root_path=self.root, private_home=self.home).describe(
            self.dana.id, description="Dana Okonkwo leads certification at GANG."
        )
        self.build_index()

        result = self.ask("Who is Dana Okonkwo?")

        first = result["sources"][0]
        self.assertEqual(first["document_id"], self.dana.id)
        self.assertEqual(first["authority"]["role"], "foundational")


# ================================================ group / people questions


class GroupQuestionTests(InferenceTestCase):
    def participants(self, question="who is on the team?"):
        self.build_index()
        result = self.ask(question, show_research=True)
        payload = result.get("structured_records", {}).get("participants", {})
        rows = {
            row["name"]: row
            for band_rows in payload.get("participants", {}).values()
            for row in band_rows
        }
        return result, payload, rows

    def test_the_documented_group_questions_all_route_to_affiliation(self):
        for question in (
            "who is on the team?",
            "who works on manufacturing?",
            "who has been involved with certification?",
            "who seems responsible for packaging?",
        ):
            with self.subTest(question=question):
                self.assertEqual(
                    infer_intent(question).policy, intent_module.AFFILIATION
                )
                self.assertTrue(infer_intent(question).wants_people)

    def test_decision_ownership_questions_are_not_swallowed(self):
        self.assertEqual(infer_intent("Who owns those issues?").policy, intent_module.DECISION)
        self.assertEqual(
            infer_intent("Who is Frank Godchaux?").policy, intent_module.DEFINITION
        )

    def test_no_roster_document_is_required(self):
        _, payload, rows = self.participants()

        self.assertTrue(rows, "participants must be assembled from signals alone")
        self.assertIn("Dana Okonkwo", rows)
        self.assertIn("Steven Gormley", rows)

    def test_a_company_email_domain_places_someone_internally(self):
        _, _, rows = self.participants()

        self.assertEqual(rows["Dana Okonkwo"]["band"], affiliation_module.CORE_INTERNAL)
        self.assertIn(
            "uses a company email address (gang.tech)", rows["Dana Okonkwo"]["reasons"]
        )

    def test_another_organisation_places_someone_externally(self):
        _, _, rows = self.participants()

        steven = rows["Steven Gormley"]
        self.assertEqual(steven["band"], affiliation_module.EXTERNAL_ADVISORY)
        self.assertEqual(steven["signals"]["affiliated_org"], "Eliro Inc.")

    def test_supply_language_places_someone_as_a_collaborator(self):
        _, _, rows = self.participants()

        self.assertEqual(rows["Jae Lin"]["band"], affiliation_module.COLLABORATOR_VENDOR)
        self.assertFalse(rows["Jae Lin"]["has_canonical_record"])

    def test_someone_present_throughout_but_unexplained_stays_unclear(self):
        """The case that matters: constant presence is not placement."""
        _, _, rows = self.participants()

        pat = rows["Pat Reyes"]
        self.assertEqual(pat["band"], affiliation_module.UNCLEAR)
        self.assertGreaterEqual(pat["signals"]["documents"], 3)
        self.assertTrue(
            any("nothing states their relationship" in reason for reason in pat["reasons"])
        )

    def test_ownership_is_attributed_to_the_subject_not_to_bystanders(self):
        """A collapsed attendee list must not credit everyone with one line."""
        _, _, rows = self.participants()

        self.assertGreater(rows["Dana Okonkwo"]["signals"]["ownership_language"], 0)
        self.assertEqual(rows["Pat Reyes"]["signals"]["ownership_language"], 0)
        self.assertEqual(rows["Steven Gormley"]["signals"]["ownership_language"], 0)

    def test_a_participant_name_never_runs_off_into_prose(self):
        _, _, rows = self.participants()

        for name in rows:
            with self.subTest(name=name):
                self.assertLessEqual(len(name.split()), affiliation_module.MAX_NAME_TOKENS)
                self.assertNotIn(".", name)

    def test_time_and_recurrence_are_recorded(self):
        _, _, rows = self.participants()

        dana = rows["Dana Okonkwo"]
        self.assertTrue(dana["signals"]["recurring"])
        self.assertGreaterEqual(dana["signals"]["distinct_months"], 2)
        self.assertEqual(dana["first_seen"], "2026-08-05")
        self.assertEqual(dana["last_seen"], "2026-09-16")

    def test_relationships_feed_the_picture(self):
        service = EntityService(root_path=self.root, private_home=self.home)
        service.add_mention(CERT_ID, self.dana.id, excerpt="Dana Okonkwo confirmed")
        service.add_mention(CERT_ID, self.gang.id, excerpt="Qi2 certification")
        service.assert_relationship(
            document_id=CERT_ID,
            subject_entity_id=self.dana.id,
            predicate="works_on",
            object_entity_id=self.gang.id,
            excerpt="Dana Okonkwo confirmed the Qi2 certification application was restarted",
        )

        _, _, rows = self.participants()

        self.assertIn("works_on", rows["Dana Okonkwo"]["signals"]["relationships"])

    def test_every_band_carries_its_reasons_and_documents(self):
        _, _, rows = self.participants()

        for name, row in rows.items():
            with self.subTest(name=name):
                self.assertTrue(row["reasons"], name)
                self.assertTrue(row["document_ids"], name)
                self.assertIn(row["band"], affiliation_module.BANDS)

    def test_the_payload_forbids_titles_and_employment(self):
        _, payload, _ = self.participants()

        rule = payload["rule"]
        self.assertIn("NOT a roster", rule)
        self.assertIn("employment", rule)
        self.assertIn("inference", rule.lower())

    def test_synthesis_is_told_how_to_handle_people(self):
        from core.ask.answer import system_prompt

        prompt = system_prompt(intent_module.EVIDENCE)
        self.assertIn("NOT an org chart", prompt)
        self.assertIn("Never state or imply employment", prompt)

    def test_a_topic_scopes_the_participants(self):
        self.build_index()
        outcome = self.tools().call("find_participants", {"topic": "tooling"})

        names = {row["name"] for row in outcome.records}
        self.assertIn("Jae Lin", names)

    def test_one_person_arriving_by_name_and_address_is_one_person(self):
        """Real mail names the same person three ways in one collapsed header."""
        write_markdown(
            self.home / "vault/emails/mixed-header.md",
            {
                "id": "01a0bee1-7f14-7b41-a4e3-f4dbd6a39201",
                "type": "knowledge",
                "source_type": "gmail-thread",
                "title": "Certification follow-up",
                "visibility": "private",
                "status": "active",
                "source_id": "gmail_mixed",
                "created": "2026-09-11",
                "updated": "2026-09-11",
            },
            "From: Dana Okonkwo <dana@gang.tech>\n"
            "To: dana@gang.tech, Steven Gormley\n\n"
            "Following up on the certification sample pack.\n",
        )
        _, _, rows = self.participants()

        self.assertIn("Dana Okonkwo", rows)
        self.assertNotIn("dana@gang.tech", rows)
        self.assertIn("gang.tech", rows["Dana Okonkwo"]["signals"]["email_domains"])

    def test_automated_senders_are_not_participants(self):
        write_markdown(
            self.home / "vault/emails/automated.md",
            {
                "id": "01a0bee1-7f14-7b41-a4e3-f4dbd6a39202",
                "type": "knowledge",
                "source_type": "gmail-thread",
                "title": "Your weekly digest",
                "visibility": "private",
                "status": "active",
                "source_id": "gmail_auto",
                "created": "2026-09-12",
                "updated": "2026-09-12",
            },
            "From: The Workspace Team <workspace-noreply@google.com>\n"
            "Cc: forward@updates.resend.com\n\n"
            "Your weekly summary is ready.\n",
        )
        _, _, rows = self.participants()

        for noise in ("workspace-noreply@google.com", "forward@updates.resend.com"):
            with self.subTest(sender=noise):
                self.assertNotIn(noise, rows)

    def test_header_labels_and_entity_residue_never_become_names(self):
        write_markdown(
            self.home / "vault/emails/residue.md",
            {
                "id": "01a0bee1-7f14-7b41-a4e3-f4dbd6a39203",
                "type": "knowledge",
                "source_type": "gmail-thread",
                "title": "Packaging note",
                "visibility": "private",
                "status": "active",
                "source_id": "gmail_residue",
                "created": "2026-09-13",
                "updated": "2026-09-13",
            },
            "From: Dana Okonkwo &lt;dana@gang.tech&gt;\n"
            "- To: Pat Reyes\n"
            "Sent: 16 Sep 2026 18:09:00\n\n"
            "Packaging note.\n",
        )
        _, _, rows = self.participants()

        for name in rows:
            with self.subTest(name=name):
                self.assertNotIn("&", name)
                self.assertFalse(name.lower().startswith(("to:", "- to", "cc:", "sent")))
                self.assertFalse(name[:1].isdigit())

    def test_participant_normalization_rejects_service_org_and_title_fragments(self):
        service = EntityService(root_path=self.root, private_home=self.home)
        service.create(
            "person",
            "Daniel Hirunrusme",
            aliases=["Daniel"],
            emails=["daniel@gang.tech"],
        )
        write_markdown(
            self.home / "vault/emails/noisy-participants.md",
            {
                "id": "01a0bee1-7f14-7b41-a4e3-f4dbd6a39205",
                "type": "knowledge",
                "source_type": "gmail-thread",
                "title": "GANG — Eliro",
                "visibility": "private",
                "status": "active",
                "source_id": "gmail_noisy_participants",
                "created": "2026-09-15",
                "updated": "2026-09-15",
            },
            "From: Daniel Hirunrusme & <daniel@gang.tech>\n"
            "To: daniel@gang.te, Anthropic <news@anthropic.example>, "
            "Automation for Tracker <automation@tracker.example>, "
            "Farmstand <farmstand@skyhighfarmgoods.example>, "
            "Riley Chen <riley.chen@example.org>, GANG — Eliro\n\n"
            "Riley Chen joined the launch discussion.\n",
        )

        _, _, rows = self.participants()

        self.assertIn("Daniel Hirunrusme", rows)
        self.assertIn("Riley Chen", rows)
        self.assertEqual(rows["Riley Chen"]["band"], affiliation_module.UNCLEAR)
        self.assertNotIn(
            "Riley Chen",
            [
                record.name
                for record in EntityService(root_path=self.root, private_home=self.home)
                .store.load_all()
            ],
        )
        for noise in (
            "Daniel Hirunrusme &",
            "daniel@gang.te",
            "Anthropic",
            "Automation for Tracker",
            "Farmstand",
            "farmstand@skyhighfarmgoods.example",
            "GANG — Eliro",
        ):
            with self.subTest(noise=noise):
                self.assertNotIn(noise, rows)

    def test_a_passing_mention_of_a_factory_does_not_make_everyone_a_vendor(self):
        """A board thread that mentions manufacturing is not a supplier thread."""
        write_markdown(
            self.home / "vault/emails/board-note.md",
            {
                "id": "01a0bee1-7f14-7b41-a4e3-f4dbd6a39204",
                "type": "knowledge",
                "source_type": "gmail-thread",
                "title": "Executive board meeting notes",
                "visibility": "private",
                "status": "active",
                "source_id": "gmail_board",
                "created": "2026-09-14",
                "updated": "2026-09-14",
            },
            "Participants: Dana Okonkwo <dana@gang.tech>\n\n"
            "We reviewed the factory timeline and the supplier quote at a high level.\n",
        )
        _, _, rows = self.participants()

        self.assertEqual(rows["Dana Okonkwo"]["band"], affiliation_module.CORE_INTERNAL)

    def test_recurring_ownership_outranks_incidental_supply_language(self):
        rows = affiliation_module.gather(
            [
                {
                    "document_id": f"doc-{index}",
                    "title": "Weekly operating meeting",
                    "type": "meeting",
                    "updated": f"2026-0{7 + index}-01",
                    "body": "Rae Adeyemi owns the launch deliverable. A supplier quote is pending.",
                    "entity_refs": [],
                    "relationships": [],
                }
                for index in range(1, 4)
            ],
            people=[self._person("Rae Adeyemi")],
        )

        self.assertEqual(rows[0].band, affiliation_module.CORE_INTERNAL)

    def _person(self, name):
        service = EntityService(root_path=self.root, private_home=self.home)
        return service.create("person", name)

    def test_without_a_described_company_internal_cannot_be_separated(self):
        EntityService(root_path=self.root, private_home=self.home).describe(
            self.gang.id, description=""
        )
        self.build_index()

        result = self.ask("who is on the team?", show_research=True)
        payload = result["structured_records"]["participants"]

        self.assertFalse(payload["home_company_known"])
        self.assertIn("cannot be separated reliably", payload["rule"])


class DeterministicNoAiInferenceTests(InferenceTestCase):
    def no_ai(self, question, *, synthesizer=None):
        service = self.service(synthesizer=synthesizer or StubSynthesizer())
        result = service.converse(
            question,
            session=service.start(),
            options=ConversationOptions(
                use_ai=False, use_cache=False, persist=False, show_research=True
            ),
        )
        return result, service

    def test_team_query_uses_participants_not_generic_team_fts(self):
        write_markdown(
            self.home / "vault/emails/marketing-team-noise.md",
            {
                "id": "01a0bee1-7f14-7b41-a4e3-f4dbd6a39210",
                "type": "knowledge",
                "source_type": "gmail-thread",
                "title": "Claude and Google Ads team update",
                "visibility": "private",
                "status": "active",
                "source_id": "gmail_marketing_noise",
                "created": "2026-09-19",
                "updated": "2026-09-19",
            },
            "From: The Claude Team <newsletter@anthropic.com>\n\n"
            "The Google Ads team recommends refreshing your campaign structure.\n",
        )
        self.build_index()

        result, _ = self.no_ai("who is on the team?")
        titles = {source["title"] for source in result["sources"]}
        trace_tools = [entry["tool"] for entry in result["research"]["trace"]]

        self.assertIn("find_participants", trace_tools)
        self.assertIn("Likely core/internal", result["answer"])
        self.assertIn("External/advisory", result["answer"])
        self.assertIn("Unclear", result["answer"])
        self.assertIn("Dana Okonkwo", result["answer"])
        self.assertNotIn("Claude and Google Ads team update", titles)
        self.assertNotIn("Claude", result["answer"])
        self.assertNotIn("Google Ads", result["answer"])

    def test_canonical_definition_works_without_ai(self):
        synthesizer = StubSynthesizer()
        self.build_index()

        result, _ = self.no_ai("what is GANG?", synthesizer=synthesizer)

        self.assertEqual(synthesizer.contexts, [])
        self.assertEqual(result["synthesis"]["reason"], "deterministic-capability")
        self.assertIn(
            "GANG is a design and manufacturing company building intentional objects.",
            result["answer"],
        )
        self.assertEqual([entry["tool"] for entry in result["research"]["trace"]], ["get_entity"])


# ============================================ diagnostics stay out of the way


class DiagnosticVisibilityTests(InferenceTestCase):
    def noisy_payload(self, context):
        ids = context.bundle.citation_ids()
        return {
            "answer": f"The unit cost is $999 per unit [{ids[0]}].",
            "claims": [
                {"id": "c1", "type": "fact", "text": "The unit cost is $999 per unit.", "citations": [ids[0]]},
                {"id": "c2", "type": "fact", "text": "An uncited assertion.", "citations": []},
            ],
            "sql": "DROP TABLE documents",
        }

    def render(self, result, **kwargs):
        stdout, stderr = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            gang_cli._print_conversation_answer(result, **kwargs)
        return stdout.getvalue(), stderr.getvalue()

    def test_a_normal_answer_prints_no_validator_output(self):
        self.build_index()
        result = self.ask(
            "What is the unit cost?", synthesizer=StubSynthesizer(self.noisy_payload)
        )
        self.assertTrue(result["grounding_warnings"])

        stdout, stderr = self.render(result)
        combined = stdout + stderr

        for noise in (
            "unverified",
            "number-not-in-evidence",
            "dropped unsupported citation",
            "ignored unsupported answer field",
            "no citation supports it",
            "validator:",
        ):
            with self.subTest(noise=noise):
                self.assertNotIn(noise, combined)

    def test_show_research_brings_all_of_it_back(self):
        self.build_index()
        result = self.ask(
            "What is the unit cost?", synthesizer=StubSynthesizer(self.noisy_payload)
        )

        _, stderr = self.render(result, show_research=True)

        self.assertIn("unverified numeric claim", stderr)
        self.assertIn("no citation supports it", stderr)
        self.assertIn("ignored unsupported answer field", stderr)

    def test_uncertainty_reads_naturally_rather_than_as_a_validator_dump(self):
        self.build_index()
        result = self.ask(
            "What is the unit cost?", synthesizer=StubSynthesizer(self.noisy_payload)
        )

        uncertainty = result["uncertainty"]
        self.assertTrue(uncertainty)
        self.assertIn("couldn't fully stand behind", uncertainty)
        # None of the validator's internal vocabulary leaks into it.
        for slug in ("number-not-in-evidence", "uncited-factual-claim", "claim_id", "check"):
            with self.subTest(slug=slug):
                self.assertNotIn(slug, uncertainty)

    def test_uncertainty_mentions_inferences_in_plain_words(self):
        self.build_index()

        def payload(context):
            ids = context.bundle.citation_ids()
            return {
                "answer": "Dana appears central.",
                "claims": [
                    {"id": "c1", "type": "fact", "text": "Dana owns the deliverable.", "citations": [ids[0]]},
                    {"id": "c2", "type": "fact", "text": "Dana confirmed the restart.", "citations": ids[:2]},
                    {
                        "id": "c3",
                        "type": "inference",
                        "text": "Dana appears to be part of the core team.",
                        "derived_from": ["c1", "c2"],
                    },
                ],
            }

        result = self.ask("explain certification ownership", synthesizer=StubSynthesizer(payload))

        self.assertEqual(result["inference_count"], 1)
        self.assertIn("drawn from the pattern of the evidence", result["uncertainty"])

    def test_a_clean_answer_carries_no_uncertainty_line_at_all(self):
        self.build_index()

        def payload(context):
            ids = context.bundle.citation_ids()
            return {
                "answer": f"Dana owns the certification deliverable [{ids[0]}].",
                "claims": [
                    {
                        "id": "c1",
                        "type": "fact",
                        "text": "Dana Okonkwo owns the certification deliverable.",
                        "citations": [ids[0]],
                    }
                ],
            }

        result = self.ask("explain certification ownership", synthesizer=StubSynthesizer(payload))

        self.assertEqual(result["uncertainty"], "")

    def test_diagnostics_remain_in_the_json_contract(self):
        self.build_index()
        result = self.run_cli(["ask", "--json", "--no-ai", "What is the unit cost?"])
        payload = json.loads(result.output)

        self.assertIn("diagnostics", payload)
        for key in (
            "validator_notes",
            "grounding_warnings",
            "dropped_citations",
            "rejected_fields",
        ):
            self.assertIn(key, payload["diagnostics"])

    def test_the_claim_ledger_still_shows_types_under_show_sources(self):
        self.build_index()
        result = self.run_cli(["ask", "--show-sources", "Show documents about certification"])
        self.assertIn("Claim ledger:", result.output)

    def test_the_inference_label_is_explicit_in_the_ledger_view(self):
        self.assertIn("inference", gang_cli.CLAIM_LABELS)
        self.assertIn("not stated in it", gang_cli.CLAIM_LABELS["inference"])


if __name__ == "__main__":
    unittest.main()
