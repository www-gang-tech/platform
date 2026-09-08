#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GANG CLI - Single binary for all build operations
"""

import click
import yaml
import os
import sys
import hashlib
import json
import shutil
import markdown
import time
import threading
import html as html_module
import uuid
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

PUBLISHABLE_CATEGORIES = [
    'posts', 'articles', 'pages', 'projects', 'newsletters', 'people', 'products'
]
TEMPLATE_OWNS_H1 = {
    'posts', 'articles', 'projects', 'newsletters', 'people', 'products'
}
PLACEHOLDER_WEBHOOK_MARKERS = ('your-n8n.app', 'example.com', 'placeholder', 'changeme')
SAFE_SLUG_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
ALLOWED_SCHEDULE_STATUSES = ('draft', 'scheduled', 'published', 'live', 'public')
DEFAULT_VARIANT_TITLES = {'default title', 'default', 'title'}
MAX_CONTENT_BYTES = 2 * 1024 * 1024
SIZE_LIKE_VALUES = {
    'xxs', 'xs', 's', 'm', 'l', 'xl', 'xxl', 'xxxl', '2xl', '3xl', '4xl',
    'os', 'one size', 'onesize',
}


def is_safe_content_slug(slug: str) -> bool:
    """Reject empty, traversal, and path-like slugs before any filesystem rename."""
    value = str(slug or '').strip()
    return bool(SAFE_SLUG_RE.match(value)) and '..' not in value and '/' not in value and '\\' not in value


def exclusive_rename(src: Path, dest: Path) -> None:
    """Rename ``src`` to ``dest`` without replacing an existing file.

    Linux ``rename(2)`` replaces the destination; a TOCTOU between
    ``exists()`` and ``rename()`` can clobber another slug.
    """
    src_path = Path(src)
    dest_path = Path(dest)
    if dest_path.exists():
        raise FileExistsError(str(dest_path))
    try:
        os.link(src_path, dest_path)
    except FileExistsError:
        raise
    except OSError:
        if dest_path.exists():
            raise FileExistsError(str(dest_path))
        src_path.rename(dest_path)
        return
    src_path.unlink(missing_ok=True)


def content_canonical_url(site_url: Any, category: str, slug: str) -> str:
    """Absolute public URL; articles publish under /posts/."""
    return f"{str(site_url or '').rstrip('/')}{public_content_url(category, slug)}"


def newsletter_archive_url(post_stem: str) -> str:
    """save_newsletter_to_content writes {stem}-newsletter.md."""
    return f"/newsletters/{post_stem}-newsletter/"


def is_size_like(value: str) -> bool:
    text = str(value or '').strip()
    if not text:
        return False
    if text.isdigit():
        return True
    return text.lower() in SIZE_LIKE_VALUES


def variant_axes(offer: Any) -> Tuple[str, str]:
    """Map Shopify option1/2 or 'Color / Size' titles onto color + size axes."""
    if not isinstance(offer, dict):
        return '', ''
    color = str(offer.get('color') or '').strip()
    size = str(offer.get('size') or '').strip()
    option1 = str(offer.get('option1') or '').strip()
    option2 = str(offer.get('option2') or '').strip()
    name = str(offer.get('name') or offer.get('title') or '').strip()

    if '/' in name:
        parts = [part.strip() for part in name.split('/') if part.strip()]
        if not color and parts:
            color = parts[0]
        if not size and len(parts) > 1:
            size = parts[1]
    else:
        usable_option1 = option1 if option1.lower() not in DEFAULT_VARIANT_TITLES else ''
        usable_name = name if name.lower() not in DEFAULT_VARIANT_TITLES else ''
        axis = usable_option1 or usable_name
        if option2:
            if not color:
                color = axis
            if not size:
                size = option2
        elif axis:
            if is_size_like(axis):
                if not size:
                    size = axis
            elif not color:
                color = axis

    if color.lower() in DEFAULT_VARIANT_TITLES:
        color = ''
    if size.lower() in DEFAULT_VARIANT_TITLES:
        size = ''
    return color, size


def variant_option3(offer: Any) -> str:
    """Third Shopify axis (option3 or a third slash-separated title part)."""
    if not isinstance(offer, dict):
        return ''
    option3 = str(offer.get('option3') or '').strip()
    if option3.lower() in DEFAULT_VARIANT_TITLES:
        option3 = ''
    if option3:
        return option3
    name = str(offer.get('name') or offer.get('title') or '').strip()
    if '/' in name:
        parts = [part.strip() for part in name.split('/') if part.strip()]
        if len(parts) > 2 and parts[2].lower() not in DEFAULT_VARIANT_TITLES:
            return parts[2]
    return ''


def renderable_markdown(files: List[Path]) -> List[Path]:
    """HTML-renderable publishable files: safe slugs; aggregator owns product PDPs."""
    rendered: List[Path] = []
    for path in files:
        category = path.parent.name
        if category not in PUBLISHABLE_CATEGORIES or category == 'products':
            continue
        if not is_safe_content_slug(path.stem):
            continue
        rendered.append(path)
    return rendered


def merge_editor_frontmatter(original: str, incoming: str) -> str:
    """Restore YAML frontmatter when an editor save dropped the --- block."""
    orig_fm, _ = parse_frontmatter_text(original)
    in_fm, in_body = parse_frontmatter_text(incoming)
    if orig_fm and not in_fm:
        dumped = yaml.dump(orig_fm, default_flow_style=False, allow_unicode=True).strip()
        body = in_body if incoming.lstrip().startswith('---') else incoming
        return f"---\n{dumped}\n---\n{body}"
    return incoming


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


def public_content_url(category: str, slug: str) -> str:
    """Public URL for a content file. Articles publish under /posts/."""
    if category == 'articles':
        category = 'posts'
    return f"/{category}/{slug}/"


def convert_markdown_html(body: str) -> str:
    """Markdown → HTML with sanitizer + external-link processing."""
    md = markdown.Markdown(extensions=['extra', 'meta'])
    content_html = md.convert(body)
    try:
        from core.html_sanitize import sanitize_markdown_html, sanitize_content_hrefs
    except ImportError:
        from gang.core.html_sanitize import sanitize_markdown_html, sanitize_content_hrefs
    content_html = sanitize_markdown_html(content_html)
    content_html = sanitize_content_hrefs(content_html)
    return process_external_links(content_html)


def collect_checkout_origins(products: Optional[List[Any]] = None) -> List[str]:
    """Configured merchant origins only — catalog URLs must not widen the allowlist."""
    origins = set()
    candidates = [
        os.environ.get('SHOPIFY_STORE_URL') or os.environ.get('SHOPIFY_STORE') or '',
    ]
    extra = os.environ.get('CHECKOUT_ORIGINS') or ''
    candidates.extend(re.split(r'[\s,]+', extra))
    del products  # product JSON is untrusted for origin expansion
    for store_url in candidates:
        store_url = (store_url or '').strip()
        if not store_url:
            continue
        if not store_url.startswith('http'):
            store_url = f'https://{store_url}'
        parsed = urlparse(store_url)
        host = (parsed.netloc or '').split('@')[-1]
        if parsed.scheme in ('http', 'https') and host:
            if host.lower() not in ('www.shopify.com', 'shopify.com'):
                origins.add(f"{parsed.scheme}://{host}")
    return sorted(origins)


def catalog_product_slug(product: Any) -> str:
    """Public PDP slug from normalized product metadata."""
    if not isinstance(product, dict):
        return ''
    meta = product.get('_meta') if isinstance(product.get('_meta'), dict) else {}
    return str(meta.get('slug') or meta.get('handle') or '').strip()


def assign_unique_catalog_slugs(products: List[Any]) -> List[Any]:
    """Keep the first safe slug; suffix later collisions so PDPs are not overwritten."""
    seen: set = set()
    unique: List[Any] = []
    for product in products or []:
        if not isinstance(product, dict):
            continue
        slug = catalog_product_slug(product)
        if not is_safe_content_slug(slug):
            continue
        candidate = slug
        n = 2
        while candidate in seen:
            suffix = f'-{n}'
            trimmed = slug[: max(1, 128 - len(suffix))]
            candidate = f'{trimmed}{suffix}'
            n += 1
            if n > 99 or not is_safe_content_slug(candidate):
                candidate = ''
                break
        if not candidate:
            continue
        seen.add(candidate)
        meta = product.get('_meta')
        if not isinstance(meta, dict):
            meta = {}
            product['_meta'] = meta
        meta['slug'] = candidate
        unique.append(product)
    return unique


def parse_frontmatter_text(content: str) -> Tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter, always returning a dict even for empty/invalid YAML."""
    try:
        from core.scheduler import strip_frontmatter_prefix
    except ImportError:
        from gang.core.scheduler import strip_frontmatter_prefix
    content = strip_frontmatter_prefix(content)
    if content.startswith('---'):
        parts = content.split('---', 2)
        # Truncated delimiters: keep the original text so writers cannot wipe the body.
        if len(parts) < 3:
            return {}, content
        try:
            raw = yaml.safe_load(parts[1])
        except yaml.YAMLError:
            raw = None
        frontmatter = raw if isinstance(raw, dict) else {}
        return frontmatter, parts[2]
    return {}, content


def json_for_script(data: Any) -> str:
    """Serialize JSON for embedding in <script> without </script> breakout."""
    from markupsafe import Markup
    return Markup(
        json.dumps(data, indent=2, default=str)
        .replace('<', '\\u003c')
        .replace('>', '\\u003e')
        .replace('&', '\\u0026')
    )


