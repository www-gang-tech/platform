"""Deterministic entity-link backfill.

Canonical entities created after documents were already ingested end up with
zero mention edges even when the corpus has strong evidence about them,
because nothing ever re-scans old documents once the entity exists. These
tests cover the deterministic linker that closes that gap, plus the
regression case it exists for: verified participant email/domain and exact
canonical name auto-link; aliases are reported as candidates only.
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
from core.entities import EntityService, EntityValidationError


def write_markdown(path, frontmatter, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n" + body,
        encoding="utf-8",
    )


def read_frontmatter(path):
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])


class BackfillTestCase(unittest.TestCase):
    def setUp(self):
        self._temp = TemporaryDirectory()
        self.root = Path(self._temp.name) / "repo"
        self.home = Path(self._temp.name) / "gang-home"
        (self.root / "brain/vault/public/posts").mkdir(parents=True)
        self.addCleanup(self._temp.cleanup)

    def service(self):
        return EntityService(root_path=self.root, private_home=self.home)

    def write_gmail_thread(self, relative_path, *, document_id, participants, body):
        path = self.home / "vault/emails" / relative_path
        write_markdown(
            path,
            {
                "id": document_id,
                "type": "email-thread",
                "source_type": "gmail-thread",
                "title": "Thread",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "people": [],
                "companies": [],
                "projects": [],
                "source_id": f"gmail-thread_{document_id}",
                "source_ids": [f"gmail-thread_{document_id}"],
                "gmail": {"participants": participants},
            },
            body,
        )
        return path

    def run_cli(self, args):
        return CliRunner().invoke(
            gang_cli.cli, args, env={"GANG_HOME": str(self.home)}, catch_exceptions=False
        )


class VerifiedEmailAndIdempotencyTests(BackfillTestCase):
    def test_backfill_links_document_that_predates_the_entity(self):
        # The document is ingested first, exactly like the reported bug: a
        # canonical entity created later has zero mention edges even though
        # the corpus already has strong evidence about it.
        doc_path = self.write_gmail_thread(
            "thread1.md",
            document_id="doc-1",
            participants=["Daniel Hirunrusme <daniel@gang.tech>", "someone@example.com"],
            body="# Thread\n\n- From: Daniel Hirunrusme <daniel@gang.tech>\n\nBody text.\n",
        )

        service = self.service()
        daniel = service.create(
            "person", "Daniel Hirunrusme", aliases=["Dan", "Daniel"], emails=["daniel@gang.tech"]
        )

        dry_run = service.backfill(daniel.id, apply=False)[daniel.id]
        self.assertEqual(dry_run["scanned"], 1)
        self.assertEqual(dry_run["high_confidence"], 1)
        self.assertEqual(dry_run["new_mentions"], 1)
        self.assertEqual(dry_run["already_linked"], 0)
        self.assertEqual(dry_run["matches"][0]["reason"], "verified-email")
        # Dry run must not touch the document at all.
        self.assertNotIn("entity_refs", read_frontmatter(doc_path))

        applied = service.backfill(daniel.id, apply=True)[daniel.id]
        self.assertEqual(applied["new_mentions"], 1)
        refs = read_frontmatter(doc_path)["entity_refs"]
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["entity_id"], daniel.id)

        # Running --apply again must be a no-op: zero new links, no duplicates.
        second = service.backfill(daniel.id, apply=True)[daniel.id]
        self.assertEqual(second["new_mentions"], 0)
        self.assertEqual(second["already_linked"], 1)
        refs_after = read_frontmatter(doc_path)["entity_refs"]
        self.assertEqual(len(refs_after), 1)

    def test_backfill_matches_structured_ingestion_envelope_participants(self):
        # The generic (non-Gmail) ingestion path stores participants under
        # ingestion_envelope rather than gmail. Both surfaces must work.
        doc_path = self.home / "vault/inbox/doc-2.md"
        write_markdown(
            doc_path,
            {
                "id": "doc-2",
                "type": "knowledge",
                "source_type": "file",
                "title": "Note",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "file_abc",
                "ingestion_envelope": {"participants": ["daniel@gang.tech"]},
            },
            "Some unrelated body text.\n",
        )

        service = self.service()
        daniel = service.create("person", "Daniel Hirunrusme", emails=["daniel@gang.tech"])
        report = service.backfill(daniel.id, apply=True)[daniel.id]
        self.assertEqual(report["new_mentions"], 1)
        self.assertEqual(read_frontmatter(doc_path)["entity_refs"][0]["label"], "daniel@gang.tech")


class CanonicalNameAndAliasTests(BackfillTestCase):
    def test_exact_canonical_name_links_but_alias_is_candidate_only(self):
        exact_path = self.home / "vault/inbox/exact.md"
        write_markdown(
            exact_path,
            {
                "id": "exact-doc",
                "type": "knowledge",
                "source_type": "file",
                "title": "Exact",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "file_exact",
            },
            "Daniel Hirunrusme reviewed the packaging update.\n",
        )
        alias_path = self.home / "vault/inbox/alias.md"
        write_markdown(
            alias_path,
            {
                "id": "alias-doc",
                "type": "knowledge",
                "source_type": "file",
                "title": "Alias only",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "file_alias",
            },
            "Dan said the timeline looks good.\n",
        )

        service = self.service()
        daniel = service.create(
            "person", "Daniel Hirunrusme", aliases=["Dan", "Daniel"], emails=["daniel@gang.tech"]
        )
        report = service.backfill(daniel.id, apply=True)[daniel.id]

        self.assertEqual(report["new_mentions"], 1)
        self.assertEqual(report["ambiguous_skipped"], 1)
        self.assertEqual(report["matches"][0]["reason"], "canonical-name")
        self.assertEqual(report["candidates"][0]["alias"], "Dan")

        self.assertIn("entity_refs", read_frontmatter(exact_path))
        # An alias hit must never be auto-linked, no matter how unique it looks.
        self.assertNotIn("entity_refs", read_frontmatter(alias_path))


class CompanyDomainTests(BackfillTestCase):
    def test_company_links_on_verified_email_domain_and_exact_name(self):
        domain_path = self.write_gmail_thread(
            "domain.md",
            document_id="domain-doc",
            participants=["Frank <frank@eliro.com>"],
            body="# Thread\n\nCertification update.\n",
        )
        name_path = self.home / "vault/inbox/name.md"
        write_markdown(
            name_path,
            {
                "id": "name-doc",
                "type": "knowledge",
                "source_type": "file",
                "title": "Name",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "file_name",
            },
            "Eliro will handle the submission.\n",
        )

        service = self.service()
        eliro = service.create("company", "Eliro", domains=["eliro.com"])
        report = service.backfill(eliro.id, apply=True)[eliro.id]

        self.assertEqual(report["new_mentions"], 2)
        reasons = {match["document_id"]: match["reason"] for match in report["matches"]}
        self.assertEqual(reasons["domain-doc"], "verified-domain")
        self.assertEqual(reasons["name-doc"], "canonical-name")
        self.assertIn("entity_refs", read_frontmatter(domain_path))
        self.assertIn("entity_refs", read_frontmatter(name_path))


class PublicAndAddressTests(BackfillTestCase):
    def test_public_documents_are_skipped_instead_of_aborting_the_pass(self):
        private_path = self.home / "vault/inbox/private.md"
        write_markdown(
            private_path,
            {
                "id": "private-doc",
                "type": "knowledge",
                "source_type": "file",
                "title": "Private",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "file_private",
            },
            "Daniel Hirunrusme reviewed the draft.\n",
        )
        public_path = self.root / "brain/vault/public/posts/about-daniel.md"
        write_markdown(
            public_path,
            {
                "id": "public-doc",
                "type": "post",
                "title": "About",
                "visibility": "public",
                "status": "published",
            },
            "Daniel Hirunrusme founded the studio.\n",
        )
        # Visibility defaults to private when the field is omitted, which used
        # to look writable until the public-vault path check raised mid-pass.
        unmarked_path = self.root / "brain/vault/public/posts/unmarked.md"
        write_markdown(
            unmarked_path,
            {
                "id": "unmarked-doc",
                "type": "post",
                "title": "Unmarked",
                "status": "published",
            },
            "Daniel Hirunrusme is mentioned here too.\n",
        )

        service = self.service()
        daniel = service.create("person", "Daniel Hirunrusme")
        report = service.backfill(daniel.id, apply=True)[daniel.id]

        self.assertEqual(report["scanned"], 1)
        self.assertEqual(report["new_mentions"], 1)
        self.assertIn("entity_refs", read_frontmatter(private_path))
        self.assertNotIn("entity_refs", read_frontmatter(public_path))
        self.assertNotIn("entity_refs", read_frontmatter(unmarked_path))

    def test_canonical_name_does_not_match_inside_an_email_or_domain(self):
        email_path = self.home / "vault/inbox/emailish.md"
        write_markdown(
            email_path,
            {
                "id": "emailish-doc",
                "type": "knowledge",
                "source_type": "file",
                "title": "Address",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "file_emailish",
            },
            "Ping dan@example.com when the file is ready.\n",
        )
        domain_path = self.home / "vault/inbox/domainish.md"
        write_markdown(
            domain_path,
            {
                "id": "domainish-doc",
                "type": "knowledge",
                "source_type": "file",
                "title": "Domain",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "file_domainish",
            },
            "The notes are on gang.tech for now.\n",
        )
        prose_path = self.home / "vault/inbox/prose.md"
        write_markdown(
            prose_path,
            {
                "id": "prose-doc",
                "type": "knowledge",
                "source_type": "file",
                "title": "Prose",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "file_prose",
            },
            "Dan will send the file. Gang will file the form.\n",
        )

        service = self.service()
        dan = service.create("person", "Dan")
        gang = service.create("company", "Gang")
        reports = service.backfill(None, apply=True)

        self.assertEqual(reports[dan.id]["new_mentions"], 1)
        self.assertEqual(reports[dan.id]["matches"][0]["document_id"], "prose-doc")
        self.assertEqual(reports[gang.id]["new_mentions"], 1)
        self.assertEqual(reports[gang.id]["matches"][0]["document_id"], "prose-doc")
        self.assertNotIn("entity_refs", read_frontmatter(email_path))
        self.assertNotIn("entity_refs", read_frontmatter(domain_path))
        self.assertEqual(len(read_frontmatter(prose_path)["entity_refs"]), 2)


class ScopeTests(BackfillTestCase):
    def test_backfill_rejects_unsupported_entity_types(self):
        service = self.service()
        project = service.create("project", "GANG")
        with self.assertRaises(EntityValidationError):
            service.backfill(project.id, apply=False)

    def test_backfill_all_only_considers_person_and_company(self):
        write_markdown(
            self.home / "vault/inbox/mixed.md",
            {
                "id": "mixed-doc",
                "type": "knowledge",
                "source_type": "file",
                "title": "Mixed",
                "visibility": "private",
                "status": "active",
                "content_trust": "untrusted",
                "source_id": "file_mixed",
            },
            "Frank Godchaux and Eliro are working on the GANG project.\n",
        )

        service = self.service()
        frank = service.create("person", "Frank Godchaux")
        eliro = service.create("company", "Eliro")
        gang = service.create("project", "GANG")

        reports = service.backfill(None, apply=False)
        self.assertIn(frank.id, reports)
        self.assertIn(eliro.id, reports)
        self.assertNotIn(gang.id, reports)


class CLITests(BackfillTestCase):
    def test_cli_backfill_is_dry_run_by_default_then_apply(self):
        doc_path = self.write_gmail_thread(
            "cli-thread.md",
            document_id="cli-doc",
            participants=["Daniel Hirunrusme <daniel@gang.tech>"],
            body="# Thread\n\nBody.\n",
        )
        service = self.service()
        daniel = service.create("person", "Daniel Hirunrusme", emails=["daniel@gang.tech"])

        dry_run = self.run_cli(["entity", "backfill", daniel.id])
        self.assertEqual(dry_run.exit_code, 0, dry_run.output)
        self.assertIn("new mentions: 1", dry_run.output)
        self.assertIn("Dry run only", dry_run.output)
        self.assertNotIn("entity_refs", read_frontmatter(doc_path))

        applied = self.run_cli(["entity", "backfill", daniel.id, "--apply"])
        self.assertEqual(applied.exit_code, 0, applied.output)
        self.assertIn("new mentions: 1", applied.output)
        self.assertIn("entity_refs", read_frontmatter(doc_path))

    def test_cli_requires_exactly_one_of_entity_id_or_all(self):
        result = self.run_cli(["entity", "backfill"])
        self.assertNotEqual(result.exit_code, 0)


class FutureIngestionTests(BackfillTestCase):
    def test_ingest_file_auto_links_a_known_entity_by_canonical_name(self):
        service = self.service()
        daniel = service.create("person", "Daniel Hirunrusme", emails=["daniel@gang.tech"])

        runner = CliRunner()
        with runner.isolated_filesystem():
            Path("gang.config.yml").write_text("build: {}\n", encoding="utf-8")
            note = Path("note.txt")
            note.write_text("Daniel Hirunrusme reviewed the packaging update today.\n", encoding="utf-8")

            env = {"GANG_HOME": str(self.home)}
            result = runner.invoke(gang_cli.cli, ["ingest", "file", str(note)], env=env)
            self.assertEqual(result.exit_code, 0, result.output)

        view = service.show(daniel.id)
        self.assertEqual(view["provenance"]["mentions"], 1)


if __name__ == "__main__":
    unittest.main()
