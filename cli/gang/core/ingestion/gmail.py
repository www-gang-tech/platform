"""Deterministic Gmail ingestion into the private knowledge vault."""

from __future__ import annotations

import base64
import email
import email.utils
import html
import json
import random
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.message import Message
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Protocol

import yaml

from core.entities.documents import preserved_entity_frontmatter
from core.paths import GangPaths

from .attachments import (
    ATTACHMENT_CONTENT_SOURCE_TYPE,
    AttachmentIngestionService,
    AttachmentOccurrence,
    AttachmentReport,
    attachment_source_id,
)
from .extract import STATUS_EXTRACTED, STATUS_UNSUPPORTED
from .ids import content_sha256, slugify, stable_source_id, uuid7
from .raw_store import LocalRawStore, RawRecord, RawStore
from .registry import IngestionRegistry


GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
RETRYABLE_403_MARKERS = (
    "quota",
    "rate limit",
    "ratelimit",
    "userratelimitexceeded",
    "quotaexceeded",
    "limit exceeded",
    "rate exceeded",
)


class GmailIngestionError(Exception):
    """Raised when Gmail ingestion cannot proceed safely."""


@dataclass(frozen=True)
class GmailRetryPolicy:
    max_attempts: int = 5
    base_delay_seconds: float = 1.0
    max_delay_seconds: float = 30.0
    jitter_seconds: float = 0.5
    min_request_interval_seconds: float = 0.25


@dataclass(frozen=True)
class GmailAttachment:
    attachment_id: str
    filename: str
    mime_type: str
    message_id: str
    size: int = 0
    #: The MIME part ID. Unlike ``attachment_id``, which Gmail reissues on
    #: every response, it is stable for the life of the message.
    part_id: str = ""


@dataclass(frozen=True)
class GmailMessage:
    message_id: str
    thread_id: str
    internal_date_ms: int
    history_id: str = ""
    label_ids: List[str] = field(default_factory=list)
    headers: Dict[str, str] = field(default_factory=dict)
    snippet: str = ""
    raw_payload: bytes = b""
    text_body: str = ""
    html_body: str = ""
    attachments: List[GmailAttachment] = field(default_factory=list)


@dataclass(frozen=True)
class GmailThread:
    thread_id: str
    messages: List[GmailMessage]


@dataclass(frozen=True)
class GmailThreadResult:
    thread_id: str
    source_id: str
    document_id: str
    document_path: Optional[Path]
    status: str
    messages: int
    raw_versions: List[RawRecord]
    error: Optional[str] = None
    attachments: Optional[AttachmentReport] = None


@dataclass(frozen=True)
class GmailSyncResult:
    threads_discovered: int
    messages_discovered: int
    created: int
    updated: int
    unchanged: int
    failed: int
    checkpoint: Dict[str, Any]
    checkpoint_advanced: bool
    results: List[GmailThreadResult]
    attachments: AttachmentReport = field(default_factory=AttachmentReport)


class GmailProvider(Protocol):
    """Narrow boundary around Gmail API behavior."""

    def discover_thread_ids(self, query: str) -> Iterable[str]:
        """Return Gmail thread IDs matching a deterministic query."""

    def fetch_thread(self, thread_id: str) -> GmailThread:
        """Fetch one Gmail thread and its messages."""

    def fetch_attachment(self, message_id: str, attachment_id: str) -> bytes:
        """Fetch a Gmail attachment payload."""


