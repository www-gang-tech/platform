"""Helpers for reading and writing Markdown frontmatter."""

from typing import Any, Dict

import yaml


def dump_frontmatter(frontmatter: Dict[str, Any], body: str) -> str:
    """Serialize Markdown content with YAML frontmatter delimiters.

    The closing delimiter must be on its own line for common frontmatter
    parsers to recognize it reliably.
    """
    yaml_text = yaml.dump(frontmatter, default_flow_style=False).rstrip()
    body_text = body if body.startswith("\n") else f"\n{body}"
    return f"---\n{yaml_text}\n---{body_text}"
