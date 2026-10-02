"""Minify built assets without changing quoted CSS values.

Navigation and breadcrumbs separate items with spaces inside `content`
strings. A whitespace collapse that ignores quotes turns `content: "   "`
into a single space and pulls those items together.
"""

from __future__ import annotations

import re


def minify_css(css: str) -> str:
    """Drop comments and extra whitespace, leaving quoted strings intact."""
    out: list[str] = []
    code: list[str] = []
    i = 0
    n = len(css)

    def flush_code() -> None:
        if not code:
            return
        text = "".join(code)
        text = re.sub(r"\s+", " ", text)
        text = re.sub(r"\s*([{}:;,])\s*", r"\1", text)
        out.append(text)
        code.clear()

    while i < n:
        if css.startswith("/*", i):
            end = css.find("*/", i + 2)
            if end < 0:
                code.append(css[i:])
                break
            i = end + 2
            continue
        quote = css[i]
        if quote in {'"', "'"}:
            flush_code()
            end = i + 1
            while end < n:
                if css[end] == "\\":
                    end += 2
                    continue
                if css[end] == quote:
                    end += 1
                    break
                end += 1
            out.append(css[i:end])
            i = end
            continue
        code.append(quote)
        i += 1
    flush_code()
    return "".join(out).strip()
