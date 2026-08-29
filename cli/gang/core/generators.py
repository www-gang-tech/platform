"""
GANG Output Generators
Generate sitemap.xml, robots.txt, feed.json, etc.
"""

import json
from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom

class OutputGenerators:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.site = config.get('site', {})
        self.site_url = self.site.get('url', 'https://example.com')
    
    def generate_sitemap(self, pages: List[Dict[str, Any]]) -> str:
        """Generate sitemap.xml"""
        urlset = Element('urlset')
        urlset.set('xmlns', 'http://www.sitemaps.org/schemas/sitemap/0.9')
        
        for page in pages:
            url = SubElement(urlset, 'url')
            
            loc = SubElement(url, 'loc')
            loc.text = f"{self.site_url}{page['url']}"
            
            if page.get('date'):
                lastmod = SubElement(url, 'lastmod')
                date_val = page['date']
                if hasattr(date_val, 'date') and callable(getattr(date_val, 'date', None)):
                    try:
                        date_val = date_val.date().isoformat()
                    except Exception:
                        date_val = str(date_val)
                elif hasattr(date_val, 'isoformat'):
                    try:
                        date_val = date_val.isoformat()
                    except Exception:
                        date_val = str(date_val)
                else:
                    date_val = str(date_val)
                date_val = date_val.strip()
                if len(date_val) >= 10 and date_val[4] == '-':
                    date_val = date_val[:10]
                lastmod.text = date_val
            
            # Priority based on page type
            priority = SubElement(url, 'priority')
            if page['url'] == '/':
                priority.text = '1.0'
            elif page.get('type') in ('post', 'posts', 'article', 'articles'):
                priority.text = '0.8'
            elif page.get('type') == 'product':
                priority.text = '0.7'
            else:
                priority.text = '0.6'
            
            changefreq = SubElement(url, 'changefreq')
            changefreq.text = 'weekly'
        
        # Pretty print XML
        xml_str = tostring(urlset, encoding='unicode')
        dom = minidom.parseString(xml_str)
        return dom.toprettyxml(indent="  ")
    
    def generate_robots(self) -> str:
        """Generate robots.txt"""
        return f"""User-agent: *
Allow: /

Sitemap: {self.site_url}/sitemap.xml
"""
    
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
            # Convert date to RFC 3339 / ISO 8601 (JSON Feed 1.1)
            date_val = post.get('date', '')
            if date_val and hasattr(date_val, 'isoformat'):
                date_val = date_val.isoformat()
            elif date_val and not isinstance(date_val, str):
                date_val = str(date_val)
            if isinstance(date_val, str):
                date_val = date_val.strip()
                if len(date_val) >= 19 and date_val[10] == ' ':
                    date_val = date_val[:10] + 'T' + date_val[11:]
                if date_val.endswith(('Z', 'z')):
                    date_val = date_val[:-1] + '+00:00'
            
            item = {
                "id": f"{self.site_url}{post['url']}",
                "url": f"{self.site_url}{post['url']}",
                "title": post.get('title', ''),
                "content_html": post.get('content_html', ''),
                "summary": post.get('summary', ''),
            }
            if date_val not in (None, ''):
                item['date_published'] = date_val
            
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
                {"type": "sitemap", "url": f"{self.site_url}/sitemap.xml"}
            ]
        }
        
        # Add content types
        types = self.config.get('types', {})
        for type_name, type_config in types.items():
            agentmap['content_types'].append({
                "name": type_name,
                "fields": type_config.get('fields', [])
            })
        
        return json.dumps(agentmap, indent=2)
    
    def generate_all(self, dist_path: Path, pages: List[Dict[str, Any]], posts: List[Dict[str, Any]]):
        """Generate all output files"""
        # Sitemap (pages already includes all content, don't add posts again)
        sitemap_xml = self.generate_sitemap(pages)
        (dist_path / 'sitemap.xml').write_text(sitemap_xml)
        
        # Robots
        robots_txt = self.generate_robots()
        (dist_path / 'robots.txt').write_text(robots_txt)
        
        # JSON Feed
        feed_json = self.generate_feed_json(posts)
        (dist_path / 'feed.json').write_text(feed_json)
        
        # Agentmap
        agentmap_json = self.generate_agentmap()
        (dist_path / 'agentmap.json').write_text(agentmap_json)

