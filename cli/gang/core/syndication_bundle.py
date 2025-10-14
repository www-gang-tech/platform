"""
Syndication Bundle Generator (POSSE)
Publish Once, Syndicate Everywhere
Generates platform-specific bundles for social media and content platforms
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
import json
from bs4 import BeautifulSoup
import yaml


class SyndicationBundleGenerator:
    """Generate syndication-ready bundles for each post"""
    
    def __init__(self, content_path: Path, dist_path: Path, site_url: str):
        self.content_path = Path(content_path)
        self.dist_path = Path(dist_path)
        self.site_url = site_url.rstrip('/')
    
    def generate_all(self) -> int:
        """Generate syndication bundles for all posts"""
        
        syndication_dir = self.dist_path / 'syndication'
        syndication_dir.mkdir(exist_ok=True)
        
        count = 0
        
        # Process posts
        posts_dir = self.content_path / 'posts'
        if posts_dir.exists():
            for md_file in posts_dir.glob('*.md'):
                bundle = self.create_bundle(md_file, 'post')
                if bundle:
                    output_path = syndication_dir / f"{bundle['slug']}.json"
                    output_path.write_text(json.dumps(bundle, indent=2))
                    count += 1
        
        return count
    
    def create_bundle(self, md_file: Path, content_type: str) -> Optional[Dict[str, Any]]:
        """Create syndication bundle for a single piece of content"""
        
        content = md_file.read_text()
        
        # Parse frontmatter
        if not content.startswith('---'):
            return None
        
        parts = content.split('---', 2)
        if len(parts) < 3:
            return None
        
        frontmatter = yaml.safe_load(parts[1])
        markdown_content = parts[2].strip()
        
        # Extract metadata
        title = frontmatter.get('title', '')
        description = frontmatter.get('description', '')
        slug = frontmatter.get('slug', md_file.stem)
        hero_image = frontmatter.get('image', '')
        hero_alt = frontmatter.get('image_alt', '')
        
        # Generate canonical URL
        canonical = f"{self.site_url}/{content_type}s/{slug}/"
        
        # Extract key points from content
        key_points = self._extract_key_points(markdown_content)
        
        # Generate summary (first paragraph or description)
        summary = description or self._extract_summary(markdown_content)
        
        # Create platform-specific content
        bundle = {
            'slug': slug,
            'title': title,
            'summary': summary,
            'hero_image': hero_image if hero_image.startswith('http') else f"{self.site_url}{hero_image}",
            'hero_alt': hero_alt,
            'key_points': key_points,
            'cta': 'Read more',
            'canonical': canonical,
            'utm_source': 'social',
            'platforms': {
                'twitter': self._format_for_twitter(title, summary, canonical),
                'linkedin': self._format_for_linkedin(title, summary, key_points, canonical),
                'medium': self._format_for_medium(title, markdown_content, canonical),
                'devto': self._format_for_devto(title, markdown_content, canonical, frontmatter)
            }
        }
        
        return bundle
    
    def _extract_key_points(self, markdown: str) -> List[str]:
        """Extract bullet points or headings as key points"""
        
        key_points = []
        
        for line in markdown.split('\n'):
            line = line.strip()
            
            # Extract h2 headings
            if line.startswith('## '):
                key_points.append(line.replace('## ', ''))
            
            # Extract bullet points
            elif line.startswith('- ') or line.startswith('* '):
                key_points.append(line[2:].strip())
        
        return key_points[:5]  # Max 5 key points
    
    def _extract_summary(self, markdown: str) -> str:
        """Extract first paragraph as summary"""
        
        paragraphs = [p.strip() for p in markdown.split('\n\n') if p.strip()]
        
        if paragraphs:
            # Find first non-heading paragraph
            for p in paragraphs:
                if not p.startswith('#'):
                    return p[:280]  # Twitter-safe length
        
        return ""
    
    def _format_for_twitter(self, title: str, summary: str, canonical: str) -> Dict[str, str]:
        """Format for Twitter/X (280 chars)"""
        
        utm_url = f"{canonical}?utm_source=twitter&utm_medium=social"
        
        # Calculate available space
        url_length = 23  # Twitter's t.co link length
        available = 280 - url_length - 3  # -3 for spacing and newline
        
        text = f"{title}\n\n{summary}"
        if len(text) > available:
            text = text[:available-3] + "..."
        
        return {
            'text': f"{text}\n\n{utm_url}",
            'max_length': 280,
            'hashtags': []
        }
    
    def _format_for_linkedin(self, title: str, summary: str, key_points: List[str], canonical: str) -> Dict[str, str]:
        """Format for LinkedIn (3000 chars)"""
        
        utm_url = f"{canonical}?utm_source=linkedin&utm_medium=social"
        
        post = f"{title}\n\n{summary}\n\n"
        
        if key_points:
            post += "Key points:\n"
            for point in key_points[:3]:
                post += f"• {point}\n"
            post += "\n"
        
        post += f"Read the full article: {utm_url}"
        
        return {
            'text': post,
            'max_length': 3000
        }
    
    def _format_for_medium(self, title: str, markdown: str, canonical: str) -> Dict[str, Any]:
        """Format for Medium (full article with canonical)"""
        
        return {
            'title': title,
            'content': markdown,
            'canonical_url': canonical,
            'tags': [],
            'publish_status': 'draft'
        }
    
    def _format_for_devto(self, title: str, markdown: str, canonical: str, frontmatter: Dict) -> Dict[str, Any]:
        """Format for Dev.to (frontmatter + markdown)"""
        
        tags = frontmatter.get('tags', [])
        if isinstance(tags, str):
            tags = [t.strip() for t in tags.split(',')]
        
        return {
            'title': title,
            'body_markdown': markdown,
            'published': False,
            'canonical_url': canonical,
            'tags': tags[:4]  # Max 4 tags on Dev.to
        }


def render_syndication_bundle(bundle_path: Path, platform: str) -> str:
    """Render a specific platform's content from a bundle"""
    
    bundle = json.loads(bundle_path.read_text())
    
    if platform not in bundle['platforms']:
        raise ValueError(f"Platform {platform} not found in bundle")
    
    platform_data = bundle['platforms'][platform]
    
    if platform in ['twitter', 'linkedin']:
        return platform_data['text']
    elif platform in ['medium', 'devto']:
        return json.dumps(platform_data, indent=2)
    else:
        return str(platform_data)

