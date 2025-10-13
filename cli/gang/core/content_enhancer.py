"""
GANG Content Enhancer
Reading time, freshness checker, code highlighting, summarization.
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta
import re
import os


class ReadingTimeCalculator:
    """Calculate accurate reading time"""
    
    # Average reading speeds (words per minute)
    WPM_TECHNICAL = 180  # Technical content (slower)
    WPM_GENERAL = 250    # General content
    WPM_FAST = 300       # Easy reading
    
    @staticmethod
    def calculate(
        content: str,
        content_type: str = 'general',
        include_code: bool = True
    ) -> Dict[str, Any]:
        """
        Calculate reading time for content.
        Returns minutes and formatted string.
        """
        
        # Remove markdown/HTML for word count
        clean_content = ReadingTimeCalculator._clean_content(content)
        
        # Count words
        words = len(clean_content.split())
        
        # Count code blocks separately (read slower)
        code_blocks = re.findall(r'```[\s\S]*?```', content)
        code_words = sum(len(block.split()) for block in code_blocks)
        
        # Adjust for content type
        if content_type == 'technical' or code_words > words * 0.1:
            wpm = ReadingTimeCalculator.WPM_TECHNICAL
        else:
            wpm = ReadingTimeCalculator.WPM_GENERAL
        
        # Calculate time
        text_minutes = (words - code_words) / wpm
        code_minutes = code_words / (wpm * 0.7)  # Code reads slower
        
        total_minutes = text_minutes + code_minutes
        
        # Round up to nearest minute
        minutes = max(1, int(total_minutes + 0.5))
        
        return {
            'minutes': minutes,
            'formatted': f"{minutes} min read",
            'words': words,
            'code_blocks': len(code_blocks),
            'reading_speed': wpm
        }
    
    @staticmethod
    def _clean_content(content: str) -> str:
        """Remove markdown/HTML for accurate word count"""
        # Remove code blocks
        content = re.sub(r'```[\s\S]*?```', '', content)
        content = re.sub(r'`[^`]+`', '', content)
        
        # Remove images
        content = re.sub(r'!\[.*?\]\(.*?\)', '', content)
        
        # Remove links but keep text
        content = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', content)
        
        # Remove HTML tags
        content = re.sub(r'<[^>]+>', '', content)
        
        # Remove frontmatter
        content = re.sub(r'^---[\s\S]*?---', '', content)
        
        return content.strip()


class ContentFreshnessChecker:
    """Check if content is outdated and needs updates"""
    
    # Thresholds for different content types
    FRESHNESS_THRESHOLDS = {
        'news': timedelta(days=7),
        'tutorial': timedelta(days=180),
        'general': timedelta(days=365),
        'evergreen': timedelta(days=730)
    }
    
    @staticmethod
    def check_freshness(
        file_path: Path,
        content: str,
        frontmatter: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Check if content needs updating.
        Returns freshness score and recommendations.
        """
        
        # Get last update date
        last_updated = frontmatter.get('updated') or frontmatter.get('date')
        
        if not last_updated:
            return {
                'status': 'unknown',
                'score': 50,
                'message': 'No update date found',
                'recommendation': 'Add "updated" field to frontmatter'
            }
        
        # Convert to datetime
        if isinstance(last_updated, str):
            try:
                last_updated = datetime.fromisoformat(last_updated)
            except:
                try:
                    last_updated = datetime.strptime(last_updated, '%Y-%m-%d')
                except:
                    return {
                        'status': 'unknown',
                        'score': 50,
                        'message': 'Invalid date format'
                    }
        
        # Calculate age
        now = datetime.now()
        age = now - last_updated
        
        # Detect content type
        content_type = ContentFreshnessChecker._detect_content_type(content, frontmatter)
        threshold = ContentFreshnessChecker.FRESHNESS_THRESHOLDS.get(
            content_type,
            ContentFreshnessChecker.FRESHNESS_THRESHOLDS['general']
        )
        
        # Calculate freshness score (100 = fresh, 0 = very stale)
        age_ratio = age / threshold
        
        if age_ratio < 0.5:
            score = 100
            status = 'fresh'
            message = f'Content is fresh ({age.days} days old)'
        elif age_ratio < 1.0:
            score = int(100 - (age_ratio * 50))
            status = 'good'
            message = f'Content is still relevant ({age.days} days old)'
        elif age_ratio < 2.0:
            score = int(50 - ((age_ratio - 1.0) * 40))
            status = 'aging'
            message = f'Content may need review ({age.days} days old)'
        else:
            score = max(0, int(10 - ((age_ratio - 2.0) * 10)))
            status = 'stale'
            message = f'Content is outdated ({age.days} days old, last updated: {last_updated.date()})'
        
        # Check for outdated terms
        outdated_terms = ContentFreshnessChecker._detect_outdated_terms(content)
        if outdated_terms:
            score = max(0, score - 10)
            message += f' | Found outdated terms: {", ".join(outdated_terms[:3])}'
        
        result = {
            'status': status,
            'score': score,
            'age_days': age.days,
            'last_updated': last_updated.isoformat(),
            'content_type': content_type,
            'message': message
        }
        
        # Add recommendations
        if status in ['aging', 'stale']:
            result['recommendations'] = [
                'Review content for accuracy',
                'Update statistics and examples',
                'Check if links are still valid',
                'Update screenshots if any',
                f'Consider updating "updated" field to {now.date()}'
            ]
        
        return result
    
    @staticmethod
    def _detect_content_type(content: str, frontmatter: Dict[str, Any]) -> str:
        """Detect content type for freshness thresholds"""
        
        # Check frontmatter first
        if frontmatter.get('type'):
            return frontmatter['type']
        
        # Check for news patterns
        news_patterns = ['breaking', 'announce', 'release', 'launch', 'today']
        if any(pattern in content.lower() for pattern in news_patterns):
            return 'news'
        
        # Check for tutorial patterns
        tutorial_patterns = ['how to', 'tutorial', 'guide', 'step by step']
        if any(pattern in content.lower() for pattern in tutorial_patterns):
            return 'tutorial'
        
        # Check for evergreen patterns
        evergreen_patterns = ['fundamental', 'principle', 'introduction', 'basics']
        if any(pattern in content.lower() for pattern in evergreen_patterns):
            return 'evergreen'
        
        return 'general'
    
    @staticmethod
    def _detect_outdated_terms(content: str) -> List[str]:
        """Detect potentially outdated technology terms"""
        
        # List of terms that indicate old content
        outdated_terms = {
            'python 2': 'Python 2 is EOL since 2020',
            'ie11': 'IE11 is deprecated',
            'internet explorer': 'Internet Explorer is deprecated',
            'angular.js': 'AngularJS is deprecated',
            'bower': 'Bower is deprecated',
            'gulp': 'Gulp is less common now',
            'grunt': 'Grunt is largely obsolete'
        }
        
        found = []
        content_lower = content.lower()
        
        for term, reason in outdated_terms.items():
            if term in content_lower:
                found.append(term)
        
        return found


