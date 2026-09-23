"""Generated evidence facts: explicit statements, materialized and cited.

Entity linking says a document refers to someone. These tests cover the layer
that records what documents *state* — "Daniel Hirunrusme is a co-founder of
GANG", "Outer shipping carton applied in China" — and the lines it must not
cross:

* only explicit statements produce facts; attendance, participation, a shared
  email domain, and frequency never do;
* bulk mail is never identity evidence, whatever it says;
* every fact carries its exact quote, verified against its source;
* canonical Markdown is never touched, and human descriptions win;
* the store rebuilds idempotently and invalidates on source, extractor, and
  entity changes;
* factual answers cost no model call.

Everything runs against a temporary GANG_HOME. The network and every provider
are wired to fail if touched.
"""

import os
import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from click.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

import cli as gang_cli
from core import source_classes
from core.ask import ConversationOptions, ConversationService
from core.ask import deterministic as deterministic_module
from core.entities import EntityService
from core.entities.model import EntityRecord
from core.entities.profiles import EntityProfileService
from core.facts import (
    METHOD_DETERMINISTIC,
    METHOD_LOCAL_MODEL,
    ClaimProposal,
    ClaimValidationError,
    EvidenceFactService,
    validate_proposal,
)
from core.facts import model as facts_model
from core.facts import service as facts_service_module
from core.facts.decisions import extract_decisions
from core.facts.extract import EntityIndex, extract_relations
from core.private_index import PrivateKnowledgeIndex

from test_conversation import StubSynthesizer, tree_fingerprint, write_markdown


SIGNATURE_ID = "01a0cf00-0000-7000-a000-00000000f001"
NEWSLETTER_ID = "01a0cf00-0000-7000-a000-00000000f002"
ATTENDEES_ID = "01a0cf00-0000-7000-a000-00000000f003"
BOARD_ID = "01a0cf00-0000-7000-a000-00000000f004"
RECAP_ID = "01a0cf00-0000-7000-a000-00000000f005"
AGENDA_ID = "01a0cf00-0000-7000-a000-00000000f006"
SUMMARY_ID = "01a0cf00-0000-7000-a000-00000000f007"
SCHEDULE_ID = "01a0cf00-0000-7000-a000-00000000f008"
THREAD_ID = "01a0cf00-0000-7000-a000-00000000f009"

PERSON_DANIEL = "01a0cf10-0000-7000-a000-0000000000d1"
PERSON_FRANK = "01a0cf10-0000-7000-a000-0000000000f1"
PERSON_DANA = "01a0cf10-0000-7000-a000-0000000000a1"
COMPANY_GANG = "01a0cf10-0000-7000-a000-0000000000c1"


def gmail_frontmatter(document_id, title, date, sender, recipients="daniel@gang.example"):
    return {
        "id": document_id,
        "type": "email-thread",
        "source_type": "gmail-thread",
        "title": title,
        "visibility": "private",
        "status": "active",
        "content_trust": "untrusted",
        "source_id": f"gmail-thread_{document_id[-4:]}",
        "created": date,
        "updated": date,
        "gmail": {"participants": [sender, recipients]},
        "ingestion_envelope": {
            "source_type": "gmail-thread",
            "messages": [{"headers": {"From": sender, "To": recipients, "Subject": title}}],
        },
    }


