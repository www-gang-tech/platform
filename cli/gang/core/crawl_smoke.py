"""Smoke checks for crawlability, landmarks, and keyboard order after build."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, List
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

from bs4 import BeautifulSoup

SHELL_MARKER = "site-shell"
POSITIVE_TABINDEX = re.compile(r"tabindex\s*=\s*[\"']?\s*([1-9]\d*)", re.I)


def run_crawl_smoke(dist_path: Path, *, preview: bool = False) -> List[str]:
    """Return error strings. Empty list means the dist is crawl-safe."""
    errors: List[str] = []
    dist_path = Path(dist_path)

    sitemap = dist_path / "sitemap.xml"
    if not sitemap.exists():
        errors.append("missing sitemap.xml")
    else:
        errors.extend(_check_sitemap_xml(sitemap, preview=preview, dist_path=dist_path))

    if not preview:
        robots = dist_path / "robots.txt"
        if not robots.exists():
            errors.append("missing robots.txt")
        else:
            text = robots.read_text()
            if "Sitemap:" not in text:
                errors.append("robots.txt missing Sitemap: line")
            if "llms.txt" not in text:
                errors.append("robots.txt should point agents at /llms.txt")

        if not (dist_path / "llms.txt").exists():
            errors.append("missing llms.txt for answer-engine discovery")
        if not (dist_path / "agentmap.json").exists():
            errors.append("missing agentmap.json")
        else:
            try:
                payload = json.loads((dist_path / "agentmap.json").read_text())
            except json.JSONDecodeError:
                errors.append("agentmap.json is not valid JSON")
            else:
                if not payload.get("navigation") and not payload.get("endpoints"):
                    errors.append("agentmap.json missing navigation or endpoints")

        html_sitemap = dist_path / "sitemap" / "index.html"
        if not html_sitemap.exists():
            errors.append("missing HTML sitemap at /sitemap/")
        else:
            errors.extend(_check_html_sitemap(html_sitemap, dist_path))

    for html_path in sorted(dist_path.rglob("*.html")):
        html = html_path.read_text(errors="replace")
        if SHELL_MARKER not in html:
            continue
        rel = html_path.relative_to(dist_path).as_posix()
        errors.extend(_check_shell_page(html, rel, preview=preview))

    return errors


def _published_url(rel: str) -> str:
    if rel in {"", "index.html"}:
        return "/"
    if rel.endswith("/index.html"):
        return "/" + rel[: -len("index.html")]
    return "/" + rel


def _loc_path(loc: str) -> str:
    path = urlparse(loc).path or "/"
    if not path.startswith("/"):
        path = "/" + path
    if path != "/" and not path.endswith("/"):
        path = f"{path}/"
    return path


def _check_html_sitemap(path: Path, dist_path: Path) -> List[str]:
    errors: List[str] = []
    soup = BeautifulSoup(path.read_text(errors="replace"), "html.parser")
    main = soup.find("main")
    hrefs = {a.get("href") for a in (main.find_all("a") if main else [])}
    required = []
    if (dist_path / "index.html").exists():
        required.append("/")
    for url, folder in (
        ("/objects/", "objects"),
        ("/journal/", "journal"),
        ("/research/", "research"),
        ("/cart/", "cart"),
        ("/search/", "search"),
    ):
        if (dist_path / folder / "index.html").exists():
            required.append(url)
    missing = [url for url in required if url not in hrefs]
    if missing:
        errors.append("HTML sitemap omits published " + ", ".join(missing))
    return errors


def _check_sitemap_xml(path: Path, *, preview: bool, dist_path: Path | None = None) -> List[str]:
    errors: List[str] = []
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        return [f"sitemap.xml is not valid XML: {exc}"]
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [el.text or "" for el in root.findall("sm:url/sm:loc", ns)]
    if not locs:
        locs = [el.text or "" for el in root.findall("{http://www.sitemaps.org/schemas/sitemap/0.9}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
    if not locs:
        return ["sitemap.xml has no <loc> entries"]
    if len(locs) != len(set(locs)):
        errors.append("sitemap.xml contains duplicate <loc> values")
    paths = {_loc_path(loc) for loc in locs}
    if dist_path is not None:
        for url, marker in (
            ("/cart/", dist_path / "cart" / "index.html"),
            ("/search/", dist_path / "search" / "index.html"),
        ):
            if marker.exists() and url not in paths:
                errors.append(f"sitemap.xml omits published {url}")
    homes = [loc for loc in locs if urlparse(loc).path in ("", "/")]
    if not homes:
        errors.append("sitemap.xml should include the site home URL")
    lastmods = root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}lastmod")
    for node in lastmods:
        value = (node.text or "").strip()
        if value and not re.match(r"^\d{4}-\d{2}-\d{2}", value):
            errors.append(f"sitemap lastmod is not W3C date: {value}")
            break
    return errors


def _check_shell_page(html: str, rel: str, *, preview: bool) -> List[str]:
    errors: List[str] = []
    soup = BeautifulSoup(html, "html.parser")
    prefix = f"{rel}: "

    if soup.find("html") is None or not soup.find("html").get("lang"):
        errors.append(prefix + "html[lang] is required")

    skip = soup.select_one("a.skip-link[href='#content']")
    if skip is None:
        errors.append(prefix + "missing skip link to #content")
    else:
        body = soup.body
        if body:
            first = _first_focusable(body)
            if first is not None and "skip-link" not in (first.get("class") or []):
                errors.append(prefix + "skip link must be the first focusable element")

    if soup.find("header", attrs={"role": "banner"}) is None and soup.find("header") is None:
        errors.append(prefix + "missing header/banner landmark")
    nav = soup.find("nav", attrs={"aria-label": True})
    if nav is None:
        errors.append(prefix + "missing labelled <nav>")
    main = soup.find("main", id="content")
    if main is None:
        errors.append(prefix + "missing <main id=\"content\">")
    elif main.get("tabindex") not in ("-1", -1):
        errors.append(prefix + "main#content needs tabindex=\"-1\" as skip target")
    if soup.find("footer") is None:
        errors.append(prefix + "missing <footer>")

    currents = soup.select("nav[aria-label] a[aria-current='page']")
    if len(currents) > 1:
        errors.append(prefix + "more than one aria-current=page in main nav")
    page_url = _published_url(rel)
    for current in currents:
        href = current.get("href") or ""
        if href != page_url:
            errors.append(prefix + f"aria-current=page points at {href}, not {page_url}")

    if POSITIVE_TABINDEX.search(html):
        errors.append(prefix + "positive tabindex is not allowed (breaks natural tab order)")

    if not preview:
        robots = soup.find("meta", attrs={"name": "robots"})
        if robots and "noindex" in (robots.get("content") or "").lower():
            errors.append(prefix + "production page is noindex")

    desc = soup.find("meta", attrs={"name": "description"})
    if desc is None or not (desc.get("content") or "").strip():
        errors.append(prefix + "missing meta description")

    canonical = soup.find("link", attrs={"rel": "canonical"})
    if canonical is None or not canonical.get("href"):
        errors.append(prefix + "missing canonical URL")

    jsonld = soup.find("script", attrs={"type": "application/ld+json"})
    payload = ""
    if jsonld is not None:
        payload = (jsonld.string or jsonld.get_text() or "").strip()
    if not payload:
        errors.append(prefix + "missing JSON-LD")
    else:
        try:
            json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            errors.append(prefix + "JSON-LD is not valid JSON")

    return errors


def _first_focusable(root) -> Any:
    for el in root.find_all(["a", "button", "input", "select", "textarea", "summary"]):
        if el.name == "a" and not el.get("href"):
            continue
        if el.has_attr("disabled"):
            continue
        tabindex = el.get("tabindex")
        if tabindex == "-1":
            continue
        return el
    return None
