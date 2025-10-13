"""
GANG Table of Contents Generator
Auto-generate TOC from headings with anchor links.
"""

from typing import Dict, List, Any
import re
import html


class TOCGenerator:
    """Generate table of contents from markdown headings"""
    
    @staticmethod
    def generate_from_markdown(content: str) -> Dict[str, Any]:
        """
        Generate TOC from markdown content.
        Returns TOC HTML and modified content with anchors.
        """
        
        # Extract headings
        headings = []
        heading_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
        
        for match in heading_pattern.finditer(content):
            level = len(match.group(1))
            text = match.group(2).strip()
            
            # Generate slug from heading text
            slug = TOCGenerator._generate_slug(text)
            
            headings.append({
                'level': level,
                'text': text,
                'slug': slug
            })
        
        # Generate TOC HTML
        toc_html = TOCGenerator._generate_toc_html(headings)
        
        # Add anchors to content
        def replace_heading(match):
            level = len(match.group(1))
            text = match.group(2).strip()
            slug = TOCGenerator._generate_slug(text)
            
            return f'{"#" * level} <a id="{slug}" href="#{slug}" class="heading-anchor" aria-hidden="true"></a>{text}'
        
        content_with_anchors = heading_pattern.sub(replace_heading, content)
        
        return {
            'toc_html': toc_html,
            'content': content_with_anchors,
            'headings': headings,
            'has_toc': len(headings) > 2
        }
    
    @staticmethod
    def generate_from_html(html_content: str) -> Dict[str, Any]:
        """Generate TOC from HTML content"""
        
        # Extract headings from HTML
        headings = []
        heading_pattern = re.compile(r'<(h[1-6])(?:\s+[^>]*)?>(.+?)</\1>', re.IGNORECASE)
        
        for match in heading_pattern.finditer(html_content):
            tag = match.group(1).lower()
            level = int(tag[1])
            text = match.group(2)
            
            # Remove HTML tags from text
            text_clean = re.sub(r'<[^>]+>', '', text).strip()
            slug = TOCGenerator._generate_slug(text_clean)
            
            headings.append({
                'level': level,
                'text': text_clean,
                'slug': slug
            })
        
        toc_html = TOCGenerator._generate_toc_html(headings)
        
        return {
            'toc_html': toc_html,
            'headings': headings,
            'has_toc': len(headings) > 2
        }
    
    @staticmethod
    def _generate_slug(text: str) -> str:
        """Generate URL-safe slug from heading text"""
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        
        # Convert to lowercase
        slug = text.lower()
        
        # Replace spaces and special chars with hyphens
        slug = re.sub(r'[^\w\s-]', '', slug)
        slug = re.sub(r'[-\s]+', '-', slug)
        
        # Remove leading/trailing hyphens
        slug = slug.strip('-')
        
        return slug
    
    @staticmethod
    def _generate_toc_html(headings: List[Dict[str, Any]]) -> str:
        """Generate HTML for table of contents"""
        
        if not headings:
            return ''
        
        # Skip if only H1 (title)
        non_h1_headings = [h for h in headings if h['level'] > 1]
        if not non_h1_headings:
            return ''
        
        # Build nested list
        html_parts = ['<nav class="table-of-contents" aria-label="Table of Contents">']
        html_parts.append('<h2>Contents</h2>')
        html_parts.append('<ol>')
        
        current_level = 2
        
        for heading in headings:
            if heading['level'] == 1:
                continue  # Skip H1 (page title)
            
            level = heading['level']
            
            # Open/close nested lists as needed
            while current_level < level:
                html_parts.append('<ol>')
                current_level += 1
            
            while current_level > level:
                html_parts.append('</ol>')
                current_level -= 1
            
            # Add list item
            safe_text = html.escape(heading['text'])
            html_parts.append(f'<li><a href="#{heading["slug"]}">{safe_text}</a></li>')
        
        # Close remaining lists
        while current_level > 1:
            html_parts.append('</ol>')
            current_level -= 1
        
        html_parts.append('</ol>')
        html_parts.append('</nav>')
        
        return '\n'.join(html_parts)
    
    @staticmethod
    def get_toc_css() -> str:
        """Get CSS for table of contents"""
        return '''
        .table-of-contents {
            background: #f8f9fa;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            padding: 1.5rem;
            margin: 2rem 0;
        }
        
        .table-of-contents h2 {
            font-size: 1.1rem;
            margin-top: 0;
            margin-bottom: 1rem;
            color: #1a1a1a;
        }
        
        .table-of-contents ol {
            margin: 0;
            padding-left: 1.5rem;
            list-style: decimal;
        }
        
        .table-of-contents li {
            margin: 0.5rem 0;
        }
        
        .table-of-contents a {
            color: #0052a3;
            text-decoration: none;
        }
        
        .table-of-contents a:hover {
            text-decoration: underline;
        }
        
        .heading-anchor {
            opacity: 0;
            margin-left: 0.5rem;
            text-decoration: none;
            font-weight: normal;
        }
        
        h1:hover .heading-anchor,
        h2:hover .heading-anchor,
        h3:hover .heading-anchor,
        h4:hover .heading-anchor,
        h5:hover .heading-anchor,
        h6:hover .heading-anchor {
            opacity: 0.5;
        }
        
        .heading-anchor:hover {
            opacity: 1 !important;
        }
        
        @media (prefers-reduced-motion: reduce) {
            .heading-anchor {
                transition: none;
            }
        }
        '''

