"""
GANG Static Site Search
Generate search index and provide search functionality.
"""

from pathlib import Path
from typing import Dict, List, Any
from html import escape
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
        
        # Extract metadata and normalize YAML values for JSON/search safety.
        title = str(frontmatter.get('title') or file_path.stem.replace('-', ' ').title())
        description = str(frontmatter.get('description') or frontmatter.get('summary') or '')
        raw_tags = frontmatter.get('tags', [])
        if isinstance(raw_tags, (list, tuple, set)):
            tags = [str(tag) for tag in raw_tags if tag is not None]
        elif raw_tags:
            tags = [str(raw_tags)]
        else:
            tags = []
        raw_date = frontmatter.get('date', '')
        date = raw_date.isoformat() if hasattr(raw_date, 'isoformat') else str(raw_date or '')
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
            'date': date,
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
    
    def generate_search_page_html(self, search_index: Dict[str, Any]) -> str:
        """Generate a static search index page without client-side JavaScript."""
        documents = search_index.get('documents', [])
        items = []
        for doc in documents:
            title = escape(str(doc.get('title') or 'Untitled'))
            url = escape(str(doc.get('url') or '#'), quote=True)
            category = escape(str(doc.get('category') or 'content'))
            date = escape(str(doc.get('date') or ''))
            description = escape(str(doc.get('description') or doc.get('content') or ''))
            date_html = f'<span>{date}</span>' if date else ''
            description_html = f'<p>{description}</p>' if description else ''
            items.append(f'''
        <li class="result">
            <h2 class="result-title"><a href="{url}">{title}</a></h2>
            <p class="result-meta"><span class="result-category">{category}</span>{date_html}</p>
            {description_html}
        </li>''')
        results_html = '\n'.join(items) or '<li>No indexed documents found.</li>'

        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Search Index</title>
    <meta name="description" content="Browse the static content index.">
    <script type="application/ld+json">
    {{
      "@context": "https://schema.org",
      "@type": "CollectionPage",
      "name": "Search Index",
      "description": "Browse the static content index.",
      "url": "/search/"
    }}
    </script>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: system-ui, -apple-system, sans-serif;
            line-height: 1.6;
            color: #1a1a1a;
            background: #fff;
            padding: 2rem;
            max-width: 800px;
            margin: 0 auto;
        }}
        header, main, footer {{ display: block; }}
        h1 {{ margin-bottom: 1rem; font-size: 2rem; }}
        .search-stats {{
            margin-bottom: 2rem;
            color: #666;
            font-size: 0.9rem;
        }}
        .result {{
            padding: 1.5rem;
            margin-bottom: 1rem;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            transition: all 0.2s;
        }}
        .result-title {{
            font-size: 1.3rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }}
        .result-title a {{
            color: #0066cc;
            text-decoration: none;
        }}
        .result-title a:hover {{
            text-decoration: underline;
        }}
        .result-meta {{
            font-size: 0.85rem;
            color: #666;
            margin-bottom: 0.5rem;
        }}
        .result p:last-child {{
            color: #333;
            line-height: 1.5;
        }}
        .result-category {{
            display: inline-block;
            padding: 0.25rem 0.5rem;
            background: #e6f2ff;
            color: #0066cc;
            border-radius: 4px;
            font-size: 0.8rem;
            margin-right: 0.5rem;
        }}
        ul {{ list-style: none; }}
        footer {{ margin-top: 3rem; color: #666; }}
    </style>
</head>
<body>
    <header>
        <h1>Search Index</h1>
        <p class="search-stats">{len(documents)} documents indexed</p>
    </header>
    <main>
        <ul>
{results_html}
        </ul>
    </main>
    <footer>
        <p><a href="/">Return home</a></p>
    </footer>
</body>
</html>'''

