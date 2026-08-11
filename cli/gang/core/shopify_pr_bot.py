"""
Shopify PR Bot
Automatically creates PRs when Shopify products are updated
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
import json
import yaml
import subprocess
from core.frontmatter import dump_frontmatter
from datetime import datetime
import os


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
            shopify_field = mapping['shopify_field']
            frontmatter_field = mapping['frontmatter_field']
            
            # Extract value from Shopify data
            value = self._extract_field(product_data, shopify_field)
            
            # Apply transformation if specified
            transform = mapping.get('transform')
            if transform and value:
                value = self._apply_transform(value, transform)
            
            # Use default if value is None and default is specified
            if value is None and 'default' in mapping:
                value = mapping['default']
            
            if value is not None:
                frontmatter[frontmatter_field] = value
        
        # Add metadata
        frontmatter['shopify_updated_at'] = datetime.utcnow().isoformat()
        frontmatter['source'] = 'shopify'
        
        return frontmatter
    
    def _extract_field(self, data: Dict, field_path: str) -> Any:
        """Extract nested field using dot notation / array indexes / wildcards."""
        
        parts = field_path.split('.')
        value = data
        
        for i, part in enumerate(parts):
            if '[' in part:
                # Array access: variants[0] or images[*]
                key = part.split('[')[0]
                index = part.split('[')[1].rstrip(']')
                
                if not isinstance(value, dict) or key not in value:
                    return None
                collection = value.get(key)
                if collection is None:
                    return None
                if not isinstance(collection, list):
                    return None
                if index == '*':
                    remaining = parts[i + 1:]
                    if not remaining:
                        return collection
                    extracted = []
                    for item in collection:
                        nested = self._extract_field(
                            item if isinstance(item, dict) else {},
                            '.'.join(remaining),
                        )
                        if nested is not None:
                            extracted.append(nested)
                    return extracted
                if index.isdigit():
                    idx = int(index)
                    if idx < 0 or idx >= len(collection):
                        return None
                    value = collection[idx]
                else:
                    return None
            else:
                if isinstance(value, dict) and part in value:
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
            # Normalize variant structure for markdown PDPs / product.js.
            if not isinstance(value, list):
                return []
            normalized = []
            for v in value:
                if not isinstance(v, dict):
                    continue
                raw_qty = v.get('inventory_quantity', v.get('inventory', 0))
                try:
                    inventory_qty = int(raw_qty) if raw_qty is not None else 0
                except (TypeError, ValueError):
                    inventory_qty = 0
                inventory_management = v.get('inventory_management')
                inventory_policy = v.get('inventory_policy', 'deny')
                if inventory_management in (None, ''):
                    in_stock = True
                elif inventory_policy == 'continue':
                    in_stock = True
                else:
                    in_stock = inventory_qty > 0
                option1 = str(v.get('option1') or '').strip()
                option2 = str(v.get('option2') or '').strip()
                option3 = str(v.get('option3') or '').strip()
                normalized.append({
                    'id': v.get('id'),
                    'title': v.get('title'),
                    'price': '0' if v.get('price') in (None, '') else str(v.get('price')),
                    'sku': v.get('sku') or '',
                    'inventory': inventory_qty,
                    'availability': (
                        'https://schema.org/InStock'
                        if in_stock
                        else 'https://schema.org/OutOfStock'
                    ),
                    'option1': option1,
                    'option2': option2,
                    'option3': option3,
                    # product.js matches color/size; map Shopify options.
                    'color': option1,
                    'size': option2 or (str(v.get('title') or '').strip() if not option1 else ''),
                    'material': option3,
                })
            return normalized
        
        return value
    
    def generate_markdown_file(self, product_data: Dict[str, Any]) -> Path:
        """Generate markdown file for product"""
        import re
        
        frontmatter = self.convert_to_frontmatter(product_data)
        
        # Get slug — reject path separators / traversal before writing.
        slug = str(frontmatter.get('slug', 'unknown') or 'unknown').strip()
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', slug):
            raise ValueError(f'Unsafe Shopify product slug/handle: {slug!r}')
        frontmatter['slug'] = slug
        
        # Create file path
        products_dir = (self.content_path / 'products').resolve()
        products_dir.mkdir(exist_ok=True)
        
        file_path = (products_dir / f"{slug}.md").resolve()
        try:
            file_path.relative_to(products_dir)
        except ValueError as exc:
            raise ValueError(f'Slug escaped products directory: {slug!r}') from exc
        
        content = dump_frontmatter(frontmatter, frontmatter.get('description', ''))
        
        file_path.write_text(content)
        
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
        
        variants = product_data.get('variants')
        first_variant = {}
        if isinstance(variants, list):
            first_variant = next((v for v in variants if isinstance(v, dict)), {})
        elif isinstance(variants, dict):
            first_variant = variants
        price = first_variant.get('price', 'N/A')
        inventory = first_variant.get(
            'inventory_quantity',
            first_variant.get('inventory', 'N/A'),
        )

        body = f"""## Product Update
        
**Product:** {product_data.get('title')}  
**Handle:** {product_data.get('handle')}  
**Updated:** {product_data.get('updated_at')}  

### Changes
- Price: ${price}
- Inventory: {inventory} units

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

