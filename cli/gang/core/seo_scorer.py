"""
GANG SEO Scorer
Moz/Lighthouse-style SEO scoring for content.
"""

from pathlib import Path
from typing import Dict, List, Any
import re


class SEOScorer:
    """Score content for SEO optimization"""
    
    def __init__(self):
        self.weights = {
            'title': 15,
            'meta_description': 10,
            'headings': 15,
            'images': 10,
            'links': 10,
            'content_quality': 20,
            'readability': 10,
            'structured_data': 10
        }
    
    def score_content(
        self,
        title: str,
        description: str,
        content: str,
        images: List[Dict[str, str]],
        links: List[str],
        structured_data: bool = False
    ) -> Dict[str, Any]:
        """
        Score content for SEO.
        Returns score (0-100) and recommendations.
        """
        
        scores = {}
        recommendations = []
        
        # Title scoring
        title_score, title_recs = self._score_title(title)
        scores['title'] = title_score
        recommendations.extend(title_recs)
        
        # Meta description
        desc_score, desc_recs = self._score_description(description)
        scores['meta_description'] = desc_score
        recommendations.extend(desc_recs)
        
        # Headings
        heading_score, heading_recs = self._score_headings(content)
        scores['headings'] = heading_score
        recommendations.extend(heading_recs)
        
        # Images
        image_score, image_recs = self._score_images(images)
        scores['images'] = image_score
        recommendations.extend(image_recs)
        
        # Links
        link_score, link_recs = self._score_links(links, content)
        scores['links'] = link_score
        recommendations.extend(link_recs)
        
        # Content quality
        quality_score, quality_recs = self._score_content_quality(content)
        scores['content_quality'] = quality_score
        recommendations.extend(quality_recs)
        
        # Readability
        read_score, read_recs = self._score_readability(content)
        scores['readability'] = read_score
        recommendations.extend(read_recs)
        
        # Structured data
        scores['structured_data'] = 10 if structured_data else 0
        if not structured_data:
            recommendations.append({
                'type': 'warning',
                'category': 'structured_data',
                'message': 'Add JSON-LD structured data for better search visibility'
            })
        
        # Calculate total score
        total_score = sum(scores.values())
        
        return {
            'score': int(total_score),
            'grade': self._get_grade(total_score),
            'scores': scores,
            'recommendations': recommendations,
            'summary': self._generate_summary(total_score, recommendations)
        }
    
    def _score_title(self, title: str) -> tuple:
        """Score title tag"""
        score = 0
        recs = []
        
        if not title:
            recs.append({
                'type': 'error',
                'category': 'title',
                'message': 'Missing title tag'
            })
            return 0, recs
        
        length = len(title)
        
        # Length check (50-60 chars ideal)
        if 50 <= length <= 60:
            score += 10
        elif 40 <= length <= 70:
            score += 7
            recs.append({
                'type': 'info',
                'category': 'title',
                'message': f'Title length ({length}) is acceptable but aim for 50-60 characters'
            })
        else:
            score += 3
            recs.append({
                'type': 'warning',
                'category': 'title',
                'message': f'Title length ({length}) should be 50-60 characters'
            })
        
        # Keyword at start
        if title[0].isupper():
            score += 5
        
        return score, recs
    
    def _score_description(self, description: str) -> tuple:
        """Score meta description"""
        score = 0
        recs = []
        
        if not description:
            recs.append({
                'type': 'error',
                'category': 'description',
                'message': 'Missing meta description'
            })
            return 0, recs
        
        length = len(description)
        
        # Length check (150-160 chars ideal)
        if 150 <= length <= 160:
            score += 10
        elif 120 <= length <= 170:
            score += 7
            recs.append({
                'type': 'info',
                'category': 'description',
                'message': f'Description length ({length}) is acceptable but aim for 150-160 characters'
            })
        else:
            score += 3
            recs.append({
                'type': 'warning',
                'category': 'description',
                'message': f'Description length ({length}) should be 150-160 characters'
            })
        
        return score, recs
    
    def _score_headings(self, content: str) -> tuple:
        """Score heading structure"""
        score = 0
        recs = []
        
        h1_count = len(re.findall(r'<h1[^>]*>|^# ', content, re.MULTILINE))
        h2_count = len(re.findall(r'<h2[^>]*>|^## ', content, re.MULTILINE))
        h3_count = len(re.findall(r'<h3[^>]*>|^### ', content, re.MULTILINE))
        
        # Exactly one H1
        if h1_count == 1:
            score += 7
        elif h1_count == 0:
            recs.append({
                'type': 'error',
                'category': 'headings',
                'message': 'Missing H1 heading'
            })
        else:
            score += 3
            recs.append({
                'type': 'warning',
                'category': 'headings',
                'message': f'Multiple H1 headings ({h1_count}) - use only one'
            })
        
        # Has H2s
        if h2_count >= 2:
            score += 5
        elif h2_count == 1:
            score += 3
        else:
            recs.append({
                'type': 'info',
                'category': 'headings',
                'message': 'Add H2 headings to structure content'
            })
        
        # Logical hierarchy
        if h2_count > 0 and h3_count > h2_count * 3:
            recs.append({
                'type': 'info',
                'category': 'headings',
                'message': 'Consider if heading hierarchy is logical'
            })
        else:
            score += 3
        
        return score, recs
    
    def _score_images(self, images: List[Dict[str, str]]) -> tuple:
        """Score image optimization"""
        score = 0
        recs = []
        
        if not images:
            recs.append({
                'type': 'info',
                'category': 'images',
                'message': 'No images found - consider adding relevant images'
            })
            return 5, recs
        
        missing_alt = sum(1 for img in images if not img.get('alt'))
        
        if missing_alt == 0:
            score += 10
        elif missing_alt < len(images) / 2:
            score += 6
            recs.append({
                'type': 'warning',
                'category': 'images',
                'message': f'{missing_alt} images missing alt text'
            })
        else:
            score += 2
            recs.append({
                'type': 'error',
                'category': 'images',
                'message': f'{missing_alt}/{len(images)} images missing alt text'
            })
        
        return score, recs
    
    def _score_links(self, links: List[str], content: str) -> tuple:
        """Score internal/external links"""
        score = 0
        recs = []
        
        internal_links = [l for l in links if not l.startswith('http')]
        external_links = [l for l in links if l.startswith('http')]
        
        # Has internal links
        if len(internal_links) >= 2:
            score += 5
        elif len(internal_links) == 1:
            score += 3
        else:
            recs.append({
                'type': 'info',
                'category': 'links',
                'message': 'Add internal links to related content'
            })
        
        # Has external links
        if len(external_links) >= 1:
            score += 3
        
        # Check for descriptive link text
        generic_patterns = ['click here', 'read more', 'here', 'this']
        if any(pattern in content.lower() for pattern in generic_patterns):
            score += 1
            recs.append({
                'type': 'info',
                'category': 'links',
                'message': 'Use descriptive link text instead of "click here" or "read more"'
            })
        else:
            score += 2
        
        return score, recs
    
    def _score_content_quality(self, content: str) -> tuple:
        """Score content quality"""
        score = 0
        recs = []
        
        # Word count
        words = len(content.split())
        
        if words >= 1000:
            score += 15
        elif words >= 500:
            score += 10
        elif words >= 300:
            score += 7
            recs.append({
                'type': 'info',
                'category': 'content',
                'message': f'Content length ({words} words) is good, but longer content (1000+) often ranks better'
            })
        else:
            score += 3
            recs.append({
                'type': 'warning',
                'category': 'content',
                'message': f'Content is short ({words} words). Aim for 500+ words for better SEO'
            })
        
        # Paragraph length
        paragraphs = content.split('\n\n')
        avg_para_length = sum(len(p.split()) for p in paragraphs) / len(paragraphs) if paragraphs else 0
        
        if 50 <= avg_para_length <= 150:
            score += 5
        elif avg_para_length > 150:
            recs.append({
                'type': 'info',
                'category': 'content',
                'message': 'Consider breaking up long paragraphs for readability'
            })
        
        return score, recs
    
    def _score_readability(self, content: str) -> tuple:
        """Score readability"""
        score = 0
        recs = []
        
        # Simple readability check
        words = content.split()
        sentences = len(re.split(r'[.!?]+', content))
        
        if sentences == 0:
            return 5, recs
        
        avg_sentence_length = len(words) / sentences
        
        if 15 <= avg_sentence_length <= 20:
            score += 10
        elif 10 <= avg_sentence_length <= 25:
            score += 7
        else:
            score += 4
            if avg_sentence_length > 25:
                recs.append({
                    'type': 'info',
                    'category': 'readability',
                    'message': 'Consider shorter sentences for better readability'
                })
        
        return score, recs
    
    def _get_grade(self, score: int) -> str:
        """Convert score to letter grade"""
        if score >= 90:
            return 'A+'
        elif score >= 80:
            return 'A'
        elif score >= 70:
            return 'B'
        elif score >= 60:
            return 'C'
        elif score >= 50:
            return 'D'
        else:
            return 'F'
    
    def _generate_summary(self, score: int, recommendations: List[Dict]) -> str:
        """Generate human-readable summary"""
        errors = len([r for r in recommendations if r['type'] == 'error'])
        warnings = len([r for r in recommendations if r['type'] == 'warning'])
        
        if score >= 90:
            return f"Excellent SEO! {errors} errors, {warnings} warnings."
        elif score >= 70:
            return f"Good SEO with room for improvement. {errors} errors, {warnings} warnings."
        elif score >= 50:
            return f"Fair SEO. Address {errors} errors and {warnings} warnings."
        else:
            return f"Needs significant SEO improvement. {errors} errors, {warnings} warnings."

