"""
Shared HTML / URL sanitizers for Markdown fragments and template hrefs.
"""

from __future__ import annotations

import html
import ipaddress
import re
import unicodedata
from typing import Any, Optional
from urllib.parse import unquote, urlparse, urlunparse

# Browsers decode named/numeric colon entities in hrefs; html.unescape does not.
_COLON_ENTITY_RE = re.compile(r'(?i)&colon;|&#0*58;|&#x0*3a;')
_HTML_COMMENT_RE = re.compile(r'<!--[\s\S]*?-->')
_LEFTOVER_SCRIPT_RE = re.compile(r'(?is)<script\b[^>]*>.*?</script>|<script\b[^>]*>')


def _normalize_href_entities(value: str) -> str:
    """Unescape HTML entities, including ``&colon;``, before scheme checks."""
    current = unicodedata.normalize('NFKC', str(value))
    for _ in range(3):
        nxt = html.unescape(current)
        nxt = _COLON_ENTITY_RE.sub(':', nxt)
        nxt = unicodedata.normalize('NFKC', nxt)
        if nxt == current:
            break
        current = nxt
    return current


def _href_has_dotdot(path: str) -> bool:
    # ``..;`` and ``..%00`` are traversal gadgets on some proxies/servers.
    return any(segment == '..' or segment.startswith('..') for segment in path.split('/'))


def _ipv4_part_is_decimal(part: str) -> bool:
    """Reject leading-zero octets so browsers cannot treat them as octal."""
    return bool(part) and part.isdigit() and not (len(part) > 1 and part.startswith('0'))


_REBIND_HOSTS = {'localtest.me'}
_REBIND_SUFFIXES = ('.nip.io', '.sslip.io', '.xip.io', '.localtest.me')
_SHOPIFY_PLATFORM_HOSTS = {'www.shopify.com', 'shopify.com'}
_SHOPIFY_CDN_HOSTS = {'cdn.shopify.com', 'cdn.shopifycdn.net'}


def _is_blocked_shopify_host(host: str) -> bool:
    """Reject Shopify marketing/admin hosts, but keep CDN image hosts."""
    hostname = (host or '').strip().lower().strip('[]')
    if hostname in _SHOPIFY_CDN_HOSTS:
        return False
    return hostname in _SHOPIFY_PLATFORM_HOSTS or hostname.endswith('.shopify.com')


def _normalize_http_host(host: str) -> str:
    """Lowercase, strip brackets, and drop a trailing DNS dot browsers ignore."""
    host = (host or '').strip().lower().strip('[]')
    while host.endswith('.') and host not in {'.', ''}:
        host = host[:-1]
    return host


def _coerce_ipv4(host: str) -> Optional[str]:
    """Expand decimal and short IPv4 forms browsers accept (``127.1``, ``2130706433``)."""
    if re.fullmatch(r'\d+', host):
        if not _ipv4_part_is_decimal(host):
            return None
        try:
            value = int(host)
            if 0 <= value <= 0xFFFFFFFF:
                return str(ipaddress.IPv4Address(value))
        except (ValueError, OverflowError):
            return None
        return None
    if not re.fullmatch(r'\d+(\.\d+){1,3}', host):
        return None
    raw_parts = host.split('.')
    if not all(_ipv4_part_is_decimal(part) for part in raw_parts):
        return None
    parts = [int(part) for part in raw_parts]
    if any(part > 255 for part in parts):
        return None
    if len(parts) == 2:
        return str(ipaddress.IPv4Address((parts[0] << 24) | parts[1]))
    if len(parts) == 3:
        return str(ipaddress.IPv4Address((parts[0] << 24) | (parts[1] << 16) | parts[2]))
    return f'{parts[0]}.{parts[1]}.{parts[2]}.{parts[3]}'


def _is_public_http_host(host: str) -> bool:
    """Reject loopback, RFC1918, link-local, and other non-public HTTP hosts."""
    host = _normalize_http_host(host)
    if not host or host in {'localhost', '0.0.0.0', '::', '::1'}:
        return False
    if host.endswith(('.localhost', '.local', '.internal', '.lan')):
        return False
    if host in _REBIND_HOSTS or host.endswith(_REBIND_SUFFIXES):
        return False
    # Browsers accept hex IPv4 labels (``0x7f.0.0.1`` → 127.0.0.1).
    if any(re.fullmatch(r'(?i)0x[0-9a-f]+', label) for label in host.split('.')):
        return False
    numeric = bool(re.fullmatch(r'\d+(\.\d+){0,3}', host))
    candidate = _coerce_ipv4(host)
    if numeric and not candidate:
        # Leading-zero / octal / junk dotted quads are not public hostnames.
        return False
    candidate = candidate or host
    try:
        ip = ipaddress.ip_address(candidate)
    except ValueError:
        # Single-label hosts are LAN/mDNS-style, not public publish targets.
        return '.' in host and not host.startswith('.')
    # IPv4-mapped IPv6 (`::ffff:127.0.0.1`) is reserved as a prefix, so apply
    # the IPv4 public-host policy to the embedded address instead.
    if ip.version == 6 and ip.ipv4_mapped is not None:
        return _is_public_http_host(str(ip.ipv4_mapped))
    cgnat = ipaddress.ip_network('100.64.0.0/10')
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
        or (ip.version == 4 and ip in cgnat)
    )


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
            addr = lower[7:].split('?', 1)[0]
            # Reject mailto:javascript:… and nested schemes in local or domain.
            return bool(addr) and addr.count('@') <= 1 and ':' not in addr
        if lower.startswith(('http://', 'https://')):
            parsed = urlparse(value)
            # Userinfo (`https://trusted@evil.com`) is a phishing gadget.
            if '@' in (parsed.netloc or '') or parsed.username:
                return False
            host = parsed.hostname or (parsed.netloc or '').split('@')[-1].split(':')[0]
            return _is_public_http_host(host)
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
    hostname = parsed.hostname or host.split(':')[0]
    if not host or not _is_public_http_host(hostname):
        return ''
    if _is_blocked_shopify_host(hostname):
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
