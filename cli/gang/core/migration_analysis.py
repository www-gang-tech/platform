"""
Read-only migration analysis for future brain/vault records.
"""

from __future__ import annotations

import hashlib
import json
import re
import secrets
import uuid
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml


PUBLISHABLE_DIRS = {"posts", "articles", "pages", "projects", "newsletters"}
PUBLIC_URL_DIRS = {
    "articles": "posts",
    "newsletters": "newsletters",
    "pages": "pages",
    "posts": "posts",
    "projects": "projects",
}
STATUSES_PUBLIC = {"published", "ready"}
STATUSES_PRIVATE = {"draft", "private", "archived"}
EXCLUDED_PATHS = {"content/comments/README.md"}
EXCLUDED_PREFIXES = ("content/examples/",)
KNOWN_FAKE_PEOPLE = {
    "content/people/contributor-example.md",
    "content/people/jane-doe.md",
    "content/people/john-smith.md",
}
TYPE_NORMALIZATION = {
    "articles": "post",
    "companies": "company",
    "comments": "comment",
    "conversations": "conversation",
    "documents": "document",
    "meetings": "meeting",
    "newsletters": "newsletter",
    "pages": "page",
    "people": "person",
    "posts": "post",
    "products": "product",
    "projects": "project",
}
SHOPIFY_AUTHORITY_FIELDS = {
    "availability",
    "available",
    "available_for_sale",
    "checkout",
    "checkout_state",
    "compare_at_price",
    "compare-at-price",
    "currency",
    "inventory",
    "inventory_policy",
    "inventory_quantity",
    "order",
    "order_data",
    "price",
    "product_id",
    "shopify_id",
    "shopify_product_id",
    "shopify_updated_at",
    "sku",
    "variant_id",
    "variant_ids",
    "variants",
}
EDITORIAL_PRODUCT_FIELDS = {
    "assets",
    "body",
    "caption",
    "cta",
    "date",
    "description",
    "development_history",
    "faq",
    "faqs",
    "image",
    "images",
    "jsonld",
    "seo",
    "specifications",
    "story",
    "summary",
    "tags",
    "title",
    "type",
}
KNOWN_FIELD_ACTIONS = {
    "assets": "preserve",
    "author": "preserve",
    "canonical_url": "preserve",
    "caption": "preserve",
    "csv": "preserve",
    "cta": "preserve",
    "date": "rename",
    "esp_provider": "external authority",
    "featured": "preserve",
    "href": "preserve",
    "image": "preserve",
    "jsonld": "generated_legacy",
    "newsletter_id": "preserve",
    "publish_date": "normalize",
    "role": "preserve",
    "section": "preserve",
    "sent_date": "external authority",
    "seo": "normalize",
    "slug": "preserve",
    "social_links": "preserve",
    "status": "normalize",
    "summary": "preserve",
    "syndicate": "preserve",
    "tags": "preserve",
    "title": "preserve",
    "type": "normalize",
    "version": "preserve",
    "visibility": "normalize",
    "year": "preserve",
}
FIELD_TARGETS = {
    "date": "created",
    "publish_date": "status + scheduling metadata",
    "seo": "retain authored override / generate when absent",
    "jsonld": "generated output from canonical fields",
    "status": "status",
    "type": "type",
    "visibility": "visibility",
}
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[([^\]]+)\]\(([^)]+)\)")
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")
HTML_REF_RE = re.compile(r"""(?:src|href)=["']([^"']+)["']""")


def _json_default(value: Any) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)


def _normalize_path(path: Path) -> str:
    return path.as_posix()


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "untitled"


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, date):
        parsed = datetime.combine(value, time.min)
    elif value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _uuid7(timestamp: datetime) -> str:
    timestamp_ms = int(timestamp.timestamp() * 1000)
    timestamp_ms = timestamp_ms & ((1 << 48) - 1)
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = timestamp_ms << 80
    value |= 0x7 << 76
    value |= rand_a << 64
    value |= 0b10 << 62
    value |= rand_b
    return str(uuid.UUID(int=value))


def _uuid7_timestamp_ms(value: str) -> Optional[int]:
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        return None
    if parsed.version != 7:
        return None
    return parsed.int >> 80


def _split_frontmatter(text: str) -> Tuple[Dict[str, Any], str, Optional[str], bool]:
    if not text.startswith("---"):
        return {}, text, None, False

    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text, "Malformed frontmatter fence", True

    try:
        frontmatter = yaml.safe_load(parts[1]) or {}
        if not isinstance(frontmatter, dict):
            return {}, parts[2], "Frontmatter is not a mapping", True
        return frontmatter, parts[2], None, True
    except yaml.YAMLError as exc:
        return {}, parts[2], f"Malformed frontmatter: {exc}", True


