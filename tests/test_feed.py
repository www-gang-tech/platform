"""The public JSON feed lists published journal and research notes."""
import json
import shutil
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

from core.content_loader import load_public_content
from core.generators import OutputGenerators
from core.site_build import write_markdown_pages


def _config():
    return yaml.safe_load((ROOT / "gang.config.yml").read_text())


def test_feed_dates_are_rfc3339_and_urls_join_once():
    generators = OutputGenerators({"site": {"title": "GANG", "url": "https://gang.tech/", "description": "Notes", "language": "en"}})
    raw = generators.generate_feed_json(
        [
            {
                "url": "/journal/older/",
                "title": "Older",
                "summary": "Earlier note",
                "date": "2026-09-30",
                "updated": "2026-09-30",
                "content_html": "<p>Earlier</p>",
            },
            {
                "url": "/journal/newer/",
                "title": "Newer",
                "date": "2026-10-01",
                "updated": "2026-10-03",
            },
            {"url": "/journal/newer/", "title": "Duplicate"},
            {"title": "No path"},
        ]
    )
    feed = json.loads(raw)
    assert feed["home_page_url"] == "https://gang.tech/"
    assert feed["feed_url"] == "https://gang.tech/feed.json"
    assert [item["url"] for item in feed["items"]] == [
        "https://gang.tech/journal/newer/",
        "https://gang.tech/journal/older/",
    ]
    newer = feed["items"][0]
    assert newer["date_published"] == "2026-10-01T00:00:00Z"
    assert newer["date_modified"] == "2026-10-03T00:00:00Z"
    assert "//journal" not in newer["url"]


def test_published_notes_are_in_the_feed(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    shutil.copytree(ROOT / "public", dist / "assets", dirs_exist_ok=True)
    config = _config()
    docs = load_public_content(config, source="vault", root_path=ROOT)
    write_markdown_pages(config, docs, dist, ROOT / "templates")

    feed = json.loads((dist / "feed.json").read_text())
    urls = [item["url"] for item in feed["items"]]
    assert "https://gang.tech/journal/a-place-for-charging/" in urls
    assert "https://gang.tech/research/qi2-magnetic-power-profile/" in urls
    assert "https://gang.tech/research/alignment-not-wattage/" in urls
    assert all("/objects/" not in url for url in urls)
    assert all("charger-alignment-draft" not in url for url in urls)
    assert urls[0] in {
        "https://gang.tech/journal/a-place-for-charging/",
        "https://gang.tech/journal/what-belongs-in-the-room/",
    }

    by_url = {item["url"]: item for item in feed["items"]}
    place = by_url["https://gang.tech/journal/a-place-for-charging/"]
    assert place["date_published"] == "2026-10-01T00:00:00Z"
    assert place["date_modified"] == "2026-10-03T00:00:00Z"
    assert "wall" in place["content_html"].lower()

    journal = (dist / "journal" / "index.html").read_text()
    research = (dist / "research" / "index.html").read_text()
    assert 'href="/feed.json"' in journal
    assert 'href="/feed.json"' in research
    projects = (dist / "projects" / "index.html").read_text()
    assert 'href="/feed.json"' not in projects
