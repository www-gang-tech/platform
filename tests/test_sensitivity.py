"""Epic 11.5 — sensitive evidence boundaries.

The central guarantee: a document containing a Social Security number never
appears in anything handed to a remote provider, on any path — one-shot Ask,
conversational synthesis, the research director, enrichment, or entity
proposals — while ordinary documents flow exactly as before and deterministic
and local answers keep using the sensitive document.

Remote calls go through the real request builders and the real
``AnthropicClient``; only the ``anthropic`` SDK module is replaced, by a fake
that records every request it would have sent. Nothing here touches the
network or ~/.gang.
"""

import json
import os
import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import mock

import yaml
from click.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

import cli as gang_cli
from core import sensitivity
from core.ai_provider import (
    AIConfig,
    AnthropicClient,
    ConfiguredAIClient,
    SensitiveEgressError,
    is_remote_provider,
)
from core.ask import ConversationOptions, ConversationService
from core.ask import disclosure
from core.ask.answer import ConversationSynthesizer
from core.ask.evidence import build_bundle
from core.ask.planner import DeterministicPlanner, PlanOverrides
from core.ask.research import AnthropicResearchDirector
from core.ask.retrieval import RetrievalError, Retriever
from core.ask.service import AskOptions, AskService
from core.ask.synthesis import AnthropicAnswerSynthesizer
from core.enrichment import AnthropicEnrichmentProvider, EnrichmentService, SensitiveDocumentError
from core.entities import EntityService
from core.entities.documents import preserved_entity_frontmatter
from core.entities.proposals import (
    AnthropicEntityProposer,
    EntityProposalService,
    SensitiveDocumentError as EntitySensitiveDocumentError,
)
from core.private_index import PrivateKnowledgeIndex


SSN = "123-45-6789"
ROUTING = "021000021"
BOARD_MARKER = "BOARD-ONLY-MARKER"

NORMAL_ID = "01b0bcc1-0000-7000-8000-000000000001"
SSN_ID = "01b0bcc1-0000-7000-8000-000000000002"
RESTRICTED_ID = "01b0bcc1-0000-7000-8000-000000000003"
DOWNGRADED_ID = "01b0bcc1-0000-7000-8000-000000000004"

NORMAL_TITLE = "Qi2 certification timeline"
SSN_TITLE = "Payroll onboarding packet"
RESTRICTED_TITLE = "Board memo on certification spend"

NORMAL_BODY = (
    "The Qi2 certification for the charger was restarted on September 10. "
    "Frank owns the certification submission and the lab slot is booked.\n"
)
SSN_BODY = (
    "Qi2 certification bonus paperwork for Frank. Employee social security number: "
    f"{SSN}. Direct deposit routing number: {ROUTING}. The certification bonus is "
    "paid after the lab slot.\n"
)
RESTRICTED_BODY = (
    f"Board discussed the Qi2 certification budget. {BOARD_MARKER}: spend is capped "
    "until the lab slot clears.\n"
)

QUESTION = "What is the status of the Qi2 certification?"
#: Routed to model synthesis rather than a deterministic capability.
SYNTHESIS_QUESTION = "Why was the Qi2 certification restarted?"


def write_markdown(path, frontmatter, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n" + body,
        encoding="utf-8",
    )


class FakeAnthropic:
    """Replaces the SDK module. Records every request; answers from a script.

    ``respond`` receives the keyword arguments ``messages.create`` was called
    with and returns the JSON object the model "said".
    """

    def __init__(self, respond):
        self.respond = respond
        self.requests = []

    def module(self):
        fake = self

        class Messages:
            def create(self, **kwargs):
                fake.requests.append(kwargs)
                text = json.dumps(fake.respond(kwargs))
                return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])

        class Anthropic:
            def __init__(self, api_key=None):
                self.messages = Messages()

        return SimpleNamespace(Anthropic=Anthropic)

    def sent_text(self):
        return json.dumps(self.requests, ensure_ascii=False, default=str)


def request_data(kwargs):
    """The DATA object inside a serialized Ask request."""
    content = kwargs["messages"][0]["content"]
    return json.loads(content.split("DATA:\n", 1)[1])