class GoogleGmailProvider:
    """Google API implementation kept outside canonical knowledge logic."""

    def __init__(
        self,
        *,
        token_path: Path | str | None = None,
        credentials_path: Path | str | None = None,
        private_home: Path | str | None = None,
        scopes: Optional[List[str]] = None,
        retry_policy: Optional[GmailRetryPolicy] = None,
        sleep_fn=time.sleep,
        monotonic_fn=time.monotonic,
        random_fn=random.random,
    ):
        paths = GangPaths.from_env(gang_home=private_home)
        self.token_path = Path(token_path) if token_path is not None else paths.gmail_token_path
        self.credentials_path = Path(credentials_path) if credentials_path is not None else paths.gmail_credentials_path
        self.scopes = scopes or [GMAIL_READONLY_SCOPE]
        self.retry_policy = retry_policy or GmailRetryPolicy()
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
            raise GmailIngestionError(
                "Gmail auth requires google-auth-oauthlib. Install requirements.txt first."
            ) from exc

        if not self.credentials_path.exists():
            raise GmailIngestionError(f"OAuth client credentials not found: {self.credentials_path}")

        flow = InstalledAppFlow.from_client_secrets_file(str(self.credentials_path), self.scopes)
        credentials = flow.run_local_server(port=0)
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(credentials.to_json() + "\n", encoding="utf-8")
        return self.token_path

    def discover_thread_ids(self, query: str) -> Iterable[str]:
        service = self._gmail_service()
        page_token = None
        seen = set()
        while True:
            request = service.users().messages().list(userId="me", q=query, pageToken=page_token)
            response = self._execute(request)
            for message in response.get("messages", []):
                thread_id = message.get("threadId")
                if thread_id and thread_id not in seen:
                    seen.add(thread_id)
                    yield thread_id
            page_token = response.get("nextPageToken")
            if not page_token:
                break

    def fetch_thread(self, thread_id: str) -> GmailThread:
        service = self._gmail_service()
        response = self._execute(service.users().threads().get(userId="me", id=thread_id, format="full"))
        messages = []
        for item in response.get("messages", []):
            message_id = item["id"]
            raw_response = self._execute(service.users().messages().get(userId="me", id=message_id, format="raw"))
            raw_payload = _decode_gmail_base64(raw_response.get("raw", ""))
            parsed = _message_from_gmail_payload(item, raw_payload)
            messages.append(parsed)
        return GmailThread(thread_id=thread_id, messages=messages)

    def account_email(self) -> str:
        """The mailbox being read, recorded as each attachment's source account."""
        response = self._execute(self._gmail_service().users().getProfile(userId="me"))
        return str(response.get("emailAddress") or "")

    def fetch_attachment(self, message_id: str, attachment_id: str) -> bytes:
        response = self._execute(
            self._gmail_service().users().messages().attachments().get(userId="me", messageId=message_id, id=attachment_id)
        )
        return _decode_gmail_base64(response.get("data", ""))

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
        raise GmailIngestionError("Gmail request failed without an exception")

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

    def _gmail_service(self):
        if self._service is not None:
            return self._service
        try:
            from google.auth.transport.requests import Request
            from google.oauth2.credentials import Credentials
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise GmailIngestionError(
                "Gmail sync requires google-api-python-client and google-auth. Install requirements.txt first."
            ) from exc

        if not self.token_path.exists():
            raise GmailIngestionError("Gmail is not authenticated. Run: gang ingest gmail auth")

        credentials = Credentials.from_authorized_user_file(str(self.token_path), self.scopes)
        if credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
            self.token_path.write_text(credentials.to_json() + "\n", encoding="utf-8")
        if not credentials.valid:
            raise GmailIngestionError("Gmail token is invalid. Run: gang ingest gmail auth")

        self._service = build("gmail", "v1", credentials=credentials)
        return self._service


