"""
Shared HTML / URL sanitizers for Markdown fragments and template hrefs.
"""

from __future__ import annotations

import html
import re
from typing import Any, Optional
from urllib.parse import unquote, urlparse, urlunparse

# Browsers decode named/numeric colon entities in hrefs; html.unescape does not.
_COLON_ENTITY_RE = re.compile(r'(?i)&colon;|&#0*58;|&#x0*3a;')
_HTML_COMMENT_RE = re.compile(r'<!--[\s\S]*?-->')
_LEFTOVER_SCRIPT_RE = re.compile(r'(?is)<script\b[^>]*>.*?</script>|<script\b[^>]*>')


def _normalize_href_entities(value: str) -> str:
    """Unescape HTML entities, including ``&colon;``, before scheme checks."""
    current = str(value)
    for _ in range(3):
        nxt = html.unescape(current)
        nxt = _COLON_ENTITY_RE.sub(':', nxt)
        if nxt == current:
            break
        current = nxt
    return current


def _href_has_dotdot(path: str) -> bool:
    # ``..;`` and ``..%00`` are traversal gadgets on some proxies/servers.
    return any(segment == '..' or segment.startswith('..') for segment in path.split('/'))


def _is_safe_href_candidate(value: str) -> bool:
    """Single-pass href policy on an already-normalized candidate."""
    if not value:
        return False
    if '\x00' in value or '%00' in value.lower():
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
            parsed = urlparse(value)
            # Userinfo (`https://trusted@evil.com`) is a phishing gadget.
            if '@' in (parsed.netloc or '') or parsed.username:
                return False
            host = (parsed.netloc or '').split('@')[-1]
            return bool(host) and host not in ('.', '..')
        return False
    # Relative / root-relative / fragment: reject path traversal and embedded
    # `//` (`/.//evil.com`, `/foo//bar`) so href policy matches redirects.
    if _href_has_dotdot(scheme_host):
        return False
    return '//' not in scheme_host


def is_safe_href(value: Optional[str]) -> bool:
    """Allow relative paths, anchors, http(s), and mailto; reject javascript: etc."""
    if not value:
        return False
    value = _normalize_href_entities(str(value).strip())
    if not value:
        return False
    if not _is_safe_href_candidate(value):
        return False
    # Percent-decode so /%2f/evil.com and /%2e%2e/admin cannot bypass prefix checks.
    decoded = value
    for _ in range(3):
        nxt = _normalize_href_entities(unquote(decoded))
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

    # Comments are not elements; leftover ``<!--><script>`` text still executes.
    html = _HTML_COMMENT_RE.sub('', html)
    # Unclosed ``<!-->`` gadgets leave the tail as a text node (event handlers).
    html = re.sub(r'<!--[\s\S]*', '', html)

    soup = BeautifulSoup(f'<div id="gang-md-root">{html}</div>', 'html.parser')
    root = soup.find(id='gang-md-root')
    if root is None:
        return ''

    forbidden_tags = {
        'script', 'style', 'iframe', 'object', 'embed', 'link', 'meta',
        'base', 'form', 'input', 'button', 'textarea', 'select',
        'svg', 'math', 'handler', 'set', 'animate', 'foreignobject',
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

    result = ''.join(str(child) for child in root.contents)
    # Parser quirks can leave ``<script>`` in text nodes or nested fragments.
    result = _LEFTOVER_SCRIPT_RE.sub('', result)
    result = re.sub(
        r'(?is)<(iframe|object|embed|svg|math)\b[^>]*>.*?</\1>|<(iframe|object|embed|svg|math)\b[^>]*>',
        '',
        result,
    )
    return re.sub(r'(?is)\s+on\w+\s*=\s*("[^"]*"|\'[^\']*\'|[^\s>]+)', '', result)


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
        elif value.lower().startswith(('http://', 'https://')):
            safe_value = safe_http_url(value) or '#'
        elif is_safe_href(value):
            safe_value = value
        else:
            safe_value = '#'
        if quote:
            return f'{attr}={quote}{safe_value}{quote}'
        return f'{attr}={safe_value}'

    url_attrs = (
        r'href|src|action|formaction|data|poster|srcset|ping|background|cite|'
        r'dynsrc|lowsrc|xlink:href'
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
