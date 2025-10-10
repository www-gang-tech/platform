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
                if not isinstance(date_val, str):
                    date_val = str(date_val)
                lastmod.text = date_val
            
            # Priority based on page type
            priority = SubElement(url, 'priority')
            if page['url'] == '/':
                priority.text = '1.0'
            elif page.get('type') == 'post':
                priority.text = '0.8'
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
        # Sitemap
        sitemap_xml = self.generate_sitemap(pages + posts)
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

