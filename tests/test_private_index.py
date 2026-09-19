import json
import sqlite3
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli" / "gang"))

import cli as gang_cli
from core.private_index import PrivateKnowledgeIndex


def write_markdown(path, frontmatter, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n"
        + "\n".join(f"{key}: {value}" for key, value in frontmatter.items())
        + "\n---\n\n"
        + body,
        encoding="utf-8",
    )


class PrivateIndexTests(unittest.TestCase):
    def test_build_indexes_public_and_private_vault_markdown_only(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            write_markdown(
                root / "brain/vault/public/pages/public.md",
                {
                    "id": "public-doc",
                    "type": "page",
                    "title": "Public Page",
                    "created": "'2026-01-01'",
                    "updated": "'2026-01-02'",
                    "visibility": "public",
                    "status": "published",
                },
                "Public canonical knowledge about ceramic mounting hardware.",
            )
            write_markdown(
                root / "brain/vault/meetings/private.md",
                {
                    "id": "private-doc",
                    "type": "knowledge",
                    "title": "Private Meeting",
                    "created_at": "'2026-01-03T00:00:00+00:00'",
                    "updated_at": "'2026-01-04T00:00:00+00:00'",
                    "visibility": "private",
                    "status": "active",
                    "source_id": "meeting_source_1",
                },
                "The ceramic mounting plate thermal test passed.",
            )
            write_markdown(
                root / "brain/vault/.ingestion/ignored.md",
                {"id": "ignored", "title": "Ignored", "visibility": "private"},
                "This generated ingestion state must not be indexed.",
            )
            write_markdown(
                root / "content/legacy.md",
                {"id": "legacy", "title": "Legacy"},
                "Legacy content must not be indexed.",
            )

            index = PrivateKnowledgeIndex(root_path=root)
            result = index.build()
            self.assertEqual(result.documents, 2)

            private_results = index.search("ceramic mounting plate", visibility="private")
            self.assertEqual([item["document_id"] for item in private_results], ["private-doc"])
            self.assertEqual(private_results[0]["source_ids"], ["meeting_source_1"])
            self.assertNotIn(str(root), json.dumps(private_results))

            public_results = index.search("Public canonical", visibility="public")
            self.assertEqual([item["document_id"] for item in public_results], ["public-doc"])
            self.assertEqual(index.status()["by_visibility"], {"private": 1, "public": 1})

    def test_rebuild_updates_changed_documents_and_removes_deleted_documents(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            doc_path = root / "brain/vault/meetings/private.md"
            write_markdown(
                doc_path,
                {
                    "id": "private-doc",
                    "type": "knowledge",
                    "title": "Private Meeting",
                    "updated_at": "'2026-01-04T00:00:00+00:00'",
                    "visibility": "private",
                    "status": "active",
                    "source_id": "meeting_source_1",
                },
                "The ceramic mounting plate thermal test passed.",
            )

            index = PrivateKnowledgeIndex(root_path=root)
            index.build()
            index.build()
            self.assertEqual(index.status()["documents"], 1)
            self.assertEqual(len(index.search("ceramic mounting plate")), 1)

            write_markdown(
                doc_path,
                {
                    "id": "private-doc",
                    "type": "knowledge",
                    "title": "Private Meeting",
                    "updated_at": "'2026-01-05T00:00:00+00:00'",
                    "visibility": "private",
                    "status": "active",
                    "source_id": "meeting_source_1",
                },
                "Distinctive boron clamp phrase replaced the old wording.",
            )
            index.build()
            results = index.search("distinctive boron clamp")
            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["document_id"], "private-doc")
            self.assertEqual(results[0]["updated"], "2026-01-05T00:00:00+00:00")
            self.assertEqual(index.search("ceramic mounting plate"), [])

            doc_path.unlink()
            index.build()
            self.assertEqual(index.status()["documents"], 0)
            self.assertEqual(index.search("distinctive boron clamp"), [])

    def test_filters_support_tag_project_person_and_source(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            doc = root / "brain/vault/inbox/private.md"
            doc.parent.mkdir(parents=True, exist_ok=True)
            doc.write_text(
                "---\n"
                "id: filtered-doc\n"
                "type: knowledge\n"
                "title: Filtered Note\n"
                "visibility: private\n"
                "status: active\n"
                "tags: [thermal]\n"
                "people: [Alice]\n"
                "projects: [Mounting Plate]\n"
                "source_id: source_abc\n"
                "---\n\n"
                "Ceramic mounting plate thermal test details.\n",
                encoding="utf-8",
            )

            index = PrivateKnowledgeIndex(root_path=root)
            index.build()

            self.assertEqual(len(index.search("thermal", tag="thermal")), 1)
            self.assertEqual(len(index.search("thermal", project="Mounting Plate")), 1)
            self.assertEqual(len(index.search("thermal", person="Alice")), 1)
            self.assertEqual(len(index.search("thermal", source="source_abc")), 1)
            self.assertEqual(index.search("thermal", source="missing"), [])

    def test_cli_build_search_and_ingest_inspect_share_source_id(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path("gang.config.yml").write_text("build: {}\n", encoding="utf-8")
            doc = Path("brain/vault/meetings/private.md")
            doc.parent.mkdir(parents=True, exist_ok=True)
            doc.write_text(
                "---\n"
                "id: private-doc\n"
                "type: knowledge\n"
                "title: Ceramic Meeting\n"
                "updated_at: '2026-01-05T00:00:00+00:00'\n"
                "visibility: private\n"
                "status: active\n"
                "source_id: source_cli_1\n"
                "---\n\n"
                "The ceramic mounting plate thermal test passed.\n",
                encoding="utf-8",
            )
            registry = Path("brain/vault/.ingestion/registry.json")
            registry.parent.mkdir(parents=True, exist_ok=True)
            registry.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "sources": {
                            "source_cli_1": {
                                "source_id": "source_cli_1",
                                "document_id": "private-doc",
                                "document_path": "brain/vault/meetings/private.md",
                                "raw_ref": "local://meeting/source_cli_1/v000001/private.txt",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )

            build = runner.invoke(gang_cli.cli, ["index", "build"])
            self.assertEqual(build.exit_code, 0, build.output)
            self.assertTrue(Path("brain/generated/brain.sqlite").exists())

            search = runner.invoke(gang_cli.cli, ["search", "ceramic mounting plate"])
            self.assertEqual(search.exit_code, 0, search.output)
            self.assertIn("Ceramic Meeting", search.output)
            self.assertIn("source_id: source_cli_1", search.output)

            inspect = runner.invoke(gang_cli.cli, ["ingest", "inspect", "source_cli_1"])
            self.assertEqual(inspect.exit_code, 0, inspect.output)
            self.assertIn('"raw_ref": "local://meeting/source_cli_1/v000001/private.txt"', inspect.output)

    def test_database_does_not_store_absolute_paths(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            write_markdown(
                root / "brain/vault/inbox/private.md",
                {
                    "id": "private-doc",
                    "type": "knowledge",
                    "title": "Private",
                    "visibility": "private",
                    "status": "active",
                },
                "Absolute paths should never appear in generated private search data.",
            )

            index = PrivateKnowledgeIndex(root_path=root)
            index.build()

            with sqlite3.connect(root / "brain/generated/brain.sqlite") as connection:
                dump = "\n".join(connection.iterdump())
            self.assertNotIn(str(root), dump)


if __name__ == "__main__":
    unittest.main()