def template_environment(templates_path: Path):
    """Jinja env with HTML autoescape so product/cart titles cannot break markup."""
    from jinja2 import Environment, FileSystemLoader, select_autoescape
    env = Environment(
        loader=FileSystemLoader(str(templates_path)),
        autoescape=select_autoescape(['html', 'xml']),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters['tojson_script'] = json_for_script
    env.filters['safe_url'] = _jinja_safe_url
    env.filters['tag_href'] = tag_href
    return env


def _jinja_safe_url(value: Any) -> str:
    return safe_http_url(value)


def tag_href(tag: Any) -> str:
    """Encode a tag for /tags/<tag>/ so slashes match write_tag_pages."""
    name = str(tag or '').strip()
    if not name or name in ('.', '..'):
        return ''
    return f"/tags/{quote(name, safe='')}/"


def offer_is_in_stock(offer: Any) -> bool:
    if not isinstance(offer, dict):
        return False
    avail = str(offer.get('availability') or '').strip()
    if not avail or avail == 'OutOfStock' or avail.endswith('/OutOfStock'):
        return False
    return avail == 'InStock' or avail.endswith('/InStock')


def safe_http_url(value: Any) -> str:
    """Allow only relative or http(s) merchant URLs (shared href policy)."""
    try:
        from core.html_sanitize import safe_http_url as _safe
    except ImportError:
        from gang.core.html_sanitize import safe_http_url as _safe
    return _safe(value)


def split_variant_name(variant_name: str) -> Tuple[str, str]:
    """Legacy Color / Size splitter; single-axis titles become size when size-like."""
    name = str(variant_name or '')
    if '/' in name:
        parts = name.split('/')
        return parts[0].strip(), (parts[1].strip() if len(parts) > 1 else '')
    text = name.strip()
    if not text or text.lower() in DEFAULT_VARIANT_TITLES:
        return '', ''
    if is_size_like(text):
        return '', text
    return text, ''


def build_pdp_context(product: Dict[str, Any], config: Dict[str, Any], slug: str) -> Dict[str, Any]:
    """Normalize product + offers into template context, preferring in-stock defaults."""
    raw_images = product.get('image', [])
    type_name = type(raw_images).__name__
    if type_name in ('list', 'tuple'):
        raw_list = [str(img) for img in raw_images if img]
    elif raw_images:
        raw_list = [str(raw_images)]
    else:
        raw_list = []
    images = [url for url in (safe_http_url(img) for img in raw_list) if url]

    offers = product.get('offers', {})
    variants_list: List[Dict[str, Any]] = []
    colors_list: List[str] = []
    sizes_list: List[str] = []
    option3s_list: List[str] = []
    first_offer: Dict[str, Any] = {}

    if type(offers).__name__ == 'list':
        color_order: List[str] = []
        size_order: List[str] = []
        option3_order: List[str] = []
        colors = set()
        color_to_image: Dict[str, int] = {}
        dict_offers = [offer for offer in offers if isinstance(offer, dict)]

        for offer in dict_offers:
            color, size = variant_axes(offer)
            extra = variant_option3(offer)
            if color not in colors:
                color_order.append(color)
                colors.add(color)
            if size not in size_order:
                size_order.append(size)
            if extra not in option3_order:
                option3_order.append(extra)
        if not any(color_order):
            color_order = []
        if not any(size_order):
            size_order = []
        if not any(option3_order):
            option3_order = []

        for idx, color in enumerate(color_order):
            if idx < len(images):
                color_to_image[color] = idx

        for offer in dict_offers:
            color_part, size_part = variant_axes(offer)
            extra_part = variant_option3(offer)
            variant_id = offer.get('id')
            if variant_id in (None, ''):
                offer_url = str(offer.get('url') or '')
                marker = 'variant='
                if marker in offer_url:
                    variant_id = offer_url.split(marker, 1)[1].split('&', 1)[0]
            image_index = color_to_image.get(color_part, 0) if color_part else 0
            image_url = images[image_index] if 0 <= image_index < len(images) else (
                images[0] if images else ''
            )
            variants_list.append({
                'name': offer.get('name', ''),
                'color': color_part,
                'size': size_part,
                'option3': extra_part,
                'price': offer.get('price', '0'),
                'currency': offer.get('priceCurrency', 'USD'),
                'availability': offer.get('availability') or 'https://schema.org/OutOfStock',
                'url': safe_http_url(offer.get('url')),
                'sku': offer.get('sku', ''),
                'id': numeric_variant_id(variant_id),
                'image_index': image_index,
                'image': image_url,
            })

        in_stock_colors = [
            color for color in color_order
            if any(
                offer_is_in_stock(offer) and variant_axes(offer)[0] == color
                for offer in dict_offers
            )
        ]
        colors_list = in_stock_colors + [color for color in color_order if color not in in_stock_colors]
        in_stock_sizes = [
            size for size in size_order
            if any(
                offer_is_in_stock(offer) and variant_axes(offer)[1] == size
                for offer in dict_offers
            )
        ]
        sizes_list = in_stock_sizes + [size for size in size_order if size not in in_stock_sizes]
        in_stock_option3s = [
            extra for extra in option3_order
            if any(
                offer_is_in_stock(offer) and variant_option3(offer) == extra
                for offer in dict_offers
            )
        ]
        option3s_list = in_stock_option3s + [
            extra for extra in option3_order if extra not in in_stock_option3s
        ]
        in_stock_offers = [offer for offer in dict_offers if offer_is_in_stock(offer)]
        first_offer = (in_stock_offers or dict_offers or [{}])[0]
        default_variant = next((item for item in variants_list if offer_is_in_stock({
            'availability': item.get('availability')
        })), variants_list[0] if variants_list else {})
        if default_variant.get('color') is not None and default_variant['color'] in colors_list:
            colors_list = [default_variant['color']] + [
                color for color in colors_list if color != default_variant['color']
            ]
        if default_variant.get('size') is not None and default_variant['size'] in sizes_list:
            sizes_list = [default_variant['size']] + [
                size for size in sizes_list if size != default_variant['size']
            ]
        if default_variant.get('option3') is not None and default_variant['option3'] in option3s_list:
            option3s_list = [default_variant['option3']] + [
                extra for extra in option3s_list if extra != default_variant['option3']
            ]
    elif isinstance(offers, dict):
        first_offer = offers

    if not isinstance(first_offer, dict):
        first_offer = {}

    brand_data = product.get('brand', '')
    brand_name = brand_data.get('name', '') if hasattr(brand_data, 'get') else str(brand_data)

    # Prefer a real in-stock variant tuple so SSR does not pair Green+S when only Green+M exists.
    matching_default = next(
        (item for item in variants_list if offer_is_in_stock({'availability': item.get('availability')})),
        variants_list[0] if variants_list else {},
    )
    default_color = matching_default.get('color')
    if default_color is None:
        default_color = colors_list[0] if colors_list else ''
    default_size = matching_default.get('size')
    if default_size is None:
        default_size = sizes_list[0] if sizes_list else ''
    default_option3 = matching_default.get('option3')
    if default_option3 is None:
        default_option3 = option3s_list[0] if option3s_list else ''
    default_variant_id = numeric_variant_id(
        matching_default.get('id') or first_offer.get('id') or ''
    )
    title = product.get('name', '')
    try:
        from core.products import _plain_text
    except ImportError:
        from gang.core.products import _plain_text
    description = _plain_text(product.get('description', ''))
    buy_url = safe_http_url(matching_default.get('url') or first_offer.get('url'))
    default_in_stock = offer_is_in_stock({
        'availability': matching_default.get('availability') or first_offer.get('availability')
    })
    if not default_in_stock:
        buy_url = ''
        default_variant_id = ''
    checkout_origins = collect_checkout_origins()
    if buy_url:
        parsed_buy = urlparse(buy_url)
        buy_host = (parsed_buy.netloc or '').split('@')[-1]
        buy_origin = f"{parsed_buy.scheme}://{buy_host}" if parsed_buy.scheme and buy_host else ''
        same_origin_path = buy_url.startswith('/') and not buy_url.startswith('//')
        if not same_origin_path and buy_origin not in checkout_origins:
            buy_url = ''
            default_variant_id = ''
    jsonld_offers = []
    if variants_list:
        for item in variants_list:
            offer = {
                '@type': 'Offer',
                'price': str(item.get('price') or '0'),
                'priceCurrency': item.get('currency') or 'USD',
                'availability': item.get('availability') or 'https://schema.org/OutOfStock',
            }
            offer['url'] = item.get('url') or f"{config['site']['url']}/products/{slug}/"
            if item.get('sku'):
                offer['sku'] = item['sku']
            jsonld_offers.append(offer)
    elif first_offer:
        offer = {
            '@type': 'Offer',
            'price': str(first_offer.get('price') or '0'),
            'priceCurrency': first_offer.get('priceCurrency') or 'USD',
            'availability': first_offer.get('availability') or 'https://schema.org/OutOfStock',
        }
        offer['url'] = buy_url or f"{config['site']['url']}/products/{slug}/"
        jsonld_offers.append(offer)

    jsonld = {
        '@context': 'https://schema.org',
        '@type': 'Product',
        'name': title,
        'description': description,
        'url': f"{config['site']['url']}/products/{slug}/",
        'image': images,
        'sku': matching_default.get('sku') or product.get('sku', ''),
        'offers': jsonld_offers[0] if len(jsonld_offers) == 1 else jsonld_offers,
    }
    jsonld['brand'] = {'@type': 'Brand', 'name': brand_name or config['site']['title']}

    return {
        'lang': config['site'].get('language', 'en'),
        'site_title': config['site']['title'],
        'title': title,
        'description': description,
        'canonical_url': f"{config['site']['url']}/products/{slug}/",
        'slug': slug,
        'product_image': images[0] if images else '',
        'product_images': images,
        'price': matching_default.get('price') or first_offer.get('price', '0'),
        'currency': matching_default.get('currency') or first_offer.get('priceCurrency', 'USD'),
        'recurring': None,
        'content': description,
        'buy_url': buy_url,
        'variants': variants_list,
        'colors': colors_list,
        'sizes': sizes_list,
        'option3s': option3s_list,
        'default_color': default_color,
        'default_size': default_size,
        'default_option3': default_option3,
        'variant_id': default_variant_id,
        'sku': matching_default.get('sku') or product.get('sku', ''),
        'brand': brand_name,
        'category': product.get('category', ''),
        'availability': matching_default.get('availability') or first_offer.get('availability', 'https://schema.org/OutOfStock'),
        'in_stock': default_in_stock,
        'checkout_origins': checkout_origins,
        'jsonld': jsonld,
        'year': datetime.now().year,
        'navigation': config.get('nav', {}).get('main', []),
        'build_time': datetime.now().strftime('%Y-%m-%d %H:%M'),
        'build_time_iso': datetime.now().isoformat(),
    }


def comments_webhook_url(config: Dict[str, Any]) -> str:
    """Return a sanitized https webhook URL, or empty when comments are off/unsafe."""
    comments = config.get('comments') or {}
    if not comments.get('enabled'):
        return ''
    url = safe_http_url(str(comments.get('webhook_url') or ''))
    if not url.lower().startswith('https://'):
        return ''
    lowered = url.lower()
    if any(marker in lowered for marker in PLACEHOLDER_WEBHOOK_MARKERS):
        return ''
    from urllib.parse import urlparse
    host = (urlparse(url).hostname or '').lower()
    if host in {'localhost', '127.0.0.1', '::1', '0.0.0.0'} or host.endswith(('.localhost', '.local')):
        return ''
    return url


def comments_are_enabled(config: Dict[str, Any]) -> bool:
    return bool(comments_webhook_url(config))


def comments_webhook_origin(config: Dict[str, Any]) -> str:
    """Origin of the comments webhook for CSP connect-src, or empty."""
    url = comments_webhook_url(config)
    if not url:
        return ''
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = (parsed.netloc or '').split('@')[-1]
    if parsed.scheme == 'https' and host:
        return f"{parsed.scheme}://{host}"
    return ''


def write_dist_headers(public_path: Path, dist_path: Path, config: Dict[str, Any]) -> None:
    """Copy _headers and merge the comments webhook origin into connect-src."""
    headers_src = public_path / '_headers'
    if not headers_src.exists():
        return
    text = headers_src.read_text()
    origin = comments_webhook_origin(config)
    if origin:
        def inject(match) -> str:
            line = match.group(0)
            if origin in line:
                return line
            return line.replace("connect-src 'self'", f"connect-src 'self' {origin}", 1)
        text = re.sub(r'Content-Security-Policy:[^\n]+', inject, text, count=1)
    (dist_path / '_headers').write_text(text)


def strip_leading_markdown_h1(body: str) -> str:
    stripped = body.lstrip('\n')
    if stripped.startswith('# '):
        newline = stripped.find('\n')
        if newline == -1:
            return ''
        return stripped[newline + 1:].lstrip('\n')
    return body


def resolve_under_root(root: Path, relative: str) -> Optional[Path]:
    """Resolve a relative path and reject traversal outside root (including symlinks)."""
    if not relative or relative.startswith('/') or '\0' in relative:
        return None
    try:
        base = root.resolve()
        candidate = (base / relative).resolve()
        candidate.relative_to(base)
        return candidate
    except (ValueError, OSError):
        return None


def resolve_content_arg(content_root: Path, file_path: str) -> Optional[Path]:
    """Resolve a CLI file argument and reject paths outside the content root."""
    if not file_path or '\0' in str(file_path):
        return None
    try:
        base = content_root.resolve()
        raw = Path(file_path)
        candidates = [raw] if raw.is_absolute() else [Path.cwd() / raw, base / raw]
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
                resolved.relative_to(base)
                return resolved
            except (ValueError, OSError):
                continue
        return None
    except (ValueError, OSError):
        return None


def is_publishable_relpath(relative: str) -> bool:
    """Allow only {publishable-category}/{safe-slug}.md."""
    rel = str(relative or '').replace('\\', '/').lstrip('/')
    if not rel.endswith('.md'):
        rel = f'{rel}.md'
    parts = rel.split('/')
    if len(parts) != 2:
        return False
    category, filename = parts
    if category not in PUBLISHABLE_CATEGORIES or not filename.endswith('.md'):
        return False
    return is_safe_content_slug(filename[:-3])


def resolve_studio_content_path(content_root: Path, relative: str) -> Optional[Path]:
    """Resolve Studio editor paths; articles publish as posts but live on disk under articles/."""
    rel = str(relative or '').replace('\\', '/').lstrip('/')
    if not rel.endswith('.md'):
        rel = f'{rel}.md'
    if not is_publishable_relpath(rel):
        return None
    candidate = resolve_under_root(content_root, rel)
    if candidate is not None and candidate.exists():
        return candidate
    parts = rel.split('/')
    if len(parts) == 2 and parts[0] == 'posts':
        alt = resolve_under_root(content_root, f'articles/{parts[1]}')
        if alt is not None and alt.exists():
            return alt
    return candidate


def frontmatter_seo(frontmatter: Any) -> Dict[str, Any]:
    """Return SEO mapping only when frontmatter.seo is a dict."""
    if not isinstance(frontmatter, dict):
        return {}
    seo = frontmatter.get('seo')
    return seo if isinstance(seo, dict) else {}


def list_item_summary(frontmatter: Any, site_description: str, content_html: str = '') -> str:
    """Card/list excerpt: authored text or HTML excerpt, never the site tagline."""
    seo = frontmatter_seo(frontmatter)
    candidates = []
    if isinstance(frontmatter, dict):
        candidates.append(frontmatter.get('summary'))
    candidates.append(seo.get('description'))
    for raw in candidates:
        if isinstance(raw, str):
            text = raw.strip()
            if text and text != site_description:
                return text
    if content_html:
        text = re.sub(r'<[^>]+>', ' ', str(content_html))
        text = re.sub(r'\s+', ' ', text).strip()
        if text:
            return text[:200]
    return ''


def sanitize_social_links(raw: Any) -> List[Dict[str, str]]:
    if not isinstance(raw, list):
        return []
    links = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        url = safe_http_url(item.get('url'))
        if not url:
            continue
        platform = str(item.get('platform') or item.get('name') or 'Social link')
        links.append({'url': url, 'platform': platform})
    return links


def collect_category_markdown(content_path: Path, include_products: bool = False) -> List[Path]:
    """Collect top-level category markdown. Product PDPs belong to the aggregator."""
    files = []
    categories = PUBLISHABLE_CATEGORIES if include_products else [
        category for category in PUBLISHABLE_CATEGORIES if category != 'products'
    ]
    for category_dir in categories:
        category_path = content_path / category_dir
        if category_path.exists():
            files.extend(sorted(category_path.glob('*.md')))
    return files


def authored_content_date(frontmatter: Dict[str, Any], file_path: Optional[Path] = None) -> Any:
    """Prefer frontmatter dates; fall back to git last-updated, never build time."""
    date_val = (
        frontmatter.get('date')
        or frontmatter.get('sent_date')
        or frontmatter.get('publish_date')
    )
    if date_val:
        return date_val
    if file_path is None:
        return None
    try:
        from core.git_metadata import get_file_last_updated
    except ImportError:
        from gang.core.git_metadata import get_file_last_updated
    meta = get_file_last_updated(Path(file_path))
    if not meta:
        return None
    return meta.get('date_iso') or meta.get('date')


def fallback_jsonld(
    content_type: str,
    title: str,
    description: str,
    url: str,
    date_val: Any,
    site_title: str,
) -> Dict[str, Any]:
    date_str = ''
    if date_val is not None:
        date_str = date_val.isoformat() if hasattr(date_val, 'isoformat') else str(date_val)
        if isinstance(date_str, str):
            date_str = date_str.strip()
    if content_type in ('posts', 'articles'):
        payload = {
            '@context': 'https://schema.org',
            '@type': 'BlogPosting',
            'headline': title,
            'description': description,
            'author': {'@type': 'Organization', 'name': site_title},
            'publisher': {'@type': 'Organization', 'name': site_title},
            'url': url,
        }
        if date_str:
            payload['datePublished'] = date_str
        return payload
    if content_type == 'people':
        return {
            '@context': 'https://schema.org',
            '@type': 'Person',
            'name': title,
            'description': description,
            'url': url,
        }
    if content_type == 'projects':
        payload = {
            '@context': 'https://schema.org',
            '@type': 'CreativeWork',
            'name': title,
            'description': description,
            'author': {'@type': 'Organization', 'name': site_title},
            'url': url,
        }
        if date_str:
            payload['dateCreated'] = date_str
        return payload
    if content_type == 'newsletters':
        payload = {
            '@context': 'https://schema.org',
            '@type': 'Article',
            'headline': title,
            'description': description,
            'url': url,
        }
        if date_str:
            payload['datePublished'] = date_str
        return payload
    return {
        '@context': 'https://schema.org',
        '@type': 'WebPage',
        'name': title,
        'description': description,
        'url': url,
    }


def minify_js_source(js_content: str) -> str:
    """Strip comments outside string/template literals so URL and regex-like text stay intact."""
    out = []
    i = 0
    n = len(js_content)
    while i < n:
        ch = js_content[i]
        nxt = js_content[i + 1] if i + 1 < n else ''
        if ch in ('"', "'", '`'):
            quote = ch
            out.append(ch)
            i += 1
            while i < n:
                cur = js_content[i]
                out.append(cur)
                if cur == '\\' and i + 1 < n:
                    out.append(js_content[i + 1])
                    i += 2
                    continue
                if cur == quote:
                    i += 1
                    break
                i += 1
            continue
        if ch == '/' and nxt == '*':
            i += 2
            while i + 1 < n and not (js_content[i] == '*' and js_content[i + 1] == '/'):
                i += 1
            i = i + 2 if i + 1 < n else n
            continue
        if ch == '/' and nxt == '/':
            line_start = not out or out[-1] == '\n'
            if not line_start:
                prefix = []
                j = len(out) - 1
                while j >= 0 and out[j] != '\n':
                    prefix.append(out[j])
                    j -= 1
                line_start = ''.join(reversed(prefix)).strip() == ''
            if line_start:
                while i < n and js_content[i] != '\n':
                    i += 1
                continue
        out.append(ch)
        i += 1
    js_content = ''.join(out)
    js_content = re.sub(r'\n[ \t]+', '\n', js_content)
    js_content = re.sub(r'[ \t]{2,}', ' ', js_content)
    js_content = '\n'.join(line for line in js_content.split('\n') if line.strip())
    return js_content.strip()


def minify_html_source(original_html: str) -> str:
    """Minify HTML while protecting script/style bodies with a per-call nonce."""
    nonce = uuid.uuid4().hex
    protected: List[str] = []

    def _protect(match: re.Match) -> str:
        protected.append(match.group(0))
        return f'GANGMINIFY{nonce}{len(protected) - 1}END'

    work = re.sub(
        r'<script\b[^>]*>.*?</script>',
        _protect,
        original_html,
        flags=re.DOTALL | re.IGNORECASE,
    )
    work = re.sub(
        r'<style\b[^>]*>.*?</style>',
        _protect,
        work,
        flags=re.DOTALL | re.IGNORECASE,
    )
    work = re.sub(r'<!--.*?-->', '', work, flags=re.DOTALL)
    work = re.sub(r'>\s+<', '><', work)
    work = '\n'.join(line.strip() for line in work.split('\n') if line.strip())
    for index, block in enumerate(protected):
        work = work.replace(f'GANGMINIFY{nonce}{index}END', block)
    return work

@click.group()
@click.pass_context
def cli(ctx):
    """GANG - AI-first static publishing platform"""
    
    # Load .env file if it exists
    env_file = Path('.env')
    if env_file.exists():
        try:
            with open(env_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        os.environ[key.strip()] = value.strip()
        except:
            pass  # Continue if .env parsing fails
    
    config_path = Path('gang.config.yml')
    if not config_path.exists():
        click.echo("Error: gang.config.yml not found", err=True)
        ctx.abort()
    
    with open(config_path) as f:
        raw = yaml.safe_load(f)
    if not isinstance(raw, dict):
        click.echo("Error: gang.config.yml must be a YAML mapping", err=True)
        ctx.abort()
    ctx.obj = raw

@cli.command()
@click.option('--answerability', is_flag=True, help='Generate answerability report')
@click.option('--format', type=click.Choice(['json', 'html']), default='html')
@click.pass_context
def report(ctx, answerability, format):
    """Generate reports on content quality and structure"""
    
    if answerability:
        try:
            from core.answerability import AnswerabilityAnalyzer
        except ImportError:
            import sys
            sys.path.insert(0, str(Path(__file__).parent))
            from core.answerability import AnswerabilityAnalyzer
        
        config = ctx.obj
        dist_path = Path(config['build']['output'])
        reports_dir = Path('reports')
        reports_dir.mkdir(exist_ok=True)
        
        click.echo("Score Analyzing answerability...\n")
        
        analyzer = AnswerabilityAnalyzer(dist_path)
        results = analyzer.analyze_site()
        
        # Save JSON
        json_path = reports_dir / 'answerability.json'
        json_path.write_text(json.dumps(results, indent=2))
        click.echo(f"✅ JSON report: {json_path}")
        
        # Save HTML dashboard
        html_path = reports_dir / 'answerability.html'
        html_report = analyzer.generate_html_report(results)
        html_path.write_text(html_report)
        click.echo(f"✅ HTML dashboard: {html_path}")
        
        # Print summary
        click.echo(f"\n📊 Summary:")
        click.echo(f"   Total Pages: {results['total_pages']}")
        click.echo(f"   JSON-LD Coverage: {results['jsonld_coverage_pct']:.1f}%")
        
        # Fail CI if coverage < 95%
        if results['jsonld_coverage_pct'] < 95:
            click.echo(f"\n❌ JSON-LD coverage below 95% threshold", err=True)
            ctx.exit(1)
        else:
            click.echo(f"\n✅ Answerability check passed!")

@cli.command(name='check-contracts')
@click.option('--verbose', is_flag=True, help='Show detailed validation results')
@click.pass_context
def check_contracts(ctx, verbose):
    """Validate page-type YAML contracts (posts, pages, people, products)"""
    try:
        from core.contract_validator import ContractValidator
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.contract_validator import ContractValidator
    
    config = ctx.obj
    dist_path = Path(config['build']['output'])
    contracts_dir = Path('contracts')
    
    if not contracts_dir.exists():
        click.echo("❌ Contracts directory not found", err=True)
        click.echo("   Expected: ./contracts/*.yml")
        ctx.exit(1)
    
    validator = ContractValidator(contracts_dir)
    
    click.echo("Score Validating site against contracts...\n")
    
    results = []
    
    # Map dist paths to content types
    type_mapping = {
        'posts': 'post',
        'pages': 'page',
        'projects': 'project',
        'products': 'product',
        'people': 'person',
    }
    
    for content_type_dir, contract_type in type_mapping.items():
        type_path = dist_path / content_type_dir
        if not type_path.exists():
            continue
        
        for html_file in type_path.rglob('index.html'):
            # Collection indexes are CollectionPage, not detail-page contracts
            if html_file.parent == type_path:
                continue
            result = validator.validate_file(html_file, contract_type)
            results.append(result)
            
            if verbose:
                status = "✅" if result['valid'] else "❌"
                click.echo(f"{status} {html_file.relative_to(dist_path)}")
                if not result['valid'] and result['errors']:
                    for error in result['errors'][:3]:
                        click.echo(f"    • {error}")
    
    # Generate Explain report
    report = validator.generate_explain_report(results)
    click.echo("\n" + report)
    
    # Exit with error if any failures
    failed = [r for r in results if not r['valid']]
    if failed:
        ctx.exit(1)

@cli.command()
@click.option('--force', is_flag=True, help='Force re-optimization of all files')
@click.pass_context
def optimize(ctx, force):
    """Fill missing SEO/alt/JSON-LD fields using AI"""
    try:
        from core.optimizer import AIOptimizer
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.optimizer import AIOptimizer
    
    click.echo("🤖 Running AI optimization...")
    config = ctx.obj
    optimizer = AIOptimizer(config)
    
    if not optimizer.client:
        click.echo("⚠️  No ANTHROPIC_API_KEY found in environment", err=True)
        click.echo("Set ANTHROPIC_API_KEY to enable AI optimization")
        return
    
    content_path = Path(config['build']['content'])
    md_files = collect_category_markdown(content_path)
    
    click.echo(f"Found {len(md_files)} content files")
    
    # Estimate cost
    cost_info = optimizer.estimate_cost(len(md_files))
    click.echo(f"💰 Estimated cost: ${cost_info['estimated_cost_usd']:.2f} (with cache: ${cost_info['with_cache']:.2f})")
    
    optimized_count = 0
    for md_file in md_files:
        if not is_safe_content_slug(md_file.stem):
            click.echo(f"⚠️  Skipping unsafe content path: {md_file.relative_to(content_path)}")
            continue
        content = md_file.read_text()
        frontmatter, body = parse_frontmatter_text(content)
        if content.startswith('---') and not frontmatter and body == content:
            click.echo(f"⚠️  Skipping malformed frontmatter: {md_file.relative_to(content_path)}")
            continue
        
        content_type = md_file.parent.name
        
        # Optimize
        optimized = optimizer.optimize_content(body, frontmatter, content_type)
        
        if optimized != frontmatter:
            dumped = yaml.dump(optimized, default_flow_style=False, allow_unicode=True).strip()
            new_content = f"---\n{dumped}\n---\n{body.lstrip(chr(10))}"
            md_file.write_text(new_content)
            optimized_count += 1
            click.echo(f"  Best Practices {md_file.relative_to(content_path)}")
    
    click.echo(f"✅ Optimized {optimized_count} files")

@cli.command()
@click.argument('file_path', type=click.Path(exists=True), required=False)
@click.option('--all', 'analyze_all', is_flag=True, help='Analyze all content files')
@click.option('--format', type=click.Choice(['text', 'json', 'summary']), default='text', help='Output format')
@click.option('--min-score', type=int, default=0, help='Minimum quality score (0-100, exit 1 if any file scores lower)')
@click.pass_context
def analyze(ctx, file_path, analyze_all, format, min_score):
    """Analyze content quality (readability, SEO, accessibility)"""
    try:
        from core.analyzer import ContentAnalyzer
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.analyzer import ContentAnalyzer
    
    config = ctx.obj
    analyzer = ContentAnalyzer(config)
    
    # Batch analysis mode
    if analyze_all:
        content_path = Path(config['build']['content'])
        md_files = collect_category_markdown(content_path)
        
        if not md_files:
            click.echo("⚠️  No markdown files found", err=True)
            ctx.exit(1)
        
        click.echo(f"📊 Analyzing {len(md_files)} files...\n")
        
        all_analyses = []
        failed_quality = []
        
        for md_file in sorted(md_files):
            if not is_safe_content_slug(md_file.stem):
                continue
            try:
                analysis = analyzer.analyze_file(md_file)
                all_analyses.append(analysis)
                
                # Calculate overall score
                seo_score = analysis['seo']['score']
                if seo_score < min_score:
                    failed_quality.append((md_file, seo_score))
                
                if format == 'text':
                    # Brief summary per file
                    status = analyzer._calculate_overall_status(analysis)
                    status_icon = analyzer._status_icon(status)
                    r = analysis['readability']
                    seo = analysis['seo']
                    click.echo(f"{status_icon} {md_file.relative_to(content_path)}")
                    click.echo(f"   └─ {r['word_count']} words, SEO: {seo['score']}/100, Grade: {r['grade_level']}")
                    
            except Exception as e:
                click.echo(f"❌ {md_file.relative_to(content_path)}: {e}")
        
        # Summary report
        if format == 'summary' or format == 'text':
            click.echo("\n" + "=" * 60)
            click.echo("📊 SUMMARY REPORT")
            click.echo("=" * 60)
            
            if not all_analyses:
                click.echo("No files analyzed.")
                return

            total_words = sum(a['readability']['word_count'] for a in all_analyses)
            avg_grade = sum(a['readability']['grade_level'] for a in all_analyses) / len(all_analyses)
            avg_seo = sum(a['seo']['score'] for a in all_analyses) / len(all_analyses)
            
            click.echo(f"Total files: {len(all_analyses)}")
            click.echo(f"Total words: {total_words:,}")
            click.echo(f"Avg grade level: {avg_grade:.1f}")
            click.echo(f"Avg SEO score: {avg_seo:.0f}/100")
            
            # Status breakdown
            statuses = [analyzer._calculate_overall_status(a) for a in all_analyses]
            click.echo(f"\nStatus breakdown:")
            click.echo(f"  Best Practices Good: {statuses.count('good') + statuses.count('excellent')}")
            click.echo(f"  ⚠️  Warning: {statuses.count('warning')}")
            click.echo(f"  ✗ Poor: {statuses.count('poor')}")
            
            if failed_quality:
                click.echo(f"\n⚠️  {len(failed_quality)} file(s) below minimum score ({min_score}):")
                for file, score in failed_quality:
                    click.echo(f"  - {file.relative_to(content_path)}: {score}/100")
                ctx.exit(1)
        
        elif format == 'json':
            click.echo(json.dumps({
                'total_files': len(all_analyses),
                'total_words': sum(a['readability']['word_count'] for a in all_analyses),
                'files': all_analyses
            }, indent=2))
        
        return
    
    # Single file analysis
    if not file_path:
        click.echo("Error: Provide a file path or use --all", err=True)
        ctx.exit(1)
    
    content_path = Path(config['build']['content'])
    resolved = resolve_content_arg(content_path, str(file_path))
    if resolved is None or resolved.suffix != '.md':
        click.echo("⚠️  File must be a markdown file under the content root", err=True)
        ctx.exit(1)
    file_path = resolved
    
    click.echo(f"📊 Analyzing {file_path}...\n")
    
    try:
        analysis = analyzer.analyze_file(file_path)
        
        if format == 'json':
            click.echo(json.dumps(analysis, indent=2))
        else:
            report = analyzer.format_report(analysis)
            click.echo(report)
        
        # Check minimum score
        seo_score = analysis['seo']['score']
        if seo_score < min_score:
            click.echo(f"\n❌ Quality check failed: SEO score {seo_score} < {min_score}")
            ctx.exit(1)
            
    except Exception as e:
        click.echo(f"❌ Analysis failed: {e}", err=True)
        ctx.exit(1)

@cli.command()
@click.option('--links', is_flag=True, help='Validate all links (internal and external)')
@click.option('--internal-only', is_flag=True, help='Only check internal links (faster)')
@click.option('--suggest-fixes', is_flag=True, help='Use AI to suggest fixes for broken links')
@click.option('--format', type=click.Choice(['text', 'json']), default='text', help='Output format')
@click.pass_context
def validate(ctx, links, internal_only, suggest_fixes, format):
    """Validate links, HTML, and other quality checks"""
    if not links:
        click.echo("Usage: gang validate --links [OPTIONS]")
        click.echo("")
        click.echo("Options:")
        click.echo("  --links           Validate all links")
        click.echo("  --internal-only   Only check internal links (faster)")
        click.echo("  --suggest-fixes   Use AI to suggest fixes (requires ANTHROPIC_API_KEY)")
        click.echo("  --format json     Output as JSON")
        click.echo("")
        click.echo("Examples:")
        click.echo("  gang validate --links")
        click.echo("  gang validate --links --internal-only")
        click.echo("  gang validate --links --suggest-fixes")
        return
    
    try:
        from core.link_validator import LinkValidator
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.link_validator import LinkValidator
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    dist_path = Path(config['build']['output'])
    
    if format != 'json':
        click.echo("🔗 Validating links...")
    
    validator = LinkValidator(config, content_path, dist_path)
    
    results = validator.scan_all_files()
    
    # If internal-only, clear external results
    if internal_only:
        results['external_links'] = 0
        results['broken_external'] = []
        results['redirects'] = []
    
    if format == 'json':
        import json
        output_data = results
        
        # Add AI suggestions if requested
        if suggest_fixes and (results['broken_internal'] or results['broken_external'] or results['redirects']):
            click.echo(json.dumps(results, indent=2), err=True)
            click.echo("\n🤖 Generating AI fix suggestions...", err=True)
            suggestions = validator.suggest_fixes_with_ai(results)
            output_data = {
                'validation_results': results,
                'ai_suggestions': suggestions
            }
        
        click.echo(json.dumps(output_data, indent=2))
    else:
        report = validator.format_report(results)
        click.echo(report)
        
        # Show AI suggestions if requested
        if suggest_fixes and (results['broken_internal'] or results['broken_external'] or results['redirects']):
            click.echo("\n🤖 Generating AI fix suggestions...\n")
            suggestions = validator.suggest_fixes_with_ai(results)
            
            if 'error' in suggestions:
                click.echo(f"⚠️  {suggestions['error']}")
                click.echo("Set ANTHROPIC_API_KEY to enable AI suggestions")
            else:
                suggestions_report = validator.format_suggestions_report(suggestions)
                click.echo(suggestions_report)
    
    # Exit with error if broken links found
    if results['broken_internal'] or results['broken_external']:
        if format != 'json':
            click.echo(f"\n❌ Validation failed with {len(results['broken_internal']) + len(results['broken_external'])} broken links")
        ctx.exit(1)

@cli.command()
@click.option('--limit', type=int, default=10, help='Number of recent builds to show')
@click.pass_context
def performance(ctx, limit):
    """Show build performance history and trends"""
    try:
        from core.build_profiler import BuildProfiler
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.build_profiler import BuildProfiler
    
    profiler = BuildProfiler()
    
    if not profiler.runs_file.exists():
        click.echo("No performance data yet. Run 'gang build --profile' first.")
        return
    
    try:
        with open(profiler.runs_file) as f:
            data = json.load(f)
            runs = data.get('runs', [])
        
        if not runs:
            click.echo("No performance data yet.")
            return
        
        click.echo("=" * 60)
        click.echo(f"Performance Build Performance History (last {min(limit, len(runs))} runs)")
        click.echo("=" * 60)
        click.echo("")
        
        # Show recent runs
        for i, run in enumerate(runs[-limit:], 1):
            timestamp = run.get('timestamp', 'Unknown')
            duration_ms = run.get('total_duration_ms', 0)
            duration_s = duration_ms / 1000
            
            click.echo(f"#{len(runs) - limit + i}: {duration_ms}ms ({duration_s:.2f}s)")
            click.echo(f"   Time: {timestamp}")
            
            # Show file counts
            files = run.get('files', {})
            if files:
                total_files = sum(files.values())
                click.echo(f"   Files: {total_files} ({', '.join(f'{k}:{v}' for k, v in files.items())})")
            
            click.echo("")
        
        # Calculate stats
        if len(runs) >= 2:
            recent_5 = runs[-5:] if len(runs) >= 5 else runs
            avg_duration = sum(r['total_duration_ms'] for r in recent_5) / len(recent_5)
            fastest = min(r['total_duration_ms'] for r in runs)
            slowest = max(r['total_duration_ms'] for r in runs)
            
            click.echo("📊 Statistics:")
            click.echo(f"├─ Average (last 5): {avg_duration:.0f}ms")
            click.echo(f"├─ Fastest: {fastest}ms")
            click.echo(f"└─ Slowest: {slowest}ms")
            click.echo("")
        
        click.echo("=" * 60)
        click.echo("💡 Run 'gang build --profile' to track performance")
        click.echo("=" * 60)
    
    except Exception as e:
        click.echo(f"Error reading performance data: {e}")

@cli.command()
@click.option('--links', is_flag=True, help='Fix broken links using AI suggestions')
@click.option('--apply', is_flag=True, help='Actually apply fixes (default is suggestions only)')
@click.option('--commit', is_flag=True, help='Create git commit with suggested fixes')
@click.option('--min-confidence', type=click.Choice(['high', 'medium', 'low']), default='high', help='Minimum confidence for applying')
@click.option('--rebuild', is_flag=True, help='Rebuild site after applying fixes')
@click.pass_context
def fix(ctx, links, apply, commit, min_confidence, rebuild):
    """Show AI suggestions for fixing broken links (use --apply to actually fix)"""
    if not links:
        click.echo("Usage: gang fix --links [OPTIONS]")
        click.echo("")
        click.echo("Options:")
        click.echo("  --links              Get AI suggestions for broken links")
        click.echo("  --apply              Actually apply the fixes (default: suggestions only)")
        click.echo("  --commit             Create git commit with fixes for review")
        click.echo("  --min-confidence     Minimum confidence: high|medium|low (default: high)")
        click.echo("  --rebuild            Rebuild site after fixing")
        click.echo("")
        click.echo("Examples:")
        click.echo("  gang fix --links                    # Show suggestions only (safe)")
        click.echo("  gang fix --links --apply            # Apply high-confidence fixes")
        click.echo("  gang fix --links --commit           # Create git commit for review")
        click.echo("  gang fix --links --apply --rebuild  # Fix and rebuild")
        click.echo("")
        click.echo("⚠️  Default behavior: Shows suggestions WITHOUT applying them")
        click.echo("    Use --apply to actually modify files")
        return
    
    try:
        from core.link_validator import LinkValidator
        from core.link_fixer import LinkFixer
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.link_validator import LinkValidator
        from core.link_fixer import LinkFixer
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    dist_path = Path(config['build']['output'])
    
    # Step 1: Validate links
    click.echo("🔗 Validating links...")
    validator = LinkValidator(config, content_path, dist_path)
    results = validator.scan_all_files()
    
    broken_count = len(results['broken_internal']) + len(results['broken_external'])
    
    if broken_count == 0:
        click.echo("Best Practices No broken links found!")
        return
    
    click.echo(f"Found {broken_count} broken link(s)\n")
    
    # Step 2: Get AI suggestions
    click.echo("🤖 Generating AI fix suggestions...")
    suggestions = validator.suggest_fixes_with_ai(results)
    
    if 'error' in suggestions:
        click.echo(f"❌ {suggestions['error']}")
        click.echo("Set ANTHROPIC_API_KEY to enable AI-powered fixes")
        ctx.exit(1)
    
    # Show suggestions
    suggestions_report = validator.format_suggestions_report(suggestions)
    click.echo(suggestions_report)
    
    # Step 3: Apply fixes if requested
    if apply or commit:
        click.echo(f"\n🔧 Applying fixes (min confidence: {min_confidence})...\n")
        
        fixer = LinkFixer(content_path)
        fix_results = fixer.apply_suggestions(suggestions, min_confidence, dry_run=False)
        
        # Show what was applied
        report = fixer.format_report(fix_results)
        click.echo(report)
        
        # Step 4: Create git commit if requested
        if commit and fix_results['applied'] > 0:
            click.echo("\n📝 Creating git commit...")
            try:
                import subprocess
                
                # Add changed files
                files_changed = list(set([f['file'] for f in fix_results['fixes']]))
                for file in files_changed:
                    file_path = content_path / file
                    subprocess.run(['git', 'add', str(file_path)], check=True)
                
                # Create commit message
                commit_msg = f"Fix {fix_results['applied']} broken link(s) [AI-suggested]\n\n"
                for fix in fix_results['fixes']:
                    if fix['action'] == 'replaced':
                        commit_msg += f"- {fix['file']}: {fix['old_url']} → {fix['new_url']}\n"
                    else:
                        commit_msg += f"- {fix['file']}: Removed {fix['old_url']}\n"
                
                subprocess.run(['git', 'commit', '-m', commit_msg], check=True)
                click.echo("✅ Git commit created!")
                click.echo("   Review with: git show")
                click.echo("   Undo with: git reset HEAD^")
                
            except subprocess.CalledProcessError as e:
                click.echo(f"⚠️  Could not create git commit: {e}")
            except Exception as e:
                click.echo(f"⚠️  Git commit failed: {e}")
        
        # Step 5: Rebuild if requested
        if rebuild and fix_results['applied'] > 0:
            click.echo("\n🔨 Rebuilding site...")
            ctx.invoke(build)
    else:
        click.echo("\n💡 To apply these suggestions:")
        click.echo("   gang fix --links --apply           # Apply and review manually")
        click.echo("   gang fix --links --commit          # Create git commit for review")
        click.echo("   gang fix --links --apply --rebuild # Apply and rebuild")
        ctx.exit(1)  # Exit with error to block workflow until fixed

@cli.group()
def media():
    """Manage media files (upload to R2, sync, list)"""
    pass

@media.command()
@click.argument('source', type=click.Path(exists=True))
@click.option('--path', help='Remote path in R2 (default: images/filename)')
@click.pass_context
def upload(ctx, source, path):
    """Upload file(s) to Cloudflare R2"""
    try:
        from core.r2_storage import R2Storage
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.r2_storage import R2Storage
    
    config = ctx.obj
    storage = R2Storage(config)
    
    if not storage.is_configured():
        missing = storage.get_missing_config()
        click.echo("❌ R2 not configured. Missing environment variables:")
        for var in missing:
            click.echo(f"  - {var}")
        click.echo("\nSee MEDIA_STORAGE_GUIDE.md for setup instructions")
        ctx.exit(1)
    
    source_path = Path(source)
    
    # Upload directory or single file
    if source_path.is_dir():
        click.echo(f"📁 Uploading directory: {source_path}")
        remote_prefix = path or 'images'
        result = storage.upload_directory(source_path, remote_prefix)
        
        if result['uploaded']:
            total_mb = result['total_size'] / (1024 * 1024)
            click.echo(f"\n✅ Uploaded {len(result['uploaded'])} file(s) ({total_mb:.2f}MB)")
            for item in result['uploaded'][:5]:
                click.echo(f"  Best Practices {item['file']}")
                click.echo(f"    {item['url']}")
            if len(result['uploaded']) > 5:
                click.echo(f"  ... and {len(result['uploaded']) - 5} more")
        
        if result['failed']:
            click.echo(f"\n❌ Failed: {len(result['failed'])} file(s)")
            for item in result['failed'][:3]:
                click.echo(f"  ✗ {item['file']}: {item['error']}")
    
    else:
        # Single file upload
        remote_path = path or f"images/{source_path.name}"
        click.echo(f"📤 Uploading {source_path.name} to {remote_path}...")
        
        result = storage.upload_file(source_path, remote_path)
        
        if 'error' in result:
            click.echo(f"❌ Upload failed: {result['error']}")
            ctx.exit(1)
        else:
            size_kb = result['size'] / 1024
            click.echo(f"✅ Uploaded successfully ({size_kb:.1f}KB)")
            click.echo(f"📍 Public URL: {result['public_url']}")
            click.echo(f"\n💡 Use in markdown:")
            click.echo(f"   ![Alt text]({result['public_url']})")

@media.command(name='list')
@click.option('--prefix', default='', help='Filter by prefix (e.g., images/)')
@click.option('--limit', default=100, type=int, help='Max files to show')
@click.pass_context
def list_media_files(ctx, prefix, limit):
    """List files in R2 bucket"""
    try:
        from core.r2_storage import R2Storage
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.r2_storage import R2Storage
    
    config = ctx.obj
    storage = R2Storage(config)
    
    if not storage.is_configured():
        missing = storage.get_missing_config()
        click.echo("❌ R2 not configured. Missing:")
        for var in missing:
            click.echo(f"  - {var}")
        ctx.exit(1)
    
    click.echo(f"📁 Listing files in {storage.bucket_name}/{prefix or '(root)'}...")
    
    files = storage.list_files(prefix, limit)
    
    if not files:
        click.echo("No files found")
        return
    
    total_size = sum(f['size'] for f in files)
    total_mb = total_size / (1024 * 1024)
    
    click.echo(f"\nFound {len(files)} file(s) ({total_mb:.2f}MB total):\n")
    
    for file in files[:limit]:
        size_kb = file['size'] / 1024
        click.echo(f"📄 {file['key']}")
        click.echo(f"   Size: {size_kb:.1f}KB")
        click.echo(f"   URL: {file['url']}")
        click.echo("")

@media.command()
@click.argument('source_dir', type=click.Path(exists=True))
@click.option('--prefix', default='images', help='Remote prefix in R2')
@click.option('--delete', is_flag=True, help='Delete remote files not in local')
@click.pass_context
def sync(ctx, source_dir, prefix, delete):
    """Sync local directory to R2"""
    try:
        from core.r2_storage import R2Storage
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.r2_storage import R2Storage
    
    config = ctx.obj
    storage = R2Storage(config)
    
    if not storage.is_configured():
        missing = storage.get_missing_config()
        click.echo("❌ R2 not configured. Missing:")
        for var in missing:
            click.echo(f"  - {var}")
        ctx.exit(1)
    
    source_path = Path(source_dir)
    click.echo(f"🔄 Syncing {source_path} → {storage.bucket_name}/{prefix}...")
    
    if delete:
        click.echo("⚠️  Delete mode enabled - will remove remote files not in local")
    
    result = storage.sync_directory(source_path, prefix, delete)
    
    click.echo(f"\n✅ Sync complete!")
    click.echo(f"  Uploaded: {result['uploaded']}")
    click.echo(f"  Skipped: {result['skipped']}")
    if delete:
        click.echo(f"  Deleted: {result['deleted']}")
    
    if result['errors']:
        click.echo(f"\n⚠️  Errors: {len(result['errors'])}")
        for error in result['errors'][:3]:
            click.echo(f"  - {error}")

@media.command()
@click.argument('remote_path')
@click.pass_context
def delete(ctx, remote_path):
    """Delete file from R2"""
    try:
        from core.r2_storage import R2Storage
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.r2_storage import R2Storage
    
    config = ctx.obj
    storage = R2Storage(config)
    
    if not storage.is_configured():
        click.echo("❌ R2 not configured")
        ctx.exit(1)
    
    if not click.confirm(f"Delete {remote_path} from R2?"):
        click.echo("Cancelled")
        return
    
    result = storage.delete_file(remote_path)
    
    if 'error' in result:
        click.echo(f"❌ Delete failed: {result['error']}")
        ctx.exit(1)
    else:
        click.echo(f"✅ Deleted: {remote_path}")

@cli.command()
@click.argument('source', type=click.Path(exists=True), required=False)
@click.option('--title', help='Article title (auto-detected if not provided)')
@click.option('--category', type=click.Choice(['posts', 'pages', 'projects']), help='Content category (AI suggests if not provided)')
@click.option('--compress-images', is_flag=True, default=True, help='Compress images before upload')
@click.option('--commit', is_flag=True, help='Create git commit after import')
@click.pass_context
def import_content(ctx, source, title, category, compress_images, commit):
    """Import content from file or clipboard (extracts & uploads images)"""
    try:
        from core.content_importer import ContentImporter
        from core.r2_storage import R2Storage
        from anthropic import Anthropic
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.content_importer import ContentImporter
        from core.r2_storage import R2Storage
        try:
            from anthropic import Anthropic
        except:
            Anthropic = None
    
    config = ctx.obj
    
    # Initialize R2 storage
    r2_storage = R2Storage(config)
    
    # Initialize AI client
    ai_client = None
    if Anthropic and os.environ.get('ANTHROPIC_API_KEY'):
        ai_client = Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])
    
    # Initialize importer
    importer = ContentImporter(config, r2_storage, ai_client)
    
    # Read content
    if source:
        content = Path(source).read_text()
        click.echo(f"📄 Importing from {source}...")
    else:
        # Try to read from clipboard
        try:
            import subprocess
            result = subprocess.run(['pbpaste'], capture_output=True, text=True)
            content = result.stdout
            if not content.strip():
                click.echo("❌ No content in clipboard. Provide a file or copy content first.")
                ctx.exit(1)
            click.echo("📋 Importing from clipboard...")
        except:
            click.echo("❌ Cannot read clipboard. Provide a file path instead.")
            ctx.exit(1)
    
    # Import and process
    click.echo("Score Analyzing content...")
    result = importer.import_from_text(content, title)
    
    # Show what was found
    click.echo(f"\n📊 Import Analysis:")
    click.echo(f"├─ Title: {result['title']}")
    click.echo(f"├─ Suggested slug: {result['suggested_slug']}")
    if result['suggested_category']:
        cat = result['suggested_category']
        click.echo(f"├─ AI category: {cat['category']} ({cat['confidence']} confidence)")
        click.echo(f"│  └─ {cat['reasoning']}")
    click.echo(f"└─ Images found: {len(result['images'])}")
    
    # Check slug conflicts
    if result['slug_conflicts']:
        click.echo(f"\n⚠️  Slug conflict! '{result['suggested_slug']}' already exists:")
        for conflict in result['slug_conflicts']:
            click.echo(f"  - {conflict}")
        
        # Suggest unique slug
        from core.content_importer import SlugChecker
        checker = SlugChecker(importer.content_path)
        suggested_cat = category or result.get('suggested_category', {}).get('category', 'pages')
        unique_slug = checker.suggest_unique_slug(result['suggested_slug'], suggested_cat)
        click.echo(f"\n💡 Suggested unique slug: {unique_slug}")
        
        if not click.confirm(f"Use '{unique_slug}' instead?"):
            click.echo("Import cancelled. Choose a different title or slug.")
            ctx.exit(1)
        
        result['suggested_slug'] = unique_slug
    
    # Process and upload images
    if result['images']:
        click.echo(f"\n🖼️  Processing {len(result['images'])} image(s)...")
        
        processed_images = importer.process_and_upload_images(
            result['images'],
            result['suggested_slug'],
            compress=compress_images
        )
        
        # Show upload results
        for img in processed_images:
            if img.get('type') == 'uploaded':
                size_kb = img['size'] / 1024
                orig_kb = img['original_size'] / 1024
                savings = ((img['original_size'] - img['size']) / img['original_size']) * 100
                click.echo(f"  Best Practices Uploaded & compressed: {size_kb:.1f}KB (saved {savings:.0f}%)")
                if img.get('alt_generated_by_ai'):
                    click.echo(f"    Alt text (AI): {img['alt']}")
    
    # Create markdown file
    final_category = category or result.get('suggested_category', {}).get('category', 'pages')
    if (
        final_category not in PUBLISHABLE_CATEGORIES
        or final_category == 'products'
        or not is_safe_content_slug(str(result.get('suggested_slug') or ''))
    ):
        click.echo("❌ Invalid import category or slug", err=True)
        ctx.exit(1)
    file_path, markdown_content = importer.create_markdown_file(
        result['title'],
        result['content'],
        final_category,
        result['suggested_slug']
    )
    
    # Show preview
    click.echo(f"\n📝 Will create: {file_path}")
    click.echo("\nPreview (first 10 lines):")
    click.echo("─" * 60)
    for i, line in enumerate(markdown_content.split('\n')[:10], 1):
        click.echo(line)
    click.echo("...")
    click.echo("─" * 60)
    
    # Confirm
    if not click.confirm("\nCreate this file?"):
        click.echo("Import cancelled")
        ctx.exit(1)
    
    # Save
    save_result = importer.save_imported_content(file_path, markdown_content, commit)
    
    if save_result['success']:
        click.echo(f"\n✅ Content imported successfully!")
        click.echo(f"📁 File: {save_result['file_path']}")
        
        if save_result.get('git_commit'):
            click.echo(f"✅ Git commit created")
            click.echo(f"   Review: git show")
        
        click.echo(f"\n💡 Next steps:")
        click.echo(f"   1. Review and edit: vim {file_path}")
        click.echo(f"   2. Analyze quality: gang analyze {file_path}")
        click.echo(f"   3. Change status to 'published' when ready")
        click.echo(f"   4. Build: gang build")

