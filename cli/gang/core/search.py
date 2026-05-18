"""
GANG Static Site Search
Generate search index and provide search functionality.
"""

from pathlib import Path
from typing import Dict, List, Any
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
        
        date_value = frontmatter.get('date', '')
        if date_value and not isinstance(date_value, str):
            date_value = str(date_value)
        
        return {
            'id': str(file_path.relative_to(self.content_path)) if isinstance(file_path, Path) else str(file_path),
            'title': title,
            'description': description,
            'url': url,
            'category': category,
            'tags': tags,
            'content': clean_text[:500],  # First 500 chars for preview
            'searchable': searchable.lower(),  # Lowercase for case-insensitive search
            'date': date_value,
        }
    
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
    
    def generate_search_page_html(self) -> str:
        """Generate a static, no-JS landing page for the search index."""
        site = self.config.get('site', {})
        site_title = site.get('title', 'Site')
        site_url = site.get('url', 'https://example.com')
        language = site.get('language', 'en')
        description = f"Search index and content discovery for {site_title}."
        jsonld = {
            "@context": "https://schema.org",
            "@type": "WebPage",
            "name": "Search",
            "description": description,
            "url": f"{site_url}/search/"
        }
        
        return f'''<!DOCTYPE html>
<html lang="{language}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'self'; img-src 'self' data:; font-src 'self'; base-uri 'self'; form-action 'self';">
    <title>Search - {site_title}</title>
    <meta name="description" content="{description}">
    <link rel="canonical" href="{site_url}/search/">
    <script type="application/ld+json">
{json.dumps(jsonld, indent=2)}
    </script>
    <link rel="stylesheet" href="/assets/style.css">
</head>
<body>
    <header role="banner">
        <nav role="navigation" aria-label="Main navigation">
            <a href="/">{site_title}</a>
            <a href="/posts/">Posts</a>
            <a href="/projects/">Projects</a>
            <a href="/pages/about/">About</a>
        </nav>
    </header>
    <main>
        <h1>Search</h1>
        <p>This site publishes a machine-readable search index for agents and static tooling.</p>
        <p><a href="/search-index.json">Download the search index</a>.</p>
    </main>
    <footer>
        <p>&copy; {datetime.now().year} {site_title}. Built with GANG.</p>
    </footer>
</body>
</html>'''

