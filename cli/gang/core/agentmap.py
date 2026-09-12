"""
GANG AgentMap Generator
Create navigation maps for AI agents to discover and interact with content.
"""

from pathlib import Path
from typing import Any, Dict, List
from datetime import datetime, timezone
import json

_PUBLIC_METADATA_KEYS = (
    'title',
    'description',
    'summary',
    'seo_description',
    'date',
    'publish_date',
    'sent_date',
    'updated',
    'author',
    'category',
    'tags',
    'status',
    'image',
    'canonical',
    'slug',
)


def _public_content_metadata(frontmatter: Dict[str, Any]) -> Dict[str, Any]:
    """Allowlist scalar frontmatter for the Content API — never emit raw YAML."""
    if not isinstance(frontmatter, dict):
        return {}
    try:
        from core.html_sanitize import safe_http_url
    except ImportError:
        from gang.core.html_sanitize import safe_http_url
    out: Dict[str, Any] = {}
    for key in _PUBLIC_METADATA_KEYS:
        if key not in frontmatter:
            continue
        value = frontmatter[key]
        if key in ('image', 'canonical'):
            out[key] = safe_http_url(value) if isinstance(value, str) else ''
        elif key == 'tags':
            if isinstance(value, list):
                out[key] = [str(tag) for tag in value if isinstance(tag, (str, int))]
            elif isinstance(value, str) and value.strip():
                out[key] = [value]
        elif hasattr(value, 'isoformat'):
            out[key] = value.isoformat()
        elif isinstance(value, (str, int, float, bool)) or value is None:
            out[key] = value
    return out


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
        catalog = products or []
        
        agentmap = {
            '@context': 'https://schema.org',
            '@type': 'WebSite',
            'version': '1.0',
            'generated': datetime.now(timezone.utc).isoformat(),
            'name': self.config.get('site', {}).get('title', 'Site'),
            'url': self.site_url,
            'description': self.config.get('site', {}).get('description', ''),
            
            'capabilities': capabilities,
            
            'endpoints': {
                'content': f"{self.site_url}/api/content.json",
                'search': f"{self.site_url}/search-index.json",
                'sitemap': f"{self.site_url}/sitemap.xml",
                'products': f"{self.site_url}/api/products.json",
            },
            
            'contentTypes': content_map['types'],
            
            'navigation': {
                'main': self._build_navigation(content_map),
                'content': content_map['by_category']
            },
            
            'search': {
                'endpoint': f"{self.site_url}/search-index.json",
                'method': 'GET',
                'parameters': [],
                'description': 'Static search index JSON; filter client-side'
            }
        }
        
        agentmap['commerce'] = {
            'enabled': bool(catalog),
            'productsEndpoint': f"{self.site_url}/api/products.json",
            'platforms': self._detect_platforms(catalog) if catalog else [],
            'totalProducts': len(catalog),
        }
        
        return agentmap
    
    def _map_content(self, content_files: List[Path]) -> Dict[str, Any]:
        """Map content files by category and type"""
        by_category = {}
        types = []
        # Build/serve emit list pages for these; /pages/ is never written.
        list_index_categories = {'posts', 'projects', 'people', 'newsletters'}
        
        for file_path in content_files:
            category = file_path.parent.name
            public_category = 'posts' if category == 'articles' else category
            
            if public_category not in by_category:
                by_category[public_category] = []
                types.append({
                    'type': public_category,
                    'url': (
                        f"{self.site_url}/{public_category}/"
                        if public_category in list_index_categories
                        else ''
                    ),
                    'apiEndpoint': f"{self.site_url}/api/{public_category}.json"
                })
            
            slug = file_path.stem
            by_category[public_category].append({
                'slug': slug,
                'url': f"{self.site_url}/{public_category}/{slug}/",
                'apiEndpoint': f"{self.site_url}/api/{public_category}/{slug}.json"
            })

        for content_type in types:
            if content_type.get('url'):
                continue
            items = by_category.get(content_type.get('type')) or []
            if items:
                content_type['url'] = items[0].get('url') or ''
        
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
        try:
            from core.scheduler import strip_frontmatter_prefix
        except ImportError:
            from gang.core.scheduler import strip_frontmatter_prefix
        
        index = {
            'version': '1.0',
            'generated': datetime.now(timezone.utc).isoformat(),
            'totalItems': len(content_files),
            'items': []
        }
        
        for file_path in content_files:
            try:
                content = strip_frontmatter_prefix(file_path.read_text())
                
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
                meta = _public_content_metadata(frontmatter)
                title = meta.get('title')
                if not isinstance(title, str) or not title.strip():
                    title = slug.replace('-', ' ').title()
                summary = meta.get('summary') or meta.get('description') or ''
                if not isinstance(summary, str):
                    summary = ''
                date_val = (
                    meta.get('date')
                    or meta.get('publish_date')
                    or meta.get('sent_date')
                    or ''
                )
                item = {
                    'title': title,
                    'url': f"{self.site_url}/{public_category}/{slug}/",
                    'apiEndpoint': f"{self.site_url}/api/{public_category}/{slug}.json",
                    'category': public_category,
                    'slug': slug,
                    'summary': summary,
                    'date': str(date_val or ''),
                    'tags': meta.get('tags') or [],
                }
                
                index['items'].append(item)
            
            except Exception as e:
                raise RuntimeError(f'Content API index failed for {file_path}: {e}') from e

        index['totalItems'] = len(index['items'])
        return index
    
    def generate_single_content_api(
        self,
        file_path: Path,
        content_path: Path
    ) -> Dict[str, Any]:
        """Generate API JSON for a single content file"""
        import yaml
        import markdown
        try:
            from core.scheduler import strip_frontmatter_prefix
        except ImportError:
            from gang.core.scheduler import strip_frontmatter_prefix
        
        content = strip_frontmatter_prefix(file_path.read_text())
        
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
            'metadata': _public_content_metadata(frontmatter),
            'content': {
                'html': content_html,
                'text': content_text,
                'markdown': body
            },
            'retrieved': datetime.now(timezone.utc).isoformat()
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
            except Exception as e:
                raise RuntimeError(f'Content API failed for {file_path}: {e}') from e
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

