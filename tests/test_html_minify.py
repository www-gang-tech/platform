"""Production HTML minification must not glue adjacent link text."""
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

from core.site_build import minify_html


def _text(html: str) -> str:
    raw = BeautifulSoup(html, "html.parser").get_text("", strip=False)
    return re.sub(r"\s+", " ", raw).strip()


def test_minifier_keeps_a_space_between_adjacent_links():
    html = """
    <!-- navigation -->
    <nav>
        <a href="/">GANG</a>
        <a href="/objects/">Store</a>
        <a href="/journal/">Journal</a>
    </nav>
    <p class="footer-line">
        <a href="/pages/privacy/">Privacy</a>
        <a href="/pages/terms/">Terms</a>
    </p>
    """
    minified = minify_html(html)
    text = _text(minified)

    assert "GANGStore" not in minified
    assert "StoreJournal" not in minified
    assert "PrivacyTerms" not in minified
    assert "GANG Store Journal" in text
    assert "Privacy Terms" in text
    assert "<!--" not in minified
    assert len(minified) < len(html)


def test_minifier_leaves_json_ld_parseable():
    html = """
    <script type="application/ld+json">
    {"@context": "https://schema.org", "@type": "WebPage", "name": "Store"}
    </script>
    """
    soup = BeautifulSoup(minify_html(html), "html.parser")
    data = json.loads(soup.find("script").string)
    assert data["@type"] == "WebPage"
    assert data["name"] == "Store"
