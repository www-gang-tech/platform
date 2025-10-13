"""
GANG Product Aggregator
Fetch products from multiple platforms and normalize to Schema.org
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import json
import os


class ProductSchema:
    """Normalize product data to Schema.org Product schema"""
    
    @staticmethod
    def normalize(product: Dict[str, Any], source: str) -> Dict[str, Any]:
        """
        Normalize product from any platform to Schema.org/Product
        """
        if source == 'shopify':
            return ProductSchema._from_shopify(product)
        elif source == 'stripe':
            return ProductSchema._from_stripe(product)
        elif source == 'gumroad':
            return ProductSchema._from_gumroad(product)
        else:
            return product
    
    @staticmethod
    def _from_shopify(product: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Shopify product to Schema.org"""
        variants = product.get('variants', [])
        first_variant = variants[0] if variants else {}
        
        # Get images
        images = [img.get('src') for img in product.get('images', [])]
        
        # Build offers from variants
        offers = []
        for variant in variants:
            # Shopify Admin REST API uses different field names than GraphQL
            # REST API: inventory_quantity, inventory_management, inventory_policy
            # GraphQL: inventoryQuantity, availableForSale
            
            inventory_qty = variant.get('inventory_quantity', variant.get('inventoryQuantity', 0))
            inventory_management = variant.get('inventory_management')  # 'shopify' if tracked, None if not
            inventory_policy = variant.get('inventory_policy', 'deny')  # 'continue' allows selling when out of stock
            
            # Determine availability:
            # - If inventory not tracked: Always in stock
            # - If inventory tracked: Check quantity > 0 OR policy allows overselling
            if inventory_management is None or inventory_management == '':
                # Not tracking inventory - always available
                in_stock = True
            elif inventory_policy == 'continue':
                # Allow overselling - always available
                in_stock = True
            else:
                # Inventory tracked and no overselling - check quantity
                in_stock = inventory_qty > 0
            
            offers.append({
                '@type': 'Offer',
                'price': variant.get('price', '0'),
                'priceCurrency': 'USD',
                'availability': 'https://schema.org/InStock' if in_stock else 'https://schema.org/OutOfStock',
                'url': f"{product.get('url')}?variant={variant.get('id')}",
                'sku': variant.get('sku', ''),
                'name': variant.get('title', ''),
                'inventory_quantity': inventory_qty  # Include for debugging
            })
        
        return {
            '@context': 'https://schema.org',
            '@type': 'Product',
            'name': product.get('title', ''),
            'description': product.get('body_html', ''),
            'image': images,
            'offers': offers if len(offers) > 1 else offers[0] if offers else {
                '@type': 'Offer',
                'price': first_variant.get('price', '0'),
                'priceCurrency': 'USD',
                'availability': 'https://schema.org/InStock'
            },
            'sku': first_variant.get('sku', ''),
            'brand': {
                '@type': 'Brand',
                'name': product.get('vendor', '')
            },
            'category': product.get('product_type', ''),
            '_meta': {
                'source': 'shopify',
                'id': product.get('id'),
                'handle': product.get('handle'),
                'url': product.get('url'),
                'variants': variants,
                'created_at': product.get('created_at'),
                'updated_at': product.get('updated_at')
            }
        }
    
    @staticmethod
    def _from_stripe(product: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Stripe product to Schema.org"""
        prices = product.get('prices', [])
        first_price = prices[0] if prices else {}
        
        return {
            '@context': 'https://schema.org',
            '@type': 'Product',
            'name': product.get('name', ''),
            'description': product.get('description', ''),
            'image': product.get('images', []),
            'offers': {
                '@type': 'Offer',
                'price': str(first_price.get('unit_amount', 0) / 100),
                'priceCurrency': first_price.get('currency', 'usd').upper(),
                'availability': 'https://schema.org/InStock' if product.get('active') else 'https://schema.org/OutOfStock'
            },
            '_meta': {
                'source': 'stripe',
                'id': product.get('id'),
                'url': product.get('url'),
                'prices': prices,
                'created': product.get('created'),
                'updated': product.get('updated')
            }
        }
    
    @staticmethod
    def _from_gumroad(product: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Gumroad product to Schema.org"""
        return {
            '@context': 'https://schema.org',
            '@type': 'Product',
            'name': product.get('name', ''),
            'description': product.get('description', ''),
            'image': [product.get('thumbnail_url')] if product.get('thumbnail_url') else [],
            'offers': {
                '@type': 'Offer',
                'price': str(product.get('price', 0) / 100),
                'priceCurrency': product.get('currency', 'USD'),
                'availability': 'https://schema.org/InStock'
            },
            '_meta': {
                'source': 'gumroad',
                'id': product.get('id'),
                'url': product.get('short_url'),
                'created_at': product.get('created_at')
            }
        }


class ShopifyClient:
    """Shopify Storefront API client"""
    
    def __init__(self, store_url: str, access_token: str):
        self.store_url = store_url.replace('https://', '').replace('http://', '')
        self.access_token = access_token
        self.api_version = '2024-01'
    
    def fetch_products(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch products from Shopify"""
        # Demo mode - return mock data
        if not self.access_token or self.access_token == 'demo':
            return self._demo_products()
        
        try:
            import requests
            
            url = f"https://{self.store_url}/admin/api/{self.api_version}/products.json"
            headers = {
                'X-Shopify-Access-Token': self.access_token,
                'Content-Type': 'application/json'
            }
            
            params = {'limit': limit}
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            return data.get('products', [])
        
        except Exception as e:
            print(f"Error fetching from Shopify: {e}")
            return []
    
    def _demo_products(self) -> List[Dict[str, Any]]:
        """Return demo Shopify products"""
        return [
            {
                'id': 1,
                'title': 'Example T-Shirt',
                'body_html': '<p>A comfortable cotton t-shirt</p>',
                'vendor': 'Demo Store',
                'product_type': 'Apparel',
                'handle': 'example-t-shirt',
                'url': 'https://demo.myshopify.com/products/example-t-shirt',
                'images': [
                    {'src': 'https://via.placeholder.com/800x800?text=T-Shirt'}
                ],
                'variants': [
                    {
                        'id': 1,
                        'title': 'Small',
                        'price': '29.99',
                        'sku': 'TSHIRT-SM',
                        'available': True
                    },
                    {
                        'id': 2,
                        'title': 'Medium',
                        'price': '29.99',
                        'sku': 'TSHIRT-MD',
                        'available': True
                    },
                    {
                        'id': 3,
                        'title': 'Large',
                        'price': '29.99',
                        'sku': 'TSHIRT-LG',
                        'available': False
                    }
                ],
                'created_at': '2024-01-01T00:00:00Z',
                'updated_at': '2024-01-15T00:00:00Z'
            }
        ]


class StripeClient:
    """Stripe Products API client"""
    
    def __init__(self, secret_key: str):
        self.secret_key = secret_key
    
    def fetch_products(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch products from Stripe"""
        # Demo mode
        if not self.secret_key or self.secret_key == 'demo':
            return self._demo_products()
        
        try:
            import stripe
            stripe.api_key = self.secret_key
            
            products = stripe.Product.list(limit=limit, active=True)
            result = []
            
            for product in products.data:
                # Fetch prices for this product
                prices = stripe.Price.list(product=product.id, active=True)
                
                result.append({
                    'id': product.id,
                    'name': product.name,
                    'description': product.description,
                    'images': product.images,
                    'url': product.url,
                    'active': product.active,
                    'prices': [
                        {
                            'id': price.id,
                            'unit_amount': price.unit_amount,
                            'currency': price.currency,
                            'recurring': price.recurring
                        }
                        for price in prices.data
                    ],
                    'created': product.created,
                    'updated': product.updated
                })
            
            return result
        
        except Exception as e:
            print(f"Error fetching from Stripe: {e}")
            return []
    
    def _demo_products(self) -> List[Dict[str, Any]]:
        """Return demo Stripe products"""
        return [
            {
                'id': 'prod_demo1',
                'name': 'Premium Membership',
                'description': 'Access to all premium content',
                'images': ['https://via.placeholder.com/400x400?text=Membership'],
                'url': 'https://stripe.com/demo',
                'active': True,
                'prices': [
                    {
                        'id': 'price_demo1',
                        'unit_amount': 999,
                        'currency': 'usd',
                        'recurring': {'interval': 'month'}
                    }
                ],
                'created': 1640000000,
                'updated': 1640000000
            }
        ]


class GumroadClient:
    """Gumroad API client"""
    
    def __init__(self, access_token: str):
        self.access_token = access_token
    
    def fetch_products(self) -> List[Dict[str, Any]]:
        """Fetch products from Gumroad"""
        # Demo mode
        if not self.access_token or self.access_token == 'demo':
            return self._demo_products()
        
        try:
            import requests
            
            url = 'https://api.gumroad.com/v2/products'
            headers = {'Authorization': f'Bearer {self.access_token}'}
            
            response = requests.get(url, headers=headers)
            response.raise_for_status()
            
            data = response.json()
            return data.get('products', [])
        
        except Exception as e:
            print(f"Error fetching from Gumroad: {e}")
            return []
    
    def _demo_products(self) -> List[Dict[str, Any]]:
        """Return demo Gumroad products"""
        return [
            {
                'id': 'demo123',
                'name': 'Startup Guide eBook',
                'description': 'Complete guide to launching your startup',
                'price': 2900,
                'currency': 'USD',
                'short_url': 'https://gum.co/demo',
                'thumbnail_url': 'https://via.placeholder.com/400x400?text=eBook',
                'created_at': '2024-01-01T00:00:00Z'
            }
        ]


class ProductAggregator:
    """Aggregate products from multiple platforms"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.products_cache_file = Path('.products-cache.json')
    
    def fetch_all(self) -> Dict[str, List[Dict[str, Any]]]:
        """Fetch products from all configured platforms"""
        products = {
            'shopify': [],
            'stripe': [],
            'gumroad': []
        }
        
        # Shopify
        shopify_config = os.environ.get('SHOPIFY_STORE_URL'), os.environ.get('SHOPIFY_ACCESS_TOKEN')
        if shopify_config[0] and shopify_config[1]:
            # Only use real Shopify if both URL and token are set
            client = ShopifyClient(shopify_config[0], shopify_config[1])
            products['shopify'] = client.fetch_products()
        elif self.config.get('demo_mode', False):
            # Only use demo if explicitly enabled
            client = ShopifyClient('demo.myshopify.com', 'demo')
            products['shopify'] = client.fetch_products()
        
        # Stripe - only if explicitly configured
        stripe_key = os.environ.get('STRIPE_SECRET_KEY')
        if stripe_key and stripe_key != 'demo':
            client = StripeClient(stripe_key)
            products['stripe'] = client.fetch_products()
        
        # Gumroad - only if explicitly configured
        gumroad_token = os.environ.get('GUMROAD_ACCESS_TOKEN')
        if gumroad_token and gumroad_token != 'demo':
            client = GumroadClient(gumroad_token)
            products['gumroad'] = client.fetch_products()
        
        # Cache results
        self._save_cache(products)
        
        return products
    
    def get_normalized_products(self, status_filter: str = 'all') -> List[Dict[str, Any]]:
        """
        Get all products normalized to Schema.org
        status_filter: 'all', 'active', 'draft', 'archived'
        """
        all_products = self.fetch_all()
        normalized = []
        
        for source, products in all_products.items():
            for product in products:
                norm_product = ProductSchema.normalize(product, source)
                
                # Add status (default to 'active' for Shopify published products)
                if source == 'shopify':
                    # Shopify products come from published endpoint, so they're active
                    norm_product['_meta']['status'] = product.get('status', 'active')
                else:
                    norm_product['_meta']['status'] = 'active'
                
                # Filter by status
                if status_filter == 'all' or norm_product['_meta']['status'] == status_filter:
                    normalized.append(norm_product)
        
        return normalized
    
    def _save_cache(self, products: Dict[str, Any]):
        """Save products to cache file"""
        cache_data = {
            'cached_at': datetime.now().isoformat(),
            'products': products
        }
        self.products_cache_file.write_text(json.dumps(cache_data, indent=2))
    
    def load_cache(self) -> Optional[Dict[str, Any]]:
        """Load products from cache"""
        if self.products_cache_file.exists():
            try:
                return json.loads(self.products_cache_file.read_text())
            except:
                return None
        return None

