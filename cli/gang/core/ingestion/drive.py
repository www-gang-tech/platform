"""Deterministic Google Drive ingestion into the private knowledge vault."""

from __future__ import annotations

import html
import io
import json
import random
import re
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol

import yaml

from core.entities.documents import preserved_entity_frontmatter
from core.paths import GangPaths

from .gmail import _error_status, _error_text, _retry_after_seconds
from .ids import content_sha256, slugify, stable_source_id, uuid7
from .raw_store import LocalRawStore, RawRecord, RawStore
from .registry import IngestionRegistry


DRIVE_READONLY_SCOPE = "https://www.googleapis.com/auth/drive.readonly"
GOOGLE_DOC_MIME = "application/vnd.google-apps.document"
GOOGLE_SHEETS_MIME = "application/vnd.google-apps.spreadsheet"
GOOGLE_SLIDES_MIME = "application/vnd.google-apps.presentation"
GOOGLE_FORMS_MIME = "application/vnd.google-apps.form"
GOOGLE_DRAWINGS_MIME = "application/vnd.google-apps.drawing"
PDF_MIME = "application/pdf"
TEXT_MIME_TYPES = {"text/plain", "text/markdown", "text/x-markdown"}
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
SUPPORTED_OFFICE_MIME_TYPES = {DOCX_MIME}
RETRYABLE_403_MARKERS = (
    "quota",
    "rate limit",
    "ratelimit",
    "userratelimitexceeded",
    "quotaexceeded",
    "limit exceeded",
    "rate exceeded",
)


class DriveIngestionError(Exception):
    """Raised when Drive ingestion cannot proceed safely."""


@dataclass(frozen=True)
class DriveRetryPolicy:
    max_attempts: int = 5
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    jitter_seconds: float = 0.5
    min_request_interval_seconds: float = 0.25


@dataclass(frozen=True)
class DriveFile:
    file_id: str
    name: str
    mime_type: str
    web_view_link: str = ""
    created_time: str = ""
    modified_time: str = ""
    owners: List[str] = field(default_factory=list)
    parents: List[str] = field(default_factory=list)
    md5_checksum: str = ""
    size: Optional[int] = None
    version: str = ""
    head_revision_id: str = ""
    trashed: bool = False
    deleted: bool = False


@dataclass(frozen=True)
class DrivePayload:
    payload: bytes
    filename: str
    export_mime_type: Optional[str] = None


@dataclass(frozen=True)
class DriveChangeBatch:
    files: List[DriveFile]
    new_start_page_token: str


@dataclass(frozen=True)
class DriveFileResult:
    drive_file_id: str
    source_id: str
    document_id: str
    document_path: Optional[Path]
    status: str
    supported: bool
    raw_record: Optional[RawRecord] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class DriveSyncResult:
    files_discovered: int
    supported: int
    unsupported: int
    created: int
    updated: int
    unchanged: int
    failed: int
    checkpoint: Dict[str, Any]
    checkpoint_advanced: bool
    results: List[DriveFileResult]


class DriveProvider(Protocol):
    """Narrow boundary around Google Drive API behavior."""

    def discover_files(self, *, since: Optional[str] = None, folder_id: Optional[str] = None) -> Iterable[DriveFile]:
        """Return a bounded initial Drive file set."""

    def discover_changes(self, page_token: str) -> DriveChangeBatch:
        """Return Drive changes since the stored page token."""

    def fetch_file(self, drive_file: DriveFile) -> DrivePayload:
        """Fetch source evidence for a Drive file."""

    def current_start_page_token(self) -> str:
        """Return the current Drive changes checkpoint token."""


