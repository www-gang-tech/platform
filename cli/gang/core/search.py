"""
GANG Static Site Search
Generate search index and provide search functionality.
"""

from pathlib import Path
from typing import Dict, List, Any
import json
import re
from datetime import date, datetime
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
            'date': self._serialize_date(frontmatter.get('date', '')),
        }
    
    def _normalize_tags(self, tags: Any) -> List[str]:
        """Return tags as strings so the search index is JSON-safe."""
        if tags is None:
            return []
        if isinstance(tags, list):
            return [str(tag) for tag in tags]
        return [str(tags)]
    
    def _serialize_date(self, value: Any) -> str:
        """Convert YAML date/datetime values into JSON-serializable strings."""
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, date):
            return value.isoformat()
        return str(value) if value is not None else ''
    
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
    
    def generate_search_page_html(self, search_index: Dict[str, Any] = None) -> str:
        """Generate a standalone, no-JS search index page."""
        documents = []
        if search_index:
            documents = sorted(
                search_index.get('documents', []),
                key=lambda doc: (doc.get('category', ''), doc.get('title', '')),
            )

        document_items = '\n'.join(
            f'''            <li>
                <article>
                    <h2><a href="{self._escape_html(doc.get('url', '#'))}">{self._escape_html(doc.get('title', 'Untitled'))}</a></h2>
                    <p class="result-meta">
                        <span class="result-category">{self._escape_html(doc.get('category', 'content'))}</span>
                        {f'<time datetime="{self._escape_html(doc.get("date", ""))}">{self._escape_html(doc.get("date", ""))}</time>' if doc.get('date') else ''}
                    </p>
                    <p>{self._escape_html(doc.get('description') or doc.get('content') or '')}</p>
                </article>
            </li>'''
            for doc in documents
        ) or '            <li>No documents indexed yet.</li>'

        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Search - GANG</title>
    <meta name="description" content="Browse indexed GANG articles, projects, pages, and resources.">
    <link rel="canonical" href="{self._escape_html(self.config.get('site', {}).get('url', '').rstrip('/'))}/search/">
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
        h1 {{ margin-bottom: 2rem; font-size: 2rem; }}
        .summary {{
            margin-bottom: 1rem;
            color: #666;
            font-size: 0.9rem;
        }}
        .results {{
            list-style: none;
        }}
        .result {{
            padding: 1.5rem;
            margin-bottom: 1rem;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            transition: all 0.2s;
        }}
        .result:hover {{
            border-color: #0066cc;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
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
        .result-description {{
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
        header, main, footer {{
            margin-bottom: 2rem;
        }}
    </style>
</head>
<body>
    <header>
        <h1>Search</h1>
        <p class="summary">{len(documents)} documents indexed. Use your browser find command to search this static index.</p>
    </header>
    <main>
        <ol class="results">
{document_items}
        </ol>
    </main>
    <footer>
        <p><a href="/">Return home</a></p>
    </footer>
</body>
</html>'''

    def _escape_html(self, value: Any) -> str:
        """Escape text for static HTML output."""
        return (
            str(value)
            .replace('&', '&amp;')
            .replace('<', '&lt;')
            .replace('>', '&gt;')
            .replace('"', '&quot;')
        )