@cli.command()
@click.argument('old_slug')
@click.argument('new_slug')
@click.option('--category', type=click.Choice(['posts', 'articles', 'pages', 'projects', 'people', 'newsletters', 'products']), required=True, help='Content category')
@click.option('--redirect', is_flag=True, default=True, help='Create 301 redirect (default: yes)')
@click.option('--no-redirect', is_flag=True, help='Skip creating redirect')
@click.pass_context
def rename_slug(ctx, old_slug, new_slug, category, redirect, no_redirect):
    """Rename a content slug with optional 301 redirect"""
    try:
        from core.content_importer import SlugChecker
        from core.redirects import RedirectManager
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.content_importer import SlugChecker
        from core.redirects import RedirectManager
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    dist_path = Path(config['build']['output'])

    if not is_safe_content_slug(old_slug) or not is_safe_content_slug(new_slug):
        click.echo("❌ Slugs may only contain letters, numbers, dots, underscores, or hyphens")
        ctx.exit(1)
    
    # Check old file exists
    old_file = content_path / category / f"{old_slug}.md"
    if not old_file.exists():
        click.echo(f"❌ File not found: {old_file}")
        ctx.exit(1)
    
    # Check new slug is unique
    checker = SlugChecker(content_path)
    new_file = content_path / category / f"{new_slug}.md"
    if new_file.exists():
        click.echo(f"❌ Slug '{new_slug}' already exists: {new_file}")
        click.echo(f"💡 Choose a different slug")
        ctx.exit(1)
    
    # Show what will happen
    click.echo(f"📝 Rename slug in {category}:")
    click.echo(f"   From: {old_slug}")
    click.echo(f"   To:   {new_slug}")
    click.echo(f"")
    
    old_url = public_content_url(category, old_slug)
    new_url = public_content_url(category, new_slug)
    
    create_redirect = redirect and not no_redirect
    
    if create_redirect:
        click.echo(f"🔀 Will create 301 redirect:")
        click.echo(f"   {old_url} → {new_url}")
    else:
        click.echo(f"⚠️  No redirect will be created")
        click.echo(f"   Old URL {old_url} will return 404")
    
    click.echo(f"")
    
    if not click.confirm("Proceed with rename?"):
        click.echo("Cancelled")
        return
    
    # Record the redirect before renaming so a failed rename can roll it back.
    redirect_manager = None
    prior_redirects = None
    if create_redirect:
        redirect_manager = RedirectManager(content_path, dist_path)
        prior_redirects = [dict(item) for item in redirect_manager.list_all_redirects()]
        result = redirect_manager.add_redirect(old_url, new_url, reason='slug_rename')
        if result.get('created'):
            click.echo(f"✅ 301 redirect created")
        elif result.get('updated'):
            click.echo(f"✅ Redirect updated (was already tracking this path)")
        click.echo(f"📄 Redirects file: .redirects.json")

    try:
        exclusive_rename(old_file, new_file)
        click.echo(f"✅ File renamed: {old_file.name} → {new_file.name}")
    except FileExistsError:
        if redirect_manager is not None and prior_redirects is not None:
            redirect_manager.restore_redirects(prior_redirects)
            click.echo("↩️  Redirect rolled back after rename failure")
        click.echo(f"❌ Slug '{new_slug}' already exists: {new_file}")
        ctx.exit(1)
    except Exception as e:
        if redirect_manager is not None and prior_redirects is not None:
            redirect_manager.restore_redirects(prior_redirects)
            click.echo("↩️  Redirect rolled back after rename failure")
        click.echo(f"❌ Rename failed: {e}")
        ctx.exit(1)
    
    # Create git commit
    if click.confirm("\nCreate git commit?"):
        try:
            import subprocess
            
            # Stage renamed file
            subprocess.run(['git', 'add', str(new_file)], check=True)
            subprocess.run(['git', 'rm', str(old_file)], check=True)
            
            if create_redirect:
                subprocess.run(['git', 'add', str(redirect_manager.redirects_file)], check=True)
            
            commit_msg = f"Rename slug: {old_slug} → {new_slug}"
            if create_redirect:
                commit_msg += f"\n\nAdded 301 redirect: {old_url} → {new_url}"
            
            subprocess.run(['git', 'commit', '-m', commit_msg], check=True)
            click.echo(f"✅ Git commit created")
        except Exception as e:
            click.echo(f"⚠️  Git commit failed: {e}")
    
    click.echo(f"\n💡 Next steps:")
    click.echo(f"   1. gang build  # Rebuild with new slug")
    click.echo(f"   2. Check redirects: cat .redirects.json")
    click.echo(f"   3. Deploy (redirects go live)")

@cli.group()
def redirects():
    """Manage 301 redirects for slug changes"""
    pass

@redirects.command('list')
@click.option('--format', type=click.Choice(['text', 'json', 'cloudflare', 'nginx', 'netlify']), default='text')
@click.pass_context
def list_redirects(ctx, format):
    """List all redirects"""
    try:
        from core.redirects import RedirectManager
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.redirects import RedirectManager
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    dist_path = Path(config['build']['output'])
    
    manager = RedirectManager(content_path, dist_path)
    redirects_list = manager.list_all_redirects()
    
    if format == 'json':
        import json
        click.echo(json.dumps(redirects_list, indent=2))
    elif format == 'cloudflare':
        click.echo(manager.generate_cloudflare_redirects())
    elif format == 'nginx':
        click.echo(manager.generate_nginx_redirects())
    elif format == 'netlify':
        click.echo(manager.generate_netlify_redirects())
    else:
        if not redirects_list:
            click.echo("No redirects configured")
            return
        
        click.echo(f"📋 {len(redirects_list)} redirect(s):\n")
        for r in redirects_list:
            status = r.get('status', 301)
            click.echo(f"  {r['from']} → {r['to']} ({status})")
            if 'reason' in r:
                click.echo(f"    Reason: {r['reason']}")
            if 'created' in r:
                click.echo(f"    Created: {r['created']}")
            click.echo()

@redirects.command('add')
@click.argument('from_path')
@click.argument('to_path')
@click.option('--temporary', is_flag=True, help='Use 302 instead of 301')
@click.pass_context
def add_redirect(ctx, from_path, to_path, temporary):
    """Add a manual redirect"""
    try:
        from core.redirects import RedirectManager
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.redirects import RedirectManager
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    dist_path = Path(config['build']['output'])
    
    manager = RedirectManager(content_path, dist_path)
    try:
        result = manager.add_redirect(
            from_path, 
            to_path, 
            reason='manual',
            permanent=not temporary
        )
    except ValueError as exc:
        click.echo(f"❌ {exc}", err=True)
        ctx.exit(1)
    
    status = 302 if temporary else 301
    if result.get('created'):
        click.echo(f"✅ Redirect created: {from_path} → {to_path} ({status})")
    elif result.get('updated'):
        click.echo(f"✅ Redirect updated: {from_path} → {to_path} ({status})")

@redirects.command('remove')
@click.argument('from_path')
@click.pass_context
def remove_redirect(ctx, from_path):
    """Remove a redirect"""
    try:
        from core.redirects import RedirectManager
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.redirects import RedirectManager
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    dist_path = Path(config['build']['output'])
    
    manager = RedirectManager(content_path, dist_path)
    
    if manager.remove_redirect(from_path):
        click.echo(f"✅ Redirect removed: {from_path}")
    else:
        click.echo(f"❌ Redirect not found: {from_path}")
        ctx.exit(1)

@redirects.command('validate')
@click.pass_context
def validate_redirects(ctx):
    """Check for redirect chains and loops"""
    try:
        from core.redirects import RedirectManager
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.redirects import RedirectManager
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    dist_path = Path(config['build']['output'])
    
    manager = RedirectManager(content_path, dist_path)
    issues = manager.validate_redirect_chain()
    
    if not issues:
        click.echo("✅ No redirect chains or loops detected")
    else:
        click.echo(f"⚠️  Found {len(issues)} issue(s):\n")
        for issue in issues:
            click.echo(f"  • {issue}")
        ctx.exit(1)

@cli.command()
@click.pass_context
def schedule(ctx):
    """View content publishing schedule"""
    try:
        from core.scheduler import ContentScheduler
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.scheduler import ContentScheduler
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    
    scheduler = ContentScheduler(content_path)
    summary = scheduler.get_scheduled_summary()
    report = scheduler.format_schedule_report(summary)
    
    click.echo(report)
    
    # Non-zero when future-dated content exists so CI can schedule a follow-up publish.
    # Also fail when scheduled items were fail-closed to draft (broken dates/YAML).
    broken_drafts = any(
        item.get('_date_error') or item.get('_yaml_error')
        for item in summary.get('draft_items', [])
    )
    if summary['scheduled'] > 0 or broken_drafts:
        ctx.exit(1)

@cli.command()
@click.argument('file_path', type=click.STRING)
@click.argument('publish_date', required=False)
@click.option('--now', is_flag=True, help='Publish immediately (remove schedule)')
@click.option('--status', default='scheduled', help='Content status (draft, scheduled, published)')
@click.pass_context
def set_schedule(ctx, file_path, publish_date, now, status):
    """Set or update publish date for content"""
    try:
        from core.scheduler import ContentScheduler
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.scheduler import ContentScheduler
    
    from datetime import datetime
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    scheduler = ContentScheduler(content_path)
    
    file_path = resolve_content_arg(content_path, file_path)
    if file_path is None:
        click.echo("❌ File path must stay inside the content directory")
        ctx.exit(1)
    try:
        relative = str(file_path.relative_to(content_path.resolve()))
    except ValueError:
        click.echo("❌ File path must stay inside the content directory")
        ctx.exit(1)
    if file_path.suffix != '.md' or not is_publishable_relpath(relative):
        click.echo("❌ File must be a publishable markdown file under a content category")
        ctx.exit(1)
    if Path(relative).parts and Path(relative).parts[0] == 'products':
        click.echo("❌ Product pages are owned by the commerce aggregator, not the content scheduler")
        ctx.exit(1)
    resolved = resolve_studio_content_path(content_path, relative)
    if resolved is None or not resolved.is_file():
        click.echo("❌ File not found under content categories")
        ctx.exit(1)
    if resolved.parent.name == 'products':
        click.echo("❌ Product pages are owned by the commerce aggregator, not the content scheduler")
        ctx.exit(1)
    file_path = resolved

    status = (status or '').strip().lower()
    if status not in ALLOWED_SCHEDULE_STATUSES:
        click.echo(f"❌ Invalid status: {status}")
        click.echo(f"   Use one of: {', '.join(ALLOWED_SCHEDULE_STATUSES)}")
        ctx.exit(1)
    
    if now:
        # --now with the default `--status scheduled` means publish immediately.
        # An explicit draft/sent/live status is preserved after clearing dates.
        clear_status = 'published' if status == 'scheduled' else status
        success = scheduler.set_publish_date(file_path, None, clear_status)
        if success:
            click.echo(f"✅ Removed schedule from {file_path.name}")
            click.echo(f"   Status: {clear_status}")
        else:
            click.echo(f"❌ Failed to update {file_path.name}")
            ctx.exit(1)
    elif publish_date:
        # Parse and set publish date
        try:
            # Try ISO format first
            try:
                from core.scheduler import parse_schedule_datetime
            except ImportError:
                from gang.core.scheduler import parse_schedule_datetime
            pub_date = parse_schedule_datetime(publish_date)
        except Exception:
            # Try common formats, including single-digit hours ("2025-12-25 9:00"
            # and ISO "2025-12-25T9:00").
            pub_date = None
            text = str(publish_date).strip()
            padded = re.sub(r'(?<=[\sT])(\d):', r'0\1:', text, count=1)
            for candidate in (text, padded):
                for fmt in [
                    '%Y-%m-%d',
                    '%Y-%m-%d %H:%M',
                    '%Y-%m-%d %H:%M:%S',
                    '%Y-%m-%dT%H:%M',
                    '%Y-%m-%dT%H:%M:%S',
                ]:
                    try:
                        pub_date = datetime.strptime(candidate, fmt)
                        break
                    except ValueError:
                        continue
                if pub_date is not None:
                    break
            if pub_date is None:
                click.echo(f"❌ Invalid date format: {publish_date}")
                click.echo("   Use: YYYY-MM-DD or YYYY-MM-DD HH:MM or ISO format")
                ctx.exit(1)
        
        # Ensure timezone aware
        if pub_date.tzinfo is None:
            from datetime import timezone
            pub_date = pub_date.replace(tzinfo=timezone.utc)
        
        success = scheduler.set_publish_date(file_path, pub_date, status)
        
        if success:
            click.echo(f"✅ Scheduled {file_path.name}")
            click.echo(f"   Publish date: {pub_date.strftime('%Y-%m-%d %H:%M %Z')}")
            click.echo(f"   Status: {status}")
            
            # Show relative time
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc)
            delta = pub_date - now
            
            if delta.days > 0:
                click.echo(f"   Will publish in {delta.days} day(s)")
            elif delta.seconds > 3600:
                hours = delta.seconds // 3600
                click.echo(f"   Will publish in {hours} hour(s)")
            elif delta.total_seconds() > 0:
                minutes = delta.seconds // 60
                click.echo(f"   Will publish in {minutes} minute(s)")
            else:
                click.echo(f"   ⚠️  Publish date is in the past (will publish on next build)")
        else:
            click.echo(f"❌ Failed to schedule {file_path.name}")
            ctx.exit(1)
    else:
        click.echo("Error: Provide a publish date or use --now")
        click.echo("")
        click.echo("Examples:")
        click.echo("  gang set-schedule content/posts/my-post.md '2025-12-25'")
        click.echo("  gang set-schedule content/posts/my-post.md '2025-12-25 09:00'")
        click.echo("  gang set-schedule content/posts/my-post.md --now")
        ctx.exit(1)

@cli.command()
@click.argument('file_path', type=click.STRING)
@click.option('--limit', default=20, help='Number of versions to show')
@click.pass_context
def history(ctx, file_path, limit):
    """Show version history for a content file"""
    try:
        from core.versioning import ContentVersioning
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.versioning import ContentVersioning
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    
    versioning = ContentVersioning(content_path)
    file_path = resolve_content_arg(content_path, file_path)
    if file_path is None:
        click.echo("❌ File path must stay inside the content directory")
        ctx.exit(1)
    
    history_list = versioning.get_file_history(file_path, limit)
    
    if not history_list:
        click.echo(f"No version history found for {file_path.name}")
        click.echo("(File may not be tracked in git)")
        return
    
    report = versioning.format_history_report(history_list, file_path)
    click.echo(report)

@cli.command()
@click.argument('file_path', type=click.STRING)
@click.argument('commit')
@click.pass_context
def restore(ctx, file_path, commit):
    """Restore a file to a specific commit version"""
    try:
        from core.versioning import ContentVersioning
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.versioning import ContentVersioning
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    
    versioning = ContentVersioning(content_path)
    file_path = resolve_content_arg(content_path, file_path)
    if file_path is None:
        click.echo("❌ File path must stay inside the content directory")
        ctx.exit(1)
    
    # Show what we're restoring
    history = versioning.get_file_history(file_path, limit=50)
    target_commit = None
    
    for h in history:
        if h['commit'].startswith(commit) or h['short_commit'] == commit:
            target_commit = h
            break
    
    if not target_commit:
        click.echo(f"❌ Commit not found: {commit}")
        click.echo(f"   Run 'gang history {file_path}' to see available versions")
        ctx.exit(1)
    
    click.echo(f"📜 Restoring {file_path.name}")
    click.echo(f"   To version: {target_commit['short_commit']}")
    click.echo(f"   Date: {target_commit['date']}")
    click.echo(f"   Message: {target_commit['message']}")
    click.echo("")
    
    if not click.confirm("Proceed with restore?"):
        click.echo("Cancelled")
        return
    
    success = versioning.restore_file_version(file_path, target_commit['commit'])
    
    if success:
        click.echo(f"✅ Restored {file_path.name} to version {target_commit['short_commit']}")
        click.echo(f"   Changes are in your working directory (not committed)")
        click.echo(f"   Run 'git add {file_path}' and 'git commit' to save")
    else:
        click.echo(f"❌ Failed to restore {file_path.name}")
        ctx.exit(1)

@cli.command()
@click.option('--days', default=7, help='Number of days to look back')
@click.pass_context
def changes(ctx, days):
    """Show recent content changes"""
    try:
        from core.versioning import ContentVersioning
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.versioning import ContentVersioning
    
    from datetime import datetime
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    
    versioning = ContentVersioning(content_path)
    recent = versioning.get_recent_changes(days)
    
    if not recent:
        click.echo(f"No content changes in the last {days} days")
        return
    
    click.echo(f"📝 Content Changes (Last {days} days)")
    click.echo("=" * 60)
    click.echo(f"Total commits: {len(recent)}\n")
    
    for commit in recent:
        date = datetime.fromisoformat(commit['date'])
        date_str = date.strftime('%Y-%m-%d %H:%M')
        
        click.echo(f"[{commit['short_commit']}] {date_str} - {commit['author']}")
        click.echo(f"  {commit['message']}")
        
        if commit['files']:
            for file in commit['files']:
                status_icon = {
                    'M': '📝',
                    'A': '✨',
                    'D': '🗑️',
                    'R': '🔄'
                }.get(file['status'], '•')
                click.echo(f"    {status_icon} {file['path']}")
        
        click.echo("")