class CodeSyntaxHighlighter:
    """Server-side syntax highlighting (no JS needed)"""
    
    @staticmethod
    def highlight_code_blocks(content: str) -> str:
        """
        Apply server-side syntax highlighting to code blocks.
        Uses Pygments for syntax highlighting.
        """
        
        try:
            from pygments import highlight
            from pygments.lexers import get_lexer_by_name, guess_lexer
            from pygments.formatters import HtmlFormatter
            
            def replace_code_block(match):
                language = match.group(1) or 'text'
                code = match.group(2)
                
                try:
                    lexer = get_lexer_by_name(language, stripall=True)
                except:
                    try:
                        lexer = guess_lexer(code)
                    except:
                        # Fallback to plain text
                        return match.group(0)
                
                formatter = HtmlFormatter(
                    style='github-dark',
                    cssclass='highlight',
                    linenos=False
                )
                
                highlighted = highlight(code, lexer, formatter)
                
                return f'<div class="code-block" data-language="{language}">\n{highlighted}\n</div>'
            
            # Replace markdown code blocks
            pattern = r'```(\w+)?\n([\s\S]*?)```'
            return re.sub(pattern, replace_code_block, content)
        
        except ImportError:
            # Pygments not installed, return as-is
            return content
    
    @staticmethod
    def get_syntax_css() -> str:
        """Get CSS for syntax highlighting"""
        try:
            from pygments.formatters import HtmlFormatter
            formatter = HtmlFormatter(style='github-dark')
            return formatter.get_style_defs('.highlight')
        except:
            return ''


class ContentSummarizer:
    """AI-powered content summarization"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get('ANTHROPIC_API_KEY')
    
    def generate_summary(
        self,
        content: str,
        title: str,
        summary_type: str = 'tldr'
    ) -> Optional[str]:
        """
        Generate summary of content.
        Types: 'tldr', 'key_takeaways', 'executive'
        """
        
        if not self.api_key:
            return None
        
        try:
            from anthropic import Anthropic
            
            client = Anthropic(api_key=self.api_key)
            
            if summary_type == 'tldr':
                prompt = f"Write a one-paragraph TL;DR (2-3 sentences) for this article titled '{title}':\n\n{content[:2000]}"
            elif summary_type == 'key_takeaways':
                prompt = f"Extract 3-5 key takeaways as bullet points from this article titled '{title}':\n\n{content[:2000]}"
            elif summary_type == 'executive':
                prompt = f"Write an executive summary (100-150 words) for this article titled '{title}':\n\n{content[:3000]}"
            else:
                return None
            
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )
            
            return response.content[0].text.strip()
        
        except Exception as e:
            return None
    
    def enhance_content_with_summaries(
        self,
        content: str,
        title: str
    ) -> Dict[str, str]:
        """Generate all summary types"""
        
        return {
            'tldr': self.generate_summary(content, title, 'tldr'),
            'key_takeaways': self.generate_summary(content, title, 'key_takeaways'),
            'executive': self.generate_summary(content, title, 'executive')
        }

