"""
GANG AI Optimizer
Build-time AI content optimization using Anthropic Claude
"""

import os
import hashlib
import json
from pathlib import Path
from typing import Dict, Any, Optional
import anthropic
from bs4 import BeautifulSoup

class AIOptimizer:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.ai_config = config.get('ai', {})
        self.cache_dir = Path('.gang/cache')
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Initialize Anthropic client
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if api_key:
            self.client = anthropic.Anthropic(api_key=api_key)
        else:
            self.client = None
    
    def _get_cache_key(self, content: str) -> str:
        """Generate cache key based on content hash"""
        return hashlib.sha256(content.encode()).hexdigest()
    
    def _get_cached(self, cache_key: str) -> Optional[Dict]:
        """Retrieve cached AI result"""
        cache_file = self.cache_dir / f"{cache_key}.json"
        if cache_file.exists():
            with open(cache_file, 'r') as f:
                return json.load(f)
        return None
    
    def _save_cache(self, cache_key: str, data: Dict):
        """Save AI result to cache"""
        cache_file = self.cache_dir / f"{cache_key}.json"
        with open(cache_file, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _call_claude(self, prompt: str) -> str:
        """Call Claude API with prompt"""
        if not self.client:
            return "{}"  # Return empty object if no API key
        
        try:
            message = self.client.messages.create(
                model=self.ai_config.get('model', 'claude-sonnet-4'),
                max_tokens=2000,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )
            return message.content[0].text
        except Exception as e:
            print(f"AI optimization error: {e}")
            return "{}"
    
    def generate_seo(self, content: str, frontmatter: Dict) -> Dict[str, str]:
        """Generate SEO title and description"""
        # Check cache
        cache_key = self._get_cache_key(f"seo:{content}")
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        # Don't overwrite human-written content
        if self.ai_config.get('never_overwrite_human', True):
            if frontmatter.get('seo', {}).get('title') and frontmatter.get('seo', {}).get('description'):
                return frontmatter.get('seo', {})
        
        prompt = f"""You are an SEO expert. Given this content, generate an SEO-optimized title and description.

Content:
{content[:1000]}...

Return JSON only:
{{
  "title": "SEO-optimized title (60 chars max)",
  "description": "SEO-optimized description (155 chars max)"
}}"""
        
        response = self._call_claude(prompt)
        
        try:
            seo_data = json.loads(response)
        except json.JSONDecodeError:
            seo_data = {
                "title": frontmatter.get('title', ''),
                "description": frontmatter.get('summary', '')
            }
        
        # Cache result
        self._save_cache(cache_key, seo_data)
        
        return seo_data
    
    def generate_alt_text(self, image_src: str, context: str = "") -> str:
        """Generate alt text for image based on context"""
        cache_key = self._get_cache_key(f"alt:{image_src}:{context}")
        cached = self._get_cached(cache_key)
        if cached:
            return cached.get('alt', '')
        
        prompt = f"""Generate descriptive alt text for an image in this context:

Image: {image_src}
Context: {context[:200]}

Return JSON only:
{{
  "alt": "Concise, descriptive alt text (125 chars max)"
}}"""
        
        response = self._call_claude(prompt)
        
        try:
            alt_data = json.loads(response)
        except json.JSONDecodeError:
            alt_data = {"alt": Path(image_src).stem.replace('-', ' ')}
        
        self._save_cache(cache_key, alt_data)
        
        return alt_data.get('alt', '')
    
    def generate_jsonld(self, content_type: str, frontmatter: Dict, content: str) -> Dict:
        """Generate JSON-LD structured data"""
        cache_key = self._get_cache_key(f"jsonld:{content_type}:{content}")
        cached = self._get_cached(cache_key)
        if cached:
            return cached
        
        # Don't overwrite existing JSON-LD
        if self.ai_config.get('never_overwrite_human', True):
            if frontmatter.get('jsonld'):
                return frontmatter.get('jsonld')
        
        site_config = self.config.get('site', {})
        
        prompt = f"""Generate JSON-LD structured data for this {content_type}.

Title: {frontmatter.get('title', '')}
Summary: {frontmatter.get('summary', '')}
Date: {frontmatter.get('date', '')}
Site: {site_config.get('title', '')}
URL: {site_config.get('url', '')}

Content preview:
{content[:500]}...

Return valid JSON-LD for Schema.org {content_type.title()}. Include @context, @type, headline, description, datePublished, author, etc.
"""
        
        response = self._call_claude(prompt)
        
        try:
            jsonld_data = json.loads(response)
        except json.JSONDecodeError:
            # Fallback to basic structure
            jsonld_data = {
                "@context": "https://schema.org",
                "@type": "Article" if content_type == "post" else "WebPage",
                "headline": frontmatter.get('title', ''),
                "description": frontmatter.get('summary', ''),
                "datePublished": str(frontmatter.get('date', '')),
                "author": {
                    "@type": "Organization",
                    "name": site_config.get('title', '')
                }
            }
        
        self._save_cache(cache_key, jsonld_data)
        
        return jsonld_data
    
    def optimize_content(self, markdown_content: str, frontmatter: Dict, content_type: str) -> Dict[str, Any]:
        """Run all AI optimizations on content"""
        if not self.client:
            print("⚠️  AI optimization skipped: No ANTHROPIC_API_KEY found")
            return frontmatter
        
        optimized = frontmatter.copy()
        fill_missing = self.ai_config.get('fill_missing', [])
        
        # Generate SEO if needed
        if 'seo.title' in fill_missing or 'seo.description' in fill_missing:
            if not optimized.get('seo'):
                optimized['seo'] = {}
            
            seo_data = self.generate_seo(markdown_content, frontmatter)
            
            if 'seo.title' in fill_missing and not optimized['seo'].get('title'):
                optimized['seo']['title'] = seo_data.get('title')
            
            if 'seo.description' in fill_missing and not optimized['seo'].get('description'):
                optimized['seo']['description'] = seo_data.get('description')
        
        # Generate JSON-LD if needed
        if 'jsonld' in fill_missing and not optimized.get('jsonld'):
            optimized['jsonld'] = self.generate_jsonld(content_type, frontmatter, markdown_content)
        
        # Note: Image alt text is handled during HTML generation
        
        return optimized
    
    def optimize_images_in_html(self, html: str, context: str = "") -> str:
        """Add missing alt text to images in HTML"""
        if not self.client:
            return html
        
        soup = BeautifulSoup(html, 'html.parser')
        images = soup.find_all('img')
        
        for img in images:
            if not img.get('alt'):
                src = img.get('src', '')
                alt_text = self.generate_alt_text(src, context)
                img['alt'] = alt_text
        
        return str(soup)
    
    def estimate_cost(self, num_documents: int) -> Dict[str, float]:
        """Estimate AI optimization costs"""
        # Rough estimates based on Claude Sonnet pricing
        cost_per_doc = 0.003  # ~$0.003 per document
        
        return {
            'documents': num_documents,
            'estimated_cost_usd': num_documents * cost_per_doc,
            'with_cache': num_documents * cost_per_doc * 0.1,  # 90% cache hit rate
        }