class GmailSyncService:
    """Synchronize Gmail threads into existing raw, registry, and private vault primitives."""

    def __init__(
        self,
        provider: GmailProvider,
        *,
        root_path: Path | str = Path("."),
        raw_store: Optional[RawStore] = None,
        registry: Optional[IngestionRegistry] = None,
        vault_path: Path | str | None = None,
        emails_path: Path | str | None = None,
        checkpoint_path: Path | str | None = None,
        private_home: Path | str | None = None,
    ):
        self.provider = provider
        self.root_path = Path(root_path).resolve()
        self.paths = GangPaths.from_env(repo_root=self.root_path, gang_home=private_home)
        self.raw_store = raw_store or LocalRawStore(self.paths.raw_path)
        self.vault_path = self._resolve(vault_path) if vault_path is not None else self.paths.private_vault
        self.emails_path = self._resolve(emails_path) if emails_path is not None else self.paths.emails_path
        self.checkpoint_path = self._resolve(checkpoint_path) if checkpoint_path is not None else self.paths.gmail_checkpoint_path
        self.registry = registry or IngestionRegistry(self.paths.registry_path, root_path=self.paths.home)
        self.attachments_path = self.paths.attachments_path
        self.source_account = ""

    def attachment_service(self) -> AttachmentIngestionService:
        return AttachmentIngestionService(
            raw_store=self.raw_store,
            registry=self.registry,
            attachments_path=self.attachments_path,
        )

    def sync(self, *, since: Optional[str] = None) -> GmailSyncResult:
        checkpoint = self.load_checkpoint()
        query = self._query_for_sync(since, checkpoint)
        self.source_account = self._resolve_source_account(checkpoint)
        thread_ids = list(dict.fromkeys(self.provider.discover_thread_ids(query)))

        results: List[GmailThreadResult] = []
        messages_discovered = 0
        max_internal_date = int(checkpoint.get("last_successful_internal_date_ms") or 0)

        for thread_id in thread_ids:
            try:
                thread = self.provider.fetch_thread(thread_id)
                messages_discovered += len(thread.messages)
                if thread.messages:
                    max_internal_date = max(max_internal_date, max(message.internal_date_ms for message in thread.messages))
                results.append(self._ingest_thread(thread))
            except Exception as exc:
                results.append(
                    GmailThreadResult(
                        thread_id=thread_id,
                        source_id=_gmail_thread_source_id(thread_id),
                        document_id="",
                        document_path=None,
                        status="failed",
                        messages=0,
                        raw_versions=[],
                        error=_safe_error(exc),
                    )
                )

        attachments = AttachmentReport()
        for result in results:
            if result.attachments is not None:
                attachments.merge(result.attachments)

        failed = sum(1 for result in results if result.status == "failed")
        checkpoint_advanced = False
        if failed == 0:
            checkpoint = {
                "version": 1,
                "account_email": self.source_account,
                "last_query": query,
                "last_successful_sync_at": datetime.now(timezone.utc).isoformat(),
                "last_successful_internal_date_ms": max_internal_date,
                "thread_count": len(thread_ids),
                "message_count": messages_discovered,
            }
            self._save_checkpoint(checkpoint)
            checkpoint_advanced = True

        return GmailSyncResult(
            threads_discovered=len(thread_ids),
            messages_discovered=messages_discovered,
            created=sum(1 for result in results if result.status == "created"),
            updated=sum(1 for result in results if result.status == "updated"),
            unchanged=sum(1 for result in results if result.status == "unchanged"),
            failed=failed,
            checkpoint=checkpoint,
            checkpoint_advanced=checkpoint_advanced,
            results=results,
            attachments=attachments,
        )

    def status(self) -> Dict[str, Any]:
        sources = {
            source_id: record
            for source_id, record in self.registry.all_sources().items()
            if record.get("adapter") == "GmailSyncService" or record.get("source_type") == "gmail-thread"
        }
        return {
            "checkpoint_path": self.checkpoint_path,
            "checkpoint": self.load_checkpoint(),
            "threads": len(sources),
            "documents": len({record.get("document_id") for record in sources.values() if record.get("document_id")}),
            "attachments": self._attachment_status(),
        }

    def _attachment_status(self) -> Dict[str, Any]:
        records = self.registry.all_sources().values()
        payloads = [record for record in records if record.get("source_type") == ATTACHMENT_CONTENT_SOURCE_TYPE]
        by_status: Dict[str, int] = {}
        for record in payloads:
            status = str(record.get("extraction_status") or "unknown")
            by_status[status] = by_status.get(status, 0) + 1
        problems = sorted(
            (
                record
                for record in payloads
                if record.get("extraction_status") not in {STATUS_EXTRACTED, STATUS_UNSUPPORTED}
            ),
            key=lambda record: (str(record.get("extraction_status")), str(record.get("source_name"))),
        )
        return {
            "occurrences": sum(1 for record in records if record.get("source_type") == "gmail-attachment" and record.get("content_source_id")),
            "payloads": len(payloads),
            "documents": sum(1 for record in payloads if record.get("document_id")),
            "by_status": by_status,
            "problems": problems,
        }

    def load_checkpoint(self) -> Dict[str, Any]:
        if not self.checkpoint_path.exists():
            return {}
        return json.loads(self.checkpoint_path.read_text(encoding="utf-8"))

    def _ingest_thread(self, thread: GmailThread) -> GmailThreadResult:
        if not thread.messages:
            raise GmailIngestionError(f"Gmail thread has no messages: {thread.thread_id}")

        messages = sorted(thread.messages, key=lambda item: (item.internal_date_ms, item.message_id))
        thread_source_id = _gmail_thread_source_id(thread.thread_id)
        previous = self.registry.get(thread_source_id)
        now = datetime.now(timezone.utc).isoformat()
        created_at = previous.get("created_at", now) if previous else now
        message_records: List[Dict[str, Any]] = []
        raw_versions: List[RawRecord] = []
        failures: List[str] = []

        for message in messages:
            if message.thread_id != thread.thread_id:
                raise GmailIngestionError("Gmail message thread identity mismatch")
            raw_payload = message.raw_payload or _raw_fallback(message)
            message_source_id = _gmail_message_source_id(message.message_id)
            raw_record = self.raw_store.put(
                "gmail-message",
                message_source_id,
                raw_payload,
                filename=f"{message.message_id}.eml",
                metadata={
                    "gmail_message_id": message.message_id,
                    "gmail_thread_id": thread.thread_id,
                    "history_id": message.history_id,
                    "internal_date_ms": message.internal_date_ms,
                },
            )
            raw_versions.append(raw_record)

            attachment_records = []
            for attachment in message.attachments:
                try:
                    payload = self.provider.fetch_attachment(message.message_id, attachment.attachment_id)
                    attachment_raw = self.raw_store.put(
                        "gmail-attachment",
                        attachment_source_id(message.message_id, content_sha256(payload)),
                        payload,
                        filename=attachment.filename or attachment.attachment_id,
                        metadata={
                            "gmail_message_id": message.message_id,
                            "gmail_thread_id": thread.thread_id,
                            "gmail_attachment_id": attachment.attachment_id,
                            "part_id": attachment.part_id,
                            "filename": attachment.filename,
                            "mime_type": attachment.mime_type,
                        },
                    )
                    # The ephemeral Gmail attachment ID stays out of the
                    # manifest: an unchanged thread must hash the same twice.
                    attachment_records.append(
                        {
                            "source_id": attachment_raw.source_id,
                            "part_id": attachment.part_id,
                            "filename": attachment.filename,
                            "mime_type": attachment.mime_type,
                            "parent_gmail_message_id": message.message_id,
                            "content_hash": attachment_raw.content_hash,
                            "raw_ref": attachment_raw.raw_ref,
                        }
                    )
                except Exception as exc:
                    failures.append(f"attachment {attachment.attachment_id}: {_safe_error(exc)}")

            message_records.append(
                {
                    "gmail_message_id": message.message_id,
                    "gmail_thread_id": message.thread_id,
                    "source_id": message_source_id,
                    "raw_ref": raw_record.raw_ref,
                    "content_hash": raw_record.content_hash,
                    "version": raw_record.version,
                    "internal_date_ms": message.internal_date_ms,
                    "history_id": message.history_id,
                    "headers": _curated_headers(message.headers),
                    "attachments": attachment_records,
                }
            )

        if failures:
            raise GmailIngestionError("; ".join(failures))

        metadata = _thread_metadata(thread.thread_id, messages)
        body = _thread_body(metadata, messages)
        manifest = {
            "source_type": "gmail-thread",
            "source_id": thread_source_id,
            "gmail_thread_id": thread.thread_id,
            "metadata": metadata,
            "messages": message_records,
        }
        manifest_payload = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
        manifest_hash = content_sha256(manifest_payload)

        if previous and previous.get("content_hash") == manifest_hash:
            return GmailThreadResult(
                thread_id=thread.thread_id,
                source_id=thread_source_id,
                document_id=previous["document_id"],
                document_path=self.registry.resolve_path(previous["document_path"]),
                status="unchanged",
                messages=len(messages),
                raw_versions=raw_versions,
                attachments=self._ingest_attachments(thread.thread_id, messages, message_records),
            )

        manifest_raw = self.raw_store.put(
            "gmail-thread",
            thread_source_id,
            manifest_payload,
            filename=f"{thread.thread_id}.json",
            metadata={"gmail_thread_id": thread.thread_id, "message_count": len(messages)},
        )
        document_id = previous["document_id"] if previous else uuid7()
        document_path = self._write_thread_document(
            document_id=document_id,
            metadata=metadata,
            body=body,
            thread_source_id=thread_source_id,
            manifest_raw=manifest_raw,
            manifest=manifest,
            created_at=created_at,
            updated_at=now,
            document_path=self.registry.resolve_path(previous["document_path"]) if previous else None,
        )
        self.registry.upsert(
            thread_source_id,
            {
                "source_id": thread_source_id,
                "adapter": "GmailSyncService",
                "source_type": "gmail-thread",
                "source_name": metadata["subject"],
                "content_hash": manifest_raw.content_hash,
                "version": manifest_raw.version,
                "document_id": document_id,
                "document_path": self.registry.relative_path(document_path),
                "raw_ref": manifest_raw.raw_ref,
                "ingested_at": now,
                "created_at": created_at,
                "updated_at": now,
                "gmail_thread_id": thread.thread_id,
                "gmail_message_ids": [message.message_id for message in messages],
            },
        )
        return GmailThreadResult(
            thread_id=thread.thread_id,
            source_id=thread_source_id,
            document_id=document_id,
            document_path=document_path,
            status="updated" if previous else "created",
            messages=len(messages),
            raw_versions=[*raw_versions, manifest_raw],
            attachments=self._ingest_attachments(thread.thread_id, messages, message_records),
        )

    def _ingest_attachments(
        self,
        thread_id: str,
        messages: List[GmailMessage],
        message_records: List[Dict[str, Any]],
    ) -> AttachmentReport:
        """Each attachment as its own canonical document. Never fails the thread."""
        received = {message.message_id: _iso_from_ms(message.internal_date_ms) for message in messages}
        occurrences = [
            AttachmentOccurrence(
                gmail_message_id=record["gmail_message_id"],
                gmail_thread_id=thread_id,
                filename=attachment.get("filename") or "",
                mime_type=attachment.get("mime_type") or "application/octet-stream",
                content_hash=attachment["content_hash"],
                raw_ref=attachment["raw_ref"],
                received_at=received.get(record["gmail_message_id"], ""),
                source_account=self.source_account,
                part_id=attachment.get("part_id") or "",
            )
            for record in message_records
            for attachment in record.get("attachments") or []
        ]
        if not occurrences:
            return AttachmentReport()
        return self.attachment_service().ingest(occurrences)

    def _resolve_source_account(self, checkpoint: Dict[str, Any]) -> str:
        account_email = getattr(self.provider, "account_email", None)
        if callable(account_email):
            try:
                return str(account_email() or "")
            except Exception:  # noqa: BLE001 - provenance nicety, never a sync failure
                pass
        return str(checkpoint.get("account_email") or "")

    def _write_thread_document(
        self,
        *,
        document_id: str,
        metadata: Dict[str, Any],
        body: str,
        thread_source_id: str,
        manifest_raw: RawRecord,
        manifest: Dict[str, Any],
        created_at: str,
        updated_at: str,
        document_path: Optional[Path],
    ) -> Path:
        self.emails_path.mkdir(parents=True, exist_ok=True)
        if document_path is None:
            document_path = self.emails_path / f"{document_id}-{slugify(metadata['subject'], 'email-thread')}.md"
        frontmatter = {
            "id": document_id,
            "type": "email-thread",
            "source_type": "gmail-thread",
            "title": metadata["subject"],
            "created": metadata.get("first_message_at") or created_at,
            "updated": metadata.get("last_message_at") or updated_at,
            "created_at": created_at,
            "updated_at": updated_at,
            "visibility": "private",
            "status": "active",
            "content_trust": "untrusted",
            "people": [],
            "companies": [],
            "projects": [],
            "tags": [],
            "sources": [{"source_id": thread_source_id, "type": "gmail-thread", "raw_ref": manifest_raw.raw_ref}],
            "source_id": thread_source_id,
            "source_ids": [thread_source_id, *[item["source_id"] for item in manifest["messages"]]],
            "related": [],
            "gmail": metadata,
            "content_hash": manifest_raw.content_hash,
            "version": manifest_raw.version,
            "raw_ref": manifest_raw.raw_ref,
            "provenance": {
                "source_id": thread_source_id,
                "source_type": "gmail-thread",
                "gmail_thread_id": metadata["gmail_thread_id"],
                "raw_ref": manifest_raw.raw_ref,
                "content_hash": manifest_raw.content_hash,
                "version": manifest_raw.version,
                "messages": [
                    {
                        "gmail_message_id": item["gmail_message_id"],
                        "source_id": item["source_id"],
                        "raw_ref": item["raw_ref"],
                        "version": item["version"],
                    }
                    for item in manifest["messages"]
                ],
            },
            "ingestion_envelope": manifest,
        }
        frontmatter.update(preserved_entity_frontmatter(document_path))
        frontmatter_text = yaml.safe_dump(frontmatter, sort_keys=False, allow_unicode=True)
        document_path.parent.mkdir(parents=True, exist_ok=True)
        document_path.write_text(f"---\n{frontmatter_text}---\n\n{body}", encoding="utf-8")
        return document_path

    def _query_for_sync(self, since: Optional[str], checkpoint: Dict[str, Any]) -> str:
        if since:
            return _query_for_since(since)
        last_ms = int(checkpoint.get("last_successful_internal_date_ms") or 0)
        if not last_ms:
            raise GmailIngestionError("First Gmail sync must be bounded. Example: gang ingest gmail --since 30d")
        overlap_seconds = max(0, int(last_ms / 1000) - 1)
        return f"after:{overlap_seconds}"

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


