"""
Answerability Analyzer
Tests if pages provide "one-pass answers" for AI and search engines
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
from bs4 import BeautifulSoup
import json


class AnswerabilityAnalyzer:
    """Analyze content for answerability - can AI extract key facts in one pass?"""
    
    def __init__(self, dist_path: Path):
        self.dist_path = Path(dist_path)
    
    def analyze_site(self) -> Dict[str, Any]:
        """Analyze entire site for answerability"""
        
        results = {
            'total_pages': 0,
            'jsonld_coverage': 0,
            'pages': [],
            'by_type': {}
        }
        
        # Analyze all HTML files
        for html_file in self.dist_path.rglob('index.html'):
            page_result = self.analyze_page(html_file)
            results['pages'].append(page_result)
            results['total_pages'] += 1
            
            if page_result['has_jsonld']:
                results['jsonld_coverage'] += 1
            
            # Group by type
            page_type = page_result.get('type', 'unknown')
            if page_type not in results['by_type']:
                results['by_type'][page_type] = []
            results['by_type'][page_type].append(page_result)
        
        # Calculate coverage percentage
        if results['total_pages'] > 0:
            results['jsonld_coverage_pct'] = (results['jsonld_coverage'] / results['total_pages']) * 100
        else:
            results['jsonld_coverage_pct'] = 0
        
        return results
    
    def analyze_page(self, html_file: Path) -> Dict[str, Any]:
        """Analyze single page for answerability"""
        
        html = html_file.read_text()
        soup = BeautifulSoup(html, 'html.parser')
        
        result = {
            'file': str(html_file.relative_to(self.dist_path)),
            'has_jsonld': False,
            'jsonld_types': [],
            'extractable_data': {},
            'required_props': [],
            'missing_props': [],
            'answerability_score': 0
        }
        
        # Check for JSON-LD
        jsonld_scripts = soup.find_all('script', type='application/ld+json')
        if jsonld_scripts:
            result['has_jsonld'] = True
            
            for script in jsonld_scripts:
                try:
                    data = json.loads(script.string)
                    result['jsonld_types'].append(data.get('@type', 'Unknown'))
                    
                    # Determine type and check required props
                    schema_type = data.get('@type')
                    required = self._get_required_props(schema_type)
                    result['required_props'] = required
                    
                    # Check which are present
                    for prop in required:
                        if prop in data:
                            result['extractable_data'][prop] = 'present'
                        else:
                            result['missing_props'].append(prop)
                    
                except json.JSONDecodeError:
                    pass
        
        # Extract basic data
        title_tag = soup.find('title')
        if title_tag:
            result['extractable_data']['title'] = title_tag.get_text()
        
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        if meta_desc:
            result['extractable_data']['description'] = meta_desc.get('content', '')
        
        # Calculate answerability score (0-100)
        score = 0
        
        if result['has_jsonld']:
            score += 30
        
        if result['extractable_data'].get('title'):
            score += 10
        
        if result['extractable_data'].get('description'):
            score += 10
        
        # Points for each required prop present
        if result['required_props']:
            coverage = len([p for p in result['required_props'] if p in result['extractable_data']])
            score += (coverage / len(result['required_props'])) * 50
        
        result['answerability_score'] = int(score)
        result['type'] = self._infer_type(html_file)
        
        return result
    
    def _get_required_props(self, schema_type: str) -> List[str]:
        """Get required properties for a schema type"""
        
        props_map = {
            'BlogPosting': ['headline', 'datePublished', 'author', 'description'],
            'Article': ['headline', 'datePublished', 'author', 'description'],
            'Product': ['name', 'description', 'image', 'offers'],
            'WebPage': ['name', 'description', 'url'],
            'CreativeWork': ['name', 'description', 'author']
        }
        
        return props_map.get(schema_type, [])
    
    def _infer_type(self, file_path: Path) -> str:
        """Infer content type from file path"""
        
        parts = file_path.parts
        
        if 'posts' in parts:
            return 'post'
        elif 'pages' in parts:
            return 'page'
        elif 'projects' in parts:
            return 'project'
        elif 'products' in parts:
            return 'product'
        else:
            return 'unknown'
    
    def generate_html_report(self, results: Dict[str, Any]) -> str:
        """Generate HTML dashboard"""
        
        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Answerability Report</title>
    <style>
        body {{ font-family: system-ui, sans-serif; max-width: 1200px; margin: 2rem auto; padding: 0 1rem; }}
        h1 {{ border-bottom: 3px solid #000; padding-bottom: 0.5rem; }}
        .metric {{ background: #f5f5f5; padding: 1rem; margin: 1rem 0; border-left: 4px solid #000; }}
        .metric h3 {{ margin-top: 0; }}
        .score {{ font-size: 2rem; font-weight: bold; }}
        .pass {{ color: #2d7d2d; }}
        .warn {{ color: #d97706; }}
        .fail {{ color: #c53030; }}
        table {{ width: 100%; border-collapse: collapse; margin: 1rem 0; }}
        th, td {{ padding: 0.5rem; text-align: left; border-bottom: 1px solid #ddd; }}
        th {{ background: #000; color: #fff; }}
        .progress {{ background: #e5e5e5; height: 20px; border-radius: 4px; overflow: hidden; }}
        .progress-bar {{ background: #2d7d2d; height: 100%; }}
    </style>
</head>
<body>
    <h1>📊 Answerability & Schema Dashboard</h1>
    
    <div class="metric">
        <h3>JSON-LD Coverage</h3>
        <div class="score {'pass' if results['jsonld_coverage_pct'] >= 95 else 'warn' if results['jsonld_coverage_pct'] >= 80 else 'fail'}">
            {results['jsonld_coverage_pct']:.1f}%
        </div>
        <div class="progress">
            <div class="progress-bar" style="width: {results['jsonld_coverage_pct']}%"></div>
        </div>
        <p>{results['jsonld_coverage']} of {results['total_pages']} pages have structured data</p>
    </div>
    
    <h2>Pages by Type</h2>
"""
        
        for page_type, pages in results['by_type'].items():
            avg_score = sum(p['answerability_score'] for p in pages) / len(pages) if pages else 0
            
            html += f"""
    <div class="metric">
        <h3>{page_type.title()} ({len(pages)} pages)</h3>
        <p>Average Answerability: <strong>{avg_score:.0f}/100</strong></p>
    </div>
"""
        
        html += """
    <h2>All Pages</h2>
    <table>
        <tr>
            <th>Page</th>
            <th>Type</th>
            <th>JSON-LD</th>
            <th>Score</th>
            <th>Missing</th>
        </tr>
"""
        
        for page in results['pages']:
            html += f"""
        <tr>
            <td>{page['file']}</td>
            <td>{page['type']}</td>
            <td>{'✅' if page['has_jsonld'] else '❌'}</td>
            <td class="{'pass' if page['answerability_score'] >= 80 else 'warn' if page['answerability_score'] >= 60 else 'fail'}">
                {page['answerability_score']}/100
            </td>
            <td>{', '.join(page['missing_props']) if page['missing_props'] else '—'}</td>
        </tr>
"""
        
        html += """
    </table>
</body>
</html>
"""
        
        return html

