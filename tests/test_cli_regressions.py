import json
import sys
import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner


ROOT = Path(__file__).resolve().parents[1]
CLI_ROOT = ROOT / "cli" / "gang"
sys.path.insert(0, str(CLI_ROOT))

from cli import cli as gang_cli  # noqa: E402
from cli import comments_are_usable, resolve_content_api_path  # noqa: E402
from core.validator import ContractValidator  # noqa: E402


class CliRegressionTests(unittest.TestCase):
    def test_check_commands_are_distinct(self):
        runner = CliRunner()

        check_help = runner.invoke(gang_cli, ["check", "--help"])
        contracts_help = runner.invoke(gang_cli, ["check-contracts", "--help"])

        self.assertEqual(check_help.exit_code, 0, check_help.output)
        self.assertEqual(contracts_help.exit_code, 0, contracts_help.output)
        self.assertIn("--output", check_help.output)
        self.assertIn("--verbose", contracts_help.output)

    def test_comments_require_real_webhook(self):
        self.assertFalse(comments_are_usable({
            "comments": {
                "enabled": True,
                "webhook_url": "https://your-n8n.app/webhook/comments",
            }
        }))
        self.assertTrue(comments_are_usable({
            "comments": {
                "enabled": True,
                "webhook_url": "https://comments.example.net/webhook",
            }
        }))

    def test_studio_content_paths_cannot_escape_content_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            content_root = Path(tmp) / "content"
            content_root.mkdir()

            safe_path = resolve_content_api_path(content_root, "posts/example.md")
            self.assertEqual(safe_path, content_root / "posts" / "example.md")

            with self.assertRaises(ValueError):
                resolve_content_api_path(content_root, "../gang.config.yml")

            with self.assertRaises(ValueError):
                resolve_content_api_path(content_root, "%2e%2e/gang.config.yml")


class ValidatorRegressionTests(unittest.TestCase):
    def _validator(self):
        return ContractValidator({
            "contracts": {
                "semantic": ["no_heading_skips"],
                "accessibility": ["keyboard_nav"],
                "seo": ["valid_jsonld", "canonical_url"],
            },
            "budgets": {"js": 0},
        })

    def test_jsonld_script_does_not_violate_js_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "index.html"
            html_path.write_text(
                "<html><head>"
                "<script type='application/ld+json'>"
                f"{json.dumps({'@context': 'https://schema.org', '@type': 'WebPage'})}"
                "</script>"
                "</head><body><h2>Section</h2></body></html>"
            )

            result = self._validator().validate_file(html_path)

            self.assertFalse([
                issue for issue in result["budgets"]
                if issue["rule"] == "js_budget"
            ])
            self.assertTrue(result["summary"]["passed"])

    def test_executable_script_still_violates_content_page_js_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "index.html"
            html_path.write_text("<html><body><script>alert('x')</script></body></html>")

            result = self._validator().validate_file(html_path)

            self.assertTrue([
                issue for issue in result["budgets"]
                if issue["rule"] == "js_budget"
            ])
            self.assertFalse(result["summary"]["passed"])

    def test_invalid_tabindex_does_not_crash(self):
        with tempfile.TemporaryDirectory() as tmp:
            html_path = Path(tmp) / "index.html"
            html_path.write_text(
                "<html><head><link rel='canonical' href='https://example.com/'></head>"
                "<body><h1>Title</h1><button tabindex='menu'>Go</button></body></html>"
            )

            result = self._validator().validate_file(html_path)

            self.assertTrue(result["summary"]["passed"])


if __name__ == "__main__":
    unittest.main()
