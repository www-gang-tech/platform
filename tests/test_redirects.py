"""Redirects saved by the CLI are the ones a vault build publishes."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

from core.redirects import RedirectManager, redirects_file_for


def _repo(tmp_path: Path) -> Path:
    (tmp_path / "gang.config.yml").write_text("site:\n  title: GANG\n")
    (tmp_path / "content").mkdir()
    vault = tmp_path / "brain" / "vault" / "public"
    vault.mkdir(parents=True)
    (tmp_path / ".redirects.json").write_text(
        json.dumps(
            {
                "redirects": [
                    {"from": "/old/", "to": "/new/", "status": 301, "reason": "manual"}
                ],
                "version": "1.0",
            }
        )
    )
    return tmp_path


def test_vault_build_reads_the_repository_redirect_file(tmp_path):
    repo = _repo(tmp_path)
    vault = repo / "brain" / "vault" / "public"
    legacy = repo / "content"
    dist = repo / "dist"

    assert redirects_file_for(vault) == repo / ".redirects.json"
    assert redirects_file_for(legacy) == repo / ".redirects.json"

    from_vault = RedirectManager(vault, dist)
    from_cli = RedirectManager(legacy, dist)
    assert from_vault.list_all_redirects() == from_cli.list_all_redirects()
    assert from_vault.list_all_redirects()[0]["from"] == "/old/"

    from_vault.add_redirect("/older/", "/newer/", reason="manual")
    saved = json.loads((repo / ".redirects.json").read_text())
    assert [item["from"] for item in saved["redirects"]] == ["/old/", "/older/"]
    assert not (repo / "brain" / "vault" / ".redirects.json").exists()

    dist.mkdir()
    from_vault.write_redirects_file()
    published = (dist / "_redirects").read_text()
    assert "/old/ /new/ 301" in published
    assert "/older/ /newer/ 301" in published


def test_redirects_without_a_project_config_stay_beside_the_content_dir(tmp_path):
    content = tmp_path / "notes"
    content.mkdir()
    assert redirects_file_for(content) == content.parent / ".redirects.json"
