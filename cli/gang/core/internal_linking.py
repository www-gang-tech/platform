"""
GANG Automatic Internal Linking
AI-powered contextual link suggestions between content.
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
import re
import os


class InternalLinkingSuggester:
    """Suggest contextual internal links between content"""
    
    def __init__(self, content_path: Path, api_key: Optional[str] = None):
        self.content_path = content_path
        self.api_key = api_key or os.environ.get('ANTHROPIC_API_KEY')
    
    def analyze_content_for_links(
        self,
        file_path: Path,
        all_content: List[Path]
    ) -> List[Dict[str, Any]]:
        """
        Analyze content and suggest internal links.
        Returns list of suggestions with context and target.
        """
        
        import yaml
        
        # Read source content
        source_content = file_path.read_text()
        
        # Parse frontmatter
        if source_content.startswith('---'):
            parts = source_content.split('---', 2)
            source_fm = yaml.safe_load(parts[1]) if len(parts) > 1 else {}
            source_body = parts[2] if len(parts) > 2 else source_content
        else:
            source_fm = {}
            source_body = source_content
        
        source_title = source_fm.get('title', file_path.stem)
        source_tags = source_fm.get('tags', [])
        
        # Build context about other content
        other_content = []
        for other_file in all_content:
            if other_file == file_path:
                continue
            
            try:
                other_text = other_file.read_text()
                if other_text.startswith('---'):
                    parts = other_text.split('---', 2)
                    other_fm = yaml.safe_load(parts[1]) if len(parts) > 1 else {}
                else:
                    other_fm = {}
                
                other_content.append({
                    'path': other_file,
                    'slug': other_file.stem,
                    'category': other_file.parent.name,
                    'title': other_fm.get('title', other_file.stem),
                    'summary': other_fm.get('summary', ''),
                    'tags': other_fm.get('tags', [])
                })
            except:
                continue
        
        # Find relevant links using simple heuristics
        suggestions = []
        
        # 1. Tag-based suggestions
        for other in other_content:
            common_tags = set(source_tags) & set(other.get('tags', []))
            if common_tags:
                suggestions.append({
                    'target_path': other['path'],
                    'target_url': f"/{other['category']}/{other['slug']}/",
                    'target_title': other['title'],
                    'reason': f"Shares tags: {', '.join(common_tags)}",
                    'confidence': 'medium',
                    'type': 'tag_match'
                })
        
        # 2. Keyword-based suggestions
        source_words = set(re.findall(r'\w{4,}', source_body.lower()))
        
        for other in other_content:
            other_title_words = set(re.findall(r'\w{4,}', other['title'].lower()))
            common_words = source_words & other_title_words
            
            if len(common_words) >= 2:
                suggestions.append({
                    'target_path': other['path'],
                    'target_url': f"/{other['category']}/{other['slug']}/",
                    'target_title': other['title'],
                    'reason': f"Related keywords: {', '.join(list(common_words)[:3])}",
                    'confidence': 'low',
                    'type': 'keyword_match'
                })
        
        # 3. AI-powered suggestions (if API key available)
        if self.api_key:
            ai_suggestions = self._get_ai_suggestions(
                source_title, source_body, other_content
            )
            suggestions.extend(ai_suggestions)
        
        # Deduplicate and sort by confidence
        seen = set()
        unique_suggestions = []
        
        for sug in suggestions:
            key = sug['target_url']
            if key not in seen:
                seen.add(key)
                unique_suggestions.append(sug)
        
        # Sort: high > medium > low
        confidence_order = {'high': 3, 'medium': 2, 'low': 1}
        unique_suggestions.sort(
            key=lambda x: confidence_order.get(x['confidence'], 0),
            reverse=True
        )
        
        return unique_suggestions[:10]  # Top 10 suggestions
    
    def _get_ai_suggestions(
        self,
        source_title: str,
        source_body: str,
        other_content: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Use AI to suggest highly relevant internal links"""
        
        try:
            from anthropic import Anthropic
            
            client = Anthropic(api_key=self.api_key)
            
            # Build context about available content
            available_content = "\n".join([
                f"- {c['title']} (/{c['category']}/{c['slug']}/): {c.get('summary', '')[:100]}"
                for c in other_content[:20]  # Limit to avoid token limits
            ])
            
            prompt = f"""You are analyzing content to suggest internal links.

SOURCE ARTICLE:
Title: {source_title}
Content: {source_body[:1000]}

AVAILABLE CONTENT TO LINK TO:
{available_content}

Task: Suggest up to 5 internal links that would add value for readers.

For each suggestion, provide:
1. Which content to link to
2. Where in the source article to add the link (suggest a sentence or paragraph)
3. Why this link is relevant

Return as JSON array:
[
  {{
    "target_slug": "example-post",
    "target_category": "posts",
    "target_title": "Example Post",
    "suggestion": "Add link after discussing X in paragraph 3",
    "reason": "Provides deeper explanation of the topic",
    "confidence": "high"
  }}
]
"""
            
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=2000,
                messages=[{"role": "user", "content": prompt}]
            )
            
            # Parse AI response
            import json
            ai_text = response.content[0].text
            
            # Extract JSON from response
            json_match = re.search(r'\[[\s\S]*\]', ai_text)
            if json_match:
                ai_suggestions_raw = json.loads(json_match.group())
                
                # Convert to our format
                return [
                    {
                        'target_path': None,  # Will be resolved later
                        'target_url': f"/{s['target_category']}/{s['target_slug']}/",
                        'target_title': s['target_title'],
                        'reason': s['reason'],
                        'suggestion': s.get('suggestion', ''),
                        'confidence': s.get('confidence', 'high'),
                        'type': 'ai_suggested'
                    }
                    for s in ai_suggestions_raw
                ]
            
            return []
        
        except Exception as e:
            return []
    
    def generate_internal_links_report(
        self,
        all_content: List[Path]
    ) -> Dict[str, Any]:
        """Generate report of internal linking opportunities"""
        
        report = {
            'total_files': len(all_content),
            'files_analyzed': 0,
            'total_suggestions': 0,
            'by_file': []
        }
        
        for file_path in all_content:
            try:
                suggestions = self.analyze_content_for_links(file_path, all_content)
                
                if suggestions:
                    report['files_analyzed'] += 1
                    report['total_suggestions'] += len(suggestions)
                    report['by_file'].append({
                        'file': str(file_path.relative_to(self.content_path)),
                        'suggestions': suggestions
                    })
            except:
                continue
        
        return report