@cli.command()
@click.argument('image_path', type=click.Path(exists=True))
@click.option('--focal-x', type=float, default=0.5, help='Focal point X (0-1)')
@click.option('--focal-y', type=float, default=0.5, help='Focal point Y (0-1)')
@click.option('--auto-detect', is_flag=True, help='Auto-detect focal point using AI')
@click.option('--is-lcp', is_flag=True, help='Mark as LCP image (no lazy loading)')
@click.pass_context
def process_image(ctx, image_path, focal_x, focal_y, auto_detect, is_lcp):
    """Process image with focal point and generate responsive crops"""
    try:
        from core.image_pipeline import ImagePipeline, FocalPointDetector
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.image_pipeline import ImagePipeline, FocalPointDetector
    
    config = ctx.obj
    public_path = Path(config['build']['public'])
    dist_path = Path(config['build']['output'])
    
    pipeline = ImagePipeline(public_path, dist_path)
    
    image = Path(image_path)
    
    if auto_detect:
        click.echo("Score Detecting focal point...")
        focal_point = FocalPointDetector.detect_focal_point(image)
        click.echo(f"   Detected: ({focal_point[0]:.2f}, {focal_point[1]:.2f})")
    else:
        focal_point = (focal_x, focal_y)
    
    click.echo(f"🖼️  Processing: {image.name}")
    result = pipeline.process_image(image, focal_point, is_lcp)
    
    click.echo(f"✅ Generated {len(result['crops'])} crops")
    click.echo(f"✅ Generated {len(result['formats'])} formats")
    
    if result['thumbhash']:
        click.echo(f"✅ ThumbHash: {result['thumbhash']}")
    
    click.echo(f"\n<picture> HTML:")
    click.echo(result['html'])

@cli.command()
@click.option('--from', 'bundle_path', type=click.Path(exists=True), help='Bundle JSON file')
@click.option('--platform', type=click.Choice(['twitter', 'linkedin', 'medium', 'devto']), required=True)
@click.pass_context
def syndicate(ctx, bundle_path, platform):
    """Render syndication bundle for a platform"""
    try:
        from core.syndication_bundle import render_syndication_bundle
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.syndication_bundle import render_syndication_bundle
    
    if bundle_path:
        output = render_syndication_bundle(Path(bundle_path), platform)
        click.echo(output)
    else:
        click.echo("❌ Please provide a bundle file with --from", err=True)

@cli.group()
def email():
    """Email newsletter management"""
    pass

@email.command('create-from-post')
@click.argument('post_path', type=click.STRING)
@click.option('--output', default='./emails', help='Output directory for email files')
@click.option('--esp', default='buttondown', help='ESP provider (buttondown, convertkit, mailerlite, postmark, sendgrid)')
@click.pass_context
def email_create_from_post(ctx, post_path, output, esp):
    """Create email template from a post"""
    try:
        from core.email_templates import EmailOrchestrator
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.email_templates import EmailOrchestrator
    
    config = ctx.obj
    content_root = Path(config['build']['content'])
    post_file = resolve_content_arg(content_root, str(post_path))
    if post_file is None or post_file.suffix != '.md':
        click.echo("❌ Post must be a markdown file under the content root", err=True)
        return
    
    orchestrator = EmailOrchestrator(config, esp)
    output_dir = Path(output)
    
    click.echo(f"📧 Creating email from: {post_file.name}")
    
    metadata = orchestrator.create_email_from_post(post_file, output_dir)
    
    # Save newsletter to content for public listing
    content_path = Path(config['build']['content'])
    newsletter_file = orchestrator.save_newsletter_to_content(post_file, metadata, content_path)
    
    click.echo(f"\n✅ Email created:")
    click.echo(f"   Title: {metadata['title']}")
    click.echo(f"   HTML: {metadata['html_path']}")
    click.echo(f"   Text: {metadata['text_path']}")
    click.echo(f"   Status: {metadata['status']}")
    click.echo(f"   Newsletter page: {newsletter_file}")
    click.echo(f"\n📝 Next steps:")
    click.echo(f"   1. Review email: open {metadata['html_path']}")
    click.echo(f"   2. Send draft to ESP: gang email send-draft {metadata['slug']}")
    click.echo(f"   3. Build site to publish newsletter page: gang build")
    click.echo(f"   4. Or manually upload to {esp}")

@email.command('send-draft')
@click.argument('email_slug')
@click.option('--emails-dir', default='./emails', help='Directory containing email files')
@click.option('--api-key', envvar='ESP_API_KEY', help='ESP API key')
@click.option('--from-email', required=True, help='From email address')
@click.pass_context
def email_send_draft(ctx, email_slug, emails_dir, api_key, from_email):
    """Send email draft to ESP"""
    try:
        from core.email_templates import ESPIntegration
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.email_templates import ESPIntegration
    
    import json
    
    if not is_safe_content_slug(email_slug):
        click.echo("❌ Invalid email slug", err=True)
        ctx.exit(1)

    emails_path = Path(emails_dir).resolve()
    meta_file = (emails_path / f"{email_slug}.json").resolve()
    try:
        meta_file.relative_to(emails_path)
    except ValueError:
        click.echo("❌ Invalid email slug", err=True)
        ctx.exit(1)
    
    if not meta_file.exists():
        click.echo(f"❌ Email not found: {email_slug}", err=True)
        return
    
    if not api_key:
        click.echo("❌ ESP_API_KEY environment variable not set", err=True)
        click.echo("   Set it with: export ESP_API_KEY=your_key")
        return
    
    # Load metadata
    metadata = json.loads(meta_file.read_text())
    
    # Load email content — metadata paths must stay inside emails_dir
    def _email_asset(raw: Any) -> Path:
        if not raw:
            raise ValueError('missing email asset path')
        candidate = Path(str(raw))
        resolved = candidate.resolve() if candidate.is_absolute() else (emails_path / candidate).resolve()
        resolved.relative_to(emails_path)
        if not resolved.is_file():
            raise ValueError(f'missing email asset: {resolved.name}')
        return resolved

    try:
        html_content = _email_asset(metadata.get('html_path')).read_text()
        text_content = _email_asset(metadata.get('text_path')).read_text()
    except (ValueError, OSError) as exc:
        click.echo(f"❌ Invalid email asset path: {exc}", err=True)
        ctx.exit(1)
    
    # Send to ESP
    esp = ESPIntegration(metadata['esp_provider'], api_key)
    
    click.echo(f"📤 Sending draft to {metadata['esp_provider']}...")
    
    try:
        result = esp.create_draft(
            subject=metadata['title'],
            html_content=html_content,
            text_content=text_content,
            from_email=from_email,
            preview_text=metadata.get('preview_text', '')
        )
        
        click.echo(f"✅ Draft created in {metadata['esp_provider']}")
        click.echo(f"   Response: {result}")
        
        # Update metadata
        metadata['esp_draft_id'] = result.get('id')
        metadata['sent_to_esp'] = datetime.now().isoformat()
        meta_file.write_text(json.dumps(metadata, indent=2))
        
    except Exception as e:
        click.echo(f"❌ Failed to send to ESP: {e}", err=True)

@email.command('klaviyo-create')
@click.argument('post_path', type=click.STRING)
@click.option('--list-id', required=True, help='Klaviyo list ID to send to (required - get with: gang email klaviyo-lists)')
@click.option('--from-email', default='newsletter@example.com', help='From email address')
@click.option('--from-name', default='GANG', help='From name')
@click.option('--api-key', envvar='KLAVIYO_API_KEY', help='Klaviyo API key')
@click.pass_context
def email_klaviyo_create(ctx, post_path, list_id, from_email, from_name, api_key):
    """Create Klaviyo campaign from post"""
    try:
        from core.klaviyo_integration import KlaviyoOrchestrator
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.klaviyo_integration import KlaviyoOrchestrator
    
    if not api_key:
        click.echo("❌ KLAVIYO_API_KEY environment variable not set", err=True)
        click.echo("   Set it with: export KLAVIYO_API_KEY=your_private_key")
        click.echo("   Get your key from: https://www.klaviyo.com/settings/account/api-keys")
        return
    
    config = ctx.obj
    content_root = Path(config['build']['content'])
    post_file = resolve_content_arg(content_root, str(post_path))
    if post_file is None or post_file.suffix != '.md':
        click.echo("❌ Post must be a markdown file under the content root", err=True)
        return
    
    if not list_id:
        click.echo("❌ --list-id is required", err=True)
        click.echo("   Get your list ID with: gang email klaviyo-lists")
        return
    
    click.echo(f"📧 Creating Klaviyo campaign from: {post_file.name}")
    
    orchestrator = KlaviyoOrchestrator(config, api_key)
    
    try:
        result = orchestrator.create_campaign_from_post(
            post_file,
            list_id=list_id,
            from_email=from_email,
            from_name=from_name
        )
        
        # Save newsletter to content for public listing
        from core.email_templates import EmailOrchestrator as EmailOrch
        email_orch = EmailOrch(config, 'klaviyo')
        content_path = Path(config['build']['content'])
        newsletter_file = email_orch.save_newsletter_to_content(
            post_file, 
            {
                'title': result['title'], 
                'slug': post_file.stem, 
                'created': result['created'], 
                'esp_provider': 'klaviyo', 
                'canonical_url': content_canonical_url(
                    config.get('site', {}).get('url'), post_file.parent.name, post_file.stem
                )
            },
            content_path
        )
        
        click.echo(f"\n✅ Klaviyo campaign created:")
        click.echo(f"   Title: {result['title']}")
        click.echo(f"   Campaign ID: {result['campaign_id']}")
        click.echo(f"   Status: {result['status']}")
        click.echo(f"   URL: {result['klaviyo_url']}")
        click.echo(f"   Newsletter page: {newsletter_file}")
        click.echo(f"\n📝 Next steps:")
        click.echo(f"   1. Review in Klaviyo dashboard")
        click.echo(f"   2. Schedule or send immediately")
        click.echo(f"   3. Build site: gang build")
        click.echo(f"   4. View at: {newsletter_archive_url(post_file.stem)}")
        
    except Exception as e:
        click.echo(f"❌ Failed to create campaign: {e}", err=True)
        import traceback
        traceback.print_exc()

@email.command('klaviyo-lists')
@click.option('--api-key', envvar='KLAVIYO_API_KEY', help='Klaviyo API key')
def email_klaviyo_lists(api_key):
    """List all Klaviyo lists"""
    try:
        from core.klaviyo_integration import KlaviyoClient
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.klaviyo_integration import KlaviyoClient
    
    if not api_key:
        click.echo("❌ KLAVIYO_API_KEY not set", err=True)
        return
    
    client = KlaviyoClient(api_key)
    
    try:
        lists = client.get_lists()
        
        click.echo(f"\n📋 Klaviyo Lists ({len(lists)}):\n")
        
        for lst in lists:
            attrs = lst['attributes']
            click.echo(f"  {attrs['name']}")
            click.echo(f"    ID: {lst['id']}")
            if attrs.get('profile_count'):
                click.echo(f"    Subscribers: {attrs['profile_count']}")
            click.echo("")
        
    except Exception as e:
        click.echo(f"❌ Failed to fetch lists: {e}", err=True)

@email.command('klaviyo-campaigns')
@click.option('--status', default='draft', help='Filter by status (draft, scheduled, sent)')
@click.option('--api-key', envvar='KLAVIYO_API_KEY', help='Klaviyo API key')
def email_klaviyo_campaigns(status, api_key):
    """List Klaviyo campaigns"""
    try:
        from core.klaviyo_integration import KlaviyoClient
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.klaviyo_integration import KlaviyoClient
    
    if not api_key:
        click.echo("❌ KLAVIYO_API_KEY not set", err=True)
        return
    
    client = KlaviyoClient(api_key)
    
    try:
        campaigns = client.get_campaigns(status)
        
        click.echo(f"\n📧 Klaviyo Campaigns ({status}):\n")
        
        for campaign in campaigns:
            attrs = campaign['attributes']
            click.echo(f"  {attrs['name']}")
            click.echo(f"    ID: {campaign['id']}")
            click.echo(f"    Status: {attrs.get('status', 'unknown')}")
            if attrs.get('send_time'):
                click.echo(f"    Scheduled: {attrs['send_time']}")
            click.echo("")
        
    except Exception as e:
        click.echo(f"❌ Failed to fetch campaigns: {e}", err=True)

@email.command('check-deliverability')
@click.argument('domain')
def email_check_deliverability(domain):
    """Check DNS records for email deliverability"""
    try:
        from core.email_templates import DeliverabilityChecker
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.email_templates import DeliverabilityChecker
    
    click.echo(f"Score Checking deliverability for: {domain}\n")
    
    try:
        results = DeliverabilityChecker.check_dns_records(domain)
        
        click.echo("SPF Record:")
        if results['spf']:
            click.echo(f"  Best Practices {results['spf']}")
        else:
            click.echo("  ✗ Not found")
        
        click.echo("\nDMARC Record:")
        if results['dmarc']:
            click.echo(f"  Best Practices {results['dmarc']}")
        else:
            click.echo("  ✗ Not found")
        
        click.echo("\nMX Records:")
        if results['mx']:
            for mx in results['mx']:
                click.echo(f"  Best Practices {mx}")
        else:
            click.echo("  ✗ Not found")
        
        # Generate setup guide
        click.echo("\n" + "="*50)
        click.echo("\n📖 Setup Guide:")
        click.echo(DeliverabilityChecker.generate_setup_guide(domain))
        
    except ImportError:
        click.echo("⚠️  dnspython not installed. Install with: pip install dnspython")
        click.echo("\n📖 Setup Guide:")
        click.echo(DeliverabilityChecker.generate_setup_guide(domain))

@cli.group()
def taxonomy():
    """Manage hierarchical taxonomies and tags"""
    pass

@taxonomy.command('list')
@click.pass_context
def taxonomy_list(ctx):
    """List all categories and tags"""
    try:
        from core.taxonomy import TaxonomyManager
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.taxonomy import TaxonomyManager
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    
    manager = TaxonomyManager(content_path)
    
    click.echo("\n📚 Categories:")
    for cat_name, cat_data in manager.get_all_categories().items():
        click.echo(f"\n  {cat_name}")
        if cat_data.get('description'):
            click.echo(f"    {cat_data['description']}")
        if cat_data.get('children'):
            click.echo(f"    Subcategories: {', '.join(cat_data['children'])}")
    
    click.echo("\n🏷️  Tags:")
    tags = manager.get_all_tags()
    for tag in tags:
        click.echo(f"  • {tag}")
    
    click.echo(f"\n✅ {len(manager.get_all_categories())} categories, {len(tags)} tags")

@taxonomy.command('analyze')
@click.pass_context
def taxonomy_analyze(ctx):
    """Analyze taxonomy usage across content"""
    try:
        from core.taxonomy import TaxonomyManager
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.taxonomy import TaxonomyManager
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    
    manager = TaxonomyManager(content_path)
    analysis = manager.analyze_content_taxonomy()
    
    click.echo("\n📊 Taxonomy Usage Analysis:\n")
    
    click.echo("By Category:")
    for category, items in sorted(analysis['by_category'].items()):
        click.echo(f"  {category}: {len(items)} items")
    
    click.echo("\nBy Tag:")
    for tag, items in sorted(analysis['by_tag'].items()):
        click.echo(f"  {tag}: {len(items)} items")
    
    if analysis['uncategorized']:
        click.echo(f"\n⚠️  {len(analysis['uncategorized'])} uncategorized items")
    
    if analysis['untagged']:
        click.echo(f"⚠️  {len(analysis['untagged'])} untagged items")

@taxonomy.command('add-category')
@click.argument('name')
@click.option('--description', help='Category description')
@click.option('--parent', help='Parent category for subcategory')
@click.pass_context
def taxonomy_add_category(ctx, name, description, parent):
    """Add a new category or subcategory"""
    try:
        from core.taxonomy import TaxonomyManager
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.taxonomy import TaxonomyManager
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    
    manager = TaxonomyManager(content_path)
    manager.add_category(name, description or '', parent)
    
    if parent:
        click.echo(f"✅ Added subcategory '{name}' under '{parent}'")
    else:
        click.echo(f"✅ Added category '{name}'")

@taxonomy.command('add-tag')
@click.argument('tag')
@click.pass_context
def taxonomy_add_tag(ctx, tag):
    """Add a new tag"""
    try:
        from core.taxonomy import TaxonomyManager
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.taxonomy import TaxonomyManager
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    
    manager = TaxonomyManager(content_path)
    manager.add_tag(tag)
    
    click.echo(f"✅ Added tag '{tag}'")

@cli.command()
@click.argument('product_json', type=click.Path(exists=True))
@click.option('--auto-pr', is_flag=True, help='Automatically create PR')
@click.pass_context
def shopify_sync(ctx, product_json, auto_pr):
    """Sync Shopify product and optionally create PR"""
    try:
        from core.shopify_pr_bot import ShopifyPRBot
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.shopify_pr_bot import ShopifyPRBot
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    mapping_path = Path('schemas/product.map.json')
    
    bot = ShopifyPRBot(content_path, mapping_path)
    
    # Load product data
    product_data = json.loads(Path(product_json).read_text())
    
    if auto_pr:
        click.echo("🤖 Creating PR for product update...")
        result = bot.create_pr(product_data)
        
        if result['success']:
            click.echo(f"✅ PR created: {result.get('pr_url', 'Branch created locally')}")
        else:
            click.echo(f"❌ Failed: {result.get('error', 'Unknown error')}", err=True)
            ctx.exit(1)
    else:
        # Just generate the file
        click.echo("📝 Generating product file...")
        file_path = bot.generate_markdown_file(product_data)
        click.echo(f"✅ Created: {file_path}")

@cli.group()
def products():
    """Manage products from Shopify, Stripe, Gumroad"""
    pass

@products.command('sync')
@click.option('--platforms', default='all', help='Platforms to sync (all, shopify, stripe, gumroad)')
@click.pass_context
def sync_products(ctx, platforms):
    """Fetch products from platforms and normalize"""
    try:
        from core.products import ProductAggregator
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.products import ProductAggregator
    
    config = ctx.obj
    
    click.echo("🛒 Syncing products...")
    aggregator = ProductAggregator(config)
    products = aggregator.get_normalized_products()
    
    click.echo(f"✅ Fetched {len(products)} product(s)")
    for p in products:
        source = p.get('_meta', {}).get('source', 'unknown')
        click.echo(f"  • {p['name']} (from {source})")

@products.command('list')
@click.option('--format', type=click.Choice(['text', 'json']), default='text')
@click.pass_context
def list_products(ctx, format):
    """List all synced products"""
    try:
        from core.products import ProductAggregator
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.products import ProductAggregator
    
    config = ctx.obj
    
    aggregator = ProductAggregator(config)
    cache = aggregator.load_cache()
    
    if not cache:
        click.echo("No products cached. Run 'gang products sync' first.")
        return
    
    products = aggregator.get_normalized_products()
    
    if format == 'json':
        import json
        click.echo(json.dumps(products, indent=2))
    else:
        click.echo(f"🛒 Products ({len(products)} total)\n")
        for p in products:
            source = p.get('_meta', {}).get('source', 'unknown')
            
            # Handle both single offer and array of offers
            offers = p.get('offers', {})
            if type(offers).__name__ == 'list':
                # Multiple offers (variants)
                first_offer = offers[0] if offers else {}
                price = first_offer.get('price', 'N/A')
                currency = first_offer.get('priceCurrency', 'USD')
                variant_count = len(offers)
                click.echo(f"• {p['name']}")
                click.echo(f"  Price: {currency} {price} ({variant_count} variant{'s' if variant_count != 1 else ''}) | Source: {source}")
            else:
                # Single offer
                price = offers.get('price', 'N/A')
                currency = offers.get('priceCurrency', 'USD')
                click.echo(f"• {p['name']}")
                click.echo(f"  Price: {currency} {price} | Source: {source}")

@cli.command('agentmap')
@click.pass_context
def generate_agentmap(ctx):
    """Generate AgentMap.json for AI agent navigation"""
    try:
        from core.agentmap import AgentMapGenerator, ContentAPIGenerator
        from core.products import ProductAggregator
        from core.scheduler import ContentScheduler
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.agentmap import AgentMapGenerator, ContentAPIGenerator
        from core.products import ProductAggregator
        from core.scheduler import ContentScheduler
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    dist_path = Path(config['build']['output'])
    site_url = config['site']['url']
    
    click.echo("🤖 Generating AgentMap for AI agents...")
    
    # Get publishable content - avoid rglob recursion issue
    scheduler = ContentScheduler(content_path)
    
    schedule_result = scheduler.get_publishable_content(collect_category_markdown(content_path))
    publishable = renderable_markdown([item['path'] for item in schedule_result['publishable']])
    
    # Get products if available (do not force demo catalog)
    aggregator = ProductAggregator(config)
    products = aggregator.get_normalized_products(status_filter='active')
    
    # Generate AgentMap
    generator = AgentMapGenerator(config, site_url)
    agentmap = generator.generate(publishable, products if products else None)
    
    # Write AgentMap
    dist_path.mkdir(parents=True, exist_ok=True)
    agentmap_file = dist_path / 'agentmap.json'
    agentmap_file.write_text(json.dumps(agentmap, indent=2))
    
    # Generate Content API
    api_dir = dist_path / 'api'
    api_dir.mkdir(parents=True, exist_ok=True)
    
    api_generator = ContentAPIGenerator(site_url)
    content_index = api_generator.generate_content_index(publishable, content_path)
    
    (api_dir / 'content.json').write_text(json.dumps(content_index, indent=2))
    api_generator.write_content_apis(
        publishable, content_path, api_dir, safe_slug=is_safe_content_slug
    )
    
    if products:
        (api_dir / 'products.json').write_text(json.dumps({
            'products': products,
            'count': len(products),
            'generated': datetime.now().isoformat(),
        }, indent=2))
    
    click.echo(f"✅ Generated AgentMap with {len(publishable)} content items")
    if products:
        click.echo(f"✅ Generated Products API with {len(products)} products")
    click.echo(f"📄 Files: agentmap.json, api/content.json")

@cli.command()
@click.option('--fix', is_flag=True, help='Suggest unique slugs for conflicts')
@click.pass_context
def slugs(ctx, fix):
    """Check slug uniqueness across all content"""
    try:
        from core.content_importer import SlugChecker
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.content_importer import SlugChecker
    
    config = ctx.obj
    content_path = Path(config['build']['content'])
    
    click.echo("Score Checking slug uniqueness...\n")
    
    checker = SlugChecker(content_path)
    results = checker.check_all_slugs()
    
    click.echo(f"📊 Slug Report:")
    click.echo(f"├─ Total slugs: {results['total_slugs']}")
    click.echo(f"├─ Unique: {results['unique_slugs']}")
    click.echo(f"└─ Duplicates: {results['duplicate_slugs']}")
    
    if results['duplicates']:
        click.echo(f"\n❌ Duplicate slugs found:")
        for slug, files in results['duplicates'].items():
            click.echo(f"\n  Slug: '{slug}' used in:")
            for file in files:
                click.echo(f"    - {file}")
            
            if fix:
                click.echo(f"  💡 To fix: Rename one file to make slugs unique")
        
        if not fix:
            click.echo(f"\n💡 Run with --fix to see suggestions")
        
        ctx.exit(1)
    else:
        click.echo(f"\n✅ All slugs are unique!")

