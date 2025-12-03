"""
GANG Content Importer
Import content from Google Docs, Notes, clipboard with automatic image extraction.
"""

import re
import base64
import io
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional
from datetime import datetime
import hashlib
from PIL import Image


class ContentImporter:
    """Import and process content with embedded images"""
    
    def __init__(self, config: Dict[str, Any], r2_storage=None, ai_client=None):
        self.config = config
        self.r2_storage = r2_storage
        self.ai_client = ai_client
        self.content_path = Path(config['build']['content'])
    
    def import_from_text(self, text_content: str, title: Optional[str] = None) -> Dict[str, Any]:
        """Import content from plain text or HTML (Google Docs paste)"""
        
        result = {
            'title': title or self._extract_title(text_content),
            'content': text_content,
            'images': [],
            'suggested_category': None,
            'suggested_slug': None,
            'slug_conflicts': [],
            'needs_review': []
        }
        
        # Extract and process images
        if self._has_html_images(text_content):
            result['images'] = self._extract_html_images(text_content)
            result['content'] = self._replace_html_images_with_markdown(text_content, result['images'])
        
        # Extract data URLs (base64 images from rich text paste)
        if 'data:image' in text_content:
            data_images = self._extract_data_url_images(text_content)
            result['images'].extend(data_images)
            result['content'] = self._replace_data_urls_with_markdown(result['content'], data_images)
        
        # Generate slug
        result['suggested_slug'] = self._generate_slug(result['title'])
        
        # Check for slug conflicts
        result['slug_conflicts'] = self._check_slug_uniqueness(result['suggested_slug'])
        
        # Use AI to suggest category if available
        if self.ai_client:
            result['suggested_category'] = self._ai_suggest_category(result['title'], result['content'])
        
        # Use AI to generate alt text for images
        if self.ai_client and result['images']:
            result['images'] = self._ai_generate_alt_text(result['images'], result['content'])
        
        return result
    
    def _extract_title(self, content: str) -> str:
        """Extract title from content (first heading or first line)"""
        # Try to find first markdown heading
        match = re.search(r'^#\s+(.+)$', content, re.MULTILINE)
        if match:
            return match.group(1).strip()
        
        # Try HTML h1
        match = re.search(r'<h1[^>]*>(.+?)</h1>', content, re.IGNORECASE)
        if match:
            return re.sub(r'<[^>]+>', '', match.group(1)).strip()
        
        # Fallback: first line
        first_line = content.split('\n')[0].strip()
        return re.sub(r'<[^>]+>', '', first_line)[:100]
    
    def _has_html_images(self, content: str) -> bool:
        """Check if content has HTML img tags"""
        return bool(re.search(r'<img[^>]+>', content, re.IGNORECASE))
    
    def _extract_html_images(self, content: str) -> List[Dict[str, Any]]:
        """Extract images from HTML img tags"""
        images = []
        pattern = r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>'
        
        for match in re.finditer(pattern, content, re.IGNORECASE):
            src = match.group(1)
            
            # Try to extract alt text
            alt_match = re.search(r'alt=["\']([^"\']+)["\']', match.group(0), re.IGNORECASE)
            alt = alt_match.group(1) if alt_match else ''
            
            images.append({
                'source': src,
                'alt': alt,
                'type': 'html',
                'original_tag': match.group(0)
            })
        
        return images
    
    def _extract_data_url_images(self, content: str) -> List[Dict[str, Any]]:
        """Extract base64-encoded images from data URLs"""
        images = []
        pattern = r'data:image/([a-zA-Z]+);base64,([A-Za-z0-9+/=]+)'
        
        for i, match in enumerate(re.finditer(pattern, content)):
            image_format = match.group(1)
            base64_data = match.group(2)
            
            images.append({
                'source': match.group(0),
                'format': image_format,
                'data': base64_data,
                'alt': '',
                'type': 'data_url',
                'index': i
            })
        
        return images
    
    def process_and_upload_images(
        self, 
        images: List[Dict[str, Any]], 
        slug: str,
        compress: bool = True
    ) -> List[Dict[str, Any]]:
        """Process images (compress, optimize) and upload to R2"""
        
        if not self.r2_storage or not self.r2_storage.is_configured():
            return images  # Return as-is if R2 not configured
        
        processed_images = []
        
        for i, image in enumerate(images):
            if image['type'] == 'data_url':
                # Decode base64 image
                processed = self._process_data_url_image(image, slug, i, compress)
                if processed:
                    processed_images.append(processed)
            
            elif image['type'] == 'html' and not image['source'].startswith('http'):
                # Local image reference - would need to be uploaded
                processed_images.append(image)
            
            else:
                # External URL - keep as-is
                processed_images.append(image)
        
        return processed_images
    
    def _process_data_url_image(
        self, 
        image: Dict[str, Any], 
        slug: str, 
        index: int,
        compress: bool
    ) -> Optional[Dict[str, Any]]:
        """Decode, compress, and upload data URL image"""
        try:
            # Decode base64
            image_data = base64.b64decode(image['data'])
            img = Image.open(io.BytesIO(image_data))
            
            # Compress if requested
            if compress:
                img = self._compress_image(img)
            
            # Generate filename
            timestamp = datetime.now().strftime('%Y%m%d-%H%M%S')
            filename = f"{slug}-{timestamp}-{index}.{image['format']}"
            
            # Save temporarily
            temp_path = Path(f"/tmp/{filename}")
            img.save(temp_path, format=image['format'].upper(), quality=85, optimize=True)
            
            # Upload to R2
            remote_path = f"images/{slug}/{filename}"
            result = self.r2_storage.upload_file(temp_path, remote_path)
            
            # Clean up temp file
            temp_path.unlink()
            
            if 'error' not in result:
                return {
                    'source': result['public_url'],
                    'alt': image['alt'],
                    'type': 'uploaded',
                    'size': result['size'],
                    'original_size': len(image_data)
                }
        
        except Exception as e:
            print(f"Error processing image: {e}")
        
        return None
    
    def _compress_image(self, img: Image.Image, max_width: int = 1600, quality: int = 85) -> Image.Image:
        """Compress image for web"""
        width, height = img.size
        
        # Resize if too large
        if width > max_width:
            new_height = int(height * (max_width / width))
            img = img.resize((max_width, new_height), Image.Resampling.LANCZOS)
        
        # Convert RGBA to RGB if needed
        if img.mode in ('RGBA', 'LA'):
            background = Image.new('RGB', img.size, (255, 255, 255))
            background.paste(img, mask=img.split()[-1])
            img = background
        
        return img
    
    def _replace_html_images_with_markdown(self, content: str, images: List[Dict[str, Any]]) -> str:
        """Replace HTML img tags with markdown syntax"""
        for image in images:
            if 'original_tag' in image:
                alt = image['alt'] or 'Image'
                src = image['source']
                markdown_img = f"![{alt}]({src})"
                content = content.replace(image['original_tag'], markdown_img)
        
        return content
    
    def _replace_data_urls_with_markdown(self, content: str, images: List[Dict[str, Any]]) -> str:
        """Replace data URLs with markdown image references"""
        for image in images:
            if image['type'] == 'uploaded':
                alt = image['alt'] or 'Image'
                markdown_img = f"![{alt}]({image['source']})"
                # Replace the data URL with markdown
                content = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', markdown_img, content, count=1)
        
        return content
    
    def _generate_slug(self, title: str) -> str:
        """Generate URL-safe slug from title"""
        # Convert to lowercase
        slug = title.lower()
        
        # Replace spaces and special chars with hyphens
        slug = re.sub(r'[^\w\s-]', '', slug)
        slug = re.sub(r'[-\s]+', '-', slug)
        
        # Remove leading/trailing hyphens
        slug = slug.strip('-')
        
        # Limit length
        slug = slug[:100]
        
        return slug
    
    def _check_slug_uniqueness(self, slug: str) -> List[str]:
        """Check if slug is already used"""
        conflicts = []
        
        # Check all content types
        for content_type in ['posts', 'pages', 'projects', 'people']:
            type_path = self.content_path / content_type
            if not type_path.exists():
                continue
            
            for md_file in type_path.glob('*.md'):
                if md_file.stem == slug:
                    conflicts.append(f"{content_type}/{slug}.md")
        
        return conflicts
    
    def _ai_suggest_category(self, title: str, content: str) -> Dict[str, Any]:
        """Use AI to suggest where this content belongs"""
        if not self.ai_client:
            return {'category': 'pages', 'confidence': 'low', 'reasoning': 'No AI available'}
        
        # Get first 500 chars of content for context
        content_preview = content[:500]
        
        prompt = f"""Analyze this content and suggest the best category for it.

Title: {title}

Content preview:
{content_preview}

Categories:
- posts: Blog posts, articles, news, time-sensitive content
- pages: About, Contact, Documentation, evergreen content
- projects: Portfolio items, case studies, work samples

Respond in JSON:
{{
  "category": "posts|pages|projects|people",
  "confidence": "high|medium|low",
  "reasoning": "Brief explanation why"
}}"""
        
        try:
            response = self.ai_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                messages=[{"role": "user", "content": prompt}]
            )
            
            import json
            suggestion_text = response.content[0].text.strip()
            
            # Extract JSON
            if '```json' in suggestion_text:
                suggestion_text = suggestion_text.split('```json')[1].split('```')[0].strip()
            elif '```' in suggestion_text:
                suggestion_text = suggestion_text.split('```')[1].split('```')[0].strip()
            
            return json.loads(suggestion_text)
        
        except Exception as e:
            return {
                'category': 'pages',
                'confidence': 'low',
                'reasoning': f'AI suggestion failed: {str(e)[:50]}'
            }
    
    def _ai_generate_alt_text(self, images: List[Dict[str, Any]], content_context: str) -> List[Dict[str, Any]]:
        """Use AI to generate alt text for images that don't have it"""
        if not self.ai_client:
            return images
        
        # Get content preview for context
        context_preview = content_context[:300]
        
        for image in images:
            if not image.get('alt') or not image['alt'].strip():
                # Generate alt text with AI
                prompt = f"""Generate descriptive alt text for an image in this article.

Article context:
{context_preview}

Image URL: {image.get('source', 'embedded image')}

Generate alt text that is:
- Descriptive (what's in the image)
- Concise (10-15 words max)
- Contextual (relates to the article)
- Accessible (helpful for screen readers)

Respond with just the alt text, no quotes or formatting."""
                
                try:
                    response = self.ai_client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=100,
                        messages=[{"role": "user", "content": prompt}]
                    )
                    
                    alt_text = response.content[0].text.strip()
                    # Remove quotes if AI added them
                    alt_text = alt_text.strip('"\'')
                    
                    image['alt'] = alt_text
                    image['alt_generated_by_ai'] = True
                
                except Exception as e:
                    image['alt'] = 'Image'
                    image['alt_generation_failed'] = str(e)[:100]
        
        return images
    
    def create_markdown_file(
        self, 
        title: str, 
        content: str, 
        category: str, 
        slug: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Tuple[Path, str]:
        """Create markdown file with frontmatter"""
        
        # Prepare frontmatter
        frontmatter = {
            'type': category.rstrip('s'),  # posts → post
            'title': title,
            'date': datetime.now().strftime('%Y-%m-%d'),
            'status': 'draft',  # Always start as draft for review
        }
        
        if metadata:
            frontmatter.update(metadata)
        
        # Create markdown content
        import yaml
        frontmatter_str = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False)
        
        markdown_content = f"""---
{frontmatter_str}---

{content}
"""
        
        # Determine file path
        file_path = self.content_path / category / f"{slug}.md"
        
        return file_path, markdown_content
    
    def save_imported_content(
        self, 
        file_path: Path, 
        content: str, 
        create_commit: bool = False
    ) -> Dict[str, Any]:
        """Save imported content and optionally create git commit"""
        
        # Create parent directory
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Write file
        file_path.write_text(content)
        
        result = {
            'file_path': str(file_path),
            'success': True
        }
        
        # Create git commit if requested
        if create_commit:
            try:
                import subprocess
                
                subprocess.run(['git', 'add', str(file_path)], check=True)
                
                commit_msg = f"Import content: {file_path.stem} [AI-assisted]\n\nAuto-imported with:\n- AI category suggestion\n- AI alt text generation\n- Image compression & upload"
                
                subprocess.run(['git', 'commit', '-m', commit_msg], check=True)
                
                result['git_commit'] = True
                result['commit_message'] = commit_msg
            
            except Exception as e:
                result['git_commit'] = False
                result['git_error'] = str(e)
        
        return result


