import importlib.util
import json
import sys
import uuid
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

from core.content_loader import PublicContentError, load_public_content


EXPECTED_PUBLIC_URLS = {
    "/newsletters/qi2-launch-newsletter/",
    "/pages/about/",
    "/pages/contact/",
    "/pages/faq/",
    "/pages/features/",
    "/pages/manifesto/",
    "/pages/wcag-conformance/",
    "/posts/qi2-launch/",
    "/projects/design-system-rebuild/",
}


def repo_config():
    return yaml.safe_load((ROOT / "gang.config.yml").read_text())


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def load_cli_module():
    spec = importlib.util.spec_from_file_location("gang_cli_for_tests", ROOT / "cli" / "gang" / "cli.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_all_current_public_urls_have_canonical_vault_documents():
    docs = load_public_content(repo_config(), source="vault", root_path=ROOT)

    assert {doc.url for doc in docs} == EXPECTED_PUBLIC_URLS
    assert len(docs) == 9


def test_legacy_and_vault_public_urls_match_before_cutover():
    legacy = {doc.url for doc in load_public_content(repo_config(), source="legacy", root_path=ROOT)}
    vault = {doc.url for doc in load_public_content(repo_config(), source="vault", root_path=ROOT)}

    assert legacy == vault == EXPECTED_PUBLIC_URLS


def test_canonical_vault_documents_have_required_public_contract_fields():
    docs = load_public_content(repo_config(), source="vault", root_path=ROOT)

    for doc in docs:
        assert uuid.UUID(doc.id).version == 7
        assert doc.visibility == "public"
        assert doc.status == "published"
        assert doc.url.startswith("/") and doc.url.endswith("/")
        assert doc.title
        assert doc.created


def test_migration_plan_contains_stable_qi2_id_and_resolution():
    plan = json.loads((ROOT / "migrations" / "legacy-content-v1.json").read_text())
    records = {record["source_path"]: record for record in plan["records"]}
    qi2 = records["content/posts/qi2-launch.md"]

    assert len(records) == 9
    assert qi2["id"] == "0199da90-c200-7056-ac0b-6f1d82bd2f41"
    assert uuid.UUID(qi2["id"]).version == 7
    assert qi2["metadata_resolution"]["title"] == "Qi2 Launch"
    assert qi2["metadata_resolution"]["date"] == "2025-10-12"


def test_private_vault_document_cannot_enter_public_collection(tmp_path):
    config = {"build": {"content": "content"}}
    write(
        tmp_path / "brain/vault/public/pages/public.md",
        "---\nid: 0199da90-c200-7056-ac0b-6f1d82bd2f41\ntype: page\ntitle: Public\ncreated: '2025-01-01'\nvisibility: public\nstatus: published\nurl: /pages/public/\n---\n# Public",
    )
    write(
        tmp_path / "brain/vault/public/pages/private.md",
        "---\nid: 0199da90-c200-7056-ac0b-6f1d82bd2f42\ntype: page\ntitle: Private\ncreated: '2025-01-01'\nvisibility: private\nstatus: draft\nurl: /pages/private/\n---\n# Private",
    )

    docs = load_public_content(config, source="vault", root_path=tmp_path)

    assert [doc.url for doc in docs] == ["/pages/public/"]


def test_missing_vault_source_does_not_fall_back_to_legacy(tmp_path):
    config = {"build": {"content": "content"}}
    write(tmp_path / "content/pages/only-legacy.md", "---\ntitle: Only Legacy\n---\n# Only Legacy")

    with pytest.raises(PublicContentError):
        load_public_content(config, source="vault", root_path=tmp_path)


def test_build_defaults_to_vault_and_keeps_explicit_legacy_rollback():
    cli_module = load_cli_module()
    source_param = next(param for param in cli_module.build.params if param.name == "source")

    assert source_param.default == "vault"
    assert set(source_param.type.choices) == {"vault", "legacy"}
