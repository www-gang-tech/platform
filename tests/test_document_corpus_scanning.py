"""Corpus-wide document scanning must survive a single malformed file.

A real imported email had an unterminated YAML quoted scalar in its
frontmatter. Before this hardening, that aborted any corpus-wide reader
(``entity candidates``, ``entity backfill``) outright. These tests pin the
hardened contract at the shared ``EntityDocumentStore`` boundary: skip and
report the malformed document, keep scanning everything else, never touch the
broken file, and never swallow the error when it is asked for directly.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from click.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

import cli as gang_cli
from core.entities import EntityService, MarkdownParseError

MALFORMED_ID = "01a0ca8d-ebc5-7204-ab22-ae6739b306f3"
VALID_ID = "01a0ca8d-ebc5-7204-ab22-ae6739b306f4"

# Mirrors the real bug: an unterminated single-quoted scalar inside a
# relationship excerpt. The rest of the frontmatter is otherwise valid.
MALFORMED_TEXT = (
    "---\n"
    f"id: {MALFORMED_ID}\n"
    "type: knowledge\n"
    "source_type: gmail-thread\n"
    "title: Broken\n"
    "visibility: private\n"
    "status: active\n"
    "content_trust: untrusted\n"
    "source_id: gmail-thread_broken\n"
    "gmail:\n"
    "  participants:\n"
    "    - daniel@gang.tech\n"
    "entity_relationships:\n"
    "  - excerpt: 'unterminated quoted scalar that never closes\n"
    "---\n\n"
    "Daniel Hirunrusme wrote this email.\n"
)


def write_markdown(path, frontmatter, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n" + body,
        encoding="utf-8",
    )


class CorpusScanHardeningTests(unittest.TestCase):
    def setUp(self):
        self._temp = TemporaryDirectory()
        self.root = Path(self._temp.name) / "repo"
        self.home = Path(self._temp.name) / "gang-home"
        (self.root / "brain/vault/public/posts").mkdir(parents=True)
        self.addCleanup(self._temp.cleanup)

        # Filename follows the real ingestion convention ({document_id}-{slug}.md)
        # so the malformed document's identity can be recovered from its path
        # even though its frontmatter cannot be parsed.
        self.malformed_path = self.home / "vault/emails" / f"{MALFORMED_ID}-broken-thread.md"
        self.malformed_path.parent.mkdir(parents=True, exist_ok=True)
        self.malformed_path.write_text(MALFORMED_TEXT, encoding="utf-8")
        self.malformed_raw_before = self.malformed_path.read_text(encoding="utf-8")

        self.valid_path = self.home / "vault/emails/valid-thread.md"
        write_markdown(
            self.valid_path,
            {
                "id": VALID_ID,
                "type": "knowledge",
                "source_type": "gmail-thread",
                "title": "Valid",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "gmail-thread_valid",
                "gmail": {"participants": ["daniel@gang.tech"]},
            },
            "# Thread\n\nDaniel Hirunrusme confirmed the timeline.\n",
        )

    def service(self):
        return EntityService(root_path=self.root, private_home=self.home)

    def run_cli(self, args):
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path("gang.config.yml").write_text("build: {}\n", encoding="utf-8")
            return runner.invoke(
                gang_cli.cli, args, env={"GANG_HOME": str(self.home)}, catch_exceptions=False
            )


class SharedBoundaryTests(CorpusScanHardeningTests):
    def test_iter_documents_skips_malformed_and_keeps_scanning(self):
        service = self.service()
        found_ids = {document.document_id for document in service.documents.iter_documents()}

        self.assertIn(VALID_ID, found_ids)
        self.assertNotIn(MALFORMED_ID, found_ids)

    def test_malformed_document_is_recorded_with_id_and_parse_error(self):
        service = self.service()
        list(service.documents.iter_documents())

        malformed = service.documents.malformed_documents
        self.assertEqual(len(malformed), 1)
        self.assertEqual(malformed[0].document_id, MALFORMED_ID)
        self.assertEqual(malformed[0].path.resolve(), self.malformed_path.resolve())
        self.assertIn("quoted scalar", malformed[0].error)

    def test_malformed_document_is_never_mutated_by_a_scan(self):
        service = self.service()
        list(service.documents.iter_documents())
        self.assertEqual(self.malformed_path.read_text(encoding="utf-8"), self.malformed_raw_before)

    def test_load_raises_for_the_malformed_document_itself(self):
        service = self.service()
        with self.assertRaises(MarkdownParseError):
            service.documents.load(MALFORMED_ID)
        # Direct access must not rewrite or repair the file either.
        self.assertEqual(self.malformed_path.read_text(encoding="utf-8"), self.malformed_raw_before)

    def test_load_still_resolves_a_valid_document_despite_unrelated_corruption(self):
        service = self.service()
        document = service.documents.load(VALID_ID)
        self.assertEqual(document.document_id, VALID_ID)


class EntityBackfillHardeningTests(CorpusScanHardeningTests):
    def test_backfill_all_apply_completes_and_reports_malformed_document(self):
        service = self.service()
        daniel = service.create("person", "Daniel Hirunrusme", emails=["daniel@gang.tech"])

        reports = service.backfill(None, apply=True)
        report = reports[daniel.id]

        # The valid document still gets linked; the run does not abort.
        self.assertEqual(report["new_mentions"], 1)
        self.assertIn("entity_refs", yaml.safe_load(
            self.valid_path.read_text(encoding="utf-8").split("---", 2)[1]
        ))

        self.assertEqual(report["malformed_documents_skipped"], 1)
        malformed_ids = {item["document_id"] for item in report["malformed_documents"]}
        self.assertIn(MALFORMED_ID, malformed_ids)
        self.assertTrue(any("quoted scalar" in item["error"] for item in report["malformed_documents"]))

        # No AI, no repair: the broken file is byte-for-byte unchanged.
        self.assertEqual(self.malformed_path.read_text(encoding="utf-8"), self.malformed_raw_before)

    def test_cli_entity_backfill_all_apply_does_not_abort_and_reports_malformed(self):
        service = self.service()
        service.create("person", "Daniel Hirunrusme", emails=["daniel@gang.tech"])

        result = self.run_cli(["entity", "backfill", "--all", "--apply", "--verbose"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("malformed documents skipped: 1", result.output)
        self.assertIn(MALFORMED_ID, result.output)
        self.assertIn("YAML parse error:", result.output)
        self.assertIn("new mentions: 1", result.output)
        self.assertEqual(self.malformed_path.read_text(encoding="utf-8"), self.malformed_raw_before)


class EntityCandidatesHardeningTests(CorpusScanHardeningTests):
    def test_candidates_completes_and_reports_malformed_document(self):
        service = self.service()
        report = service.candidates()

        self.assertEqual(report["summary"]["malformed_documents_skipped"], 1)
        malformed_ids = {item["document_id"] for item in report["malformed_documents"]}
        self.assertIn(MALFORMED_ID, malformed_ids)
        self.assertEqual(self.malformed_path.read_text(encoding="utf-8"), self.malformed_raw_before)

    def test_cli_entity_candidates_does_not_abort_and_reports_malformed(self):
        result = self.run_cli(["entity", "candidates", "--verbose"])
        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("malformed documents skipped: 1", result.output)
        self.assertIn(MALFORMED_ID, result.output)
        self.assertIn("YAML parse error:", result.output)


class ValidCorpusUnaffectedTests(unittest.TestCase):
    """A corpus with no malformed documents behaves exactly as before."""

    def setUp(self):
        self._temp = TemporaryDirectory()
        self.root = Path(self._temp.name) / "repo"
        self.home = Path(self._temp.name) / "gang-home"
        (self.root / "brain/vault/public/posts").mkdir(parents=True)
        self.addCleanup(self._temp.cleanup)

        self.valid_path = self.home / "vault/emails/valid-thread.md"
        write_markdown(
            self.valid_path,
            {
                "id": VALID_ID,
                "type": "knowledge",
                "source_type": "gmail-thread",
                "title": "Valid",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "gmail-thread_valid",
                "gmail": {"participants": ["daniel@gang.tech"]},
            },
            "# Thread\n\nDaniel Hirunrusme confirmed the timeline.\n",
        )

    def service(self):
        return EntityService(root_path=self.root, private_home=self.home)

    def test_backfill_reports_zero_malformed_documents(self):
        service = self.service()
        daniel = service.create("person", "Daniel Hirunrusme", emails=["daniel@gang.tech"])
        report = service.backfill(daniel.id, apply=True)[daniel.id]
        self.assertEqual(report["new_mentions"], 1)
        self.assertEqual(report["malformed_documents_skipped"], 0)
        self.assertEqual(report["malformed_documents"], [])

    def test_candidates_reports_zero_malformed_documents(self):
        service = self.service()
        report = service.candidates()
        self.assertEqual(report["summary"]["malformed_documents_skipped"], 0)
        self.assertEqual(report["malformed_documents"], [])


if __name__ == "__main__":
    unittest.main()
