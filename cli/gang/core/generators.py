"""
GANG Output Generators
Generate sitemap.xml, robots.txt, feed.json, etc.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

class OutputGenerators:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.site = config.get('site', {})
        self.site_url = self.site.get('url', 'https://example.com')
    
    def generate_sitemap(self, pages: List[Dict[str, Any]]) -> str:
        """Generate sitemap.xml with unique locs and W3C lastmod dates."""
        urlset = Element("urlset")
        urlset.set("xmlns", "http://www.sitemaps.org/schemas/sitemap/0.9")
        seen = set()
        for page in pages:
            loc_path = page.get("url") or "/"
            if not loc_path.startswith("/"):
                loc_path = "/" + loc_path
            if loc_path in seen:
                continue
            seen.add(loc_path)
            url = SubElement(urlset, "url")
            loc = SubElement(url, "loc")
            loc.text = f"{self.site_url.rstrip('/')}{loc_path}"
            lastmod = _w3c_date(page.get("date") or page.get("updated") or page.get("lastmod"))
            if lastmod:
                node = SubElement(url, "lastmod")
                node.text = lastmod
            priority = SubElement(url, "priority")
            priority.text = _sitemap_priority(loc_path, page.get("type"))
            changefreq = SubElement(url, "changefreq")
            changefreq.text = _sitemap_changefreq(loc_path, page.get("type"))
        xml_str = tostring(urlset, encoding="unicode")
        return minidom.parseString(xml_str).toprettyxml(indent="  ")

    def generate_robots(self, preview: bool = False) -> str:
        if preview:
            return """User-agent: *
Disallow: /
"""
        base = self.site_url.rstrip("/")
        return f"""User-agent: *
Allow: /

Sitemap: {base}/sitemap.xml

# Answer engines / agents: {base}/llms.txt {base}/agentmap.json {base}/feed.json
"""

    def generate_llms_txt(self, pages: List[Dict[str, Any]]) -> str:
        """Plain-text map for answer engines (https://llmstxt.org)."""
        title = self.site.get("title", "Site")
        description = self.site.get("description", "")
        base = self.site_url.rstrip("/")
        lines = [
            f"# {title}",
            f"> {description}",
            "",
            "Public studio site. Private lab notes and source mappings are not published.",
            "",
            "## Primary navigation",
            f"- [Home]({base}/)",
            f"- [Studio]({base}/studio/)",
            f"- [About]({base}/about/)",
            f"- [Objects]({base}/objects/)",
            f"- [Research]({base}/research/)",
            f"- [Journal]({base}/journal/)",
            f"- [Team]({base}/team/)",
            f"- [FAQ]({base}/pages/faq/)",
            f"- [Contact]({base}/pages/contact/)",
            f"- [Cart]({base}/cart/)",
            "",
            "## All public URLs",
        ]
        for page in sorted(pages, key=lambda item: item.get("url") or ""):
            path = page.get("url") or "/"
            name = page.get("title") or path
            lines.append(f"- [{name}]({base}{path})")
        lines.extend(
            [
                "",
                "## Machine-readable",
                f"- Sitemap: {base}/sitemap.xml",
                f"- HTML sitemap: {base}/sitemap/",
                f"- AgentMap: {base}/agentmap.json",
                f"- JSON Feed: {base}/feed.json",
            ]
        )
        return "\n".join(lines) + "\n"
    
    def generate_feed_json(self, posts: List[Dict[str, Any]]) -> str:
        """Generate JSON Feed (https://jsonfeed.org)"""
        feed = {
            "version": "https://jsonfeed.org/version/1.1",
            "title": self.site.get('title', ''),
            "home_page_url": self.site_url,
            "feed_url": f"{self.site_url}/feed.json",
            "description": self.site.get('description', ''),
            "language": self.site.get('language', 'en'),
            "items": []
        }
        
        for post in posts:
            # Convert date to string if needed
            date_val = post.get('date', '')
            if date_val and not isinstance(date_val, str):
                date_val = str(date_val)
            
            item = {
                "id": f"{self.site_url}{post['url']}",
                "url": f"{self.site_url}{post['url']}",
                "title": post.get('title', ''),
                "content_html": post.get('content_html', ''),
                "summary": post.get('summary', ''),
                "date_published": date_val,
            }
            
            if post.get('tags'):
                item['tags'] = post['tags']
            
            feed['items'].append(item)
        
        return json.dumps(feed, indent=2)
    
    def generate_agentmap(self) -> str:
        """Generate agentmap.json for AI agents"""
        agentmap = {
            "version": "1.0",
            "site": {
                "name": self.site.get('title', ''),
                "url": self.site_url,
                "description": self.site.get('description', ''),
            },
            "content_types": [],
            "navigation": self.config.get('nav', {}).get('main', []),
            "feeds": [
                {"type": "json", "url": f"{self.site_url}/feed.json"},
                {"type": "sitemap", "url": f"{self.site_url}/sitemap.xml"},
            ],
            "endpoints": {
                "sitemap": f"{self.site_url.rstrip('/')}/sitemap.xml",
                "htmlSitemap": f"{self.site_url.rstrip('/')}/sitemap/",
                "llmsTxt": f"{self.site_url.rstrip('/')}/llms.txt",
                "agentmap": f"{self.site_url.rstrip('/')}/agentmap.json",
                "feed": f"{self.site_url.rstrip('/')}/feed.json",
            },
        }
        
        # Add content types
        types = self.config.get('types', {})
        for type_name, type_config in types.items():
            agentmap['content_types'].append({
                "name": type_name,
                "fields": type_config.get('fields', [])
            })
        
        return json.dumps(agentmap, indent=2)

    def generate_all(self, dist_path: Path, pages: List[Dict[str, Any]], posts: List[Dict[str, Any]], preview: bool = False):
        """Generate all output files"""
        sitemap_xml = self.generate_sitemap(pages)
        (dist_path / "sitemap.xml").write_text(sitemap_xml)

        robots_txt = self.generate_robots(preview=preview)
        (dist_path / "robots.txt").write_text(robots_txt)

        feed_json = self.generate_feed_json(posts)
        (dist_path / "feed.json").write_text(feed_json)

        agentmap_json = self.generate_agentmap()
        (dist_path / "agentmap.json").write_text(agentmap_json)
        (dist_path / "llms.txt").write_text(self.generate_llms_txt(pages))


def _w3c_date(value: Any) -> Optional[str]:
    if not value:
        return None
    match = re.match(r"(\d{4}-\d{2}-\d{2})", str(value))
    return match.group(1) if match else None


def _sitemap_priority(url: str, type_name: Any) -> str:
    if url == "/":
        return "1.0"
    if url in {"/objects/", "/research/", "/journal/", "/studio/", "/about/", "/team/", "/pages/faq/", "/pages/contact/"}:
        return "0.9"
    if url == "/cart/" or url == "/search/":
        return "0.4"
    if type_name in {"objects", "research", "journal", "object"}:
        return "0.8"
    return "0.6"


def _sitemap_changefreq(url: str, type_name: Any) -> str:
    if url == "/":
        return "weekly"
    if url.endswith("/") and url.count("/") == 2:
        return "weekly"
    if type_name in {"objects", "research", "journal"}:
        return "monthly"
    return "monthly"

