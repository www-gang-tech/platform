"""
Shared HTML / URL sanitizers for Markdown fragments and template hrefs.
"""

from __future__ import annotations

from typing import Any, Optional
from urllib.parse import unquote, urlparse, urlunparse


def _href_has_dotdot(path: str) -> bool:
    return any(segment == '..' for segment in path.split('/'))


def _is_safe_href_candidate(value: str) -> bool:
    """Single-pass href policy on an already-normalized candidate."""
    if not value:
        return False
    # Browsers normalize backslash "protocol-relative" forms (/\evil, \\evil)
    # into cross-origin navigations; reject those alongside //host.
    if value.startswith(('//', '/\\', '\\')):
        return False
    # Collapse escapes before scheme checks so java\nscript: cannot sneak through.
    normalized = value.replace('\\', '/')
    if normalized.startswith('//'):
        return False
    scheme_host = normalized.split('?', 1)[0].split('#', 1)[0]
    if ':' in scheme_host:
        lower = scheme_host.lower()
        if lower.startswith('mailto:'):
            addr = lower[7:]
            local = addr.split('@', 1)[0]
            # Reject mailto:javascript:… and other nested schemes.
            return bool(addr) and ':' not in local
        if lower.startswith(('http://', 'https://')):
            host = lower.split('://', 1)[1]
            return bool(host) and host not in ('.', '..')
        return False
    # Relative / root-relative / fragment: reject path traversal.
    return not _href_has_dotdot(scheme_host)


def is_safe_href(value: Optional[str]) -> bool:
    """Allow relative paths, anchors, http(s), and mailto; reject javascript: etc."""
    if not value:
        return False
    value = str(value).strip()
    if not value:
        return False
    if not _is_safe_href_candidate(value):
        return False
    # Percent-decode so /%2f/evil.com and /%2e%2e/admin cannot bypass prefix checks.
    decoded = value
    for _ in range(3):
        nxt = unquote(decoded)
        if nxt == decoded:
            break
        decoded = nxt
        if not _is_safe_href_candidate(decoded):
            return False
    return True


def safe_href(value: Optional[str], fallback: str = '#') -> str:
    """Return value when safe, otherwise fallback."""
    return value if is_safe_href(value) else fallback


def safe_http_url(value: Any) -> str:
    """Allow only relative site paths or http(s) URLs.

    Applies the shared href policy (encoded slashes, ``..``, backslash gadgets),
    strips userinfo, and rejects ``shopify.com`` checkout hosts.
    """
    if not isinstance(value, str):
        return ''
    value = value.strip()
    if not value or value == '#':
        return ''
    if not is_safe_href(value):
        return ''
    if value.startswith('/') and not value.startswith('//'):
        return value
    parsed = urlparse(value)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        return ''
    host = (parsed.netloc or '').split('@')[-1]
    if not host or host.lower() in ('www.shopify.com', 'shopify.com'):
        return ''
    if '@' in parsed.netloc:
        return urlunparse(parsed._replace(netloc=host))
    return value


def sanitize_markdown_html(html: str) -> str:
    """Strip dangerous tags/attrs from Markdown-generated HTML fragments."""
    from bs4 import BeautifulSoup

    if not html:
        return ''

    soup = BeautifulSoup(f'<div id="gang-md-root">{html}</div>', 'html.parser')
    root = soup.find(id='gang-md-root')
    if root is None:
        return ''

    forbidden_tags = {
        'script', 'style', 'iframe', 'object', 'embed', 'link', 'meta',
        'base', 'form', 'input', 'button', 'textarea', 'select',
    }
    # Snapshot tags first: decomposing a parent invalidates children still in
    # the list (BeautifulSoup sets attrs=None), which used to TypeError.
    for tag in list(root.find_all(True)):
        if getattr(tag, 'decomposed', False):
            continue
        name = (tag.name or '').lower()
        if name in forbidden_tags:
            tag.decompose()
            continue
        attrs = tag.attrs
        if not attrs:
            continue
        for attr in list(attrs):
            attr_l = str(attr).lower()
            if attr_l.startswith('on') or attr_l in {
                'style', 'srcdoc', 'ping', 'background', 'dynsrc', 'lowsrc',
            }:
                del tag.attrs[attr]

    return ''.join(str(child) for child in root.contents)


def sanitize_content_hrefs(html: str) -> str:
    """Rewrite unsafe URL-bearing attributes in generated markdown HTML."""
    import re

    def sanitize_srcset(value: str) -> str:
        parts = []
        for candidate in value.split(','):
            token = candidate.strip()
            if not token:
                continue
            url = token.split(None, 1)[0]
            descriptor = token[len(url):]
            if is_safe_href(url):
                parts.append(token)
            else:
                parts.append(f'#{descriptor}' if descriptor else '#')
        return ', '.join(parts) if parts else '#'

    def rewrite(attr: str, quote: str, value: str) -> str:
        if attr.lower() == 'srcset':
            safe_value = sanitize_srcset(value)
        elif is_safe_href(value):
            safe_value = value
        else:
            safe_value = '#'
        if quote:
            return f'{attr}={quote}{safe_value}{quote}'
        return f'{attr}={safe_value}'

    url_attrs = (
        r'href|src|action|formaction|data|poster|srcset|ping|background|cite|'
        r'dynsrc|lowsrc'
    )
    html = re.sub(
        rf'\b({url_attrs})\s*=\s*(["\'])(.*?)\2',
        lambda m: rewrite(m.group(1), m.group(2), m.group(3)),
        html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return re.sub(
        rf'\b({url_attrs})\s*=\s*([^"\'>\s]+)',
        lambda m: rewrite(m.group(1), '', m.group(2)),
        html,
        flags=re.IGNORECASE,
    )