def _message_from_gmail_payload(item: Dict[str, Any], raw_payload: bytes) -> GmailMessage:
    payload = item.get("payload") or {}
    headers = {header.get("name", ""): header.get("value", "") for header in payload.get("headers", [])}
    parsed = email.message_from_bytes(raw_payload)
    text_body, html_body = _extract_bodies(parsed)
    attachments = _extract_attachments(item)
    return GmailMessage(
        message_id=item["id"],
        thread_id=item["threadId"],
        internal_date_ms=int(item.get("internalDate") or 0),
        history_id=str(item.get("historyId") or ""),
        label_ids=list(item.get("labelIds") or []),
        headers=headers or dict(parsed.items()),
        snippet=str(item.get("snippet") or ""),
        raw_payload=raw_payload,
        text_body=text_body,
        html_body=html_body,
        attachments=attachments,
    )


def _extract_bodies(message: Message) -> tuple[str, str]:
    text_parts: List[str] = []
    html_parts: List[str] = []
    for part in message.walk() if message.is_multipart() else [message]:
        content_disposition = (part.get("Content-Disposition") or "").lower()
        if "attachment" in content_disposition:
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            decoded = payload.decode(charset, errors="replace")
        except LookupError:
            decoded = payload.decode("utf-8", errors="replace")
        content_type = part.get_content_type()
        if content_type == "text/plain":
            text_parts.append(decoded)
        elif content_type == "text/html":
            html_parts.append(decoded)
    return "\n".join(text_parts).strip(), "\n".join(html_parts).strip()


