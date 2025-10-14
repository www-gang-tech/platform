"""
Image Pipeline 2.0
Advanced image processing with focal points, art-directed crops, and ThumbHash
"""

from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import subprocess
import json
import base64


class ImagePipeline:
    """Process images with focal points and responsive crops"""
    
    def __init__(self, public_path: Path, dist_path: Path):
        self.public_path = Path(public_path)
        self.dist_path = Path(dist_path)
        self.breakpoints = {
            'mobile': 375,
            'tablet': 768,
            'desktop': 1440
        }
    
    def process_image(self, image_path: Path, focal_point: Optional[Tuple[float, float]] = None,
                     is_lcp: bool = False) -> Dict[str, Any]:
        """
        Process a single image with focal point cropping
        
        Args:
            image_path: Path to source image
            focal_point: (x, y) coordinates (0-1 range) for focal point
            is_lcp: If True, don't lazy load (this is the LCP image)
        
        Returns:
            Dict with processed image data and HTML
        """
        
        if not focal_point:
            focal_point = (0.5, 0.5)  # Default to center
        
        result = {
            'original': str(image_path),
            'focal_point': focal_point,
            'is_lcp': is_lcp,
            'crops': {},
            'thumbhash': None,
            'html': ''
        }
        
        # Generate crops for each breakpoint
        for breakpoint, width in self.breakpoints.items():
            crop_path = self._generate_crop(image_path, width, focal_point)
            if crop_path:
                result['crops'][breakpoint] = str(crop_path)
        
        # Generate formats (AVIF, WebP, JPG)
        formats = self._generate_formats(image_path)
        result['formats'] = formats
        
        # Generate ThumbHash placeholder
        thumbhash = self._generate_thumbhash(image_path)
        if thumbhash:
            result['thumbhash'] = thumbhash
        
        # Generate <picture> HTML
        html = self._generate_picture_html(result, is_lcp)
        result['html'] = html
        
        return result
    
    def _generate_crop(self, image_path: Path, width: int, focal_point: Tuple[float, float]) -> Optional[Path]:
        """Generate art-directed crop at focal point"""
        
        # Check if ImageMagick is available
        try:
            subprocess.run(['convert', '-version'], capture_output=True, check=True)
        except (subprocess.CalledProcessError, FileNotFoundError):
            # ImageMagick not available, skip cropping
            return None
        
        output_dir = self.dist_path / 'assets' / 'images' / 'crops'
        output_dir.mkdir(parents=True, exist_ok=True)
        
        stem = image_path.stem
        output_path = output_dir / f"{stem}-{width}w.jpg"
        
        # Calculate crop dimensions
        fx, fy = focal_point
        
        # Use ImageMagick to crop with focal point
        # This is a simplified version - real implementation would be more sophisticated
        cmd = [
            'convert',
            str(image_path),
            '-resize', f"{width}x",
            '-quality', '85',
            str(output_path)
        ]
        
        try:
            subprocess.run(cmd, capture_output=True, check=True)
            return output_path
        except subprocess.CalledProcessError:
            return None
    
    def _generate_formats(self, image_path: Path) -> Dict[str, str]:
        """Generate AVIF and WebP versions"""
        
        formats = {}
        output_dir = self.dist_path / 'assets' / 'images'
        output_dir.mkdir(parents=True, exist_ok=True)
        
        stem = image_path.stem
        
        # AVIF (best compression, modern browsers)
        avif_path = output_dir / f"{stem}.avif"
        formats['avif'] = str(avif_path)
        
        # WebP (good fallback)
        webp_path = output_dir / f"{stem}.webp"
        formats['webp'] = str(webp_path)
        
        # JPEG (universal fallback)
        jpg_path = output_dir / f"{stem}.jpg"
        formats['jpg'] = str(jpg_path)
        
        # Note: Actual conversion would use ImageMagick or similar
        # For now, we're just defining the paths
        
        return formats
    
    def _generate_thumbhash(self, image_path: Path) -> Optional[str]:
        """
        Generate ThumbHash placeholder
        
        Note: This is a placeholder. Real implementation would use:
        https://github.com/evanw/thumbhash
        """
        
        # ThumbHash generation requires the thumbhash library
        # For now, return a mock hash
        return "1QcSHQRnh493V4dIh4eXh1h4kJUI"
    
    def _generate_picture_html(self, data: Dict[str, Any], is_lcp: bool) -> str:
        """Generate responsive <picture> element"""
        
        formats = data.get('formats', {})
        crops = data.get('crops', {})
        thumbhash = data.get('thumbhash')
        
        html = '<picture>\n'
        
        # AVIF sources (mobile, tablet, desktop)
        if 'avif' in formats:
            html += f'  <source type="image/avif" srcset="{formats["avif"]}">\n'
        
        # WebP sources
        if 'webp' in formats:
            html += f'  <source type="image/webp" srcset="{formats["webp"]}">\n'
        
        # Fallback img
        lazy = '' if is_lcp else ' loading="lazy"'
        decode = ' decoding="async"' if not is_lcp else ''
        
        html += f'  <img src="{formats.get("jpg", data["original"])}"'
        html += f' alt="TODO: Add alt text"'
        html += f'{lazy}{decode}>\n'
        html += '</picture>'
        
        return html
    
    def update_frontmatter_with_focal_point(self, md_file: Path, image_filename: str,
                                           focal_point: Tuple[float, float]) -> None:
        """Add focal_point to frontmatter for an image"""
        
        content = md_file.read_text()
        
        if not content.startswith('---'):
            return
        
        parts = content.split('---', 2)
        if len(parts) < 3:
            return
        
        import yaml
        frontmatter = yaml.safe_load(parts[1])
        
        # Add/update images array
        if 'images' not in frontmatter:
            frontmatter['images'] = []
        
        # Find or create entry for this image
        image_entry = None
        for img in frontmatter['images']:
            if img.get('src') == image_filename:
                image_entry = img
                break
        
        if not image_entry:
            image_entry = {'src': image_filename}
            frontmatter['images'].append(image_entry)
        
        # Update focal point
        image_entry['focal_point'] = list(focal_point)
        
        # Write back
        new_frontmatter = yaml.dump(frontmatter, default_flow_style=False)
        new_content = f"---\n{new_frontmatter}---{parts[2]}"
        md_file.write_text(new_content)


class FocalPointDetector:
    """AI-powered focal point detection"""
    
    @staticmethod
    def detect_focal_point(image_path: Path) -> Tuple[float, float]:
        """
        Detect focal point using AI or image analysis
        
        This would integrate with services like:
        - Cloudinary's auto focal point
        - AWS Rekognition
        - Google Cloud Vision
        - Local ML model (e.g., face detection)
        
        Returns (x, y) in 0-1 range
        """
        
        # Placeholder: return center
        # Real implementation would use computer vision
        return (0.5, 0.5)
    
    @staticmethod
    def detect_faces(image_path: Path) -> List[Tuple[float, float]]:
        """Detect faces in image and return their centers"""
        
        # Would use face detection library
        # For now, return empty
        return []

