"""
GANG Product Aggregator
Fetch products from multiple platforms and normalize to Schema.org
"""

from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
import hashlib
import html
import json
import os
import re


def _plain_text(value: Any) -> str:
    text = re.sub(r'<[^>]*>', '', str(value or ''))
    text = re.sub(r'<[^>]*$', '', text)
    return html.unescape(text).strip()


def _checkout_origin_host() -> str:
    """First configured merchant host from SHOPIFY_STORE* or CHECKOUT_ORIGINS."""
    candidates = [
        os.environ.get('SHOPIFY_STORE_URL') or os.environ.get('SHOPIFY_STORE') or '',
    ]
    extra = os.environ.get('CHECKOUT_ORIGINS') or ''
    candidates.extend(re.split(r'[\s,]+', extra))
    for store in candidates:
        store = (store or '').strip()
        if not store:
            continue
        if not store.startswith('http'):
            store = f'https://{store}'
        parsed = urlparse(store)
        host = (parsed.netloc or '').split('@')[-1]
        if parsed.scheme in ('http', 'https') and host and host.lower() not in (
            'www.shopify.com', 'shopify.com'
        ):
            return host
    return ''


def numeric_variant_id(value: Any) -> str:
    """Shopify cart permalinks only accept numeric variant IDs, never SKUs."""
    if isinstance(value, bool):
        return ''
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value or '').strip()
    if re.fullmatch(r'\d+\.0+', text):
        text = text.split('.', 1)[0]
    return text if text.isdigit() else ''


def shopify_storefront_url(product: Dict[str, Any]) -> str:
    """Build a merchant product URL from handle + store host when Admin API omits it.

    Prefer the configured checkout host so custom-domain Admin URLs still match
    the deny-by-default allowlist (catalog JSON must not choose the origin).
    """
    try:
        from core.html_sanitize import safe_http_url
    except ImportError:
        from gang.core.html_sanitize import safe_http_url
    handle = product.get('handle') or ''
    host = _checkout_origin_host()
    if handle and host:
        return f"https://{host}/products/{handle}"
    existing = product.get('url') or ''
    if isinstance(existing, str):
        existing = safe_http_url(existing)
        if existing.startswith(('http://', 'https://')):
            return existing
    return existing if isinstance(existing, str) else ''


def _secret_fingerprint(value: str) -> str:
    """Short hash of a live credential so cache restore can detect rotation."""
    if not value or value == 'demo':
        return ''
    return hashlib.sha256(value.encode('utf-8')).hexdigest()[:16]


def commerce_cache_key() -> Dict[str, str]:
    """Fingerprint configured stores so cache restore cannot mix catalogs."""
    stripe = os.environ.get('STRIPE_SECRET_KEY') or ''
    gumroad = os.environ.get('GUMROAD_ACCESS_TOKEN') or ''
    shopify_token = os.environ.get('SHOPIFY_ACCESS_TOKEN') or ''
    return {
        'shopify_host': (_checkout_origin_host() or '').lower(),
        'shopify_token': _secret_fingerprint(shopify_token),
        'stripe': _secret_fingerprint(stripe),
        'gumroad': _secret_fingerprint(gumroad),
    }


def cache_source_allowed(cached: Optional[Dict[str, Any]], source: str) -> bool:
    """Reject restore when a recorded host or credential fingerprint no longer matches."""
    if not cached:
        return False
    recorded_keys = cached.get('cache_key') or {}
    current = commerce_cache_key()
    if source == 'shopify':
        recorded = (recorded_keys.get('shopify_host') or '').lower()
        current_host = current.get('shopify_host') or ''
        if not recorded or recorded != current_host:
            return False
        recorded_token = recorded_keys.get('shopify_token') or ''
        current_token = current.get('shopify_token') or ''
        # Legacy caches without a token fingerprint must not restore after rotation.
        if not recorded_token or recorded_token != current_token:
            return False
        return True
    if source in ('stripe', 'gumroad'):
        recorded = recorded_keys.get(source) or ''
        current_fp = current.get(source) or ''
        if recorded == '1':
            return False
        return bool(recorded) and recorded == current_fp
    return False


