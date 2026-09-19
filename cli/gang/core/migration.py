"""
Compatibility migrations for legacy content.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import yaml


REQUIRED_PLAN_FIELDS = {
    "source_path",
    "destination_path",
    "id",
    "current_url",
    "expected_future_url",
    "expected_source_content_hash",
    "classification",
    "approved_frontmatter_transformations",
}


class MigrationError(Exception):
    """Raised when migration preconditions fail."""


def parse_markdown(content: str) -> Tuple[Dict[str, Any], str]:
    """Return frontmatter and body while preserving the body bytes as text."""
    if not content.startswith("---"):
        return {}, content

    parts = content.split("---", 2)
    if len(parts) < 3:
        return {}, content

    frontmatter = yaml.safe_load(parts[1]) or {}
    return frontmatter, parts[2]


def normalize_for_json(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: normalize_for_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [normalize_for_json(item) for item in value]
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump_markdown(frontmatter: Dict[str, Any], body: str) -> str:
    rendered_frontmatter = yaml.safe_dump(
        frontmatter,
        default_flow_style=False,
        sort_keys=False,
        allow_unicode=True,
    )
    return f"---\n{rendered_frontmatter}---{body}"


@dataclass
class MigrationResult:
    source_path: str
    destination_path: str
    status: str
    message: str
    id: str
    current_url: str
    expected_future_url: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source_path": self.source_path,
            "destination_path": self.destination_path,
            "status": self.status,
            "message": self.message,
            "id": self.id,
            "current_url": self.current_url,
            "expected_future_url": self.expected_future_url,
        }


class LegacyContentMigrator:
    """Apply a durable legacy-content migration plan."""

    def __init__(self, repo_root: Path):
        self.repo_root = repo_root

    def load_plan(self, plan_path: Path) -> Dict[str, Any]:
        resolved = self._resolve(plan_path)
        if not resolved.exists():
            raise MigrationError(f"Migration plan not found: {plan_path}")

        data = json.loads(resolved.read_text())
        records = data.get("records")
        if not isinstance(records, list) or not records:
            raise MigrationError("Migration plan must contain a non-empty records list")

        for index, record in enumerate(records, start=1):
            missing = REQUIRED_PLAN_FIELDS.difference(record)
            if missing:
                fields = ", ".join(sorted(missing))
                raise MigrationError(f"Record {index} is missing required field(s): {fields}")
            if record["current_url"] != record["expected_future_url"]:
                raise MigrationError(
                    f"URL mismatch for {record['source_path']}: "
                    f"{record['current_url']} != {record['expected_future_url']}"
                )

        return data

    def apply_plan(self, plan_path: Path, apply: bool = False) -> Dict[str, Any]:
        plan = self.load_plan(plan_path)
        prepared = [self._inspect_record(record) for record in plan["records"]]
        results = [item[0] for item in prepared]
        failures = [result for result in results if result.status == "failed"]

        if apply and not failures:
            applied_results: List[MigrationResult] = []
            for result, destination_path, expected_content in prepared:
                if result.status == "would_write":
                    destination_path.parent.mkdir(parents=True, exist_ok=True)
                    destination_path.write_text(expected_content)
                    applied_results.append(
                        MigrationResult(
                            source_path=result.source_path,
                            destination_path=result.destination_path,
                            status="written",
                            message="destination created",
                            id=result.id,
                            current_url=result.current_url,
                            expected_future_url=result.expected_future_url,
                        )
                    )
                else:
                    applied_results.append(result)
            results = applied_results

        audit = {
            "plan": str(plan_path),
            "mode": "apply" if apply else "dry-run",
            "records": len(results),
            "written": len([r for r in results if r.status == "written"]),
            "unchanged": len([r for r in results if r.status == "unchanged"]),
            "would_write": len([r for r in results if r.status == "would_write"]),
            "failed": len(failures),
            "results": [result.as_dict() for result in results],
            "excluded_records": plan.get("excluded_records", []),
        }

        reports_dir = self.repo_root / "reports"
        reports_dir.mkdir(exist_ok=True)
        (reports_dir / "migration-audit.json").write_text(json.dumps(audit, indent=2) + "\n")

        manifest = {
            "migration": plan.get("migration"),
            "records": [
                {
                    "source_path": record["source_path"],
                    "destination_path": record["destination_path"],
                    "id": record["id"],
                    "current_url": record["current_url"],
                    "expected_future_url": record["expected_future_url"],
                    "source_hash": record["expected_source_content_hash"],
                    "classification": record["classification"],
                }
                for record in plan["records"]
            ],
        }
        (reports_dir / "migration-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")

        if failures:
            messages = "; ".join(f"{item.source_path}: {item.message}" for item in failures)
            raise MigrationError(messages)

        return audit

    def _inspect_record(self, record: Dict[str, Any]) -> Tuple[MigrationResult, Path, str]:
        source_path = self._resolve(Path(record["source_path"]))
        destination_path = self._resolve(Path(record["destination_path"]))
        expected_hash = record["expected_source_content_hash"]

        base = {
            "source_path": record["source_path"],
            "destination_path": record["destination_path"],
            "id": record["id"],
            "current_url": record["current_url"],
            "expected_future_url": record["expected_future_url"],
        }

        if not source_path.exists():
            return MigrationResult(status="failed", message="source file missing", **base), destination_path, ""

        actual_hash = sha256_file(source_path)
        if actual_hash != expected_hash:
            result = MigrationResult(
                status="failed",
                message=f"source hash changed: expected {expected_hash}, got {actual_hash}",
                **base,
            )
            return result, destination_path, ""

        expected_content = self._render_destination(source_path, record)

        if destination_path.exists():
            current_content = destination_path.read_text()
            if current_content == expected_content:
                result = MigrationResult(status="unchanged", message="destination already migrated", **base)
                return result, destination_path, expected_content
            result = MigrationResult(
                status="failed",
                message="destination exists and does not match expected migration output",
                **base,
            )
            return result, destination_path, expected_content

        result = MigrationResult(status="would_write", message="destination would be created", **base)
        return result, destination_path, expected_content

    def _render_destination(self, source_path: Path, record: Dict[str, Any]) -> str:
        source = source_path.read_text()
        frontmatter, body = parse_markdown(source)
        frontmatter = dict(frontmatter)

        content_type = record.get("canonical_type") or self._infer_type(record["destination_path"])
        created = frontmatter.get("created") or frontmatter.get("date")
        updated = frontmatter.get("updated") or frontmatter.get("date") or created

        canonical: Dict[str, Any] = {
            "id": record["id"],
            "type": content_type,
            "title": frontmatter.get("title"),
            "created": normalize_for_json(created),
            "updated": normalize_for_json(updated),
            "visibility": "public",
            "status": "published",
            "url": record["current_url"],
        }

        merged: Dict[str, Any] = {}
        for key, value in canonical.items():
            if value not in (None, ""):
                merged[key] = value

        for key, value in frontmatter.items():
            if key not in merged:
                merged[key] = normalize_for_json(value)

        for key, value in record.get("frontmatter_overrides", {}).items():
            if value is None:
                merged.pop(key, None)
            else:
                merged[key] = normalize_for_json(value)

        return dump_markdown(merged, body)

    def _infer_type(self, destination_path: str) -> str:
        parts = Path(destination_path).parts
        if "posts" in parts:
            return "post"
        if "projects" in parts:
            return "project"
        if "newsletters" in parts:
            return "newsletter"
        if "products" in parts:
            return "product"
        return "page"

    def _resolve(self, path: Path) -> Path:
        if path.is_absolute():
            return path
        return self.repo_root / path
