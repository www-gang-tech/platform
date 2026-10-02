import json
import sys
from pathlib import Path

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))
sys.path.insert(0, str(ROOT / "tests"))

from core.crawl_smoke import run_crawl_smoke
from core.generators import OutputGenerators
from test_editorial_preview import _render


def test_production_editorial_build_passes_crawl_smoke(tmp_path):
    dist = _render(tmp_path, preview=False)
    errors = run_crawl_smoke(dist, preview=False)
    assert errors == [], errors

    home = (dist / "index.html").read_text()
    soup = BeautifulSoup(home, "html.parser")
    skip = soup.select_one("a.skip-link")
    assert skip is not None
    assert skip.get("href") == "#content"
    assert soup.find("main", id="content").get("tabindex") == "-1"
    assert 'tabindex="1"' not in home
    assert (dist / "llms.txt").exists()
    assert "Sitemap:" in (dist / "robots.txt").read_text()
    assert "llms.txt" in (dist / "robots.txt").read_text()
    assert (dist / "sitemap" / "index.html").exists()
    assert 'aria-current="page"' in soup.select_one("a.site-wordmark").decode()


def test_preview_build_allows_noindex_and_still_has_skip_target(tmp_path):
    dist = _render(tmp_path, preview=True)
    errors = run_crawl_smoke(dist, preview=True)
    assert errors == [], errors
    assert "noindex" in (dist / "index.html").read_text()


def test_sitemap_xml_dedupes_and_uses_w3c_dates():
    gen = OutputGenerators(
        {
            "site": {
                "title": "GANG",
                "url": "https://gang-platform.dev",
                "description": "Studio",
            }
        }
    )
    xml = gen.generate_sitemap(
        [
            {"url": "/", "title": "Home", "date": "2026-01-02T10:00:00"},
            {"url": "/", "title": "Home again", "date": "not-a-date"},
            {"url": "objects/", "title": "Objects", "date": "2026-03-04"},
        ]
    )
    assert xml.count("https://gang-platform.dev/") >= 1
    assert xml.count("<loc>https://gang-platform.dev/</loc>") == 1
    assert "<lastmod>2026-01-02</lastmod>" in xml
    assert "<lastmod>2026-03-04</lastmod>" in xml
    llms = gen.generate_llms_txt([{"url": "/", "title": "Home"}])
    assert "/llms.txt" in gen.generate_robots()
    assert "Home" in llms
    agentmap = json.loads(gen.generate_agentmap())
    assert agentmap["endpoints"]["llmsTxt"].endswith("/llms.txt")