def coerce_available_flag(value: Any) -> Optional[bool]:
    """Parse Shopify/YAML availability; string 'false' must not become True."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ('true', '1', 'yes', 'on'):
            return True
        if text in (
            'false', '0', 'no', 'off', '',
            'outofstock', 'out_of_stock', 'soldout', 'sold_out',
            'unavailable', 'notinstock', 'not_in_stock',
        ):
            return False
        return None
    return None


def variant_in_stock(variant: Dict[str, Any]) -> bool:
    """Prefer Shopify's explicit `available` flag over stale inventory counts."""
    if not isinstance(variant, dict):
        return False
    available = coerce_available_flag(variant.get('available'))
    if available is not None:
        return available
    inventory_qty = variant.get('inventory_quantity', variant.get('inventoryQuantity', 0))
    try:
        inventory_qty = int(inventory_qty or 0)
    except (TypeError, ValueError):
        inventory_qty = 0
    inventory_management = variant.get('inventory_management')
    inventory_policy = variant.get('inventory_policy', 'deny')
    if inventory_management is None or inventory_management == '':
        return True
    if inventory_policy == 'continue':
        return True
    return inventory_qty > 0


def append_variant_query(product_url: str, variant_id: Any) -> str:
    """Append ?variant= without breaking an existing query string."""
    vid = numeric_variant_id(variant_id)
    if not product_url or not vid:
        return product_url
    parsed = urlparse(product_url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query['variant'] = vid
    return urlunparse(parsed._replace(query=urlencode(query)))


def _safe_http_url(value: Any) -> str:
    try:
        from core.html_sanitize import safe_http_url
    except ImportError:
        from gang.core.html_sanitize import safe_http_url
    return safe_http_url(value)


def _safe_image_urls(raw_images: Any) -> List[str]:
    """Keep only http(s) or root-relative image URLs from platform payloads."""
    if isinstance(raw_images, str):
        raw_images = [raw_images]
    if not isinstance(raw_images, list):
        return []
    images = []
    for img in raw_images:
        src = ''
        if isinstance(img, dict):
            src = img.get('src') or img.get('url') or ''
        elif isinstance(img, str):
            src = img
        url = _safe_http_url(src)
        if url:
            images.append(url)
    return images


def commerce_slug(*candidates: Any) -> str:
    """Safe public slug from platform id/name/handle."""
    for raw in candidates:
        text = str(raw or '').strip()
        if not text:
            continue
        slug = re.sub(r'[^A-Za-z0-9._-]+', '-', text).strip('-_.')[:128]
        if slug and re.match(r'^[A-Za-z0-9]', slug):
            return slug
    return ''


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
        variants = product.get('variants') or []
        if not isinstance(variants, list):
            variants = []
        first_variant = variants[0] if variants and isinstance(variants[0], dict) else {}
        
        images = _safe_image_urls(product.get('images') or [])
        
        currency = os.environ.get('SHOPIFY_CURRENCY') or 'USD'
        product_url = shopify_storefront_url(product)
        
        offers = []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            inventory_qty = variant.get('inventory_quantity', variant.get('inventoryQuantity', 0))
            try:
                inventory_qty = int(inventory_qty or 0)
            except (TypeError, ValueError):
                inventory_qty = 0
            in_stock = variant_in_stock(variant)
            
            price = variant.get('price')
            if price is None or price == '':
                price = '0'
            
            variant_id = variant.get('id', '')
            offer_url = append_variant_query(product_url, variant_id)
            
            offers.append({
                '@type': 'Offer',
                'price': str(price),
                'priceCurrency': currency,
                'availability': 'https://schema.org/InStock' if in_stock else 'https://schema.org/OutOfStock',
                'url': offer_url,
                'sku': variant.get('sku') or '',
                'name': variant.get('title') or '',
                'id': variant_id,
                'inventory_quantity': inventory_qty,
                'option1': variant.get('option1') or '',
                'option2': variant.get('option2') or '',
                'option3': variant.get('option3') or '',
            })
        
        default_offer = {
            '@type': 'Offer',
            'price': str(first_variant.get('price') or '0'),
            'priceCurrency': currency,
            'availability': 'https://schema.org/OutOfStock'
        }
        
        return {
            '@context': 'https://schema.org',
            '@type': 'Product',
            'name': product.get('title', ''),
            'description': _plain_text(product.get('body_html') or ''),
            'image': images,
            'offers': offers if len(offers) > 1 else (offers[0] if offers else default_offer),
            'sku': first_variant.get('sku') or '',
            'brand': {
                '@type': 'Brand',
                'name': product.get('vendor') or ''
            },
            'category': product.get('product_type') or '',
            '_meta': {
                'source': 'shopify',
                'id': product.get('id'),
                'handle': product.get('handle'),
                'url': product_url,
                'variants': variants,
                'created_at': product.get('created_at'),
                'updated_at': product.get('updated_at')
            }
        }
    
    @staticmethod
    def _from_stripe(product: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Stripe product to Schema.org"""
        prices = product.get('prices') or []
        if not isinstance(prices, list):
            prices = [prices] if isinstance(prices, dict) else []
        first_price = prices[0] if prices and isinstance(prices[0], dict) else {}
        unit_amount = first_price.get('unit_amount') or 0
        try:
            price = str(int(unit_amount) / 100)
        except (TypeError, ValueError):
            price = '0'
        currency = (first_price.get('currency') or 'usd')
        if not isinstance(currency, str):
            currency = 'usd'
        
        return {
            '@context': 'https://schema.org',
            '@type': 'Product',
            'name': product.get('name', ''),
            'description': product.get('description', ''),
            'image': _safe_image_urls(product.get('images') or []),
            'offers': {
                '@type': 'Offer',
                'price': price,
                'priceCurrency': currency.upper(),
                'availability': (
                    'https://schema.org/InStock'
                    if coerce_available_flag(product.get('active')) is True
                    else 'https://schema.org/OutOfStock'
                )
            },
            '_meta': {
                'source': 'stripe',
                'id': product.get('id'),
                'handle': commerce_slug(product.get('metadata', {}).get('handle') if isinstance(product.get('metadata'), dict) else '', product.get('id'), product.get('name')),
                'slug': commerce_slug(product.get('metadata', {}).get('handle') if isinstance(product.get('metadata'), dict) else '', product.get('id'), product.get('name')),
                'url': _safe_http_url(product.get('url')),
                'prices': prices,
                'created': product.get('created'),
                'updated': product.get('updated')
            }
        }
    
    @staticmethod
    def _from_gumroad(product: Dict[str, Any]) -> Dict[str, Any]:
        """Convert Gumroad product to Schema.org"""
        raw_price = product.get('price') or 0
        try:
            if isinstance(raw_price, str) and '.' in raw_price.strip():
                gumroad_price = str(float(raw_price))
            elif isinstance(raw_price, float) and not raw_price.is_integer():
                gumroad_price = str(raw_price)
            else:
                gumroad_price = str(int(raw_price) / 100)
        except (TypeError, ValueError):
            gumroad_price = '0'
        return {
            '@context': 'https://schema.org',
            '@type': 'Product',
            'name': product.get('name', ''),
            'description': product.get('description', ''),
            'image': _safe_image_urls(product.get('thumbnail_url')),
            'offers': {
                '@type': 'Offer',
                'price': gumroad_price,
                'priceCurrency': str(product.get('currency') or 'USD').upper(),
                'availability': (
                    'https://schema.org/InStock'
                    if coerce_available_flag(product.get('published')) is True
                    else 'https://schema.org/OutOfStock'
                )
            },
            '_meta': {
                'source': 'gumroad',
                'id': product.get('id'),
                'handle': commerce_slug(product.get('custom_permalink'), product.get('id'), product.get('name')),
                'slug': commerce_slug(product.get('custom_permalink'), product.get('id'), product.get('name')),
                'url': _safe_http_url(product.get('short_url')),
                'created_at': product.get('created_at')
            }
        }


class ShopifyClient:
    """Shopify Storefront API client"""
    
    def __init__(self, store_url: str, access_token: str):
        cleaned = (store_url or '').replace('https://', '').replace('http://', '')
        host_part, sep, rest = cleaned.partition('/')
        host_part = host_part.split('@')[-1]
        self.store_url = f"{host_part}{sep}{rest}" if sep else host_part
        self.access_token = access_token
        self.api_version = '2024-01'
    
    def fetch_products(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Fetch products from Shopify"""
        # Demo mode - return mock data
        if not self.access_token or self.access_token == 'demo':
            return self._demo_products()
        
        try:
            import requests

            store_host = self.store_url.split('/')[0].split('?')[0].split('@')[-1].lower()
            headers = {
                'X-Shopify-Access-Token': self.access_token,
                'Content-Type': 'application/json'
            }
            page_limit = min(max(int(limit or 100), 1), 250)
            url = f"https://{store_host}/admin/api/{self.api_version}/products.json"
            params = {'limit': page_limit}
            products: List[Dict[str, Any]] = []
            seen_ids = set()
            for _ in range(20):
                response = requests.get(url, headers=headers, params=params, timeout=30)
                response.raise_for_status()
                page = (response.json() or {}).get('products') or []
                for product in page:
                    if not isinstance(product, dict):
                        continue
                    product_id = product.get('id')
                    if product_id is not None:
                        if product_id in seen_ids:
                            continue
                        seen_ids.add(product_id)
                    handle = product.get('handle')
                    if handle and not product.get('url'):
                        product['url'] = f"https://{store_host}/products/{handle}"
                    products.append(product)
                next_link = ((response.links or {}).get('next') or {}).get('url')
                if not next_link:
                    break
                parsed = urlparse(next_link)
                if parsed.scheme != 'https' or (parsed.hostname or '').lower() != store_host:
                    break
                url = next_link
                params = None
            return products
        
        except Exception as e:
            print(f"Error fetching from Shopify: {e}")
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
    
    def fetch_products(self) -> List[Dict[str, Any]]:
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
            
            data = response.json()
            if not isinstance(data, dict) or data.get('success') is not True:
                return None
            return data.get('products') or []
        
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
        live_configured = False
        fetched_ok = set()
        
        shopify_url = os.environ.get('SHOPIFY_STORE_URL') or os.environ.get('SHOPIFY_STORE')
        shopify_token = os.environ.get('SHOPIFY_ACCESS_TOKEN')
        configured = set()
        if shopify_url and shopify_token and shopify_token != 'demo':
            live_configured = True
            configured.add('shopify')
            client = ShopifyClient(shopify_url, shopify_token)
            fetched = client.fetch_products()
            if fetched is not None:
                products['shopify'] = fetched
                fetched_ok.add('shopify')
        elif self.config.get('demo_mode', False):
            configured.add('shopify')
            client = ShopifyClient('demo.myshopify.com', 'demo')
            products['shopify'] = client.fetch_products() or []
            fetched_ok.add('shopify')
        
        stripe_key = os.environ.get('STRIPE_SECRET_KEY')
        if stripe_key and stripe_key != 'demo':
            live_configured = True
            configured.add('stripe')
            client = StripeClient(stripe_key)
            fetched = client.fetch_products()
            if fetched is not None:
                products['stripe'] = fetched
                fetched_ok.add('stripe')
        
        gumroad_token = os.environ.get('GUMROAD_ACCESS_TOKEN')
        if gumroad_token and gumroad_token != 'demo':
            live_configured = True
            configured.add('gumroad')
            client = GumroadClient(gumroad_token)
            fetched = client.fetch_products()
            if fetched is not None:
                products['gumroad'] = fetched
                fetched_ok.add('gumroad')
        
        # Restore cache when nothing is configured, or when a live fetch failed.
        # products is pre-keyed, so "source not in products" never restores.
        # Demo mode must keep the demo catalog even when a stale live cache exists.
        cached = self.load_cache()
        if self.config.get('demo_mode', False) and not live_configured:
            return products
        if cached and cached.get('products'):
            if not live_configured:
                # Demo/empty tokens with a leftover store host must not restore
                # that platform's stale live catalog (checkout-origin-only setup).
                disabled = set()
                if shopify_url and (not shopify_token or shopify_token == 'demo'):
                    disabled.add('shopify')
                if stripe_key == 'demo':
                    disabled.add('stripe')
                if gumroad_token == 'demo':
                    disabled.add('gumroad')
                restored: Dict[str, Any] = {}
                for source, items in cached['products'].items():
                    if source in disabled:
                        continue
                    if cache_source_allowed(cached, source):
                        restored[source] = items if isinstance(items, list) else []
                return restored or products
            for source, items in cached['products'].items():
                # Restore configured sources that failed, or that succeeded
                # with an empty list (transient empty responses must not
                # wipe a previously good catalog).
                cached_items = items if isinstance(items, list) else []
                if source not in configured or not cache_source_allowed(cached, source):
                    continue
                if source not in fetched_ok:
                    products[source] = cached_items
                elif not products.get(source) and cached_items:
                    products[source] = cached_items
        
        has_products = any(products.get(source) for source in products)
        if has_products or fetched_ok:
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
                if source == 'shopify' and isinstance(product, dict) and not product.get('url'):
                    product = dict(product)
                    product['url'] = shopify_storefront_url(product)
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
            'cache_key': commerce_cache_key(),
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

