import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI_ROOT = ROOT / "cli" / "gang"
sys.path.insert(0, str(CLI_ROOT))
sys.modules.setdefault("anthropic", types.SimpleNamespace(Anthropic=object))

from core.analyzer import ContentAnalyzer
from core.contract_validator import ContractValidator
from core.link_validator import LinkValidator
from core.optimizer import AIOptimizer
from core.search import SearchIndexer
from core.validator import ContractValidator as ConfigContractValidator


class RegressionTests(unittest.TestCase):
    def test_optimizer_does_not_mutate_original_nested_frontmatter(self):
        optimizer = AIOptimizer({"ai": {"fill_missing": ["seo.title", "seo.description"]}})
        optimizer.client = object()
        optimizer.generate_seo = lambda content, frontmatter: {
            "title": "Generated title",
            "description": "Generated description",
        }

        frontmatter = {"title": "Original", "seo": {"description": "Human description"}}
        optimized = optimizer.optimize_content("Body", frontmatter, "post")

        self.assertEqual(optimized["seo"]["title"], "Generated title")
        self.assertNotIn("title", frontmatter["seo"])
        self.assertNotEqual(optimized, frontmatter)

    def test_contract_validator_accepts_jsonld_graph_nodes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            contracts = tmp_path / "contracts"
            contracts.mkdir()
            (contracts / "post.yml").write_text(
                "\n".join(
                    [
                        "type: post",
                        "jsonld:",
                        "  required_type: Article",
                        "  required_props:",
                        "    - headline",
                        "    - author",
                    ]
                )
            )

            page = tmp_path / "index.html"
            page.write_text(
                """
                <html><head>
                <script type="application/ld+json">
                {
                  "@context": "https://schema.org",
                  "@graph": [
                    {"@type": "WebSite", "name": "Example"},
                    {"@type": "Article", "headline": "Hello", "author": "GANG"}
                  ]
                }
                </script>
                </head><body><h1>Hello</h1></body></html>
                """
            )

            result = ContractValidator(contracts).validate_file(page, "post")

        self.assertEqual([], result["errors"])

    def test_content_analyzer_treats_empty_frontmatter_as_mapping(self):
        with tempfile.TemporaryDirectory() as tmp:
            md_file = Path(tmp) / "empty-frontmatter.md"
            md_file.write_text("---\n\n---\n# Title\n\nA short sentence.")

            analysis = ContentAnalyzer({}).analyze_file(md_file)

        self.assertEqual({}, analysis["frontmatter"])
        self.assertEqual(4, analysis["readability"]["word_count"])

    def test_internal_only_link_validation_skips_external_requests(self):
        class NoExternalRequestsValidator(LinkValidator):
            def _check_external_link(self, url):
                raise AssertionError("external request should not be made")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            content = tmp_path / "content"
            dist = tmp_path / "dist"
            (content / "pages").mkdir(parents=True)
            dist.mkdir()
            (content / "pages" / "home.md").write_text(
                "---\ntitle: Home\n---\n[External](https://example.com)\n[Self](/pages/home/)"
            )

            validator = NoExternalRequestsValidator({}, content, dist)
            results = validator.scan_all_files(check_external=False)

        self.assertEqual(0, results["external_links"])
        self.assertEqual([], results["broken_external"])
        self.assertEqual([], results["broken_internal"])
        self.assertEqual(1, results["internal_links"])

    def test_search_indexer_normalizes_frontmatter_for_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            content = Path(tmp) / "content"
            (content / "posts").mkdir(parents=True)
            md_file = content / "posts" / "dated.md"
            md_file.write_text(
                "---\n"
                "title: 123\n"
                "date: 2026-05-11\n"
                "tags: launch\n"
                "---\n"
                "# Launch\n"
            )

            index = SearchIndexer(content, {}).build_search_index([md_file])

        document = index["documents"][0]
        self.assertEqual("123", document["title"])
        self.assertEqual("2026-05-11", document["date"])
        self.assertEqual(["launch"], document["tags"])

    def test_validator_ignores_jsonld_for_js_budget(self):
        validator = ConfigContractValidator({"budgets": {"js": 0}})
        with tempfile.TemporaryDirectory() as tmp:
            html = Path(tmp) / "index.html"
            html.write_text(
                '<script type="application/ld+json">{"@context":"https://schema.org"}</script>'
            )

            self.assertEqual([], validator.check_budgets(html))

    def test_validator_handles_bad_tabindex_values(self):
        validator = ConfigContractValidator({
            "contracts": {"accessibility": ["keyboard_nav"]}
        })

        issues = validator.check_accessibility('<button tabindex="bogus">Go</button>')

        self.assertEqual([], issues)


if __name__ == "__main__":
    unittest.main()