def _extract_attachments(item: Dict[str, Any]) -> List[GmailAttachment]:
    attachments: List[GmailAttachment] = []

    def visit(part: Dict[str, Any]) -> None:
        body = part.get("body") or {}
        attachment_id = body.get("attachmentId")
        filename = part.get("filename") or ""
        if attachment_id:
            attachments.append(
                GmailAttachment(
                    attachment_id=attachment_id,
                    filename=filename,
                    mime_type=part.get("mimeType") or "application/octet-stream",
                    message_id=item["id"],
                    size=int(body.get("size") or 0),
                    part_id=str(part.get("partId") or ""),
                )
            )
        for child in part.get("parts") or []:
            visit(child)

    visit(item.get("payload") or {})
    return attachments


def _decode_gmail_base64(value: str) -> bytes:
    if not value:
        return b""
    padded = value + "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _is_retryable_google_error(exc: Exception) -> bool:
    status = _error_status(exc)
    details = _error_text(exc).lower()
    if status in {429, 500, 502, 503, 504}:
        return True
    if status == 403 and any(marker in details for marker in RETRYABLE_403_MARKERS):
        return True
    return False


def _error_status(exc: Exception) -> Optional[int]:
    response = getattr(exc, "resp", None) or getattr(exc, "response", None)
    for candidate in (getattr(response, "status", None), getattr(response, "status_code", None), getattr(exc, "status", None)):
        if candidate is None:
            continue
        try:
            return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


