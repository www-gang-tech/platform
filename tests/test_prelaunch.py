"""Public editorial pages share a shell and make the prelaunch state clear."""
import shutil
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

from core.content_loader import load_public_content
from core.site_build import write_markdown_pages


def _config():
    return yaml.safe_load((ROOT / "gang.config.yml").read_text())


def _render(tmp_path, *, preview=False):
    dist = tmp_path / ("preview" if preview else "prod")
    dist.mkdir()
    shutil.copytree(ROOT / "public", dist / "assets", dirs_exist_ok=True)
    docs = load_public_content(_config(), source="vault", root_path=ROOT, include_drafts=preview)
    write_markdown_pages(
        _config(),
        docs,
        dist,
        ROOT / "templates",
        preview=preview,
        editor_mode=False,
    )
    return dist


def test_pages_use_markdown_shell_not_retail_layout(tmp_path):
    dist = _render(tmp_path)
    home = (dist / "index.html").read_text()
    charger = (dist / "objects/charger/index.html").read_text()
    studio = (dist / "studio/index.html").read_text()

    for html in (home, charger, studio):
        assert 'href="/assets/shell.css"' in html
        assert 'href="/assets/style.css"' in html
        assert "site-shell" in html
        assert "markdown-body" in html
        assert "retail.css" not in html
        assert "layout-home" not in html
        assert "hero-image" not in html
        assert '/assets/cart.js' not in html
        assert '/assets/comments.js' not in html

    assert "GANG" in home
    assert "Crafted tools for intentional living" in home
    assert "GANG 100W MagSafe Wall Charger" in home
    assert "Frank Godchaux and Daniel Hirunrusme" in studio
    assert "A memory for the practice" in studio
    assert "In development" in charger
    assert "GANG–1" in charger
    assert "Up to 25 W per zone" in charger
    assert "160 W" in charger
    assert 'href="/assets/documents/gang-specifications.pdf"' in charger
    assert "Qi2 certified" not in charger
    assert "Add to bag" not in charger


def test_updates_page_is_markdown_with_email_request(tmp_path):
    dist = _render(tmp_path)
    soup = BeautifulSoup((dist / "updates/index.html").read_text(), "html.parser")
    assert soup.select_one(".markdown-body")
    assert not soup.find("form")
    link = soup.find("a", href=lambda value: value and value.startswith("mailto:info@gang.tech"))
    target = urlsplit(link["href"])
    assert target.path == "info@gang.tech"
    assert "unsubscribe" in parse_qs(target.query)["body"][0]
    assert "Request updates by email" in link.get_text()
    assert "Send the message" in soup.get_text()
    assert "You're on the list" not in soup.get_text()


def test_production_omits_drafts_and_indexes_existing_nav(tmp_path):
    dist = _render(tmp_path, preview=False)
    home = (dist / "index.html").read_text()

    assert (dist / "studio/index.html").exists()
    assert (dist / "journal/index.html").exists()
    assert (dist / "research/index.html").exists()
    assert (dist / "objects/index.html").exists()
    assert not (dist / "journal/charger-alignment-draft/index.html").exists()
    assert 'href="/studio/"' in home
    assert 'href="/objects/"' in home
    assert 'src="/assets/images/gang-4-in-1-prototype.jpg"' in home
    nav = BeautifulSoup(home, "html.parser").select_one(".site-header")
    assert "Store" in nav.find("a", href="/objects/").get_text()
    assert "Information" in nav.find("a", href="/studio/").get_text()
    assert "Journal" in nav.find("a", href="/journal/").get_text()
    assert "Projects" in nav.find("a", href="/projects/").get_text()
    assert nav.find("a", href="/objects/", string="Objects") is None
    assert nav.find("a", href="/about/", string="Philosophy") is None
    assert nav.find("a", href="/cart/")
    assert nav.find("a", href="/updates/")
    assert "Subscribe" in nav.get_text()
    assert "Cart" in nav.get_text()
    assert nav.select_one(".site-masthead-date") is None
    assert not nav.find("a", href="/studio.html")
    assert "grid-template-columns: 1fr 1.2fr" not in (ROOT / "public" / "style.css").read_text()
    assert "Page size:" in home
    assert "__PAGE_SIZE__" not in home


def test_homepage_does_not_invent_coverage_or_a_price(tmp_path):
    dist = _render(tmp_path)
    home = (dist / "index.html").read_text()
    soup = BeautifulSoup(home, "html.parser")

    text = soup.get_text(" ", strip=True)
    for publication in ("Wallpaper", "Dezeen", "The Verge", "Monocle"):
        assert publication not in text
    assert "$200" not in text
    assert "USD" not in text
    assert "In development" in text
    assert soup.find("a", href="/pages/press/")


def test_markdown_header_margin_does_not_apply_to_the_site_header():
    css = (ROOT / "public" / "style.css").read_text()
    bare_header = [line.strip() for line in css.splitlines() if line.strip() == "header {"]
    assert bare_header == []
    assert ".markdown-body header {" in css


def test_store_index_is_a_four_column_grid(tmp_path):
    dist = _render(tmp_path)
    store = (dist / "objects/index.html").read_text()
    css = (ROOT / "public" / "style.css").read_text()
    soup = BeautifulSoup(store, "html.parser")
    grid = soup.select_one(".store-grid")
    assert grid is not None
    assert grid.find("a", href="/objects/charger/")
    assert "repeat(4, 1fr)" in css
    assert "repeat(2, 1fr)" in css