def grounded_answer(kwargs):
    """A well-formed answer citing the first id the request offered."""
    data = request_data(kwargs)
    ids = data.get("valid_citation_ids") or []
    if "decisions" in data:  # the research director
        return {"decision": "ENOUGH_EVIDENCE", "reason": "enough"}
    first = ids[0] if ids else None
    return {
        "answer": f"The certification was restarted [{first}]." if first else "Nothing found.",
        "claims": (
            [{"id": "c1", "type": "fact", "kind": "explicit", "text": "The certification was restarted.", "citations": [first]}]
            if first
            else []
        ),
        "insufficient_evidence": not first,
    }


class RecordingProvider:
    """A provider stub with an explicit locality, for local-path tests."""

    model = "stub-model"
    has_credentials = True

    def __init__(self, *, provider_name, is_remote):
        self.provider_name = provider_name
        self.is_remote = is_remote
        self.contexts = []

    def synthesize(self, context):
        # One-shot Ask hands over a bundle; conversation hands over a context.
        self.contexts.append(context)
        bundle = getattr(context, "bundle", context)
        first = bundle.citation_ids()[0]
        return {
            "answer": f"The certification was restarted [{first}].",
            "claims": [{"id": "c1", "type": "fact", "text": "The certification was restarted.", "citations": [first]}],
        }


class SensitivityTestCase(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        environment = mock.patch.dict(
            os.environ,
            {
                "ANTHROPIC_API_KEY": "",
                "GANG_LOCAL_ONLY": "",
                "GANG_ASK_PROVIDER": "",
                "GANG_ASK_MODEL": "",
                "GANG_OLLAMA_ENDPOINT": "",
            },
            clear=False,
        )
        environment.start()
        self.addCleanup(environment.stop)
        network = mock.patch(
            "urllib.request.urlopen",
            side_effect=AssertionError("Unexpected network call in sensitivity tests."),
        )
        network.start()
        self.addCleanup(network.stop)

        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name) / "repo"
        self.home = Path(self._temp.name) / "gang-home"
        (self.root / "brain/vault/public").mkdir(parents=True)
        self.write_corpus()

    def write_corpus(self):
        base = {"type": "knowledge", "visibility": "private", "status": "active", "content_trust": "untrusted"}
        write_markdown(
            self.home / "vault/documents/qi2-timeline.md",
            {**base, "id": NORMAL_ID, "source_type": "drive-file", "title": NORMAL_TITLE,
             "source_id": "drive-file_timeline", "created": "2026-09-10", "updated": "2026-09-10"},
            NORMAL_BODY,
        )
        write_markdown(
            self.home / "vault/documents/payroll-onboarding.md",
            {**base, "id": SSN_ID, "source_type": "gmail-attachment", "title": SSN_TITLE,
             "source_id": "gmail-attachment_payroll", "created": "2026-09-11", "updated": "2026-09-11"},
            SSN_BODY,
        )
        write_markdown(
            self.home / "vault/documents/board-memo.md",
            {**base, "id": RESTRICTED_ID, "source_type": "drive-file", "title": RESTRICTED_TITLE,
             "source_id": "drive-file_board", "created": "2026-09-12", "updated": "2026-09-12",
             "sensitivity": "restricted", "sensitivity_reason": "board only"},
            RESTRICTED_BODY,
        )

    def build_index(self):
        return PrivateKnowledgeIndex(root_path=self.root, private_home=self.home).build()

    def index(self):
        return PrivateKnowledgeIndex(root_path=self.root, private_home=self.home)

    def fake_anthropic(self, respond=grounded_answer):
        fake = FakeAnthropic(respond)
        patcher = mock.patch.dict(sys.modules, {"anthropic": fake.module()})
        patcher.start()
        self.addCleanup(patcher.stop)
        return fake

    def assert_no_sensitive_material(self, text):
        for needle in (SSN, "123456789", ROUTING, BOARD_MARKER, SSN_ID, RESTRICTED_ID, SSN_TITLE, RESTRICTED_TITLE):
            self.assertNotIn(needle, text)

    def run_cli(self, args):
        (self.root / "gang.config.yml").write_text("site:\n  name: Test\n", encoding="utf-8")
        previous = Path.cwd()
        os.chdir(self.root)
        try:
            with mock.patch.dict(os.environ, {"GANG_HOME": str(self.home)}):
                return CliRunner().invoke(gang_cli.cli, args, catch_exceptions=False)
        finally:
            os.chdir(previous)


# ================================================================ detection


