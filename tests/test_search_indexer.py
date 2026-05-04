import json
import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli" / "gang"))

from core.search import SearchIndexer
from core.validator import ContractValidator


class SearchIndexerTest(unittest.TestCase):
    def test_search_index_serializes_yaml_dates(self):
        with self.subTest("plain YAML dates are JSON-safe"):
            import tempfile

            with tempfile.TemporaryDirectory() as temp_dir:
                content_dir = Path(temp_dir) / "content"
                pages_dir = content_dir / "pages"
                pages_dir.mkdir(parents=True)

                page = pages_dir / "dated-page.md"
                page.write_text(
                    """---
title: Dated Page
date: 2025-01-11
tags:
  - docs
---

# Dated Page

This page has a YAML date.
""",
                    encoding="utf-8",
                )

                index = SearchIndexer(content_dir, {}).build_search_index([page])

                self.assertEqual(index["documents"][0]["date"], "2025-01-11")
                json.dumps(index)


class ContractValidatorTest(unittest.TestCase):
    def test_jsonld_does_not_count_against_js_budget(self):
        import tempfile

        html = """<!doctype html>
<html>
<head>
  <script type="application/ld+json">{"@context":"https://schema.org"}</script>
</head>
<body><h1>Page</h1></body>
</html>"""

        with tempfile.TemporaryDirectory() as temp_dir:
            html_path = Path(temp_dir) / "index.html"
            html_path.write_text(html, encoding="utf-8")

            validator = ContractValidator({"budgets": {"js": 0}})

            self.assertEqual(validator.check_budgets(html_path), [])


if __name__ == "__main__":
    unittest.main()
