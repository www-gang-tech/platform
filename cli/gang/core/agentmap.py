"""
GANG AgentMap Generator
Create navigation maps for AI agents to discover and interact with content.
"""

from pathlib import Path
from typing import Dict, List, Any
from datetime import datetime
import json


def _json_safe(value: Any) -> Any:
    """Coerce YAML date/datetime values for json.dumps."""
    if hasattr(value, 'isoformat') and not isinstance(value, str):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _as_title(value: Any, fallback: str) -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


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
                'description': 'Static full-text search index across all generated content'
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
    
    def _published_category(self, category: str) -> str:
        return 'posts' if category == 'articles' else category
    
    def _map_content(self, content_files: List[Path]) -> Dict[str, Any]:
        """Map content files by category and type"""
        by_category = {}
        types = []
        
        for file_path in content_files:
            category = self._published_category(file_path.parent.name)
            
            if category not in by_category:
                by_category[category] = []
                types.append({
                    'type': category,
                    'url': f"{self.site_url}/{category}/",
                    'apiEndpoint': f"{self.site_url}/api/content.json"
                })
            
            slug = file_path.stem
            by_category[category].append({
                'slug': slug,
                'url': f"{self.site_url}/{category}/{slug}/",
                'apiEndpoint': f"{self.site_url}/api/content.json"
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
                
                # Parse frontmatter (null/empty YAML must not become non-dict)
                try:
                    from core.frontmatter import parse_frontmatter
                except ImportError:  # pragma: no cover
                    from frontmatter import parse_frontmatter
                frontmatter, _body = parse_frontmatter(content)
                
                category = 'posts' if file_path.parent.name == 'articles' else file_path.parent.name
                slug = file_path.stem
                
                summary = frontmatter.get('summary')
                if summary is None:
                    summary = frontmatter.get('description')
                item = {
                    'title': _as_title(frontmatter.get('title'), slug.replace('-', ' ').title()),
                    'url': f"{self.site_url}/{category}/{slug}/",
                    'apiEndpoint': f"{self.site_url}/api/content.json",
                    'category': category,
                    'slug': slug,
                    'summary': '' if summary is None else str(summary),
                    'date': '' if frontmatter.get('date') in (None, '') else str(frontmatter.get('date')),
                    'tags': self._normalize_tags(frontmatter.get('tags', []))
                }
                
                index['items'].append(item)
            
            except Exception as e:
                continue
        
        return index
    
    def _normalize_tags(self, tags: Any) -> List[str]:
        if tags is None:
            return []
        if type(tags).__name__ in ('list', 'tuple', 'set'):
            return [str(tag) for tag in tags if tag is not None]
        return [str(tags)]
    
    def generate_single_content_api(
        self,
        file_path: Path,
        content_path: Path
    ) -> Dict[str, Any]:
        """Generate API JSON for a single content file"""
        import markdown
        
        content = file_path.read_text()
        try:
            from core.frontmatter import parse_frontmatter
        except ImportError:  # pragma: no cover
            from frontmatter import parse_frontmatter
        frontmatter, body = parse_frontmatter(content)
        
        # Convert markdown to HTML (sanitize before any consumer renders |safe)
        md = markdown.Markdown(extensions=['extra'])
        content_html = md.convert(body)
        try:
            from core.html_sanitize import sanitize_markdown_html, sanitize_content_hrefs
        except ImportError:  # pragma: no cover
            from html_sanitize import sanitize_markdown_html, sanitize_content_hrefs
        content_html = sanitize_content_hrefs(sanitize_markdown_html(content_html))
        
        # Also provide plain text
        import re
        content_text = re.sub('<[^<]+?>', '', content_html)
        
        category = 'posts' if file_path.parent.name == 'articles' else file_path.parent.name
        slug = file_path.stem
        
        return {
            'title': _as_title(frontmatter.get('title'), slug.replace('-', ' ').title()),
            'url': f"{self.site_url}/{category}/{slug}/",
            'category': category,
            'slug': slug,
            'metadata': _json_safe(frontmatter),
            'content': {
                'html': content_html,
                'text': content_text,
                'markdown': body
            },
            'retrieved': datetime.now().isoformat()
        }