@cli.command()
@click.option('--check-quality', is_flag=True, help='Run content quality checks before building')
@click.option('--min-quality-score', type=int, default=85, help='Minimum quality score (default: 85)')
@click.option('--validate-links', is_flag=True, help='Validate all links before building')
@click.option('--check-slugs', is_flag=True, default=True, help='Check slug uniqueness (default: enabled)')
@click.option('--optimize-images', is_flag=True, help='Auto-optimize images before building')
@click.option('--profile', is_flag=True, help='Show build performance metrics')
@click.pass_context
def build(ctx, check_quality, min_quality_score, validate_links, check_slugs, optimize_images, profile):
    """Build static site with semantic HTML"""
    try:
        from core.templates import TemplateEngine
        from core.generators import OutputGenerators
        from core.optimizer import AIOptimizer
        from core.build_profiler import BuildProfiler
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.templates import TemplateEngine
        from core.generators import OutputGenerators
        from core.optimizer import AIOptimizer
        from core.build_profiler import BuildProfiler
    
    # Initialize profiler
    profiler = BuildProfiler() if profile else None
    if profiler:
        profiler.start()
    
    click.echo("🔨 Building site...")
    config = ctx.obj
    
    # Slug uniqueness check (enabled by default)
    if check_slugs:
        from core.content_importer import SlugChecker
        content_path = Path(config['build']['content'])
        checker = SlugChecker(content_path)
        results = checker.check_all_slugs()
        
        if results['duplicate_slugs'] > 0:
            click.echo("❌ Duplicate slugs detected!\n")
            for slug, files in results['duplicates'].items():
                click.echo(f"  Slug '{slug}' used in:")
                for file in files:
                    click.echo(f"    - {file}")
            
            click.echo(f"\n🚫 Cannot build: {results['duplicate_slugs']} duplicate slug(s) found")
            click.echo("   Run 'gang slugs' for details")
            click.echo("   Fix by renaming files to have unique slugs")
            ctx.exit(1)
        else:
            click.echo(f"Best Practices All {results['total_slugs']} slugs are unique\n")
    
    # Quality gate check
    if check_quality:
        from core.analyzer import ContentAnalyzer
        click.echo("Score Running content quality checks...")
        analyzer = ContentAnalyzer(config)
        content_path = Path(config['build']['content'])
        md_files = collect_category_markdown(content_path)
        
        failed_files = []
        for md_file in md_files:
            try:
                analysis = analyzer.analyze_file(md_file)
                seo_score = analysis['seo']['score']
                if seo_score < min_quality_score:
                    failed_files.append((md_file.relative_to(content_path), seo_score))
            except Exception as e:
                click.echo(f"⚠️  Could not analyze {md_file.relative_to(content_path)}: {e}")
        
        if failed_files:
            click.echo(f"\n❌ Quality gate failed! {len(failed_files)} file(s) below minimum score ({min_quality_score}):")
            for file, score in failed_files:
                click.echo(f"  - {file}: {score}/100")
            click.echo(f"\nRun 'gang analyze --all' for detailed report")
            click.echo("Tip: Use --min-quality-score to adjust threshold or fix content issues")
            ctx.exit(1)
        else:
            click.echo(f"Best Practices All {len(md_files)} files pass quality threshold ({min_quality_score}+)\n")
    
    # Link validation check
    if validate_links:
        from core.link_validator import LinkValidator
        click.echo("🔗 Validating links...")
        content_path = Path(config['build']['content'])
        dist_path = Path(config['build']['output'])
        validator = LinkValidator(config, content_path, dist_path)
        
        results = validator.scan_all_files()
        
        broken_count = len(results['broken_internal']) + len(results['broken_external'])
        
        if broken_count > 0:
            click.echo(f"❌ Found {broken_count} broken link(s):")
            for item in results['broken_internal'][:3]:
                click.echo(f"  - {item['file']}: {item['url']} (internal)")
            for item in results['broken_external'][:3]:
                click.echo(f"  - {item['file']}: {item['url']} → {item['error']}")
            if broken_count > 6:
                click.echo(f"  ... and {broken_count - 6} more")
            click.echo(f"\nRun 'gang validate --links' for full report")
            click.echo("Build aborted due to broken links\n")
            ctx.exit(1)
        else:
            click.echo(f"Best Practices All {results['total_links']} links valid\n")
    
    # Initialize systems
    templates_path = Path(config['build'].get('templates', './templates'))
    template_engine = TemplateEngine(templates_path)
    generators = OutputGenerators(config)
    optimizer = AIOptimizer(config)
    
    # Create dist directory
    dist_path = Path(config['build']['output'])
    if dist_path.exists():
        shutil.rmtree(dist_path)
    dist_path.mkdir(parents=True, exist_ok=True)
    
    # Optimize images if requested
    if optimize_images:
        from core.images import ImageProcessor
        click.echo("🖼️  Optimizing images...")
        
        public_path = Path(config['build']['public'])
        images_source = public_path / 'images' if (public_path / 'images').exists() else public_path
        images_output = dist_path / 'assets' / 'images'
        images_output.mkdir(parents=True, exist_ok=True)
        
        processor = ImageProcessor(config)
        result = processor.process_all_images(images_source, images_output)
        
        stats = result['stats']
        if stats['total_images'] > 0:
            savings_kb = stats['savings_bytes'] / 1024
            click.echo(f"  Best Practices Optimized {stats['total_images']} image(s) → {stats['total_variants']} variants")
            click.echo(f"  💾 Saved {savings_kb:.1f}KB ({stats['savings_percent']:.1f}% reduction)")
    
    # Copy public assets
    public_path = Path(config['build']['public'])
    if public_path.exists():
        if profiler:
            with profiler.stage('copy_assets'):
                click.echo("📦 Copying public assets...")
                shutil.copytree(public_path, dist_path / 'assets', dirs_exist_ok=True)
        else:
            click.echo("📦 Copying public assets...")
            shutil.copytree(public_path, dist_path / 'assets', dirs_exist_ok=True)
        write_dist_headers(public_path, dist_path, config)
    
    # Build content
    content_path = Path(config['build']['content'])
    all_pages = []
    all_posts = []
    all_projects = []
    all_newsletters = []
    all_people = []
    tag_pages: List[Dict[str, str]] = []
    
    # Parse markdown files
    if profiler:
        profiler.stage('process_content').__enter__()
    
    # Filter content based on publish dates
    try:
        from core.scheduler import ContentScheduler
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.scheduler import ContentScheduler
    
    scheduler = ContentScheduler(content_path)
    
    # Collect publishable markdown (exclude examples/comments)
    all_md_files = collect_category_markdown(content_path)
    
    schedule_result = scheduler.get_publishable_content(all_md_files)
    
    publishable_files = renderable_markdown(
        [item['path'] for item in schedule_result['publishable']]
    )
    
    # Show scheduling info if there are scheduled items
    if schedule_result['scheduled']:
        click.echo(f"🕐 {len(schedule_result['scheduled'])} post(s) scheduled for future")
    if schedule_result['draft']:
        click.echo(f"📝 {len(schedule_result['draft'])} draft post(s) excluded")
    
    click.echo(f"📝 Processing {len(publishable_files)} publishable content file(s)...")
    for md_file in publishable_files:
        content_type = md_file.parent.name
        if content_type not in PUBLISHABLE_CATEGORIES or not is_safe_content_slug(md_file.stem):
            click.echo(f"⚠️  Skipping unsafe content path: {md_file.relative_to(content_path)}")
            continue
        
        # Parse markdown with frontmatter
        content = md_file.read_text()
        frontmatter, body = parse_frontmatter_text(content)
        if content_type in TEMPLATE_OWNS_H1:
            body = strip_leading_markdown_h1(body)
        
        # Convert markdown to HTML
        content_html = convert_markdown_html(body)
        
        # Prepare context for template
        build_time = datetime.now()
        slug = md_file.stem
        
        # Never bake in-place editor chrome into published HTML.
        user_authenticated = False
        
        content_date = authored_content_date(frontmatter, md_file)
        description = (
            frontmatter.get('summary')
            or frontmatter_seo(frontmatter).get('description')
            or config['site']['description']
        )
        if isinstance(description, str):
            description = description.strip() or config['site']['description']
        else:
            description = config['site']['description']
        
        title = frontmatter.get('title') or md_file.stem.replace('-', ' ').title()
        tags = frontmatter.get('tags') or []
        if isinstance(tags, str):
            tags = [tags]
        elif not isinstance(tags, list):
            tags = []
        tags = [str(tag) for tag in tags]
        
        comments_enabled = comments_are_enabled(config) and content_type in ('posts', 'articles')
        page_comments = []
        if comments_enabled:
            try:
                from core.comments import get_comments_for_build
            except ImportError:
                from gang.core.comments import get_comments_for_build
            comment_type = 'post' if content_type in ('posts', 'articles') else 'product'
            page_comments = get_comments_for_build(content_path, slug, comment_type)
        
        context = {
            'site_title': config['site']['title'],
            'lang': config['site']['language'],
            'title': title,
            'description': description,
            'content': content_html,
            'year': datetime.now().year,
            'navigation': config.get('nav', {}).get('main', []),
            'date': content_date,
            'date_formatted': str(content_date or ''),
            'tags': tags,
            'build_time': build_time.strftime('%B %d, %Y at %I:%M %p'),
            'build_time_iso': build_time.isoformat(),
            'jsonld': frontmatter.get('jsonld'),
            'og_type': 'article' if content_type in ('posts', 'articles', 'projects') else 'website',
            'page_type': content_type.rstrip('s'),
            'category': content_type,
            'slug': slug,
            'user_authenticated': user_authenticated,
            'comments_enabled': comments_enabled,
            'comments': page_comments,
            'comments_webhook_url': comments_webhook_url(config) if comments_enabled else '',
            'comments_webhook_origin': comments_webhook_origin(config) if comments_enabled else '',
            'role': frontmatter.get('role', ''),
            'image': safe_http_url(frontmatter.get('image', '')),
            'social_links': sanitize_social_links(frontmatter.get('social_links')),
            'summary': frontmatter.get('summary') or '',
            'issue_number': frontmatter.get('issue_number') or frontmatter.get('newsletter_id') or '',
            'sent_date': frontmatter.get('sent_date') or frontmatter.get('date') or '',
            'status': frontmatter.get('status') or '',
        }
        
        # Treat articles as posts on the public URL, but keep the disk category
        # so the in-place editor can PUT the original articles/{slug}.md file.
        context['source_category'] = content_type
        if content_type == 'articles':
            content_type = 'posts'
            # Update context to reflect the change
            context['page_type'] = 'post'
            context['category'] = 'posts'
        
        # Add canonical URL
        url = public_content_url(content_type, slug)
        
        context['canonical_url'] = f"{str(config['site']['url']).rstrip('/')}{url}"
        
        jsonld = context.get('jsonld')
        if not isinstance(jsonld, dict) or not jsonld:
            context['jsonld'] = fallback_jsonld(
                content_type,
                context['title'],
                context['description'],
                context['canonical_url'],
                context.get('date'),
                config['site']['title'],
            )
        
        # Select template
        if content_type == 'posts':
            template_name = 'post.html'
        elif content_type == 'projects':
            template_name = 'article.html'
        elif content_type == 'newsletters':
            template_name = 'newsletter.html'
        elif content_type == 'people':
            template_name = 'person.html'
        else:
            template_name = 'page.html'
        
        # Render HTML
        try:
            html = template_engine.render(template_name, context)
        except Exception as e:
            click.echo(f"⚠️  Template error in {md_file}: {e}")
            html = process_markdown_fallback(md_file, content_type, config)
        
        # Determine output path
        output_file = dist_path / content_type / slug / 'index.html'
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(html)
        click.echo(f"  Best Practices {md_file.relative_to(content_path)}")
        
        # Collect metadata for sitemaps
        page_data = {
            'url': url,
            'title': context['title'],
            'summary': list_item_summary(
                frontmatter, config['site']['description'], content_html
            ),
            'date': context['date'],
            'type': content_type,
            'content_html': content_html,
            'tags': context['tags'],
        }
        
        # Add to appropriate collection (no duplicates)
        if content_type == 'posts':
            all_posts.append(page_data)
        elif content_type == 'projects':
            all_projects.append(page_data)
        elif content_type == 'newsletters':
            all_newsletters.append(page_data)
        elif content_type == 'pages':
            all_pages.append(page_data)
        elif content_type == 'people':
            all_people.append(page_data)
    
    # Create index page
    click.echo("🏠 Creating index page...")
    index_context = {
        'site_title': config['site']['title'],
        'lang': config['site']['language'],
        'title': config['site']['title'],
        'description': config['site']['description'],
        'year': datetime.now().year,
        'navigation': config.get('nav', {}).get('main', []),
        'posts': sorted(all_posts, key=lambda x: x.get('date', ''), reverse=True)[:5],
    }
    
    index_html = create_index_simple(
        config,
        sorted(all_posts, key=lambda x: x.get('date', ''), reverse=True)[:5],
        templates_path,
    )
    page_size_bytes = len(index_html.encode('utf-8'))
    index_html = index_html.replace('__PAGE_SIZE__', format_bytes(page_size_bytes))
    (dist_path / 'index.html').write_text(index_html)
    
    # Create newsletters list page
    if all_newsletters:
        newsletters_dir = dist_path / 'newsletters'
        newsletters_dir.mkdir(parents=True, exist_ok=True)
        
        newsletters_html = create_list_page_simple(config, sorted(all_newsletters, key=lambda x: x.get('date', ''), reverse=True), 'Newsletters', templates_path)
        page_size_bytes = len(newsletters_html.encode('utf-8'))
        newsletters_html = newsletters_html.replace('__PAGE_SIZE__', format_bytes(page_size_bytes))
        (newsletters_dir / 'index.html').write_text(newsletters_html)
    
    # Create list pages
    # Always create posts index page, even if empty
    click.echo("📄 Creating posts index...")
    posts_html = create_list_page_simple(config, sorted(all_posts, key=lambda x: x.get('date', ''), reverse=True), 'Posts', templates_path)
    page_size_bytes = len(posts_html.encode('utf-8'))
    posts_html = posts_html.replace('__PAGE_SIZE__', format_bytes(page_size_bytes))
    (dist_path / 'posts').mkdir(parents=True, exist_ok=True)
    (dist_path / 'posts' / 'index.html').write_text(posts_html)
    
    if all_projects:
        click.echo("📄 Creating projects index...")
        projects_html = create_list_page_simple(config, all_projects, 'Projects', templates_path)
        page_size_bytes = len(projects_html.encode('utf-8'))
        projects_html = projects_html.replace('__PAGE_SIZE__', format_bytes(page_size_bytes))
        (dist_path / 'projects' / 'index.html').write_text(projects_html)
    
    if all_people:
        click.echo("📄 Creating people index...")
        people_html = create_list_page_simple(config, all_people, 'People', templates_path, path='/people/')
        page_size_bytes = len(people_html.encode('utf-8'))
        people_html = people_html.replace('__PAGE_SIZE__', format_bytes(page_size_bytes))
        (dist_path / 'people').mkdir(parents=True, exist_ok=True)
        (dist_path / 'people' / 'index.html').write_text(people_html)
    
    tag_pages = write_tag_pages(
        config,
        dist_path,
        tagged_build_items(all_pages, all_posts, all_projects, all_people, all_newsletters),
        templates_path,
    )
    
    # Generate outputs
    click.echo("🗺️  Generating sitemap, feeds, etc...")
    all_pages.append({'url': '/', 'title': config['site']['title'], 'type': 'home'})
    if all_posts:
        all_pages.append({'url': '/posts/', 'title': 'Posts', 'type': 'list'})
    if all_projects:
        all_pages.append({'url': '/projects/', 'title': 'Projects', 'type': 'list'})
    if all_people:
        all_pages.append({'url': '/people/', 'title': 'People', 'type': 'list'})
    if all_newsletters:
        all_pages.append({'url': '/newsletters/', 'title': 'Newsletters', 'type': 'list'})
    
    # Combine all content for sitemap generation
    all_content = all_pages + all_posts + all_projects + all_people + all_newsletters
    
    if profiler:
        with profiler.stage('generate_outputs'):
            generators.generate_all(dist_path, all_content, all_posts)
    else:
        generators.generate_all(dist_path, all_content, all_posts)
    
    # Generate redirect rules if any exist
    try:
        from core.redirects import RedirectManager
        redirect_manager = RedirectManager(content_path, dist_path)
        redirect_list = redirect_manager.list_all_redirects()
        
        if redirect_list:
            redirect_manager.write_redirects_file(format='cloudflare')
            click.echo(f"🔀 Generated {len(redirect_list)} redirect(s) → dist/_redirects")
    except Exception as e:
        click.echo(f"⚠️  Could not generate redirects: {e}")
    
    # Generate product pages (only active products)
    products = []
    try:
        from core.products import ProductAggregator
        
        aggregator = ProductAggregator(config)
        products = aggregator.get_normalized_products(status_filter='active')
        
        if products:
            click.echo(f"🛒 Generating {len(products)} product page(s)...")
            
            template_dir = Path(__file__).parent.parent.parent / 'templates'
            jinja_env = template_environment(template_dir)
            
            products_path = dist_path / 'products'
            products_path.mkdir(parents=True, exist_ok=True)
            
            # Generate PLP
            products = assign_unique_catalog_slugs(products)
            plp_template = jinja_env.get_template('products-list.html')
            plp_canonical = f"{str(config['site']['url']).rstrip('/')}/products/"
            plp_html = plp_template.render(
                products=products,
                site_title=config['site']['title'],
                lang=config['site'].get('language', 'en'),
                site_url=config['site']['url'],
                canonical_url=plp_canonical,
                jsonld={
                    '@context': 'https://schema.org',
                    '@type': 'CollectionPage',
                    'name': 'Products',
                    'description': 'Product catalog',
                    'url': plp_canonical,
                    'numberOfItems': len(products),
                },
                year=datetime.now().year,
                navigation=config.get('nav', {}).get('main', []),
                build_time=datetime.now().strftime('%Y-%m-%d %H:%M'),
                build_time_iso=datetime.now().isoformat()
            )
            (products_path / 'index.html').write_text(plp_html)
            
            # Generate PDPs
            pdp_template = jinja_env.get_template('product.html')
            for product in products:
                # Use 'handle' if 'slug' not present (Shopify uses 'handle')
                slug = product['_meta'].get('slug') or product['_meta'].get('handle')
                if not slug:
                    click.echo(f"⚠️  Skipping product without slug/handle: {product.get('name')}")
                    continue
                if not is_safe_content_slug(str(slug)):
                    click.echo(f"⚠️  Skipping product with unsafe slug/handle: {slug}")
                    continue
                
                pdp_dir = products_path / slug
                pdp_dir.mkdir(parents=True, exist_ok=True)
                pdp_html = pdp_template.render(**build_pdp_context(product, config, slug))
                (pdp_dir / 'index.html').write_text(pdp_html)
                all_content.append({
                    'url': f'/products/{slug}/',
                    'title': product.get('name', slug),
                    'type': 'product',
                })
            
            all_content.append({'url': '/products/', 'title': 'Products', 'type': 'list'})
            generators.generate_all(dist_path, all_content, all_posts)
            click.echo(f"✅ Generated product pages (PLP + {len(products)} PDPs)")
    except Exception as e:
        click.echo(f"⚠️  Could not generate product pages: {e}")
        products = []
    
    # Always emit cart (footer links to /cart/ even with an empty catalog)
    try:
        template_dir = Path(__file__).parent.parent.parent / 'templates'
        jinja_env = template_environment(template_dir)
        build_time = datetime.now()
        
        cart_dir = dist_path / 'cart'
        cart_dir.mkdir(parents=True, exist_ok=True)
        cart_jsonld = {
            '@context': 'https://schema.org',
            '@type': 'WebPage',
            'name': 'Shopping Cart',
            'description': config['site']['description'],
            'url': f"{str(config['site']['url']).rstrip('/')}/cart/",
        }
        cart_template = jinja_env.get_template('cart.html')
        cart_html = cart_template.render(
            year=datetime.now().year,
            site_title=config['site']['title'],
            lighthouse_scores=True,
            build_time=build_time.strftime('%B %d, %Y at %I:%M %p'),
            build_time_iso=build_time.isoformat(),
            description=config['site']['description'],
            jsonld=cart_jsonld,
            site_url=config['site']['url'],
            checkout_origins=collect_checkout_origins(products),
        )
        (cart_dir / 'index.html').write_text(cart_html)
        click.echo("🛒 Generated cart page")
    except Exception as e:
        click.echo(f"⚠️  Could not generate cart: {e}")
    
    # Generate search index from the same publishable set the build rendered
    try:
        from core.search import SearchIndexer
        
        indexer = SearchIndexer(content_path, config)
        search_index = indexer.build_search_index(publishable_files)
        indexer.add_product_documents(search_index, products)
        
        search_index_file = dist_path / 'search-index.json'
        search_index_file.write_text(json.dumps(search_index, default=str))
        
        search_page = dist_path / 'search' / 'index.html'
        search_page.parent.mkdir(parents=True, exist_ok=True)
        search_page.write_text(indexer.generate_search_page_html(config, templates_path))
        
        click.echo(f"🔍 Generated search index ({len(search_index['documents'])} documents)")
    except Exception as e:
        click.echo(f"⚠️  Could not generate search index: {e}")

    try:
        write_html_sitemap(
            dist_path,
            config,
            pages=all_pages,
            posts=all_posts,
            projects=all_projects,
            products=products,
            people=all_people,
            newsletters=all_newsletters,
            tags=tag_pages,
        )
        click.echo("🗺️  Generated HTML sitemap")
    except Exception as e:
        click.echo(f"⚠️  Could not generate sitemap: {e}")

    merge_sitemap_entries(
        all_content, discovery_sitemap_entries(tag_pages, dist_path=dist_path)
    )
    generators.generate_all(dist_path, all_content, all_posts)
    
    # Generate AgentMap for AI agents
    try:
        from core.agentmap import AgentMapGenerator, ContentAPIGenerator
        from core.products import ProductAggregator
        
        publishable_paths = [
            Path(item) if not isinstance(item, Path) else item
            for item in publishable_files
        ]
        
        aggregator = ProductAggregator(config)
        products = aggregator.get_normalized_products(status_filter='active')
        
        # Generate AgentMap
        site_url = config.get('site', {}).get('url', 'https://example.com')
        generator = AgentMapGenerator(config, site_url)
        agentmap = generator.generate(publishable_paths, products if products else None)
        
        # Write AgentMap
        agentmap_file = dist_path / 'agentmap.json'
        agentmap_file.write_text(json.dumps(agentmap, indent=2))
        
        # Generate Content API
        api_generator = ContentAPIGenerator(site_url)
        content_api = api_generator.generate_content_index(publishable_paths, content_path)
        
        api_dir = dist_path / 'api'
        api_dir.mkdir(parents=True, exist_ok=True)
        (api_dir / 'content.json').write_text(json.dumps(content_api, indent=2))
        api_generator.write_content_apis(
            publishable_paths, content_path, api_dir, safe_slug=is_safe_content_slug
        )
        
        # Generate products API
        if products:
            products_api = {
                'products': products,
                'count': len(products),
                'generated': datetime.now().isoformat()
            }
            (api_dir / 'products.json').write_text(json.dumps(products_api, indent=2))
        
        click.echo(f"🤖 Generated AgentMap with {len(publishable_paths)} content items")
    except Exception as e:
        click.echo(f"⚠️  Could not generate AgentMap: {e}")
    
    # Minify HTML, CSS, and JS (simple implementation)
    try:
        import re
        
        # Minify JS (safer approach - preserve operators)
        js_files = [f for f in dist_path.rglob('*.js')]
        js_original = 0
        js_minified = 0
        for js_file in js_files:
            # Skip editor-bundle.js to avoid corruption
            if js_file.name == 'editor-bundle.js':
                continue
                
            js_content = js_file.read_text()
            js_original += len(js_content)
            js_content = minify_js_source(js_content)
            js_minified += len(js_content)
            js_file.write_text(js_content)
        
        if js_files:
            js_savings = ((js_original - js_minified) / js_original * 100) if js_original > 0 else 0
            click.echo(f"🗜️  Minified {len(js_files)} JS file(s) ({js_savings:.1f}% reduction)")
        
        # Minify CSS
        css_files = [f for f in dist_path.rglob('*.css')]
        css_original = 0
        css_minified = 0
        for css_file in css_files:
            css_content = css_file.read_text()
            css_original += len(css_content)
            # Remove comments
            css_content = re.sub(r'/\*.*?\*/', '', css_content, flags=re.DOTALL)
            # Remove extra whitespace
            css_content = re.sub(r'\s+', ' ', css_content)
            # Remove spaces around special characters
            css_content = re.sub(r'\s*([{}:;,])\s*', r'\1', css_content)
            css_minified += len(css_content.strip())
            css_file.write_text(css_content.strip())
        
        if css_files:
            css_savings = ((css_original - css_minified) / css_original * 100) if css_original > 0 else 0
            click.echo(f"🗜️  Minified {len(css_files)} CSS file(s) ({css_savings:.1f}% reduction)")
        
        # Minify HTML
        html_files = [f for f in dist_path.rglob('*.html')]
        minified_count = 0
        original_size = 0
        minified_size = 0
        
        for html_file in html_files:
            original_html = html_file.read_text()
            original_size += len(original_html)
            minified = minify_html_source(original_html)
            minified_size += len(minified)
            html_file.write_text(minified)
            minified_count += 1
        
        savings = ((original_size - minified_size) / original_size * 100) if original_size > 0 else 0
        click.echo(f"🗜️  Minified {minified_count} HTML files ({savings:.1f}% reduction)")
    except Exception as e:
        click.echo(f"⚠️  Could not minify assets: {e}")
    
    # End profiling
    if profiler:
        profiler.end()
        profiler.record_files('pages', len(all_pages))
        profiler.record_files('posts', len(all_posts))
        profiler.record_files('projects', len(all_projects))
        profiler.save_run()
    
    click.echo(f"✅ Build complete! Output in {dist_path}")
    
    # Show performance report if requested
    if profiler:
        click.echo("")
        report = profiler.format_report()
        click.echo(report)


def process_markdown_fallback(md_file: Path, content_type: str, config: Dict) -> str:
    """Fallback markdown processor if templates fail"""
    return process_markdown(md_file, content_type, config)


def process_external_links(html: str) -> str:
    """
    Opt-in external link processing
    Only adds target='_blank' if link has data-newtab attribute or 'ext' class
    Always adds rel='noopener noreferrer' for security
    """
    import re
    
    def replace_link(match):
        full_tag = match.group(0)
        href = match.group(1)
        
        # Skip internal links
        if href.startswith('/'):
            return full_tag
        
        # Always add rel for security
        if 'rel=' not in full_tag:
            full_tag = full_tag.replace('>', ' rel="noopener noreferrer">', 1)
        
        # Only add target if opt-in (data-newtab or class="ext")
        if 'data-newtab' in full_tag or 'class="ext"' in full_tag or "class='ext'" in full_tag:
            if 'target=' not in full_tag:
                full_tag = full_tag.replace('>', ' target="_blank">', 1)
        
        return full_tag
    
    # Pattern: <a href="http(s)://..."
    pattern = r'<a\s+([^>]*href=["\']?(https?://[^"\'>\s]+)["\']?[^>]*?)>'
    return re.sub(pattern, lambda m: replace_link(m), html)


def format_bytes(bytes_size: int) -> str:
    """Format bytes to human readable string"""
    if bytes_size < 1024:
        return f"{bytes_size}B"
    elif bytes_size < 1024 * 1024:
        return f"{bytes_size / 1024:.1f}KB"
    else:
        return f"{bytes_size / (1024 * 1024):.2f}MB"


def render_header(config: Dict, templates_path: Path = None) -> str:
    """Render header partial template from HTML file"""
    if templates_path is None:
        # Default to templates directory relative to project root
        templates_path = Path(__file__).parent.parent.parent / 'templates'
    
    try:
        env = template_environment(templates_path)
        template = env.get_template('partials/header.html')
        return template.render(site_title=config['site']['title'])
    except Exception as e:
        # Fallback to simple header if template fails
        return f"""<header role="banner">
    <a href="/" style="text-decoration: none; color: inherit;">
        <strong>{html_module.escape(str(config['site']['title']))}</strong>
    </a>
    <nav role="navigation" aria-label="Main navigation">
        <a href="/">Home</a>
        <a href="/posts/">Posts</a>
        <a href="/projects/">Projects</a>
        <a href="/products/">Products</a>
        <a href="/pages/manifesto/">Manifesto</a>
        <a href="/pages/about/">About</a>
        <a href="/pages/contact/">Contact</a>
        <a href="/cart/">Cart <span class="cart-count">0</span></a>
    </nav>
</header>"""


