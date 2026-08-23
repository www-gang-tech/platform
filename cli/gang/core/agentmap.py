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
                'search': f"{self.site_url}/search-index.json",
                'sitemap': f"{self.site_url}/sitemap.xml"
            },
            
            'contentTypes': content_map['types'],
            
            'navigation': {
                'main': self._build_navigation(content_map),
                'content': content_map['by_category']
            },
            
            'search': {
                'endpoint': f"{self.site_url}/search-index.json",
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
            public_category = 'posts' if category == 'articles' else category
            
            if public_category not in by_category:
                by_category[public_category] = []
                types.append({
                    'type': public_category,
                    'url': f"{self.site_url}/{public_category}/",
                    'apiEndpoint': f"{self.site_url}/api/{public_category}.json"
                })
            
            slug = file_path.stem
            by_category[public_category].append({
                'slug': slug,
                'url': f"{self.site_url}/{public_category}/{slug}/",
                'apiEndpoint': f"{self.site_url}/api/{public_category}/{slug}.json"
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
                
                if not isinstance(frontmatter, dict):
                    frontmatter = {}
                category = file_path.parent.name
                slug = file_path.stem
                public_category = 'posts' if category == 'articles' else category
                
                item = {
                    'title': frontmatter.get('title', slug.replace('-', ' ').title()),
                    'url': f"{self.site_url}/{public_category}/{slug}/",
                    'apiEndpoint': f"{self.site_url}/api/{public_category}/{slug}.json",
                    'category': public_category,
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
        if not isinstance(frontmatter, dict):
            frontmatter = {}
        
        # Convert markdown to HTML
        md = markdown.Markdown(extensions=['extra'])
        content_html = md.convert(body)
        try:
            from core.html_sanitize import sanitize_markdown_html, sanitize_content_hrefs
        except ImportError:
            from gang.core.html_sanitize import sanitize_markdown_html, sanitize_content_hrefs
        content_html = sanitize_content_hrefs(sanitize_markdown_html(content_html))
        
        # Also provide plain text
        import re
        content_text = re.sub('<[^<]+?>', '', content_html)
        
        category = file_path.parent.name
        slug = file_path.stem
        public_category = 'posts' if category == 'articles' else category
        
        return {
            'title': frontmatter.get('title', slug.replace('-', ' ').title()),
            'url': f"{self.site_url}/{public_category}/{slug}/",
            'category': public_category,
            'slug': slug,
            'metadata': frontmatter,
            'content': {
                'html': content_html,
                'text': content_text,
                'markdown': body
            },
            'retrieved': datetime.now().isoformat()
        }

    def write_content_apis(
        self,
        content_files: List[Path],
        content_path: Path,
        dest_dir: Path,
        safe_slug=None,
    ) -> int:
        """Write advertised /api/{category}.json and /api/{category}/{slug}.json files."""
        import re

        dest_dir.mkdir(parents=True, exist_ok=True)
        slug_re = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
        by_category: Dict[str, List[Dict[str, Any]]] = {}
        written = 0
        for file_path in content_files:
            try:
                item = self.generate_single_content_api(file_path, content_path)
            except Exception:
                continue
            category = str(item.get('category') or '')
            slug = str(item.get('slug') or '')
            if not category or not slug_re.match(category):
                continue
            if not slug_re.match(slug) or '..' in slug:
                continue
            if safe_slug and not safe_slug(slug):
                continue
            category_dir = dest_dir / category
            category_dir.mkdir(parents=True, exist_ok=True)
            (category_dir / f'{slug}.json').write_text(
                json.dumps(item, indent=2, default=str)
            )
            by_category.setdefault(category, []).append({
                'slug': slug,
                'url': item.get('url'),
                'title': item.get('title'),
                'apiEndpoint': f"{self.site_url}/api/{category}/{slug}.json",
            })
            written += 1
        for category, items in by_category.items():
            (dest_dir / f'{category}.json').write_text(json.dumps({
                'category': category,
                'count': len(items),
                'items': items,
            }, indent=2, default=str))
        return written

