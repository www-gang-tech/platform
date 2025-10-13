"""
GANG Schema.org Maximizer
Auto-detect and generate all applicable Schema.org types.
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
import re
from datetime import datetime


class SchemaMaximizer:
    """Generate comprehensive Schema.org structured data"""
    
    def __init__(self, site_url: str):
        self.site_url = site_url.rstrip('/')
    
    def detect_and_generate_schemas(
        self,
        content: str,
        frontmatter: Dict[str, Any],
        url: str
    ) -> List[Dict[str, Any]]:
        """
        Detect content type and generate all applicable schemas.
        Returns list of JSON-LD objects.
        """
        
        schemas = []
        
        # Base Article schema (always applicable for blog posts)
        article_schema = self._generate_article_schema(content, frontmatter, url)
        schemas.append(article_schema)
        
        # Detect FAQs
        if self._has_faq_pattern(content):
            faq_schema = self._generate_faq_schema(content)
            if faq_schema:
                schemas.append(faq_schema)
        
        # Detect How-To
        if self._has_howto_pattern(content):
            howto_schema = self._generate_howto_schema(content, frontmatter)
            if howto_schema:
                schemas.append(howto_schema)
        
        # Detect Recipe
        if self._has_recipe_pattern(content):
            recipe_schema = self._generate_recipe_schema(content, frontmatter)
            if recipe_schema:
                schemas.append(recipe_schema)
        
        # Detect Course
        if self._has_course_pattern(content):
            course_schema = self._generate_course_schema(content, frontmatter)
            if course_schema:
                schemas.append(course_schema)
        
        # Detect Video
        if self._has_video_pattern(content):
            video_schema = self._generate_video_schema(content, frontmatter)
            if video_schema:
                schemas.append(video_schema)
        
        return schemas
    
    def _generate_article_schema(
        self,
        content: str,
        frontmatter: Dict[str, Any],
        url: str
    ) -> Dict[str, Any]:
        """Generate Article schema"""
        
        schema = {
            '@context': 'https://schema.org',
            '@type': 'Article',
            'headline': frontmatter.get('title', ''),
            'description': frontmatter.get('summary', frontmatter.get('description', '')),
            'url': url,
            'datePublished': str(frontmatter.get('date', datetime.now().date())),
            'dateModified': str(frontmatter.get('updated', frontmatter.get('date', datetime.now().date()))),
            'author': {
                '@type': 'Person',
                'name': frontmatter.get('author', 'GANG')
            }
        }
        
        # Add image if available
        if frontmatter.get('image'):
            schema['image'] = f"{self.site_url}/{frontmatter['image']}"
        
        # Word count
        word_count = len(content.split())
        if word_count > 0:
            schema['wordCount'] = word_count
        
        return schema
    
    def _has_faq_pattern(self, content: str) -> bool:
        """Detect FAQ pattern in content"""
        # Look for Q&A patterns
        patterns = [
            r'(?:^|\n)#+\s*(?:Q|Question)[:?]',
            r'(?:^|\n)#+\s*(?:A|Answer):',
            r'(?:^|\n)#+\s*(?:FAQ|Frequently Asked Questions)',
            r'\*\*(?:Q|Question)\*\*[:?]'
        ]
        
        return any(re.search(pattern, content, re.IGNORECASE) for pattern in patterns)
    
    def _generate_faq_schema(self, content: str) -> Optional[Dict[str, Any]]:
        """Generate FAQPage schema from content"""
        
        # Extract Q&A pairs
        qa_pairs = []
        
        # Pattern 1: Markdown headings
        # ## Question? \n Answer...
        pattern1 = re.finditer(
            r'#+\s*(.+?\?)\s*\n+(.+?)(?=\n#+|\Z)',
            content,
            re.DOTALL
        )
        
        for match in pattern1:
            question = match.group(1).strip()
            answer = match.group(2).strip()
            
            qa_pairs.append({
                '@type': 'Question',
                'name': question,
                'acceptedAnswer': {
                    '@type': 'Answer',
                    'text': answer[:500]  # Truncate long answers
                }
            })
        
        # Pattern 2: **Q:** ... **A:** ...
        pattern2 = re.finditer(
            r'\*\*(?:Q|Question)\*\*:?\s*(.+?)\s*\*\*(?:A|Answer)\*\*:?\s*(.+?)(?=\*\*(?:Q|Question)\*\*|\Z)',
            content,
            re.DOTALL | re.IGNORECASE
        )
        
        for match in pattern2:
            question = match.group(1).strip()
            answer = match.group(2).strip()
            
            qa_pairs.append({
                '@type': 'Question',
                'name': question,
                'acceptedAnswer': {
                    '@type': 'Answer',
                    'text': answer[:500]
                }
            })
        
        if len(qa_pairs) >= 2:  # Need at least 2 Q&A pairs for FAQPage
            return {
                '@context': 'https://schema.org',
                '@type': 'FAQPage',
                'mainEntity': qa_pairs
            }
        
        return None
    
    def _has_howto_pattern(self, content: str) -> bool:
        """Detect How-To pattern"""
        patterns = [
            r'#+\s*How to',
            r'#+\s*Step \d+',
            r'^\d+\.\s+[A-Z]',  # Numbered steps
            r'#+\s*Tutorial',
            r'#+\s*Guide'
        ]
        
        return any(re.search(pattern, content, re.IGNORECASE | re.MULTILINE) for pattern in patterns)
    
    def _generate_howto_schema(
        self,
        content: str,
        frontmatter: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Generate HowTo schema"""
        
        # Extract steps
        steps = []
        
        # Pattern: ## Step 1: Title \n Content
        step_pattern = re.finditer(
            r'#+\s*Step\s+(\d+):?\s*(.+?)\n+(.+?)(?=\n#+\s*Step|\Z)',
            content,
            re.DOTALL | re.IGNORECASE
        )
        
        for match in step_pattern:
            step_num = match.group(1)
            step_title = match.group(2).strip()
            step_text = match.group(3).strip()
            
            steps.append({
                '@type': 'HowToStep',
                'position': int(step_num),
                'name': step_title,
                'text': step_text[:300]
            })
        
        # Pattern: 1. Title \n Content
        if not steps:
            numbered_pattern = re.finditer(
                r'^(\d+)\.\s+(.+?)$\n+(.+?)(?=^\d+\.|\Z)',
                content,
                re.MULTILINE | re.DOTALL
            )
            
            for match in numbered_pattern:
                step_num = match.group(1)
                step_title = match.group(2).strip()
                step_text = match.group(3).strip()
                
                steps.append({
                    '@type': 'HowToStep',
                    'position': int(step_num),
                    'name': step_title,
                    'text': step_text[:300]
                })
        
        if len(steps) >= 2:
            return {
                '@context': 'https://schema.org',
                '@type': 'HowTo',
                'name': frontmatter.get('title', ''),
                'description': frontmatter.get('summary', ''),
                'step': steps
            }
        
        return None
    
    def _has_recipe_pattern(self, content: str) -> bool:
        """Detect recipe pattern"""
        patterns = [
            r'#+\s*Ingredients',
            r'#+\s*Instructions',
            r'\d+\s+(?:cups?|tablespoons?|teaspoons?)',
            r'(?:Prep|Cook|Total)\s+Time'
        ]
        
        return any(re.search(pattern, content, re.IGNORECASE) for pattern in patterns)
    
    def _generate_recipe_schema(
        self,
        content: str,
        frontmatter: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Generate Recipe schema"""
        
        # Extract ingredients
        ingredients = []
        ingredients_match = re.search(
            r'#+\s*Ingredients\s*\n+((?:[-*]\s+.+\n?)+)',
            content,
            re.IGNORECASE
        )
        
        if ingredients_match:
            ingredient_lines = ingredients_match.group(1).strip().split('\n')
            ingredients = [
                re.sub(r'^[-*]\s+', '', line).strip()
                for line in ingredient_lines if line.strip()
            ]
        
        # Extract instructions
        instructions = []
        instructions_match = re.search(
            r'#+\s*Instructions\s*\n+((?:[-*\d.]\s+.+\n?)+)',
            content,
            re.IGNORECASE
        )
        
        if instructions_match:
            instruction_lines = instructions_match.group(1).strip().split('\n')
            for i, line in enumerate(instruction_lines):
                if line.strip():
                    instructions.append({
                        '@type': 'HowToStep',
                        'position': i + 1,
                        'text': re.sub(r'^[-*\d.]\s+', '', line).strip()
                    })
        
        if ingredients and instructions:
            return {
                '@context': 'https://schema.org',
                '@type': 'Recipe',
                'name': frontmatter.get('title', ''),
                'description': frontmatter.get('summary', ''),
                'recipeIngredient': ingredients,
                'recipeInstructions': instructions
            }
        
        return None
    
    def _has_course_pattern(self, content: str) -> bool:
        """Detect course/tutorial pattern"""
        patterns = [
            r'#+\s*(?:Lesson|Module|Chapter)\s+\d+',
            r'#+\s*Course',
            r'#+\s*Learning Objectives',
            r'#+\s*Prerequisites'
        ]
        
        return any(re.search(pattern, content, re.IGNORECASE) for pattern in patterns)
    
    def _generate_course_schema(
        self,
        content: str,
        frontmatter: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Generate Course schema"""
        
        # Extract lessons/modules
        lessons = []
        lesson_pattern = re.finditer(
            r'#+\s*(?:Lesson|Module|Chapter)\s+(\d+):?\s*(.+?)\n+(.+?)(?=\n#+\s*(?:Lesson|Module|Chapter)|\Z)',
            content,
            re.DOTALL | re.IGNORECASE
        )
        
        for match in lesson_pattern:
            lesson_num = match.group(1)
            lesson_title = match.group(2).strip()
            lesson_content = match.group(3).strip()
            
            lessons.append({
                '@type': 'LearningResource',
                'position': int(lesson_num),
                'name': lesson_title,
                'description': lesson_content[:200]
            })
        
        if lessons:
            return {
                '@context': 'https://schema.org',
                '@type': 'Course',
                'name': frontmatter.get('title', ''),
                'description': frontmatter.get('summary', ''),
                'hasCourseInstance': lessons
            }
        
        return None
    
    def _has_video_pattern(self, content: str) -> bool:
        """Detect video embed"""
        patterns = [
            r'youtube\.com',
            r'vimeo\.com',
            r'<iframe.*?video',
            r'\[.*?\]\(.*?\.mp4\)'
        ]
        
        return any(re.search(pattern, content, re.IGNORECASE) for pattern in patterns)
    
    def _generate_video_schema(
        self,
        content: str,
        frontmatter: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Generate VideoObject schema"""
        
        # Extract video URL
        video_url = None
        
        youtube_match = re.search(r'youtube\.com/watch\?v=([^&\s]+)', content)
        if youtube_match:
            video_id = youtube_match.group(1)
            video_url = f"https://www.youtube.com/watch?v={video_id}"
        
        vimeo_match = re.search(r'vimeo\.com/(\d+)', content)
        if vimeo_match:
            video_id = vimeo_match.group(1)
            video_url = f"https://vimeo.com/{video_id}"
        
        if video_url:
            return {
                '@context': 'https://schema.org',
                '@type': 'VideoObject',
                'name': frontmatter.get('title', ''),
                'description': frontmatter.get('summary', ''),
                'contentUrl': video_url,
                'uploadDate': str(frontmatter.get('date', datetime.now().date()))
            }
        
        return None