class GoogleDriveProvider:
    """Google API implementation kept outside canonical knowledge logic."""

    def __init__(
        self,
        *,
        token_path: Path | str | None = None,
        credentials_path: Path | str | None = None,
        private_home: Path | str | None = None,
        scopes: Optional[List[str]] = None,
        retry_policy: Optional[DriveRetryPolicy] = None,
        sleep_fn=time.sleep,
        monotonic_fn=time.monotonic,
        random_fn=random.random,
    ):
        paths = GangPaths.from_env(gang_home=private_home)
        self.token_path = Path(token_path) if token_path is not None else paths.drive_token_path
        self.credentials_path = Path(credentials_path) if credentials_path is not None else paths.drive_credentials_path
        self.scopes = scopes or [DRIVE_READONLY_SCOPE]
        self.retry_policy = retry_policy or DriveRetryPolicy()
        self.sleep_fn = sleep_fn
        self.monotonic_fn = monotonic_fn
        self.random_fn = random_fn
        self.retry_count = 0
        self.rate_limit_sleep_count = 0
        self._service = None
        self._last_request_started_at: Optional[float] = None

    def authenticate(self) -> Path:
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError as exc:
            raise DriveIngestionError(
                "Drive auth requires google-auth-oauthlib. Install requirements.txt first."
            ) from exc

        if not self.credentials_path.exists():
            raise DriveIngestionError(f"OAuth client credentials not found: {self.credentials_path}")

        flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), self.scopes)
        credentials = flow.run_local_server(port=0)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(credentials.to_json() + "\n", encoding="utf-8")
        return self.token_path

    def discover_files(self, *, since: Optional[str] = None, folder_id: Optional[str] = None) -> Iterable[DriveFile]:
        service = self._drive_service()
        query_parts = ["trashed = false"]
        if since:
            query_parts.append(f"modifiedTime >= '{_rfc3339_for_since(since)}'")
        if folder_id:
            query_parts.append(f"'{_escape_drive_query(folder_id)}' in parents")
        query = " and ".join(query_parts)
        page_token = None
        while True:
            response = self._execute(
                service.files().list(
                    q=query,
                    spaces="drive",
                    pageToken=page_token,
                    fields=(
                        "nextPageToken,files(id,name,mimeType,webViewLink,createdTime,modifiedTime,"
                        "owners(displayName,emailAddress),parents,md5Checksum,size,trashed,version,headRevisionId)"
                    ),
                )
            )
            for item in response.get("files", []):
                yield _drive_file_from_api(item)
            page_token = response.get("nextPageToken")
            if not page_token:
                break

    def discover_changes(self, page_token: str) -> DriveChangeBatch:
        service = self._drive_service()
        files: List[DriveFile] = []
        token = page_token
        new_start = page_token
        while True:
            response = self._execute(
                service.changes().list(
                    pageToken=token,
                    spaces="drive",
                    includeRemoved=True,
                    fields=(
                        "nextPageToken,newStartPageToken,changes(removed,fileId,file(id,name,mimeType,webViewLink,"
                        "createdTime,modifiedTime,owners(displayName,emailAddress),parents,md5Checksum,size,trashed,"
                        "version,headRevisionId))"
                    ),
                )
            )
            for change in response.get("changes", []):
                item = change.get("file") or {"id": change.get("fileId"), "name": "", "mimeType": ""}
                drive_file = _drive_file_from_api(item)
                if change.get("removed"):
                    drive_file = DriveFile(
                        file_id=drive_file.file_id,
                        name=drive_file.name,
                        mime_type=drive_file.mime_type,
                        web_view_link=drive_file.web_view_link,
                        created_time=drive_file.created_time,
                        modified_time=drive_file.modified_time,
                        owners=drive_file.owners,
                        parents=drive_file.parents,
                        md5_checksum=drive_file.md5_checksum,
                        size=drive_file.size,
                        version=drive_file.version,
                        head_revision_id=drive_file.head_revision_id,
                        trashed=True,
                        deleted=True,
                    )
                files.append(drive_file)
            token = response.get("nextPageToken")
            if token:
                continue
            new_start = response.get("newStartPageToken") or page_token
            break
        return DriveChangeBatch(files=files, new_start_page_token=new_start)

    def fetch_file(self, drive_file: DriveFile) -> DrivePayload:
        if drive_file.deleted:
            payload = json.dumps(_drive_metadata(drive_file), indent=2, sort_keys=True).encode("utf-8")
            return DrivePayload(payload=payload, filename=f"{drive_file.file_id}.metadata.json")

        service = self._drive_service()
        if drive_file.mime_type == GOOGLE_DOC_MIME:
            export_mime = "text/markdown"
            return DrivePayload(
                payload=self._download_bytes(service.files().export_media(fileId=drive_file.file_id, mimeType=export_mime)),
                filename=f"{slugify(drive_file.name, 'google-doc')}.md",
                export_mime_type=export_mime,
            )

        return DrivePayload(
            payload=self._download_bytes(service.files().get_media(fileId=drive_file.file_id)),
            filename=drive_file.name or f"{drive_file.file_id}.bin",
        )

    def current_start_page_token(self) -> str:
        response = self._execute(self._drive_service().changes().getStartPageToken())
        return str(response.get("startPageToken") or "")

    def _download_bytes(self, request) -> bytes:
        try:
            from googleapiclient.http import MediaIoBaseDownload
        except ImportError as exc:
            raise DriveIngestionError(
                "Drive sync requires google-api-python-client. Install requirements.txt first."
            ) from exc

        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            last_error: Optional[Exception] = None
            for attempt in range(max(1, self.retry_policy.max_attempts)):
                self._pace_request()
                try:
                    _, done = downloader.next_chunk()
                    last_error = None
                    break
                except Exception as exc:
                    last_error = exc
                    if attempt >= self.retry_policy.max_attempts - 1 or not _is_retryable_google_error(exc):
                        raise
                    self.retry_count += 1
                    self.sleep_fn(self._retry_delay(exc, attempt))
            if last_error:
                raise last_error
        return buffer.getvalue()

    def _execute(self, request) -> Dict[str, Any]:
        last_error: Optional[Exception] = None
        for attempt in range(max(1, self.retry_policy.max_attempts)):
            self._pace_request()
            try:
                return request.execute()
            except Exception as exc:
                last_error = exc
                if attempt >= self.retry_policy.max_attempts - 1 or not _is_retryable_google_error(exc):
                    raise
                delay = self._retry_delay(exc, attempt)
                self.retry_count += 1
                self.sleep_fn(delay)
        if last_error:
            raise last_error
        raise DriveIngestionError("Drive request failed without an exception")

    def _pace_request(self) -> None:
        interval = max(0.0, self.retry_policy.min_request_interval_seconds)
        now = self.monotonic_fn()
        if self._last_request_started_at is not None and interval > 0:
            elapsed = now - self._last_request_started_at
            if elapsed < interval:
                self.rate_limit_sleep_count += 1
                self.sleep_fn(interval - elapsed)
                now = self.monotonic_fn()
        self._last_request_started_at = now

    def _retry_delay(self, exc: Exception, attempt: int) -> float:
        retry_after = _retry_after_seconds(exc)
        if retry_after is not None:
            return min(retry_after, self.retry_policy.max_delay_seconds)
        jitter = max(0.0, self.retry_policy.jitter_seconds) * self.random_fn()
        exponential = self.retry_policy.base_delay_seconds * (2**attempt)
        return min(exponential + jitter, self.retry_policy.max_delay_seconds)

    def _drive_service(self):
        if self._service is not None:
            return self._service
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise DriveIngestionError(
                "Drive sync requires google-api-python-client and google-auth. Install requirements.txt first."
            ) from exc

        if not self.token_path.exists():
            raise DriveIngestionError("Drive is not authenticated. Run: gang ingest drive auth")

        credentials = Credentials.from_authorized_user_file(str(self.token_path), self.scopes)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            self.token_path.write_text(credentials.to_json() + "\n", encoding="utf-8")
        if not credentials.valid:
            raise DriveIngestionError("Drive token is invalid. Run: gang ingest drive auth")

        self._service = build("drive", "v3", credentials=credentials)
        return self._service


