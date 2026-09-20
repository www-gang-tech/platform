import json
import os
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli" / "gang"))

from core.brain_home import BrainHome
from core.paths import GangPaths
from core.private_index import PrivateKnowledgeIndex


def write_markdown(path, frontmatter, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n" + body, encoding="utf-8")


class BrainHomeTests(unittest.TestCase):
    def test_path_resolver_uses_configured_home_or_default(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            configured = root / "custom-home"
            with patch.dict(os.environ, {"GANG_HOME": str(configured)}):
                paths = GangPaths.from_env(repo_root=root / "repo")

            self.assertEqual(paths.home, configured.resolve())
            self.assertEqual(paths.private_vault, configured.resolve() / "vault")
            self.assertEqual(paths.repo_public_vault, (root / "repo/brain/vault/public").resolve())

        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(GangPaths.from_env().home, (Path.home() / ".gang").resolve())

    def test_status_counts_private_public_raw_and_gmail_without_content(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            home = root / "gang-home"
            write_markdown(home / "vault/emails/email.md", {"id": "email-1", "type": "email-thread"}, "Private body")
            write_markdown(root / "brain/vault/public/pages/page.md", {"id": "public-1", "type": "page"}, "Public body")
            raw_meta = home / "raw/gmail-thread/source/v000001/metadata.json"
            raw_meta.parent.mkdir(parents=True, exist_ok=True)
            raw_meta.write_text("{}", encoding="utf-8")
            registry = home / "ingestion/registry.json"
            registry.parent.mkdir(parents=True, exist_ok=True)
            registry.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "sources": {
                            "gmail-thread_x": {
                                "source_type": "gmail-thread",
                                "document_id": "email-1",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            status = BrainHome(repo_root=root, private_home=home).status()

            self.assertEqual(status["private_documents"], 1)
            self.assertEqual(status["repository_public_documents"], 1)
            self.assertEqual(status["raw_sources"], 1)
            self.assertEqual(status["gmail_threads"], 1)

    def test_migration_dry_run_apply_idempotency_and_registry_rewrite(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "workspace-a"
            home = root / "gang-home"
            write_markdown(source / "brain/vault/meetings/meeting.md", {"id": "meeting-1"}, "Stable private note")
            raw = source / "brain/raw/meeting/source/v000001/payload.txt"
            raw.parent.mkdir(parents=True, exist_ok=True)
            raw.write_text("raw evidence", encoding="utf-8")
            registry = source / "brain/vault/.ingestion/registry.json"
            registry.parent.mkdir(parents=True, exist_ok=True)
            registry.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "sources": {
                            "source-1": {
                                "document_id": "meeting-1",
                                "document_path": "brain/vault/meetings/meeting.md",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            brain = BrainHome(repo_root=root / "workspace-b", private_home=home)
            dry_run = brain.migrate(source_root=source)

            self.assertFalse(dry_run["applied"])
            self.assertEqual(len(dry_run["will_copy"]), 3)
            self.assertFalse((home / "vault/meetings/meeting.md").exists())

            applied = brain.migrate(source_root=source, apply=True)
            self.assertTrue(applied["applied"])
            self.assertTrue((home / "vault/meetings/meeting.md").exists())
            self.assertTrue((home / "raw/meeting/source/v000001/payload.txt").exists())
            migrated_registry = json.loads((home / "ingestion/registry.json").read_text(encoding="utf-8"))
            self.assertEqual(migrated_registry["sources"]["source-1"]["document_path"], "vault/meetings/meeting.md")

            rerun = brain.migrate(source_root=source, apply=True)
            self.assertEqual(len(rerun["will_copy"]), 0)
            self.assertEqual(len(rerun["unchanged"]), 3)

    def test_migration_detects_collisions_without_overwrite(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            source = root / "workspace-a"
            home = root / "gang-home"
            write_markdown(source / "brain/vault/inbox/conflict.md", {"id": "doc-1"}, "source")
            write_markdown(home / "vault/inbox/conflict.md", {"id": "doc-1"}, "different destination")

            result = BrainHome(repo_root=root / "workspace-b", private_home=home).migrate(source_root=source, apply=True)

            self.assertFalse(result["applied"])
            self.assertEqual(len(result["conflicts"]), 1)
            self.assertIn("different destination", (home / "vault/inbox/conflict.md").read_text(encoding="utf-8"))

    def test_two_worktrees_share_same_private_corpus(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            home = root / "gang-home"
            workspace_a = root / "workspace-a"
            workspace_b = root / "workspace-b"
            write_markdown(
                home / "vault/emails/shared.md",
                {"id": "shared-email", "type": "email-thread", "visibility": "private", "status": "active"},
                "Distinctive zircon relay phrase.",
            )
            write_markdown(
                workspace_b / "brain/vault/public/pages/public.md",
                {"id": "public-page", "type": "page", "visibility": "public", "status": "published"},
                "Public-only content.",
            )

            PrivateKnowledgeIndex(root_path=workspace_a, private_home=home).build()
            index_b = PrivateKnowledgeIndex(root_path=workspace_b, private_home=home)
            index_b.build()
            results = index_b.search("distinctive zircon relay")

            self.assertEqual([item["document_id"] for item in results], ["shared-email"])


if __name__ == "__main__":
    unittest.main()
