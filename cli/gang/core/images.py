"""
GANG Image Processor
Generate responsive images in multiple formats (AVIF, WebP)
"""

from pathlib import Path
from typing import Dict, List, Any, Tuple
from PIL import Image
import hashlib

class ImageProcessor:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.image_config = config.get('images', {})
        self.formats = self.image_config.get('formats', ['webp', 'avif'])
        self.widths = self.image_config.get('widths', [640, 1024, 1600])
        self.quality = self.image_config.get('quality', {'avif': 85, 'webp': 85})
    
    def generate_blurhash(self, image_path: Path) -> str:
        """Generate placeholder hash (simplified version)"""
        # For now, return a simple base64-like string
        # In production, would use actual blurhash library
        return hashlib.md5(str(image_path).encode()).hexdigest()[:16]
    
    def generate_responsive_images(self, image_path: Path, output_dir: Path) -> List[Dict[str, Any]]:
        """Generate responsive image variants"""
        variants = []
        
        try:
            with Image.open(image_path) as img:
                original_width, original_height = img.size
                
                # Convert to RGB if needed
                if img.mode in ('RGBA', 'LA', 'P'):
                    background = Image.new('RGB', img.size, (255, 255, 255))
                    if img.mode == 'P':
                        img = img.convert('RGBA')
                    background.paste(img, mask=img.split()[-1] if img.mode in ('RGBA', 'LA') else None)
                    img = background
                
                for width in self.widths:
                    # Skip if width is larger than original
                    if width > original_width:
                        continue
                    
                    # Calculate height maintaining aspect ratio
                    height = int(original_height * (width / original_width))
                    
                    # Resize image
                    resized = img.resize((width, height), Image.Resampling.LANCZOS)
                    
                    # Generate variants in different formats
                    for format in self.formats:
                        output_filename = f"{image_path.stem}-{width}w.{format}"
                        output_path = output_dir / output_filename
                        
                        quality = self.quality.get(format, 85)
                        
                        if format == 'avif':
                            try:
                                resized.save(output_path, 'AVIF', quality=quality)
                                variants.append({
                                    'format': format,
                                    'width': width,
                                    'height': height,
                                    'path': output_filename,
                                    'size': output_path.stat().st_size
                                })
                            except Exception as e:
                                print(f"Warning: AVIF encoding failed: {e}")
                                continue
                        
                        elif format == 'webp':
                            resized.save(output_path, 'WEBP', quality=quality)
                            variants.append({
                                'format': format,
                                'width': width,
                                'height': height,
                                'path': output_filename,
                                'size': output_path.stat().st_size
                            })
                        
                        elif format == 'jpg':
                            resized.save(output_path, 'JPEG', quality=quality, optimize=True)
                            variants.append({
                                'format': format,
                                'width': width,
                                'height': height,
                                'path': output_filename,
                                'size': output_path.stat().st_size
                            })
        
        except Exception as e:
            print(f"Error processing image {image_path}: {e}")
        
        return variants
    
    def generate_picture_element(self, image_src: str, alt_text: str, variants: List[Dict[str, Any]]) -> str:
        """Generate HTML <picture> element with responsive images"""
        if not variants:
            return f'<img src="{image_src}" alt="{alt_text}" loading="lazy">'
        
        # Group by format
        by_format = {}
        for variant in variants:
            fmt = variant['format']
            if fmt not in by_format:
                by_format[fmt] = []
            by_format[fmt].append(variant)
        
        # Build <picture> element
        html = ['<picture>']
        
        # Add source elements for each format (AVIF first, then WebP)
        for fmt in ['avif', 'webp']:
            if fmt in by_format:
                sources = by_format[fmt]
                srcset = ', '.join([f"/assets/images/{v['path']} {v['width']}w" for v in sources])
                html.append(f'  <source type="image/{fmt}" srcset="{srcset}">')
        
        # Fallback img
        fallback_variant = variants[-1] if variants else None
        if fallback_variant:
            fallback_src = f"/assets/images/{fallback_variant['path']}"
        else:
            fallback_src = image_src
        
        html.append(f'  <img src="{fallback_src}" alt="{alt_text}" loading="lazy" decoding="async">')
        html.append('</picture>')
        
        return '\n'.join(html)
    
    def process_all_images(self, source_dir: Path, output_dir: Path) -> Dict[str, List[Dict]]:
        """Process all images in a directory"""
        output_dir.mkdir(parents=True, exist_ok=True)
        
        image_map = {}
        stats = {
            'total_images': 0,
            'total_variants': 0,
            'original_size': 0,
            'optimized_size': 0,
            'savings_bytes': 0,
            'savings_percent': 0
        }
        
        image_extensions = ['.jpg', '.jpeg', '.png', '.webp']
        for ext in image_extensions:
            for image_path in source_dir.rglob(f'*{ext}'):
                original_size = image_path.stat().st_size
                stats['total_images'] += 1
                stats['original_size'] += original_size
                
                variants = self.generate_responsive_images(image_path, output_dir)
                image_map[str(image_path.relative_to(source_dir))] = variants
                
                # Calculate optimized sizes
                for variant in variants:
                    stats['total_variants'] += 1
                    stats['optimized_size'] += variant['size']
        
        if stats['original_size'] > 0:
            stats['savings_bytes'] = stats['original_size'] - stats['optimized_size']
            stats['savings_percent'] = (stats['savings_bytes'] / stats['original_size']) * 100
        
        return {'images': image_map, 'stats': stats}
    
    def analyze_markdown_images(self, md_content: str) -> Dict[str, Any]:
        """Analyze images in markdown content"""
        import re
        
        # Find all markdown images: ![alt](url)
        pattern = r'!\[([^\]]*)\]\(([^\)]+)\)'
        images = re.findall(pattern, md_content)
        
        analysis = {
            'total_images': len(images),
            'missing_alt': 0,
            'external_images': 0,
            'images': []
        }
        
        for alt_text, url in images:
            image_info = {
                'alt': alt_text,
                'url': url,
                'has_alt': bool(alt_text.strip()),
                'is_external': url.startswith('http://') or url.startswith('https://')
            }
            
            if not image_info['has_alt']:
                analysis['missing_alt'] += 1
            
            if image_info['is_external']:
                analysis['external_images'] += 1
            
            analysis['images'].append(image_info)
        
        return analysis
    
    def replace_images_in_markdown(self, md_content: str, image_map: Dict[str, List[Dict]]) -> str:
        """Replace markdown images with optimized <picture> elements"""
        import re
        
        # Find all markdown images
        pattern = r'!\[([^\]]*)\]\(([^\)]+)\)'
        
        def replace_image(match):
            alt_text = match.group(1)
            url = match.group(2)
            
            # Skip external images
            if url.startswith('http://') or url.startswith('https://'):
                return match.group(0)
            
            # Check if we have variants for this image
            # Extract filename from URL
            filename = url.split('/')[-1]
            
            if filename in image_map:
                # Generate <picture> element
                return self.generate_picture_element(url, alt_text, image_map[filename])
            
            return match.group(0)
        
        return re.sub(pattern, replace_image, md_content)

