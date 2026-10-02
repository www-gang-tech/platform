import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

from core.content_loader import load_public_content
from core.site_build import write_markdown_pages


def _config():
    return yaml.safe_load((ROOT / "gang.config.yml").read_text())


def _render(tmp_path, *, preview):
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


def test_production_omits_drafts_editor_and_indexes_public_nav(tmp_path):
    dist = _render(tmp_path, preview=False)
    home = (dist / "index.html").read_text()
    charger = (dist / "objects/charger/index.html").read_text()

    assert (dist / "studio/index.html").exists()
    assert (dist / "journal/index.html").exists()
    assert (dist / "research/index.html").exists()
    assert (dist / "objects/index.html").exists()
    assert not (dist / "journal/charger-alignment-draft/index.html").exists()
    assert not (dist / "pages/ok-rm-brief/index.html").exists()
    assert "editor-bundle" not in home
    assert "noindex" not in home
    assert 'href="/studio/"' in home
    assert "In development" in charger
    assert "Related" in charger
    assert "Now / Next / Learned" in charger
    assert "Page size:" in home
    assert "/assets/shell.css" in home
    assert 'src="/assets/images/gang-hero.jpg"' in home
    assert 'href="/search/"' in home
    assert ">Search<" in home
    journal = (dist / "journal/index.html").read_text()
    assert "listing-search" not in journal
    assert "Show results" not in journal
    assert "index-entry-thumb" in journal
    assert "September 30, 2026" in journal
    assert "Privacy Policy" in home
    assert "Terms" in home
    contact = (dist / "pages/contact/index.html").read_text()
    assert "mailto:info@gang.tech" in contact
    css = (dist / "assets/style.css").read_text()
    assert "font-weight: 400" in css
    assert ".site-main a" in css
    search = (dist / "search/index.html").read_text()
    assert 'id="site-search-input"' in search
    assert "index-entry-thumb" in search
    assert 'href="/pages/privacy/"' in home
    assert 'href="/pages/terms/"' in home
    assert "KB" in home or " B" in home
    assert "__PAGE_SIZE__" not in home
    feed = (dist / "feed.json").read_text()
    assert "charger-alignment-draft" not in feed


def test_preview_includes_drafts_and_noindex(tmp_path):
    dist = _render(tmp_path, preview=True)
    assert (dist / "journal/charger-alignment-draft/index.html").exists()
    draft = (dist / "journal/charger-alignment-draft/index.html").read_text()
    assert "editorial-kicker" not in draft
    assert "JOURNAL" not in draft
    assert (dist / "pages/ok-rm-brief/index.html").exists()
    assert "noindex" in (dist / "index.html").read_text()
    assert "Disallow: /" in (dist / "robots.txt").read_text()
    assert "editor-bundle" not in (dist / "studio/index.html").read_text()
