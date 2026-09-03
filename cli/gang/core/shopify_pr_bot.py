"""
Shopify PR Bot
Automatically creates PRs when Shopify products are updated
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
import json
import re
import yaml
import subprocess
from datetime import datetime
import os

SAFE_SLUG_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')


def _is_safe_product_slug(slug: str) -> bool:
    value = str(slug or '').strip()
    return bool(SAFE_SLUG_RE.match(value)) and '..' not in value and '/' not in value and '\\' not in value


class ShopifyPRBot:
    """Create GitHub PRs for Shopify product updates"""
    
    def __init__(self, content_path: Path, field_mapping_path: Path):
        self.content_path = Path(content_path)
        self.field_mapping_path = Path(field_mapping_path)
        self.field_mapping = self._load_field_mapping()
    
    def _load_field_mapping(self) -> Dict[str, Any]:
        """Load product field mapping schema"""
        
        if not self.field_mapping_path.exists():
            # Return default mapping
            return {
                'mappings': {
                    'title': {'shopify_field': 'title', 'frontmatter_field': 'title'},
                    'description': {'shopify_field': 'body_html', 'frontmatter_field': 'description'},
                    'slug': {'shopify_field': 'handle', 'frontmatter_field': 'slug'},
                }
            }
        
        return json.loads(self.field_mapping_path.read_text())
    
    def convert_to_frontmatter(self, product_data: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Shopify product to frontmatter using field mapping"""
        
        frontmatter = {}
        mappings = self.field_mapping.get('mappings', {})
        
        for key, mapping in mappings.items():
            shopify_field = mapping.get('shopify_field') or mapping.get('source')
            frontmatter_field = mapping.get('frontmatter_field') or mapping.get('target') or key
            if not shopify_field:
                continue
            
            # Extract value from Shopify data
            value = self._extract_field(product_data, shopify_field)
            
            # Apply transformation if specified (including 0 / empty-string values)
            transform = mapping.get('transform')
            if transform is not None and value is not None:
                value = self._apply_transform(value, transform)
            
            # Use default if value is None and default is specified
            if value is None and 'default' in mapping:
                value = mapping['default']
            
            if value is not None:
                frontmatter[frontmatter_field] = value
        
        # Add metadata
        frontmatter['shopify_updated_at'] = datetime.utcnow().isoformat()
        frontmatter['source'] = 'shopify'

        variants = frontmatter.get('variants')
        if isinstance(variants, list):
            try:
                from core.products import append_variant_query, shopify_storefront_url
            except ImportError:
                from gang.core.products import append_variant_query, shopify_storefront_url
            try:
                from core.html_sanitize import safe_http_url
            except ImportError:
                from gang.core.html_sanitize import safe_http_url
            base = shopify_storefront_url(product_data)
            for variant in variants:
                if not isinstance(variant, dict):
                    continue
                if not variant.get('url'):
                    variant['url'] = append_variant_query(base, variant.get('id'))
                variant['url'] = safe_http_url(variant.get('url'))
        
        return frontmatter
    
    def _extract_field(self, data: Dict, field_path: str) -> Any:
        """Extract nested field using dot notation, including images[*].src."""
        
        parts = field_path.split('.')
        value = data
        
        for i, part in enumerate(parts):
            if not isinstance(value, dict):
                return None
            if '[' in part:
                key = part.split('[')[0]
                index = part.split('[')[1].rstrip(']')
                items = value.get(key)
                if not isinstance(items, list):
                    return None
                if index == '*':
                    rest = parts[i + 1:]
                    if not rest:
                        return items
                    extracted = []
                    for item in items:
                        sub = item
                        ok = True
                        for rest_part in rest:
                            if isinstance(sub, dict) and rest_part in sub:
                                sub = sub[rest_part]
                            else:
                                ok = False
                                break
                        if ok and sub is not None:
                            extracted.append(sub)
                    return extracted
                if index.isdigit():
                    idx = int(index)
                    if 0 <= idx < len(items):
                        value = items[idx]
                    else:
                        return None
                else:
                    return None
            elif part in value:
                value = value[part]
            else:
                return None
        
        return value
    
    def _apply_transform(self, value: Any, transform: str) -> Any:
        """Apply transformation to value"""
        
        if transform == 'html_to_markdown':
            # Convert HTML to markdown (simplified)
            from html import unescape
            import re
            
            # Remove HTML tags
            value = re.sub(r'<[^>]+>', '', str(value))
            value = unescape(value)
            return value
        
        elif transform == 'normalize_variants':
            # Normalize variant structure
            if isinstance(value, list):
                try:
                    from core.products import coerce_available_flag
                except ImportError:
                    from gang.core.products import coerce_available_flag
                try:
                    from core.html_sanitize import safe_http_url
                except ImportError:
                    from gang.core.html_sanitize import safe_http_url
                normalized = []
                for v in value:
                    if not isinstance(v, dict):
                        continue
                    qty = v.get('inventory_quantity')
                    try:
                        qty_num = int(qty) if qty is not None and qty != '' else 0
                    except (TypeError, ValueError):
                        qty_num = 0
                    policy = str(v.get('inventory_policy') or '')
                    available = coerce_available_flag(v.get('available'))
                    inventory_management = v.get('inventory_management')
                    if available is None:
                        if inventory_management is None or inventory_management == '':
                            available = True
                        elif policy == 'continue':
                            available = True
                        else:
                            available = qty_num > 0
                    normalized.append({
                        'id': v.get('id'),
                        'title': v.get('title'),
                        'price': v.get('price'),
                        'sku': v.get('sku'),
                        'inventory': qty_num,
                        'inventory_quantity': qty_num,
                        'inventory_policy': v.get('inventory_policy'),
                        'inventory_management': v.get('inventory_management'),
                        'option1': v.get('option1'),
                        'option2': v.get('option2'),
                        'option3': v.get('option3'),
                        'available': available is True,
                        'availability': (
                            'https://schema.org/InStock'
                            if available is True
                            else 'https://schema.org/OutOfStock'
                        ),
                        'url': safe_http_url(v.get('url') or v.get('buy_url')),
                    })
                return normalized
        
        return value
    
    def generate_markdown_file(self, product_data: Dict[str, Any]) -> Path:
        """Generate markdown file for product"""
        
        frontmatter = self.convert_to_frontmatter(product_data)
        
        # Get slug and jail it under content/products/
        slug = str(frontmatter.get('slug') or product_data.get('handle') or '').strip()
        if not _is_safe_product_slug(slug):
            raise ValueError(f'Unsafe product slug: {slug!r}')

        products_dir = (self.content_path / 'products').resolve()
        products_dir.mkdir(parents=True, exist_ok=True)
        file_path = (products_dir / f"{slug}.md").resolve()
        file_path.relative_to(products_dir)

        # Generate markdown content
        dumped = yaml.dump(frontmatter, default_flow_style=False).strip()
        body = frontmatter.get('description') or ''
        file_path.write_text(f"---\n{dumped}\n---\n{body}\n")

        return file_path
    
    def create_pr(self, product_data: Dict[str, Any], branch_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Create GitHub PR for product update
        
        Returns:
            Dict with PR details or error
        """
        
        handle = product_data.get('handle', 'unknown')
        
        if not branch_name:
            timestamp = datetime.utcnow().strftime('%Y%m%d-%H%M%S')
            branch_name = f"shop/update-{handle}-{timestamp}"
        
        result = {
            'success': False,
            'branch': branch_name,
            'product_handle': handle
        }
        
        try:
            # 1. Create new branch
            subprocess.run(['git', 'checkout', '-b', branch_name], check=True, capture_output=True)
            
            # 2. Generate markdown file
            file_path = self.generate_markdown_file(product_data)
            result['file_path'] = str(file_path)
            
            # 3. Stage changes
            subprocess.run(['git', 'add', str(file_path)], check=True, capture_output=True)
            
            # 4. Commit
            commit_msg = f"Update product: {product_data.get('title', handle)}\n\nShopify updated at: {product_data.get('updated_at')}"
            subprocess.run(['git', 'commit', '-m', commit_msg], check=True, capture_output=True)
            
            # 5. Push to remote (if GITHUB_TOKEN is set)
            github_token = os.getenv('GITHUB_TOKEN')
            if github_token:
                subprocess.run(['git', 'push', 'origin', branch_name], check=True, capture_output=True)
                
                # 6. Create PR via GitHub API
                pr_result = self._create_github_pr(
                    branch_name,
                    product_data,
                    github_token
                )
                
                result.update(pr_result)
            else:
                result['success'] = True
                result['message'] = 'Branch created locally. Set GITHUB_TOKEN to auto-create PR.'
            
        except subprocess.CalledProcessError as e:
            result['error'] = f"Git command failed: {e.stderr.decode()}"
        except Exception as e:
            result['error'] = str(e)
        
        return result
    
    def _create_github_pr(self, branch_name: str, product_data: Dict[str, Any], 
                          github_token: str) -> Dict[str, Any]:
        """Create PR using GitHub API"""
        
        import requests
        
        # Get repo info from git remote
        remote_url = subprocess.run(
            ['git', 'config', '--get', 'remote.origin.url'],
            capture_output=True,
            text=True
        ).stdout.strip()
        
        # Parse owner/repo from URL
        # Example: https://github.com/owner/repo.git or git@github.com:owner/repo.git
        if 'github.com' in remote_url:
            parts = remote_url.replace('.git', '').split('/')
            repo = parts[-1]
            owner = parts[-2].split(':')[-1]
        else:
            return {'success': False, 'error': 'Could not parse GitHub repo from remote URL'}
        
        # Create PR
        title = f"🛒 Update product: {product_data.get('title', product_data.get('handle'))}"
        
        body = f"""## Product Update
        
**Product:** {product_data.get('title')}  
**Handle:** {product_data.get('handle')}  
**Updated:** {product_data.get('updated_at')}  

### Changes
- Price: ${product_data.get('variants', [{}])[0].get('price', 'N/A')}
- Inventory: {product_data.get('variants', [{}])[0].get('inventory_quantity', 'N/A')} units

This PR was automatically generated by Shopify PR Bot.
"""
        
        api_url = f"https://api.github.com/repos/{owner}/{repo}/pulls"
        
        headers = {
            'Authorization': f'token {github_token}',
            'Accept': 'application/vnd.github.v3+json'
        }
        
        data = {
            'title': title,
            'body': body,
            'head': branch_name,
            'base': 'main'  # or 'master'
        }
        
        response = requests.post(api_url, headers=headers, json=data)
        
        if response.status_code == 201:
            pr_data = response.json()
            return {
                'success': True,
                'pr_url': pr_data['html_url'],
                'pr_number': pr_data['number']
            }
        else:
            return {
                'success': False,
                'error': f"GitHub API error: {response.status_code} - {response.text}"
            }

