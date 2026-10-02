import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

from core.faq_accordion import faq_html_to_accordion


def test_faq_markdown_headings_become_aria_accordion():
    html = """
    <h1>Frequently Asked Questions</h1>
    <h2>General Questions</h2>
    <h3>What is GANG?</h3>
    <p>A publishing platform.</p>
    <h3>Is GANG open source?</h3>
    <p>Yes, on <a href="https://github.com/www-gang-tech/platform">GitHub</a>.</p>
    <hr>
    <p>More questions? Contact us.</p>
    """
    out = faq_html_to_accordion(html)

    assert "<h1>" not in out
    assert "<h2>General Questions</h2>" in out
    assert "<details class=\"faq-item\" name=\"faq\">" in out
    assert 'id="faq-what-is-gang"' in out
    assert 'aria-controls="faq-panel-what-is-gang"' in out
    assert 'id="faq-panel-what-is-gang"' in out
    assert 'role="region"' in out
    assert 'aria-labelledby="faq-what-is-gang"' in out
    assert "<summary" in out and "What is GANG?" in out
    assert "A publishing platform." in out
    assert "<hr" not in out
    assert "More questions? Contact us." in out
