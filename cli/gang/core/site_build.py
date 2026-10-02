"""Shared Markdown-to-HTML rendering for production and local preview."""

from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import markdown

from .content_loader import LIST_ROUTES, PublicDocument
from .faq_accordion import faq_html_to_accordion
from .generators import OutputGenerators
from .templates import TemplateEngine

# Dated public documents. Standalone pages (about, FAQ, contact) are not posts.
FEED_COLLECTIONS = (
    "journal",
    "research",
    "objects",
    "posts",
    "projects",
    "newsletters",
    "guides",
)

SECTION_INDEXES = (
    ("objects", "Objects", "Objects in development and in use."),
    ("research", "Research", "Notes that can be checked against primary sources."),
    ("journal", "Journal", "Development notes and charging guides."),
    ("guides", "Guides", "Practical charging notes."),
    ("studio", "Studio", "How this studio publishes."),
    ("posts", "Journal", "Writing."),
    ("projects", "Projects", "Projects."),
    ("newsletters", "Newsletters", "Newsletters."),
)


def output_file_for_url(dist_path: Path, url: str) -> Path:
    clean = url.strip("/")
    if not clean:
        return dist_path / "index.html"
    return dist_path / clean / "index.html"


def template_for_document(document: PublicDocument) -> str:
    if document.url == "/":
        return "home.html"
    if document.collection in {"objects", "research", "journal", "guides"} or document.url in {
        "/studio/",
        "/about/",
        "/team/",
        "/updates/",
        "/pages/contact/",
        "/pages/ok-rm-brief/",
        "/pages/faq/",
        "/pages/compatibility/",
        "/pages/setup/",
        "/pages/press/",
        "/pages/trade/",
    }:
        return "editorial.html"
    if document.collection == "posts":
        return "post.html"
    if document.collection == "projects":
        return "article.html"
    if document.collection == "newsletters":
        return "newsletter.html"
    return "page.html"


def resolve_related(document: PublicDocument, by_url: Dict[str, PublicDocument]) -> List[Dict[str, str]]:
    related = []
    for raw in document.frontmatter.get("related") or []:
        target = str(raw).strip()
        if not target.endswith("/"):
            target = f"{target}/"
        other = by_url.get(target)
        if other:
            related.append({"url": other.url, "title": other.title})
        else:
            related.append({"url": target, "title": target})
    return related


def write_markdown_pages(
    config: Dict[str, Any],
    documents: List[PublicDocument],
    dist_path: Path,
    templates_path: Path,
    *,
    preview: bool = False,
    editor_mode: Optional[bool] = None,
    live_reload_html: str = "",
    process_external_links=None,
    process_markdown_fallback=None,
) -> Dict[str, List[Dict[str, Any]]]:
    if editor_mode is None:
        editor_mode = os.environ.get("EDITOR_MODE", "").lower() == "true" and preview

    template_engine = TemplateEngine(templates_path)
    by_url = {doc.url: doc for doc in documents}
    grouped: Dict[str, List[Dict[str, Any]]] = {
        "pages": [],
        "posts": [],
        "projects": [],
        "newsletters": [],
        "objects": [],
        "research": [],
        "journal": [],
        "guides": [],
        "all": [],
    }

    md = markdown.Markdown(extensions=["extra", "meta"])
    for document in documents:
        content_html = md.convert(document.body)
        md.reset()
        if process_external_links:
            content_html = process_external_links(content_html)
        if document.url == "/pages/faq/":
            content_html = faq_html_to_accordion(content_html)

        related = resolve_related(document, by_url)
        noindex = preview or document.status != "published" or bool(document.frontmatter.get("noindex"))
        build_time = datetime.now()
        canonical_url = f"{config['site']['url']}{document.url}"
        context = {
            "site_title": config["site"]["title"],
            "lang": config["site"]["language"],
            "title": document.title,
            "description": document.summary or config["site"]["description"],
            "content": content_html,
            "year": datetime.now().year,
            "navigation": config.get("nav", {}).get("main", []),
            "date": document.date or document.created,
            "date_formatted": str(document.date or document.created or ""),
            "tags": document.tags,
            "build_time": build_time.strftime("%B %d, %Y at %I:%M %p"),
            "build_time_iso": build_time.isoformat(),
            "jsonld": document.frontmatter.get("jsonld")
            or default_jsonld(
                config,
                title=document.title,
                url=canonical_url,
                description=document.summary or config["site"]["description"],
                page_type="FAQPage" if document.url == "/pages/faq/" else "WebPage",
            ),
            "page_type": document.type,
            "category": document.collection,
            "slug": document.slug,
            "user_authenticated": editor_mode,
            "canonical_url": canonical_url,
            "current_path": document.url,
            "related": related,
            "comments": [],
            "noindex": noindex,
            "preview": preview,
            "document_status": document.status,
            "now": document.frontmatter.get("now"),
            "next": document.frontmatter.get("next"),
            "learned": document.frontmatter.get("learned"),
            "revision_notes": document.frontmatter.get("revision_notes") or [],
            "stage": document.frontmatter.get("stage"),
            "source_path": document.source_path.as_posix(),
        }

        template_name = template_for_document(document)
        try:
            html = template_engine.render(template_name, context)
        except Exception:
            if process_markdown_fallback:
                html = process_markdown_fallback(document.source_path, document.collection, config)
            else:
                raise
        if live_reload_html:
            html = _inject(html, live_reload_html)
        html = stamp_page_size(html)

        output_file = output_file_for_url(dist_path, document.url)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(html)

        page_data = document.to_page_data(content_html)
        grouped.setdefault(document.collection, []).append(page_data)
        grouped["all"].append(page_data)

    _write_section_indexes(
        config,
        grouped,
        dist_path,
        template_engine,
        preview=preview,
        editor_mode=editor_mode,
        live_reload_html=live_reload_html,
        has_home=any(doc.url == "/" for doc in documents),
    )

    generators = OutputGenerators(config)
    sitemap_pages = list(grouped["all"])
    if not any(item["url"] == "/" for item in sitemap_pages):
        sitemap_pages.append({"url": "/", "title": config["site"]["title"], "type": "home"})
    for route in LIST_ROUTES:
        if route != "/" and any(item["url"].startswith(route) or item["type"] == route.strip("/") for item in grouped["all"]):
            sitemap_pages.append({"url": route, "title": route.strip("/").title(), "type": "list"})
    if not any(item.get("url") == "/sitemap/" for item in sitemap_pages):
        sitemap_pages.append({"url": "/sitemap/", "title": "Sitemap", "type": "list", "date": datetime.now().strftime("%Y-%m-%d")})
    if not any(item.get("url") == "/search/" for item in sitemap_pages):
        sitemap_pages.append({"url": "/search/", "title": "Search", "type": "list", "date": datetime.now().strftime("%Y-%m-%d")})
    generators.generate_all(dist_path, sitemap_pages, feed_documents(grouped), preview=preview)
    return grouped