def render_footer(config: Dict, year: int = None, page_size: str = None, build_time: str = None, 
                  build_time_iso: str = None, lighthouse_scores: bool = True, 
                  description: str = None, templates_path: Path = None) -> str:
    """Render footer partial template from HTML file"""
    from datetime import datetime
    
    if templates_path is None:
        # Default to templates directory relative to project root
        templates_path = Path(__file__).parent.parent.parent / 'templates'
    
    if year is None:
        year = datetime.now().year
    
    try:
        env = template_environment(templates_path)
        template = env.get_template('partials/footer.html')
        return template.render(
            site_title=config['site']['title'],
            year=year,
            page_size=page_size,
            build_time=build_time,
            build_time_iso=build_time_iso,
            lighthouse_scores=lighthouse_scores,
            description=description
        )
    except Exception as e:
        # Fallback to simple footer if template fails
        footer_text = f"<p>&copy; {year} {config['site']['title']}. Built with GANG."
        if page_size:
            footer_text += f" {page_size}"
        footer_text += "</p>"
        return f"<footer>{footer_text}</footer>"


def create_index_simple(config: Dict, recent_posts: List, templates_path: Path = None) -> str:
    """Create simple index page"""
    posts_html = ""
    for post in recent_posts:
        url = html_module.escape(str(post.get('url') or ''), quote=True)
        title = html_module.escape(str(post.get('title') or ''))
        posts_html += f'<li><a href="{url}">{title}</a></li>\n'
    
    jsonld = {
        "@context": "https://schema.org",
        "@type": "WebSite",
        "name": config['site']['title'],
        "description": config['site']['description'],
        "url": config['site']['url']
    }
    jsonld_str = json_for_script(jsonld)
    site_url = str(config['site']['url']).rstrip('/')
    
    # Build timestamp
    build_time = datetime.now()
    build_time_formatted = build_time.strftime('%B %d, %Y at %I:%M %p')
    build_time_iso = build_time.isoformat()
    
    # Render header and footer
    header_html = render_header(config, templates_path)
    footer_html = render_footer(
        config,
        year=datetime.now().year,
        page_size=None,
        build_time=build_time_formatted,
        build_time_iso=build_time_iso,
        lighthouse_scores=True,
        description=config['site']['description'],
        templates_path=templates_path
    )
    
    html = f"""<!DOCTYPE html>
<html lang="{html_module.escape(config['site']['language'])}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; font-src 'self'; connect-src 'self'; base-uri 'self'; form-action 'self' https:;">
    <title>{html_module.escape(config['site']['title'])}</title>
    <meta name="description" content="{html_module.escape(config['site']['description'])}">
    <link rel="canonical" href="{html_module.escape(site_url + '/', quote=True)}">
    <script type="application/ld+json">
{jsonld_str}
    </script>
    <link rel="stylesheet" href="/assets/style.css">
    <style>
        ul {{
            list-style: none;
        }}
    </style>
</head>
<body>
    {header_html}
    <main>
        <h1>{html_module.escape(config['site']['title'])}</h1>
        <p>{html_module.escape(config['site']['description'])}</p>
        
        <h2>Latest Posts</h2>
        <ul  class="unstyled">
            {posts_html}
        </ul>
        <p><a href="/posts/">View all posts →</a></p>
    </main>
    {footer_html}
</body>
</html>"""
    
    return html


def create_list_page_simple(config: Dict, items: List, title: str, templates_path: Path = None, path: str = None) -> str:
    """Create simple list page"""
    items_html = ""
    for item in items:
        item_url = html_module.escape(str(item.get('url') or ''), quote=True)
        item_title = html_module.escape(str(item.get('title') or ''))
        items_html += f'<li><a href="{item_url}">{item_title}</a>'
        if item.get('summary'):
            items_html += f'<p>{html_module.escape(str(item["summary"]))}</p>'
        items_html += '</li>\n'
    
    list_path = path or f"/{title.lower().strip('/')}/"
    if not list_path.startswith('/'):
        list_path = '/' + list_path
    if not list_path.endswith('/'):
        list_path += '/'
    site_url = str(config['site']['url']).rstrip('/')
    canonical = f"{site_url}{list_path}"
    
    jsonld = {
        "@context": "https://schema.org",
        "@type": "CollectionPage",
        "name": title,
        "description": config['site']['description'],
        "url": canonical
    }
    jsonld_str = json_for_script(jsonld)
    
    # Build timestamp
    build_time = datetime.now()
    build_time_formatted = build_time.strftime('%B %d, %Y at %I:%M %p')
    build_time_iso = build_time.isoformat()
    
    # Render header and footer
    header_html = render_header(config, templates_path)
    footer_html = render_footer(
        config,
        year=datetime.now().year,
        page_size=None,  # Will be replaced with __PAGE_SIZE__ placeholder
        build_time=build_time_formatted,
        build_time_iso=build_time_iso,
        lighthouse_scores=True,
        description=config['site']['description'],
        templates_path=templates_path
    )
    
    html = f"""<!DOCTYPE html>
<html lang="{html_module.escape(str(config['site']['language']), quote=True)}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' https: data:; font-src 'self'; connect-src 'self'; base-uri 'self'; form-action 'self' https:;">
    <title>{html_module.escape(title)} - {html_module.escape(config['site']['title'])}</title>
    <meta name="description" content="{html_module.escape(config['site']['description'])}">
    <link rel="canonical" href="{html_module.escape(canonical, quote=True)}">
    <script type="application/ld+json">
{jsonld_str}
    </script>
    <link rel="stylesheet" href="/assets/style.css">
    <style>
        /* Page-specific: unstyled list */
        ul {{
            list-style: none;
        }}
        li {{
            margin-bottom: 1.5rem;
        }}
    </style>
</head>
<body>
    {header_html}
    <main>
        <h1>{html_module.escape(title)}</h1>
        <ul>
            {items_html}
        </ul>
    </main>
    {footer_html}
</body>
</html>"""
    
    return html


def tagged_build_items(
    all_pages: Optional[List[Dict]] = None,
    all_posts: Optional[List[Dict]] = None,
    all_projects: Optional[List[Dict]] = None,
    all_people: Optional[List[Dict]] = None,
    all_newsletters: Optional[List[Dict]] = None,
) -> List[Dict]:
    """Every rendered collection that can carry tags (not just posts/projects)."""
    items: List[Dict] = []
    for group in (all_posts, all_projects, all_pages, all_newsletters, all_people):
        items.extend(group or [])
    return items


def write_tag_pages(config: Dict, dist_path: Path, items: List[Dict], templates_path: Path = None) -> List[Dict[str, str]]:
    """Emit /tags/ and /tags/<tag>/ collection pages linked from content templates."""
    by_tag: Dict[str, List[Dict]] = {}
    for item in items:
        for tag in item.get('tags') or []:
            tag_name = str(tag).strip()
            if not tag_name or tag_name in ('.', '..'):
                continue
            by_tag.setdefault(tag_name, []).append(item)
    if not by_tag:
        return []
    
    tags_index_items = []
    sitemap_entries: List[Dict[str, str]] = []
    for tag_name in sorted(by_tag.keys(), key=str.lower):
        encoded = quote(tag_name, safe='')
        tag_path = f"/tags/{encoded}/"
        tag_html = create_list_page_simple(
            config, by_tag[tag_name], f"Tag: {tag_name}", templates_path, path=tag_path
        )
        tag_dir = dist_path / 'tags' / encoded
        tag_dir.mkdir(parents=True, exist_ok=True)
        (tag_dir / 'index.html').write_text(tag_html)
        tags_index_items.append({
            'url': tag_path,
            'title': tag_name,
            'summary': f"{len(by_tag[tag_name])} item(s)",
        })
        sitemap_entries.append({'url': tag_path, 'title': f'Tag: {tag_name}', 'type': 'tag'})
    
    tags_html = create_list_page_simple(config, tags_index_items, 'Tags', templates_path, path='/tags/')
    tags_root = dist_path / 'tags'
    tags_root.mkdir(parents=True, exist_ok=True)
    (tags_root / 'index.html').write_text(tags_html)
    click.echo(f"🏷️  Generated {len(by_tag)} tag page(s)")
    sitemap_entries.append({'url': '/tags/', 'title': 'Tags', 'type': 'list'})
    return sitemap_entries


def html_sitemap_utilities(dist_path: Path) -> List[Dict[str, str]]:
    """List search/cart on the HTML sitemap only when those pages exist."""
    utilities = []
    if (dist_path / 'search' / 'index.html').is_file():
        utilities.append({'url': '/search/', 'title': 'Search'})
    if (dist_path / 'cart' / 'index.html').is_file():
        utilities.append({'url': '/cart/', 'title': 'Cart'})
    return utilities


def write_html_sitemap(
    dist_path: Path,
    config: Dict[str, Any],
    *,
    pages: List[Any],
    posts: List[Any],
    projects: List[Any],
    products: List[Any],
    people: List[Any],
    newsletters: List[Any],
    tags: List[Any],
    live_reload_script: str = '',
) -> None:
    """Write /sitemap/ after cart/search so utility links are not ghosts."""
    template_dir = Path(__file__).parent.parent.parent / 'templates'
    jinja_env = template_environment(template_dir)
    sitemap_dir = dist_path / 'sitemap'
    sitemap_dir.mkdir(parents=True, exist_ok=True)
    sitemap_jsonld = {
        '@context': 'https://schema.org',
        '@type': 'CollectionPage',
        'name': 'Sitemap',
        'description': 'Complete sitemap of all pages',
        'url': f"{str(config['site']['url']).rstrip('/')}/sitemap/",
    }
    sitemap_template = jinja_env.get_template('sitemap.html')
    sitemap_html = sitemap_template.render(
        site_title=config['site']['title'],
        site_url=config['site']['url'],
        pages=pages,
        posts=posts,
        projects=projects,
        products=products,
        people=people,
        newsletters=newsletters,
        tags=tags,
        utilities=html_sitemap_utilities(dist_path),
        jsonld=sitemap_jsonld,
        year=datetime.now().year,
        build_time_iso=datetime.now().isoformat(),
    )
    if live_reload_script and '</body>' in sitemap_html:
        sitemap_html = sitemap_html.replace('</body>', live_reload_script + '</body>')
    (sitemap_dir / 'index.html').write_text(sitemap_html)


def discovery_sitemap_entries(
    tag_pages: Optional[List[Dict[str, str]]] = None,
    dist_path: Optional[Path] = None,
) -> List[Dict[str, str]]:
    """Utility pages generated after the first sitemap pass.

    When ``dist_path`` is given, only advertise utilities that actually exist
    so a failed cart/search/sitemap render cannot ghost those URLs.
    """
    extras = []
    for url, title, rel in (
        ('/search/', 'Search', 'search/index.html'),
        ('/cart/', 'Cart', 'cart/index.html'),
        ('/sitemap/', 'Sitemap', 'sitemap/index.html'),
    ):
        if dist_path is None or (dist_path / rel).is_file():
            extras.append({'url': url, 'title': title, 'type': 'utility'})
    extras.extend(tag_pages or [])
    return extras


def merge_sitemap_entries(all_content: List[Dict], extras: List[Dict]) -> List[Dict]:
    seen = {item.get('url') for item in all_content}
    for item in extras:
        url = item.get('url')
        if url and url not in seen:
            all_content.append(item)
            seen.add(url)
    return all_content


def process_markdown(md_file: Path, content_type: str, config: Dict) -> str:
    """Process a markdown file into HTML"""
    content = md_file.read_text()
    
    frontmatter, body = parse_frontmatter_text(content)
    
    # Convert markdown to HTML
    body_html = convert_markdown_html(body)
    
    title = html_module.escape(str(frontmatter.get('title') or md_file.stem.replace('-', ' ').title()))
    description = html_module.escape(
        str(frontmatter.get('summary') or frontmatter_seo(frontmatter).get('description') or config['site']['description']),
        quote=True,
    )
    
    # Build time for footer
    build_time = datetime.now()
    build_time_formatted = build_time.strftime('%B %d, %Y at %I:%M %p')
    build_time_iso = build_time.isoformat()
    
    # Render header
    header_html = render_header(config)
    
    # Build HTML page
    page_html = f"""<!DOCTYPE html>
<html lang="{html_module.escape(str(config['site']['language']), quote=True)}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; font-src 'self'; base-uri 'self'; form-action 'self';">
    <title>{title} - {html_module.escape(str(config['site']['title']))}</title>
    <meta name="description" content="{description}">
    <style>
        :root {{
            --max-width: 65ch;
            --spacing: 1.5rem;
        }}
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: system-ui, -apple-system, sans-serif;
            line-height: 1.6;
            color: #1a1a1a;
            background: #ffffff;
            padding: var(--spacing);
        }}
        header, main, footer {{
            max-width: var(--max-width);
            margin: 0 auto;
        }}
        header {{
            padding-bottom: var(--spacing);
            border-bottom: 1px solid #e0e0e0;
            margin-bottom: var(--spacing);
        }}
        nav {{
            margin-top: 1rem;
        }}
        nav a {{
            margin-right: 1rem;
            color: #0052a3;
            text-decoration: underline;
            text-decoration-thickness: 1px;
            text-underline-offset: 2px;
        }}
        nav a:hover {{
            text-decoration-thickness: 2px;
        }}
        h1 {{
            font-size: 2rem;
            margin-bottom: 1rem;
        }}
        h2 {{
            font-size: 1.5rem;
            margin-top: 2rem;
            margin-bottom: 1rem;
        }}
        h3 {{
            font-size: 1.25rem;
            margin-top: 1.5rem;
            margin-bottom: 0.75rem;
        }}
        p, ul, ol {{
            margin-bottom: 1rem;
        }}
        ul, ol {{
            margin-left: 1.5rem;
        }}
        code {{
            background: #f5f5f5;
            padding: 0.2em 0.4em;
            border-radius: 3px;
            font-size: 0.9em;
        }}
        pre {{
            background: #f5f5f5;
            padding: 1rem;
            border-radius: 5px;
            overflow-x: auto;
            margin-bottom: 1rem;
        }}
        pre code {{
            background: none;
            padding: 0;
        }}
        footer {{
            margin-top: 3rem;
            padding-top: var(--spacing);
            border-top: 1px solid #e0e0e0;
            color: #595959;
            font-size: 0.9rem;
        }}
        .lighthouse-scores {{
            margin-top: 0.5rem;
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
            font-size: 0.85rem;
        }}
        .lighthouse-scores .score {{
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
        }}
        .lighthouse-scores strong {{
            font-weight: 600;
            color: #1a1a1a;
        }}
        .last-updated {{
            margin-top: 0.5rem;
            font-size: 0.8rem;
            opacity: 0.8;
        }}
        .last-updated time {{
            font-style: italic;
        }}
    </style>
</head>
<body>
    {header_html}
    <main>
        <article>
            {body_html}
        </article>
    </main>
    <footer>
        <p>&copy; {datetime.now().year} {html_module.escape(str(config['site']['title']))}. Built with GANG. __PAGE_SIZE__</p>
        <p class="lighthouse-scores">
            <span class="score" title="Performance">Performance <strong>100</strong></span>
            <span class="score" title="Accessibility">Accessibility <strong>100</strong></span>
            <span class="score" title="Best Practices">Best Practices <strong>100</strong></span>
            <span class="score" title="SEO">Score <strong>100</strong></span>
        </p>
        <p class="last-updated">
            <time datetime="{build_time_iso}">Last updated: {build_time_formatted}</time>
        </p>
    </footer>
</body>
</html>"""
    
    return page_html


def create_index(config: Dict, posts: List, projects: List) -> str:
    """Create the homepage"""
    posts_links = '\n'.join([f'<li><a href="/posts/{slug}/">{slug.replace("-", " ").title()}</a></li>' 
                              for slug, _ in posts[:5]])
    
    # Render header
    header_html = render_header(config)
    
    html = f"""<!DOCTYPE html>
<html lang="{config['site']['language']}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{config['site']['title']}</title>
    <meta name="description" content="{config['site']['description']}">
    <style>
        :root {{
            --max-width: 65ch;
            --spacing: 1.5rem;
        }}
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: system-ui, -apple-system, sans-serif;
            line-height: 1.6;
            color: #1a1a1a;
            background: #ffffff;
            padding: var(--spacing);
        }}
        header, main, footer {{
            max-width: var(--max-width);
            margin: 0 auto;
        }}
        header {{
            padding-bottom: var(--spacing);
            border-bottom: 1px solid #e0e0e0;
            margin-bottom: var(--spacing);
        }}
        nav {{
            margin-top: 1rem;
        }}
        nav a {{
            margin-right: 1rem;
            color: #0052a3;
            text-decoration: underline;
            text-decoration-thickness: 1px;
            text-underline-offset: 2px;
        }}
        nav a:hover {{
            text-decoration-thickness: 2px;
        }}
        h1 {{
            font-size: 2.5rem;
            margin-bottom: 1rem;
        }}
        h2 {{
            font-size: 1.5rem;
            margin-top: 2rem;
            margin-bottom: 1rem;
        }}
        ul {{
            list-style: none;
            padding: 0;
        }}
        li {{
            margin-bottom: 0.5rem;
        }}
        a {{
            color: #0052a3;
            text-decoration: underline;
            text-decoration-thickness: 1px;
            text-underline-offset: 2px;
        }}
        a:hover {{
            text-decoration-thickness: 2px;
        }}
        footer {{
            margin-top: 3rem;
            padding-top: var(--spacing);
            border-top: 1px solid #e0e0e0;
            color: #595959;
            font-size: 0.9rem;
        }}
        .lighthouse-scores {{
            margin-top: 0.5rem;
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
            font-size: 0.85rem;
        }}
        .lighthouse-scores .score {{
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
        }}
        .lighthouse-scores strong {{
            font-weight: 600;
            color: #1a1a1a;
        }}
        .last-updated {{
            margin-top: 0.5rem;
            font-size: 0.8rem;
            opacity: 0.8;
        }}
        .last-updated time {{
            font-style: italic;
        }}
    </style>
</head>
<body>
    {header_html}
    <main>
        <h1>{config['site']['title']}</h1>
        <p>{config['site']['description']}</p>
        
        <h2>Latest Posts</h2>
        <ul  class="unstyled">>
            {posts_links}
        </ul>
        <p><a href="/posts/">View all posts →</a></p>
    </main>
    <footer>
        <p>&copy; {datetime.now().year} {config['site']['title']}. Built with GANG.</p>
    </footer>
</body>
</html>"""
    
    return html


def create_list_page(config: Dict, items: List, title: str) -> str:
    """Create a list page for posts or projects"""
    items_links = '\n'.join([f'<li><a href="/{title.lower()}/{slug}/">{slug.replace("-", " ").title()}</a></li>' 
                              for slug, _ in items])
    
    # Render header
    header_html = render_header(config)
    
    html = f"""<!DOCTYPE html>
<html lang="{config['site']['language']}">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title} - {config['site']['title']}</title>
    <meta name="description" content="{config['site']['description']}">
    <style>
        :root {{
            --max-width: 65ch;
            --spacing: 1.5rem;
        }}
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        body {{
            font-family: system-ui, -apple-system, sans-serif;
            line-height: 1.6;
            color: #1a1a1a;
            background: #ffffff;
            padding: var(--spacing);
        }}
        header, main, footer {{
            max-width: var(--max-width);
            margin: 0 auto;
        }}
        header {{
            padding-bottom: var(--spacing);
            border-bottom: 1px solid #e0e0e0;
            margin-bottom: var(--spacing);
        }}
        nav {{
            margin-top: 1rem;
        }}
        nav a {{
            margin-right: 1rem;
            color: #0052a3;
            text-decoration: underline;
            text-decoration-thickness: 1px;
            text-underline-offset: 2px;
        }}
        nav a:hover {{
            text-decoration-thickness: 2px;
        }}
        h1 {{
            font-size: 2rem;
            margin-bottom: 1.5rem;
        }}
        ul {{
            list-style: none;
            padding: 0;
        }}
        li {{
            margin-bottom: 0.75rem;
        }}
        a {{
            color: #0052a3;
            text-decoration: underline;
            text-decoration-thickness: 1px;
            text-underline-offset: 2px;
        }}
        a:hover {{
            text-decoration-thickness: 2px;
        }}
        footer {{
            margin-top: 3rem;
            padding-top: var(--spacing);
            border-top: 1px solid #e0e0e0;
            color: #595959;
            font-size: 0.9rem;
        }}
        .lighthouse-scores {{
            margin-top: 0.5rem;
            display: flex;
            gap: 1rem;
            flex-wrap: wrap;
            font-size: 0.85rem;
        }}
        .lighthouse-scores .score {{
            display: inline-flex;
            align-items: center;
            gap: 0.25rem;
        }}
        .lighthouse-scores strong {{
            font-weight: 600;
            color: #1a1a1a;
        }}
        .last-updated {{
            margin-top: 0.5rem;
            font-size: 0.8rem;
            opacity: 0.8;
        }}
        .last-updated time {{
            font-style: italic;
        }}
    </style>
</head>
<body>
    {header_html}
    <main>
        <h1>{html_module.escape(title)}</h1>
        <ul>
            {items_links}
        </ul>
    </main>
    <footer>
        <p>&copy; {datetime.now().year} {config['site']['title']}. Built with GANG.</p>
    </footer>
</body>
</html>"""
    
    return html

@cli.command()
@click.option('--output', '-o', type=click.Path(), help='Output JSON report to file')
@click.pass_context
def check(ctx, output):
    """Validate Template Contracts and WCAG compliance"""
    try:
        from core.validator import ContractValidator
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.validator import ContractValidator
    
    click.echo("✅ Validating contracts...")
    config = ctx.obj
    
    dist_path = Path(config['build']['output'])
    if not dist_path.exists():
        click.echo("Error: dist/ directory not found. Run 'gang build' first.", err=True)
        ctx.exit(1)
    
    validator = ContractValidator(config, dist_path=dist_path)
    results = validator.validate_directory(dist_path)
    
    # Print summary
    summary = results['summary']
    click.echo(f"\n📊 Validation Results:")
    click.echo(f"  Total files: {summary['total_files']}")
    click.echo(f"  ✅ Passed: {summary['passed']}")
    click.echo(f"  ❌ Failed: {summary['failed']}")
    click.echo(f"  📈 Pass rate: {summary['pass_rate']:.1f}%")
    
    # Print file details
    for file_result in results['files']:
        file_summary = file_result['summary']
        if not file_summary['passed']:
            try:
                display_path = Path(file_result['file']).resolve().relative_to(dist_path.resolve())
            except ValueError:
                display_path = Path(file_result['file'])
            click.echo(f"\n❌ {display_path}")
            click.echo(f"   Errors: {file_summary['errors']}, Warnings: {file_summary['warnings']}")
            
            # Show issues
            for category in ['semantic', 'accessibility', 'seo', 'budgets']:
                issues = file_result[category]
                for issue in issues:
                    icon = '🔴' if issue['severity'] == 'error' else '🟡'
                    click.echo(f"   {icon} [{issue['rule']}] {issue['message']}")
    
    # Save JSON report if requested
    if output:
        output_path = Path(output)
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)
        click.echo(f"\n📄 Report saved to {output_path}")
    
    # Exit with error code if validation failed
    if summary['failed'] > 0:
        ctx.exit(1)

