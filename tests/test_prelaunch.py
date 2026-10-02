"""The public site keeps the editorial markdown shell. Copy can change; chrome cannot."""
import json
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

    assert "Power has a place." in home
    assert "Public writing starts as a file." in studio
    assert "In development" in charger
    assert "GANG 4-in-1" in charger
    assert "25 W" not in charger
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


def test_search_keeps_query_and_section_from_the_address(tmp_path):
    dist = _render(tmp_path)
    search = (dist / "search/index.html").read_text()
    journal = (dist / "journal/index.html").read_text()

    assert "URLSearchParams" in search
    assert "params.get(\"q\")" in search
    assert "data-section=" in search
    assert 'name="section"' in journal
    assert 'value="journal"' in journal


def test_json_feed_includes_journal_and_skips_standalone_pages(tmp_path):
    dist = _render(tmp_path)
    feed = json.loads((dist / "feed.json").read_text())
    urls = {item["url"] for item in feed["items"]}

    assert "https://gang.tech/journal/a-place-for-charging/" in urls
    assert "https://gang.tech/research/alignment-not-wattage/" in urls
    assert "https://gang.tech/objects/charger/" in urls
    assert "https://gang.tech/pages/faq/" not in urls
    assert "https://gang.tech/about/" not in urls
    assert feed["items"][0]["date_published"] >= feed["items"][-1]["date_published"]


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
    assert 'src="/assets/images/gang-hero.jpg"' in home
    assert "Page size:" in home
    assert "__PAGE_SIZE__" not in home
    assert 'href="/studio.html"' not in home
    assert 'href="https://instagram.com/gang__tech"' in home
    assert 'href="http://instagram.com/gang__tech"' not in home
