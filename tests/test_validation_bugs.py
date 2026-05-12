import sys
import unittest
from pathlib import Path

import yaml
from click.testing import CliRunner


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

from cli import cli, create_index_simple, create_list_page_simple  # noqa: E402
from core.image_pipeline import ImagePipeline  # noqa: E402
from core.validator import ContractValidator  # noqa: E402


MIN_CONFIG = {
    "site": {"title": "Test", "url": "https://example.com"},
    "build": {
        "output": "./dist",
        "content": "./content",
        "templates": "./templates",
        "public": "./public",
    },
    "contracts": {
        "semantic": ["single_h1", {"required_landmarks": ["main"]}],
        "accessibility": [{"alt_coverage": 100}, {"keyboard_nav": True}],
        "seo": [{"valid_jsonld": True}],
    },
    "budgets": {"html": 30720, "css": 10240, "js": 0},
}


class GangCheckCliTests(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()

    def test_check_help_includes_output_and_verbose_options(self):
        result = self.runner.invoke(cli, ["check", "--help"])

        self.assertEqual(result.exit_code, 0, result.output)
        self.assertIn("--output", result.output)
        self.assertIn("--verbose", result.output)

    def test_check_fails_when_dist_is_missing(self):
        with self.runner.isolated_filesystem():
            Path("gang.config.yml").write_text(yaml.safe_dump(MIN_CONFIG))

            result = self.runner.invoke(cli, ["check"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("dist/ directory not found", result.output)

    def test_check_fails_when_dist_contains_no_html(self):
        with self.runner.isolated_filesystem():
            Path("gang.config.yml").write_text(yaml.safe_dump(MIN_CONFIG))
            Path("dist").mkdir()

            result = self.runner.invoke(cli, ["check"])

        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("No HTML files found", result.output)


class ContractValidatorRegressionTests(unittest.TestCase):
    def test_json_ld_does_not_count_against_zero_js_budget(self):
        validator = ContractValidator(MIN_CONFIG)

        with CliRunner().isolated_filesystem():
            html_path = Path("index.html")
            html_path.write_text(
                """
                <!doctype html>
                <html>
                  <body>
                    <main><h1>Page</h1></main>
                    <script type="application/ld+json">
                      {"@context":"https://schema.org","@type":"WebPage"}
                    </script>
                  </body>
                </html>
                """
            )

            issues = validator.check_budgets(html_path)

        self.assertFalse(
            [issue for issue in issues if issue["rule"] == "js_budget"],
            issues,
        )

    def test_invalid_tabindex_reports_error_instead_of_crashing(self):
        validator = ContractValidator(MIN_CONFIG)

        issues = validator.check_accessibility('<main><button tabindex="bad">Go</button></main>')

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0]["severity"], "error")
        self.assertEqual(issues[0]["rule"], "keyboard_nav")

    def test_executable_script_still_violates_zero_js_budget(self):
        validator = ContractValidator(MIN_CONFIG)

        with CliRunner().isolated_filesystem():
            html_path = Path("index.html")
            html_path.write_text("<main><h1>Page</h1></main><script>alert('x')</script>")

            issues = validator.check_budgets(html_path)

        self.assertEqual(
            [issue["rule"] for issue in issues if issue["rule"] == "js_budget"],
            ["js_budget"],
        )


class ImagePipelineRegressionTests(unittest.TestCase):
    def test_picture_html_uses_escaped_alt_text_without_placeholder(self):
        pipeline = ImagePipeline(Path("public"), Path("dist"))

        html = pipeline._generate_picture_html(
            {"original": "fallback.jpg", "formats": {"jpg": "image.jpg"}},
            is_lcp=False,
            alt_text='A "great" & useful product',
        )

        self.assertIn('alt="A &quot;great&quot; &amp; useful product"', html)
        self.assertNotIn("TODO: Add alt text", html)


class GeneratedPageRegressionTests(unittest.TestCase):
    def test_simple_index_and_list_pages_emit_canonicals(self):
        index_html = create_index_simple(MIN_CONFIG, [])
        posts_html = create_list_page_simple(MIN_CONFIG, [], "Posts")

        self.assertIn('<link rel="canonical" href="https://example.com/">', index_html)
        self.assertIn('<link rel="canonical" href="https://example.com/posts/">', posts_html)


if __name__ == "__main__":
    unittest.main()
