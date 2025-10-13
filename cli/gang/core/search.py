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
            'id': str(file_path.relative_to(self.content_path)),
            'title': title,
            'description': description,
            'url': url,
            'category': category,
            'tags': tags,
            'content': clean_text[:500],  # First 500 chars for preview
            'searchable': searchable.lower(),  # Lowercase for case-insensitive search
            'date': frontmatter.get('date', ''),
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
        """Generate a standalone search page HTML"""
        return '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Search</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: system-ui, -apple-system, sans-serif;
            line-height: 1.6;
            color: #1a1a1a;
            background: #fff;
            padding: 2rem;
            max-width: 800px;
            margin: 0 auto;
        }
        h1 { margin-bottom: 2rem; font-size: 2rem; }
        .search-box {
            margin-bottom: 2rem;
            position: relative;
        }
        #searchInput {
            width: 100%;
            padding: 1rem;
            font-size: 1.1rem;
            border: 2px solid #e0e0e0;
            border-radius: 8px;
        }
        #searchInput:focus {
            outline: none;
            border-color: #0066cc;
        }
        .search-stats {
            margin-bottom: 1rem;
            color: #666;
            font-size: 0.9rem;
        }
        .result {
            padding: 1.5rem;
            margin-bottom: 1rem;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            transition: all 0.2s;
        }
        .result:hover {
            border-color: #0066cc;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .result-title {
            font-size: 1.3rem;
            font-weight: 600;
            margin-bottom: 0.5rem;
        }
        .result-title a {
            color: #0066cc;
            text-decoration: none;
        }
        .result-title a:hover {
            text-decoration: underline;
        }
        .result-meta {
            font-size: 0.85rem;
            color: #666;
            margin-bottom: 0.5rem;
        }
        .result-description {
            color: #333;
            line-height: 1.5;
        }
        .result-category {
            display: inline-block;
            padding: 0.25rem 0.5rem;
            background: #e6f2ff;
            color: #0066cc;
            border-radius: 4px;
            font-size: 0.8rem;
            margin-right: 0.5rem;
        }
        .no-results {
            text-align: center;
            padding: 3rem;
            color: #666;
        }
        .loading {
            text-align: center;
            padding: 2rem;
            color: #999;
        }
        mark {
            background: #ffeb3b;
            padding: 0 2px;
        }
    </style>
</head>
<body>
    <h1>🔍 Search</h1>
    
    <div class="search-box">
        <input 
            type="text" 
            id="searchInput" 
            placeholder="Search articles, projects, pages..."
            autocomplete="off"
        >
    </div>
    
    <div id="searchStats" class="search-stats"></div>
    <div id="results"></div>
    
    <script>
        let searchIndex = null;
        
        // Load search index
        fetch('/search-index.json')
            .then(r => r.json())
            .then(data => {
                searchIndex = data;
                document.getElementById('searchStats').textContent = 
                    `${data.documents.length} documents indexed`;
            })
            .catch(e => {
                document.getElementById('results').innerHTML = 
                    '<div class="no-results">Failed to load search index</div>';
            });
        
        // Search function
        function search(query) {
            if (!searchIndex || !query.trim()) {
                document.getElementById('results').innerHTML = '';
                document.getElementById('searchStats').textContent = 
                    `${searchIndex?.documents.length || 0} documents indexed`;
                return;
            }
            
            const terms = query.toLowerCase().trim().split(/\\s+/);
            const results = [];
            
            for (const doc of searchIndex.documents) {
                let score = 0;
                const searchable = doc.searchable;
                
                // Score based on term matches
                for (const term of terms) {
                    if (term.length < 2) continue;
                    
                    // Title match (high weight)
                    if (doc.title.toLowerCase().includes(term)) {
                        score += 10;
                    }
                    
                    // Exact match in content
                    const regex = new RegExp(term, 'gi');
                    const matches = (searchable.match(regex) || []).length;
                    score += matches;
                }
                
                if (score > 0) {
                    results.push({ ...doc, score });
                }
            }
            
            // Sort by score
            results.sort((a, b) => b.score - a.score);
            
            // Display results
            displayResults(results, query);
        }
        
        function displayResults(results, query) {
            const container = document.getElementById('results');
            const stats = document.getElementById('searchStats');
            
            if (results.length === 0) {
                container.innerHTML = 
                    '<div class="no-results">No results found for "' + 
                    escapeHtml(query) + '"</div>';
                stats.textContent = '0 results';
                return;
            }
            
            stats.textContent = `${results.length} result(s) for "${query}"`;
            
            container.innerHTML = results.map(r => `
                <div class="result">
                    <div class="result-title">
                        <a href="${r.url}">${escapeHtml(r.title)}</a>
                    </div>
                    <div class="result-meta">
                        <span class="result-category">${escapeHtml(r.category)}</span>
                        ${r.date ? '<span>' + r.date + '</span>' : ''}
                    </div>
                    <div class="result-description">
                        ${escapeHtml(r.description || r.content)}
                    </div>
                </div>
            `).join('');
        }
        
        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }
        
        // Debounced search
        let searchTimeout;
        document.getElementById('searchInput').addEventListener('input', (e) => {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(() => {
                search(e.target.value);
            }, 300);
        });
        
        // Auto-focus search box
        document.getElementById('searchInput').focus();
        
        // Search from URL parameter
        const urlParams = new URLSearchParams(window.location.search);
        const queryParam = urlParams.get('q');
        if (queryParam) {
            document.getElementById('searchInput').value = queryParam;
            setTimeout(() => search(queryParam), 500);
        }
    </script>
</body>
</html>'''

