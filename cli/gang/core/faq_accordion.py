"""Turn FAQ Markdown headings into an accessible details/summary accordion."""

from __future__ import annotations

import re
from html import unescape
from typing import List

HEADING_SPLIT = re.compile(r"(<h[23][^>]*>.*?</h[23]>)", re.IGNORECASE | re.DOTALL)
HEADING_PARTS = re.compile(r"<h([23])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)


def slugify(text: str) -> str:
    plain = unescape(re.sub(r"<[^>]+>", "", text))
    slug = re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")
    return slug[:72] or "question"


def faq_html_to_accordion(html: str) -> str:
    """Convert h3 + following blocks into ARIA-labelled details/summary items.

    Authors keep writing Markdown: ``##`` for groups, ``###`` for questions.
    """
    html = re.sub(r"^\s*<h1[^>]*>.*?</h1>\s*", "", html, count=1, flags=re.IGNORECASE | re.DOTALL)
    html = re.sub(r"<hr\s*/?>", "", html, flags=re.IGNORECASE)
    tokens = HEADING_SPLIT.split(html)

    out: List[str] = ['<div class="faq-accordion">']
    pending_question: str | None = None
    pending_body: List[str] = []
    used_ids: dict[str, int] = {}

    def panel_id(question_html: str) -> str:
        base = slugify(question_html)
        used_ids[base] = used_ids.get(base, 0) + 1
        if used_ids[base] == 1:
            return base
        return f"{base}-{used_ids[base]}"

    def flush_item() -> None:
        nonlocal pending_question
        if pending_question is None:
            return
        slug = panel_id(pending_question)
        summary_id = f"faq-{slug}"
        panel = f"faq-panel-{slug}"
        body = "".join(pending_body).strip()
        out.append(
            "<details class=\"faq-item\" name=\"faq\">"
            f"<summary id=\"{summary_id}\" aria-controls=\"{panel}\">{pending_question}</summary>"
            f"<div id=\"{panel}\" class=\"faq-panel\" role=\"region\" aria-labelledby=\"{summary_id}\">"
            f"{body}</div>"
            "</details>"
        )
        pending_question = None
        pending_body.clear()

    for token in tokens:
        if not token:
            continue
        heading = HEADING_PARTS.fullmatch(token.strip())
        if heading:
            level, inner = heading.group(1), heading.group(2).strip()
            if level == "2":
                flush_item()
                out.append(f"<h2>{inner}</h2>")
            else:
                flush_item()
                pending_question = inner
            continue
        if pending_question is not None:
            pending_body.append(token)
        else:
            out.append(token)

    flush_item()
    out.append("</div>")
    return "".join(out)
