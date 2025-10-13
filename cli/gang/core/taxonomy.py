"""
Taxonomy Manager - Notion-style hierarchical tagging system
Manages tags, categories, and their relationships across all content
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
import yaml
import json
from collections import defaultdict


class TaxonomyManager:
    """Manage hierarchical taxonomies across content"""
    
    def __init__(self, content_path: Path):
        self.content_path = Path(content_path)
        self.taxonomy_file = content_path / '.taxonomy.yaml'
        self.taxonomy = self._load_taxonomy()
    
    def _load_taxonomy(self) -> Dict[str, Any]:
        """Load taxonomy structure from file"""
        if self.taxonomy_file.exists():
            with open(self.taxonomy_file) as f:
                return yaml.safe_load(f) or {}
        
        # Default taxonomy structure
        return {
            'categories': {
                'Product': {
                    'description': 'Products and product-related content',
                    'children': ['Font', 'Design', 'Software', 'Hardware']
                },
                'Tutorial': {
                    'description': 'How-to guides and tutorials',
                    'children': ['Development', 'Design', 'Marketing']
                },
                'News': {
                    'description': 'Company and industry news',
                    'children': ['Announcement', 'Release', 'Update']
                },
                'Opinion': {
                    'description': 'Thought leadership and opinions',
                    'children': ['Essay', 'Review', 'Analysis']
                }
            },
            'tags': [
                'Open Source',
                'Typography',
                'Web Development',
                'Accessibility',
                'Performance',
                'SEO',
                'Design Systems'
            ]
        }
    
    def save_taxonomy(self):
        """Save taxonomy to file"""
        with open(self.taxonomy_file, 'w') as f:
            yaml.dump(self.taxonomy, f, default_flow_style=False, sort_keys=False)
    
    def add_category(self, name: str, description: str = '', parent: Optional[str] = None):
        """Add a new category or subcategory"""
        if parent:
            # Add as child
            if parent in self.taxonomy['categories']:
                if 'children' not in self.taxonomy['categories'][parent]:
                    self.taxonomy['categories'][parent]['children'] = []
                if name not in self.taxonomy['categories'][parent]['children']:
                    self.taxonomy['categories'][parent]['children'].append(name)
        else:
            # Add as top-level category
            self.taxonomy['categories'][name] = {
                'description': description,
                'children': []
            }
        
        self.save_taxonomy()
    
    def add_tag(self, tag: str):
        """Add a new tag"""
        if 'tags' not in self.taxonomy:
            self.taxonomy['tags'] = []
        
        if tag not in self.taxonomy['tags']:
            self.taxonomy['tags'].append(tag)
            self.save_taxonomy()
    
    def get_all_categories(self) -> Dict[str, Any]:
        """Get all categories with hierarchy"""
        return self.taxonomy.get('categories', {})
    
    def get_all_tags(self) -> List[str]:
        """Get all tags"""
        return sorted(self.taxonomy.get('tags', []))
    
    def analyze_content_taxonomy(self) -> Dict[str, Any]:
        """Analyze how taxonomy is used across content"""
        analysis = {
            'by_category': defaultdict(list),
            'by_tag': defaultdict(list),
            'untagged': [],
            'uncategorized': []
        }
        
        for md_file in self.content_path.rglob('*.md'):
            content = md_file.read_text()
            if content.startswith('---'):
                parts = content.split('---', 2)
                frontmatter = yaml.safe_load(parts[1]) if len(parts) > 1 else {}
                
                title = frontmatter.get('title', md_file.stem)
                category = frontmatter.get('category')
                tags = frontmatter.get('tags', [])
                
                relative_path = md_file.relative_to(self.content_path)
                
                if category:
                    analysis['by_category'][category].append({
                        'title': title,
                        'path': str(relative_path)
                    })
                else:
                    analysis['uncategorized'].append({
                        'title': title,
                        'path': str(relative_path)
                    })
                
                if tags:
                    for tag in tags:
                        analysis['by_tag'][tag].append({
                            'title': title,
                            'path': str(relative_path)
                        })
                else:
                    analysis['untagged'].append({
                        'title': title,
                        'path': str(relative_path)
                    })
        
        return dict(analysis)
    
    def get_related_content(self, category: Optional[str], tags: List[str]) -> List[Dict[str, Any]]:
        """Find related content based on category and tags"""
        related = []
        
        for md_file in self.content_path.rglob('*.md'):
            content = md_file.read_text()
            if content.startswith('---'):
                parts = content.split('---', 2)
                frontmatter = yaml.safe_load(parts[1]) if len(parts) > 1 else {}
                
                file_category = frontmatter.get('category')
                file_tags = frontmatter.get('tags', [])
                
                # Score based on matches
                score = 0
                if category and file_category == category:
                    score += 3  # Category match is worth more
                
                tag_matches = len(set(tags) & set(file_tags))
                score += tag_matches
                
                if score > 0:
                    related.append({
                        'title': frontmatter.get('title', md_file.stem),
                        'path': str(md_file.relative_to(self.content_path)),
                        'score': score,
                        'category': file_category,
                        'tags': file_tags
                    })
        
        # Sort by score descending
        related.sort(key=lambda x: x['score'], reverse=True)
        return related[:5]  # Top 5 related items
    
    def suggest_tags(self, content: str, title: str) -> List[str]:
        """Suggest tags based on content (simple keyword matching)"""
        content_lower = (content + ' ' + title).lower()
        suggestions = []
        
        # Check against existing tags
        for tag in self.get_all_tags():
            if tag.lower() in content_lower:
                suggestions.append(tag)
        
        return suggestions
    
    def suggest_category(self, content: str, title: str) -> Optional[str]:
        """Suggest category based on content"""
        content_lower = (content + ' ' + title).lower()
        
        # Simple keyword-based suggestion
        keywords = {
            'Product': ['product', 'launch', 'release', 'available', 'buy', 'pricing'],
            'Tutorial': ['how to', 'guide', 'tutorial', 'learn', 'step by step'],
            'News': ['announcing', 'released', 'update', 'news', 'today'],
            'Opinion': ['think', 'believe', 'opinion', 'perspective', 'essay']
        }
        
        scores = {}
        for category, kw_list in keywords.items():
            scores[category] = sum(1 for kw in kw_list if kw in content_lower)
        
        if max(scores.values()) > 0:
            return max(scores, key=scores.get)
        
        return None
    
    def export_for_seo(self) -> Dict[str, Any]:
        """Export taxonomy in SEO-friendly format"""
        return {
            '@context': 'https://schema.org',
            '@type': 'ItemList',
            'name': 'Content Categories',
            'itemListElement': [
                {
                    '@type': 'ListItem',
                    'position': idx + 1,
                    'name': cat_name,
                    'description': cat_data.get('description', ''),
                    'numberOfItems': len(cat_data.get('children', []))
                }
                for idx, (cat_name, cat_data) in enumerate(self.taxonomy.get('categories', {}).items())
            ]
        }
    
    def get_breadcrumb(self, category: str, subcategory: Optional[str] = None) -> List[Dict[str, str]]:
        """Generate breadcrumb navigation for SEO"""
        breadcrumb = [
            {'name': 'Home', 'url': '/'}
        ]
        
        if category:
            breadcrumb.append({
                'name': category,
                'url': f'/category/{category.lower().replace(" ", "-")}/'
            })
        
        if subcategory:
            breadcrumb.append({
                'name': subcategory,
                'url': f'/category/{category.lower().replace(" ", "-")}/{subcategory.lower().replace(" ", "-")}/'
            })
        
        return breadcrumb

