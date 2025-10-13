"""
GANG SEO Preview Generator
Generate social media card previews (Twitter, Facebook, LinkedIn).
"""

from typing import Dict, Any, Optional
from pathlib import Path
import re


class SEOPreviewGenerator:
    """Generate social media preview cards"""
    
    def __init__(self, site_url: str):
        self.site_url = site_url.rstrip('/')
    
    def generate_previews(
        self,
        title: str,
        description: str,
        url: str,
        image: Optional[str] = None,
        author: Optional[str] = None,
        published_date: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate preview data for all major platforms.
        Returns Twitter, Facebook, and LinkedIn previews.
        """
        
        # Ensure absolute URL for image
        if image and not image.startswith('http'):
            image = f"{self.site_url}/{image.lstrip('/')}"
        
        return {
            'twitter': self._generate_twitter_card(
                title, description, url, image, author
            ),
            'facebook': self._generate_facebook_card(
                title, description, url, image, author, published_date
            ),
            'linkedin': self._generate_linkedin_card(
                title, description, url, image
            ),
            'meta_tags': self._generate_meta_tags(
                title, description, url, image, author, published_date
            )
        }
    
    def _generate_twitter_card(
        self,
        title: str,
        description: str,
        url: str,
        image: Optional[str],
        author: Optional[str]
    ) -> Dict[str, Any]:
        """Generate Twitter Card preview"""
        
        # Truncate for Twitter limits
        title_truncated = self._truncate(title, 70)
        desc_truncated = self._truncate(description, 200)
        
        card = {
            'card_type': 'summary_large_image' if image else 'summary',
            'title': title_truncated,
            'description': desc_truncated,
            'url': url,
            'image': image,
            'creator': f"@{author}" if author else None,
            'tags': {
                'twitter:card': 'summary_large_image' if image else 'summary',
                'twitter:title': title_truncated,
                'twitter:description': desc_truncated,
                'twitter:url': url
            }
        }
        
        if image:
            card['tags']['twitter:image'] = image
            card['tags']['twitter:image:alt'] = title_truncated
        
        if author:
            card['tags']['twitter:creator'] = f"@{author}"
        
        return card
    
    def _generate_facebook_card(
        self,
        title: str,
        description: str,
        url: str,
        image: Optional[str],
        author: Optional[str],
        published_date: Optional[str]
    ) -> Dict[str, Any]:
        """Generate Facebook Open Graph preview"""
        
        # Facebook allows longer text
        title_truncated = self._truncate(title, 95)
        desc_truncated = self._truncate(description, 300)
        
        card = {
            'title': title_truncated,
            'description': desc_truncated,
            'url': url,
            'type': 'article',
            'image': image,
            'tags': {
                'og:type': 'article',
                'og:title': title_truncated,
                'og:description': desc_truncated,
                'og:url': url
            }
        }
        
        if image:
            card['tags']['og:image'] = image
            card['tags']['og:image:width'] = '1200'
            card['tags']['og:image:height'] = '630'
            card['tags']['og:image:alt'] = title_truncated
        
        if author:
            card['tags']['article:author'] = author
        
        if published_date:
            card['tags']['article:published_time'] = published_date
        
        return card
    
    def _generate_linkedin_card(
        self,
        title: str,
        description: str,
        url: str,
        image: Optional[str]
    ) -> Dict[str, Any]:
        """Generate LinkedIn preview (uses Open Graph)"""
        
        title_truncated = self._truncate(title, 200)
        desc_truncated = self._truncate(description, 256)
        
        card = {
            'title': title_truncated,
            'description': desc_truncated,
            'url': url,
            'image': image,
            'tags': {
                'og:title': title_truncated,
                'og:description': desc_truncated,
                'og:url': url,
                'og:type': 'article'
            }
        }
        
        if image:
            card['tags']['og:image'] = image
        
        return card
    
    def _generate_meta_tags(
        self,
        title: str,
        description: str,
        url: str,
        image: Optional[str],
        author: Optional[str],
        published_date: Optional[str]
    ) -> Dict[str, str]:
        """Generate all meta tags for HTML"""
        
        tags = {
            # Standard meta
            'title': title,
            'description': description,
            'canonical': url,
            
            # Open Graph (Facebook)
            'og:type': 'article',
            'og:title': self._truncate(title, 95),
            'og:description': self._truncate(description, 300),
            'og:url': url,
            
            # Twitter
            'twitter:card': 'summary_large_image' if image else 'summary',
            'twitter:title': self._truncate(title, 70),
            'twitter:description': self._truncate(description, 200),
            'twitter:url': url
        }
        
        if image:
            tags['og:image'] = image
            tags['og:image:width'] = '1200'
            tags['og:image:height'] = '630'
            tags['twitter:image'] = image
            tags['twitter:image:alt'] = title
        
        if author:
            tags['article:author'] = author
            tags['twitter:creator'] = f"@{author}"
        
        if published_date:
            tags['article:published_time'] = published_date
        
        return tags
    
    def _truncate(self, text: str, max_length: int) -> str:
        """Truncate text to max length without cutting words"""
        if len(text) <= max_length:
            return text
        
        truncated = text[:max_length].rsplit(' ', 1)[0]
        return truncated + '...'
    
    def generate_html_meta_tags(
        self,
        title: str,
        description: str,
        url: str,
        image: Optional[str] = None,
        author: Optional[str] = None,
        published_date: Optional[str] = None
    ) -> str:
        """Generate HTML meta tags as a string"""
        
        tags = self._generate_meta_tags(
            title, description, url, image, author, published_date
        )
        
        html_parts = []
        
        # Title
        html_parts.append(f'<title>{tags["title"]}</title>')
        html_parts.append(f'<meta name="description" content="{tags["description"]}">')
        html_parts.append(f'<link rel="canonical" href="{tags["canonical"]}">')
        
        # Open Graph
        for key, value in tags.items():
            if key.startswith('og:'):
                html_parts.append(f'<meta property="{key}" content="{value}">')
        
        # Twitter
        for key, value in tags.items():
            if key.startswith('twitter:'):
                html_parts.append(f'<meta name="{key}" content="{value}">')
        
        # Article meta
        for key, value in tags.items():
            if key.startswith('article:'):
                html_parts.append(f'<meta property="{key}" content="{value}">')
        
        return '\n'.join(html_parts)
    
    def validate_image_dimensions(self, width: int, height: int) -> Dict[str, Any]:
        """Validate image dimensions for social media"""
        
        recommendations = []
        
        # Twitter (1200x675 or 2:1 ratio)
        twitter_ok = (width >= 1200 and height >= 675 and 1.9 <= width/height <= 2.1)
        if not twitter_ok:
            recommendations.append({
                'platform': 'Twitter',
                'recommended': '1200x675 (2:1 ratio)',
                'current': f'{width}x{height}'
            })
        
        # Facebook (1200x630 or 1.91:1 ratio)
        facebook_ok = (width >= 1200 and height >= 630 and 1.8 <= width/height <= 2.0)
        if not facebook_ok:
            recommendations.append({
                'platform': 'Facebook',
                'recommended': '1200x630 (1.91:1 ratio)',
                'current': f'{width}x{height}'
            })
        
        # LinkedIn (1200x627 or 1.91:1 ratio)
        linkedin_ok = (width >= 1200 and height >= 627 and 1.8 <= width/height <= 2.0)
        if not linkedin_ok:
            recommendations.append({
                'platform': 'LinkedIn',
                'recommended': '1200x627 (1.91:1 ratio)',
                'current': f'{width}x{height}'
            })
        
        return {
            'valid': len(recommendations) == 0,
            'recommendations': recommendations
        }

