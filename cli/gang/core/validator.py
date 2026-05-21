"""
GANG Contract Validator
Enforces Template Contracts: semantics, a11y, budgets, JSON-LD
"""

from bs4 import BeautifulSoup
import json
import re
from typing import List, Dict, Any
from pathlib import Path

class ContractValidator:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.contracts = config.get('contracts', {})
        self.budgets = config.get('budgets', {})

    def _rule_names(self, section: str) -> List[str]:
        """Return configured rule names without assuming every dict is non-empty."""
        names = []
        for item in self.contracts.get(section, []):
            if isinstance(item, str):
                names.append(item)
            elif isinstance(item, dict):
                names.extend(item.keys())
        return names
    
    def check_semantic(self, html: str) -> List[Dict]:
        """Check semantic HTML structure"""
        issues = []
        soup = BeautifulSoup(html, 'html.parser')
        
        # Check single H1
        if 'single_h1' in self.contracts.get('semantic', []):
            h1_tags = soup.find_all('h1')
            if len(h1_tags) != 1:
                issues.append({
                    'severity': 'error',
                    'rule': 'single_h1',
                    'message': f'Found {len(h1_tags)} <h1> elements. Exactly one H1 required.',
                })
        
        # Check no heading skips
        if 'no_heading_skips' in self.contracts.get('semantic', []):
            headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
            prev_level = 0
            for heading in headings:
                level = int(heading.name[1])
                if level - prev_level > 1:
                    issues.append({
                        'severity': 'error',
                        'rule': 'no_heading_skips',
                        'message': f'Heading level skip detected: <{heading.name}> after <h{prev_level}>',
                    })
                prev_level = level
        
        # Check required landmarks
        required_landmarks = None
        for item in self.contracts.get('semantic', []):
            if isinstance(item, dict) and 'required_landmarks' in item:
                required_landmarks = item['required_landmarks']
                break
        
        if required_landmarks:
            for landmark in required_landmarks:
                if not soup.find(landmark):
                    issues.append({
                        'severity': 'error',
                        'rule': 'required_landmarks',
                        'message': f'Required landmark <{landmark}> not found',
                    })
        
        return issues
    
    def check_accessibility(self, html: str) -> List[Dict]:
        """Check accessibility compliance"""
        issues = []
        soup = BeautifulSoup(html, 'html.parser')
        
        # Check alt text coverage
        alt_coverage = None
        for item in self.contracts.get('accessibility', []):
            if isinstance(item, dict) and 'alt_coverage' in item:
                alt_coverage = item['alt_coverage']
                break
        
        if alt_coverage:
            images = soup.find_all('img')
            if images:
                images_with_alt = [img for img in images if img.get('alt') is not None]
                coverage = (len(images_with_alt) / len(images)) * 100
                if coverage < alt_coverage:
                    issues.append({
                        'severity': 'error',
                        'rule': 'alt_coverage',
                        'message': f'Alt text coverage {coverage:.1f}% < required {alt_coverage}%',
                    })
        
        # Check color contrast (basic check for inline styles)
        if 'color_contrast' in self._rule_names('accessibility'):
            elements_with_style = soup.find_all(style=True)
            for elem in elements_with_style:
                style = elem.get('style', '')
                if 'color' in style.lower():
                    # Note: Full contrast checking requires rendered colors
                    # This is a placeholder for the concept
                    pass
        
        # Check keyboard navigation (check for tabindex misuse)
        if 'keyboard_nav' in self._rule_names('accessibility'):
            def has_positive_tabindex(value):
                try:
                    return value is not None and int(value) > 0
                except (TypeError, ValueError):
                    return False

            bad_tabindex = soup.find_all(attrs={'tabindex': has_positive_tabindex})
            if bad_tabindex:
                issues.append({
                    'severity': 'warning',
                    'rule': 'keyboard_nav',
                    'message': f'Found {len(bad_tabindex)} elements with positive tabindex (anti-pattern)',
                })
        
        return issues
    
    def check_seo(self, html: str) -> List[Dict]:
        """Check SEO requirements"""
        issues = []
        soup = BeautifulSoup(html, 'html.parser')
        
        # Check meta description
        if 'meta_description' in self._rule_names('seo'):
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            if not meta_desc or not meta_desc.get('content'):
                issues.append({
                    'severity': 'error',
                    'rule': 'meta_description',
                    'message': 'Missing or empty meta description',
                })
        
        # Check canonical URL
        if 'canonical_url' in self._rule_names('seo'):
            canonical = soup.find('link', attrs={'rel': 'canonical'})
            if not canonical:
                issues.append({
                    'severity': 'warning',
                    'rule': 'canonical_url',
                    'message': 'Missing canonical URL',
                })
        
        # Check valid JSON-LD
        if 'valid_jsonld' in self._rule_names('seo'):
            jsonld_scripts = soup.find_all('script', attrs={'type': 'application/ld+json'})
            for script in jsonld_scripts:
                try:
                    json.loads(script.string)
                except (json.JSONDecodeError, TypeError):
                    issues.append({
                        'severity': 'error',
                        'rule': 'valid_jsonld',
                        'message': 'Invalid JSON-LD markup detected',
                    })
        
        return issues
    
    def check_budgets(self, html_path: Path) -> List[Dict]:
        """Check performance budgets"""
        issues = []
        
        html_size = html_path.stat().st_size
        html_budget = self.budgets.get('html', float('inf'))
        
        if html_size > html_budget:
            issues.append({
                'severity': 'error',
                'rule': 'html_budget',
                'message': f'HTML size {html_size} bytes exceeds budget {html_budget} bytes',
            })
        
        # Check inline CSS size
        with open(html_path, 'r') as f:
            content = f.read()
            style_tags = re.findall(r'<style[^>]*>(.*?)</style>', content, re.DOTALL)
            css_size = sum(len(style) for style in style_tags)
            css_budget = self.budgets.get('css', float('inf'))
            
            if css_size > css_budget:
                issues.append({
                    'severity': 'error',
                    'rule': 'css_budget',
                    'message': f'CSS size {css_size} bytes exceeds budget {css_budget} bytes',
                })
        
        # Check for JavaScript (should be 0 on content pages)
        js_budget = self.budgets.get('js', float('inf'))
        if js_budget == 0 and not self._allows_executable_js(html_path):
            soup = BeautifulSoup(content, 'html.parser')
            scripts = [script for script in soup.find_all('script') if self._is_executable_script(script)]
            
            if scripts:
                issues.append({
                    'severity': 'error',
                    'rule': 'js_budget',
                    'message': 'JavaScript detected, but budget is 0 bytes',
                })
        
        return issues

    def _allows_executable_js(self, html_path: Path) -> bool:
        """Skip JS=0 content-page enforcement for known interactive utility pages."""
        utility_sections = {'search', 'cart', 'products', 'studio'}
        return any(part in utility_sections for part in html_path.parts)

    def _is_executable_script(self, script) -> bool:
        script_type = (script.get('type') or '').strip().lower()
        non_executable_types = {
            'application/ld+json',
            'application/json',
            'application/schema+json',
            'application/vnd.api+json',
            'text/template',
        }

        if script_type in non_executable_types:
            return False

        return bool(script.get('src') or (script.string and script.string.strip()))
    
    def validate_file(self, html_path: Path) -> Dict[str, Any]:
        """Validate a single HTML file against all contracts"""
        with open(html_path, 'r') as f:
            html = f.read()
        
        results = {
            'file': str(html_path),
            'semantic': self.check_semantic(html),
            'accessibility': self.check_accessibility(html),
            'seo': self.check_seo(html),
            'budgets': self.check_budgets(html_path),
        }
        
        # Calculate summary
        all_issues = (results['semantic'] + results['accessibility'] + 
                     results['seo'] + results['budgets'])
        
        results['summary'] = {
            'total_issues': len(all_issues),
            'errors': len([i for i in all_issues if i['severity'] == 'error']),
            'warnings': len([i for i in all_issues if i['severity'] == 'warning']),
            'passed': len([i for i in all_issues if i['severity'] == 'error']) == 0,
        }
        
        return results
    
    def validate_directory(self, dist_path: Path) -> Dict[str, Any]:
        """Validate all HTML files in output directory"""
        html_files = list(dist_path.rglob('*.html'))
        results = []
        
        for html_file in html_files:
            file_result = self.validate_file(html_file)
            results.append(file_result)
        
        # Overall summary
        total_files = len(results)
        passed_files = len([r for r in results if r['summary']['passed']])
        
        return {
            'files': results,
            'summary': {
                'total_files': total_files,
                'passed': passed_files,
                'failed': total_files - passed_files,
                'pass_rate': (passed_files / total_files * 100) if total_files > 0 else 0,
            }
        }