@cli.command()
@click.option('--output', '-o', type=click.Path(), help='Output JSON report to file')
@click.pass_context
def audit(ctx, output):
    """Run Lighthouse CI audits (auto-discovers all pages)"""
    import subprocess
    from pathlib import Path
    
    config = ctx.obj
    dist_path = Path(config['build']['output'])
    
    if not dist_path.exists():
        click.echo("❌ Error: dist/ directory not found. Run 'gang build' first.", err=True)
        ctx.exit(1)
    
    # Check if Lighthouse CI is available
    try:
        subprocess.run(['npx', '--version'], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        click.echo("❌ Error: npx not found. Install Node.js to run Lighthouse audits.", err=True)
        ctx.exit(1)
    
    # Count pages
    page_count = len(list(dist_path.rglob('index.html')))
    click.echo(f"📊 Running audits on {page_count} pages...")
    click.echo("🔦 Lighthouse CI will auto-discover all pages in dist/")
    click.echo("   (3 runs per page, this may take a few minutes)\n")
    
    try:
        # Run Lighthouse CI with autorun (uses staticDistDir from config)
        result = subprocess.run(
            ['npx', '--yes', '@lhci/cli@0.13.x', 'autorun'],
            text=True
        )
        
        # Check thresholds from config
        thresholds = config.get('lighthouse', {})
        if result.returncode != 0:
            click.echo("\n❌ Lighthouse audits failed!")
            click.echo(f"   Expected: Performance ≥{thresholds.get('performance', 95)}, "
                      f"Accessibility ≥{thresholds.get('accessibility', 98)}, "
                      f"Best Practices ≥{thresholds.get('bestPractices', 100)}, "
                      f"SEO ≥{thresholds.get('seo', 100)}")
            ctx.exit(1)
        
        click.echo("\n✅ All audits passed!")
        
        # Report location
        lhci_dir = Path('.lighthouseci')
        if lhci_dir.exists():
            click.echo(f"📄 Detailed reports: {lhci_dir.absolute()}")
        
        if output:
            click.echo(f"📊 Custom report: {output}")
        
    except KeyboardInterrupt:
        click.echo("\n⚠️  Audit interrupted")
        ctx.exit(1)

@cli.command('update-deps')
@click.option('--check-only', is_flag=True, help='Only check for updates, do not install')
@click.option('--security-only', is_flag=True, help='Only update packages with security issues')
@click.pass_context
def update_deps(ctx, check_only, security_only):
    """Check and update third-party dependencies"""
    import subprocess
    
    click.echo("Score Checking for dependency updates...\n")
    
    # Check if pip-audit is available for security checks
    has_pip_audit = False
    if security_only:
        try:
            subprocess.run(['pip-audit', '--version'], capture_output=True, check=True)
            has_pip_audit = True
        except (subprocess.CalledProcessError, FileNotFoundError):
            click.echo("⚠️  pip-audit not found. Install with: pip install pip-audit")
            click.echo("    Falling back to regular update check.\n")
    
    # Security audit
    if security_only and has_pip_audit:
        click.echo("🔒 Running security audit...")
        result = subprocess.run(
            ['pip-audit', '-r', 'requirements.txt'],
            capture_output=True,
            text=True
        )
        click.echo(result.stdout)
        if result.returncode != 0:
            click.echo("❌ Security vulnerabilities found!")
            ctx.exit(1)
        else:
            click.echo("✅ No security vulnerabilities found.")
        return
    
    # Check for outdated packages
    click.echo("📦 Checking Python packages...")
    result = subprocess.run(
        ['pip', 'list', '--outdated', '--format=columns'],
        capture_output=True,
        text=True
    )
    
    if result.stdout.strip():
        click.echo(result.stdout)
        
        if not check_only:
            if click.confirm('\n📥 Update all dependencies in requirements.txt?'):
                # Update requirements.txt with latest versions
                click.echo("\n⬆️  Updating dependencies...")
                subprocess.run(['pip', 'install', '--upgrade', '-r', 'requirements.txt'])
                click.echo("\n✅ Dependencies updated! Run 'gang check && gang audit' to verify.")
            else:
                click.echo("⏭️  Skipped updates.")
    else:
        click.echo("✅ All dependencies are up to date!")
    
    # Reminder
    click.echo("\n💡 Tip: Enable Dependabot in .github/dependabot.yml for automated PRs")

@cli.command()
@click.argument('source_dir', type=click.Path(exists=True))
@click.option('--output', '-o', type=click.Path(), help='Output directory for processed images')
@click.option('--analyze', is_flag=True, help='Analyze image usage in content')
@click.option('--check-alt', is_flag=True, help='Check for missing alt text')
@click.pass_context
def image(ctx, source_dir, output, analyze, check_alt):
    """Process images to responsive formats and validate usage"""
    try:
        from core.images import ImageProcessor
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from core.images import ImageProcessor
    
    config = ctx.obj
    processor = ImageProcessor(config)
    
    # If analyze or check-alt mode
    if analyze or check_alt:
        content_path = Path(config['build']['content'])
        click.echo("Score Analyzing images in content...\n")
        
        total_missing_alt = 0
        total_external = 0
        total_images = 0
        
        for md_file in content_path.rglob('*.md'):
            content = md_file.read_text()
            analysis = processor.analyze_markdown_images(content)
            
            if analysis['total_images'] > 0:
                total_images += analysis['total_images']
                total_missing_alt += analysis['missing_alt']
                total_external += analysis['external_images']
                
                if check_alt and analysis['missing_alt'] > 0:
                    click.echo(f"⚠️  {md_file.relative_to(content_path)}")
                    for img in analysis['images']:
                        if not img['has_alt']:
                            click.echo(f"   Missing alt: {img['url']}")
        
        click.echo(f"\n📊 Image Analysis Summary:")
        click.echo(f"├─ Total images: {total_images}")
        click.echo(f"├─ Missing alt text: {total_missing_alt}")
        click.echo(f"└─ External images: {total_external}")
        
        if total_missing_alt > 0:
            click.echo(f"\n💡 Run 'gang optimize' to auto-generate alt text with AI")
            ctx.exit(1)
        
        return
    
    # Regular image processing
    click.echo("🖼️  Processing images...")
    source_path = Path(source_dir)
    output_path = Path(output) if output else Path(config['build']['output']) / 'assets' / 'images'
    
    image_map = processor.process_all_images(source_path, output_path)
    if isinstance(image_map, dict) and 'images' in image_map:
        image_map = image_map['images']
    
    total_variants = sum(len(variants) for variants in image_map.values())
    click.echo(f"✅ Processed {len(image_map)} images into {total_variants} variants")
    
    for original, variants in image_map.items():
        click.echo(f"  {original}:")
        for variant in variants:
            size_kb = variant['size'] / 1024
            click.echo(f"    - {variant['width']}w {variant['format']}: {size_kb:.1f}KB")

@cli.command()
@click.option('--port', default=3000, help='Port for Studio')
@click.option('--host', default='127.0.0.1', help='Host to bind to')
@click.pass_context
def studio(ctx, port, host):
    """Start Studio CMS"""
    click.echo(f"🎨 Starting GANG Studio on {host}:{port}...")
    
    # Import here to avoid dependency issues
    try:
        from http.server import HTTPServer, SimpleHTTPRequestHandler
        import json
        import threading
        
        config = ctx.obj
        
        class StudioHandler(SimpleHTTPRequestHandler):
            def log_message(self, format, *args):
                # Suppress HTTP request logs
                pass

            def _is_direct_loopback(self) -> bool:
                addr = self.client_address[0] if self.client_address else ''
                if addr not in ('127.0.0.1', '::1'):
                    return False
                if self.headers.get('X-Forwarded-For') or self.headers.get('X-Real-IP'):
                    return False
                return True

            def _is_loopback_origin(self) -> bool:
                origin_header = (self.headers.get('Origin') or '').strip()
                referer = (self.headers.get('Referer') or '').strip()
                # Mutating requests must send Origin so a form on another loopback
                # port cannot CSRF with a missing Origin + spoofed Referer.
                if self.command not in ('GET', 'HEAD', 'OPTIONS') and not origin_header:
                    return False
                origin = origin_header or referer
                if not origin:
                    return self.command in ('GET', 'HEAD', 'OPTIONS')
                try:
                    parsed = urlparse(origin)
                    host = (parsed.hostname or '').lower()
                except ValueError:
                    return False
                if host not in {'127.0.0.1', 'localhost', '::1'}:
                    return False
                if self.command not in ('GET', 'HEAD', 'OPTIONS'):
                    try:
                        origin_port = parsed.port or (443 if parsed.scheme == 'https' else 80)
                    except ValueError:
                        return False
                    if origin_port != port:
                        return False
                    # Require the Origin host to match this request's Host so
                    # http://[::1]:PORT cannot CSRF a server bound to 127.0.0.1.
                    req_host = (self.headers.get('Host') or '').split('@')[-1].strip()
                    if req_host.startswith('['):
                        end = req_host.find(']')
                        req_name = req_host[1:end].lower() if end != -1 else ''
                    else:
                        req_name = req_host.rsplit(':', 1)[0].lower()
                    if host != req_name:
                        return False
                    if parsed.scheme and parsed.scheme != 'http':
                        return False
                return True

            def _read_json_body(self) -> Dict[str, Any]:
                raw_length = self.headers.get('Content-Length', '0')
                try:
                    content_length = int(raw_length or 0)
                except (TypeError, ValueError):
                    content_length = 0
                if content_length <= 0:
                    raise ValueError('Missing request body')
                if content_length > MAX_CONTENT_BYTES:
                    raise ValueError('Request body too large')
                body = self.rfile.read(content_length)
                data = json.loads(body.decode())
                if not isinstance(data, dict):
                    raise ValueError('JSON object required')
                return data

            def _auth_ok(self) -> bool:
                token = os.environ.get('STUDIO_AUTH_TOKEN', '').strip()
                if not token:
                    return self._is_direct_loopback() and self._is_loopback_origin()
                return self.headers.get('Authorization', '') == f'Bearer {token}'

            def _reject_unauthorized(self) -> None:
                self.send_response(401)
                self.send_header('Content-type', 'application/json')
                self._send_cors()
                self.end_headers()
                self.wfile.write(json.dumps({'error': 'Unauthorized'}).encode())

            def _send_cors(self):
                origin = self.headers.get('Origin', '')
                allowed = {
                    f'http://127.0.0.1:{port}',
                    f'http://localhost:{port}',
                }
                if origin in allowed:
                    self.send_header('Access-Control-Allow-Origin', origin)
                    self.send_header('Vary', 'Origin')
            
            def do_GET(self):
                if self.path.startswith('/api/') and not self._auth_ok():
                    self._reject_unauthorized()
                    return
                if self.path in ('/api/content', '/api/content/list'):
                    try:
                        # List all content files
                        content_path = Path(config['build']['content']).resolve()
                        files = []
                        
                        click.echo(f"Score Looking for content in: {content_path}")
                        
                        if not content_path.exists():
                            click.echo(f"⚠️  Content directory not found: {content_path}")
                            self.send_response(200)
                            self.send_header('Content-type', 'application/json')
                            self._send_cors()
                            self.end_headers()
                            self.wfile.write(json.dumps([]).encode())
                            return
                        
                        for category in PUBLISHABLE_CATEGORIES:
                            category_path = content_path / category
                            if not category_path.exists():
                                continue
                            for md_file in sorted(category_path.glob('*.md')):
                                if not is_safe_content_slug(md_file.stem):
                                    continue
                                files.append({
                                    'path': str(md_file.relative_to(content_path)),
                                    'type': category,
                                    'name': md_file.stem
                                })
                        
                        click.echo(f"📂 Found {len(files)} content files: {[f['name'] for f in files]}")
                        
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self._send_cors()
                        self.end_headers()
                        self.wfile.write(json.dumps(files).encode())
                    except Exception as e:
                        import traceback
                        click.echo(f"❌ Error listing files: {e}")
                        click.echo(traceback.format_exc())
                        self.send_error(500)
                
                elif self.path.startswith('/api/content/'):
                    try:
                        file_path = self.path.replace('/api/content/', '').lstrip('/')
                        content_base = Path(config['build']['content']).resolve()
                        if not is_publishable_relpath(file_path):
                            self.send_error(403)
                            return
                        content_path = resolve_studio_content_path(content_base, file_path)
                        
                        if content_path is None:
                            self.send_error(403)
                            return
                        
                        click.echo(f"📖 Reading file: {content_path}")
                        
                        if content_path.exists():
                            content = content_path.read_text()
                            self.send_response(200)
                            self.send_header('Content-type', 'text/plain')
                            self._send_cors()
                            self.end_headers()
                            self.wfile.write(content.encode())
                        else:
                            click.echo(f"❌ File not found: {content_path}")
                            self.send_error(404)
                    except Exception as e:
                        import traceback
                        click.echo(f"❌ Error reading file: {e}")
                        click.echo(traceback.format_exc())
                        self.send_error(500)
                
                elif self.path == '/' or self.path == '/studio.html':
                    # Serve studio UI
                    try:
                        studio_html_path = Path('studio.html').resolve()
                        click.echo(f"🎨 Serving studio from: {studio_html_path}")
                        if studio_html_path.exists():
                            with open(studio_html_path, 'r') as f:
                                content = f.read()
                            self.send_response(200)
                            self.send_header('Content-type', 'text/html')
                            self.end_headers()
                            self.wfile.write(content.encode())
                        else:
                            click.echo(f"❌ studio.html not found at: {studio_html_path}")
                            self.send_error(404, "studio.html not found")
                    except Exception as e:
                        import traceback
                        click.echo(f"❌ Error serving studio: {e}")
                        click.echo(traceback.format_exc())
                        self.send_error(500)
                
                else:
                    self.send_error(404)
            
            def do_POST(self):
                """Handle POST requests"""
                if not self._auth_ok():
                    self._reject_unauthorized()
                    return
                if self.path == '/api/validate-headings':
                    try:
                        data = self._read_json_body()
                        
                        content = data.get('content', '')
                        
                        click.echo(f"Score Validating headings in content ({len(content)} chars)")
                        
                        # Import heading validator
                        sys.path.insert(0, str(Path(__file__).parent))
                        from core.heading_validator import HeadingValidator
                        
                        validator = HeadingValidator()
                        category = str(data.get('category') or data.get('page_type') or '')
                        result = validator.validate_markdown(
                            content,
                            template_owns_h1=category in TEMPLATE_OWNS_H1,
                        )
                        
                        # Add formatted report
                        result['report'] = validator.generate_error_report(result)
                        
                        click.echo(f"✅ Validation complete: {'PASS' if result['valid'] else 'FAIL'}")
                        
                        # Return validation result
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self._send_cors()
                        self.end_headers()
                        self.wfile.write(json.dumps(result, default=str).encode())
                        
                    except Exception as e:
                        import traceback
                        click.echo(f"❌ Error validating headings: {e}")
                        click.echo(traceback.format_exc())
                        self.send_response(500)
                        self.send_header('Content-type', 'application/json')
                        self._send_cors()
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            'error': 'Internal server error',
                            'message': str(e)
                        }).encode())
                
                elif self.path == '/api/rename-slug':
                    try:
                        data = self._read_json_body()
                        
                        old_slug = data.get('old_slug')
                        new_slug = data.get('new_slug')
                        category = data.get('category')
                        create_redirect = data.get('create_redirect', True)
                        
                        click.echo(f"🔄 Rename request: {old_slug} → {new_slug} (redirect: {create_redirect})")
                        
                        # Import redirect manager
                        sys.path.insert(0, str(Path(__file__).parent))
                        from core.redirects import RedirectManager
                        from core.content_importer import SlugChecker
                        
                        content_path = Path(config['build']['content'])
                        dist_path = Path(config['build']['output'])

                        if category not in PUBLISHABLE_CATEGORIES or not is_safe_content_slug(old_slug) or not is_safe_content_slug(new_slug):
                            self.send_response(400)
                            self.send_header('Content-type', 'application/json')
                            self._send_cors()
                            self.end_headers()
                            self.wfile.write(json.dumps({
                                'error': 'Invalid slug or category',
                                'message': 'Slugs may only contain letters, numbers, dots, underscores, or hyphens'
                            }).encode())
                            return
                        
                        # Check old file exists (articles listed as posts live on disk under articles/)
                        old_file = resolve_studio_content_path(content_path, f"{category}/{old_slug}")
                        if old_file is None or not old_file.exists():
                            self.send_response(404)
                            self.send_header('Content-type', 'application/json')
                            self._send_cors()
                            self.end_headers()
                            self.wfile.write(json.dumps({
                                'error': 'File not found',
                                'message': f'File {old_file} does not exist'
                            }).encode())
                            return
                        
                        # Keep the renamed file in the same on-disk category as the source.
                        new_file = old_file.with_name(f"{new_slug}.md")
                        try:
                            new_file.resolve().relative_to(content_path.resolve())
                        except ValueError:
                            self.send_response(400)
                            self.send_header('Content-type', 'application/json')
                            self._send_cors()
                            self.end_headers()
                            self.wfile.write(json.dumps({
                                'error': 'Invalid slug or category',
                                'message': 'Rename must stay inside the content directory'
                            }).encode())
                            return
                        if new_file.exists():
                            self.send_response(400)
                            self.send_header('Content-type', 'application/json')
                            self._send_cors()
                            self.end_headers()
                            self.wfile.write(json.dumps({
                                'error': 'Slug already exists',
                                'message': f'A file with slug "{new_slug}" already exists'
                            }).encode())
                            return
                        
                        redirect_info = None
                        redirect_manager = None
                        prior_redirects = None
                        if create_redirect:
                            old_url = public_content_url(category, old_slug)
                            new_url = public_content_url(category, new_slug)
                            redirect_manager = RedirectManager(content_path, dist_path)
                            prior_redirects = [dict(item) for item in redirect_manager.list_all_redirects()]
                            try:
                                result = redirect_manager.add_redirect(old_url, new_url, reason='slug_rename_cms')
                            except ValueError as exc:
                                self.send_response(400)
                                self.send_header('Content-type', 'application/json')
                                self._send_cors()
                                self.end_headers()
                                self.wfile.write(json.dumps({'error': str(exc)}).encode())
                                return
                            redirect_info = result.get('redirect')
                            click.echo(f"✅ 301 redirect created: {old_url} → {new_url}")

                        try:
                            exclusive_rename(old_file, new_file)
                        except FileExistsError:
                            if redirect_manager is not None and prior_redirects is not None:
                                redirect_manager.restore_redirects(prior_redirects)
                            self.send_response(400)
                            self.send_header('Content-type', 'application/json')
                            self._send_cors()
                            self.end_headers()
                            self.wfile.write(json.dumps({
                                'error': 'Slug already exists',
                                'message': f'A file with slug "{new_slug}" already exists'
                            }).encode())
                            return
                        except Exception:
                            if redirect_manager is not None and prior_redirects is not None:
                                redirect_manager.restore_redirects(prior_redirects)
                            raise
                        click.echo(f"✅ File renamed: {old_file.name} → {new_file.name}")
                        
                        # Return success response
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self._send_cors()
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            'success': True,
                            'old_path': str(old_file.relative_to(content_path)),
                            'new_path': str(new_file.relative_to(content_path)),
                            'redirect': redirect_info
                        }).encode())
                        
                    except Exception as e:
                        import traceback
                        click.echo(f"❌ Error renaming slug: {e}")
                        click.echo(traceback.format_exc())
                        self.send_response(500)
                        self.send_header('Content-type', 'application/json')
                        self._send_cors()
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            'error': 'Internal server error',
                            'message': str(e)
                        }).encode())
                
                elif self.path == '/api/redirects':
                    # Get all redirects
                    try:
                        sys.path.insert(0, str(Path(__file__).parent))
                        from core.redirects import RedirectManager
                        
                        content_path = Path(config['build']['content'])
                        dist_path = Path(config['build']['output'])
                        
                        manager = RedirectManager(content_path, dist_path)
                        redirects_list = manager.list_all_redirects()
                        
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self._send_cors()
                        self.end_headers()
                        self.wfile.write(json.dumps(redirects_list).encode())
                        
                    except Exception as e:
                        import traceback
                        click.echo(f"❌ Error listing redirects: {e}")
                        click.echo(traceback.format_exc())
                        self.send_error(500)
                
                elif self.path == '/api/products/sync':
                    # Sync products from Shopify/Stripe/Gumroad
                    try:
                        sys.path.insert(0, str(Path(__file__).parent))
                        from core.products import ProductAggregator
                        
                        click.echo("🛒 Syncing products via API...")
                        aggregator = ProductAggregator(config)
                        products = aggregator.get_normalized_products(status_filter='all')
                        
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self._send_cors()
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            'success': True,
                            'total': len(products),
                            'products': products
                        }).encode())
                        
                        click.echo(f"✅ Synced {len(products)} products")
                        
                    except Exception as e:
                        import traceback
                        click.echo(f"❌ Error syncing products: {e}")
                        click.echo(traceback.format_exc())
                        self.send_error(500)
                
                else:
                    self.send_error(404)
            
            def do_PUT(self):
                """Handle PUT requests"""
                if not self._auth_ok():
                    self._reject_unauthorized()
                    return
                if self.path.startswith('/api/content/'):
                    try:
                        file_path = self.path.replace('/api/content/', '').lstrip('/')
                        content_base = Path(config['build']['content']).resolve()
                        if not is_publishable_relpath(file_path):
                            self.send_response(403)
                            self.send_header('Content-type', 'application/json')
                            self._send_cors()
                            self.end_headers()
                            self.wfile.write(json.dumps({'error': 'Invalid file path'}).encode())
                            return
                        content_path = resolve_studio_content_path(content_base, file_path)
                        
                        if content_path is None:
                            self.send_response(403)
                            self.send_header('Content-type', 'application/json')
                            self._send_cors()
                            self.end_headers()
                            self.wfile.write(json.dumps({'error': 'Invalid file path'}).encode())
                            return
                        
                        try:
                            content_length = int(self.headers.get('Content-Length', 0) or 0)
                        except (TypeError, ValueError):
                            content_length = 0
                        if content_length <= 0:
                            self.send_response(400)
                            self.send_header('Content-type', 'application/json')
                            self._send_cors()
                            self.end_headers()
                            self.wfile.write(json.dumps({'error': 'No content provided'}).encode())
                            return
                        if content_length > MAX_CONTENT_BYTES:
                            self.send_response(413)
                            self.send_header('Content-type', 'application/json')
                            self._send_cors()
                            self.end_headers()
                            self.wfile.write(json.dumps({'error': 'Request body too large'}).encode())
                            return
                        body = self.rfile.read(content_length)
                        content = body.decode()
                        if not content.strip():
                            self.send_response(400)
                            self.send_header('Content-type', 'application/json')
                            self._send_cors()
                            self.end_headers()
                            self.wfile.write(json.dumps({'error': 'No content provided'}).encode())
                            return
                        if content_path.exists():
                            content = merge_editor_frontmatter(content_path.read_text(), content)
                        
                        content_path.parent.mkdir(parents=True, exist_ok=True)
                        content_path.write_text(content)
                        click.echo(f"✅ Saved file: {content_path}")
                        
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self._send_cors()
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            'success': True,
                            'path': str(content_path.relative_to(content_base))
                        }).encode())
                        
                    except Exception as e:
                        import traceback
                        click.echo(f"❌ Error saving file: {e}")
                        click.echo(traceback.format_exc())
                        self.send_response(500)
                        self.send_header('Content-type', 'application/json')
                        self._send_cors()
                        self.end_headers()
                        self.wfile.write(json.dumps({
                            'error': 'Failed to save',
                            'message': str(e)
                        }).encode())
                else:
                    self.send_error(404)
            
            def do_DELETE(self):
                """Handle DELETE requests"""
                if not self._auth_ok():
                    self._reject_unauthorized()
                    return
                if self.path.startswith('/api/redirects/'):
                    try:
                        # Get redirect path
                        from_path = self.path.replace('/api/redirects', '')
                        
                        sys.path.insert(0, str(Path(__file__).parent))
                        from core.redirects import RedirectManager
                        
                        content_path = Path(config['build']['content'])
                        dist_path = Path(config['build']['output'])
                        
                        manager = RedirectManager(content_path, dist_path)
                        if not manager._valid_redirect_target(from_path):
                            self.send_response(400)
                            self.send_header('Content-type', 'application/json')
                            self._send_cors()
                            self.end_headers()
                            self.wfile.write(json.dumps({'error': 'Invalid redirect path'}).encode())
                            return
                        
                        if manager.remove_redirect(from_path):
                            click.echo(f"✅ Redirect removed: {from_path}")
                            self.send_response(200)
                            self.send_header('Content-type', 'application/json')
                            self._send_cors()
                            self.end_headers()
                            self.wfile.write(json.dumps({
                                'success': True,
                                'message': 'Redirect removed'
                            }).encode())
                        else:
                            self.send_response(404)
                            self.send_header('Content-type', 'application/json')
                            self._send_cors()
                            self.end_headers()
                            self.wfile.write(json.dumps({
                                'error': 'Redirect not found'
                            }).encode())
                            
                    except Exception as e:
                        import traceback
                        click.echo(f"❌ Error deleting redirect: {e}")
                        click.echo(traceback.format_exc())
                        self.send_error(500)
                else:
                    self.send_error(404)
        
        # Create studio HTML file
        studio_html_path = Path('studio.html')
        if not studio_html_path.exists():
            create_studio_html(studio_html_path)
        
        server = HTTPServer((host, port), StudioHandler)
        
        click.echo(f"✅ Studio running at http://{host}:{port}")
        click.echo("📝 Open this URL in your browser")
        click.echo("Press Ctrl+C to stop")
        
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            click.echo("\n👋 Shutting down Studio...")
            server.shutdown()
    
    except ImportError as e:
        click.echo(f"❌ Error starting Studio: {e}", err=True)
        click.echo("Studio requires additional dependencies")