class SlugChecker:
    """Check slug uniqueness across the site"""
    
    def __init__(self, content_path: Path):
        self.content_path = content_path
    
    def check_all_slugs(self) -> Dict[str, Any]:
        """Check all slugs for uniqueness"""
        slug_map = {}
        duplicates = {}
        
        # Scan all content types
        for content_type in ['posts', 'pages', 'projects', 'newsletters', 'people']:
            type_path = self.content_path / content_type
            if not type_path.exists():
                continue
            
            for md_file in type_path.glob('*.md'):
                slug = md_file.stem
                
                if slug not in slug_map:
                    slug_map[slug] = []
                
                slug_map[slug].append(f"{content_type}/{slug}.md")
        
        # Find duplicates
        for slug, files in slug_map.items():
            if len(files) > 1:
                duplicates[slug] = files
        
        return {
            'total_slugs': len(slug_map),
            'unique_slugs': len([s for s in slug_map.values() if len(s) == 1]),
            'duplicate_slugs': len(duplicates),
            'duplicates': duplicates
        }
    
    def suggest_unique_slug(self, base_slug: str, category: str) -> str:
        """Suggest a unique slug by appending numbers if needed"""
        slug = base_slug
        counter = 1
        
        while True:
            file_path = self.content_path / category / f"{slug}.md"
            if not file_path.exists():
                return slug
            
            slug = f"{base_slug}-{counter}"
            counter += 1
            
            if counter > 100:  # Safety limit
                import random
                slug = f"{base_slug}-{random.randint(1000, 9999)}"
                break
        
        return slug

