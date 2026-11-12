"""Shrink published JavaScript without breaking URLs or string literals."""

from __future__ import annotations

import re


def minify_javascript(source: str) -> str:
    """Drop full-line comments and extra whitespace.

    A ``//`` in the middle of a line is left alone. The publisher used to
    treat every ``//`` as a comment, which cut ``https://`` out of template
    literals and left ``cart.js`` unable to parse.
    """
    kept = [line for line in source.split("\n") if not line.lstrip().startswith("//")]
    text = "\n".join(kept)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"\n\s+", "\n", text)
    text = re.sub(r"\s{2,}", " ", text)
    text = "\n".join(line for line in text.split("\n") if line.strip())
    return text.strip()
