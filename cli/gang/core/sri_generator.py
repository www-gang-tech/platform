"""
Subresource Integrity (SRI) Generator
Generates SRI hashes for CSS and JavaScript files
"""

from pathlib import Path
import hashlib
import base64
from typing import Dict, List


class SRIGenerator:
    """Generate SRI hashes for static assets"""
    
    @staticmethod
    def generate_hash(file_path: Path, algorithm='sha384') -> str:
        """
        Generate SRI hash for a file
        
        Args:
            file_path: Path to the file
            algorithm: Hash algorithm (sha256, sha384, sha512)
        
        Returns:
            SRI hash string (e.g., 'sha384-xxx...')
        """
        content = file_path.read_bytes()
        
        if algorithm == 'sha256':
            hash_obj = hashlib.sha256(content)
        elif algorithm == 'sha384':
            hash_obj = hashlib.sha384(content)
        elif algorithm == 'sha512':
            hash_obj = hashlib.sha512(content)
        else:
            raise ValueError(f"Unsupported algorithm: {algorithm}")
        
        hash_b64 = base64.b64encode(hash_obj.digest()).decode('utf-8')
        
        return f"{algorithm}-{hash_b64}"
    
    @staticmethod
    def generate_for_directory(dist_path: Path) -> Dict[str, str]:
        """
        Generate SRI hashes for all CSS and JS files in dist
        
        Returns:
            Dict mapping file paths to SRI hashes
        """
        sri_map = {}
        
        assets_path = dist_path / 'assets'
        if not assets_path.exists():
            return sri_map
        
        # Process CSS files
        for css_file in assets_path.glob('*.css'):
            sri_hash = SRIGenerator.generate_hash(css_file)
            relative_path = f"/assets/{css_file.name}"
            sri_map[relative_path] = sri_hash
        
        # Process JS files
        for js_file in assets_path.glob('*.js'):
            sri_hash = SRIGenerator.generate_hash(js_file)
            relative_path = f"/assets/{js_file.name}"
            sri_map[relative_path] = sri_hash
        
        return sri_map
    
    @staticmethod
    def inject_sri_into_html(html: str, sri_map: Dict[str, str]) -> str:
        """Inject SRI hashes into HTML link and script tags"""
        import re
        
        # Inject SRI into CSS links
        for path, sri_hash in sri_map.items():
            if path.endswith('.css'):
                # Find <link href="/assets/style.css" and add integrity attribute
                pattern = f'<link([^>]*?)href="{path}"([^>]*?)>'
                replacement = f'<link\\1href="{path}"\\2 integrity="{sri_hash}" crossorigin="anonymous">'
                html = re.sub(pattern, replacement, html)
        
        # Inject SRI into JS scripts
        for path, sri_hash in sri_map.items():
            if path.endswith('.js'):
                # Find <script src="/assets/cart.js" and add integrity attribute
                pattern = f'<script([^>]*?)src="{path}"([^>]*?)>'
                replacement = f'<script\\1src="{path}"\\2 integrity="{sri_hash}" crossorigin="anonymous">'
                html = re.sub(pattern, replacement, html)
        
        return html
    
    @staticmethod
    def generate_csp_with_sri(sri_map: Dict[str, str]) -> str:
        """
        Generate CSP header with SRI hashes
        
        Instead of 'unsafe-inline', use SRI hashes for allowed scripts/styles
        """
        script_hashes = [hash_val for path, hash_val in sri_map.items() if path.endswith('.js')]
        style_hashes = [hash_val for path, hash_val in sri_map.items() if path.endswith('.css')]
        
        script_src = "'self' " + ' '.join(f"'{h}'" for h in script_hashes) if script_hashes else "'self'"
        style_src = "'self' " + ' '.join(f"'{h}'" for h in style_hashes) if style_hashes else "'self'"
        
        csp = f"default-src 'self'; script-src {script_src}; style-src {style_src}; img-src 'self' https: data:; font-src 'self'; connect-src 'self'; base-uri 'self'; form-action 'self' https:; frame-ancestors 'none'"
        
        return csp