def _extract_refs(body: str, frontmatter: Dict[str, Any]) -> Tuple[List[Dict[str, str]], List[Dict[str, str]]]:
    links = []
    images = []

    for match in MARKDOWN_LINK_RE.finditer(body):
        target = match.group(2).split()[0].strip()
        links.append({"kind": "markdown", "label": match.group(1), "target": target})

    for match in MARKDOWN_IMAGE_RE.finditer(body):
        target = match.group(2).split()[0].strip()
        images.append({"kind": "markdown", "alt": match.group(1), "target": target})

    for match in HTML_REF_RE.finditer(body):
        target = match.group(1).strip()
        bucket = images if target.lower().split("?")[0].endswith((".avif", ".gif", ".jpg", ".jpeg", ".png", ".svg", ".webp")) else links
        bucket.append({"kind": "html", "target": target})

    def collect_media(value: Any, key_path: str = ""):
        if isinstance(value, dict):
            for key, nested in value.items():
                collect_media(nested, f"{key_path}.{key}" if key_path else str(key))
        elif isinstance(value, list):
            for idx, nested in enumerate(value):
                collect_media(nested, f"{key_path}[{idx}]")
        elif isinstance(value, str):
            lowered = value.lower().split("?")[0]
            field_name = re.split(r"[.\[]", key_path.lower())[-1].rstrip("]")
            media_like_key = field_name in {"asset", "image", "src", "thumbnail"}
            if media_like_key or lowered.endswith((".avif", ".gif", ".jpg", ".jpeg", ".png", ".svg", ".webp")):
                images.append({"kind": "frontmatter", "field": key_path, "target": value})

    collect_media(frontmatter)
    return links, images


