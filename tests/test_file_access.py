import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

from core.file_access import (
    ConflictError,
    FileAccessError,
    read_website_file,
    save_website_file,
    visual_editor_safe,
    website_root,
)


def test_website_root_is_public_vault():
    assert website_root(ROOT) == (ROOT / "brain/vault/public").resolve()


def test_body_save_preserves_frontmatter_bytes_and_unknown_fields(tmp_path):
    root = tmp_path / "brain/vault/public"
    path = root / "pages" / "sample.md"
    original = (
        "---\n"
        "id: 0199da90-c200-7056-ac0b-6f1d82bd2f41\n"
        "url: /pages/sample/\n"
        "created: '2026-01-01'\n"
        "custom_flag: keep-me\n"
        "title: Sample\n"
        "---\n"
        "\nHello\n"
    )
    path.parent.mkdir(parents=True)
    path.write_text(original)

    current = read_website_file(root, "pages/sample.md")
    saved = save_website_file(root, "pages/sample.md", revision=current.revision, body="\nChanged\n")

    text = path.read_text()
    assert "custom_flag: keep-me" in text
    assert "id: 0199da90-c200-7056-ac0b-6f1d82bd2f41" in text
    assert "url: /pages/sample/" in text
    assert "created: '2026-01-01'" in text
    assert "Changed" in text
    assert saved.revision != current.revision


def test_unchanged_save_does_not_rewrite_file(tmp_path):
    root = tmp_path / "vault"
    path = root / "pages" / "same.md"
    original = "---\ntitle: Same\n---\n\nBody\n"
    path.parent.mkdir(parents=True)
    path.write_text(original)
    current = read_website_file(root, "pages/same.md")
    save_website_file(root, "pages/same.md", revision=current.revision, body=current.body)
    assert path.read_text() == original
    assert read_website_file(root, "pages/same.md").revision == current.revision


def test_conflicting_save_keeps_disk_and_reports_revision(tmp_path):
    root = tmp_path / "vault"
    path = root / "pages" / "race.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\ntitle: Race\n---\n\nOne\n")
    first = read_website_file(root, "pages/race.md")
    path.write_text("---\ntitle: Race\n---\n\nTwo\n")

    with pytest.raises(ConflictError) as exc:
        save_website_file(root, "pages/race.md", revision=first.revision, body="\nUnsaved\n")

    assert path.read_text().endswith("Two\n")
    assert exc.value.current.body.endswith("Two\n")
    assert "Unsaved" not in path.read_text()


def test_path_escape_is_rejected(tmp_path):
    root = tmp_path / "vault"
    root.mkdir()
    with pytest.raises(FileAccessError):
        read_website_file(root, "../secret.md")


def test_tables_are_not_visual_safe():
    assert visual_editor_safe("Hello")
    assert not visual_editor_safe("| a | b |\n| --- | --- |\n")
    assert not visual_editor_safe("```\ncode\n```")