class FactsTestCase(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        credentials = mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}, clear=False)
        credentials.start()
        self.addCleanup(credentials.stop)
        network = mock.patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("Unexpected provider network call; evidence facts are deterministic."),
        )
        network.start()
        self.addCleanup(network.stop)

        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name) / "repo"
        self.home = Path(self._temp.name) / "gang-home"
        (self.root / "brain/vault/public/posts").mkdir(parents=True)
        self.write_corpus()

    # ----------------------------------------------------------- the corpus

    def write_corpus(self):
        # Daniel's own signature, in a message Daniel sent.
        write_markdown(
            self.home / "vault/emails/signature.md",
            gmail_frontmatter(
                SIGNATURE_ID,
                "WPC membership application",
                "2026-02-12",
                "Daniel Hirunrusme <daniel@gang.example>",
                "membership@wpc.example",
            ),
            "## Messages\n\n### Message 1\n\n"
            "- From: Daniel Hirunrusme <daniel@gang.example>\n"
            "- To: membership@wpc.example\n\n"
            "Hello, the membership application is attached.\n\n"
            "All the best,\n\n"
            "Daniel Hirunrusme\n"
            "GANG, Co-Founder\n"
            "daniel@gang.example\n",
        )
        # A newsletter sent to Daniel that happens to say something about him.
        write_markdown(
            self.home / "vault/emails/newsletter.md",
            gmail_frontmatter(
                NEWSLETTER_ID,
                "This week in design",
                "2026-09-22",
                "Design Weekly <newsletters@designweekly.example>",
                "Daniel Hirunrusme <daniel@gang.example>",
            ),
            "- Participants: Daniel Hirunrusme <daniel@gang.example>, Design Weekly\n\n"
            "Reader spotlight: Daniel Hirunrusme is the Chief Executive Officer of GANG.\n\n"
            "You are receiving this email because you subscribed. Unsubscribe.\n",
        )
        # Attendance and participation, repeated: presence and nothing else.
        write_markdown(
            self.home / "vault/emails/attendees.md",
            gmail_frontmatter(
                ATTENDEES_ID,
                "Kickoff invite follow-up",
                "2026-05-04",
                "Dana Reyes <dana@gang.example>",
                "Daniel Hirunrusme <daniel@gang.example>",
            ),
            "- From: Dana Reyes <dana@gang.example>\n"
            "- To: Daniel Hirunrusme <daniel@gang.example>, Frank Godchaux <frank@gang.example>\n\n"
            "Attendees: Dana Reyes, Daniel Hirunrusme, Frank Godchaux\n\n"
            "Dana Reyes and Daniel Hirunrusme reviewed tooling lead times.\n"
            "Dana Reyes joined the call again on Friday.\n",
        )
        # Formal board notes with explicit decision sections.
        write_markdown(
            self.home / "vault/emails/board.md",
            gmail_frontmatter(
                BOARD_ID,
                "GANG Meeting 24 Notes Date: August 21, 2026",
                "2026-08-22",
                "Steven Gormley <steven@eliro.example>",
            ),
            "6. Double-Box Packaging Strategy\n\n"
            "The team aligned on *double-boxing the finished product* to protect the\n"
            "retail packaging during transportation to the consumer.\n"
            "Decision\n\n"
            "*Outer shipping carton applied in China.*\n"
            "Remaining Work\n\n"
            "   - Confirm final outer-carton dimensions.\n"
            "------------------------------\n"
            "Decisions\n"
            "Aligned\n"
            "Continue refining premium packaging using the magnetic fold-over design.\n"
            "Delay formal prototype demonstrations until mechanical issues are corrected.\n"
            "Requires Follow-Up\n"
            "Final packaging cost.\n"
            "------------------------------\n"
            "Decision Required\n\n"
            "Choose the packaging print vendor.\n\n"
            "> Decision\n"
            "> Quoted packaging decision that belongs to another message.\n",
        )
        write_markdown(
            self.home / "vault/emails/recap.md",
            gmail_frontmatter(
                RECAP_ID,
                "Meeting Recap 2026-08-28",
                "2026-08-29",
                "Jess Huffman <jess@creative.example>",
            ),
            "   - *Screwdriver*\n"
            "      - *Decision made*: we will use the thicker handled screwdriver. Jess\n"
            "      will rework the screwdriver and packaging in response.\n"
            "   - *Etching Samples*\n"
            "      - Etching samples shipped today.\n",
        )
        # A forward-looking agenda: its "Decision" headings are still open.
        write_markdown(
            self.home / "vault/emails/agenda.md",
            gmail_frontmatter(
                AGENDA_ID,
                "FINAL WORKING VERSION FOR Meeting 37 — November 13, 2026",
                "2026-09-20",
                "Steven Gormley <steven@eliro.example>",
            ),
            "Decision\n\n*Is the packaging approved?*\n\n"
            "Decision\n\nApprove the packaging print vendor.\n",
        )
        # A meeting summary delivered by a no-reply assistant.
        write_markdown(
            self.home / "vault/emails/summary.md",
            gmail_frontmatter(
                SUMMARY_ID,
                "Your summary of Packaging Handoff",
                "2026-04-27",
                "Sana <noreply@sana.example>",
            ),
            "Key topics\n"
            "Packaging Handoff decisions\n"
            ": The team rejected the underside cable wrap as higher-cost and agreed to place "
            "a standard cord on the top foam instead. Jess will prototype the packaging now.\n"
            "You're getting this email because you have an account.\n",
        )
        # Explicitly assigned work, for the ownership route.
        write_markdown(
            self.home / "vault/emails/schedule.md",
            gmail_frontmatter(
                SCHEDULE_ID,
                "GANG Schedule — Due Soon (2026-09-21)",
                "2026-09-21",
                "Daniel Hirunrusme <daniel@gang.example>",
            ),
            "From: Daniel Hirunrusme <daniel@gang.example> - To: daniel@gang.example, frank@gang.example\n"
            "Open tasks are due today, imminent, or overdue:\n"
            "1. Order the packaging proof Owner: Daniel | Due: 2026-09-12 | Status: in progress\n",
        )
        # Ordinary correspondence that names people but states nothing.
        write_markdown(
            self.home / "vault/emails/thread.md",
            gmail_frontmatter(
                THREAD_ID,
                "Lunch Friday",
                "2026-09-01",
                "Frank Godchaux <frank@gang.example>",
            ),
            "Daniel Hirunrusme and Frank Godchaux will grab lunch on Friday.\n"
            "Frank Godchaux, who is traveling, may join late.\n",
        )

    # ------------------------------------------------------------- helpers

    def entities(self):
        return EntityService(root_path=self.root, private_home=self.home)

    def facts(self):
        return EvidenceFactService(root_path=self.root, private_home=self.home)

    def build_index(self):
        return PrivateKnowledgeIndex(root_path=self.root, private_home=self.home).build()

    def seed(self, *, describe_frank=True):
        service = self.entities()
        gang = service.create("company", "GANG", domains=["gang.example"])
        daniel = service.create(
            "person", "Daniel Hirunrusme", aliases=["Daniel", "Dan"], emails=["daniel@gang.example"]
        )
        frank = service.create("person", "Frank Godchaux", aliases=["Frank"], emails=["frank@gang.example"])
        dana = service.create("person", "Dana Reyes", aliases=["Dana"])
        if describe_frank:
            service.describe(frank.id, description="Frank Godchaux is a co-founder of GANG.")
        # Mailbox participation links Daniel to everything, exactly as the
        # verified-email backfill does on the real corpus.
        for document_id in (SIGNATURE_ID, NEWSLETTER_ID, ATTENDEES_ID, BOARD_ID, SCHEDULE_ID, THREAD_ID):
            service.add_mention(document_id, daniel.id, label="daniel@gang.example", excerpt="daniel@gang.example")
        service.add_mention(ATTENDEES_ID, dana.id, excerpt="Dana Reyes")
        self.build_index()
        return {"gang": gang, "daniel": daniel, "frank": frank, "dana": dana}

    def service(self, **kwargs):
        kwargs.setdefault("synthesizer", StubSynthesizer())
        return ConversationService(root_path=self.root, private_home=self.home, **kwargs)

    def ask(self, question, *, use_ai=True, **kwargs):
        service = self.service(**kwargs)
        return service.converse(
            question,
            session=service.start(),
            options=ConversationOptions(use_ai=use_ai, use_cache=False, persist=False, show_research=True),
        )

    def run_cli(self, args):
        return CliRunner().invoke(
            gang_cli.cli,
            args,
            env={"GANG_HOME": str(self.home), "ANTHROPIC_API_KEY": ""},
            catch_exceptions=False,
        )


