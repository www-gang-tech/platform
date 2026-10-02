#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GANG Studio Backend API for local in-page editing."""

from flask import Flask, request, jsonify
from flask_cors import CORS
import os

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "cli" / "gang"))

from core.file_access import website_root
from core.studio_api import handle_list, handle_read, handle_save, handle_validate

app = Flask(__name__)
CORS(app)

CONTENT_DIR = website_root(PROJECT_ROOT)


@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "service": "gang-studio", "content": str(CONTENT_DIR)})


@app.route("/api/auth/status")
def auth_status():
    auth_header = request.headers.get("Authorization", "")
    authenticated = bool(auth_header) or os.environ.get("EDITOR_MODE") == "true"
    return jsonify(
        {
            "authenticated": authenticated,
            "user": {"email": "local@dev"} if authenticated else None,
        }
    )


@app.route("/api/content/list")
def list_content():
    status, payload = handle_list(CONTENT_DIR)
    return jsonify(payload), status


@app.route("/api/content", methods=["GET"])
def list_content_root():
    status, payload = handle_list(CONTENT_DIR)
    return jsonify(payload), status


@app.route("/api/content/<path:file_path>", methods=["GET"])
def get_content(file_path):
    status, payload = handle_read(CONTENT_DIR, file_path)
    return jsonify(payload), status


@app.route("/api/content/<path:file_path>", methods=["PUT"])
def save_content(file_path):
    status, payload = handle_save(
        CONTENT_DIR,
        file_path,
        request.get_data(as_text=True) or "",
        request.headers.get("Content-Type", ""),
        request.headers.get("If-Match", ""),
    )
    return jsonify(payload), status


@app.route("/api/validate-headings", methods=["POST"])
def validate_headings():
    status, payload = handle_validate(request.get_data(as_text=True) or "")
    return jsonify(payload), status


@app.route("/api/build", methods=["POST"])
def trigger_build():
    return jsonify(
        {
            "status": "local_only",
            "message": "Save writes the working file only. Release through git review, then gang build. This endpoint does not commit, push, or deploy.",
        }
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5001))
    print("GANG Studio backend (local file access only)")
    print("Website content:", CONTENT_DIR)
    app.run(host="127.0.0.1", port=port, debug=True)
