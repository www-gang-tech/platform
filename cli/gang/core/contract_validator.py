"""
Contract Validator - Enforce page-type contracts
Validates pages against their contract specifications
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
import yaml
import re
from bs4 import BeautifulSoup


class ContractValidator:
    """Validate pages against their type contracts"""
    
    def __init__(self, contracts_dir: Path):
        self.contracts_dir = Path(contracts_dir)
        self.contracts = self._load_contracts()
    
    def _load_contracts(self) -> Dict[str, Dict[str, Any]]:
        """Load all contract files"""
        contracts = {}
        
        for contract_file in self.contracts_dir.glob('*.yml'):
            contract = yaml.safe_load(contract_file.read_text())
            contracts[contract['type']] = contract
        
        return contracts
    
    def validate_file(self, html_path: Path, content_type: str) -> Dict[str, Any]:
        """Validate a single HTML file against its contract"""
        
        contract = self.contracts.get(content_type)
        if not contract:
            return {'valid': True, 'errors': [], 'warnings': [f'No contract for type: {content_type}']}
        
        html_content = html_path.read_text()
        soup = BeautifulSoup(html_content, 'html.parser')
        
        errors = []
        warnings = []
        
        # Validate budgets
        budget_result = self._check_budgets(html_content, contract.get('budgets', {}))
        errors.extend(budget_result['errors'])
        warnings.extend(budget_result['warnings'])
        
        # Validate headings
        heading_result = self._check_headings(soup, contract.get('headings', {}))
        errors.extend(heading_result['errors'])
        
        # Validate landmarks
        landmark_result = self._check_landmarks(soup, contract.get('landmarks', {}))
        errors.extend(landmark_result['errors'])
        warnings.extend(landmark_result['warnings'])
        
        # Validate JSON-LD
        jsonld_result = self._check_jsonld(soup, contract.get('jsonld', {}))
        errors.extend(jsonld_result['errors'])
        
        # Validate meta tags
        meta_result = self._check_meta(soup, contract.get('meta', {}))
        errors.extend(meta_result['errors'])
        
        return {
            'valid': len(errors) == 0,
            'errors': errors,
            'warnings': warnings,
            'contract_type': content_type,
            'file': str(html_path)
        }
    
    def _check_budgets(self, html: str, budgets: Dict[str, int]) -> Dict[str, List[str]]:
        """Check file size budgets"""
        errors = []
        warnings = []
        
        html_size = len(html.encode('utf-8'))
        html_budget = budgets.get('html', float('inf'))
        
        if html_size > html_budget:
            errors.append(f"HTML size {html_size} bytes exceeds budget {html_budget} bytes")
        elif html_size > html_budget * 0.9:
            warnings.append(f"HTML size {html_size} bytes is 90% of budget {html_budget} bytes")
        
        # Note: CSS and JS budgets checked separately in build process
        
        return {'errors': errors, 'warnings': warnings}
    
    def _check_headings(self, soup: BeautifulSoup, heading_rules: Dict) -> Dict[str, List[str]]:
        """Check heading structure"""
        errors = []
        
        # Check for exactly one h1
        if heading_rules.get('single_h1', True):
            h1_tags = soup.find_all('h1')
            if len(h1_tags) == 0:
                errors.append("Missing required <h1> tag")
            elif len(h1_tags) > 1:
                errors.append(f"Multiple <h1> tags found: {len(h1_tags)} (should be exactly 1)")
        
        # Check heading order (no skips)
        all_headings = soup.find_all(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        prev_level = 0
        
        for heading in all_headings:
            level = int(heading.name[1])
            
            if prev_level > 0 and level > prev_level + 1:
                errors.append(f"Heading skip detected: {heading.name} after h{prev_level} ('{heading.get_text()}')")
            
            prev_level = level
        
        return {'errors': errors}
    
    def _check_landmarks(self, soup: BeautifulSoup, landmark_rules: Dict) -> Dict[str, List[str]]:
        """Check ARIA landmarks"""
        errors = []
        warnings = []
        
        required = landmark_rules.get('required', [])
        
        for landmark in required:
            elements = soup.find_all(landmark)
            if not elements:
                errors.append(f"Missing required landmark: <{landmark}>")
        
        recommended = landmark_rules.get('recommended', [])
        for landmark in recommended:
            elements = soup.find_all(landmark)
            if not elements:
                warnings.append(f"Recommended landmark missing: <{landmark}>")
        
        return {'errors': errors, 'warnings': warnings}
    
    def _check_jsonld(self, soup: BeautifulSoup, jsonld_rules: Dict) -> Dict[str, List[str]]:
        """Check JSON-LD structured data"""
        errors = []
        
        # Find JSON-LD scripts
        jsonld_scripts = soup.find_all('script', type='application/ld+json')
        
        if not jsonld_scripts:
            errors.append("Missing JSON-LD structured data")
            return {'errors': errors}
        
        import json
        
        required_type = jsonld_rules.get('required_type')
        required_props = jsonld_rules.get('required_props', [])
        
        for script in jsonld_scripts:
            try:
                data = json.loads(script.string)
                
                # Check @type
                if required_type and data.get('@type') != required_type:
                    errors.append(f"JSON-LD @type is '{data.get('@type')}', expected '{required_type}'")
                
                # Check required props
                for prop in required_props:
                    if prop not in data:
                        errors.append(f"Missing required JSON-LD property: {prop}")
                
            except json.JSONDecodeError:
                errors.append("Invalid JSON-LD: failed to parse")
        
        return {'errors': errors}
    
    def _check_meta(self, soup: BeautifulSoup, meta_rules: Dict) -> Dict[str, List[str]]:
        """Check meta tags"""
        errors = []
        
        required = meta_rules.get('required', [])
        
        for meta_name in required:
            if meta_name == 'title':
                if not soup.find('title'):
                    errors.append("Missing <title> tag")
            elif meta_name == 'description':
                if not soup.find('meta', attrs={'name': 'description'}):
                    errors.append("Missing meta description")
            elif meta_name == 'canonical':
                if not soup.find('link', attrs={'rel': 'canonical'}):
                    errors.append("Missing canonical URL")
            elif meta_name.startswith('og:'):
                if not soup.find('meta', attrs={'property': meta_name}):
                    errors.append(f"Missing Open Graph tag: {meta_name}")
            elif meta_name.startswith('twitter:'):
                if not soup.find('meta', attrs={'name': meta_name}):
                    errors.append(f"Missing Twitter Card tag: {meta_name}")
        
        return {'errors': errors}
    
    def generate_explain_report(self, results: List[Dict[str, Any]]) -> str:
        """Generate human-readable Explain report"""
        
        report = []
        report.append("=" * 80)
        report.append("CONTRACT VALIDATION REPORT - Explain")
        report.append("=" * 80)
        report.append("")
        
        total_files = len(results)
        failed_files = [r for r in results if not r['valid']]
        
        report.append(f"Files Checked: {total_files}")
        report.append(f"Passed: {total_files - len(failed_files)}")
        report.append(f"Failed: {len(failed_files)}")
        report.append("")
        
        if not failed_files:
            report.append("✅ All contracts satisfied!")
            return '\n'.join(report)
        
        report.append("❌ CONTRACT VIOLATIONS FOUND:")
        report.append("")
        
        for result in failed_files:
            report.append(f"File: {result['file']}")
            report.append(f"Type: {result['contract_type']}")
            report.append("")
            
            if result['errors']:
                report.append("  ERRORS:")
                for error in result['errors']:
                    report.append(f"    ❌ {error}")
                report.append("")
            
            if result.get('warnings'):
                report.append("  WARNINGS:")
                for warning in result['warnings']:
                    report.append(f"    ⚠️  {warning}")
                report.append("")
            
            report.append("-" * 80)
            report.append("")
        
        return '\n'.join(report)

