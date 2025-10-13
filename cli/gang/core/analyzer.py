"""
GANG Content Quality Analyzer
Analyze content for readability, SEO, accessibility, and structure.
"""

import re
from pathlib import Path
from typing import Dict, List, Tuple, Any
import yaml
import markdown


class ContentAnalyzer:
    """Analyze markdown content for quality metrics"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.targets = {
            'readability_grade': (6, 10),  # Target grade level
            'min_words': 300,
            'max_words': 3000,
            'min_headings': 2,
        }
    
    def analyze_file(self, file_path: Path) -> Dict[str, Any]:
        """Analyze a markdown file and return quality metrics"""
        content = file_path.read_text()
        
        # Parse frontmatter and body
        if content.startswith('---'):
            parts = content.split('---', 2)
            frontmatter = yaml.safe_load(parts[1]) if len(parts) > 1 else {}
            body = parts[2] if len(parts) > 2 else ''
        else:
            frontmatter = {}
            body = content
        
        # Convert to HTML for structure analysis
        md = markdown.Markdown(extensions=['extra', 'meta'])
        html = md.convert(body)
        
        # Convert frontmatter dates to strings for JSON serialization
        frontmatter_serializable = {}
        for key, value in frontmatter.items():
            if hasattr(value, 'isoformat'):  # datetime/date objects
                frontmatter_serializable[key] = value.isoformat()
            elif isinstance(value, list):
                frontmatter_serializable[key] = [str(v) if hasattr(v, 'isoformat') else v for v in value]
            else:
                frontmatter_serializable[key] = value
        
        return {
            'file': str(file_path),
            'frontmatter': frontmatter_serializable,
            'readability': self._analyze_readability(body),
            'seo': self._analyze_seo(frontmatter, body),
            'structure': self._analyze_structure(body),
            'accessibility': self._analyze_accessibility(body, html),
            'metadata': self._analyze_metadata(body),
        }
    
    def _analyze_readability(self, text: str) -> Dict[str, Any]:
        """Calculate readability metrics"""
        # Clean text
        clean_text = re.sub(r'[#*`\[\]()]', '', text)
        clean_text = re.sub(r'\n+', ' ', clean_text)
        
        # Count sentences, words, syllables
        sentences = [s.strip() for s in re.split(r'[.!?]+', clean_text) if s.strip()]
        words = [w for w in re.split(r'\s+', clean_text) if w.strip()]
        
        sentence_count = len(sentences)
        word_count = len(words)
        
        if sentence_count == 0 or word_count == 0:
            return {
                'word_count': 0,
                'sentence_count': 0,
                'grade_level': 0,
                'reading_time_minutes': 0,
                'status': 'error',
                'message': 'No content to analyze'
            }
        
        # Estimate syllables (simple heuristic)
        syllable_count = sum(self._count_syllables(word) for word in words)
        
        # Flesch-Kincaid Grade Level
        # Formula: 0.39 * (words/sentences) + 11.8 * (syllables/words) - 15.59
        words_per_sentence = word_count / sentence_count
        syllables_per_word = syllable_count / word_count
        grade_level = 0.39 * words_per_sentence + 11.8 * syllables_per_word - 15.59
        grade_level = max(0, min(18, grade_level))  # Clamp between 0-18
        
        # Reading time (average 200-250 words per minute)
        reading_time = word_count / 225
        
        # Status check
        target_min, target_max = self.targets['readability_grade']
        if target_min <= grade_level <= target_max:
            status = 'good'
            message = f'Grade {grade_level:.1f} is in target range ({target_min}-{target_max})'
        elif grade_level < target_min:
            status = 'warning'
            message = f'Grade {grade_level:.1f} may be too simple'
        else:
            status = 'warning'
            message = f'Grade {grade_level:.1f} may be too complex'
        
        return {
            'word_count': word_count,
            'sentence_count': sentence_count,
            'syllable_count': syllable_count,
            'words_per_sentence': round(words_per_sentence, 1),
            'syllables_per_word': round(syllables_per_word, 2),
            'grade_level': round(grade_level, 1),
            'reading_time_minutes': round(reading_time, 1),
            'status': status,
            'message': message
        }
    
    def _count_syllables(self, word: str) -> int:
        """Estimate syllable count (simple heuristic)"""
        word = word.lower()
        vowels = 'aeiouy'
        syllables = 0
        previous_was_vowel = False
        
        for char in word:
            is_vowel = char in vowels
            if is_vowel and not previous_was_vowel:
                syllables += 1
            previous_was_vowel = is_vowel
        
        # Adjust for silent 'e'
        if word.endswith('e'):
            syllables -= 1
        
        # Ensure at least one syllable
        return max(1, syllables)
    
    def _analyze_seo(self, frontmatter: Dict, body: str) -> Dict[str, Any]:
        """Analyze SEO factors"""
        issues = []
        score = 100
        
        # Check title
        title = frontmatter.get('title', '')
        if not title:
            issues.append('Missing title in frontmatter')
            score -= 20
        elif len(title) < 30:
            issues.append(f'Title too short ({len(title)} chars, recommend 50-60)')
            score -= 5
        elif len(title) > 60:
            issues.append(f'Title too long ({len(title)} chars, recommend 50-60)')
            score -= 5
        
        # Check description/summary
        description = frontmatter.get('summary', frontmatter.get('description', ''))
        if not description:
            issues.append('Missing summary/description in frontmatter')
            score -= 20
        elif len(description) < 120:
            issues.append(f'Description too short ({len(description)} chars, recommend 150-160)')
            score -= 5
        elif len(description) > 160:
            issues.append(f'Description too long ({len(description)} chars, recommend 150-160)')
            score -= 5
        
        # Check for images
        images = re.findall(r'!\[([^\]]*)\]\([^\)]+\)', body)
        if not images:
            issues.append('No images found (consider adding visuals)')
            score -= 10
        
        # Check for alt text on images
        for alt in images:
            if not alt.strip():
                issues.append('Image(s) missing alt text')
                score -= 10
                break
        
        # Check heading structure
        headings = re.findall(r'^#+\s+(.+)$', body, re.MULTILINE)
        if len(headings) < self.targets['min_headings']:
            issues.append(f'Only {len(headings)} heading(s), recommend at least {self.targets["min_headings"]}')
            score -= 10
        
        # Check for external links
        links = re.findall(r'\[([^\]]+)\]\(([^\)]+)\)', body)
        external_links = [link for link in links if link[1].startswith('http')]
        if not external_links:
            issues.append('No external links (consider adding authoritative sources)')
            score -= 5
        
        score = max(0, score)
        
        if score >= 90:
            status = 'excellent'
        elif score >= 70:
            status = 'good'
        elif score >= 50:
            status = 'warning'
        else:
            status = 'poor'
        
        return {
            'score': score,
            'status': status,
            'title_length': len(title),
            'description_length': len(description),
            'image_count': len(images),
            'heading_count': len(headings),
            'external_link_count': len(external_links),
            'issues': issues
        }
    
    def _analyze_structure(self, body: str) -> Dict[str, Any]:
        """Analyze document structure"""
        issues = []
        
        # Extract headings with levels
        heading_matches = re.findall(r'^(#+)\s+(.+)$', body, re.MULTILINE)
        headings = [(len(h[0]), h[1]) for h in heading_matches]
        
        # Check heading hierarchy
        if headings:
            previous_level = 0
            for level, text in headings:
                if level > previous_level + 1:
                    issues.append(f'Heading skip: jumped from h{previous_level} to h{level}')
                previous_level = level
            
            # Check for h1
            h1_count = sum(1 for level, _ in headings if level == 1)
            if h1_count == 0:
                issues.append('No h1 heading found')
            elif h1_count > 1:
                issues.append(f'Multiple h1 headings found ({h1_count}), should have exactly one')
        else:
            issues.append('No headings found')
        
        # Check for lists
        lists = re.findall(r'^[-*+]\s+.+$', body, re.MULTILINE)
        ordered_lists = re.findall(r'^\d+\.\s+.+$', body, re.MULTILINE)
        
        # Check for code blocks
        code_blocks = re.findall(r'```[\s\S]*?```', body)
        inline_code = re.findall(r'`[^`]+`', body)
        
        status = 'good' if len(issues) == 0 else 'warning'
        
        return {
            'status': status,
            'heading_count': len(headings),
            'heading_levels': [level for level, _ in headings],
            'list_count': len(lists) + len(ordered_lists),
            'code_block_count': len(code_blocks),
            'inline_code_count': len(inline_code),
            'issues': issues
        }
    
    def _analyze_accessibility(self, body: str, html: str) -> Dict[str, Any]:
        """Analyze accessibility factors"""
        issues = []
        
        # Check images for alt text
        images = re.findall(r'!\[([^\]]*)\]\([^\)]+\)', body)
        images_without_alt = sum(1 for alt in images if not alt.strip())
        
        if images_without_alt > 0:
            issues.append(f'{images_without_alt} image(s) missing alt text')
        
        # Check for link text quality
        links = re.findall(r'\[([^\]]+)\]\([^\)]+\)', body)
        vague_links = [text for text in links if text.lower().strip() in 
                       ['click here', 'here', 'read more', 'link', 'this']]
        if vague_links:
            issues.append(f'{len(vague_links)} vague link text(s) found: {", ".join(set(vague_links))}')
        
        # Check for proper list formatting
        # This is basic - just ensure markdown lists are used
        
        status = 'good' if len(issues) == 0 else 'warning'
        
        return {
            'status': status,
            'image_count': len(images),
            'images_with_alt': len(images) - images_without_alt,
            'link_count': len(links),
            'vague_link_count': len(vague_links),
            'issues': issues
        }
    
    def _analyze_metadata(self, body: str) -> Dict[str, Any]:
        """Analyze general metadata"""
        paragraphs = [p.strip() for p in body.split('\n\n') if p.strip() and not p.startswith('#')]
        
        return {
            'paragraph_count': len(paragraphs),
            'character_count': len(body),
            'line_count': len(body.split('\n'))
        }
    
    def format_report(self, analysis: Dict[str, Any]) -> str:
        """Format analysis results as a readable report"""
        report = []
        
        # Header
        report.append("=" * 60)
        report.append(f"📊 Content Quality Report")
        report.append(f"File: {analysis['file']}")
        report.append("=" * 60)
        report.append("")
        
        # Readability
        r = analysis['readability']
        status_icon = self._status_icon(r['status'])
        report.append(f"📖 READABILITY {status_icon}")
        report.append(f"├─ Word count: {r['word_count']:,} words")
        report.append(f"├─ Reading time: ~{r['reading_time_minutes']} min")
        report.append(f"├─ Grade level: {r['grade_level']} (target: 6-10)")
        report.append(f"├─ Words/sentence: {r['words_per_sentence']}")
        report.append(f"└─ {r['message']}")
        report.append("")
        
        # SEO
        seo = analysis['seo']
        status_icon = self._status_icon(seo['status'])
        report.append(f"🔍 SEO SCORE: {seo['score']}/100 {status_icon}")
        report.append(f"├─ Title: {seo['title_length']} chars (recommend 50-60)")
        report.append(f"├─ Description: {seo['description_length']} chars (recommend 150-160)")
        report.append(f"├─ Images: {seo['image_count']}")
        report.append(f"├─ Headings: {seo['heading_count']}")
        report.append(f"└─ External links: {seo['external_link_count']}")
        
        if seo['issues']:
            report.append("")
            report.append("  Issues:")
            for issue in seo['issues']:
                report.append(f"  ⚠️  {issue}")
        report.append("")
        
        # Structure
        struct = analysis['structure']
        status_icon = self._status_icon(struct['status'])
        report.append(f"🏗️  STRUCTURE {status_icon}")
        report.append(f"├─ Headings: {struct['heading_count']}")
        report.append(f"├─ Lists: {struct['list_count']}")
        report.append(f"└─ Code blocks: {struct['code_block_count']}")
        
        if struct['issues']:
            report.append("")
            report.append("  Issues:")
            for issue in struct['issues']:
                report.append(f"  ⚠️  {issue}")
        report.append("")
        
        # Accessibility
        a11y = analysis['accessibility']
        status_icon = self._status_icon(a11y['status'])
        report.append(f"♿ ACCESSIBILITY {status_icon}")
        report.append(f"├─ Images with alt text: {a11y['images_with_alt']}/{a11y['image_count']}")
        report.append(f"├─ Total links: {a11y['link_count']}")
        report.append(f"└─ Vague links: {a11y['vague_link_count']}")
        
        if a11y['issues']:
            report.append("")
            report.append("  Issues:")
            for issue in a11y['issues']:
                report.append(f"  ⚠️  {issue}")
        report.append("")
        
        # Summary
        report.append("=" * 60)
        overall_status = self._calculate_overall_status(analysis)
        status_icon = self._status_icon(overall_status)
        report.append(f"Overall Status: {overall_status.upper()} {status_icon}")
        report.append("=" * 60)
        
        return '\n'.join(report)
    
    def _status_icon(self, status: str) -> str:
        """Return an icon for status"""
        icons = {
            'excellent': '🌟',
            'good': '✓',
            'warning': '⚠️',
            'poor': '✗',
            'error': '❌'
        }
        return icons.get(status, '•')
    
    def _calculate_overall_status(self, analysis: Dict[str, Any]) -> str:
        """Calculate overall content status"""
        statuses = [
            analysis['readability']['status'],
            analysis['seo']['status'],
            analysis['structure']['status'],
            analysis['accessibility']['status']
        ]
        
        if 'error' in statuses or 'poor' in statuses:
            return 'poor'
        elif statuses.count('warning') >= 2:
            return 'warning'
        elif 'excellent' in statuses and 'warning' not in statuses:
            return 'excellent'
        else:
            return 'good'