def feed_documents(grouped: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Journal, research, and other dated documents. The posts collection is legacy."""
    items: List[Dict[str, Any]] = []
    for key in FEED_COLLECTIONS:
        items.extend(grouped.get(key) or [])
    return sorted(items, key=lambda item: str(item.get("date") or ""), reverse=True)


def _write_section_indexes(
    config,
    grouped,
    dist_path: Path,
    template_engine: TemplateEngine,
    *,
    preview: bool,
    editor_mode: bool,
    live_reload_html: str,
    has_home: bool,
) -> None:
    build_time = datetime.now()
    base_context = {
        "site_title": config["site"]["title"],
        "lang": config["site"]["language"],
        "year": datetime.now().year,
        "navigation": config.get("nav", {}).get("main", []),
        "user_authenticated": editor_mode,
        "noindex": preview,
        "preview": preview,
        "comments": [],
        "build_time": build_time.strftime("%B %d, %Y at %I:%M %p"),
        "build_time_iso": build_time.isoformat(),
        "canonical_url": config["site"]["url"],
    }

    titles = {key: label for key, label, _intro in SECTION_INDEXES}
    intros = {key: intro for key, _label, intro in SECTION_INDEXES}

    for collection, items in grouped.items():
        if collection in {"all", "pages"}:
            continue
        if collection not in titles:
            continue
        # Studio is a single page, not a generated index, unless no studio page exists.
        if collection == "studio":
            continue
        list_url = f"/{collection}/"
        if any(item["url"] == list_url for item in grouped["all"]):
            continue
        context = {
            **base_context,
            "title": titles[collection],
            "page_title": titles[collection],
            "description": intros[collection],
            "items": sorted(items, key=lambda item: item.get("date") or "", reverse=True),
            "content_type": collection,
            "canonical_url": f"{config['site']['url']}{list_url}",
            "current_path": list_url,
            "jsonld": default_jsonld(
                config,
                title=titles[collection],
                url=f"{config['site']['url']}{list_url}",
                description=intros[collection],
                page_type="CollectionPage",
            ),
            "page_type": collection,
            "category": collection,
            "slug": collection,
        }
        html = template_engine.render("list.html", context)
        if live_reload_html:
            html = _inject(html, live_reload_html)
        html = stamp_page_size(html)
        output = output_file_for_url(dist_path, list_url)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(html)

    write_html_sitemap(
        config,
        grouped,
        dist_path,
        template_engine,
        preview=preview,
        editor_mode=editor_mode,
        live_reload_html=live_reload_html,
    )
    write_search_page(
        config,
        grouped,
        dist_path,
        template_engine,
        preview=preview,
        editor_mode=editor_mode,
        live_reload_html=live_reload_html,
    )


def html_sitemap_sections(grouped: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []
    for key, label, _intro in SECTION_INDEXES:
        if key == "studio":
            continue
        items = grouped.get(key) or []
        if items:
            sections.append(
                {"title": label, "links": sorted(items, key=lambda item: (item.get("title") or "").lower())}
            )
    pages = [item for item in (grouped.get("pages") or []) if item.get("url") not in {"/", None}]
    if pages:
        sections.append(
            {"title": "Pages", "links": sorted(pages, key=lambda item: (item.get("title") or "").lower())}
        )
    return sections


def write_html_sitemap(
    config: Dict[str, Any],
    grouped: Dict[str, List[Dict[str, Any]]],
    dist_path: Path,
    template_engine: TemplateEngine,
    *,
    preview: bool,
    editor_mode: bool = False,
    live_reload_html: str = "",
    products: Optional[List[Dict[str, Any]]] = None,
) -> None:
    build_time = datetime.now()
    canonical_url = f"{config['site']['url'].rstrip('/')}/sitemap/"
    context = {
        "site_title": config["site"]["title"],
        "lang": config["site"]["language"],
        "year": datetime.now().year,
        "navigation": config.get("nav", {}).get("main", []),
        "user_authenticated": editor_mode,
        "noindex": preview,
        "preview": preview,
        "comments": [],
        "title": "Sitemap",
        "description": "HTML sitemap of public pages for people, crawlers, and agents.",
        "canonical_url": canonical_url,
        "current_path": "/sitemap/",
        "sections": html_sitemap_sections(grouped),
        "products": products or [],
        "jsonld": default_jsonld(
            config,
            title="Sitemap",
            url=canonical_url,
            description="HTML sitemap of public pages for people, crawlers, and agents.",
        ),
        "build_time": build_time.strftime("%B %d, %Y at %I:%M %p"),
        "build_time_iso": build_time.isoformat(),
        "page_type": "sitemap",
        "category": "pages",
        "slug": "sitemap",
    }
    html = template_engine.render("sitemap.html", context)
    if live_reload_html:
        html = _inject(html, live_reload_html)
    html = stamp_page_size(html)
    output = output_file_for_url(dist_path, "/sitemap/")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html)


def write_search_page(
    config: Dict[str, Any],
    grouped: Dict[str, List[Dict[str, Any]]],
    dist_path: Path,
    template_engine: TemplateEngine,
    *,
    preview: bool,
    editor_mode: bool = False,
    live_reload_html: str = "",
) -> None:
    build_time = datetime.now()
    canonical_url = f"{config['site']['url'].rstrip('/')}/search/"
    items = sorted(
        [item for item in (grouped.get("all") or []) if item.get("url") and item.get("title")],
        key=lambda item: (item.get("title") or "").lower(),
    )
    context = {
        "site_title": config["site"]["title"],
        "lang": config["site"]["language"],
        "year": datetime.now().year,
        "navigation": config.get("nav", {}).get("main", []),
        "user_authenticated": editor_mode,
        "noindex": preview,
        "preview": preview,
        "comments": [],
        "title": "Search",
        "description": "Search public GANG pages.",
        "canonical_url": canonical_url,
        "current_path": "/search/",
        "items": items,
        "query": "",
        "jsonld": default_jsonld(
            config,
            title="Search",
            url=canonical_url,
            description="Search public GANG pages.",
        ),
        "build_time": build_time.strftime("%B %d, %Y at %I:%M %p"),
        "build_time_iso": build_time.isoformat(),
        "page_type": "search",
        "category": "pages",
        "slug": "search",
    }
    html = template_engine.render("search.html", context)
    if live_reload_html:
        html = _inject(html, live_reload_html)
    html = stamp_page_size(html)
    output = output_file_for_url(dist_path, "/search/")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html)


def default_jsonld(config: Dict[str, Any], *, title: str, url: str, description: str, page_type: str = "WebPage") -> Dict[str, Any]:
    site_url = config["site"]["url"].rstrip("/")
    return {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "WebSite",
                "name": config["site"]["title"],
                "url": f"{site_url}/",
                "description": config["site"]["description"],
            },
            {
                "@type": page_type,
                "name": title,
                "url": url,
                "description": description,
                "isPartOf": {"@type": "WebSite", "url": f"{site_url}/"},
            },
        ],
    }


def stamp_page_size(html: str, placeholder: str = "__PAGE_SIZE__") -> str:
    if placeholder not in html:
        return html
    label = format_bytes(len(html.replace(placeholder, "").encode("utf-8")))
    return html.replace(placeholder, label)


def format_bytes(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    kilobytes = size / 1024
    if kilobytes < 10:
        return f"{kilobytes:.1f} KB"
    return f"{kilobytes:.0f} KB"


def _inject(html: str, snippet: str) -> str:
    if snippet in html:
        return html
    if "</body>" in html:
        return html.replace("</body>", snippet + "</body>")
    return html + snippet
