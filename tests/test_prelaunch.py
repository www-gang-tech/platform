"""Public editorial pages share a shell and make the prelaunch state clear."""
import shutil
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

from core.content_loader import load_public_content
from core.site_build import write_markdown_pages
from core.templates import TemplateEngine


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
    home_soup = BeautifulSoup(home, "html.parser")
    assert home_soup.title.get_text(strip=True) == "GANG"
    footer = home_soup.select_one("footer")
    assert footer.find("a", href="/pages/contact/")
    assert footer.find("a", href="/pages/faq/")
    assert footer.find("a", href="/pages/privacy/") is None
    assert footer.find("a", href="/pages/terms/") is None
    instagram = footer.find("a", string="Instagram")
    assert instagram["href"] == "https://instagram.com/gang__tech"
    assert "noopener" in instagram.get("rel", [])
    assert "noreferrer" in instagram.get("rel", [])
    for item in _config()["nav"]["main"]:
        link = nav.find("a", href=item["path"])
        assert link is not None and item["label"] in link.get_text()


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


def test_journal_keeps_a_date_on_every_row(tmp_path):
    dist = _render(tmp_path)
    soup = BeautifulSoup((dist / "journal/index.html").read_text(), "html.parser")
    rows = soup.select(".journal-table tbody tr")
    assert len(rows) >= 2
    dated = []
    for row in rows:
        stamp = row.find("time")
        assert stamp is not None
        assert stamp.get("datetime")
        assert stamp.get_text(strip=True)
        assert stamp.get_text(strip=True) not in {"Today", "Yesterday"}
        dated.append(stamp)
    repeated = [stamp for stamp in dated if "visually-hidden" in (stamp.get("class") or [])]
    assert repeated
    assert any(stamp["datetime"] == "2026-10-01" for stamp in repeated)


def test_listing_dates_stay_calendar_dates():
    engine = TemplateEngine(ROOT / "templates")
    today = datetime.now().date()
    assert engine._listing_date(today.isoformat()) not in {"Today", "Yesterday"}
    assert engine._listing_date("2026-10-01").startswith("Thu Oct 01")
    previous_year = today.replace(year=today.year - 1)
    assert str(previous_year.year) in engine._listing_date(previous_year.isoformat())


def test_cart_empty_state_is_visible_without_javascript(tmp_path):
    dist = _render(tmp_path)
    soup = BeautifulSoup((dist / "cart/index.html").read_text(), "html.parser")
    empty = soup.select_one("#cart-empty")
    assert empty is not None
    assert "display: none" not in (empty.get("style") or "")
    assert "Your cart is empty" in empty.get_text()
    summary = soup.select_one("#cart-summary")
    assert summary is not None
    assert "display: none" in (summary.get("style") or "")


def test_machine_readable_nav_matches_the_header(tmp_path):
    dist = _render(tmp_path)
    llms = (dist / "llms.txt").read_text().split("## All public URLs", 1)[0]
    assert "[Store](https://gang.tech/objects/)" in llms
    assert "[Information](https://gang.tech/studio/)" in llms
    assert "[Projects](https://gang.tech/projects/)" in llms
    assert "[Subscribe](https://gang.tech/updates/)" in llms
    assert "[Cart](https://gang.tech/cart/)" in llms
    assert "[Objects](" not in llms