def _error_text(exc: Exception) -> str:
    parts = [str(exc)]
    content = getattr(exc, "content", None)
    if isinstance(content, bytes):
        parts.append(content.decode("utf-8", errors="replace"))
    elif content is not None:
        parts.append(str(content))
    return " ".join(parts)


def _retry_after_seconds(exc: Exception) -> Optional[float]:
    response = getattr(exc, "resp", None) or getattr(exc, "response", None)
    if response is None:
        return None
    value = _header_value(response, "retry-after")
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, (parsed - datetime.now(timezone.utc)).total_seconds())


def _header_value(response: Any, name: str) -> Optional[str]:
    headers = getattr(response, "headers", None)
    if isinstance(headers, dict):
        for key, value in headers.items():
            if str(key).lower() == name.lower():
                return str(value)
    if hasattr(response, "get"):
        try:
            value = response.get(name) or response.get(name.title())
            if value is not None:
                return str(value)
        except Exception:
            return None
    return None


def _query_for_since(value: str) -> str:
    value = value.strip().lower()
    match = re.fullmatch(r"(\d+)([dmy])", value)
    if match:
        amount, unit = match.groups()
        return f"newer_than:{amount}{unit}"
    date_match = re.fullmatch(r"\d{4}-\d{2}-\d{2}", value)
    if date_match:
        dt = datetime.fromisoformat(value).replace(tzinfo=timezone.utc)
        return f"after:{int(dt.timestamp())}"
    raise GmailIngestionError("Unsupported --since value. Use a bounded value like 30d or 2026-01-31.")


