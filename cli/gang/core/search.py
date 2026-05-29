"""
GANG Static Site Search
Generate search index and provide search functionality.
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
import html
import json
import re
from datetime import datetime
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
        title = frontmatter.get('title', file_path.stem.replace('-', ' ').title())
        description = frontmatter.get('description') or frontmatter.get('summary', '')
        tags = frontmatter.get('tags', [])
        if not isinstance(tags, list):
            tags = [tags] if tags else []
        tags = [str(tag) for tag in tags]
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
            'date': self._stringify_date(frontmatter.get('date', '')),
        }

    def _stringify_date(self, value: Any) -> str:
        """Return a JSON-safe date string for frontmatter values."""
        if not value:
            return ''
        if hasattr(value, 'isoformat'):
            return value.isoformat()
        return str(value)
    
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
    
    def generate_search_page_html(self, search_index: Optional[Dict[str, Any]] = None) -> str:
        """Generate a static, no-JS search index page."""
        site = self.config.get('site', {})
        title = 'Search'
        site_title = html.escape(site.get('title', 'GANG'))
        site_url = site.get('url', '').rstrip('/')
        language = html.escape(site.get('language', 'en'))
        description = 'Browse the static search index for this site.'
        documents = (search_index or {}).get('documents', [])

        items = []
        for doc in documents:
            doc_title = html.escape(str(doc.get('title') or 'Untitled'))
            url = html.escape(str(doc.get('url') or '#'), quote=True)
            category = html.escape(str(doc.get('category') or 'content'))
            summary = html.escape(str(doc.get('description') or doc.get('content') or ''))
            date = html.escape(str(doc.get('date') or ''))
            meta = f'<span>{category}</span>'
            if date:
                meta += f' <span>{date}</span>'
            summary_html = f'<p>{summary}</p>' if summary else ''
            items.append(
                f'<li><h2><a href="{url}">{doc_title}</a></h2>'
                f'<p class="result-meta">{meta}</p>{summary_html}</li>'
            )

        items_html = '\n'.join(items) or '<li>No documents are currently indexed.</li>'
        canonical = f'{site_url}/search/' if site_url else '/search/'
        jsonld = json.dumps({
            '@context': 'https://schema.org',
            '@type': 'CollectionPage',
            'name': title,
            'description': description,
            'url': canonical,
        }, indent=2)

        return f'''<!DOCTYPE html>
<html lang="{language}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - {site_title}</title>
    <meta name="description" content="{html.escape(description, quote=True)}">
    <link rel="canonical" href="{html.escape(canonical, quote=True)}">
    <script type="application/ld+json">
{jsonld}
    </script>
    <link rel="stylesheet" href="/assets/style.css">
</head>
<body>
    <header>
        <nav aria-label="Primary"><a href="/">Home</a></nav>
    </header>
    <main>
        <h1>{title}</h1>
        <p>This page lists indexed content without requiring client-side JavaScript.</p>
        <ol>
            {items_html}
        </ol>
    </main>
    <footer>
        <p>&copy; {datetime.now().year} {site_title}</p>
    </footer>
</body>
</html>'''

