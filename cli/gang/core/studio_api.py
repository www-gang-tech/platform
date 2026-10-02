"""HTTP helpers shared by `gang studio` and the Flask in-page editor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Tuple

from .file_access import (
    ConflictError,
    FileAccessError,
    list_website_files,
    read_website_file,
    save_payload_from_request,
    website_root,
)
from .heading_validator import HeadingValidator


JsonResponse = Tuple[int, Any]


def studio_root(repo_root: Path | str = ".") -> Path:
    return website_root(repo_root)


def handle_list(root: Path) -> JsonResponse:
    return 200, list_website_files(root)


def handle_read(root: Path, relative_path: str) -> JsonResponse:
    try:
        document = read_website_file(root, relative_path)
    except FileAccessError as exc:
        return exc.status_code, {"error": str(exc)}
    return 200, document.to_payload()


def handle_save(root: Path, relative_path: str, raw_body: str, content_type: str, if_match: str = "") -> JsonResponse:
    try:
        document = save_payload_from_request(root, relative_path, raw_body, content_type, if_match)
    except ConflictError as exc:
        payload = exc.current.to_payload()
        payload["error"] = "conflict"
        payload["message"] = str(exc)
        return 409, payload
    except FileAccessError as exc:
        return exc.status_code, {"error": str(exc)}
    return 200, {"status": "saved", **document.to_payload()}


def handle_validate(raw_body: str) -> JsonResponse:
    try:
        data = json.loads(raw_body) if raw_body else {}
    except json.JSONDecodeError:
        return 400, {"error": "JSON body required"}
    content = data.get("content") or data.get("body") or ""
    validator = HeadingValidator()
    result = validator.validate_markdown(content)
    result["report"] = validator.generate_error_report(result)
    return 200, result