def _gmail_thread_source_id(thread_id: str) -> str:
    return stable_source_id("gmail-thread", "gmail", thread_id)


def _gmail_message_source_id(message_id: str) -> str:
    return stable_source_id("gmail-message", "gmail", message_id)


def _thread_metadata(thread_id: str, messages: List[GmailMessage]) -> Dict[str, Any]:
    subject = _clean_subject(_first_header(messages, "Subject") or "(no subject)")
    participants = sorted(
        {
            value
            for message in messages
            for value in _participants_for_message(message)
            if value
        }
    )
    first_ms = min(message.internal_date_ms for message in messages)
    last_ms = max(message.internal_date_ms for message in messages)
    return {
        "gmail_thread_id": thread_id,
        "subject": subject,
        "participants": participants,
        "first_message_at": _iso_from_ms(first_ms),
        "last_message_at": _iso_from_ms(last_ms),
        "message_count": len(messages),
        "message_ids": [message.message_id for message in messages],
    }


def _thread_body(metadata: Dict[str, Any], messages: List[GmailMessage]) -> str:
    lines = [
        f"# {metadata['subject']}",
        "",
        "## Thread Metadata",
        "",
        f"- Gmail thread ID: `{metadata['gmail_thread_id']}`",
        f"- Message count: {metadata['message_count']}",
        f"- First message: {metadata['first_message_at']}",
        f"- Last message: {metadata['last_message_at']}",
    ]
    if metadata["participants"]:
        lines.append("- Participants: " + ", ".join(metadata["participants"]))
    lines.extend(["", "## Messages", ""])

    for index, message in enumerate(messages, 1):
        headers = _curated_headers(message.headers)
        lines.extend(
            [
                f"### Message {index}",
                "",
                f"- Gmail message ID: `{message.message_id}`",
                f"- Date: {headers.get('Date') or _iso_from_ms(message.internal_date_ms)}",
                f"- From: {_safe_inline(headers.get('From') or '')}",
            ]
        )
        if headers.get("To"):
            lines.append(f"- To: {_safe_inline(headers['To'])}")
        if headers.get("Cc"):
            lines.append(f"- Cc: {_safe_inline(headers['Cc'])}")
        lines.extend(["", _safe_markdown_text(_message_text(message)).rstrip(), ""])
        if message.attachments:
            lines.extend(["Attachments:", ""])
            for attachment in message.attachments:
                lines.append(f"- {_safe_inline(attachment.filename or attachment.attachment_id)} ({attachment.mime_type})")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _message_text(message: GmailMessage) -> str:
    if message.text_body.strip():
        return message.text_body
    if message.html_body.strip():
        return _html_to_text(message.html_body)
    if message.snippet.strip():
        return message.snippet
    parsed = email.message_from_bytes(message.raw_payload or b"")
    text, html_body = _extract_bodies(parsed)
    if text:
        return text
    if html_body:
        return _html_to_text(html_body)
    return ""


