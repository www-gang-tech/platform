"""
GANG Link Fixer
Auto-apply AI-suggested link fixes to markdown files.
"""

import re
from pathlib import Path
from typing import Dict, List, Any


class LinkFixer:
    """Apply link fixes to markdown files"""
    
    def __init__(self, content_path: Path):
        self.content_path = content_path
        self.fixes_applied = []
        self.fixes_skipped = []
    
    def apply_suggestions(
        self, 
        suggestions: Dict[str, Any], 
        min_confidence: str = 'high',
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """Apply AI suggestions to files"""
        
        confidence_order = {'high': 3, 'medium': 2, 'low': 1}
        min_conf_value = confidence_order.get(min_confidence, 3)
        
        # Apply internal link fixes
        for suggestion in suggestions['internal']:
            file_path = self.content_path / suggestion['file']
            broken_url = suggestion['broken_url']
            suggested_url = suggestion['suggested_url']
            confidence = suggestion['confidence']
            
            # Check confidence threshold
            if confidence_order.get(confidence, 0) < min_conf_value:
                self.fixes_skipped.append({
                    'file': suggestion['file'],
                    'broken': broken_url,
                    'suggested': suggested_url,
                    'reason': f'Confidence {confidence} < {min_confidence}'
                })
                continue
            
            # Apply fix
            if suggested_url:
                self._replace_link_in_file(
                    file_path, broken_url, suggested_url, dry_run
                )
            else:
                # No suggestion - offer to remove
                action = suggestion.get('reasoning', '')
                if 'remove' in action.lower():
                    self._remove_link_in_file(
                        file_path, broken_url, dry_run
                    )
        
        # Apply redirect fixes (always high confidence)
        for suggestion in suggestions['redirects']:
            file_path = self.content_path / suggestion['file']
            current_url = suggestion['current_url']
            new_url = suggestion['redirect_to']
            
            self._replace_link_in_file(
                file_path, current_url, new_url, dry_run
            )
        
        return {
            'applied': len(self.fixes_applied),
            'skipped': len(self.fixes_skipped),
            'fixes': self.fixes_applied,
            'skipped_details': self.fixes_skipped,
            'dry_run': dry_run
        }
    
    def _replace_link_in_file(
        self, 
        file_path: Path, 
        old_url: str, 
        new_url: str, 
        dry_run: bool
    ):
        """Replace a link URL in a markdown file"""
        try:
            content = file_path.read_text()
            
            # Find and replace markdown link
            # Pattern: [any text](old_url)
            pattern = r'\[([^\]]+)\]\(' + re.escape(old_url) + r'\)'
            replacement = r'[\1](' + new_url + ')'
            
            new_content, count = re.subn(pattern, replacement, content)
            
            if count > 0:
                if not dry_run:
                    file_path.write_text(new_content)
                
                self.fixes_applied.append({
                    'file': str(file_path.relative_to(self.content_path)),
                    'old_url': old_url,
                    'new_url': new_url,
                    'count': count,
                    'action': 'replaced'
                })
            
        except Exception as e:
            self.fixes_skipped.append({
                'file': str(file_path.relative_to(self.content_path)),
                'broken': old_url,
                'suggested': new_url,
                'reason': f'Error: {str(e)}'
            })
    
    def _remove_link_in_file(
        self, 
        file_path: Path, 
        url: str, 
        dry_run: bool
    ):
        """Remove a link from markdown (keeping the text)"""
        try:
            content = file_path.read_text()
            
            # Pattern: [text](url) → text (remove link, keep text)
            pattern = r'\[([^\]]+)\]\(' + re.escape(url) + r'\)'
            replacement = r'\1'  # Just the text, no link
            
            new_content, count = re.subn(pattern, replacement, content)
            
            if count > 0:
                if not dry_run:
                    file_path.write_text(new_content)
                
                self.fixes_applied.append({
                    'file': str(file_path.relative_to(self.content_path)),
                    'old_url': url,
                    'new_url': None,
                    'count': count,
                    'action': 'removed'
                })
            
        except Exception as e:
            self.fixes_skipped.append({
                'file': str(file_path.relative_to(self.content_path)),
                'broken': url,
                'suggested': None,
                'reason': f'Error: {str(e)}'
            })
    
    def format_report(self, results: Dict[str, Any]) -> str:
        """Format fix results as readable report"""
        report = []
        
        report.append("=" * 60)
        if results['dry_run']:
            report.append("🔍 Link Fix Preview (Dry Run)")
        else:
            report.append("✅ Link Fixes Applied")
        report.append("=" * 60)
        report.append("")
        
        if results['applied'] > 0:
            report.append(f"✓ Applied {results['applied']} fix(es):")
            for fix in results['fixes']:
                if fix['action'] == 'replaced':
                    report.append(f"  {fix['file']}")
                    report.append(f"    {fix['old_url']} → {fix['new_url']}")
                else:
                    report.append(f"  {fix['file']}")
                    report.append(f"    Removed: {fix['old_url']}")
            report.append("")
        
        if results['skipped'] > 0:
            report.append(f"⚠️  Skipped {results['skipped']} fix(es):")
            for skip in results['skipped_details']:
                report.append(f"  {skip['file']}")
                report.append(f"    {skip['broken']} → {skip.get('suggested', 'N/A')}")
                report.append(f"    Reason: {skip['reason']}")
            report.append("")
        
        if results['dry_run']:
            report.append("💡 Run without --dry-run to apply these fixes")
        else:
            report.append("✅ Files updated! Run 'gang build' to rebuild")
        
        report.append("=" * 60)
        
        return '\n'.join(report)

