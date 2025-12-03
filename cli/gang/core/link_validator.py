"""
GANG Link Validator
Validate internal and external links at build time.
"""

import re
import requests
from pathlib import Path
from typing import Dict, List, Tuple, Set, Any, Optional
from urllib.parse import urljoin, urlparse
import yaml
import os


class LinkValidator:
    """Validate links in markdown content"""
    
    def __init__(self, config: Dict[str, Any], content_path: Path, dist_path: Path):
        self.config = config
        self.content_path = content_path
        self.dist_path = dist_path
        self.site_url = config.get('site', {}).get('url', 'https://example.com')
        
        # Cache for external URLs to avoid duplicate checks
        self.external_cache: Dict[str, Tuple[bool, int, str]] = {}
        
        # Track all internal pages
        self.internal_pages: Set[str] = set()
        
    def scan_all_files(self) -> Dict[str, Any]:
        """Scan all markdown files and validate links"""
        md_files = list(self.content_path.rglob('*.md'))
        
        # Get git remotes to whitelist
        git_remotes = self.get_git_remotes()
        
        # First pass: collect all valid internal pages
        for md_file in md_files:
            url = self._get_page_url(md_file)
            if url:
                self.internal_pages.add(url)
                # Also add without trailing slash
                if url.endswith('/'):
                    self.internal_pages.add(url.rstrip('/'))
                else:
                    self.internal_pages.add(url + '/')
        
        # Second pass: validate all links
        results = {
            'total_files': 0,
            'total_links': 0,
            'internal_links': 0,
            'external_links': 0,
            'broken_internal': [],
            'broken_external': [],
            'redirects': [],
            'warnings': []
        }
        
        for md_file in sorted(md_files):
            file_result = self.validate_file(md_file, git_remotes)
            results['total_files'] += 1
            results['total_links'] += file_result['total_links']
            results['internal_links'] += file_result['internal_links']
            results['external_links'] += file_result['external_links']
            results['broken_internal'].extend(file_result['broken_internal'])
            results['broken_external'].extend(file_result['broken_external'])
            results['redirects'].extend(file_result['redirects'])
            results['warnings'].extend(file_result['warnings'])
        
        return results
    
    def get_git_remotes(self) -> List[str]:
        """Get git remote URLs to whitelist them"""
        try:
            import subprocess
            result = subprocess.run(
                ['git', 'remote', '-v'],
                capture_output=True,
                text=True,
                cwd=self.content_path.parent
            )
            if result.returncode == 0:
                # Extract URLs from output
                urls = []
                for line in result.stdout.split('\n'):
                    if '\t' in line:
                        parts = line.split('\t')
                        if len(parts) > 1:
                            url = parts[1].split()[0]
                            # Convert git URL to HTTPS
                            url = url.replace('.git', '')
                            if url.startswith('git@github.com:'):
                                url = url.replace('git@github.com:', 'https://github.com/')
                            urls.append(url)
                return list(set(urls))
        except:
            pass
        return []
    
    def validate_file(self, file_path: Path, git_remotes: List[str] = None) -> Dict[str, Any]:
        """Validate links in a single file"""
        if git_remotes is None:
            git_remotes = []
        content = file_path.read_text()
        
        # Parse frontmatter
        if content.startswith('---'):
            parts = content.split('---', 2)
            body = parts[2] if len(parts) > 2 else ''
        else:
            body = content
        
        result = {
            'file': str(file_path.relative_to(self.content_path)),
            'total_links': 0,
            'internal_links': 0,
            'external_links': 0,
            'broken_internal': [],
            'broken_external': [],
            'redirects': [],
            'warnings': []
        }
        
        # Extract all markdown links: [text](url)
        link_pattern = r'\[([^\]]+)\]\(([^\)]+)\)'
        links = re.findall(link_pattern, body)
        
        for link_text, url in links:
            result['total_links'] += 1
            
            # Skip anchors, mailto, tel, etc.
            if url.startswith('#') or url.startswith('mailto:') or url.startswith('tel:'):
                continue
            
            # Check if external or internal
            if url.startswith('http://') or url.startswith('https://'):
                result['external_links'] += 1
                
                # Check if this is a git remote (whitelist it)
                is_git_remote = any(url.startswith(remote) for remote in git_remotes)
                
                status = self._check_external_link(url)
                
                if status['broken']:
                    # If it's a git remote returning 404, it's likely private - warn instead of error
                    if is_git_remote and status['status_code'] == 404:
                        result['warnings'].append({
                            'file': result['file'],
                            'type': 'private_repo',
                            'url': url,
                            'message': 'Git remote URL (may be private or not yet pushed)'
                        })
                    else:
                        result['broken_external'].append({
                            'file': result['file'],
                            'link_text': link_text,
                            'url': url,
                            'status_code': status['status_code'],
                            'error': status['error']
                        })
                elif status['redirect']:
                    result['redirects'].append({
                        'file': result['file'],
                        'url': url,
                        'redirect_to': status['redirect_to'],
                        'status_code': status['status_code']
                    })
            else:
                result['internal_links'] += 1
                if not self._check_internal_link(url):
                    result['broken_internal'].append({
                        'file': result['file'],
                        'link_text': link_text,
                        'url': url
                    })
        
        # Check for image links
        image_pattern = r'!\[([^\]]*)\]\(([^\)]+)\)'
        images = re.findall(image_pattern, body)
        
        for alt_text, url in images:
            if url.startswith('http://') or url.startswith('https://'):
                # External image
                result['warnings'].append({
                    'file': result['file'],
                    'type': 'external_image',
                    'url': url,
                    'message': 'External image (consider hosting locally)'
                })
        
        return result
    
    def _get_page_url(self, md_file: Path) -> str:
        """Get the URL for a markdown file"""
        rel_path = md_file.relative_to(self.content_path)
        parts = rel_path.parts
        
        if len(parts) < 2:
            return None
        
        content_type = parts[0]  # posts, pages, projects, etc.
        slug = rel_path.stem
        
        if content_type in ['posts', 'projects', 'people']:
            return f'/{content_type}/{slug}/'
        elif content_type == 'pages':
            return f'/pages/{slug}/'
        
        return None
    
    def _check_internal_link(self, url: str) -> bool:
        """Check if an internal link is valid"""
        # Clean up the URL
        url = url.split('#')[0]  # Remove anchor
        url = url.split('?')[0]  # Remove query string
        
        # Check if it's in our list of valid pages
        if url in self.internal_pages:
            return True
        
        # Check if it's a static file
        if not url.startswith('/'):
            return True  # Relative links are assumed valid
        
        # Check if file exists in dist (for assets)
        if self.dist_path.exists():
            file_path = self.dist_path / url.lstrip('/')
            if file_path.exists():
                return True
            
            # Check with index.html
            if not url.endswith('/'):
                index_path = self.dist_path / url.lstrip('/') / 'index.html'
                if index_path.exists():
                    return True
        
        return False
    
    def _check_external_link(self, url: str) -> Dict[str, Any]:
        """Check if an external link is valid"""
        # Check cache first
        if url in self.external_cache:
            status, code, redirect = self.external_cache[url]
            return {
                'broken': not status,
                'status_code': code,
                'redirect': bool(redirect),
                'redirect_to': redirect,
                'error': None if status else f'HTTP {code}'
            }
        
        try:
            # Try HEAD first for efficiency, but fallback to GET for sites that block HEAD
            try:
                response = requests.head(
                    url,
                    timeout=10,
                    allow_redirects=False,
                    headers={'User-Agent': 'Mozilla/5.0 (compatible; GANG-LinkValidator/1.0)'}
                )
                status_code = response.status_code
                
                # If HEAD returns 405 (Method Not Allowed), retry with GET
                if status_code == 405:
                    raise requests.exceptions.RequestException("HEAD not allowed, trying GET")
                    
            except (requests.exceptions.RequestException, requests.exceptions.ConnectionError):
                # Fallback to GET request (some sites like GitHub block HEAD)
                response = requests.get(
                    url,
                    timeout=10,
                    allow_redirects=False,
                    headers={'User-Agent': 'Mozilla/5.0 (compatible; GANG-LinkValidator/1.0)'},
                    stream=True  # Don't download full body
                )
                status_code = response.status_code
                response.close()  # Close connection immediately
            
            # 2xx = success
            if 200 <= status_code < 300:
                self.external_cache[url] = (True, status_code, None)
                return {
                    'broken': False,
                    'status_code': status_code,
                    'redirect': False,
                    'redirect_to': None,
                    'error': None
                }
            
            # 3xx = redirect
            elif 300 <= status_code < 400:
                redirect_to = response.headers.get('Location', 'Unknown')
                self.external_cache[url] = (True, status_code, redirect_to)
                return {
                    'broken': False,
                    'status_code': status_code,
                    'redirect': True,
                    'redirect_to': redirect_to,
                    'error': None
                }
            
            # 4xx, 5xx = broken
            else:
                self.external_cache[url] = (False, status_code, None)
                return {
                    'broken': True,
                    'status_code': status_code,
                    'redirect': False,
                    'redirect_to': None,
                    'error': f'HTTP {status_code}'
                }
        
        except requests.exceptions.Timeout:
            self.external_cache[url] = (False, 0, None)
            return {
                'broken': True,
                'status_code': 0,
                'redirect': False,
                'redirect_to': None,
                'error': 'Timeout'
            }
        
        except requests.exceptions.RequestException as e:
            error_msg = str(e)
            self.external_cache[url] = (False, 0, None)
            return {
                'broken': True,
                'status_code': 0,
                'redirect': False,
                'redirect_to': None,
                'error': error_msg[:100]  # Truncate long errors
            }
    
    def format_report(self, results: Dict[str, Any]) -> str:
        """Format validation results as readable report"""
        report = []
        
        report.append("=" * 60)
        report.append("🔗 Link Validation Report")
        report.append("=" * 60)
        report.append("")
        
        # Summary
        report.append("📊 SUMMARY")
        report.append(f"├─ Files scanned: {results['total_files']}")
        report.append(f"├─ Total links: {results['total_links']}")
        report.append(f"├─ Internal links: {results['internal_links']}")
        report.append(f"└─ External links: {results['external_links']}")
        report.append("")
        
        # Internal links
        broken_internal = results['broken_internal']
        if broken_internal:
            report.append(f"❌ BROKEN INTERNAL LINKS: {len(broken_internal)}")
            for item in broken_internal[:10]:  # Show first 10
                report.append(f"  {item['file']}")
                report.append(f"  └─ [{item['link_text']}]({item['url']})")
            if len(broken_internal) > 10:
                report.append(f"  ... and {len(broken_internal) - 10} more")
            report.append("")
        else:
            report.append("✓ Internal links: All valid")
            report.append("")
        
        # External links
        broken_external = results['broken_external']
        if broken_external:
            report.append(f"❌ BROKEN EXTERNAL LINKS: {len(broken_external)}")
            for item in broken_external[:10]:
                report.append(f"  {item['file']}")
                report.append(f"  └─ {item['url']} → {item['error']}")
            if len(broken_external) > 10:
                report.append(f"  ... and {len(broken_external) - 10} more")
            report.append("")
        else:
            report.append("✓ External links: All valid")
            report.append("")
        
        # Redirects
        redirects = results['redirects']
        if redirects:
            report.append(f"⚠️  REDIRECTS: {len(redirects)}")
            for item in redirects[:5]:
                report.append(f"  {item['file']}")
                report.append(f"  └─ {item['url']} → {item['status_code']}")
                report.append(f"     Redirects to: {item['redirect_to']}")
            if len(redirects) > 5:
                report.append(f"  ... and {len(redirects) - 5} more")
            report.append("")
        
        # Warnings
        warnings = results['warnings']
        if warnings:
            report.append(f"⚠️  WARNINGS: {len(warnings)}")
            for item in warnings[:5]:
                report.append(f"  {item['file']}: {item['message']}")
            if len(warnings) > 5:
                report.append(f"  ... and {len(warnings) - 5} more")
            report.append("")
        
        # Overall status
        report.append("=" * 60)
        if broken_internal or broken_external:
            report.append("Overall Status: FAILED ❌")
            report.append(f"Total broken links: {len(broken_internal) + len(broken_external)}")
        else:
            report.append("Overall Status: PASSED ✓")
        report.append("=" * 60)
        
        return '\n'.join(report)
    
    def suggest_fixes_with_ai(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Use AI to suggest fixes for broken links"""
        try:
            from anthropic import Anthropic
        except ImportError:
            return {'error': 'Anthropic library not installed'}
        
        api_key = os.environ.get('ANTHROPIC_API_KEY')
        if not api_key:
            return {'error': 'ANTHROPIC_API_KEY not set'}
        
        client = Anthropic(api_key=api_key)
        suggestions = {
            'internal': [],
            'external': [],
            'redirects': []
        }
        
        # Get all valid internal pages for context
        valid_pages = list(self.internal_pages)
        
        # Suggest fixes for broken internal links
        for item in results['broken_internal']:
            broken_url = item['url']
            file = item['file']
            link_text = item['link_text']
            
            # Use AI to find best match
            suggestion = self._ai_suggest_internal_link(
                client, broken_url, link_text, valid_pages
            )
            
            suggestions['internal'].append({
                'file': file,
                'broken_url': broken_url,
                'link_text': link_text,
                'suggested_url': suggestion.get('url'),
                'confidence': suggestion.get('confidence'),
                'reasoning': suggestion.get('reasoning')
            })
        
        # Suggest fixes for broken external links
        for item in results['broken_external']:
            broken_url = item['url']
            file = item['file']
            error = item['error']
            
            suggestion = self._ai_suggest_external_link(
                client, broken_url, error
            )
            
            suggestions['external'].append({
                'file': file,
                'broken_url': broken_url,
                'error': error,
                'suggested_url': suggestion.get('url'),
                'suggested_action': suggestion.get('action'),
                'reasoning': suggestion.get('reasoning')
            })
        
        # Suggest updating redirects
        for item in results['redirects']:
            suggestions['redirects'].append({
                'file': item['file'],
                'current_url': item['url'],
                'redirect_to': item['redirect_to'],
                'suggested_action': 'update',
                'reasoning': f"Update link to final destination to avoid redirect ({item['status_code']})"
            })
        
        return suggestions
    
    def _ai_suggest_internal_link(
        self, 
        client, 
        broken_url: str, 
        link_text: str, 
        valid_pages: List[str]
    ) -> Dict[str, Any]:
        """Use AI to suggest the most likely correct internal link"""
        
        prompt = f"""You are helping fix a broken internal link in a website.

Broken link: {broken_url}
Link text: "{link_text}"

Available valid pages on the site:
{chr(10).join(f'  - {page}' for page in valid_pages[:50])}

Your task:
1. Find the CLOSEST matching page from the available pages, even if not perfect
2. Use fuzzy matching on the URL path (e.g., /docs → /pages/documentation, /doc → /pages/docs)
3. Consider the link text meaning
4. Always suggest the BEST available match, even if imperfect

Respond in JSON format:
{{
  "url": "/best/available/match/",
  "confidence": "high|medium|low",
  "reasoning": "Why this is the closest match",
  "action": "update"
}}

Only suggest null if there are truly NO pages on the site that could relate:
{{
  "url": null,
  "confidence": "low",
  "reasoning": "No related pages found",
  "action": "create_or_remove"
}}

IMPORTANT: Always try to find the closest semantic or URL match first!"""
        
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )
            
            import json
            suggestion_text = response.content[0].text.strip()
            
            # Extract JSON from response
            if '```json' in suggestion_text:
                suggestion_text = suggestion_text.split('```json')[1].split('```')[0].strip()
            elif '```' in suggestion_text:
                suggestion_text = suggestion_text.split('```')[1].split('```')[0].strip()
            
            suggestion = json.loads(suggestion_text)
            return suggestion
            
        except Exception as e:
            return {
                'url': None,
                'confidence': 'low',
                'reasoning': f'AI suggestion failed: {str(e)[:100]}'
            }
    
    def _ai_suggest_external_link(
        self, 
        client, 
        broken_url: str, 
        error: str
    ) -> Dict[str, Any]:
        """Use AI to suggest fix for broken external link"""
        
        prompt = f"""You are helping fix a broken external link in a website.

Broken URL: {broken_url}
Error: {error}

Suggest the best action to fix this broken link.

Respond in JSON format:
{{
  "url": "suggested replacement URL or null",
  "action": "replace|remove|archive|manual_check",
  "reasoning": "Brief explanation of the suggested action"
}}

Actions:
- replace: Suggest an alternative working URL
- remove: Link is outdated, should be removed
- archive: Use Web Archive version (https://web.archive.org/web/...)
- manual_check: Needs human review (temporary issue, typo, etc.)"""
        
        try:
            response = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )
            
            import json
            suggestion_text = response.content[0].text.strip()
            
            # Extract JSON from response
            if '```json' in suggestion_text:
                suggestion_text = suggestion_text.split('```json')[1].split('```')[0].strip()
            elif '```' in suggestion_text:
                suggestion_text = suggestion_text.split('```')[1].split('```')[0].strip()
            
            suggestion = json.loads(suggestion_text)
            return suggestion
            
        except Exception as e:
            return {
                'url': None,
                'action': 'manual_check',
                'reasoning': f'AI suggestion failed: {str(e)[:100]}'
            }
    
    def format_suggestions_report(self, suggestions: Dict[str, Any]) -> str:
        """Format AI suggestions as readable report"""
        report = []
        
        report.append("=" * 60)
        report.append("🤖 AI-Powered Link Fix Suggestions")
        report.append("=" * 60)
        report.append("")
        
        # Internal link suggestions
        if suggestions['internal']:
            report.append(f"📝 INTERNAL LINK FIXES ({len(suggestions['internal'])})")
            report.append("")
            for item in suggestions['internal']:
                report.append(f"File: {item['file']}")
                report.append(f"  Broken: {item['broken_url']}")
                if item['suggested_url']:
                    report.append(f"  ✨ Suggested: {item['suggested_url']} ({item['confidence']} confidence)")
                    report.append(f"  💡 {item['reasoning']}")
                else:
                    report.append(f"  ⚠️  {item['reasoning']}")
                report.append("")
        
        # External link suggestions
        if suggestions['external']:
            report.append(f"🌐 EXTERNAL LINK FIXES ({len(suggestions['external'])})")
            report.append("")
            for item in suggestions['external']:
                report.append(f"File: {item['file']}")
                report.append(f"  Broken: {item['broken_url']}")
                report.append(f"  Error: {item['error']}")
                report.append(f"  ✨ Action: {item['suggested_action'].upper()}")
                if item['suggested_url']:
                    report.append(f"  Suggested URL: {item['suggested_url']}")
                report.append(f"  💡 {item['reasoning']}")
                report.append("")
        
        # Redirect suggestions
        if suggestions['redirects']:
            report.append(f"↪️  REDIRECT FIXES ({len(suggestions['redirects'])})")
            report.append("")
            for item in suggestions['redirects']:
                report.append(f"File: {item['file']}")
                report.append(f"  Current: {item['current_url']}")
                report.append(f"  ✨ Update to: {item['redirect_to']}")
                report.append(f"  💡 {item['reasoning']}")
                report.append("")
        
        report.append("=" * 60)
        report.append("💡 TIP: Review suggestions and apply manually")
        report.append("    Future: 'gang fix --links' to auto-apply")
        report.append("=" * 60)
        
        return '\n'.join(report)

