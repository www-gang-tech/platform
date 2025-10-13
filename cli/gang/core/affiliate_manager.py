"""
GANG Affiliate Link Manager
Track and manage affiliate links across content.
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
import re
import json
from datetime import datetime


class AffiliateLinkManager:
    """Manage affiliate links and tracking"""
    
    # Known affiliate platforms
    PLATFORMS = {
        'amazon': r'amazon\.com.*?tag=[\w-]+',
        'gumroad': r'gumroad\.com',
        'stripe': r'buy\.stripe\.com',
        'lemonsqueezy': r'lemonsqueezy\.com',
        'paddle': r'paddle\.com',
        'convertkit': r'convertkit\.com',
        'teachable': r'teachable\.com'
    }
    
    def __init__(self, content_path: Path):
        self.content_path = content_path
        self.links_db_file = content_path.parent / '.affiliate-links.json'
        self.links_db = self._load_links_db()
    
    def _load_links_db(self) -> Dict[str, Any]:
        """Load affiliate links database"""
        if self.links_db_file.exists():
            try:
                return json.loads(self.links_db_file.read_text())
            except:
                pass
        
        return {
            'links': [],
            'updated': datetime.now().isoformat()
        }
    
    def _save_links_db(self):
        """Save affiliate links database"""
        self.links_db['updated'] = datetime.now().isoformat()
        self.links_db_file.write_text(json.dumps(self.links_db, indent=2))
    
    def scan_content(self, file_path: Path) -> List[Dict[str, Any]]:
        """Scan content for affiliate links"""
        
        content = file_path.read_text()
        found_links = []
        
        # Extract all URLs from markdown links
        link_pattern = r'\[([^\]]+)\]\(([^\)]+)\)'
        
        for match in re.finditer(link_pattern, content):
            link_text = match.group(1)
            url = match.group(2)
            
            # Check if it's an affiliate link
            platform = self._identify_platform(url)
            
            if platform:
                found_links.append({
                    'url': url,
                    'text': link_text,
                    'platform': platform,
                    'file': str(file_path.relative_to(self.content_path)),
                    'position': match.start()
                })
        
        return found_links
    
    def _identify_platform(self, url: str) -> Optional[str]:
        """Identify affiliate platform from URL"""
        for platform, pattern in self.PLATFORMS.items():
            if re.search(pattern, url, re.IGNORECASE):
                return platform
        return None
    
    def scan_all_content(self) -> Dict[str, Any]:
        """Scan all content files for affiliate links"""
        
        all_links = []
        
        for md_file in self.content_path.rglob('*.md'):
            try:
                links = self.scan_content(md_file)
                all_links.extend(links)
            except:
                continue
        
        # Group by platform
        by_platform = {}
        for link in all_links:
            platform = link['platform']
            if platform not in by_platform:
                by_platform[platform] = []
            by_platform[platform].append(link)
        
        # Update database
        self.links_db['links'] = all_links
        self.links_db['by_platform'] = by_platform
        self.links_db['total_links'] = len(all_links)
        self.links_db['platforms'] = list(by_platform.keys())
        self._save_links_db()
        
        return {
            'total_links': len(all_links),
            'platforms': list(by_platform.keys()),
            'by_platform': {
                platform: len(links)
                for platform, links in by_platform.items()
            },
            'details': all_links
        }
    
    def add_tracking_params(
        self,
        url: str,
        params: Dict[str, str]
    ) -> str:
        """Add tracking parameters to URL"""
        
        if '?' in url:
            separator = '&'
        else:
            separator = '?'
        
        param_str = '&'.join([f"{k}={v}" for k, v in params.items()])
        
        return f"{url}{separator}{param_str}"
    
    def validate_affiliate_urls(self) -> List[Dict[str, Any]]:
        """Validate all affiliate URLs are properly formatted"""
        
        issues = []
        
        for link in self.links_db.get('links', []):
            url = link['url']
            platform = link['platform']
            
            # Amazon: Check for tag parameter
            if platform == 'amazon' and 'tag=' not in url:
                issues.append({
                    'link': link,
                    'issue': 'Missing Amazon affiliate tag',
                    'fix': 'Add ?tag=your-tag-20 to URL'
                })
            
            # Check for tracking params
            if '?' not in url and platform in ['amazon', 'gumroad']:
                issues.append({
                    'link': link,
                    'issue': 'Missing tracking parameters',
                    'fix': 'Add UTM parameters for analytics'
                })
        
        return issues
    
    def generate_disclosure(self, platform: str = None) -> str:
        """Generate affiliate disclosure text"""
        
        if platform:
            return f"This post contains affiliate links to {platform.title()}. We may earn a commission if you make a purchase through these links at no additional cost to you."
        else:
            return "This post contains affiliate links. We may earn a commission if you make a purchase through these links at no additional cost to you."


class PerformanceBudgetReporter:
    """Track and enforce performance budgets"""
    
    BUDGETS = {
        'html': 30 * 1024,      # 30KB
        'css': 10 * 1024,       # 10KB
        'js': 0,                # Zero JS on content pages
        'images': 200 * 1024,   # 200KB total images per page
        'total': 300 * 1024     # 300KB total page weight
    }
    
    def __init__(self, dist_path: Path):
        self.dist_path = dist_path
        self.history_file = dist_path.parent / '.budget-history.json'
        self.history = self._load_history()
    
    def _load_history(self) -> Dict[str, Any]:
        """Load budget history"""
        if self.history_file.exists():
            try:
                return json.loads(self.history_file.read_text())
            except:
                pass
        
        return {'builds': []}
    
    def _save_history(self):
        """Save budget history"""
        self.history_file.write_text(json.dumps(self.history, indent=2))
    
    def analyze_page(self, page_path: Path) -> Dict[str, Any]:
        """Analyze a single page against budgets"""
        
        html_size = page_path.stat().st_size if page_path.exists() else 0
        
        # Extract linked assets
        content = page_path.read_text() if page_path.exists() else ''
        
        css_size = 0
        js_size = 0
        images_size = 0
        
        # Find CSS files
        css_links = re.findall(r'<link[^>]+href=["\']([^"\']+\.css)["\']', content)
        for css_link in css_links:
            css_file = self.dist_path / css_link.lstrip('/')
            if css_file.exists():
                css_size += css_file.stat().st_size
        
        # Check for inline CSS
        inline_css = re.findall(r'<style>([\s\S]*?)</style>', content)
        for css in inline_css:
            css_size += len(css.encode())
        
        # Find JS files
        js_links = re.findall(r'<script[^>]+src=["\']([^"\']+\.js)["\']', content)
        for js_link in js_links:
            js_file = self.dist_path / js_link.lstrip('/')
            if js_file.exists():
                js_size += js_file.stat().st_size
        
        # Check for inline JS
        inline_js = re.findall(r'<script(?![^>]*src=)[^>]*>([\s\S]*?)</script>', content)
        for js in inline_js:
            js_size += len(js.encode())
        
        # Find images
        img_links = re.findall(r'<img[^>]+src=["\']([^"\']+)["\']', content)
        for img_link in img_links:
            if not img_link.startswith('http'):
                img_file = self.dist_path / img_link.lstrip('/')
                if img_file.exists():
                    images_size += img_file.stat().st_size
        
        total_size = html_size + css_size + js_size + images_size
        
        # Check against budgets
        violations = []
        
        if html_size > self.BUDGETS['html']:
            violations.append({
                'type': 'html',
                'size': html_size,
                'budget': self.BUDGETS['html'],
                'overage': html_size - self.BUDGETS['html']
            })
        
        if css_size > self.BUDGETS['css']:
            violations.append({
                'type': 'css',
                'size': css_size,
                'budget': self.BUDGETS['css'],
                'overage': css_size - self.BUDGETS['css']
            })
        
        if js_size > self.BUDGETS['js']:
            violations.append({
                'type': 'js',
                'size': js_size,
                'budget': self.BUDGETS['js'],
                'overage': js_size - self.BUDGETS['js']
            })
        
        if total_size > self.BUDGETS['total']:
            violations.append({
                'type': 'total',
                'size': total_size,
                'budget': self.BUDGETS['total'],
                'overage': total_size - self.BUDGETS['total']
            })
        
        return {
            'page': str(page_path.relative_to(self.dist_path)),
            'sizes': {
                'html': html_size,
                'css': css_size,
                'js': js_size,
                'images': images_size,
                'total': total_size
            },
            'budgets': self.BUDGETS,
            'violations': violations,
            'passes': len(violations) == 0
        }
    
    def analyze_all_pages(self) -> Dict[str, Any]:
        """Analyze all HTML pages"""
        
        results = []
        total_violations = 0
        
        for html_file in self.dist_path.rglob('*.html'):
            try:
                analysis = self.analyze_page(html_file)
                results.append(analysis)
                if not analysis['passes']:
                    total_violations += len(analysis['violations'])
            except:
                continue
        
        # Record in history
        self.history['builds'].append({
            'timestamp': datetime.now().isoformat(),
            'total_pages': len(results),
            'passing_pages': sum(1 for r in results if r['passes']),
            'violations': total_violations
        })
        self._save_history()
        
        return {
            'total_pages': len(results),
            'passing': sum(1 for r in results if r['passes']),
            'failing': sum(1 for r in results if not r['passes']),
            'total_violations': total_violations,
            'details': results
        }
    
    def format_budget_report(self, analysis: Dict[str, Any]) -> str:
        """Format budget analysis as readable report"""
        
        lines = []
        lines.append("📊 Performance Budget Report")
        lines.append("=" * 60)
        lines.append(f"Total pages: {analysis['total_pages']}")
        lines.append(f"✅ Passing: {analysis['passing']}")
        lines.append(f"❌ Failing: {analysis['failing']}")
        lines.append("")
        
        if analysis['failing'] > 0:
            lines.append("Budget Violations:")
            lines.append("-" * 60)
            
            for page in analysis['details']:
                if not page['passes']:
                    lines.append(f"\n{page['page']}:")
                    for v in page['violations']:
                        size_kb = v['size'] / 1024
                        budget_kb = v['budget'] / 1024
                        overage_kb = v['overage'] / 1024
                        lines.append(f"  ❌ {v['type'].upper()}: {size_kb:.1f}KB / {budget_kb:.1f}KB (over by {overage_kb:.1f}KB)")
        
        return '\n'.join(lines)

