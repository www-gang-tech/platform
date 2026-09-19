import hashlib
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli" / "gang"))

from core.migration_analysis import MigrationAnalyzer


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def config():
    return {
        "site": {"url": "https://example.test"},
        "build": {"content": "content", "public": "public"},
    }


def analyze(root):
    return MigrationAnalyzer(config(), root_path=root, now=NOW).analyze()


def doc(analysis, path):
    for item in analysis["documents"]:
        if item["current_path"] == path:
            return item
    raise AssertionError(f"Missing document {path}")


def test_published_legacy_content_maps_to_public_published(tmp_path):
    write(
        tmp_path / "content/posts/hello.md",
        "---\ntitle: Hello\nstatus: published\ndate: 2025-01-01\n---\nBody",
    )

    analysis = analyze(tmp_path)
    item = doc(analysis, "content/posts/hello.md")

    assert item["currently_public"] is True
    assert item["proposed_record"]["visibility"] == "public"
    assert item["proposed_record"]["status"] == "published"
    assert item["current_public_url"] == "/posts/hello/"
    assert item["proposed_record"]["public_url"] == "/posts/hello/"


def test_draft_content_does_not_become_public(tmp_path):
    write(
        tmp_path / "content/pages/draft.md",
        "---\ntitle: Draft\nstatus: draft\ndate: 2025-01-01\n---\nBody",
    )

    item = doc(analyze(tmp_path), "content/pages/draft.md")

    assert item["currently_public"] is False
    assert item["proposed_record"]["visibility"] == "private"
    assert item["proposed_record"]["status"] == "draft"
    assert item["proposed_record"]["public_url"] is None


def test_missing_status_preserves_legacy_public_behavior_and_warns(tmp_path):
    write(tmp_path / "content/posts/no-status.md", "---\ntitle: No Status\ndate: 2025-01-01\n---\nBody")

    item = doc(analyze(tmp_path), "content/posts/no-status.md")

    assert item["currently_public"] is True
    assert item["proposed_record"]["visibility"] == "public"
    assert item["proposed_record"]["status"] == "published"
    assert item["warnings"] == []
    assert any("legacy_publication_inferred" in notice for notice in item["notices"])
    assert item["safe_to_migrate"] is True


def test_url_remains_unchanged_when_target_moves_to_vault(tmp_path):
    write(
        tmp_path / "content/projects/rebuild.md",
        "---\ntitle: Rebuild\nstatus: published\ndate: 2025-01-01\n---\nBody",
    )

    item = doc(analyze(tmp_path), "content/projects/rebuild.md")

    assert item["current_public_url"] == "/projects/rebuild/"
    assert item["proposed_record"]["public_url"] == "/projects/rebuild/"
    assert item["proposed_record"]["canonical_vault_location"] == "brain/vault/public/projects/rebuild.md"


def test_non_public_vault_records_do_not_use_private_prefix(tmp_path):
    write(
        tmp_path / "content/pages/draft.md",
        "---\ntitle: Draft\nstatus: draft\ndate: 2025-01-01\n---\nBody",
    )

    item = doc(analyze(tmp_path), "content/pages/draft.md")

    assert item["proposed_record"]["canonical_vault_location"] == "brain/vault/pages/draft.md"
    assert "/private/" not in item["proposed_record"]["canonical_vault_location"]


def test_duplicate_slug_and_url_detection(tmp_path):
    write(tmp_path / "content/posts/same.md", "---\ntitle: Same\nstatus: published\n---\nBody")
    write(tmp_path / "content/articles/same.md", "---\ntitle: Same Article\nstatus: published\n---\nBody")

    analysis = analyze(tmp_path)
    conflict_types = {item["type"] for item in analysis["conflicts"]}

    assert "duplicate_slug" in conflict_types
    assert "duplicate_url" in conflict_types
    assert all(item["safe_to_migrate"] is False for item in analysis["documents"])


def test_malformed_frontmatter_is_reported(tmp_path):
    write(tmp_path / "content/posts/bad.md", "---\ntitle: [bad\n---\nBody")

    item = doc(analyze(tmp_path), "content/posts/bad.md")

    assert item["malformed_frontmatter"] is True
    assert any("Malformed frontmatter" in warning for warning in item["warnings"])


def test_unknown_fields_are_preserved_in_report(tmp_path):
    write(
        tmp_path / "content/posts/unknown.md",
        "---\ntitle: Unknown\nstatus: published\nritual_score: 7\n---\nBody",
    )

    analysis = analyze(tmp_path)
    item = doc(analysis, "content/posts/unknown.md")
    mapping = {field["current"]: field for field in analysis["field_mapping"]}

    assert "ritual_score" in item["proposed_record"]["fields_cannot_map_deterministically"]
    assert mapping["ritual_score"]["classification"] == "unknown"


