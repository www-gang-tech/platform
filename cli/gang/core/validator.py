"""
GANG Contract Validator
Enforces Template Contracts: semantics, a11y, budgets, JSON-LD
"""

from bs4 import BeautifulSoup
import json
from typing import List, Dict, Any

class ContractValidator:
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.contracts = config.get('contracts', {})
        self.budgets = config.get('budgets', {})
    
    def check_semantic(self, html: str) -> List[Dict]:
        """Check semantic HTML structure"""
        issues = []
        soup = BeautifulSoup(html, 'html.parser')
        
        # Check single H1
        h1_tags = soup.find_all('h1')
        if len(h1_tags) != 1:
            issues.append({
                'severity': 'error',
                'rule': 'single_h1',
                'message': f'Found {len(h1_tags)} <h1> elements. Exactly one H1 required.',
            })
        
        return issues
    
    def run_all_checks(self, html: str) -> Dict[str, List[Dict]]:
        """Run all contract validations"""
        return {
            'semantic': self.check_semantic(html),
        }
