import importlib
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI_PATH = ROOT / "cli" / "gang"
if str(CLI_PATH) not in sys.path:
    sys.path.insert(0, str(CLI_PATH))

from core.search import SearchIndexer
from core.validator import ContractValidator


class SearchIndexerTests(unittest.TestCase):
    def test_index_normalizes_dates_and_tags_for_json_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            content_path = Path(temp_dir)
            post_path = content_path / "posts" / "sample.md"
            post_path.parent.mkdir()
            post_path.write_text(
                "---\n"
                "title: Sample\n"
                "date: 2025-10-13T10:00:00+00:00\n"
                "tags: alpha\n"
                "---\n"
                "Body text\n"
            )

            index = SearchIndexer(content_path, {}).build_search_index([post_path])

            self.assertEqual(index["documents"][0]["date"], "2025-10-13T10:00:00+00:00")
            self.assertEqual(index["documents"][0]["tags"], ["alpha"])
            json.dumps(index)

    def test_date_serializer_handles_datetime_instances(self):
        indexer = SearchIndexer(Path("."), {})
        value = datetime(2025, 10, 13, 10, 0, tzinfo=timezone.utc)

        self.assertEqual(indexer._serialize_date(value), "2025-10-13T10:00:00+00:00")


class CliModuleTests(unittest.TestCase):
    def test_cli_module_does_not_shadow_builtin_list(self):
        cli_module = importlib.import_module("cli")

        self.assertNotIn("list", cli_module.__dict__)

    def test_check_commands_expose_documented_options(self):
        cli_module = importlib.import_module("cli")
        root_commands = cli_module.cli.commands

        self.assertIn("check", root_commands)
        self.assertIn("contract-check", root_commands)

        check_options = {
            option
            for param in root_commands["check"].params
            for option in getattr(param, "opts", [])
        }
        self.assertIn("--verbose", check_options)
        self.assertIn("--output", check_options)


class BudgetValidatorTests(unittest.TestCase):
    def test_json_data_scripts_do_not_violate_zero_js_budget(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "index.html"
            html_path.write_text(
                '<script type="application/ld+json">{"@context":"https://schema.org"}</script>'
                '<script type="application/json" id="data">{"ok":true}</script>'
            )
            validator = ContractValidator({"budgets": {"js": 0}})

            issues = validator.check_budgets(html_path)

            self.assertEqual([], [issue for issue in issues if issue["rule"] == "js_budget"])

    def test_executable_scripts_violate_zero_js_budget(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "index.html"
            html_path.write_text("<script>window.alert('x')</script>")
            validator = ContractValidator({"budgets": {"js": 0}})

            issues = validator.check_budgets(html_path)

            self.assertEqual(["js_budget"], [issue["rule"] for issue in issues])


if __name__ == "__main__":
    unittest.main()