def test_shopify_transactional_fields_are_external_authority(tmp_path):
    write(
        tmp_path / "content/examples/product.md",
        "---\ntitle: Charger\ntype: product\nprice: '39.99'\ninventory: 3\nsku: CH-1\nstory: Made here\n---\nBody",
    )

    product = analyze(tmp_path)["product_analysis"][0]

    assert set(product["external_authority_fields"]) >= {"inventory", "price", "sku"}
    assert "title" in product["editorial_knowledge_fields"]


def test_excluded_example_files_are_not_proposed_as_vault_knowledge(tmp_path):
    write(
        tmp_path / "content/examples/product-example.md",
        "---\ntitle: Charger\ntype: product\nprice: '39.99'\njsonld: {}\n---\nBody",
    )

    analysis = analyze(tmp_path)
    item = doc(analysis, "content/examples/product-example.md")

    assert item["source_classification"] == "fixture/example"
    assert item["migration_status"] == "excluded_from_migration"
    assert item["excluded_from_migration"] is True
    assert item["proposed_record"]["canonical_vault_location"] is None
    assert item["proposed_record"]["id"] is None
    assert analysis["summary"]["excluded_from_migration"] == 1
    assert analysis["summary"]["review_required"] == 0


def test_documentation_can_be_excluded(tmp_path):
    write(tmp_path / "content/comments/README.md", "---\nseo: {}\njsonld: {}\n---\n# Comments")

    item = doc(analyze(tmp_path), "content/comments/README.md")

    assert item["source_classification"] == "documentation"
    assert item["migration_status"] == "excluded_from_migration"
    assert item["proposed_record"]["canonical_vault_location"] is None


def test_missing_title_still_blocks_public_migration(tmp_path):
    write(tmp_path / "content/posts/no-title.md", "---\nstatus: published\ndate: 2025-01-01\n---\nBody")

    item = doc(analyze(tmp_path), "content/posts/no-title.md")

    assert "Missing title" in item["warnings"]
    assert item["safe_to_migrate"] is False
    assert item["migration_status"] == "review_required"


def test_uuidv7_values_are_valid_and_not_timestamp_zero(tmp_path):
    write(tmp_path / "content/posts/uuid.md", "---\ntitle: UUID\nstatus: published\ndate: 2025-01-01\n---\nBody")

    item = doc(analyze(tmp_path), "content/posts/uuid.md")
    parsed = uuid.UUID(item["proposed_record"]["id"])

    assert parsed.version == 7
    assert parsed.int >> 80 > 0


def test_migration_ids_remain_stable_across_repeated_analysis(tmp_path):
    write(tmp_path / "content/posts/stable.md", "---\ntitle: Stable\nstatus: published\n---\nBody")

    first_analyzer = MigrationAnalyzer(config(), root_path=tmp_path, now=NOW)
    first = first_analyzer.analyze()
    first_analyzer.write_reports(tmp_path / "reports", first)

    second = analyze(tmp_path)

    assert doc(first, "content/posts/stable.md")["proposed_record"]["id"] == doc(second, "content/posts/stable.md")["proposed_record"]["id"]


def test_legacy_jsonld_is_treated_as_generated_legacy(tmp_path):
    write(tmp_path / "content/posts/jsonld.md", "---\ntitle: JSONLD\nstatus: published\njsonld: {}\n---\nBody")

    analysis = analyze(tmp_path)
    mapping = {field["current"]: field for field in analysis["field_mapping"]}
    item = doc(analysis, "content/posts/jsonld.md")

    assert mapping["jsonld"]["classification"] == "generated_legacy"
    assert "jsonld" in item["proposed_record"]["fields_transformed"]


def test_analysis_does_not_modify_input_files(tmp_path):
    source = tmp_path / "content/posts/still.md"
    write(source, "---\ntitle: Still\nstatus: published\n---\nBody")
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    analyzer = MigrationAnalyzer(config(), root_path=tmp_path, now=NOW)
    analysis = analyzer.analyze()
    analyzer.write_reports(tmp_path / "reports", analysis)
    after = hashlib.sha256(source.read_bytes()).hexdigest()

    assert before == after
    assert (tmp_path / "reports/migration-analysis.json").exists()
    assert (tmp_path / "reports/migration-analysis.md").exists()
    assert (tmp_path / "reports/migration-manifest.json").exists()


def test_source_files_remain_untouched_after_repeated_analysis(tmp_path):
    source = tmp_path / "content/posts/stable.md"
    write(source, "---\ntitle: Stable\nstatus: published\n---\nBody")
    before = hashlib.sha256(source.read_bytes()).hexdigest()

    first_analyzer = MigrationAnalyzer(config(), root_path=tmp_path, now=NOW)
    first = first_analyzer.analyze()
    first_analyzer.write_reports(tmp_path / "reports", first)
    second = analyze(tmp_path)
    after = hashlib.sha256(source.read_bytes()).hexdigest()

    assert before == after
    assert doc(first, "content/posts/stable.md")["proposed_record"]["id"] == doc(second, "content/posts/stable.md")["proposed_record"]["id"]