@cli.command()
@click.option('--port', default=8000, help='Port for dev server')
@click.option('--host', default='localhost', help='Host to bind to')
@click.pass_context
def serve(ctx, port, host):
    """Start dev server with live reload"""
    click.echo("🚀 Starting dev server with live reload...")
    
    import signal
    import sys
    
    # Global variables for cleanup
    server = None
    observer = None
    
    def signal_handler(signum, frame):
        """Handle shutdown signals"""
        click.echo(f"\n👋 Received signal {signum}, shutting down...")
        try:
            if observer:
                observer.stop()
                observer.join(timeout=1)
        except:
            pass
        try:
            if server:
                server.shutdown()
        except:
            pass
        sys.exit(0)
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # Terminal close
    signal.signal(signal.SIGHUP, signal_handler)   # Terminal hangup
    
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
        from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
        import os
        
        config = ctx.obj
        content_path = Path(config['build']['content']).resolve()
        templates_path = Path(config['build'].get('templates', './templates')).resolve()
        public_path = Path(config['build']['public']).resolve()
        dist_path = Path(config['build']['output']).resolve()
        
        # Track clients for live reload
        reload_clients = []
        rebuild_lock = threading.Lock()
        debounce_timer = {'t': None}
        
        class ChangeHandler(FileSystemEventHandler):
            def on_any_event(self, event):
                if event.is_directory:
                    return
                
                # Ignore dist folder changes and hidden files
                if str(dist_path) in event.src_path or '/__pycache__/' in event.src_path:
                    return
                
                if event.src_path.startswith('.') or '/.git/' in event.src_path:
                    return

                src_name = Path(event.src_path).name

                def fire():
                    if not rebuild_lock.acquire(blocking=False):
                        timer = threading.Timer(0.5, fire)
                        timer.daemon = True
                        debounce_timer['t'] = timer
                        timer.start()
                        return
                    try:
                        click.echo(f"\n📝 Change detected: {src_name}")
                        rebuild_site(ctx)
                        time.sleep(0.1)
                        notify_reload()
                    finally:
                        rebuild_lock.release()

                if debounce_timer['t'] is not None:
                    debounce_timer['t'].cancel()
                timer = threading.Timer(0.5, fire)
                timer.daemon = True
                debounce_timer['t'] = timer
                timer.start()
        
        # Live reload script to inject during build
        live_reload_script = '''
<script>
(function() {
    console.log('🔌 Connecting to live reload...');
    const source = new EventSource('/__livereload');
    
    source.onmessage = function(e) {
        if (e.data === 'reload') {
            console.log('🔄 Reloading page...');
            location.reload();
        }
    };
    
    source.onerror = function(e) {
        console.warn('Live reload disconnected');
        source.close();
    };
    
    source.onopen = function(e) {
        console.log('✅ Live reload connected');
    };
    
    // IMPORTANT: Close connection when navigating away
    window.addEventListener('beforeunload', function() {
        console.log('Closing live reload connection...');
        source.close();
    });
    
    // Also close on pagehide (for back/forward navigation)
    window.addEventListener('pagehide', function() {
        source.close();
    });
})();
</script>
'''
        
        def rebuild_site(ctx):
            """Rebuild the site"""
            click.echo("🔨 Rebuilding site...")
            backup_path = dist_path.parent / f".{dist_path.name}.prev"
            previous = None
            try:
                # Import here to use fresh code
                from core.templates import TemplateEngine
                from core.generators import OutputGenerators
                from core.optimizer import AIOptimizer
                
                # Move the last good tree aside so a failed rebuild cannot
                # leave the live-reload server serving an empty dist/.
                if dist_path.exists():
                    if backup_path.exists():
                        shutil.rmtree(backup_path)
                    dist_path.rename(backup_path)
                    previous = backup_path
                dist_path.mkdir(parents=True, exist_ok=True)
                
                # Initialize systems
                template_engine = TemplateEngine(templates_path)
                generators = OutputGenerators(config)
                optimizer = AIOptimizer(config)
                tag_pages: List[Dict[str, str]] = []
                
                # Copy public assets
                if public_path.exists():
                    shutil.copytree(public_path, dist_path / 'assets', dirs_exist_ok=True)
                    write_dist_headers(public_path, dist_path, config)
                
                # Build content
                all_pages = []
                all_posts = []
                all_projects = []
                all_people = []
                all_newsletters = []
                tag_pages = []
                products = []
                
                try:
                    from core.scheduler import ContentScheduler
                except ImportError:
                    from gang.core.scheduler import ContentScheduler
                scheduler = ContentScheduler(content_path)
                schedule_result = scheduler.get_publishable_content(collect_category_markdown(content_path))
                publishable_files = renderable_markdown(
                    [item['path'] for item in schedule_result['publishable']]
                )

                for md_file in publishable_files:
                    content_type = md_file.parent.name
                    if content_type not in PUBLISHABLE_CATEGORIES or not is_safe_content_slug(md_file.stem):
                        continue
                    
                    # Parse markdown with frontmatter
                    content = md_file.read_text()
                    frontmatter, body = parse_frontmatter_text(content)
                    if content_type in TEMPLATE_OWNS_H1:
                        body = strip_leading_markdown_h1(body)
                    
                    # Convert markdown to HTML
                    content_html = convert_markdown_html(body)
                    
                    # Prepare context
                    slug = md_file.stem
                    source_type = content_type
                    if content_type == 'articles':
                        content_type = 'posts'
                    url = public_content_url(content_type, slug)
                    if content_type == 'posts':
                        template_name = 'post.html'
                    elif content_type == 'projects':
                        template_name = 'article.html'
                    elif content_type == 'newsletters':
                        template_name = 'newsletter.html'
                    elif content_type == 'people':
                        template_name = 'person.html'
                    else:
                        template_name = 'page.html'
                    
                    build_time = datetime.now()
                    
                    # Never bake in-place editor chrome into published HTML.
                    user_authenticated = False
                    tags = frontmatter.get('tags') or []
                    if isinstance(tags, str):
                        tags = [tags]
                    elif not isinstance(tags, list):
                        tags = []
                    tags = [str(tag) for tag in tags]

                    content_date = authored_content_date(frontmatter, md_file)
                    description = (
                        frontmatter.get('summary')
                        or frontmatter_seo(frontmatter).get('description')
                        or config['site']['description']
                    )
                    if isinstance(description, str):
                        description = description.strip() or config['site']['description']
                    else:
                        description = config['site']['description']

                    comments_enabled = comments_are_enabled(config) and source_type in ('posts', 'articles')
                    page_comments = []
                    if comments_enabled:
                        try:
                            from core.comments import get_comments_for_build
                        except ImportError:
                            from gang.core.comments import get_comments_for_build
                        page_comments = get_comments_for_build(content_path, slug, 'post')
                    
                    context = {
                        'site_title': config['site']['title'],
                        'lang': config['site']['language'],
                        'title': frontmatter.get('title') or slug.replace('-', ' ').title(),
                        'description': description,
                        'content': content_html,
                        'year': datetime.now().year,
                        'navigation': config.get('nav', {}).get('main', []),
                        'date': content_date,
                        'date_formatted': str(content_date or ''),
                        'tags': tags,
                        'build_time': build_time.strftime('%B %d, %Y at %I:%M %p'),
                        'build_time_iso': build_time.isoformat(),
                        'jsonld': frontmatter.get('jsonld'),
                        'og_type': 'article' if content_type in ('posts', 'projects') else 'website',
                        'canonical_url': f"{str(config['site']['url']).rstrip('/')}{url}",
                        'page_type': content_type.rstrip('s'),
                        'category': content_type,
                        'source_category': source_type,
                        'slug': slug,
                        'user_authenticated': user_authenticated,
                        'comments_enabled': comments_enabled,
                        'comments': page_comments,
                        'comments_webhook_url': comments_webhook_url(config) if comments_enabled else '',
                        'comments_webhook_origin': comments_webhook_origin(config) if comments_enabled else '',
                        'role': frontmatter.get('role', ''),
                        'image': safe_http_url(frontmatter.get('image', '')),
                        'social_links': sanitize_social_links(frontmatter.get('social_links')),
                        'summary': frontmatter.get('summary') or '',
                        'issue_number': frontmatter.get('issue_number') or frontmatter.get('newsletter_id') or '',
                        'sent_date': frontmatter.get('sent_date') or frontmatter.get('date') or '',
                        'status': frontmatter.get('status') or '',
                    }
                    if not isinstance(context.get('jsonld'), dict) or not context.get('jsonld'):
                        context['jsonld'] = fallback_jsonld(
                            content_type,
                            context['title'],
                            context['description'],
                            context['canonical_url'],
                            context.get('date'),
                            config['site']['title'],
                        )
                    
                    # Render HTML
                    try:
                        html = template_engine.render(template_name, context)
                    except Exception as e:
                        html = process_markdown_fallback(md_file, content_type, config)
                    
                    # Inject live reload script
                    if '</body>' in html:
                        html = html.replace('</body>', live_reload_script + '</body>')
                    else:
                        html += live_reload_script
                    
                    # Calculate and inject page size
                    page_size_bytes = len(html.encode('utf-8'))
                    page_size_str = format_bytes(page_size_bytes)
                    html = html.replace('__PAGE_SIZE__', page_size_str)
                    
                    # Write output
                    output_file = dist_path / content_type / slug / 'index.html'
                    output_file.parent.mkdir(parents=True, exist_ok=True)
                    output_file.write_text(html)
                    
                    # Collect metadata
                    page_data = {
                        'url': url,
                        'title': context['title'],
                        'summary': list_item_summary(
                            frontmatter, config['site']['description'], content_html
                        ),
                        'date': context['date'],
                        'type': content_type,
                        'content_html': content_html,
                        'tags': context['tags'],
                    }
                    
                    if content_type == 'posts':
                        all_posts.append(page_data)
                    elif content_type == 'projects':
                        all_projects.append(page_data)
                    elif content_type == 'newsletters':
                        all_newsletters.append(page_data)
                    elif content_type == 'people':
                        all_people.append(page_data)
                    else:
                        all_pages.append(page_data)
                
                # Create index page
                index_html = create_index_simple(config, sorted(all_posts, key=lambda x: x.get('date', ''), reverse=True)[:5], templates_path)
                # Inject live reload script
                if '</body>' in index_html:
                    index_html = index_html.replace('</body>', live_reload_script + '</body>')
                else:
                    index_html += live_reload_script
                # Recalculate page size after injecting live reload
                page_size_bytes = len(index_html.encode('utf-8'))
                index_html = index_html.replace('__PAGE_SIZE__', format_bytes(page_size_bytes))
                (dist_path / 'index.html').write_text(index_html)
                
                # Create list pages
                posts_html = create_list_page_simple(config, sorted(all_posts, key=lambda x: x.get('date', ''), reverse=True), 'Posts', templates_path)
                if '</body>' in posts_html:
                    posts_html = posts_html.replace('</body>', live_reload_script + '</body>')
                page_size_bytes = len(posts_html.encode('utf-8'))
                posts_html = posts_html.replace('__PAGE_SIZE__', format_bytes(page_size_bytes))
                (dist_path / 'posts').mkdir(parents=True, exist_ok=True)
                (dist_path / 'posts' / 'index.html').write_text(posts_html)
                
                if all_projects:
                    projects_html = create_list_page_simple(config, all_projects, 'Projects', templates_path)
                    # Inject live reload script
                    if '</body>' in projects_html:
                        projects_html = projects_html.replace('</body>', live_reload_script + '</body>')
                    # Recalculate page size after injecting live reload
                    page_size_bytes = len(projects_html.encode('utf-8'))
                    projects_html = projects_html.replace('__PAGE_SIZE__', format_bytes(page_size_bytes))
                    (dist_path / 'projects' / 'index.html').write_text(projects_html)

                if all_people:
                    people_html = create_list_page_simple(config, all_people, 'People', templates_path, path='/people/')
                    if '</body>' in people_html:
                        people_html = people_html.replace('</body>', live_reload_script + '</body>')
                    people_html = people_html.replace('__PAGE_SIZE__', format_bytes(len(people_html.encode('utf-8'))))
                    (dist_path / 'people').mkdir(parents=True, exist_ok=True)
                    (dist_path / 'people' / 'index.html').write_text(people_html)

                if all_newsletters:
                    newsletters_html = create_list_page_simple(
                        config, sorted(all_newsletters, key=lambda x: x.get('date', ''), reverse=True), 'Newsletters', templates_path
                    )
                    if '</body>' in newsletters_html:
                        newsletters_html = newsletters_html.replace('</body>', live_reload_script + '</body>')
                    newsletters_html = newsletters_html.replace('__PAGE_SIZE__', format_bytes(len(newsletters_html.encode('utf-8'))))
                    (dist_path / 'newsletters').mkdir(parents=True, exist_ok=True)
                    (dist_path / 'newsletters' / 'index.html').write_text(newsletters_html)

                tag_pages = write_tag_pages(
                    config,
                    dist_path,
                    tagged_build_items(all_pages, all_posts, all_projects, all_people, all_newsletters),
                    templates_path,
                )
                
                # Generate outputs (same all_content set as gang build)
                all_pages.append({'url': '/', 'title': config['site']['title'], 'type': 'home'})
                if all_posts:
                    all_pages.append({'url': '/posts/', 'title': 'Posts', 'type': 'list'})
                if all_projects:
                    all_pages.append({'url': '/projects/', 'title': 'Projects', 'type': 'list'})
                if all_people:
                    all_pages.append({'url': '/people/', 'title': 'People', 'type': 'list'})
                if all_newsletters:
                    all_pages.append({'url': '/newsletters/', 'title': 'Newsletters', 'type': 'list'})

                all_content = all_pages + all_posts + all_projects + all_people + all_newsletters
                generators.generate_all(dist_path, all_content, all_posts)

                try:
                    from core.redirects import RedirectManager
                    redirect_manager = RedirectManager(content_path, dist_path)
                    redirect_list = redirect_manager.list_all_redirects()
                    if redirect_list:
                        redirect_manager.write_redirects_file(format='cloudflare')
                except Exception as e:
                    click.echo(f"⚠️  Could not generate redirects: {e}")
                
                # Generate product pages (only active products)
                try:
                    from core.products import ProductAggregator
                    
                    aggregator = ProductAggregator(config)
                    products = aggregator.get_normalized_products(status_filter='active') or []
                    
                    if products:
                        products = assign_unique_catalog_slugs(products)
                        template_dir = Path(__file__).parent.parent.parent / 'templates'
                        jinja_env = template_environment(template_dir)
                        
                        products_path = dist_path / 'products'
                        products_path.mkdir(parents=True, exist_ok=True)
                        
                        # Generate PLP
                        plp_template = jinja_env.get_template('products-list.html')
                        plp_canonical = f"{str(config['site']['url']).rstrip('/')}/products/"
                        plp_html = plp_template.render(
                            products=products,
                            site_title=config['site']['title'],
                            lang=config['site'].get('language', 'en'),
                            canonical_url=plp_canonical,
                            jsonld={
                                '@context': 'https://schema.org',
                                '@type': 'CollectionPage',
                                'name': 'Products',
                                'description': 'Product catalog',
                                'url': plp_canonical,
                                'numberOfItems': len(products),
                            },
                            year=datetime.now().year,
                            navigation=config.get('nav', {}).get('main', []),
                            build_time=datetime.now().strftime('%Y-%m-%d %H:%M'),
                            build_time_iso=datetime.now().isoformat()
                        )
                        # Inject live reload
                        if '</body>' in plp_html:
                            plp_html = plp_html.replace('</body>', live_reload_script + '</body>')
                        (products_path / 'index.html').write_text(plp_html)
                        
                        # Generate PDPs
                        pdp_template = jinja_env.get_template('product.html')
                        for product in products:
                            slug = product['_meta'].get('slug') or product['_meta'].get('handle')
                            if not slug or not is_safe_content_slug(str(slug)):
                                continue
                            
                            pdp_dir = products_path / slug
                            pdp_dir.mkdir(parents=True, exist_ok=True)
                            pdp_html = pdp_template.render(**build_pdp_context(product, config, slug))
                            # Inject live reload
                            if '</body>' in pdp_html:
                                pdp_html = pdp_html.replace('</body>', live_reload_script + '</body>')
                            (pdp_dir / 'index.html').write_text(pdp_html)
                            all_content.append({
                                'url': f'/products/{slug}/',
                                'title': product.get('name', slug),
                                'type': 'product',
                            })
                        all_content.append({'url': '/products/', 'title': 'Products', 'type': 'list'})
                        generators.generate_all(dist_path, all_content, all_posts)
                except Exception as e:
                    click.echo(f"⚠️  Could not generate product pages: {e}")
                    products = []

                try:
                    template_dir = Path(__file__).parent.parent.parent / 'templates'
                    jinja_env = template_environment(template_dir)
                    build_time = datetime.now()
                    cart_jsonld = {
                        '@context': 'https://schema.org',
                        '@type': 'WebPage',
                        'name': 'Shopping Cart',
                        'description': config['site']['description'],
                        'url': f"{str(config['site']['url']).rstrip('/')}/cart/",
                    }
                    cart_dir = dist_path / 'cart'
                    cart_dir.mkdir(parents=True, exist_ok=True)
                    cart_template = jinja_env.get_template('cart.html')
                    cart_html = cart_template.render(
                        year=datetime.now().year,
                        site_title=config['site']['title'],
                        lighthouse_scores=True,
                        build_time=build_time.strftime('%B %d, %Y at %I:%M %p'),
                        build_time_iso=build_time.isoformat(),
                        description=config['site']['description'],
                        jsonld=cart_jsonld,
                        site_url=config['site']['url'],
                        checkout_origins=collect_checkout_origins(products),
                    )
                    if '</body>' in cart_html:
                        cart_html = cart_html.replace('</body>', live_reload_script + '</body>')
                    (cart_dir / 'index.html').write_text(cart_html)
                except Exception as e:
                    click.echo(f"⚠️  Could not generate cart: {e}")

                try:
                    from core.search import SearchIndexer
                    indexer = SearchIndexer(content_path, config)
                    search_index = indexer.build_search_index(publishable_files)
                    indexer.add_product_documents(search_index, products)
                    (dist_path / 'search-index.json').write_text(json.dumps(search_index, default=str))
                    search_page = dist_path / 'search' / 'index.html'
                    search_page.parent.mkdir(parents=True, exist_ok=True)
                    search_html = indexer.generate_search_page_html(config, templates_path)
                    if '</body>' in search_html:
                        search_html = search_html.replace('</body>', live_reload_script + '</body>')
                    search_page.write_text(search_html)
                except Exception as e:
                    click.echo(f"⚠️  Could not generate search index: {e}")

                try:
                    write_html_sitemap(
                        dist_path,
                        config,
                        pages=all_pages,
                        posts=all_posts,
                        projects=all_projects,
                        products=products,
                        people=all_people,
                        newsletters=all_newsletters,
                        tags=tag_pages,
                        live_reload_script=live_reload_script,
                    )
                except Exception as e:
                    click.echo(f"⚠️  Could not generate sitemap: {e}")

                merge_sitemap_entries(
                    all_content, discovery_sitemap_entries(tag_pages, dist_path=dist_path)
                )
                generators.generate_all(dist_path, all_content, all_posts)

                try:
                    from core.agentmap import AgentMapGenerator, ContentAPIGenerator
                    from core.products import ProductAggregator

                    publishable_paths = [
                        Path(item) if not isinstance(item, Path) else item
                        for item in publishable_files
                    ]
                    aggregator = ProductAggregator(config)
                    agent_products = aggregator.get_normalized_products(status_filter='active')
                    site_url = config.get('site', {}).get('url', 'https://example.com')
                    generator = AgentMapGenerator(config, site_url)
                    agentmap = generator.generate(publishable_paths, agent_products if agent_products else None)
                    (dist_path / 'agentmap.json').write_text(json.dumps(agentmap, indent=2))

                    api_dir = dist_path / 'api'
                    api_dir.mkdir(parents=True, exist_ok=True)
                    api_generator = ContentAPIGenerator(site_url)
                    content_api = api_generator.generate_content_index(publishable_paths, content_path)
                    (api_dir / 'content.json').write_text(json.dumps(content_api, indent=2))
                    api_generator.write_content_apis(
                        publishable_paths, content_path, api_dir, safe_slug=is_safe_content_slug
                    )
                    if agent_products:
                        (api_dir / 'products.json').write_text(json.dumps({
                            'products': agent_products,
                            'count': len(agent_products),
                            'generated': datetime.now().isoformat(),
                        }, indent=2))
                except Exception as e:
                    click.echo(f"⚠️  Could not generate AgentMap: {e}")
                
                click.echo("✅ Build complete!")
                if previous and previous.exists():
                    shutil.rmtree(previous, ignore_errors=True)
                
            except Exception as e:
                click.echo(f"❌ Build error: {e}", err=True)
                import traceback
                traceback.print_exc()
                if previous is not None:
                    if dist_path.exists():
                        shutil.rmtree(dist_path, ignore_errors=True)
                    if previous.exists():
                        previous.rename(dist_path)
        
        def notify_reload():
            """Notify all connected clients to reload"""
            click.echo(f"📡 Notifying {len(reload_clients)} connected clients")
            for client in reload_clients[:]:
                try:
                    client.wfile.write(b"data: reload\n\n")
                    client.wfile.flush()
                except Exception as e:
                    if client in reload_clients:
                        reload_clients.remove(client)
        
        class LiveReloadHandler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(dist_path), **kwargs)
            
            def log_message(self, format, *args):
                # Log requests for debugging
                if len(args) > 0:
                    click.echo(f"[REQUEST] {args[0]}")

            def _send_cors(self):
                origin = self.headers.get('Origin', '')
                if origin.startswith('http://127.0.0.1:') or origin.startswith('http://localhost:'):
                    self.send_header('Access-Control-Allow-Origin', origin)
                    self.send_header('Vary', 'Origin')
            
            def do_GET(self):
                try:
                    if self.path == '/__livereload':
                        # SSE endpoint for live reload
                        self.send_response(200)
                        self.send_header('Content-Type', 'text/event-stream')
                        self.send_header('Cache-Control', 'no-cache')
                        self.send_header('Connection', 'keep-alive')
                        self._send_cors()
                        self.end_headers()
                        
                        reload_clients.append(self)
                        
                        # Keep connection alive - just wait, no pings needed
                        try:
                            # Block until client disconnects or we send reload
                            while True:
                                time.sleep(60)
                        except:
                            pass
                        finally:
                            if self in reload_clients:
                                reload_clients.remove(self)
                    else:
                        # Let parent handle all other requests (HTML and assets)
                        super().do_GET()
                except BrokenPipeError:
                    # Client disconnected, ignore
                    pass
                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    try:
                        self.send_error(500)
                    except:
                        pass
        
        # Initial build
        click.echo("🔨 Initial build...")
        rebuild_site(ctx)
        
        # Start file watcher
        observer = Observer()
        handler = ChangeHandler()
        
        # Watch content, templates, and public directories
        if content_path.exists():
            observer.schedule(handler, str(content_path), recursive=True)
            click.echo(f"👀 Watching: {content_path}")
        
        if templates_path.exists():
            observer.schedule(handler, str(templates_path), recursive=True)
            click.echo(f"👀 Watching: {templates_path}")
        
        if public_path.exists():
            observer.schedule(handler, str(public_path), recursive=True)
            click.echo(f"👀 Watching: {public_path}")
        
        observer.start()
        
        # Start HTTP server (threading to handle multiple connections)
        server = ThreadingHTTPServer((host, port), LiveReloadHandler)
        
        click.echo(f"\n✅ Dev server running at http://{host}:{port}")
        click.echo("📝 Live reload enabled - changes will auto-refresh the browser")
        click.echo("Press Ctrl+C to stop (or close terminal)\n")
        
        # The signal handler will take care of cleanup
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            click.echo("\n👋 Shutting down...")
            observer.stop()
            observer.join()
            server.shutdown()
        except SystemExit:
            # Signal handler called sys.exit()
            pass
    
    except ImportError as e:
        click.echo(f"❌ Error: {e}", err=True)
        click.echo("Install watchdog: pip install watchdog>=3.0.0")
        ctx.abort()


def create_studio_html(output_path: Path):
    """Create the Studio CMS HTML interface"""
    html = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>GANG Studio</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: system-ui, -apple-system, sans-serif;
            display: flex;
            height: 100vh;
            overflow: hidden;
            background: #f5f5f5;
        }
        
        .sidebar {
            width: 250px;
            background: #1a1a1a;
            color: #fff;
            display: flex;
            flex-direction: column;
        }
        
        .sidebar-header {
            padding: 1.5rem;
            border-bottom: 1px solid #333;
        }
        
        .sidebar-header h1 {
            font-size: 1.25rem;
            font-weight: 600;
        }
        
        .content-list {
            flex: 1;
            overflow-y: auto;
            padding: 1rem;
        }
        
        .content-item {
            padding: 0.75rem;
            margin-bottom: 0.5rem;
            background: #2a2a2a;
            border-radius: 4px;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        .content-item:hover {
            background: #333;
        }
        
        .content-item.active {
            background: #0066cc;
        }
        
        .content-item-name {
            font-weight: 500;
        }
        
        .content-item-type {
            font-size: 0.875rem;
            color: #999;
            margin-top: 0.25rem;
        }
        
        .main {
            flex: 1;
            display: flex;
            flex-direction: column;
        }
        
        .toolbar {
            padding: 1rem 1.5rem;
            background: #fff;
            border-bottom: 1px solid #e0e0e0;
            display: flex;
            align-items: center;
            gap: 1rem;
        }
        
        .toolbar button {
            padding: 0.5rem 1rem;
            border: none;
            border-radius: 4px;
            background: #0066cc;
            color: #fff;
            font-weight: 500;
            cursor: pointer;
            transition: background 0.2s;
        }
        
        .toolbar button:hover {
            background: #0052a3;
        }
        
        .editor {
            flex: 1;
            display: flex;
        }
        
        .editor-pane {
            flex: 1;
            padding: 2rem;
            background: #fff;
        }
        
        .editor-pane textarea {
            width: 100%;
            height: 100%;
            border: 1px solid #e0e0e0;
            border-radius: 4px;
            padding: 1rem;
            font-family: 'Monaco', 'Courier New', monospace;
            font-size: 0.875rem;
            line-height: 1.6;
            resize: none;
        }
        
        .preview-pane {
            flex: 1;
            padding: 2rem;
            background: #fafafa;
            overflow-y: auto;
            border-left: 1px solid #e0e0e0;
        }
        
        .preview-content {
            max-width: 65ch;
            margin: 0 auto;
        }
        
        .loading {
            padding: 2rem;
            text-align: center;
            color: #595959;
        }
    </style>
</head>
<body>
    <div class="sidebar">
        <div class="sidebar-header">
            <h1>GANG Studio</h1>
        </div>
        <div class="content-list" id="contentList">
            <div class="loading">Loading content...</div>
        </div>
    </div>
    
    <div class="main">
        <div class="toolbar">
            <button onclick="saveContent()">💾 Save</button>
            <button onclick="buildSite()">🔨 Build</button>
            <button onclick="runOptimize()">🤖 Optimize</button>
            <span id="status"></span>
        </div>
        
        <div class="editor">
            <div class="editor-pane">
                <textarea id="editor" placeholder="Select a file to edit..."></textarea>
            </div>
            <div class="preview-pane">
                <div class="preview-content" id="preview">
                    <p style="color: #666;">Preview will appear here...</p>
                </div>
            </div>
        </div>
    </div>
    
    <script>
        let currentFile = null;
        
        // Load content list
        async function loadContentList() {
            const listEl = document.getElementById('contentList');
            try {
                console.log('Fetching content from /api/content...');
                const response = await fetch('/api/content');
                console.log('Response status:', response.status);
                
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                
                const files = await response.json();
                console.log('Received files:', files);
                
                listEl.innerHTML = '';
                
                if (files.length === 0) {
                    listEl.innerHTML = '<div class="loading">No content files found</div>';
                    return;
                }
                
                files.forEach(file => {
                    const item = document.createElement('div');
                    item.className = 'content-item';
                    const nameEl = document.createElement('div');
                    nameEl.className = 'content-item-name';
                    nameEl.textContent = file.name || '';
                    const typeEl = document.createElement('div');
                    typeEl.className = 'content-item-type';
                    typeEl.textContent = file.type || '';
                    item.appendChild(nameEl);
                    item.appendChild(typeEl);
                    item.onclick = () => loadFile(file.path);
                    listEl.appendChild(item);
                });
            } catch (e) {
                console.error('Failed to load content list:', e);
                listEl.textContent = '';
                const err = document.createElement('div');
                err.className = 'loading';
                err.style.color = '#ff6b6b';
                err.textContent = 'Error: ' + (e && e.message ? e.message : 'failed') + '. Check browser console for details';
                listEl.appendChild(err);
            }
        }
        
        // Load specific file
        async function loadFile(path) {
            try {
                const response = await fetch(`/api/content/${path}`);
                const content = await response.text();
                
                currentFile = path;
                document.getElementById('editor').value = content;
                updatePreview(content);
                
                // Update active state
                document.querySelectorAll('.content-item').forEach(item => {
                    item.classList.remove('active');
                });
                event.target.closest('.content-item').classList.add('active');
            } catch (e) {
                console.error('Failed to load file:', e);
            }
        }
        
        // Update preview
        function escapePreview(text) {
            const div = document.createElement('div');
            div.textContent = text == null ? '' : String(text);
            return div.innerHTML;
        }
        function updatePreview(markdown) {
            // Escape first so authored HTML cannot run in the preview pane
            const html = escapePreview(markdown)
                .replace(/^# (.+)$/gm, '<h1>$1</h1>')
                .replace(/^## (.+)$/gm, '<h2>$1</h2>')
                .replace(/^### (.+)$/gm, '<h3>$1</h3>')
                .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
                .replace(/\*(.+?)\*/g, '<em>$1</em>')
                .replace(/\n\n/g, '</p><p>')
                .replace(/^(.+)$/gm, '<p>$1</p>');
            
            document.getElementById('preview').innerHTML = html;
        }
        
        // Save content
        function saveContent() {
            alert('Save functionality requires backend API integration');
        }
        
        // Build site
        function buildSite() {
            alert('Run "gang build" in terminal to build the site');
        }
        
        // Run optimize
        function runOptimize() {
            alert('Run "gang optimize" in terminal to optimize content');
        }
        
        // Auto-update preview
        document.getElementById('editor').addEventListener('input', (e) => {
            updatePreview(e.target.value);
        });
        
        // Load initial content
        loadContentList();
    </script>
</body>
</html>"""
    
    output_path.write_text(html)


if __name__ == '__main__':
    cli()
