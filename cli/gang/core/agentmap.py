"""
GANG AgentMap Generator
Create navigation maps for AI agents to discover and interact with content.
"""

from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime
import json


class AgentMapGenerator:
    """Generate AgentMap.json for AI agent navigation"""
    
    def __init__(self, config: Dict[str, Any], site_url: str):
        self.config = config
        self.site_url = site_url.rstrip('/')
    
    def generate(
        self, 
        content_files: List[Path],
        products: List[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate AgentMap - a machine-readable navigation map for AI agents.
        Based on principles from sitemap.xml but designed for AI interaction.
        """
        
        # Organize content by type
        content_map = self._map_content(content_files)
        
        # Build capabilities list
        capabilities = ['read', 'search']
        if products:
            capabilities.append('purchase')
        
        agentmap = {
            '@context': 'https://schema.org',
            '@type': 'WebSite',
            'version': '1.0',
            'generated': datetime.now().isoformat(),
            'name': self.config.get('site', {}).get('title', 'Site'),
            'url': self.site_url,
            'description': self.config.get('site', {}).get('description', ''),
            
            'capabilities': capabilities,
            
            'endpoints': {
                'api': f"{self.site_url}/api/",
                'content': f"{self.site_url}/api/content.json",
                'search': f"{self.site_url}/api/search.json",
                'sitemap': f"{self.site_url}/sitemap.xml"
            },
            
            'contentTypes': content_map['types'],
            
            'navigation': {
                'main': self._build_navigation(content_map),
                'content': content_map['by_category']
            },
            
            'search': {
                'endpoint': f"{self.site_url}/api/search.json",
                'method': 'GET',
                'parameters': ['q', 'category', 'limit'],
                'description': 'Full-text search across all content'
            }
        }
        
        # Add products if available
        if products:
            agentmap['endpoints']['products'] = f"{self.site_url}/api/products.json"
            agentmap['commerce'] = {
                'enabled': True,
                'productsEndpoint': f"{self.site_url}/api/products.json",
                'platforms': self._detect_platforms(products),
                'totalProducts': len(products)
            }
        
        return agentmap
    
    def _map_content(self, content_files: List[Path]) -> Dict[str, Any]:
        """Map content files by category and type"""
        by_category = {}
        types = []
        
        for file_path in content_files:
            category = file_path.parent.name
            
            if category not in by_category:
                by_category[category] = []
                types.append({
                    'type': category,
                    'url': f"{self.site_url}/{category}/",
                    'apiEndpoint': f"{self.site_url}/api/{category}.json"
                })
            
            slug = file_path.stem
            by_category[category].append({
                'slug': slug,
                'url': f"{self.site_url}/{category}/{slug}/",
                'apiEndpoint': f"{self.site_url}/api/{category}/{slug}.json"
            })
        
        return {
            'types': types,
            'by_category': by_category
        }
    
    def _build_navigation(self, content_map: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Build main navigation structure"""
        nav = []
        
        for content_type in content_map['types']:
            nav.append({
                'label': content_type['type'].title(),
                'url': content_type['url'],
                'type': content_type['type']
            })
        
        return nav
    
    def _detect_platforms(self, products: List[Dict[str, Any]]) -> List[str]:
        """Detect which platforms are being used"""
        platforms = set()
        
        for product in products:
            source = product.get('_meta', {}).get('source')
            if source:
                platforms.add(source)
        
        return list(platforms)


class ContentAPIGenerator:
    """Generate JSON API endpoints for all content"""
    
    def __init__(self, site_url: str):
        self.site_url = site_url.rstrip('/')
    
    def generate_content_index(
        self,
        content_files: List[Path],
        content_path: Path
    ) -> Dict[str, Any]:
        """Generate master content index API"""
        import yaml
        
        index = {
            'version': '1.0',
            'generated': datetime.now().isoformat(),
            'totalItems': len(content_files),
            'items': []
        }
        
        for file_path in content_files:
            try:
                content = file_path.read_text()
                
                # Parse frontmatter
                frontmatter = {}
                if content.startswith('---'):
                    parts = content.split('---', 2)
                    if len(parts) >= 3:
                        frontmatter = yaml.safe_load(parts[1]) or {}
                
                category = file_path.parent.name
                slug = file_path.stem
                
                item = {
                    'title': frontmatter.get('title', slug.replace('-', ' ').title()),
                    'url': f"{self.site_url}/{category}/{slug}/",
                    'apiEndpoint': f"{self.site_url}/api/{category}/{slug}.json",
                    'category': category,
                    'slug': slug,
                    'summary': frontmatter.get('summary', frontmatter.get('description', '')),
                    'date': str(frontmatter.get('date', '')),
                    'tags': frontmatter.get('tags', [])
                }
                
                index['items'].append(item)
            
            except Exception as e:
                continue
        
        return index
    
    def generate_single_content_api(
        self,
        file_path: Path,
        content_path: Path
    ) -> Dict[str, Any]:
        """Generate API JSON for a single content file"""
        import yaml
        import markdown
        
        content = file_path.read_text()
        
        # Parse frontmatter
        frontmatter = {}
        body = content
        
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                frontmatter = yaml.safe_load(parts[1]) or {}
                body = parts[2]
        
        # Convert markdown to HTML
        md = markdown.Markdown(extensions=['extra'])
        content_html = md.convert(body)
        
        # Also provide plain text
        import re
        content_text = re.sub('<[^<]+?>', '', content_html)
        
        category = file_path.parent.name
        slug = file_path.stem
        
        return {
            'title': frontmatter.get('title', slug.replace('-', ' ').title()),
            'url': f"{self.site_url}/{category}/{slug}/",
            'category': category,
            'slug': slug,
            'metadata': frontmatter,
            'content': {
                'html': content_html,
                'text': content_text,
                'markdown': body
            },
            'retrieved': datetime.now().isoformat()
        }