class DriveSyncService:
    """Synchronize Drive files into existing raw, registry, private vault, and FTS primitives."""

    def __init__(
        self,
        provider: DriveProvider,
        *,
        root_path: Path | str = Path("."),
        raw_store: Optional[RawStore] = None,
        registry: Optional[IngestionRegistry] = None,
        documents_path: Path | str | None = None,
        checkpoint_path: Path | str | None = None,
        private_home: Path | str | None = None,
    ):
        self.provider = provider
        self.root_path = Path(root_path).resolve()
        self.paths = GangPaths.from_env(repo_root=self.root_path, gang_home=private_home)
        self.raw_store = raw_store or LocalRawStore(self.paths.raw_path)
        self.documents_path = self._resolve(documents_path) if documents_path is not None else self.paths.documents_path
        self.checkpoint_path = self._resolve(checkpoint_path) if checkpoint_path is not None else self.paths.drive_checkpoint_path
        self.registry = registry or IngestionRegistry(self.paths.registry_path, root_path=self.paths.home)

    def sync(self, *, since: Optional[str] = None, folder_id: Optional[str] = None) -> DriveSyncResult:
        checkpoint = self.load_checkpoint()
        last_token = checkpoint.get("start_page_token")
        bounded_initial = since is not None or folder_id is not None
        if last_token and not bounded_initial:
            change_batch = self.provider.discover_changes(str(last_token))
            files = change_batch.files
            next_token = change_batch.new_start_page_token
            mode = "incremental"
        elif bounded_initial:
            files = list(self.provider.discover_files(since=since, folder_id=folder_id))
            next_token = self.provider.current_start_page_token()
            mode = "bounded"
        else:
            raise DriveIngestionError("First Drive sync must be bounded. Example: gang ingest drive --since 30d")

        results: List[DriveFileResult] = []
        for drive_file in files:
            try:
                results.append(self._ingest_file(drive_file))
            except Exception as exc:
                results.append(
                    DriveFileResult(
                        drive_file_id=drive_file.file_id,
                        source_id=_drive_file_source_id(drive_file.file_id),
                        document_id="",
                        document_path=None,
                        status="failed",
                        supported=_is_supported(drive_file),
                        error=_safe_error(exc),
                    )
                )

        failed = sum(1 for result in results if result.status == "failed")
        checkpoint_advanced = False
        if failed == 0:
            checkpoint = {
                "version": 1,
                "mode": mode,
                "last_successful_sync_at": datetime.now(timezone.utc).isoformat(),
                "start_page_token": next_token,
                "last_since": since,
                "last_folder_id": folder_id,
                "file_count": len(files),
            }
            self._save_checkpoint(checkpoint)
            checkpoint_advanced = True

        return DriveSyncResult(
            files_discovered=len(files),
            supported=sum(1 for result in results if result.supported),
            unsupported=sum(1 for result in results if not result.supported),
            created=sum(1 for result in results if result.status == "created"),
            updated=sum(1 for result in results if result.status == "updated"),
            unchanged=sum(1 for result in results if result.status == "unchanged"),
            failed=failed,
            checkpoint=checkpoint,
            checkpoint_advanced=checkpoint_advanced,
            results=results,
        )

    def status(self) -> Dict[str, Any]:
        sources = {
            source_id: record
            for source_id, record in self.registry.all_sources().items()
            if record.get("adapter") == "DriveSyncService" or record.get("source_type") == "drive-file"
        }
        return {
            "checkpoint_path": self.checkpoint_path,
            "checkpoint": self.load_checkpoint(),
            "files": len(sources),
            "documents": len({record.get("document_id") for record in sources.values() if record.get("document_id")}),
        }

    def load_checkpoint(self) -> Dict[str, Any]:
        if not self.checkpoint_path.exists():
            return {}
        return json.loads(self.checkpoint_path.read_text(encoding="utf-8"))

    def _ingest_file(self, drive_file: DriveFile) -> DriveFileResult:
        source_id = _drive_file_source_id(drive_file.file_id)
        previous = self.registry.get(source_id)
        supported = _is_supported(drive_file)
        now = datetime.now(timezone.utc).isoformat()
        created_at = previous.get("created_at", now) if previous else now

        if not supported:
            raw_record = self._store_unsupported_evidence(drive_file)
            self._upsert_registry(
                drive_file=drive_file,
                raw_record=raw_record,
                payload_hash=raw_record.content_hash,
                source_state_hash=_source_state_hash(drive_file, raw_record.content_hash, {"unsupported": True}),
                document_id=previous.get("document_id", "") if previous else "",
                document_path=previous.get("document_path", "") if previous else "",
                created_at=created_at,
                updated_at=now,
                supported=False,
                append_raw_version=not previous or (previous.get("payload_hash") or previous.get("content_hash")) != raw_record.content_hash,
            )
            return DriveFileResult(
                drive_file_id=drive_file.file_id,
                source_id=source_id,
                document_id=previous.get("document_id", "") if previous else "",
                document_path=self.registry.resolve_path(previous["document_path"]) if previous and previous.get("document_path") else None,
                status="unsupported",
                supported=False,
                raw_record=raw_record,
            )

        fetched = self.provider.fetch_file(drive_file)
        _validate_fetched_payload(drive_file, fetched)
        raw_record = self.raw_store.put(
            "drive-file",
            source_id,
            fetched.payload,
            filename=fetched.filename,
            metadata={**_drive_metadata(drive_file), "export_mime_type": fetched.export_mime_type},
        )
        normalized = _normalize_drive_file(drive_file, fetched.payload, fetched.filename, fetched.export_mime_type)
        payload_hash = raw_record.content_hash
        source_state_hash = _source_state_hash(drive_file, payload_hash, normalized["metadata"])
        manifest = {
            "source_type": "drive-file",
            "source_id": source_id,
            "drive_file_id": drive_file.file_id,
            "metadata": _drive_metadata(drive_file),
            "raw_ref": raw_record.raw_ref,
            "payload_hash": payload_hash,
            "source_state_hash": source_state_hash,
            "raw_version": raw_record.version,
            "normalization": normalized["metadata"],
        }
        previous_payload_hash = previous.get("payload_hash") or previous.get("content_hash") if previous else ""
        previous_source_state_hash = previous.get("source_state_hash") or previous.get("content_hash") if previous else ""

        if previous and previous_payload_hash == payload_hash and previous_source_state_hash == source_state_hash:
            return DriveFileResult(
                drive_file_id=drive_file.file_id,
                source_id=source_id,
                document_id=previous["document_id"],
                document_path=self.registry.resolve_path(previous["document_path"]),
                status="unchanged",
                supported=True,
                raw_record=raw_record,
            )

        document_id = previous["document_id"] if previous else uuid7()
        document_path = self._write_document(
            document_id=document_id,
            drive_file=drive_file,
            source_id=source_id,
            raw_record=raw_record,
            manifest=manifest,
            normalized=normalized,
            created_at=created_at,
            updated_at=now,
            document_path=self.registry.resolve_path(previous["document_path"]) if previous and previous.get("document_path") else None,
        )
        self._upsert_registry(
            drive_file=drive_file,
            raw_record=raw_record,
            payload_hash=payload_hash,
            source_state_hash=source_state_hash,
            document_id=document_id,
            document_path=self.registry.relative_path(document_path),
            created_at=created_at,
            updated_at=now,
            supported=True,
            append_raw_version=not previous or previous_payload_hash != payload_hash,
        )
        return DriveFileResult(
            drive_file_id=drive_file.file_id,
            source_id=source_id,
            document_id=document_id,
            document_path=document_path,
            status="updated" if previous and previous_payload_hash != payload_hash else ("unchanged" if previous else "created"),
            supported=True,
            raw_record=raw_record,
        )

    def _store_unsupported_evidence(self, drive_file: DriveFile) -> RawRecord:
        source_id = _drive_file_source_id(drive_file.file_id)
        payload = json.dumps(_drive_metadata(drive_file), indent=2, sort_keys=True).encode("utf-8")
        if _is_downloadable(drive_file):
            try:
                fetched = self.provider.fetch_file(drive_file)
                payload = fetched.payload
                filename = fetched.filename
            except Exception:
                filename = f"{drive_file.file_id}.metadata.json"
        else:
            filename = f"{drive_file.file_id}.metadata.json"
        return self.raw_store.put(
            "drive-file",
            source_id,
            payload,
            filename=filename,
            metadata={**_drive_metadata(drive_file), "unsupported": True},
        )

    def _write_document(
        self,
        *,
        document_id: str,
        drive_file: DriveFile,
        source_id: str,
        raw_record: RawRecord,
        manifest: Dict[str, Any],
        normalized: Dict[str, Any],
        created_at: str,
        updated_at: str,
        document_path: Optional[Path],
    ) -> Path:
        self.documents_path.mkdir(parents=True, exist_ok=True)
        if document_path is None:
            document_path = self.documents_path / f"{document_id}-{slugify(normalized['title'], 'drive-document')}.md"
        frontmatter = {
            "id": document_id,
            "type": "document",
            "source_type": "drive-file",
            "title": normalized["title"],
            "created": _date_or_default(drive_file.created_time, created_at),
            "updated": _date_or_default(drive_file.modified_time, updated_at),
            "created_at": created_at,
            "updated_at": updated_at,
            "visibility": "private",
            "status": "active",
            "content_trust": "untrusted",
            "people": [],
            "companies": [],
            "projects": [],
            "tags": [],
            "sources": [{"source_id": source_id, "type": "drive-file", "raw_ref": raw_record.raw_ref}],
            "source_id": source_id,
            "source_ids": [source_id],
            "related": [],
            "drive": _drive_metadata(drive_file),
            "content_hash": raw_record.content_hash,
            "payload_hash": raw_record.content_hash,
            "source_state_hash": manifest.get("source_state_hash"),
            "version": raw_record.version,
            "raw_version": raw_record.version,
            "raw_ref": raw_record.raw_ref,
            "provenance": {
                "source_id": source_id,
                "source_type": "drive-file",
                "drive_file_id": drive_file.file_id,
                "source_version": _source_version(drive_file, raw_record),
                "raw_ref": raw_record.raw_ref,
                "payload_hash": raw_record.content_hash,
                "raw_version": raw_record.version,
            },
            "ingestion_envelope": manifest,
        }
        frontmatter.update(preserved_entity_frontmatter(document_path))
        frontmatter_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
        document_path.parent.mkdir(parents=True, exist_ok=True)
        document_path.write_text(f"---\n{frontmatter_text}---\n\n{normalized['body']}", encoding="utf-8")
        return document_path

    def _upsert_registry(
        self,
        *,
        drive_file: DriveFile,
        raw_record: RawRecord,
        payload_hash: str,
        source_state_hash: str,
        document_id: str,
        document_path: str,
        created_at: str,
        updated_at: str,
        supported: bool,
        append_raw_version: bool = True,
    ) -> None:
        source_id = _drive_file_source_id(drive_file.file_id)
        self.registry.upsert(
            source_id,
            {
                "source_id": source_id,
                "adapter": "DriveSyncService",
                "source_type": "drive-file",
                "source_name": drive_file.name,
                "content_hash": payload_hash,
                "payload_hash": payload_hash,
                "source_state_hash": source_state_hash,
                "raw_version": raw_record.version,
                "version": raw_record.version,
                "document_id": document_id,
                "document_path": document_path,
                "raw_ref": raw_record.raw_ref,
                "ingested_at": updated_at,
                "created_at": created_at,
                "updated_at": updated_at,
                "drive_file_id": drive_file.file_id,
                "drive_mime_type": drive_file.mime_type,
                "drive_modified_time": drive_file.modified_time,
                "drive_trashed": drive_file.trashed,
                "drive_deleted": drive_file.deleted,
                "supported": supported,
            },
            append_version=append_raw_version,
            version_record={
                "raw_version": raw_record.version,
                "version": raw_record.version,
                "raw_ref": raw_record.raw_ref,
                "payload_hash": payload_hash,
                "content_hash": payload_hash,
                "ingested_at": updated_at,
            },
        )

    def _save_checkpoint(self, checkpoint: Dict[str, Any]) -> None:
        self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.checkpoint_path.with_suffix(".tmp")
        temp_path.write_text(json.dumps(checkpoint, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        temp_path.replace(self.checkpoint_path)

    def _resolve(self, path: Path | str) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate
        return self.root_path / candidate


def _drive_file_source_id(file_id: str) -> str:
    return stable_source_id("drive-file", "drive", file_id)


def _is_supported(drive_file: DriveFile) -> bool:
    if drive_file.deleted or drive_file.trashed:
        return False
    if drive_file.mime_type == GOOGLE_DOC_MIME:
        return True
    if drive_file.mime_type == PDF_MIME:
        return True
    if drive_file.mime_type in TEXT_MIME_TYPES:
        return True
    if Path(drive_file.name).suffix.lower() in {".md", ".txt"}:
        return True
    if drive_file.mime_type in SUPPORTED_OFFICE_MIME_TYPES:
        return True
    return False


def _is_downloadable(drive_file: DriveFile) -> bool:
    return bool(drive_file.mime_type and not drive_file.mime_type.startswith("application/vnd.google-apps."))


def _validate_fetched_payload(drive_file: DriveFile, fetched: DrivePayload) -> None:
    if drive_file.mime_type != GOOGLE_DOC_MIME:
        return
    if fetched.payload:
        return
    if _is_deterministically_empty_google_doc(drive_file):
        return
    raise DriveIngestionError(
        "Google Doc export returned an unexpected zero-byte payload; refusing to create a canonical document"
    )


def _is_deterministically_empty_google_doc(drive_file: DriveFile) -> bool:
    return drive_file.size == 0


def _source_state_hash(drive_file: DriveFile, payload_hash: str, normalization_metadata: Dict[str, Any]) -> str:
    return content_sha256(
        json.dumps(
            {
                "drive": _drive_metadata(drive_file),
                "normalization": normalization_metadata,
                "payload_hash": payload_hash,
            },
            sort_keys=True,
        ).encode("utf-8")
    )


def _normalize_drive_file(
    drive_file: DriveFile,
    payload: bytes,
    filename: str,
    export_mime_type: Optional[str],
) -> Dict[str, Any]:
    title = drive_file.name or Path(filename).stem or "Untitled Drive Document"
    metadata = {
        "adapter": "DriveSyncService",
        "drive_file_id": drive_file.file_id,
        "mime_type": drive_file.mime_type,
        "export_mime_type": export_mime_type,
    }
    if drive_file.mime_type == GOOGLE_DOC_MIME:
        text = _decode_text(payload)
        if (export_mime_type or "").lower() == "text/html":
            body = _html_to_markdown(text)
        else:
            body = text.rstrip() + "\n"
        return {"title": _first_heading(body) or title, "body": _ensure_heading(body, title), "metadata": metadata}
    if drive_file.mime_type == PDF_MIME:
        extracted = _extract_pdf_text(payload)
        body = f"# {title}\n\n## Extracted Text\n\n{extracted.rstrip() or '(No extractable PDF text.)'}\n"
        return {"title": title, "body": body, "metadata": {**metadata, "extraction": "pdf-text"}}
    if drive_file.mime_type in TEXT_MIME_TYPES or Path(filename).suffix.lower() in {".md", ".txt"}:
        text = _decode_text(payload).rstrip() + "\n"
        body = text if Path(filename).suffix.lower() == ".md" or drive_file.mime_type == "text/markdown" else f"# {title}\n\n{text}"
        return {"title": _first_heading(body) or title, "body": body, "metadata": metadata}
    if drive_file.mime_type == DOCX_MIME:
        body = f"# {title}\n\n{_extract_docx_text(payload).rstrip()}\n"
        return {"title": title, "body": body, "metadata": {**metadata, "extraction": "docx-text"}}
    raise DriveIngestionError(f"Unsupported Drive file type: {drive_file.mime_type}")


def _extract_pdf_text(payload: bytes) -> str:
    try:
        from pypdf import PdfReader
    except ImportError:
        return _extract_printable_strings(payload)

    reader = PdfReader(io.BytesIO(payload))
    parts = []
    for page in reader.pages:
        parts.append(page.extract_text() or "")
    return "\n\n".join(part.strip() for part in parts if part.strip())


def _extract_docx_text(payload: bytes) -> str:
    try:
        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            xml = archive.read("word/document.xml").decode("utf-8", errors="replace")
    except Exception as exc:
        raise DriveIngestionError("DOCX text extraction failed") from exc
    paragraphs = re.findall(r"<w:p\b[\s\S]*?</w:p>", xml)
    lines = []
    for paragraph in paragraphs:
        texts = re.findall(r"<w:t[^>]*>([\s\S]*?)</w:t>", paragraph)
        line = html.unescape("".join(texts)).strip()
        if line:
            lines.append(line)
    return "\n\n".join(lines) or "(No extractable DOCX text.)"


def _extract_printable_strings(payload: bytes) -> str:
    text = payload.decode("latin-1", errors="ignore")
    literal_strings = [html.unescape(item) for item in re.findall(r"\(([^()]{3,})\)", text)]
    if literal_strings:
        return "\n".join(_safe_markdown_text(item) for item in literal_strings)
    strings = re.findall(r"[A-Za-z0-9][A-Za-z0-9 ,.;:'\"!?()/_-]{8,}", text)
    return "\n".join(_safe_markdown_text(item) for item in strings[:200])


def _html_to_markdown(value: str) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
        value = re.sub(r"<h1[^>]*>(.*?)</h1>", r"# \1\n\n", value, flags=re.IGNORECASE | re.DOTALL)
        value = re.sub(r"<h2[^>]*>(.*?)</h2>", r"## \1\n\n", value, flags=re.IGNORECASE | re.DOTALL)
        value = re.sub(r"<li[^>]*>(.*?)</li>", r"- \1\n", value, flags=re.IGNORECASE | re.DOTALL)
        value = re.sub(r"<[^>]+>", " ", value)
        return html.unescape(re.sub(r"\s+", " ", value)).strip() + "\n"

    soup = BeautifulSoup(value, "html.parser")
    for tag in soup(["script", "style", "iframe", "object", "embed", "img"]):
        tag.decompose()
    lines: List[str] = []
    for element in soup.find_all(["h1", "h2", "h3", "p", "li", "tr"]):
        text = element.get_text(" ", strip=True)
        if not text:
            continue
        if element.name == "h1":
            lines.extend([f"# {text}", ""])
        elif element.name == "h2":
            lines.extend([f"## {text}", ""])
        elif element.name == "h3":
            lines.extend([f"### {text}", ""])
        elif element.name == "li":
            lines.append(f"- {text}")
        elif element.name == "tr":
            cells = [cell.get_text(" ", strip=True) for cell in element.find_all(["th", "td"])]
            if cells:
                lines.append(" | ".join(cells))
        else:
            lines.extend([text, ""])
    return "\n".join(lines).rstrip() + "\n"


def _decode_text(payload: bytes) -> str:
    if b"\x00" in payload:
        raise DriveIngestionError("Unsupported binary payload rejected")
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise DriveIngestionError("Unsupported text encoding rejected") from exc


def _ensure_heading(body: str, title: str) -> str:
    body = body.rstrip() + "\n"
    if body.lstrip().startswith("#"):
        return body
    return f"# {title}\n\n{body}"


def _first_heading(body: str) -> str:
    for line in body.splitlines():
        match = re.match(r"^#\s+(.+)$", line.strip())
        if match:
            return match.group(1).strip()
    return ""


def _drive_metadata(drive_file: DriveFile) -> Dict[str, Any]:
    return {
        "drive_file_id": drive_file.file_id,
        "mime_type": drive_file.mime_type,
        "source_url": drive_file.web_view_link,
        "original_name": drive_file.name,
        "created_time": drive_file.created_time,
        "modified_time": drive_file.modified_time,
        "owners": list(drive_file.owners),
        "parent_folder_ids": list(drive_file.parents),
        "source_version": _source_version(drive_file),
        "md5_checksum": drive_file.md5_checksum,
        "size": drive_file.size,
        "trashed": drive_file.trashed,
        "deleted": drive_file.deleted,
    }


def _source_version(drive_file: DriveFile, raw_record: Optional[RawRecord] = None) -> str:
    for value in (drive_file.head_revision_id, drive_file.version, drive_file.md5_checksum):
        if value:
            return str(value)
    if raw_record is not None:
        return f"raw-v{raw_record.version:06d}"
    return ""


def _drive_file_from_api(item: Dict[str, Any]) -> DriveFile:
    owners = []
    for owner in item.get("owners") or []:
        owners.append(str(owner.get("emailAddress") or owner.get("displayName") or "").strip())
    return DriveFile(
        file_id=str(item.get("id") or ""),
        name=str(item.get("name") or ""),
        mime_type=str(item.get("mimeType") or ""),
        web_view_link=str(item.get("webViewLink") or ""),
        created_time=str(item.get("createdTime") or ""),
        modified_time=str(item.get("modifiedTime") or ""),
        owners=[owner for owner in owners if owner],
        parents=[str(parent) for parent in item.get("parents") or []],
        md5_checksum=str(item.get("md5Checksum") or ""),
        size=int(item["size"]) if str(item.get("size") or "").isdigit() else None,
        version=str(item.get("version") or ""),
        head_revision_id=str(item.get("headRevisionId") or ""),
        trashed=bool(item.get("trashed")),
    )


def _rfc3339_for_since(value: str) -> str:
    value = value.strip().lower()
    match = re.fullmatch(r"(\d+)([dmy])", value)
    if match:
        amount, unit = match.groups()
        days = int(amount) * {"d": 1, "m": 30, "y": 365}[unit]
        return (datetime.now(timezone.utc) - timedelta(days=days)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    date_match = re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
    if date_match:
        return datetime.fromisoformat(value).replace(tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")
    raise DriveIngestionError("Unsupported --since value. Use a bounded value like 30d or 2026-01-31.")


def _escape_drive_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _date_or_default(value: str, default: str) -> str:
    return value or default


def _is_retryable_google_error(exc: Exception) -> bool:
    status = _error_status(exc)
    details = _error_text(exc).lower()
    if status in {429, 500, 502, 503, 504}:
        return True
    if status == 403 and any(marker in details for marker in RETRYABLE_403_MARKERS):
        return True
    return False


def _safe_markdown_text(value: str) -> str:
    value = html.unescape(value or "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)
    value = value.replace("<", "&lt;").replace(">", "&gt;")
    value = re.sub(r"\n{4,}", "\n\n\n", value)
    return value.strip()


def _safe_error(exc: Exception) -> str:
    return re.sub(r"\s+", " ", str(exc)).strip()[:240] or exc.__class__.__name__