def records(*specs):
    """Minimal in-memory entity records for extractor unit tests."""
    built = []
    for entity_id, entity_type, name, aliases, emails in specs:
        built.append(
            EntityRecord(id=entity_id, type=entity_type, name=name, aliases=list(aliases), emails=list(emails))
        )
    return built


UNIT_RECORDS = records(
    (PERSON_DANIEL, "person", "Daniel Hirunrusme", ["Daniel"], ["daniel@gang.example"]),
    (PERSON_FRANK, "person", "Frank Godchaux", ["Frank"], ["frank@gang.example"]),
    (PERSON_DANA, "person", "Dana Reyes", [], []),
    (COMPANY_GANG, "company", "GANG", [], []),
)


# ================================================================ extraction


class RelationExtractionTests(unittest.TestCase):
    def setUp(self):
        self.index = EntityIndex(UNIT_RECORDS)

    def claims(self, body, senders=()):
        return extract_relations(document_id="doc", body=body, index=self.index, sender_addresses=senders)

    def assertClaims(self, body, expected, senders=()):
        found = sorted(
            (claim.subject_entity_id, claim.predicate, claim.object_entity_id)
            for claim in self.claims(body, senders)
        )
        self.assertEqual(found, sorted(expected))

    def test_explicit_statements_produce_claims(self):
        cases = {
            "Daniel Hirunrusme is a co-founder of GANG.": [(PERSON_DANIEL, "cofounder_of", COMPANY_GANG)],
            "GANG co-founders Daniel Hirunrusme and Frank Godchaux met the factory.": [
                (PERSON_DANIEL, "cofounder_of", COMPANY_GANG),
                (PERSON_FRANK, "cofounder_of", COMPANY_GANG),
            ],
            "Daniel Hirunrusme, co-founder of GANG, signed the letter.": [
                (PERSON_DANIEL, "cofounder_of", COMPANY_GANG)
            ],
            "This summarizes the vision of the founders of GANG, Frank Godchaux and Daniel Hirunrusme.": [
                (PERSON_FRANK, "founder_of", COMPANY_GANG),
                (PERSON_DANIEL, "founder_of", COMPANY_GANG),
            ],
            "Daniel Hirunrusme and Frank Godchaux are the co-founders of GANG.": [
                (PERSON_DANIEL, "cofounder_of", COMPANY_GANG),
                (PERSON_FRANK, "cofounder_of", COMPANY_GANG),
            ],
        }
        for body, expected in cases.items():
            with self.subTest(body=body):
                self.assertClaims(body, expected)

    def test_a_stated_title_is_kept_verbatim_as_the_role(self):
        (claim,) = self.claims("Daniel Hirunrusme serves as Chief Executive Officer of GANG.")
        self.assertEqual(claim.predicate, "works_for")
        self.assertEqual(claim.role, "Chief Executive Officer")

    def test_participation_never_produces_a_role(self):
        bodies = [
            "Attendees: Daniel Hirunrusme, Frank Godchaux, Dana Reyes",
            "- Participants: Daniel Hirunrusme <daniel@gang.example>, GANG <hello@gang.example>",
            "From: Daniel Hirunrusme <daniel@gang.example>\nTo: Frank Godchaux <frank@gang.example>",
            "Daniel Hirunrusme and Frank Godchaux attended the GANG board meeting.",
            "Daniel Hirunrusme joined the GANG call. Daniel Hirunrusme joined the GANG call again.",
            "Dana Reyes emailed from dana@gang.example about GANG.",
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.assertClaims(body, [])

    def test_qualified_or_misattributed_statements_produce_nothing(self):
        bodies = [
            "Daniel Hirunrusme is not a co-founder of GANG.",
            "Daniel Hirunrusme is a former co-founder of GANG.",
            "Daniel Hirunrusme is a potential advisor to GANG.",
            "Daniel Hirunrusme said Dana is a co-founder of GANG.",
            "Is Daniel Hirunrusme a co-founder of GANG?",
            "Daniel Hirunrusme is a co-founder of GANG-Tech.",
            "Daniel Hirunrusme, co-founder of Gang Tech, LLC, signed.",
        ]
        for body in bodies:
            with self.subTest(body=body):
                self.assertClaims(body, [])

    def test_a_person_named_only_by_alias_is_kept_below_high_confidence(self):
        (claim,) = self.claims("Daniel is a co-founder of GANG.")
        self.assertEqual(claim.confidence, "medium")
        (full,) = self.claims("Daniel Hirunrusme is a co-founder of GANG.")
        self.assertEqual(full.confidence, "high")

    def test_a_signature_block_from_its_owner_is_a_role_statement(self):
        body = "Thanks,\n\nDaniel Hirunrusme\nGANG, Co-Founder\ndaniel@gang.example\n"
        (claim,) = self.claims(body, senders=["Daniel Hirunrusme <daniel@gang.example>"])
        self.assertEqual(
            (claim.subject_entity_id, claim.predicate, claim.object_entity_id),
            (PERSON_DANIEL, "cofounder_of", COMPANY_GANG),
        )
        self.assertEqual(claim.rule, "signature-block")
        self.assertEqual(claim.excerpt, "Daniel Hirunrusme GANG, Co-Founder daniel@gang.example")

    def test_a_signature_is_not_a_statement_unless_its_owner_sent_it(self):
        body = "Thanks,\n\nDaniel Hirunrusme\nGANG, Co-Founder\ndaniel@gang.example\n"
        self.assertEqual(self.claims(body, senders=["Frank Godchaux <frank@gang.example>"]), [])
        quoted = "> Daniel Hirunrusme\n> GANG, Co-Founder\n> daniel@gang.example\n"
        self.assertEqual(self.claims(quoted, senders=["Daniel Hirunrusme <daniel@gang.example>"]), [])
        # Name and title without the owner's address could be anyone's block.
        missing = "Daniel Hirunrusme\nGANG, Co-Founder\n+1 555 0100\n"
        self.assertEqual(self.claims(missing, senders=["Daniel Hirunrusme <daniel@gang.example>"]), [])

    def test_an_ambiguous_alias_is_never_used(self):
        index = EntityIndex(
            UNIT_RECORDS
            + records(("01a0cf10-0000-7000-a000-0000000000d2", "person", "Daniel Other", ["Daniel"], []))
        )
        found = extract_relations(document_id="doc", body="Daniel is a co-founder of GANG.", index=index)
        self.assertEqual(found, [])


# ================================================================ validation


class ProposalValidationTests(unittest.TestCase):
    """The boundary any proposer — rules today, a local model later — must pass."""

    SOURCE = "Board notes. Daniel Hirunrusme is a co-founder of GANG. Nothing else."

    def setUp(self):
        self.index = EntityIndex(UNIT_RECORDS)

    def proposal(self, **overrides):
        values = dict(
            document_id="doc",
            subject_entity_id=PERSON_DANIEL,
            predicate="cofounder_of",
            object_entity_id=COMPANY_GANG,
            excerpt="Daniel Hirunrusme is a co-founder of GANG.",
            method=METHOD_DETERMINISTIC,
        )
        values.update(overrides)
        return ClaimProposal(**values)

    def validate(self, proposal):
        return validate_proposal(
            proposal, source_text=self.SOURCE, entities=self.index.records, surface_forms=self.index.surface_forms()
        )

    def test_a_verified_claim_is_admitted(self):
        self.assertEqual(self.validate(self.proposal()).confidence, "high")

    def test_rejections(self):
        cases = {
            "fabricated quote": self.proposal(excerpt="Daniel Hirunrusme is the CEO of GANG."),
            "uncontrolled predicate": self.proposal(predicate="ceo_of"),
            "unresolved entity": self.proposal(object_entity_id="01a0cf10-0000-7000-a000-00000000dead"),
            "wrong subject type": self.proposal(subject_entity_id=COMPANY_GANG, object_entity_id=PERSON_DANIEL),
            "remote model": self.proposal(method="anthropic-model"),
            "quote about someone else": self.proposal(subject_entity_id=PERSON_FRANK),
            "two objects": self.proposal(object_value="GANG"),
            "no quote": self.proposal(excerpt=""),
        }
        for label, proposal in cases.items():
            with self.subTest(case=label):
                with self.assertRaises(ClaimValidationError):
                    self.validate(proposal)

    def test_a_local_model_claim_is_capped_below_what_ask_states(self):
        admitted = self.validate(self.proposal(method=METHOD_LOCAL_MODEL, confidence="high"))
        self.assertEqual(admitted.confidence, "medium")

    def test_quote_verification_tolerates_only_presentation_differences(self):
        source = "Decision\n\n*Outer shipping\ncarton applied in China.*"
        self.assertTrue(facts_model.quote_in_source("Outer shipping carton applied in China.", source))
        self.assertFalse(facts_model.quote_in_source("Outer carton applied in China.", source))


# ============================================================ source classes


class SourceClassTests(unittest.TestCase):
    def classify(self, **kwargs):
        kwargs.setdefault("source_type", "gmail-thread")
        return source_classes.classify_source(**kwargs)

    def test_newsletters_and_notifications_are_bulk(self):
        self.assertEqual(
            self.classify(title="This week in design", senders=["Design Weekly <newsletters@designweekly.example>"]).name,
            source_classes.BULK,
        )
        self.assertEqual(
            self.classify(title="Welcome aboard", senders=["Ann <ann@shop.example>"], body="… Unsubscribe here").name,
            source_classes.BULK,
        )
        self.assertEqual(
            self.classify(title="Updated invitation: GANG weekly", senders=["pam@eliro.example"]).name,
            source_classes.BULK,
        )

    def test_meeting_summaries_rank_as_notes_whoever_delivers_them(self):
        found = self.classify(title="Your summary of Packaging Handoff", senders=["Sana <noreply@sana.example>"])
        self.assertEqual(found.name, source_classes.MEETING_NOTES)

    def test_mail_from_a_known_entity_is_correspondence_despite_boilerplate(self):
        found = self.classify(
            title="Fwd: newsletter",
            senders=["Daniel <daniel@gang.example>"],
            body="Unsubscribe",
            known_domains=["gang.example"],
        )
        self.assertEqual(found.name, source_classes.EMAIL)

    def test_corporate_records_outrank_everything(self):
        record = source_classes.classify_source(title="GANG Operating Agreement", source_type="drive-file")
        self.assertEqual(record.name, source_classes.CORPORATE_RECORD)
        self.assertGreater(record.rank, source_classes.SOURCE_RANKS[source_classes.MEETING_NOTES])
        self.assertGreater(
            source_classes.SOURCE_RANKS[source_classes.MEETING_NOTES],
            source_classes.SOURCE_RANKS[source_classes.EMAIL],
        )

    def test_agendas_supply_no_decisions_and_bulk_supplies_nothing(self):
        agenda = self.classify(title="Weekly Executive Operating Agenda")
        self.assertFalse(agenda.decision_evidence)
        bulk = self.classify(title="Sale!", senders=["news@store.example"])
        self.assertFalse(bulk.identity_evidence)
        self.assertFalse(bulk.decision_evidence)


# ================================================================= decisions


class DecisionExtractionTests(unittest.TestCase):
    def decisions(self, body, *, formal=True):
        return [(item.text, item.status, item.context) for item in extract_decisions(body, formal=formal)]

    def test_a_decision_heading_takes_its_statement_and_section(self):
        body = (
            "6. Double-Box Packaging Strategy\n\nThe carton question came up.\n"
            "Decision\n\n*Outer shipping carton applied in China.*\nRemaining Work\n\n- Confirm dimensions.\n"
        )
        self.assertIn(
            ("Outer shipping carton applied in China.", "decided", "6. Double-Box Packaging Strategy"),
            self.decisions(body),
        )
        self.assertNotIn("Confirm dimensions.", [text for text, _, _ in self.decisions(body)])

    def test_a_decisions_list_honours_status_lines_and_labels(self):
        body = (
            "DecisionsAligned\n\n*Packaging*\nGANG will use a double-box shipping strategy.\n\n"
            "*Equity Structure*\nFundraising will use a single class of common stock.\n"
            "------------------------------\n"
        )
        self.assertEqual(
            self.decisions(body),
            [
                ("GANG will use a double-box shipping strategy.", "aligned", "Packaging"),
                ("Fundraising will use a single class of common stock.", "aligned", "Equity Structure"),
            ],
        )

    def test_inline_and_topic_markers(self):
        inline = "- *Decision made*: we will use the thicker handled screwdriver. Jess\nwill rework it.\nEtching Samples\n"
        self.assertEqual(
            self.decisions(inline),
            [("we will use the thicker handled screwdriver. Jess will rework it.", "decided", "")],
        )
        topic = (
            "Packaging Handoff decisions\n: The team rejected the side wrap and agreed to use the top foam. "
            "Jess will prototype it.\n"
        )
        self.assertEqual(
            self.decisions(topic, formal=False),
            [("The team rejected the side wrap and agreed to use the top foam.", "agreed", "Packaging Handoff")],
        )

    def test_group_agreement_is_trusted_only_in_formal_notes(self):
        body = "The team approved having the factory apply the outer carton.\n"
        self.assertEqual(self.decisions(body, formal=True)[0][1], "approved")
        self.assertEqual(self.decisions(body, formal=False), [])

    def test_what_is_not_a_decision(self):
        bodies = [
            "Decision Required\n\nChoose the print vendor.\n",
            "Decision\n\n*Are all prerequisites in place?*\n",
            "> Decision\n> Quoted decision from another message.\n",
            "Daniel and Frank agreed.\n",
            "The team agreed to revisit the carton next week.\n",
            "The team did not agree on the carton.\n",
            "Decisions\nAligned\nContinue the fold-over design.\nRequires Follow-Up\nFinal packaging cost.\n",
        ]
        results = {body: self.decisions(body) for body in bodies}
        self.assertEqual(results[bodies[-1]], [("Continue the fold-over design.", "aligned", "")])
        for body in bodies[:-1]:
            with self.subTest(body=body):
                self.assertEqual(results[body], [])


# ============================================================ store behavior


class FactStoreTests(FactsTestCase):
    def test_build_materializes_explicit_facts_with_full_provenance(self):
        seeded = self.seed()
        report = self.facts().build()

        self.assertEqual(report["malformed"], 0)
        (fact,) = self.facts().facts_for(seeded["daniel"].id)
        self.assertEqual(fact.sentence(), "Daniel Hirunrusme is a co-founder of GANG.")
        self.assertEqual(fact.document_id, SIGNATURE_ID)
        self.assertEqual(fact.excerpt, "Daniel Hirunrusme GANG, Co-Founder daniel@gang.example")
        self.assertEqual(fact.document_date, "2026-02-12")
        self.assertEqual(fact.method, METHOD_DETERMINISTIC)
        self.assertEqual(fact.rule, "signature-block")
        self.assertEqual(fact.extractor_version, facts_model.EXTRACTOR_VERSION)
        self.assertTrue(fact.source_hash)
        self.assertEqual(fact.source_class, source_classes.EMAIL)

    def test_the_newsletter_is_never_identity_evidence(self):
        seeded = self.seed()
        self.facts().build()

        for fact in self.facts().facts_for(seeded["daniel"].id, min_confidence="low"):
            self.assertNotEqual(fact.document_id, NEWSLETTER_ID)
            self.assertNotEqual(fact.predicate, "works_for")
        with sqlite3.connect(self.facts().store.database_path) as connection:
            source_class = connection.execute(
                "SELECT source_class FROM sources WHERE document_id = ?", (NEWSLETTER_ID,)
            ).fetchone()[0]
        self.assertEqual(source_class, source_classes.BULK)

    def test_attendance_and_participation_create_no_roles(self):
        seeded = self.seed()
        self.facts().build()

        self.assertEqual(self.facts().facts_for(seeded["dana"].id, min_confidence="low"), [])
        attendee_facts = [
            fact
            for person in ("daniel", "frank", "dana")
            for fact in self.facts().facts_for(seeded[person].id, min_confidence="low")
            if fact.document_id in (ATTENDEES_ID, THREAD_ID)
        ]
        self.assertEqual(attendee_facts, [])

    def test_rebuilding_twice_over_unchanged_evidence_is_idempotent(self):
        self.seed()
        service = self.facts()
        first = service.build()
        snapshot = service.store.snapshot()
        second = service.build()
        forced = service.build(force=True)

        self.assertGreater(first["extracted"], 0)
        self.assertEqual(second["extracted"], 0)
        self.assertEqual(second["removed"], 0)
        self.assertEqual(service.store.snapshot(), snapshot)
        self.assertEqual(forced["facts"], first["facts"])
        self.assertEqual(service.store.snapshot(), snapshot)

    def test_a_changed_source_is_reextracted_and_a_deleted_one_is_forgotten(self):
        seeded = self.seed()
        service = self.facts()
        service.build()
        self.assertEqual(len(service.facts_for(seeded["daniel"].id)), 1)

        path = self.home / "vault/emails/signature.md"
        path.write_text(path.read_text(encoding="utf-8").replace("GANG, Co-Founder\n", ""), encoding="utf-8")
        changed = service.build()
        self.assertEqual(changed["extracted"], 1)
        self.assertEqual(service.facts_for(seeded["daniel"].id), [])

        board_decisions = service.decisions(topic="carton")["total"]
        self.assertGreater(board_decisions, 0)
        (self.home / "vault/emails/board.md").unlink()
        removed = service.build()
        self.assertEqual(removed["removed"], 1)
        self.assertEqual(service.decisions(topic="carton")["total"], 0)

    def test_a_new_extractor_version_or_entity_change_reextracts_everything(self):
        seeded = self.seed()
        service = self.facts()
        service.build()

        with mock.patch.object(facts_service_module, "EXTRACTOR_VERSION", facts_model.EXTRACTOR_VERSION + 1):
            upgraded = service.build()
        self.assertTrue(upgraded["full_rebuild"])

        self.entities().add_alias(seeded["gang"].id, "Gang Tech")
        realiased = self.facts().build()
        self.assertTrue(realiased["full_rebuild"])
        self.assertEqual(realiased["extracted"], realiased["scanned"])

    def test_building_never_touches_canonical_markdown(self):
        self.seed()
        before = tree_fingerprint(self.home / "vault")
        self.facts().build(force=True)
        self.ask("who is Daniel?")
        self.ask("what did we decide about packaging?")
        self.assertEqual(tree_fingerprint(self.home / "vault"), before)

    def test_a_suppression_survives_rebuilds_without_editing_the_source(self):
        seeded = self.seed()
        service = self.facts()
        service.build()
        (fact,) = service.facts_for(seeded["daniel"].id)
        before = tree_fingerprint(self.home / "vault")

        service.suppress(fact.fact_id, reason="test")
        service.clear()
        service.build(force=True)

        self.assertEqual(service.facts_for(seeded["daniel"].id), [])
        self.assertEqual(
            [item.fact_id for item in service.facts_for(seeded["daniel"].id, include_suppressed=True)],
            [fact.fact_id],
        )
        self.assertEqual(tree_fingerprint(self.home / "vault"), before)
        self.assertTrue(service.overrides_path.exists())
        self.assertNotIn("generated", service.overrides_path.parts)


# ======================================================================= Ask


class DefinitionLadderTests(FactsTestCase):
    def test_who_is_daniel_states_the_evidenced_role(self):
        self.seed()
        stub = StubSynthesizer()

        result = self.ask("who is Daniel?", synthesizer=stub)

        self.assertEqual(result["synthesis"]["reason"], deterministic_module.EVIDENCE_FACTS_REASON)
        self.assertTrue(result["answer"].startswith("Daniel Hirunrusme is a co-founder of GANG. [1]"))
        self.assertIn("Evidence: “Daniel Hirunrusme GANG, Co-Founder daniel@gang.example”", result["answer"])
        self.assertEqual([source["document_id"] for source in result["sources"]], [SIGNATURE_ID])
        for claim in result["claims"]:
            self.assertTrue(claim["citations"])
        self.assertEqual(result["provider_calls"], [])
        self.assertEqual(stub.contexts, [])

    def test_who_is_frank_keeps_the_authored_description(self):
        seeded = self.seed()
        # Even a statement the extractor would accept does not compete with
        # the description a human wrote.
        write_markdown(
            self.home / "vault/emails/frank-role.md",
            gmail_frontmatter(THREAD_ID[:-1] + "a", "Board notes", "2026-09-02", "steven@eliro.example"),
            "Frank Godchaux is a partner at GANG.\n",
        )
        self.build_index()

        result = self.ask("who is Frank?")

        self.assertEqual(result["synthesis"]["reason"], "deterministic-capability")
        self.assertTrue(result["answer"].startswith("Frank Godchaux is a co-founder of GANG."))
        self.assertNotIn("partner", result["answer"])
        self.assertEqual(result["sources"][0]["document_id"], seeded["frank"].id)

    def test_a_human_relationship_is_stated_before_generated_facts(self):
        seeded = self.seed()
        self.entities().assert_relationship(
            document_id=BOARD_ID,
            subject_entity_id=seeded["daniel"].id,
            predicate="affiliated_with",
            object_entity_id=seeded["gang"].id,
            excerpt="Double-Box Packaging Strategy",
        )

        result = self.ask("who is Daniel Hirunrusme?")

        lines = [line for line in result["answer"].splitlines() if line and not line.startswith("  ")]
        self.assertTrue(lines[0].startswith("Daniel Hirunrusme is affiliated with GANG."))
        self.assertTrue(lines[1].startswith("Daniel Hirunrusme is a co-founder of GANG."))

    def test_no_explicit_evidence_falls_back_to_the_derived_profile(self):
        self.seed()

        result = self.ask("who is Dana Reyes?")

        self.assertEqual(result["synthesis"]["reason"], deterministic_module.DERIVED_PROFILE_REASON)
        self.assertIn("No document in this evidence states a role", result["answer"])

    def test_a_suppressed_fact_is_not_stated(self):
        seeded = self.seed()
        service = self.facts()
        service.build()
        (fact,) = service.facts_for(seeded["daniel"].id)
        service.suppress(fact.fact_id)

        result = self.ask("who is Daniel?")

        self.assertNotEqual(result["synthesis"]["reason"], deterministic_module.EVIDENCE_FACTS_REASON)
        self.assertNotIn("co-founder", result["answer"])

    def test_a_quote_no_longer_in_the_index_is_not_cited(self):
        seeded = self.seed()
        service = self.facts()
        service.build()
        with sqlite3.connect(service.store.database_path) as connection:
            connection.execute(
                "UPDATE facts SET excerpt = 'Daniel Hirunrusme GANG, Co-Founder, retired' WHERE subject_entity_id = ?",
                (seeded["daniel"].id,),
            )
        with mock.patch.object(EvidenceFactService, "build", return_value={}):
            result = self.ask("who is Daniel?")

        self.assertNotEqual(result["synthesis"]["reason"], deterministic_module.EVIDENCE_FACTS_REASON)

    def test_the_newsletter_is_not_cited_by_the_fallback_profile_either(self):
        seeded = self.seed()
        profile = EntityProfileService(root_path=self.root, private_home=self.home).profile(
            seeded["daniel"].id, persist=False
        )
        cited = {document_id for statement in profile.statements for document_id in statement.document_ids}
        self.assertNotIn(NEWSLETTER_ID, cited)
        self.assertIn(SIGNATURE_ID, cited)


class DecisionAnswerTests(FactsTestCase):
    def test_packaging_decisions_are_materialized_with_dates_status_and_citations(self):
        self.seed()
        stub = StubSynthesizer()

        result = self.ask("what did we decide about packaging?", synthesizer=stub)
        answer = result["answer"]

        self.assertEqual(result["synthesis"]["reason"], deterministic_module.MATERIALIZED_DECISIONS_REASON)
        self.assertIn(
            "- 2026-08-21 — Outer shipping carton applied in China. (decided; 6. Double-Box Packaging Strategy)",
            answer,
        )
        self.assertIn("Continue refining premium packaging using the magnetic fold-over design. (aligned)", answer)
        self.assertIn("- 2026-08-28 — we will use the thicker handled screwdriver.", answer)
        self.assertIn("agreed to place a standard cord on the top foam instead. (agreed; Packaging Handoff)", answer)
        # Newest first.
        self.assertLess(answer.index("2026-08-28"), answer.index("2026-08-21"))
        self.assertLess(answer.index("2026-08-21"), answer.index("2026-04-27"))
        for excluded in ("Final packaging cost", "print vendor", "Is the packaging approved", "Quoted packaging"):
            with self.subTest(excluded=excluded):
                self.assertNotIn(excluded, answer)
        for claim in result["claims"]:
            self.assertTrue(claim["citations"])
        self.assertEqual(result["provider_calls"], [])
        self.assertEqual(stub.contexts, [])

    def test_decisions_that_match_nothing_leave_the_ordinary_path_alone(self):
        self.seed()

        result = self.ask("what did we decide about zirconium?", use_ai=False)

        self.assertNotEqual(result["synthesis"].get("reason"), deterministic_module.MATERIALIZED_DECISIONS_REASON)


class AssignmentsUnchangedTests(FactsTestCase):
    def test_what_does_daniel_need_to_do_still_uses_assignments(self):
        self.seed()

        result = self.ask("what does Daniel need to do?")

        self.assertEqual(result["synthesis"]["reason"], deterministic_module.ASSIGNMENTS_REASON)
        self.assertIn("Order the packaging proof", result["answer"])
        self.assertNotIn("co-founder", result["answer"])
        self.assertEqual(result["provider_calls"], [])


# ======================================================================= CLI


class FactsCliTests(FactsTestCase):
    def test_build_show_decisions_and_suppress(self):
        self.seed()

        built = self.run_cli(["facts", "build"])
        self.assertEqual(built.exit_code, 0, built.output)
        self.assertIn("never canonical", built.output)

        again = self.run_cli(["facts", "build", "--format", "json"])
        self.assertIn('"extracted": 0', again.output)

        shown = self.run_cli(["facts", "show", "Daniel"])
        self.assertEqual(shown.exit_code, 0, shown.output)
        self.assertIn("Daniel Hirunrusme is a co-founder of GANG.", shown.output)
        fact_id = next(token for token in shown.output.split() if token.startswith("fact_"))

        decisions = self.run_cli(["facts", "decisions", "--topic", "packaging"])
        self.assertIn("Outer shipping carton applied in China.", decisions.output)

        suppressed = self.run_cli(["facts", "suppress", fact_id, "--reason", "test"])
        self.assertEqual(suppressed.exit_code, 0, suppressed.output)
        self.assertIn("No generated facts", self.run_cli(["facts", "show", "Daniel"]).output)

        status = self.run_cli(["facts", "status"])
        self.assertIn("Suppressed: 1", status.output)

    def test_index_build_refreshes_facts(self):
        self.seed()

        result = self.run_cli(["index", "build"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("Evidence facts:", result.output)
        self.assertTrue(self.facts().store.exists())


if __name__ == "__main__":
    unittest.main()
