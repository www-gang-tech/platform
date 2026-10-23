"""Public editorial pages share a shell and make the prelaunch state clear."""
import json
import shutil
import subprocess
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


def test_search_uses_page_body_and_each_word(tmp_path):
    dist = _render(tmp_path)
    html = (dist / "search" / "index.html").read_text()
    assert 'fetch("/search-index.json")' in html
    soup = BeautifulSoup(html, "html.parser")
    charger = soup.select_one("a[href='/objects/charger/']").parent
    visible = charger.get("data-search") or ""
    assert "tpu" not in visible
    assert "charger" not in visible

    import importlib.util
    from core.search import SearchIndexer

    spec = importlib.util.spec_from_file_location("gang_cli_search", ROOT / "cli" / "gang" / "cli.py")
    cli_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli_module)
    docs = load_public_content(_config(), source="vault", root_path=ROOT)
    index = cli_module.build_search_index_from_documents(docs, SearchIndexer(ROOT / "brain" / "vault" / "public", _config()))
    indexed = next(doc for doc in index["documents"] if doc["url"] == "/objects/charger/")
    assert "tpu" in indexed["searchable"]
    assert "charger" in indexed["searchable"]
    script = html.split("<script>", 1)[1].split("</script>", 1)[0]
    probe = Path(tmp_path) / "search-probe.js"
    probe.write_text(
        "var window = {};\n"
        "var document = {getElementById: function(){return null;}, querySelectorAll: function(){return [];}};\n"
        "var fetch = function(){return Promise.reject(new Error('skip'));};\n"
        + script
        + "\nvar body = window.GangSearch.absorb({documents:[{url:'/objects/charger/', searchable:'where a device meets its charger. die-cast zinc and an injection-moulded TPU front.'}]});\n"
        "var hay = body['/objects/charger/'] + ' gang–1 wall-mounted wireless charging';\n"
        "console.log(JSON.stringify({\n"
        "  charger: window.GangSearch.matches(hay, 'charger'),\n"
        "  wallCharger: window.GangSearch.matches(hay, 'wall charger'),\n"
        "  tpu: window.GangSearch.matches(hay, 'TPU'),\n"
        "  miss: window.GangSearch.matches('alignment is the finding', 'screwdriver')\n"
        "}));\n"
    )
    completed = subprocess.run(["node", str(probe)], check=True, capture_output=True, text=True)
    assert json.loads(completed.stdout) == {
        "charger": True,
        "wallCharger": True,
        "tpu": True,
        "miss": False,
    }


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
