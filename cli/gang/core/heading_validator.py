"""
Heading Validator
Validates heading structure for accessibility compliance
Prevents publishing pages with non-sequential headings
"""

from pathlib import Path
from typing import Dict, List, Tuple, Optional
import re
from bs4 import BeautifulSoup
import markdown


class HeadingValidator:
    """Validate heading structure for accessibility"""
    
    def __init__(self):
        self.md = markdown.Markdown()
    
    def validate_markdown(self, content: str) -> Dict[str, any]:
        """
        Validate heading order in markdown content
        
        Args:
            content: Markdown content string
        
        Returns:
            Dict with validation results:
            {
                'valid': bool,
                'errors': List[str],
                'headings': List[Tuple[int, str, int]],  # (level, text, line_number)
                'suggestions': List[str]
            }
        """
        
        result = {
            'valid': True,
            'errors': [],
            'headings': [],
            'suggestions': []
        }
        
        # Extract headings from markdown
        lines = content.split('\n')
        headings = []
        
        for line_num, line in enumerate(lines, 1):
            # Match markdown headings: # Heading, ## Heading, etc.
            match = re.match(r'^(#{1,6})\s+(.+)$', line.strip())
            if match:
                level = len(match.group(1))
                text = match.group(2).strip()
                headings.append((level, text, line_num))
        
        result['headings'] = headings
        
        if not headings:
            result['suggestions'].append("No headings found. Consider adding headings to structure your content.")
            return result
        
        # Validate heading order
        errors = self._validate_heading_sequence(headings)
        
        if errors:
            result['valid'] = False
            result['errors'] = errors
            result['suggestions'] = self._generate_suggestions(headings, errors)
        
        return result
    
    def validate_html(self, html: str) -> Dict[str, any]:
        """
        Validate heading order in HTML content
        
        Args:
            html: HTML content string
        
        Returns:
            Dict with validation results
        """
        
        result = {
            'valid': True,
            'errors': [],
            'headings': [],
            'suggestions': []
        }
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # Extract all headings in order
        headings = []
        for tag in soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6']):
            level = int(tag.name[1])
            text = tag.get_text().strip()
            headings.append((level, text, None))  # No line number for HTML
        
        result['headings'] = headings
        
        if not headings:
            result['suggestions'].append("No headings found in HTML.")
            return result
        
        # Validate heading order
        errors = self._validate_heading_sequence(headings)
        
        if errors:
            result['valid'] = False
            result['errors'] = errors
            result['suggestions'] = self._generate_suggestions(headings, errors)
        
        return result
    
    def _validate_heading_sequence(self, headings: List[Tuple[int, str, Optional[int]]]) -> List[str]:
        """
        Check if headings are in sequential order (no skips)
        
        Args:
            headings: List of (level, text, line_number) tuples
        
        Returns:
            List of error messages
        """
        errors = []
        
        # Check for multiple h1s
        h1_count = sum(1 for level, _, _ in headings if level == 1)
        if h1_count == 0:
            errors.append("Missing h1 heading. Every page should have exactly one h1.")
        elif h1_count > 1:
            h1_headings = [f"'{text}' (line {line})" if line else f"'{text}'" 
                          for level, text, line in headings if level == 1]
            errors.append(f"Multiple h1 headings found ({h1_count}): {', '.join(h1_headings)}. Only one h1 is allowed per page.")
        
        # Check for heading skips
        prev_level = 0
        for i, (level, text, line_num) in enumerate(headings):
            if prev_level > 0 and level > prev_level + 1:
                location = f" (line {line_num})" if line_num else ""
                skip_info = f"h{prev_level} → h{level}"
                errors.append(
                    f"Heading level skip: {skip_info} at '{text}'{location}. "
                    f"Headings should not skip levels (use h{prev_level + 1} instead of h{level})."
                )
            
            prev_level = level
        
        return errors
    
    def _generate_suggestions(self, headings: List[Tuple[int, str, Optional[int]]], 
                            errors: List[str]) -> List[str]:
        """Generate helpful suggestions to fix heading issues"""
        
        suggestions = []
        
        # Suggest correct structure
        if any("skip" in error.lower() for error in errors):
            suggestions.append("Fix: Headings should follow a sequential hierarchy: h1 → h2 → h3, etc.")
            suggestions.append("Example: # Main Title, ## Section, ### Subsection")
        
        if any("multiple h1" in error.lower() for error in errors):
            suggestions.append("Fix: Use only one h1 (# in markdown) for the page title.")
            suggestions.append("Use h2 (##) for main sections instead.")
        
        if any("missing h1" in error.lower() for error in errors):
            suggestions.append("Fix: Add a main title with h1 (# in markdown) at the top of your content.")
        
        # Show corrected structure
        suggestions.append("\nCurrent heading structure:")
        for level, text, line_num in headings:
            location = f" (line {line_num})" if line_num else ""
            indent = "  " * (level - 1)
            suggestions.append(f"{indent}h{level}: {text}{location}")
        
        return suggestions
    
    def validate_file(self, file_path: Path) -> Dict[str, any]:
        """
        Validate heading structure in a markdown file
        
        Args:
            file_path: Path to markdown file
        
        Returns:
            Dict with validation results
        """
        
        content = file_path.read_text()
        
        # Skip frontmatter if present
        if content.startswith('---'):
            parts = content.split('---', 2)
            if len(parts) >= 3:
                content = parts[2]
        
        result = self.validate_markdown(content)
        result['file'] = str(file_path)
        
        return result
    
    def generate_error_report(self, validation_result: Dict[str, any]) -> str:
        """Generate a formatted error report for display"""
        
        if validation_result['valid']:
            return "✅ Heading structure is valid!"
        
        report = []
        report.append("❌ Heading Validation Failed\n")
        report.append("=" * 60)
        
        # Show errors
        if validation_result['errors']:
            report.append("\nErrors:")
            for i, error in enumerate(validation_result['errors'], 1):
                report.append(f"{i}. {error}")
        
        # Show suggestions
        if validation_result['suggestions']:
            report.append("\n" + "-" * 60)
            report.append("\nHow to fix:")
            for suggestion in validation_result['suggestions']:
                report.append(suggestion)
        
        report.append("\n" + "=" * 60)
        report.append("\n⚠️  Please fix these issues before publishing.")
        
        return '\n'.join(report)

