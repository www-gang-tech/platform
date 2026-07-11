"""Helpers for writing markdown frontmatter consistently."""

from typing import Any, Dict

import yaml


def dump_frontmatter(frontmatter: Dict[str, Any], body: str) -> str:
    """Serialize markdown with normalized YAML frontmatter delimiters."""
    yaml_text = yaml.dump(frontmatter, default_flow_style=False, sort_keys=False).strip()
    body = body.lstrip('\n')
    return f"---\n{yaml_text}\n---\n{body}"
