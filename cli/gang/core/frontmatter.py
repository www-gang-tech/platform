"""Helpers for writing markdown frontmatter consistently."""

from pathlib import Path
from typing import Any, Dict, Tuple

import yaml


def dump_frontmatter(frontmatter: Dict[str, Any], body: str) -> str:
    """Serialize markdown with normalized YAML frontmatter delimiters."""
    yaml_text = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).strip()
    body = body.lstrip('\n')
    return f"---\n{yaml_text}\n---\n{body}"


def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter; always return a dict (never None/list/scalar).

    Malformed YAML fails closed as ``status: draft`` so schedulers cannot
    publish files whose draft marker was lost to a parse error.
    """
    if not content.startswith('---'):
        return {}, content
    parts = content.split('---', 2)
    if len(parts) < 2:
        return {}, content
    try:
        loaded = yaml.safe_load(parts[1]) if parts[1].strip() else {}
    except Exception:
        body = parts[2] if len(parts) > 2 else ''
        return {'status': 'draft', '_yaml_error': True}, body
    frontmatter = loaded if isinstance(loaded, dict) else {}
    body = parts[2] if len(parts) > 2 else ''
    return frontmatter, body


def update_slug_in_file(file_path: Path, new_slug: str) -> bool:
    """Update frontmatter ``slug`` after a file rename. Returns True if rewritten."""
    content = file_path.read_text(encoding='utf-8')
    if not content.startswith('---'):
        return False
    parts = content.split('---', 2)
    if len(parts) < 3:
        return False
    try:
        frontmatter = yaml.safe_load(parts[1]) or {}
    except Exception:
        return False
    if not isinstance(frontmatter, dict):
        return False
    current = frontmatter.get('slug')
    if current is not None and str(current) == new_slug:
        return False
    frontmatter['slug'] = new_slug
    file_path.write_text(dump_frontmatter(frontmatter, parts[2]), encoding='utf-8')
    return True
