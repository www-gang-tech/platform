"""
GANG Redirect Manager
Track slug changes and generate 301 redirects.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from urllib.parse import urlparse


class RedirectManager:
    """Manage 301 redirects for slug changes"""

    _SAFE_PATH = re.compile(r'^/[A-Za-z0-9._~!$&\'()*+,;=:@/\-]*$')
    
    def __init__(self, content_path: Path, dist_path: Path):
        self.content_path = content_path
        self.dist_path = dist_path
        self.redirects_file = content_path.parent / '.redirects.json'
        self.redirects = self._load_redirects()

    @classmethod
    def validate_redirect_path(cls, path: str, *, allow_external: bool = False) -> str:
        """Normalize and validate a redirect from/to value for _redirects safety."""
        if path is None:
            raise ValueError('Redirect path is required')
        value = str(path).strip()
        if not value:
            raise ValueError('Redirect path is required')
        if any(ch.isspace() for ch in value) or any(ord(ch) < 32 for ch in value):
            raise ValueError(f'Redirect path contains whitespace/control characters: {path!r}')
        if value.startswith(('http://', 'https://')):
            if not allow_external:
                raise ValueError(f'External redirect destinations are not allowed: {path}')
            parsed = urlparse(value)
            if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
                raise ValueError(f'Invalid external redirect URL: {path}')
            if any(ch.isspace() for ch in value) or '\n' in value or '\r' in value:
                raise ValueError(f'Invalid external redirect URL: {path}')
            return value
        if not value.startswith('/'):
            raise ValueError(f'Redirect path must start with /: {path}')
        if value.startswith('//'):
            raise ValueError(f'Redirect path must not be protocol-relative: {path}')
        if not cls._SAFE_PATH.fullmatch(value):
            raise ValueError(f'Invalid redirect path: {path}')
        # Collapse accidental duplicate slashes but keep a single leading slash.
        normalized = '/' + '/'.join(part for part in value.split('/') if part)
        if value.endswith('/') and normalized != '/':
            normalized += '/'
        return normalized
    
    def _load_redirects(self) -> Dict[str, Any]:
        """Load existing redirects"""
        if self.redirects_file.exists():
            try:
                with open(self.redirects_file) as f:
                    return json.load(f)
            except:
                pass
        
        return {'redirects': [], 'version': '1.0'}
    
    def _save_redirects(self):
        """Save redirects to file"""
        with open(self.redirects_file, 'w') as f:
            json.dump(self.redirects, f, indent=2)
    
    def add_redirect(
        self, 
        old_path: str, 
        new_path: str, 
        reason: str = 'slug_change',
        permanent: bool = True
    ) -> Dict[str, Any]:
        """Add a new redirect"""
        old_path = self.validate_redirect_path(old_path, allow_external=False)
        new_path = self.validate_redirect_path(new_path, allow_external=True)
        
        # Check if redirect already exists
        for redirect in self.redirects['redirects']:
            if redirect['from'] == old_path:
                # Update existing redirect
                redirect['to'] = new_path
                redirect['updated'] = datetime.now().isoformat()
                redirect['reason'] = reason
                self._save_redirects()
                return {'updated': True, 'redirect': redirect}
        
        # Create new redirect
        redirect = {
            'from': old_path,
            'to': new_path,
            'status': 301 if permanent else 302,
            'reason': reason,
            'created': datetime.now().isoformat()
        }
        
        self.redirects['redirects'].append(redirect)
        self._save_redirects()
        
        return {'created': True, 'redirect': redirect}
    
    def remove_redirect(self, old_path: str) -> bool:
        """Remove a redirect"""
        original_count = len(self.redirects['redirects'])
        self.redirects['redirects'] = [
            r for r in self.redirects['redirects'] 
            if r['from'] != old_path
        ]
        
        if len(self.redirects['redirects']) < original_count:
            self._save_redirects()
            return True
        
        return False
    
    def get_redirect(self, old_path: str) -> Optional[Dict[str, Any]]:
        """Get redirect for a path"""
        for redirect in self.redirects['redirects']:
            if redirect['from'] == old_path:
                return redirect
        return None
    
    def list_all_redirects(self) -> List[Dict[str, Any]]:
        """Get all redirects"""
        return self.redirects['redirects']
    
    def generate_cloudflare_redirects(self) -> str:
        """Generate _redirects file for Cloudflare Pages"""
        lines = []
        lines.append("# GANG Platform Redirects")
        lines.append("# Generated automatically - do not edit manually")
        lines.append(f"# Last updated: {datetime.now().isoformat()}")
        lines.append("")
        
        for redirect in self.redirects['redirects']:
            # Cloudflare Pages _redirects format:
            # /old-path /new-path 301
            status = redirect.get('status', 301)
            lines.append(f"{redirect['from']} {redirect['to']} {status}")
        
        return '\n'.join(lines)
    
    def generate_nginx_redirects(self) -> str:
        """Generate nginx redirect config"""
        lines = []
        lines.append("# GANG Platform Redirects")
        lines.append("# Add to your nginx config")
        lines.append("")
        
        for redirect in self.redirects['redirects']:
            status = redirect.get('status', 301)
            lines.append(f"rewrite ^{redirect['from']}$ {redirect['to']} permanent;")
        
        return '\n'.join(lines)
    
    def generate_netlify_redirects(self) -> str:
        """Generate _redirects file for Netlify"""
        lines = []
        
        for redirect in self.redirects['redirects']:
            status = redirect.get('status', 301)
            lines.append(f"{redirect['from']} {redirect['to']} {status}")
        
        return '\n'.join(lines)
    
    def write_redirects_file(self, format: str = 'cloudflare'):
        """Write redirects file to dist directory"""
        if format == 'cloudflare':
            content = self.generate_cloudflare_redirects()
            output_file = self.dist_path / '_redirects'
        elif format == 'nginx':
            content = self.generate_nginx_redirects()
            output_file = self.dist_path / 'nginx-redirects.conf'
        elif format == 'netlify':
            content = self.generate_netlify_redirects()
            output_file = self.dist_path / '_redirects'
        else:
            return
        
        output_file.write_text(content)
    
    def validate_redirect_chain(self) -> List[str]:
        """Check for redirect chains and loops"""
        issues = []
        
        # Build redirect map
        redirect_map = {r['from']: r['to'] for r in self.redirects['redirects']}
        
        # Check for chains
        for from_path, to_path in redirect_map.items():
            visited = {from_path}
            current = to_path
            chain_length = 1
            
            while current in redirect_map:
                if current in visited:
                    issues.append(f"Redirect loop detected: {' → '.join(visited)} → {current}")
                    break
                
                visited.add(current)
                current = redirect_map[current]
                chain_length += 1
                
                if chain_length > 1:
                    chain = ' → '.join(list(visited) + [current])
                    issues.append(f"Redirect chain ({chain_length} hops): {chain}")
                    break
        
        return issues

