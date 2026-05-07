import json
import importlib
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

from core.search import SearchIndexer  # noqa: E402
from core.validator import ContractValidator  # noqa: E402


class ValidatorScriptBudgetTests(unittest.TestCase):
    def test_json_data_scripts_do_not_count_against_zero_js_budget(self):
        html = """<!doctype html>
<html lang="en">
<head>
  <title>Example</title>
  <script type="application/ld+json">{"@context":"https://schema.org"}</script>
  <script type="application/json" id="data">{"ok": true}</script>
</head>
<body><h1>Example</h1></body>
</html>"""

        with TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "index.html"
            html_path.write_text(html, encoding="utf-8")
            validator = ContractValidator({"budgets": {"js": 0}})

            issues = validator.check_budgets(html_path)

            self.assertNotIn("js_budget", {issue["rule"] for issue in issues})

    def test_executable_scripts_count_against_zero_js_budget(self):
        html = """<!doctype html>
<html lang="en">
<head><title>Example</title><script>console.log("runs")</script></head>
<body><h1>Example</h1></body>
</html>"""

        with TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "index.html"
            html_path.write_text(html, encoding="utf-8")
            validator = ContractValidator({"budgets": {"js": 0}})

            issues = validator.check_budgets(html_path)

            self.assertIn("js_budget", {issue["rule"] for issue in issues})


class SearchIndexerTests(unittest.TestCase):
    def test_yaml_dates_are_serialized_as_json_safe_strings(self):
        with TemporaryDirectory() as tmp:
            content_path = Path(tmp) / "content"
            posts_path = content_path / "posts"
            posts_path.mkdir(parents=True)
            post_path = posts_path / "launch.md"
            post_path.write_text(
                """---
title: Launch
date: 2025-10-12
tags:
  - release
summary: Launch summary
---

Launch body.
""",
                encoding="utf-8",
            )

            indexer = SearchIndexer(content_path, {})
            index = indexer.build_search_index([post_path])

            serialized = json.dumps(index)

            self.assertIn('"date": "2025-10-12"', serialized)
            self.assertEqual(index["documents"][0]["tags"], ["release"])


class CliCommandRegistrationTests(unittest.TestCase):
    def test_media_list_command_does_not_shadow_builtin_list(self):
        cli_module = importlib.import_module("cli")

        self.assertNotIn("list", vars(cli_module))
        self.assertIn("list", cli_module.cli.commands["media"].commands)

    def test_empty_frontmatter_jsonld_gets_page_default(self):
        cli_module = importlib.import_module("cli")
        config = {
            "site": {
                "title": "GANG",
                "description": "Site description",
                "url": "https://example.com",
            }
        }
        context = {
            "title": "Launch",
            "description": "Launch description",
            "date": "2025-10-12",
        }

        jsonld = cli_module.get_page_jsonld({"jsonld": {}}, config, context, "posts", "/posts/launch/")

        self.assertEqual(jsonld["@type"], "Article")
        self.assertEqual(jsonld["url"], "https://example.com/posts/launch/")
        self.assertEqual(jsonld["headline"], "Launch")


if __name__ == "__main__":
    unittest.main()
