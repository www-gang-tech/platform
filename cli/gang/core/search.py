"""
GANG Static Site Search
Generate search index and provide search functionality.
"""

from pathlib import Path
from typing import Dict, List, Any
import json
import re
from datetime import datetime
from html import escape
import yaml


class SearchIndexer:
    """Generate search index for static site"""
    
    def __init__(self, content_path: Path, config: Dict[str, Any]):
        self.content_path = content_path
        self.config = config
    
    def build_search_index(self, content_files: List[Path]) -> Dict[str, Any]:
        """
        Build a search index from all publishable content.
        Returns a JSON-serializable index.
        """
        index = {
            'version': '1.0',
            'generated': datetime.now().isoformat(),
            'documents': []
        }
        
        for file_path in content_files:
            try:
                doc = self._index_file(file_path)
                if doc:
                    index['documents'].append(doc)
            except Exception as e:
                # Skip files that can't be indexed
                continue
        
        return index
    
    def _index_file(self, file_path: Path) -> Dict[str, Any]:
        """Index a single markdown file"""
        content = file_path.read_text()
        
        # Parse frontmatter
        frontmatter = {}
        body = content
        
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                try:
                    frontmatter = yaml.safe_load(parts[1]) or {}
                    body = parts[2]
                except:
                    pass
        
        # Extract metadata
        title = self._stringify(frontmatter.get('title'), file_path.stem.replace('-', ' ').title())
        description = self._stringify(frontmatter.get('description') or frontmatter.get('summary'), '')
        tags = self._normalize_tags(frontmatter.get('tags', []))
        category = file_path.parent.name
        
        # Generate URL
        slug = file_path.stem
        if category == 'posts':
            url = f"/posts/{slug}/"
        elif category == 'projects':
            url = f"/projects/{slug}/"
        elif category == 'pages':
            url = f"/pages/{slug}/"
        elif category == 'people':
            url = f"/people/{slug}/"
        else:
            url = f"/{category}/{slug}/"
        
        # Clean body text (remove markdown syntax)
        clean_text = self._clean_markdown(body)
        
        # Extract first paragraph as excerpt if no description
        if not description:
            paragraphs = [p.strip() for p in clean_text.split('\n\n') if p.strip()]
            description = paragraphs[0][:200] + '...' if paragraphs else ''
        
        # Create searchable content (title is weighted more)
        searchable = f"{title} {title} {title} {description} {clean_text} {' '.join(tags)}"
        
        return {
            'id': str(file_path.relative_to(self.content_path)) if isinstance(file_path, Path) else str(file_path),
            'title': title,
            'description': description,
            'url': url,
            'category': category,
            'tags': tags,
            'content': clean_text[:500],  # First 500 chars for preview
            'searchable': searchable.lower(),  # Lowercase for case-insensitive search
            'date': self._stringify(frontmatter.get('date'), ''),
        }
    
    def _stringify(self, value: Any, default: str = '') -> str:
        """Convert YAML scalar values to JSON-safe strings."""
        if value is None:
            return default
        return str(value)
    
    def _normalize_tags(self, tags: Any) -> List[str]:
        """Normalize frontmatter tags into JSON-safe strings."""
        if tags is None:
            return []
        if isinstance(tags, (list, tuple, set)):
            return [str(tag) for tag in tags if tag is not None]
        return [str(tags)]
    
    def _clean_markdown(self, text: str) -> str:
        """Remove markdown syntax from text"""
        # Remove code blocks
        text = re.sub(r'```[\s\S]*?```', '', text)
        text = re.sub(r'`[^`]+`', '', text)
        
        # Remove images
        text = re.sub(r'!\[([^\]]*)\]\([^\)]+\)', r'\1', text)
        
        # Remove links but keep text
        text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
        
        # Remove headings markers
        text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)
        
        # Remove emphasis
        text = re.sub(r'\*\*([^\*]+)\*\*', r'\1', text)
        text = re.sub(r'\*([^\*]+)\*', r'\1', text)
        text = re.sub(r'__([^_]+)__', r'\1', text)
        text = re.sub(r'_([^_]+)_', r'\1', text)
        
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        
        # Clean up whitespace
        text = re.sub(r'\s+', ' ', text)
        
        return text.strip()
    
    def generate_search_page_html(self, documents: List[Dict[str, Any]] = None) -> str:
        """Generate a static, semantic search index page."""
        site = self.config.get('site', {})
        site_title = escape(site.get('title', ''))
        site_description = escape(site.get('description', ''))
        site_url = site.get('url', '').rstrip('/')
        canonical_url = escape(f"{site_url}/search/")
        lang = escape(site.get('language', 'en'))
        documents = documents or []
        items = []
        for document in sorted(documents, key=lambda doc: doc.get('title', '')):
            title = escape(document.get('title', 'Untitled'))
            url = escape(document.get('url', '#'), quote=True)
            description = escape(document.get('description') or document.get('content') or '')
            category = escape(document.get('category', 'content'))
            items.append(
                f'<li><a href="{url}">{title}</a>'
                f'<p><span>{category}</span>{description}</p></li>'
            )
        items_html = '\n'.join(items) if items else '<li>No searchable documents are available.</li>'
        
        html = '''<!DOCTYPE html>
<html lang="__LANG__">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'self'; img-src 'self' https: data:; font-src 'self'; base-uri 'self'; form-action 'self' https:;">
    <title>Search - __SITE_TITLE__</title>
    <meta name="description" content="Search __SITE_TITLE__ content.">
    <link rel="canonical" href="__CANONICAL_URL__">
    <link rel="stylesheet" href="/assets/style.css">
</head>
<body>
    <header role="banner"><a href="/">__SITE_TITLE__</a></header>
    <main>
        <h1>Search</h1>
        <p>__SITE_DESCRIPTION__</p>
        <p>Browse __DOCUMENT_COUNT__ indexed documents. A machine-readable index is available at <a href="/search-index.json">search-index.json</a>.</p>
        <ol>
__DOCUMENTS__
        </ol>
    </main>
    <footer><p>&copy; __YEAR__ __SITE_TITLE__.</p></footer>
</body>
</html>'''
        return (
            html
            .replace('__LANG__', lang)
            .replace('__SITE_TITLE__', site_title)
            .replace('__CANONICAL_URL__', canonical_url)
            .replace('__SITE_DESCRIPTION__', site_description)
            .replace('__DOCUMENT_COUNT__', str(len(documents)))
            .replace('__DOCUMENTS__', items_html)
            .replace('__YEAR__', str(datetime.now().year))
        )