class DetectionTests(unittest.TestCase):
    def detectors(self, text):
        return sorted(finding.detector for finding in sensitivity.detect(text))

    def test_strongly_structured_identifiers_are_detected(self):
        cases = {
            f"My SSN is {SSN} thanks": ["us-ssn"],
            "Social Security Number: 123456789": ["us-ssn-labeled"],
            "ITIN 912-70-1234": ["us-itin", "us-taxpayer-id-labeled"],
            "Employer identification number (EIN)\n12-3456789": ["us-taxpayer-id-labeled"],
            f"Routing number: {ROUTING}": ["bank-routing-labeled"],
            "Checking account number: 0001234567": ["bank-account-labeled"],
            "Pay DE89 3704 0044 0532 0130 00 FROM tomorrow": ["iban"],
            "Card 4111 1111 1111 1111 exp 04/28": ["payment-card"],
            "Passport No: 123456789": ["passport-labeled"],
            "Driver's License Number: D1234567": ["drivers-license-labeled"],
            "Form W-2 Wage and Tax Statement. Wages, tips, other compensation 100000": ["tax-form"],
            "1040 U.S. Individual Income Tax Return. Adjusted gross income 90,000": ["tax-form"],
            # Labels and IBANs are written in either case. A lowercase label
            # is still the identifier.
            "ssn: 123456789": ["us-ssn-labeled"],
            "Ssn 123 45 6789": ["us-ssn-labeled"],
            "ein: 12-3456789": ["us-taxpayer-id-labeled"],
            "aba: 021000021": ["bank-routing-labeled"],
            "dl# D1234567": ["drivers-license-labeled"],
            "Pay de89 3704 0044 0532 0130 00 FROM tomorrow": ["iban"],
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(self.detectors(text), expected)

    def test_ordinary_numbers_and_mentions_are_not_sensitive(self):
        for text in (
            "Call 555-123-4567 or (555) 123-4567.",
            "Dates 2024-05-12 and 12-05-2024; invoice 12-3456789.",
            "Order 021000021 shipped; routing number: 123456789 fails its checksum.",
            "Account number: 0001234567 on your utility bill.",
            "Serial 1234 5678 9012 3456 is not a card.",
            "Invalid SSN shapes 000-12-3456, 666-12-3456, 123-00-4567, 900-12-3456.",
            "SSN on file: XXX-XX-1234.",
            "Please send your W-2 and a W-9 by Friday.",
            "id 123e4567-e89b-12d3-a456-426614174000",
            "Qi2 certification QI-27832 was restarted on September 10.",
        ):
            with self.subTest(text=text):
                self.assertEqual(self.detectors(text), [])

    def test_detection_makes_a_document_local_only_and_explains_why_without_values(self):
        assessment = sensitivity.classify({"title": "Payroll"}, SSN_BODY)
        self.assertEqual(assessment.level, sensitivity.LOCAL_ONLY)
        self.assertEqual(assessment.basis, sensitivity.BASIS_DETECTED)
        self.assertFalse(assessment.permits_remote)
        rendered = json.dumps(assessment.to_dict())
        self.assertIn("us-ssn", rendered)
        self.assertIn("bank-routing-labeled", rendered)
        self.assertNotIn(SSN, rendered)
        self.assertNotIn(ROUTING, rendered)

    def test_frontmatter_strings_are_scanned_too(self):
        assessment = sensitivity.classify({"summary": f"Employee SSN {SSN}"}, "Nothing here.")
        self.assertEqual(assessment.level, sensitivity.LOCAL_ONLY)

    def test_explicit_override_wins_in_both_directions(self):
        restricted = sensitivity.classify({"sensitivity": "restricted", "sensitivity_reason": "board"}, "hello")
        self.assertEqual((restricted.level, restricted.basis), (sensitivity.RESTRICTED, sensitivity.BASIS_OVERRIDE))
        self.assertIn("board", restricted.reasons()[0])

        downgraded = sensitivity.classify({"sensitivity": "Normal"}, SSN_BODY)
        self.assertEqual(downgraded.level, sensitivity.NORMAL)
        self.assertEqual(downgraded.detected_level, sensitivity.LOCAL_ONLY)
        self.assertTrue(any("replaces the detected level" in reason for reason in downgraded.reasons()))

        spelled = sensitivity.classify({"sensitivity": "local_only"}, "hello")
        self.assertEqual(spelled.level, sensitivity.LOCAL_ONLY)

    def test_unrecognized_override_is_ignored_and_reported(self):
        assessment = sensitivity.classify({"sensitivity": "secret"}, SSN_BODY)
        self.assertEqual(assessment.level, sensitivity.LOCAL_ONLY)
        self.assertEqual(assessment.basis, sensitivity.BASIS_DETECTED)
        self.assertTrue(any("secret" in reason for reason in assessment.reasons()))

    def test_json_escaped_separator_is_masked_the_same_way_it_is_detected(self):
        text = "SSN:\\n123456789"
        self.assertEqual(self.detectors(text), ["us-ssn-labeled"])
        masked = sensitivity.mask_identifiers(text)
        self.assertNotIn("123456789", masked)
        self.assertIn("[ssn withheld]", masked)
        self.assertIn("SSN:", masked)

    def test_only_normal_is_permitted_remotely_and_unknown_is_not(self):
        self.assertTrue(sensitivity.permits_remote("normal"))
        for level in ("restricted", "local-only", "", None, "weird"):
            self.assertFalse(sensitivity.permits_remote(level))


# ============================================================= index + tools


class IndexAndDiagnosticsTests(SensitivityTestCase):
    def test_index_classifies_documents_and_reports_counts(self):
        self.build_index()
        status = self.index().status()
        self.assertEqual(status["by_sensitivity"], {"normal": 1, "restricted": 1, "local-only": 1})

        levels = Retriever(self.index().database_path).sensitivity([NORMAL_ID, SSN_ID, RESTRICTED_ID, "missing"])
        self.assertEqual(
            levels, {NORMAL_ID: "normal", SSN_ID: "local-only", RESTRICTED_ID: "restricted"}
        )

    def test_report_explains_classification_and_never_stores_values(self):
        self.build_index()
        (row,) = self.index().sensitivity_report(document_id=SSN_ID)
        self.assertEqual(row["sensitivity"], "local-only")
        self.assertEqual(row["basis"], "detected")
        self.assertEqual(
            sorted(finding["detector"] for finding in row["findings"]),
            ["bank-routing-labeled", "us-ssn"],
        )
        (restricted,) = self.index().sensitivity_report(document_id=RESTRICTED_ID)
        self.assertEqual(restricted["basis"], "override")
        self.assertEqual(restricted["override_reason"], "board only")

        listed = [item["document_id"] for item in self.index().sensitivity_report()]
        self.assertEqual(listed, [SSN_ID, RESTRICTED_ID])

        with sqlite3.connect(self.index().database_path) as connection:
            details = " ".join(value for (value,) in connection.execute("SELECT sensitivity_detail FROM documents"))
        self.assertNotIn(SSN, details)
        self.assertNotIn(ROUTING, details)

    def test_sensitivity_cli_explains_without_printing_values(self):
        self.build_index()
        show = self.run_cli(["sensitivity", "show", SSN_ID])
        self.assertEqual(show.exit_code, 0, show.output)
        self.assertIn("sensitivity: local-only", show.output)
        self.assertIn("US Social Security number", show.output)
        self.assertIn("never sent", show.output)

        listing = self.run_cli(["sensitivity", "list"])
        self.assertIn(SSN_ID, listing.output)
        self.assertIn(RESTRICTED_ID, listing.output)
        self.assertNotIn(NORMAL_ID, listing.output)

        status = self.run_cli(["sensitivity", "status", "--format", "json"])
        self.assertEqual(json.loads(status.output)["by_sensitivity"], {"normal": 1, "restricted": 1, "local-only": 1})

        index_status = self.run_cli(["index", "status"])
        self.assertIn("Sensitivity:", index_status.output)
        self.assertIn("local-only: 1", index_status.output)

        search = self.run_cli(["search", "social", "security"])
        self.assertIn(SSN_ID, search.output)
        self.assertIn("sensitivity: local-only", search.output)

        for result in (show, listing, status, index_status, search):
            self.assertNotIn(SSN, result.output)
            self.assertNotIn(ROUTING, result.output)

    def test_an_index_built_before_classification_fails_closed(self):
        self.build_index()
        with sqlite3.connect(self.index().database_path) as connection:
            connection.execute("ALTER TABLE documents DROP COLUMN sensitivity")
        with self.assertRaises(RetrievalError) as raised:
            Retriever(self.index().database_path).connect()
        self.assertIn("gang index build", str(raised.exception))

    def test_manual_override_survives_connector_regeneration(self):
        path = self.home / "vault/documents/board-memo.md"
        preserved = preserved_entity_frontmatter(path)
        self.assertEqual(preserved, {"sensitivity": "restricted", "sensitivity_reason": "board only"})

    def test_raw_and_canonical_documents_are_never_altered(self):
        before = {path: path.read_bytes() for path in self.home.rglob("*.md")}
        self.build_index()
        AskService(root_path=self.root, private_home=self.home).ask(
            QUESTION, options=AskOptions(use_ai=False, use_cache=False)
        )
        self.assertEqual(before, {path: path.read_bytes() for path in self.home.rglob("*.md")})


# ========================================================= remote safety


class RemoteProviderSafetyTests(SensitivityTestCase):
    """The regression: an SSN document never reaches a remote provider."""

    def test_one_shot_ask_never_sends_sensitive_evidence_to_a_remote_provider(self):
        self.build_index()
        fake = self.fake_anthropic()
        synthesizer = AnthropicAnswerSynthesizer(root_path=self.root, provider="anthropic", api_key="test-key")
        self.assertTrue(is_remote_provider(synthesizer))

        result = AskService(root_path=self.root, private_home=self.home, synthesizer=synthesizer).ask(
            QUESTION, options=AskOptions(use_cache=False)
        )

        # A remote call happened, over the ordinary document only.
        self.assertEqual(len(fake.requests), 1)
        sent = fake.sent_text()
        self.assertIn("restarted on September 10", sent)
        self.assertIn(NORMAL_ID, sent)
        self.assert_no_sensitive_material(sent)
        self.assertEqual(request_data(fake.requests[0])["withheld_sources"]["count"], 2)

        # Locally, provenance stays intact: every source is listed, and the
        # withheld ones are named as withheld.
        self.assertEqual(result["synthesis"]["mode"], "ai")
        self.assertEqual(
            sorted(item["document_id"] for item in result["synthesis"]["withheld_sources"]),
            sorted([SSN_ID, RESTRICTED_ID]),
        )
        levels = {source["document_id"]: source["sensitivity"] for source in result["sources"]}
        self.assertEqual(levels, {NORMAL_ID: "normal", SSN_ID: "local-only", RESTRICTED_ID: "restricted"})
        cited = {source["document_id"] for source in result["sources"] if source["cited"]}
        self.assertEqual(cited, {NORMAL_ID})

    def test_conversation_research_and_synthesis_never_see_sensitive_evidence(self):
        self.build_index()
        steps = [
            # An adversarial director asks to read the sensitive document by id.
            {"decision": "READ_DOCUMENT", "tool": "get_document", "arguments": {"document_id": SSN_ID}, "reason": "read"},
            {"decision": "ENOUGH_EVIDENCE", "reason": "enough"},
        ]

        def respond(kwargs):
            data = request_data(kwargs)
            if "decisions" in data:
                return steps.pop(0) if steps else {"decision": "ENOUGH_EVIDENCE"}
            return grounded_answer(kwargs)

        fake = self.fake_anthropic(respond)
        service = ConversationService(
            root_path=self.root,
            private_home=self.home,
            synthesizer=ConversationSynthesizer(root_path=self.root, provider="anthropic", api_key="test-key"),
            director=AnthropicResearchDirector(root_path=self.root, provider="anthropic", api_key="test-key"),
        )
        session = service.start()
        result = service.converse(
            SYNTHESIS_QUESTION, session=session, options=ConversationOptions(use_cache=False, persist=False)
        )

        purposes = [call.get("purpose") for call in result["provider_calls"]]
        self.assertIn("research-step", purposes)
        self.assertIn("synthesis", purposes)
        self.assertGreaterEqual(len(fake.requests), 3)
        sent = fake.sent_text()
        self.assertIn("restarted on September 10", sent)
        self.assert_no_sensitive_material(sent)
        self.assertEqual(
            sorted(item["document_id"] for item in result["synthesis"]["withheld_sources"]),
            sorted([SSN_ID, RESTRICTED_ID]),
        )

    def test_a_follow_up_turn_does_not_carry_a_sensitive_earlier_answer_to_a_remote_provider(self):
        self.build_index()
        fake = self.fake_anthropic()
        service = ConversationService(
            root_path=self.root,
            private_home=self.home,
            synthesizer=ConversationSynthesizer(root_path=self.root, provider="anthropic", api_key="test-key"),
        )
        session = service.start()
        # Turn one is local: it reads the SSN document and says so.
        local = service.converse(
            "Show me the payroll onboarding packet with the social security number",
            session=session,
            options=ConversationOptions(use_ai=False, use_cache=False, persist=False),
        )
        self.assertIn(SSN_TITLE, local["answer"])
        self.assertEqual(fake.requests, [])

        # Turn two goes remote; the earlier turn's summary must not.
        service.converse(
            SYNTHESIS_QUESTION, session=session, options=ConversationOptions(use_cache=False, persist=False)
        )
        self.assertEqual(len(fake.requests), 1)
        data = request_data(fake.requests[0])
        self.assertEqual(data["conversation_state"]["recent_turns"], [])
        self.assert_no_sensitive_material(fake.sent_text())

    def test_when_everything_is_sensitive_a_remote_provider_is_not_called(self):
        (self.home / "vault/documents/qi2-timeline.md").unlink()
        self.build_index()
        fake = self.fake_anthropic()
        synthesizer = AnthropicAnswerSynthesizer(root_path=self.root, provider="anthropic", api_key="test-key")

        result = AskService(root_path=self.root, private_home=self.home, synthesizer=synthesizer).ask(
            QUESTION, options=AskOptions(use_cache=False)
        )

        self.assertEqual(fake.requests, [])
        self.assertEqual(result["synthesis"]["mode"], "deterministic")
        self.assertEqual(result["synthesis"]["reason"], disclosure.SENSITIVE_EVIDENCE_REASON)
        self.assertIn(disclosure.SENSITIVE_EVIDENCE_NOTICE, result["answer"])
        # The local reader still gets the matching documents.
        self.assertIn(SSN_TITLE, result["answer"])

    def test_remote_enrichment_refuses_sensitive_documents_and_filters_context(self):
        self.build_index()
        fake = self.fake_anthropic(lambda kwargs: {"proposed_enrichment": {"summary": "Certification restarted."}})
        service = EnrichmentService(
            root_path=self.root,
            private_home=self.home,
            provider=AnthropicEnrichmentProvider(api_key="test-key"),
        )
        for document_id in (SSN_ID, RESTRICTED_ID):
            with self.subTest(document_id=document_id), self.assertRaises(SensitiveDocumentError):
                service.create_proposal(document_id)
        self.assertEqual(fake.requests, [])

        proposal = service.create_proposal(NORMAL_ID)
        self.assertEqual(len(fake.requests), 1)
        self.assertNotIn(SSN_ID, proposal["context_document_ids"])
        self.assert_no_sensitive_material(fake.sent_text())

    def test_remote_entity_proposals_refuse_sensitive_documents_and_deterministic_still_works(self):
        self.build_index()
        fake = self.fake_anthropic(lambda kwargs: {"proposed_mentions": [], "proposed_relationships": []})
        service = EntityProposalService(root_path=self.root, private_home=self.home)
        with self.assertRaises(EntitySensitiveDocumentError):
            service.create_proposal(SSN_ID, provider=AnthropicEntityProposer(api_key="test-key"))
        self.assertEqual(fake.requests, [])

        # The deterministic proposer resolves names in-process; nothing leaves.
        proposal = service.create_proposal(SSN_ID)
        self.assertEqual(proposal["provider"], "deterministic")

    def test_an_ollama_endpoint_on_another_host_is_remote(self):
        loopback = ConfiguredAIClient(
            role="synthesis", provider="ollama", config=AIConfig.from_mapping({"ollama": {"endpoint": "http://127.0.0.1:11434"}})
        )
        self.assertFalse(loopback.is_remote)
        mapped = ConfiguredAIClient(
            role="synthesis",
            provider="ollama",
            config=AIConfig.from_mapping({"ollama": {"endpoint": "http://[::ffff:127.0.0.1]:11434"}}),
        )
        self.assertFalse(mapped.is_remote)
        disguised = ConfiguredAIClient(
            role="synthesis",
            provider="ollama",
            config=AIConfig.from_mapping({"ollama": {"endpoint": "http://127.0.0.1.evil.example:11434"}}),
        )
        self.assertTrue(disguised.is_remote)
        lan = ConfiguredAIClient(
            role="synthesis", provider="ollama", config=AIConfig.from_mapping({"ollama": {"endpoint": "http://gpu.example:11434"}})
        )
        self.assertTrue(lan.is_remote)
        self.assertTrue(ConfiguredAIClient(role="synthesis", provider="anthropic", api_key="x").is_remote)
        # Anything that cannot say where it sends text is treated as remote.
        self.assertTrue(is_remote_provider(SimpleNamespace(provider_name="mystery")))
        self.assertFalse(is_remote_provider(SimpleNamespace(provider_name="ollama")))

    def test_the_egress_backstop_refuses_rather_than_redacts(self):
        fake = self.fake_anthropic()
        client = AnthropicClient(api_key="test-key")
        request = {
            "system": "Answer.",
            "messages": [{"role": "user", "content": json.dumps({"excerpt": f"Employee SSN {SSN}"})}],
            "max_tokens": 10,
        }
        with self.assertRaises(SensitiveEgressError) as raised:
            client.complete_json(request, purpose="test")
        self.assertEqual(fake.requests, [])
        self.assertNotIn(SSN, str(raised.exception))
        self.assertIn("us-ssn", str(raised.exception))


# ======================================================== ordinary + local


class OrdinaryAndLocalBehaviorTests(SensitivityTestCase):
    def test_ordinary_documents_reach_a_remote_provider_unchanged(self):
        for path in (self.home / "vault/documents").glob("*.md"):
            if path.name != "qi2-timeline.md":
                path.unlink()
        self.build_index()

        retriever = Retriever(self.index().database_path)
        plan = DeterministicPlanner(None).plan(QUESTION, PlanOverrides()).plan
        bundle = build_bundle(QUESTION, retriever.retrieve(plan), plan)
        # The remote view of an all-normal bundle is the bundle itself, so the
        # packet built from it is byte-for-byte what it always was.
        self.assertEqual(bundle.for_remote_provider(), bundle)
        self.assertNotIn("withheld_sources", bundle.to_dict())

        fake = self.fake_anthropic()
        synthesizer = AnthropicAnswerSynthesizer(root_path=self.root, provider="anthropic", api_key="test-key")
        result = AskService(root_path=self.root, private_home=self.home, synthesizer=synthesizer).ask(
            QUESTION, options=AskOptions(use_cache=False)
        )
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(
            fake.requests[0]["messages"], synthesizer.build_request(bundle)["messages"]
        )
        self.assertEqual(result["synthesis"]["withheld_sources"], [])
        self.assertEqual(result["synthesis"]["mode"], "ai")

    def test_deterministic_answers_still_use_local_only_evidence(self):
        self.build_index()
        result = AskService(root_path=self.root, private_home=self.home).ask(
            QUESTION, options=AskOptions(use_ai=False, use_cache=False)
        )
        self.assertIn(SSN_TITLE, result["answer"])
        self.assertIn(SSN_ID, [source["document_id"] for source in result["sources"]])
        self.assertNotIn("withheld_sources", result["synthesis"])
        # The excerpt shown as provenance keeps its words and loses the value.
        (excerpt,) = [item["excerpts"][0] for item in result["evidence"] if item["document_id"] == SSN_ID]
        self.assertIn("social security number: [ssn withheld]", excerpt)
        self.assertIn("routing number: [bank-account withheld]", excerpt)
        self.assertNotIn(SSN, json.dumps(result))
        self.assertNotIn(ROUTING, json.dumps(result))

    def test_a_loopback_local_model_sees_restricted_and_local_only_evidence(self):
        self.build_index()
        local = RecordingProvider(provider_name="ollama", is_remote=False)
        AskService(root_path=self.root, private_home=self.home, synthesizer=local).ask(
            QUESTION, options=AskOptions(use_cache=False)
        )
        (bundle,) = local.contexts
        self.assertEqual(
            sorted(item.document_id for item in bundle.items), sorted([NORMAL_ID, SSN_ID, RESTRICTED_ID])
        )

    def test_a_fact_from_a_local_only_document_still_answers_deterministically(self):
        entities = EntityService(root_path=self.root, private_home=self.home)
        entities.create("company", "GANG", domains=["gang.example"])
        entities.create("person", "Daniel Hirunrusme", aliases=["Daniel"], emails=["daniel@gang.example"])
        write_markdown(
            self.home / "vault/documents/offer-letter.md",
            {"id": DOWNGRADED_ID, "type": "knowledge", "source_type": "gmail-attachment",
             "title": "Offer letter", "visibility": "private", "status": "active",
             "created": "2026-03-01", "updated": "2026-03-01"},
            f"Daniel Hirunrusme is a co-founder of GANG.\n\nEmployee SSN: {SSN}\n",
        )
        self.build_index()
        remote = RecordingProvider(provider_name="anthropic", is_remote=True)
        service = ConversationService(root_path=self.root, private_home=self.home, synthesizer=remote)

        result = service.converse(
            "who is Daniel?", session=service.start(),
            options=ConversationOptions(use_cache=False, persist=False),
        )

        # Answered from the generated fact, cited to the local-only document,
        # without a model call and without the identifier in the answer.
        self.assertTrue(result["answer"].startswith("Daniel Hirunrusme is a co-founder of GANG."), result["answer"])
        self.assertEqual(result["synthesis"]["mode"], "deterministic")
        self.assertIn(DOWNGRADED_ID, [source["document_id"] for source in result["sources"]])
        self.assertEqual(remote.contexts, [])
        self.assertEqual(result["provider_calls"], [])
        self.assertNotIn(SSN, json.dumps(result, default=str))

    def test_a_manual_override_to_normal_releases_a_false_positive(self):
        write_markdown(
            self.home / "vault/documents/part-numbers.md",
            {"id": DOWNGRADED_ID, "type": "knowledge", "title": "Qi2 certification part list",
             "visibility": "private", "sensitivity": "normal",
             "sensitivity_reason": "part number, not an SSN"},
            "Qi2 certification fixture part 222-33-4444 is on order.\n",
        )
        self.build_index()
        (row,) = self.index().sensitivity_report(document_id=DOWNGRADED_ID)
        self.assertEqual((row["sensitivity"], row["detected_level"]), ("normal", "local-only"))


# =========================================================== structure scrub


class RemoteDataScrubTests(unittest.TestCase):
    def lookup(self, ids):
        return {value: ("normal" if value.startswith("ok") else "local-only") for value in ids if value != "missing"}

    def test_facts_keep_provenance_locally_but_not_their_sensitive_quote_remotely(self):
        records = {
            "evidence_facts": [
                {
                    "kind": "evidence-facts",
                    "entity_id": "person_1",
                    "statements": [
                        {"text": "Frank is a co-founder.", "document_ids": ["ok-1"], "quote": "co-founder"},
                        {"text": "Frank is paid.", "document_ids": ["secret-1"], "quote": f"SSN {SSN}"},
                        {"text": "Mixed.", "document_ids": ["ok-1", "secret-1"], "quote": "mixed"},
                    ],
                }
            ],
            "decisions": [
                {"document_id": "secret-1", "text": "Pay the bonus."},
                {"document_id": "ok-2", "text": "Ship it."},
            ],
            "timeline": {"items": [{"document_id": "missing", "excerpt": "unknown source"}], "rule": "r"},
        }
        scrubbed = disclosure.remote_data(records, self.lookup)
        statements = scrubbed["evidence_facts"][0]["statements"]
        self.assertEqual([item["text"] for item in statements], ["Frank is a co-founder."])
        self.assertEqual([item["text"] for item in scrubbed["decisions"]], ["Ship it."])
        # An id the index does not know is treated as withheld.
        self.assertEqual(scrubbed["timeline"]["items"], [])
        self.assertNotIn(SSN, json.dumps(scrubbed))
        # The original, local structure is untouched.
        self.assertEqual(len(records["evidence_facts"][0]["statements"]), 3)

    def test_pointer_lists_lose_withheld_ids_and_keep_the_rest(self):
        session = {
            "active_document_ids": ["ok-1", "secret-1"],
            "recent_turns": [
                {"question": "q1", "previous_answer_summary": "safe", "document_ids": ["ok-1"]},
                {"question": "q2", "previous_answer_summary": f"SSN {SSN}", "document_ids": ["secret-1"]},
            ],
        }
        scrubbed = disclosure.remote_data(session, self.lookup)
        self.assertEqual(scrubbed["active_document_ids"], ["ok-1"])
        self.assertEqual([turn["question"] for turn in scrubbed["recent_turns"]], ["q1"])

    def test_nothing_sensitive_means_the_value_is_returned_as_is(self):
        value = {"documents_so_far": [{"document_id": "ok-1", "excerpt": "fine"}]}
        self.assertIs(disclosure.remote_data(value, self.lookup), value)


if __name__ == "__main__":
    unittest.main()
