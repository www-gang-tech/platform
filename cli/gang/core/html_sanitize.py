"""
Shared HTML / URL sanitizers for Markdown fragments and template hrefs.
"""

from __future__ import annotations

from typing import Optional


def is_safe_href(value: Optional[str]) -> bool:
    """Allow relative paths, anchors, http(s), and mailto; reject javascript: etc."""
    if not value:
        return False
    value = str(value).strip()
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
        return scheme_host.lower().startswith(('http:', 'https:', 'mailto:'))
    return True


def safe_href(value: Optional[str], fallback: str = '#') -> str:
    """Return value when safe, otherwise fallback."""
    return value if is_safe_href(value) else fallback


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
            # dynsrc is a legacy IE URL sink; treat like other dangerous attrs.
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

    # Quoted attributes first so srcset values with spaces are preserved.
    # Include ping/background — legacy URL sinks not covered by href/src alone.
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