def _html_to_text(value: str) -> str:
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        value = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value)
        value = re.sub(r"(?is)<img\b[^>]*>", " ", value)
        value = re.sub(r"<[^>]+>", " ", value)
        return html.unescape(re.sub(r"\s+", " ", value)).strip()

    soup = BeautifulSoup(value, "html.parser")
    for tag in soup(["script", "style", "iframe", "object", "embed", "img"]):
        tag.decompose()
    return soup.get_text("\n", strip=True)


def _safe_markdown_text(value: str) -> str:
    value = html.unescape(value or "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)
    value = value.replace("<", "&lt;").replace(">", "&gt;")
    value = re.sub(r"\n{4,}", "\n\n\n", value)
    return value.strip() or "(empty message body)"


def _safe_inline(value: str) -> str:
    return _safe_markdown_text(value).replace("\n", " ")


def _participants_for_message(message: GmailMessage) -> List[str]:
    values = []
    for key in ("From", "To", "Cc"):
        raw = message.headers.get(key) or message.headers.get(key.lower()) or ""
        values.extend([item.strip() for item in raw.split(",") if item.strip()])
    return values


def _curated_headers(headers: Dict[str, str]) -> Dict[str, str]:
    result = {}
    for key in ("Date", "From", "To", "Cc", "Subject", "Message-ID"):
        value = headers.get(key) or headers.get(key.lower())
        if value:
            result[key] = str(value)
    return result


def _first_header(messages: List[GmailMessage], key: str) -> str:
    for message in messages:
        value = message.headers.get(key) or message.headers.get(key.lower())
        if value:
            return str(value)
    return ""


def _clean_subject(value: str) -> str:
    value = re.sub(r"^\s*(re|fwd?):\s*", "", value, flags=re.IGNORECASE).strip()
    return value or "(no subject)"


def _iso_from_ms(value: int) -> str:
    return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()


def _raw_fallback(message: GmailMessage) -> bytes:
    headers = "\n".join(f"{key}: {value}" for key, value in _curated_headers(message.headers).items())
    body = message.text_body or _html_to_text(message.html_body) or message.snippet
    return (headers + "\n\n" + body).encode("utf-8")


def _safe_error(exc: Exception) -> str:
    return re.sub(r"\s+", " ", str(exc)).strip()[:240] or exc.__class__.__name__
