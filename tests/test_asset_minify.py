"""CSS minification must not rewrite quoted content strings."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

from core.asset_minify import minify_css


def test_nav_separator_spaces_survive_minification():
    css = Path(ROOT / "public" / "shell.css").read_text()
    out = minify_css(css)

    assert 'content:"   "' in out
    assert 'content:"    "' in out
    assert "/*" not in out


def test_comment_quotes_do_not_swallow_the_next_rule():
    css = '/* say "hi" */\n.a { color: red; content: "   "; }'
    out = minify_css(css)

    assert "say" not in out
    assert out == '.a{color:red;content:"   ";}'