class MigrationAnalyzer:
    def __init__(
        self,
        config: Dict[str, Any],
        root_path: Path = Path("."),
        content_path: Optional[Path] = None,
        public_path: Optional[Path] = None,
        now: Optional[datetime] = None,
        id_map_path: Optional[Path] = None,
    ):
        self.config = config
        self.root_path = root_path
        build_config = config.get("build", {})
        self.content_path = content_path or Path(build_config.get("content", "./content"))
        self.public_path = public_path or Path(build_config.get("public", "./public"))
        if not self.content_path.is_absolute():
            self.content_path = self.root_path / self.content_path
        if not self.public_path.is_absolute():
            self.public_path = self.root_path / self.public_path
        self.now = now or datetime.now(timezone.utc)
        if self.now.tzinfo is None:
            self.now = self.now.replace(tzinfo=timezone.utc)
        self.site_url = config.get("site", {}).get("url", "").rstrip("/")
        self.redirects = self._load_redirects()
        self.id_map_path = id_map_path or (self.root_path / "reports" / "migration-manifest.json")
        if not self.id_map_path.is_absolute():
            self.id_map_path = self.root_path / self.id_map_path
        self.id_map = self._load_id_map()

    def analyze(self) -> Dict[str, Any]:
        records = [self._analyze_file(path) for path in self._content_files()]
        self._attach_conflicts(records)

        field_mapping = self._field_mapping(records)
        url_report = self._url_report(records)
        product_report = self._product_report(records)
        manifest = [self._manifest_item(record) for record in records]
        conflicts = self._conflicts(records)
        summary = self._summary(records, conflicts)

        return {
            "summary": summary,
            "documents": records,
            "url_preservation": url_report,
            "visibility_migration": self._visibility_report(records),
            "field_mapping": field_mapping,
            "product_analysis": product_report,
            "internal_link_analysis": self._internal_link_report(records),
            "conflicts": conflicts,
            "manifest": manifest,
            "notes": {
                "dry_run_only": True,
                "content_source": _normalize_path(self.content_path.relative_to(self.root_path)),
                "future_vault": "brain/vault",
                "future_public_vault": "brain/vault/public",
                "id_policy": "Canonical migration IDs are random UUIDv7 values allocated once and frozen in migration-manifest.json. Paths, titles, slugs, and mutable content are not permanent identity.",
                "jsonld_policy": "Legacy jsonld frontmatter is generated_legacy compatibility data. Future JSON-LD is derived deterministically from canonical fields and contracts.",
                "seo_policy": "Authored SEO metadata is preserved as a human override; absent SEO can be generated and is not required for every knowledge note.",
            },
        }

    def write_reports(self, output_dir: Path, analysis: Optional[Dict[str, Any]] = None) -> Dict[str, Path]:
        analysis = analysis or self.analyze()
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / "migration-analysis.json"
        md_path = output_dir / "migration-analysis.md"
        manifest_path = output_dir / "migration-manifest.json"

        json_path.write_text(json.dumps(analysis, indent=2, sort_keys=True, default=_json_default) + "\n")
        md_path.write_text(self.render_markdown(analysis))
        manifest_path.write_text(json.dumps(analysis["manifest"], indent=2, sort_keys=True, default=_json_default) + "\n")
        return {
            "analysis_json": json_path,
            "analysis_md": md_path,
            "manifest_json": manifest_path,
        }

    def _load_id_map(self) -> Dict[str, str]:
        if not self.id_map_path.exists():
            return {}
        try:
            data = json.loads(self.id_map_path.read_text())
        except json.JSONDecodeError:
            return {}

        if not isinstance(data, list):
            return {}

        id_map = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            allocation = item.get("id_allocation") or {}
            if allocation.get("policy") != "random_uuidv7_frozen":
                continue
            source = item.get("source")
            record_id = item.get("id")
            timestamp_ms = _uuid7_timestamp_ms(str(record_id))
            if source and timestamp_ms:
                id_map[str(source)] = str(record_id)
        return id_map

    def _allocated_id(self, source_path: str) -> str:
        if source_path in self.id_map:
            return self.id_map[source_path]
        record_id = _uuid7(self.now)
        self.id_map[source_path] = record_id
        return record_id

    def render_markdown(self, analysis: Dict[str, Any]) -> str:
        lines = ["# Migration Analysis", "", "Dry-run only. No content files were moved or rewritten.", ""]
        summary = analysis["summary"]
        lines.extend(
            [
                "## Summary",
                "",
                f"- Total files analyzed: {summary['total_files_analyzed']}",
                f"- Canonical migration candidates: {summary['canonical_migration_candidates']}",
                f"- Excluded from migration: {summary['excluded_from_migration']}",
                f"- Currently public: {summary['currently_public']}",
                f"- Drafts: {summary['drafts']}",
                f"- Scheduled: {summary['scheduled']}",
                f"- Ambiguous: {summary['ambiguous']}",
                f"- Migration-safe: {summary['migration_safe']}",
                f"- Review-required: {summary['review_required']}",
                f"- URL conflicts: {summary['url_conflicts']}",
                f"- Product records: {summary['product_records']}",
                f"- Invalid records: {summary['invalid_records']}",
                "",
                "## Per-Document Table",
                "",
                "| Path | Source Classification | UUID | Current URL | Proposed URL | Type | Visibility | Status | Target Vault Path | Migration Status | Warnings | Notices |",
                "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
            ]
        )
        for record in analysis["documents"]:
            warnings = "<br>".join(record["warnings"]) if record["warnings"] else ""
            notices = "<br>".join(record["notices"]) if record["notices"] else ""
            lines.append(
                "| {path} | {classification} | {uuid} | {current} | {proposed} | {type} | {visibility} | {status} | {target} | {migration} | {warnings} | {notices} |".format(
                    path=record["current_path"],
                    classification=record["source_classification"],
                    uuid=record["proposed_record"]["id"] or "",
                    current=record["current_public_url"] or "",
                    proposed=record["proposed_record"]["public_url"] or "",
                    type=record["proposed_record"]["type"],
                    visibility=record["proposed_record"]["visibility"],
                    status=record["proposed_record"]["status"],
                    target=record["proposed_record"]["canonical_vault_location"] or "",
                    migration=record["migration_status"],
                    warnings=warnings,
                    notices=notices,
                )
            )

        lines.extend(["", "## Source Classification", ""])
        lines.append("| Classification | Count | Paths |")
        lines.append("| --- | --- | --- |")
        classification_paths = defaultdict(list)
        for record in analysis["documents"]:
            classification_paths[record["source_classification"]].append(record["current_path"])
        for classification, paths in sorted(classification_paths.items()):
            lines.append(f"| {classification} | {len(paths)} | {'<br>'.join(sorted(paths))} |")

        lines.extend(["", "## URL Preservation", ""])
        lines.append("| Current URL | Proposed URL | Status | Path |")
        lines.append("| --- | --- | --- | --- |")
        for item in analysis["url_preservation"]:
            lines.append(f"| {item['current_url']} | {item['proposed_url'] or ''} | {item['status']} | {item['path']} |")

        lines.extend(["", "## Conflicts", ""])
        if analysis["conflicts"]:
            for conflict in analysis["conflicts"]:
                lines.append(f"- **{conflict['type']}**: {conflict['message']}")
        else:
            lines.append("No conflicts detected.")

        lines.extend(["", "## Product Analysis", ""])
        if analysis["product_analysis"]:
            for item in analysis["product_analysis"]:
                lines.append(f"### {item['path']}")
                lines.append("")
                lines.append(f"- Editorial knowledge fields: {', '.join(item['editorial_knowledge_fields']) or 'none'}")
                lines.append(f"- External authority fields: {', '.join(item['external_authority_fields']) or 'none'}")
                lines.append(f"- Generated legacy fields: {', '.join(item['generated_legacy_fields']) or 'none'}")
                lines.append(f"- Unknown product fields: {', '.join(item['unknown_fields']) or 'none'}")
                lines.append("")
        else:
            lines.append("No product-related Markdown records found.")

        return "\n".join(lines) + "\n"

    def _content_files(self) -> List[Path]:
        if not self.content_path.exists():
            return []
        return sorted(path for path in self.content_path.rglob("*.md") if path.is_file())

    def _load_redirects(self) -> List[Dict[str, Any]]:
        redirects_path = self.root_path / ".redirects.json"
        if not redirects_path.exists():
            return []
        try:
            data = json.loads(redirects_path.read_text())
            return data.get("redirects", []) if isinstance(data, dict) else []
        except json.JSONDecodeError:
            return []

    def _analyze_file(self, path: Path) -> Dict[str, Any]:
        rel_path = path.relative_to(self.root_path)
        rel_content_path = path.relative_to(self.content_path)
        rel_path_text = _normalize_path(rel_path)
        text = path.read_text()
        frontmatter, body, parse_error, has_frontmatter = _split_frontmatter(text)
        current_type = self._current_type(rel_content_path, frontmatter)
        slug = str(frontmatter.get("slug") or path.stem)
        current_url = self._current_url(rel_content_path, slug)
        source_classification = self._source_classification(rel_path_text, rel_content_path, frontmatter)
        publication = self._publication_state(path, rel_content_path, frontmatter, parse_error, has_frontmatter)
        proposed = self._proposed_record(path, rel_path, rel_content_path, frontmatter, body, current_type, slug, current_url, publication, source_classification)
        links, images = _extract_refs(body, frontmatter)
        warnings = list(publication["warnings"])
        notices = list(publication["notices"])

        if parse_error:
            warnings.append(parse_error)
        if not frontmatter.get("title"):
            warnings.append("Missing title")
        if publication["currently_public"] and current_type in {"post", "newsletter", "update"} and not (frontmatter.get("date") or frontmatter.get("publish_date")):
            warnings.append("Missing date")
        if publication["ambiguous"]:
            warnings.append("Publication state requires review")
        if source_classification in {"fixture/example", "documentation", "legacy_system_data"}:
            notices.append(f"Excluded from canonical migration: {source_classification}")

        missing_media = self._missing_media(images)
        for media in missing_media:
            warnings.append(f"Missing referenced media: {media}")

        broken_internal = self._broken_internal_links(links)
        for link in broken_internal:
            warnings.append(f"Broken internal link: {link}")

        record = {
            "current_path": _normalize_path(rel_path),
            "source_classification": source_classification,
            "excluded_from_migration": source_classification in {"fixture/example", "documentation", "legacy_system_data"},
            "current_content_type": current_type,
            "current_slug": slug,
            "current_public_url": current_url if publication["currently_public"] else None,
            "derived_public_url": current_url,
            "title": frontmatter.get("title"),
            "current_status": frontmatter.get("status"),
            "current_publish_date": frontmatter.get("publish_date"),
            "current_date": frontmatter.get("date"),
            "author": frontmatter.get("author"),
            "tags": frontmatter.get("tags", []),
            "seo_metadata": deepcopy(frontmatter.get("seo")),
            "jsonld_metadata": deepcopy(frontmatter.get("jsonld")),
            "image_media_references": images,
            "internal_links": [link for link in links if self._is_internal(link["target"])],
            "external_links": [link for link in links if not self._is_internal(link["target"])],
            "redirects_affecting_page": self._redirects_for(current_url),
            "shopify_product_relationship": self._shopify_relationship(frontmatter),
            "frontmatter_fields": sorted(frontmatter.keys()),
            "unknown_frontmatter_fields": sorted(k for k in frontmatter if k not in KNOWN_FIELD_ACTIONS and k not in SHOPIFY_AUTHORITY_FIELDS),
            "malformed_frontmatter": parse_error is not None,
            "currently_public": publication["currently_public"],
            "publication_state": publication["state"],
            "proposed_record": proposed,
            "warnings": sorted(set(warnings)),
            "notices": sorted(set(notices)),
            "migration_status": "review_required",
            "safe_to_migrate": False,
        }

        return record

    def _current_type(self, rel_content_path: Path, frontmatter: Dict[str, Any]) -> str:
        if frontmatter.get("type"):
            return TYPE_NORMALIZATION.get(str(frontmatter["type"]), str(frontmatter["type"]))
        top = rel_content_path.parts[0] if rel_content_path.parts else "content"
        if top in TYPE_NORMALIZATION:
            return TYPE_NORMALIZATION[top]
        return top[:-1] if top.endswith("s") else top

    def _source_classification(self, rel_path: str, rel_content_path: Path, frontmatter: Dict[str, Any]) -> str:
        if rel_path in EXCLUDED_PATHS:
            return "documentation"
        if rel_path.startswith(EXCLUDED_PREFIXES) or rel_path in KNOWN_FAKE_PEOPLE:
            return "fixture/example"

        top = rel_content_path.parts[0] if rel_content_path.parts else ""
        if top == "comments":
            return "legacy_system_data"
        if top in PUBLISHABLE_DIRS or top in {"people"}:
            return "canonical_content"
        return "review_required"

    def _current_url(self, rel_content_path: Path, slug: str) -> Optional[str]:
        top = rel_content_path.parts[0] if rel_content_path.parts else ""
        if top not in PUBLIC_URL_DIRS:
            return None
        return f"/{PUBLIC_URL_DIRS[top]}/{slug}/"

    def _publication_state(
        self,
        path: Path,
        rel_content_path: Path,
        frontmatter: Dict[str, Any],
        parse_error: Optional[str],
        has_frontmatter: bool,
    ) -> Dict[str, Any]:
        top = rel_content_path.parts[0] if rel_content_path.parts else ""
        warnings = []
        notices = []
        ambiguous = False

        if top not in PUBLISHABLE_DIRS:
            return {
                "state": "not_production_content",
                "currently_public": False,
                "proposed_visibility": "private",
                "proposed_status": str(frontmatter.get("status") or "draft"),
                "warnings": ["Not part of current production build inputs"],
                "notices": notices,
                "ambiguous": False,
            }

        if parse_error:
            return {
                "state": "published_ambiguous",
                "currently_public": True,
                "proposed_visibility": "public",
                "proposed_status": "published",
                "warnings": ["Malformed frontmatter is currently included by scheduler; review before migration"],
                "notices": notices,
                "ambiguous": True,
            }

        if not has_frontmatter:
            notices.append("legacy_publication_inferred: missing frontmatter is currently publishable by legacy scheduler")
            return {
                "state": "published_missing_frontmatter",
                "currently_public": True,
                "proposed_visibility": "public",
                "proposed_status": "published",
                "warnings": warnings,
                "notices": notices,
                "ambiguous": True,
            }

        status = frontmatter.get("status")
        if status is None:
            notices.append("legacy_publication_inferred: missing status maps to public/published because this file is a current production input")
            status = "published"

        status_text = str(status)
        if status_text == "draft":
            return {
                "state": "draft",
                "currently_public": False,
                "proposed_visibility": "private",
                "proposed_status": "draft",
                "warnings": warnings,
                "notices": notices,
                "ambiguous": ambiguous,
            }

        publish_date = _parse_datetime(frontmatter.get("publish_date"))
        if frontmatter.get("publish_date") and publish_date is None:
            warnings.append("Invalid publish_date is currently treated as publishable")
            ambiguous = True
        elif publish_date and publish_date > self.now:
            return {
                "state": "scheduled",
                "currently_public": False,
                "proposed_visibility": "private",
                "proposed_status": "scheduled",
                "warnings": warnings,
                "notices": notices,
                "ambiguous": ambiguous,
            }

        if status_text not in STATUSES_PUBLIC and status_text not in STATUSES_PRIVATE:
            warnings.append(f"Unknown status '{status_text}' is currently publishable unless draft")
            ambiguous = True

        if status_text in STATUSES_PRIVATE:
            return {
                "state": status_text,
                "currently_public": False,
                "proposed_visibility": "private",
                "proposed_status": status_text,
                "warnings": warnings,
                "notices": notices,
                "ambiguous": ambiguous,
            }

        return {
            "state": "published",
            "currently_public": True,
            "proposed_visibility": "public",
            "proposed_status": "published",
            "warnings": warnings,
            "notices": notices,
            "ambiguous": ambiguous,
        }

    def _proposed_record(
        self,
        path: Path,
        rel_path: Path,
        rel_content_path: Path,
        frontmatter: Dict[str, Any],
        body: str,
        current_type: str,
        slug: str,
        current_url: Optional[str],
        publication: Dict[str, Any],
        source_classification: str,
    ) -> Dict[str, Any]:
        source_path = _normalize_path(rel_path)
        excluded = source_classification in {"fixture/example", "documentation", "legacy_system_data"}
        proposed_id = None if excluded else self._allocated_id(source_path)
        created = frontmatter.get("date") or frontmatter.get("publish_date")
        updated = frontmatter.get("updated") or frontmatter.get("modified") or created
        future_parts = list(rel_content_path.parts)
        if excluded:
            target = None
        elif publication["proposed_visibility"] == "public":
            target = Path("brain") / "vault" / "public" / Path(*future_parts)
        else:
            target = Path("brain") / "vault" / Path(*future_parts)
        proposed_url = current_url if publication["proposed_visibility"] == "public" and not excluded else None
        fields_retained, fields_transformed, fields_deprecated, fields_unmapped = self._field_buckets(frontmatter)

        return {
            "id": proposed_id,
            "type": current_type,
            "visibility": publication["proposed_visibility"],
            "status": publication["proposed_status"],
            "created": created,
            "updated": updated,
            "canonical_vault_location": _normalize_path(target) if target else None,
            "existing_slug": slug,
            "existing_public_url": current_url,
            "public_url": proposed_url,
            "relationship_fields": self._relationship_fields(frontmatter),
            "source": {
                "path": _normalize_path(rel_path),
                "content_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            },
            "fields_retained_unchanged": fields_retained,
            "fields_transformed": fields_transformed,
            "fields_deprecated": fields_deprecated,
            "fields_cannot_map_deterministically": fields_unmapped,
        }

    def _field_buckets(self, frontmatter: Dict[str, Any]) -> Tuple[List[str], List[str], List[str], List[str]]:
        retained = []
        transformed = []
        deprecated = []
        unmapped = []
        for field in sorted(frontmatter.keys()):
            action = KNOWN_FIELD_ACTIONS.get(field)
            if action == "preserve":
                retained.append(field)
            elif action in {"rename", "normalize", "generated", "generated_legacy", "external authority"}:
                transformed.append(field)
            elif action == "deprecated":
                deprecated.append(field)
            elif field in SHOPIFY_AUTHORITY_FIELDS:
                transformed.append(field)
            else:
                unmapped.append(field)
        return retained, transformed, deprecated, unmapped

    def _relationship_fields(self, frontmatter: Dict[str, Any]) -> Dict[str, Any]:
        keys = ("author", "canonical_url", "cta", "newsletter_id", "related", "social_links", "tags")
        return {key: deepcopy(frontmatter[key]) for key in keys if key in frontmatter}

    def _shopify_relationship(self, frontmatter: Dict[str, Any]) -> Dict[str, Any]:
        matches = {}
        for key, value in frontmatter.items():
            key_lower = str(key).lower()
            if key_lower in SHOPIFY_AUTHORITY_FIELDS or "shopify" in key_lower or "variant" in key_lower:
                matches[key] = deepcopy(value)
        return {
            "is_product_related": self._is_product_related(frontmatter),
            "external_authority_fields": matches,
        }

    def _is_product_related(self, frontmatter: Dict[str, Any]) -> bool:
        if str(frontmatter.get("type", "")).lower() == "product":
            return True
        if any(key in frontmatter for key in SHOPIFY_AUTHORITY_FIELDS):
            return True
        tags = frontmatter.get("tags", [])
        return isinstance(tags, list) and any(str(tag).lower() in {"product", "products", "shopify"} for tag in tags)

    def _redirects_for(self, current_url: Optional[str]) -> List[Dict[str, Any]]:
        if not current_url:
            return []
        return [deepcopy(item) for item in self.redirects if item.get("from") == current_url or item.get("to") == current_url]

    def _is_internal(self, target: str) -> bool:
        if target.startswith("#") or target.startswith("/"):
            return True
        return not re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target)

    def _missing_media(self, images: List[Dict[str, str]]) -> List[str]:
        missing = []
        for image in images:
            target = image.get("target", "")
            if not target or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", target):
                continue
            clean = target.split("#", 1)[0].split("?", 1)[0]
            if clean.startswith("/assets/"):
                candidate = self.public_path / clean.removeprefix("/assets/")
            elif clean.startswith("/"):
                candidate = self.public_path / clean.removeprefix("/")
            else:
                candidate = self.content_path / clean
            if clean and not candidate.exists():
                missing.append(target)
        return sorted(set(missing))

    def _broken_internal_links(self, links: List[Dict[str, str]]) -> List[str]:
        known_urls = set()
        for path in self._content_files():
            rel = path.relative_to(self.content_path)
            top = rel.parts[0] if rel.parts else ""
            if top in PUBLIC_URL_DIRS:
                known_urls.add(f"/{PUBLIC_URL_DIRS[top]}/{path.stem}/")
        known_urls.update({"/", "/posts/", "/projects/", "/newsletters/"})

        broken = []
        for link in links:
            target = link["target"]
            if not target.startswith("/") or target.startswith("//"):
                continue
            clean = target.split("#", 1)[0].split("?", 1)[0]
            if "." in Path(clean).name:
                candidate = self.public_path / clean.removeprefix("/assets/").removeprefix("/")
                if not candidate.exists():
                    broken.append(target)
            elif not clean.endswith("/"):
                if f"{clean}/" not in known_urls and clean not in known_urls:
                    broken.append(target)
            elif clean not in known_urls:
                broken.append(target)
        return sorted(set(broken))

    def _attach_conflicts(self, records: List[Dict[str, Any]]) -> None:
        slug_paths = defaultdict(list)
        url_paths = defaultdict(list)
        id_paths = defaultdict(list)

        for record in records:
            if record["excluded_from_migration"]:
                continue
            slug_paths[record["current_slug"]].append(record["current_path"])
            url = record["current_public_url"]
            if url:
                url_paths[url].append(record["current_path"])
            record_id = record["proposed_record"]["id"]
            if record_id:
                id_paths[record_id].append(record["current_path"])

        duplicate_slugs = {slug: paths for slug, paths in slug_paths.items() if len(paths) > 1}
        duplicate_urls = {url: paths for url, paths in url_paths.items() if len(paths) > 1}
        duplicate_ids = {record_id: paths for record_id, paths in id_paths.items() if len(paths) > 1}

        for record in records:
            if record["excluded_from_migration"]:
                record["safe_to_migrate"] = False
                record["migration_status"] = "excluded_from_migration"
                continue

            review = bool(record["warnings"])
            if record["current_slug"] in duplicate_slugs:
                record["warnings"].append(f"Duplicate slug '{record['current_slug']}'")
                review = True
            url = record["current_public_url"]
            if url and url in duplicate_urls:
                record["warnings"].append(f"Multiple files resolve to URL '{url}'")
                review = True
            if record["proposed_record"]["id"] in duplicate_ids:
                record["warnings"].append(f"Duplicate proposed ID '{record['proposed_record']['id']}'")
                review = True
            record["warnings"] = sorted(set(record["warnings"]))
            record["safe_to_migrate"] = not review
            record["migration_status"] = "migration_safe" if record["safe_to_migrate"] else "review_required"

    def _summary(self, records: List[Dict[str, Any]], conflicts: List[Dict[str, Any]]) -> Dict[str, int]:
        canonical = [item for item in records if not item["excluded_from_migration"]]
        return {
            "total_files_analyzed": len(records),
            "canonical_migration_candidates": len(canonical),
            "excluded_from_migration": sum(1 for item in records if item["excluded_from_migration"]),
            "currently_public": sum(1 for item in canonical if item["currently_public"]),
            "current_public_records": sum(1 for item in canonical if item["currently_public"]),
            "drafts": sum(1 for item in canonical if item["publication_state"] == "draft"),
            "scheduled": sum(1 for item in canonical if item["publication_state"] == "scheduled"),
            "ambiguous": sum(1 for item in canonical if "ambiguous" in item["publication_state"] or "requires review" in " ".join(item["warnings"])),
            "migration_safe": sum(1 for item in canonical if item["safe_to_migrate"]),
            "review_required": sum(1 for item in canonical if not item["safe_to_migrate"]),
            "url_conflicts": sum(1 for item in conflicts if item["type"] in {"duplicate_url", "url_status"}),
            "product_records": sum(1 for item in canonical if item["shopify_product_relationship"]["is_product_related"]),
            "invalid_records": sum(1 for item in canonical if item["malformed_frontmatter"]),
        }

    def _url_report(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        report = []
        for record in records:
            if not record["currently_public"]:
                continue
            current = record["current_public_url"]
            proposed = record["proposed_record"]["public_url"]
            if not current or not proposed:
                status = "unknown"
            elif current == proposed:
                status = "unchanged"
            else:
                status = "redirect_required"
            if any("Multiple files resolve" in warning for warning in record["warnings"]):
                status = "conflict"
            report.append({"current_url": current, "proposed_url": proposed, "status": status, "path": record["current_path"]})
        return sorted(report, key=lambda item: (item["current_url"] or "", item["path"]))

    def _visibility_report(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        buckets = {
            "currently_published": [],
            "currently_draft": [],
            "scheduled": [],
            "missing_status": [],
            "ambiguous": [],
            "excluded_from_migration": [],
        }
        for record in records:
            item = {
                "path": record["current_path"],
                "source_classification": record["source_classification"],
                "proposed_visibility": record["proposed_record"]["visibility"],
                "proposed_status": record["proposed_record"]["status"],
                "warnings": record["warnings"],
                "notices": record["notices"],
            }
            if record["excluded_from_migration"]:
                buckets["excluded_from_migration"].append(item)
                continue
            if record["currently_public"]:
                buckets["currently_published"].append(item)
            if record["publication_state"] == "draft":
                buckets["currently_draft"].append(item)
            if record["publication_state"] == "scheduled":
                buckets["scheduled"].append(item)
            if record["current_status"] is None:
                buckets["missing_status"].append(item)
            if record["warnings"]:
                buckets["ambiguous"].append(item)
        return buckets

    def _field_mapping(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        field_paths = defaultdict(list)
        for record in records:
            for field in record["frontmatter_fields"]:
                field_paths[field].append(record["current_path"])

        mapping = []
        for field in sorted(field_paths):
            if field in SHOPIFY_AUTHORITY_FIELDS:
                classification = "external authority"
            else:
                classification = KNOWN_FIELD_ACTIONS.get(field, "unknown")
            mapping.append(
                {
                    "current": field,
                    "future": FIELD_TARGETS.get(field, "retain unchanged" if classification == "preserve" else "requires review"),
                    "classification": classification,
                    "paths": sorted(field_paths[field]),
                }
            )
        return mapping

    def _product_report(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        items = []
        for record in records:
            if not record["shopify_product_relationship"]["is_product_related"]:
                continue
            editorial = []
            external = []
            generated_legacy = []
            unknown = []
            for field in record["frontmatter_fields"]:
                field_lower = field.lower()
                if field_lower in SHOPIFY_AUTHORITY_FIELDS or "shopify" in field_lower or "variant" in field_lower:
                    external.append(field)
                elif KNOWN_FIELD_ACTIONS.get(field) == "generated_legacy":
                    generated_legacy.append(field)
                elif field_lower in EDITORIAL_PRODUCT_FIELDS or field_lower in KNOWN_FIELD_ACTIONS:
                    editorial.append(field)
                else:
                    unknown.append(field)
            items.append(
                {
                    "path": record["current_path"],
                    "editorial_knowledge_fields": sorted(editorial),
                    "external_authority_fields": sorted(external),
                    "generated_legacy_fields": sorted(generated_legacy),
                    "unknown_fields": sorted(unknown),
                }
            )
        return items

    def _internal_link_report(self, records: List[Dict[str, Any]]) -> Dict[str, Any]:
        affected = []
        for record in records:
            path = Path(record["current_path"])
            if record["internal_links"] or record["image_media_references"]:
                target = record["proposed_record"]["canonical_vault_location"] or ""
                affected.append(
                    {
                        "path": record["current_path"],
                        "markdown_links": record["internal_links"],
                        "image_references": record["image_media_references"],
                        "requires_compatibility_handling": str(path).startswith("content/") and target.startswith("brain/vault/"),
                    }
                )
        return {
            "paths_requiring_compatibility_handling": affected,
            "template_assumptions": ["Existing renderer reads content/ and derives URLs from parent directory + filename."],
            "search_index_references": ["Search and output generators should keep using public URLs, not vault paths."],
            "api_output": ["Future API output must expose preserved public_url values."],
            "agentmap_output": ["AgentMap content type references remain config-driven during this epic."],
        }

    def _conflicts(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        conflicts = []
        slug_counter = defaultdict(list)
        url_counter = defaultdict(list)
        id_counter = defaultdict(list)

        for record in records:
            if record["excluded_from_migration"]:
                continue
            slug_counter[record["current_slug"]].append(record["current_path"])
            if record["current_public_url"]:
                url_counter[record["current_public_url"]].append(record["current_path"])
            record_id = record["proposed_record"]["id"]
            if record_id:
                id_counter[record_id].append(record["current_path"])

            if not record["excluded_from_migration"]:
                for warning in record["warnings"]:
                    conflicts.append({"type": "record_warning", "path": record["current_path"], "message": warning})

        for slug, paths in slug_counter.items():
            if len(paths) > 1:
                conflicts.append({"type": "duplicate_slug", "paths": sorted(paths), "message": f"Slug '{slug}' appears in multiple files."})
        for url, paths in url_counter.items():
            if len(paths) > 1:
                conflicts.append({"type": "duplicate_url", "paths": sorted(paths), "message": f"URL '{url}' resolves from multiple files."})
        for record_id, paths in id_counter.items():
            if len(paths) > 1:
                conflicts.append({"type": "duplicate_id", "paths": sorted(paths), "message": f"Proposed ID '{record_id}' appears more than once."})

        return sorted(conflicts, key=lambda item: (item["type"], item.get("path", ""), item.get("message", "")))

    def _manifest_item(self, record: Dict[str, Any]) -> Dict[str, Any]:
        proposed = record["proposed_record"]
        return {
            "source": record["current_path"],
            "source_classification": record["source_classification"],
            "destination": proposed["canonical_vault_location"],
            "id": proposed["id"],
            "id_allocation": {
                "policy": "random_uuidv7_frozen" if proposed["id"] else None,
                "stored_in": "reports/migration-manifest.json" if proposed["id"] else None,
            },
            "current_url": record["current_public_url"],
            "proposed_url": proposed["public_url"],
            "frontmatter_changes": {
                "retain": proposed["fields_retained_unchanged"],
                "transform": proposed["fields_transformed"],
                "deprecated": proposed["fields_deprecated"],
                "cannot_map_deterministically": proposed["fields_cannot_map_deterministically"],
            },
            "warnings": record["warnings"],
            "notices": record["notices"],
            "migration_status": record["migration_status"],
            "excluded_from_migration": record["excluded_from_migration"],
            "safe_to_migrate": record["safe_to_migrate"],
        }
