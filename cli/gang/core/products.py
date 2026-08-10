"""
GANG Product Aggregator
Fetch products from multiple platforms and normalize to Schema.org
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
import json
import os
import re


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
    def _slugify(value: Any, fallback: str = 'product') -> str:
        """Build a URL-safe slug for aggregator PDPs and PLP links."""
        text = re.sub(r'[^a-z0-9]+', '-', str(value or '').lower()).strip('-')
        if text and re.fullmatch(r'[a-z0-9][a-z0-9._-]*', text):
            return text
        fallback_text = re.sub(r'[^a-z0-9]+', '-', str(fallback or 'product').lower()).strip('-')
        return fallback_text or 'product'
    
    @staticmethod
    def _normalize_store_host(store: Optional[str]) -> str:
        """Strip scheme/slashes so host compares and URLs stay well-formed."""
        return (
            str(store or '')
            .replace('https://', '')
            .replace('http://', '')
            .strip()
            .strip('/')
        )

    @staticmethod
    def _shopify_currency() -> str:
        """Shop-level currency (Admin variants omit currency; allow env override)."""
        raw = (
            os.environ.get('SHOPIFY_CURRENCY')
            or os.environ.get('SHOPIFY_SHOP_CURRENCY')
            or 'USD'
        )
        currency = str(raw).strip().upper() or 'USD'
        if not re.fullmatch(r'[A-Z]{3}', currency):
            return 'USD'
        return currency

    @staticmethod
    def _shopify_product_url(product: Dict[str, Any]) -> str:
        """Resolve a public Shopify product URL from payload or store env."""
        existing = product.get('url')
        if existing:
            return str(existing).rstrip('/') if str(existing).endswith('/') else str(existing)
        handle = product.get('handle')
        if not handle:
            return ''
        store = ProductSchema._normalize_store_host(
            os.environ.get('SHOPIFY_STORE_URL') or os.environ.get('SHOPIFY_STORE')
        )
        if not store:
            return ''
        return f"https://{store}/products/{handle}"

    @staticmethod
    def _from_shopify(product: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Shopify product to Schema.org"""
        raw_variants = product.get('variants') or []
        if not isinstance(raw_variants, list):
            raw_variants = []
        variants = [v for v in raw_variants if isinstance(v, dict)]
        first_variant = variants[0] if variants else {}
        product_url = ProductSchema._shopify_product_url(product)
        currency = ProductSchema._shopify_currency()
        
        # Get images — tolerate null lists and non-dict entries from Admin API.
        raw_images = product.get('images') or []
        if not isinstance(raw_images, list):
            raw_images = []
        images = []
        for img in raw_images:
            if isinstance(img, dict) and img.get('src'):
                images.append(img.get('src'))
            elif isinstance(img, str) and img.strip():
                images.append(img.strip())
        
        # Build offers from variants
        offers = []
        for variant in variants:
            # Shopify Admin REST API uses different field names than GraphQL
            # REST API: inventory_quantity, inventory_management, inventory_policy
            # GraphQL: inventoryQuantity, availableForSale
            
            raw_qty = variant.get('inventory_quantity', variant.get('inventoryQuantity', 0))
            try:
                inventory_qty = int(raw_qty) if raw_qty is not None else 0
            except (TypeError, ValueError):
                inventory_qty = 0
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
            
            raw_price = variant.get('price')
            price = '0' if raw_price is None or raw_price == '' else str(raw_price)
            variant_id = variant.get('id')
            variant_id_str = '' if variant_id is None else str(variant_id).strip()
            offer_url = ''
            if product_url and variant_id_str and variant_id_str.lower() != 'none':
                offer_url = f"{product_url}?variant={variant_id_str}"
            # Prefer Shopify option1/option2 over title splitting ("Red/Blue" is one color).
            option1 = str(variant.get('option1') or '').strip()
            option2 = str(variant.get('option2') or '').strip()
            option3 = str(variant.get('option3') or '').strip()
            offers.append({
                '@type': 'Offer',
                'id': variant_id,
                'price': price,
                'priceCurrency': currency,
                'availability': 'https://schema.org/InStock' if in_stock else 'https://schema.org/OutOfStock',
                'url': offer_url,
                'sku': variant.get('sku') or '',
                'name': variant.get('title') or '',
                'option1': option1,
                'option2': option2,
                'option3': option3,
                'inventory_quantity': inventory_qty  # Include for debugging
            })

        # Shopify body_html is markup; store plain text for PLP/JSON-LD consumers.
        raw_description = product.get('body_html', '') or ''
        if '<' in str(raw_description):
            from bs4 import BeautifulSoup
            import re
            description = BeautifulSoup(str(raw_description), 'html.parser').get_text(' ')
            description = re.sub(r'\s+', ' ', description).strip()
        else:
            description = str(raw_description).strip()

        first_price = first_variant.get('price')
        first_price = '0' if first_price is None or first_price == '' else str(first_price)
        
        return {
            '@context': 'https://schema.org',
            '@type': 'Product',
            'name': product.get('title', ''),
            'description': description,
            'image': images,
            'offers': offers if len(offers) > 1 else offers[0] if offers else {
                '@type': 'Offer',
                'price': first_price,
                'priceCurrency': currency,
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
                'url': product_url or product.get('url'),
                'variants': variants,
                'created_at': product.get('created_at'),
                'updated_at': product.get('updated_at')
            }
        }
    
    @staticmethod
    def _from_stripe(product: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Stripe product to Schema.org"""
        raw_prices = product.get('prices', [])
        if isinstance(raw_prices, list):
            prices = [p for p in raw_prices if isinstance(p, dict)]
        else:
            prices = []
        first_price = prices[0] if prices else {}
        unit_amount = first_price.get('unit_amount')
        try:
            unit_amount = 0 if unit_amount is None else float(unit_amount)
        except (TypeError, ValueError):
            unit_amount = 0
        currency = (first_price.get('currency') or 'usd')
        currency = str(currency).upper() if currency else 'USD'
        slug = ProductSchema._slugify(product.get('name'), product.get('id') or 'stripe-product')
        images = product.get('images', [])
        if not isinstance(images, list):
            images = []
        
        return {
            '@context': 'https://schema.org',
            '@type': 'Product',
            'name': product.get('name', ''),
            'description': product.get('description', '') or '',
            'image': images,
            'offers': {
                '@type': 'Offer',
                'price': str(unit_amount / 100),
                'priceCurrency': currency,
                'availability': 'https://schema.org/InStock' if product.get('active') else 'https://schema.org/OutOfStock'
            },
            '_meta': {
                'source': 'stripe',
                'id': product.get('id'),
                'slug': slug,
                'handle': slug,
                'url': product.get('url'),
                'prices': prices,
                'created': product.get('created'),
                'updated': product.get('updated')
            }
        }
    
    @staticmethod
    def _from_gumroad(product: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Gumroad product to Schema.org"""
        raw_price = product.get('price')
        try:
            price_cents = 0 if raw_price is None or raw_price == '' else float(raw_price)
        except (TypeError, ValueError):
            price_cents = 0
        currency = product.get('currency') or 'USD'
        currency = str(currency).upper()
        slug = ProductSchema._slugify(
            product.get('custom_permalink') or product.get('name'),
            product.get('id') or 'gumroad-product',
        )
        return {
            '@context': 'https://schema.org',
            '@type': 'Product',
            'name': product.get('name', ''),
            'description': product.get('description', '') or '',
            'image': [product.get('thumbnail_url')] if product.get('thumbnail_url') else [],
            'offers': {
                '@type': 'Offer',
                'price': str(price_cents / 100),
                'priceCurrency': currency,
                'availability': 'https://schema.org/InStock'
            },
            '_meta': {
                'source': 'gumroad',
                'id': product.get('id'),
                'slug': slug,
                'handle': slug,
                'url': product.get('short_url'),
                'created_at': product.get('created_at')
            }
        }


class ShopifyClient:
    """Shopify Storefront API client"""
    
    def __init__(self, store_url: str, access_token: str):
        self.store_url = ProductSchema._normalize_store_host(store_url)
        self.access_token = access_token
        self.api_version = '2024-01'
    
    def fetch_products(self, limit: int = 100) -> Optional[List[Dict[str, Any]]]:
        """Fetch products from Shopify, following Admin API pagination."""
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
            
            page_limit = max(1, min(int(limit or 100), 250))
            params = {'limit': page_limit}
            products: List[Dict[str, Any]] = []
            while url:
                response = requests.get(url, headers=headers, params=params, timeout=30)
                response.raise_for_status()
                payload = response.json() if response.content else {}
                batch = payload.get('products', []) if isinstance(payload, dict) else []
                if not isinstance(batch, list):
                    batch = []
                for item in batch:
                    if isinstance(item, dict):
                        products.append(item)

                next_url = None
                link = response.headers.get('Link') or response.headers.get('link') or ''
                for part in link.split(','):
                    if 'rel="next"' in part:
                        start = part.find('<')
                        end = part.find('>')
                        if start != -1 and end != -1:
                            candidate = part[start + 1:end]
                            # Never follow pagination off the configured Shopify host
                            # (avoids leaking X-Shopify-Access-Token to a third party).
                            from urllib.parse import urlparse
                            parsed = urlparse(candidate)
                            if (
                                parsed.scheme == 'https'
                                and parsed.netloc.lower() == self.store_url.lower()
                                and parsed.path
                            ):
                                next_url = candidate
                        break
                url = next_url
                params = None  # next Link URL already includes query params

            for product in products:
                handle = product.get('handle')
                if handle and not product.get('url'):
                    product['url'] = f"https://{self.store_url}/products/{handle}"
            return products
        
        except Exception as e:
            print(f"Error fetching from Shopify: {e}")
            # None signals hard failure so fetch_all can restore cache;
            # [] means a successful empty catalog and must be writable.
            return None
    
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
    
    def fetch_products(self, limit: int = 100) -> Optional[List[Dict[str, Any]]]:
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
            return None
    
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
    
    def fetch_products(self) -> Optional[List[Dict[str, Any]]]:
        """Fetch products from Gumroad"""
        # Demo mode
        if not self.access_token or self.access_token == 'demo':
            return self._demo_products()
        
        try:
            import requests
            
            url = 'https://api.gumroad.com/v2/products'
            headers = {'Authorization': f'Bearer {self.access_token}'}
            
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            
            data = response.json() if response.content else {}
            if not isinstance(data, dict):
                return []
            # Key present with null must not be treated as hard failure (None).
            products = data.get('products', [])
            if products is None:
                return []
            if not isinstance(products, list):
                return []
            return [p for p in products if isinstance(p, dict)]
        
        except Exception as e:
            print(f"Error fetching from Gumroad: {e}")
            return None
    
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
        # Track which sources completed a live fetch successfully (including
        # empty catalogs). Failures return None and should restore cache.
        fetched_ok = set()

        # Shopify
        shopify_config = os.environ.get('SHOPIFY_STORE_URL'), os.environ.get('SHOPIFY_ACCESS_TOKEN')
        if shopify_config[0] and shopify_config[1]:
            # Only use real Shopify if both URL and token are set
            client = ShopifyClient(shopify_config[0], shopify_config[1])
            result = client.fetch_products()
            if result is None:
                pass  # failure — restore from cache below
            else:
                products['shopify'] = result
                fetched_ok.add('shopify')
        elif self.config.get('demo_mode', False):
            # Only use demo if explicitly enabled
            client = ShopifyClient('demo.myshopify.com', 'demo')
            products['shopify'] = client.fetch_products() or []
            fetched_ok.add('shopify')
        
        # Stripe - only if explicitly configured
        stripe_key = os.environ.get('STRIPE_SECRET_KEY')
        if stripe_key and stripe_key != 'demo':
            client = StripeClient(stripe_key)
            result = client.fetch_products()
            if result is None:
                pass
            else:
                products['stripe'] = result
                fetched_ok.add('stripe')
        
        # Gumroad - only if explicitly configured
        gumroad_token = os.environ.get('GUMROAD_ACCESS_TOKEN')
        if gumroad_token and gumroad_token != 'demo':
            client = GumroadClient(gumroad_token)
            result = client.fetch_products()
            if result is None:
                pass
            else:
                products['gumroad'] = result
                fetched_ok.add('gumroad')
        
        cached_products = self._cached_products()
        if cached_products is not None:
            # Restore per-source cache only after a hard fetch failure.
            # Successful empty catalogs must be allowed to clear stale PDPs.
            for source in ('shopify', 'stripe', 'gumroad'):
                if source in fetched_ok:
                    continue
                if cached_products.get(source):
                    products[source] = cached_products[source]

        if any(products.values()) or fetched_ok:
            self._save_cache(products)
        elif cached_products is not None:
            return cached_products
        
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
    
    def _current_store_host(self) -> str:
        return ProductSchema._normalize_store_host(
            os.environ.get('SHOPIFY_STORE_URL')
            or os.environ.get('SHOPIFY_STORE')
            or (self.config.get('shopify') or {}).get('store_url')
        )

    def _save_cache(self, products: Dict[str, Any]):
        """Save products to cache file"""
        store = self._current_store_host()
        cache_data = {
            'cached_at': datetime.now().isoformat(),
            'store_url': store or None,
            'products': products
        }
        self.products_cache_file.write_text(json.dumps(cache_data, indent=2))
    
    def load_cache(self) -> Optional[Dict[str, Any]]:
        """Load products from cache"""
        if self.products_cache_file.exists():
            try:
                return json.loads(self.products_cache_file.read_text())
            except Exception:
                return None
        return None
    
    def _cached_products(self) -> Optional[Dict[str, List[Dict[str, Any]]]]:
        cache = self.load_cache()
        if not cache:
            return None
        products = cache.get('products')
        if not isinstance(products, dict):
            return None
        if not any(products.get(source) for source in ('shopify', 'stripe', 'gumroad')):
            return None
        current_store = self._current_store_host()
        cached_store = ProductSchema._normalize_store_host(cache.get('store_url'))
        # Do not restore a foreign-store Shopify catalog after SHOPIFY_STORE_URL changes.
        shopify_products_raw = products.get('shopify', []) or []
        if (
            shopify_products_raw
            and current_store
            and cached_store
            and current_store.lower() != cached_store.lower()
        ):
            shopify_products_raw = []
        store = current_store or cached_store
        shopify_products = []
        for product in shopify_products_raw:
            if not isinstance(product, dict):
                continue
            enriched = dict(product)
            handle = enriched.get('handle')
            if handle and not enriched.get('url') and store:
                enriched['url'] = f"https://{store}/products/{handle}"
            shopify_products.append(enriched)
        stripe = products.get('stripe', [])
        gumroad = products.get('gumroad', [])
        if not isinstance(stripe, list):
            stripe = []
        if not isinstance(gumroad, list):
            gumroad = []
        restored = {
            'shopify': shopify_products,
            'stripe': [p for p in stripe if isinstance(p, dict)],
            'gumroad': [p for p in gumroad if isinstance(p, dict)],
        }
        if not any(restored.values()):
            return None
        return restored

