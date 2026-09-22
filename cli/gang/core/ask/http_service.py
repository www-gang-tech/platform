"""Local-only authenticated HTTP surface for conversational Ask.

This module is deliberately a wrapper around ``ConversationService``. It does
not add new corpus capabilities: requests can ask questions, inspect/delete
conversation sessions, and read transient job state. Corpus retrieval still
runs through the existing typed planner and read-only index.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import queue
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException

from core.ai_provider import AIConfig, ProviderTimeoutError

from .conversation import ConversationOptions, ConversationService
from .plan import DEFAULT_LIMIT, MAX_LIMIT, QueryPlanError, validate_plan
from .planner import PlanOverrides
from .retrieval import Retriever
from .service import AskError
from .session import SessionError


HTTP_LOCAL_MODEL = "qwen3:8b"
HTTP_PRINCIPAL = "Daniel"
DEFAULT_BIND_HOST = "127.0.0.1"
DEFAULT_QUEUE_DEPTH = 8
TOKEN_HASH_ENV = "GANG_HTTP_TOKEN_SHA256"

REQUEST_FIELDS = {"question", "session_id", "level", "filters"}
LEVELS = {"fast", "normal"}

FILTER_FIELDS = {
    "document_types",
    "source_types",
    "visibility",
    "date_range",
    "entity_ids",
    "order",
    "limit",
}

SENSITIVE_CONTROL_FIELDS = {
    "mode",
    "provider",
    "model",
    "premium",
    "local_only",
    "endpoint",
    "GANG_HOME",
    "root",
    "path",
    "paths",
    "filesystem",
    "cache",
    "cache_settings",
    "research",
    "research_controls",
    "mode_override",
}

HTTP_RESULT_DROP_FIELDS = {"provider_calls"}


class HTTPConfigError(RuntimeError):
    """Raised when the shared service would start in an unsafe configuration."""


class HTTPRequestError(ValueError):
    """Raised for client input that does not match the Stage 1 contract."""

    def __init__(self, code: str, message: str, *, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


class QueueFullError(RuntimeError):
    """Raised when the single Ask worker queue is at capacity."""


@dataclass
class Job:
    job_id: str
    request_id: str
    principal: str
    payload: Dict[str, Any]
    status: str = "queued"
    created_at: str = field(default_factory=lambda: _now())
    updated_at: str = field(default_factory=lambda: _now())
    result: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None

    def public(self) -> Dict[str, Any]:
        body: Dict[str, Any] = {
            "job_id": self.job_id,
            "request_id": self.request_id,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
        if self.result is not None:
            body["result"] = self.result
        if self.error is not None:
            body["error"] = self.error
        return body


class AuditedRetriever(Retriever):
    """Retriever wrapper that records each actual index read."""

    READ_METHODS = (
        "vocabulary",
        "retrieve",
        "documents",
        "content_hashes",
        "entity",
        "entity_document_ids",
        "entity_relationships",
        "foundational_documents",
        "recent_documents",
        "enriched_documents",
    )

    def __init__(
        self,
        database_path: Path | str,
        *,
        audit_path: Path | str,
        principal: str = HTTP_PRINCIPAL,
        clock: Optional[Any] = None,
    ):
        super().__init__(database_path)
        self.audit_path = Path(audit_path)
        self.principal = principal
        self.clock = clock
        self._local = threading.local()

    def bind_request(self, request_id: str):
        return _RetrieverAuditContext(self, request_id)

    def _request_id(self) -> str:
        return str(getattr(self._local, "request_id", "") or "")

    def _write_audit(self, method: str, result: Any, arguments: Dict[str, Any]) -> None:
        record = {
            "version": "1",
            "kind": "retrieval",
            "timestamp": _now(self.clock),
            "request_id": self._request_id(),
            "principal": self.principal,
            "method": method,
            "arguments": _safe_arguments(arguments),
            "result": _result_summary(result),
        }
        _append_jsonl_private(self.audit_path, record)

    def vocabulary(self) -> Dict[str, List[str]]:
        result = super().vocabulary()
        self._write_audit("vocabulary", result, {})
        return result

    def retrieve(self, plan):
        result = super().retrieve(plan)
        self._write_audit("retrieve", result, {"plan": plan.to_dict()})
        return result

    def documents(self, document_ids):
        result = super().documents(document_ids)
        self._write_audit("documents", result, {"document_ids": list(document_ids or [])})
        return result

    def content_hashes(self, document_ids):
        result = super().content_hashes(document_ids)
        self._write_audit("content_hashes", result, {"document_ids": list(document_ids or [])})
        return result

    def entity(self, entity_id):
        result = super().entity(entity_id)
        self._write_audit("entity", result, {"entity_id": entity_id})
        return result

    def entity_document_ids(self, entity_id, *, limit: int = 25):
        result = super().entity_document_ids(entity_id, limit=limit)
        self._write_audit("entity_document_ids", result, {"entity_id": entity_id, "limit": limit})
        return result

    def entity_relationships(self, entity_id, *, limit: int = 25):
        result = super().entity_relationships(entity_id, limit=limit)
        self._write_audit("entity_relationships", result, {"entity_id": entity_id, "limit": limit})
        return result

    def foundational_documents(self, entity_ids):
        result = super().foundational_documents(entity_ids)
        self._write_audit("foundational_documents", result, {"entity_ids": list(entity_ids or [])})
        return result

    def recent_documents(self, *, limit: int = 25):
        result = super().recent_documents(limit=limit)
        self._write_audit("recent_documents", result, {"limit": limit})
        return result

    def enriched_documents(self, *, limit: int = 50):
        result = super().enriched_documents(limit=limit)
        self._write_audit("enriched_documents", result, {"limit": limit})
        return result


class _RetrieverAuditContext:
    def __init__(self, retriever: AuditedRetriever, request_id: str):
        self.retriever = retriever
        self.request_id = request_id
        self.previous = ""

    def __enter__(self):
        self.previous = self.retriever._request_id()
        self.retriever._local.request_id = self.request_id
        return self.retriever

    def __exit__(self, *args):
        self.retriever._local.request_id = self.previous
        return False


class AskHTTPServer:
    """Owns the one ConversationService and its single FIFO worker."""

    def __init__(
        self,
        *,
        root_path: Path | str = Path("."),
        private_home: Path | str | None = None,
        principal: str = HTTP_PRINCIPAL,
        queue_depth: int = DEFAULT_QUEUE_DEPTH,
        service: Optional[ConversationService] = None,
        retriever: Optional[AuditedRetriever] = None,
    ):
        self.root_path = Path(root_path).resolve()
        if service is not None:
            self.service = service
            self.retriever = retriever or getattr(service, "retriever", None)
        else:
            base = ConversationService(root_path=self.root_path, private_home=private_home)
            self.retriever = retriever or AuditedRetriever(
                base.paths.index_path,
                audit_path=base.paths.home / "audit" / "retrieval.jsonl",
                principal=principal,
            )
            self.service = ConversationService(
                root_path=self.root_path,
                private_home=base.paths.home,
                retriever=self.retriever,
            )
        self.principal = principal
        self.audit_path = self.service.paths.home / "audit" / "http.jsonl"
        self.jobs: Dict[str, Job] = {}
        self._queue: "queue.Queue[str]" = queue.Queue(maxsize=max(1, int(queue_depth or 1)))
        self._condition = threading.Condition()
        self._worker = threading.Thread(target=self._run, name="gang-ask-http-worker", daemon=True)
        self._worker.start()

    @property
    def worker_count(self) -> int:
        return 1

    def enqueue(self, payload: Dict[str, Any]) -> Job:
        request_id = uuid.uuid4().hex
        job = Job(
            job_id=uuid.uuid4().hex,
            request_id=request_id,
            principal=self.principal,
            payload=payload,
        )
        with self._condition:
            self.jobs[job.job_id] = job
            try:
                self._queue.put_nowait(job.job_id)
            except queue.Full as exc:
                self.jobs.pop(job.job_id, None)
                raise QueueFullError("Ask queue is full") from exc
            self._condition.notify_all()
        return job

    def audit_auth_failure(
        self,
        *,
        request_id: str,
        reason: str,
        remote_addr: str = "",
        token_hash_prefix: str = "",
    ) -> None:
        _append_jsonl_private(
            self.audit_path,
            {
                "version": "1",
                "kind": "auth",
                "timestamp": _now(),
                "reason": reason,
                "request_id": request_id,
                "remote_addr": remote_addr,
                **({"token_hash_prefix": token_hash_prefix} if token_hash_prefix else {}),
            },
        )

    def audit_turn(
        self,
        *,
        job: Job,
        outcome: str,
        started: float,
        result: Optional[Dict[str, Any]] = None,
        error_code: str = "",
    ) -> None:
        result = result or {}
        synthesis = result.get("synthesis") if isinstance(result.get("synthesis"), dict) else {}
        intent = result.get("intent") if isinstance(result.get("intent"), dict) else {}
        sources = result.get("sources") if isinstance(result.get("sources"), list) else []
        cited_document_ids = [
            str(source.get("document_id") or "")
            for source in sources
            if isinstance(source, dict) and source.get("cited") and source.get("document_id")
        ]
        _append_jsonl_private(
            self.audit_path,
            {
                "version": "1",
                "kind": "turn",
                "timestamp": _now(),
                "request_id": job.request_id,
                "principal_id": self.principal,
                "session_id": str(job.payload.get("session_id") or result.get("session_id") or ""),
                "question": str(job.payload.get("question") or ""),
                "question_sha256": sha256_text(str(job.payload.get("question") or "")),
                "level": str(job.payload.get("level") or ""),
                "mode": str(intent.get("mode") or ""),
                "outcome": outcome,
                **({"error_code": error_code} if error_code else {}),
                "cited_document_ids": cited_document_ids,
                "provider": str(synthesis.get("provider") or ""),
                "model": str(synthesis.get("model") or ""),
                "cached": False,
                "latency_ms": int((time.monotonic() - started) * 1000),
            },
        )

    def job(self, job_id: str, *, block: float = 0.0) -> Optional[Job]:
        deadline = time.monotonic() + max(0.0, min(block, 30.0))
        with self._condition:
            while True:
                job = self.jobs.get(job_id)
                if job is None or job.status in {"succeeded", "failed", "provider-timeout"}:
                    return job
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return job
                self._condition.wait(timeout=remaining)

    def _run(self) -> None:
        while True:
            job_id = self._queue.get()
            try:
                self._execute(job_id)
            finally:
                self._queue.task_done()

    def _execute(self, job_id: str) -> None:
        started = time.monotonic()
        with self._condition:
            job = self.jobs[job_id]
            job.status = "running"
            job.updated_at = _now()
            self._condition.notify_all()

        try:
            result = self._ask(job)
        except Exception as exc:  # noqa: BLE001 - sanitized below by design
            timeout = _caused_by_timeout(exc)
            code = "provider_timeout" if timeout else "ask_failed"
            outcome = "provider-timeout" if timeout else "error"
            status = "provider-timeout" if timeout else "failed"
            message = (
                "The local AI provider timed out."
                if timeout
                else "The question could not be answered."
            )
            self.audit_turn(
                job=job,
                outcome=outcome,
                error_code=code,
                started=started,
            )
            error = {
                "code": code,
                "message": message,
                "request_id": job.request_id,
            }
            with self._condition:
                job.status = status
                job.error = error
                job.updated_at = _now()
                self._condition.notify_all()
            return

        self.audit_turn(job=job, outcome="ok", result=result, started=started)
        with self._condition:
            job.status = "succeeded"
            job.result = result
            job.updated_at = _now()
            self._condition.notify_all()

    def _ask(self, job: Job) -> Dict[str, Any]:
        payload = job.payload
        filters = payload.get("filters") or {}
        level = payload.get("level") or "normal"
        session = self.service.sessions.load_or_create(payload.get("session_id"))
        options = _options_for(level)
        overrides = _overrides(payload["question"], filters)

        retriever = self.retriever
        context = (
            retriever.bind_request(job.request_id)
            if isinstance(retriever, AuditedRetriever)
            else _NullContext()
        )
        with context:
            result = self.service.converse(
                payload["question"],
                session=session,
                overrides=overrides,
                options=options,
            )

        return _http_projection(result, request_id=job.request_id)


class _NullContext:
    def __enter__(self):
        return None

    def __exit__(self, *args):
        return False


def create_app(
    *,
    root_path: Path | str = Path("."),
    private_home: Path | str | None = None,
    bind_host: str = DEFAULT_BIND_HOST,
    auth_token: Optional[str] = None,
    token_sha256: Optional[str] = None,
    approved_tailnet_cidrs: Iterable[str] = (),
    queue_depth: int = DEFAULT_QUEUE_DEPTH,
    server: Optional[AskHTTPServer] = None,
) -> Flask:
    """Create the Flask app used by tests and the local service runner."""

    validate_bind_host(bind_host, approved_tailnet_cidrs=approved_tailnet_cidrs)
    config = AIConfig.load(root_path)
    validate_local_ollama_endpoint(config.ollama_endpoint)

    token_hash = token_sha256 or _token_hash_from_env_or_token(auth_token)
    if not token_hash:
        raise HTTPConfigError("HTTP bearer token hash is required")

    app = Flask(__name__)
    app.config["JSON_SORT_KEYS"] = True
    app.config["GANG_BIND_HOST"] = bind_host
    app.config["GANG_TOKEN_SHA256"] = token_hash
    app.config["GANG_SERVER"] = server or AskHTTPServer(
        root_path=root_path,
        private_home=private_home,
        queue_depth=queue_depth,
    )

    @app.before_request
    def _authenticate():
        if request.path == "/healthz":
            return None
        if not _authorized(request.headers.get("Authorization", ""), token_hash):
            request_id = uuid.uuid4().hex
            _server().audit_auth_failure(
                request_id=request_id,
                reason="missing-or-invalid-bearer",
                remote_addr=str(request.remote_addr or ""),
                token_hash_prefix=_token_hash_prefix(request.headers.get("Authorization", "")),
            )
            return _error(
                "unauthorized",
                "Authentication required.",
                status=401,
                request_id=request_id,
            )
        return None

    @app.errorhandler(HTTPRequestError)
    def _handle_request_error(exc: HTTPRequestError):
        return _error(exc.code, str(exc), status=exc.status)

    @app.errorhandler(SessionError)
    def _handle_session_error(exc: SessionError):
        return _error("invalid_session", "The session id is invalid or unavailable.", status=400)

    @app.errorhandler(QueryPlanError)
    def _handle_plan_error(exc: QueryPlanError):
        return _error("invalid_filters", "The retrieval filters are invalid.", status=400)

    @app.errorhandler(AskError)
    def _handle_ask_error(exc: AskError):
        return _error("ask_failed", "The question could not be answered.", status=502)

    @app.errorhandler(Exception)
    def _handle_unexpected(exc: Exception):
        if isinstance(exc, HTTPException):
            status = exc.code or 500
            code = "not_found" if status == 404 else "http_error"
            message = "No such route." if status == 404 else "The request could not be completed."
            return _error(code, message, status=status)
        return _error("internal_error", "The request could not be completed.", status=500)

    @app.get("/healthz")
    def healthz():
        return jsonify({"status": "ok"})

    @app.get("/v1/health")
    def health():
        state = _server().service
        return jsonify(
            {
                "status": "ok",
                "principal": HTTP_PRINCIPAL,
                "local_only": True,
                "worker_count": _server().worker_count,
                "session_count": len(state.sessions.list_sessions()),
            }
        )

    @app.get("/v1/whoami")
    def whoami():
        return jsonify({"principal": HTTP_PRINCIPAL, "scope": "full_corpus"})

    @app.post("/v1/ask")
    def ask():
        payload = _parse_ask_request(request.get_json(silent=True))
        try:
            job = _server().enqueue(payload)
        except QueueFullError:
            return _error(
                "queue_full",
                "Ask queue is full. Try again shortly.",
                status=429,
                headers={"Retry-After": "1"},
            )
        return jsonify(job.public()), 202

    @app.get("/v1/jobs/<job_id>")
    def get_job(job_id: str):
        job = _server().job(job_id, block=_block_seconds(request.args.get("block")))
        if job is None:
            return _error("not_found", "No such job.", status=404)
        if job.status == "provider-timeout":
            return _error(
                "provider_timeout",
                "The local AI provider timed out.",
                status=504,
                request_id=job.request_id,
            )
        return jsonify(job.public())

    @app.get("/v1/sessions")
    def sessions():
        return jsonify({"sessions": _server().service.sessions.list_sessions()})

    @app.get("/v1/sessions/<session_id>")
    def get_session(session_id: str):
        session = _server().service.sessions.load(session_id)
        return jsonify({"session": session.to_dict()})

    @app.delete("/v1/sessions/<session_id>")
    def delete_session(session_id: str):
        deleted = _server().service.sessions.delete(session_id)
        return jsonify({"deleted": deleted, "session_id": session_id})

    def _server() -> AskHTTPServer:
        return app.config["GANG_SERVER"]

    return app


def issue_token(path: Path | str) -> str:
    """Create one bearer token, store only its sha256, and return it once."""

    token = secrets.token_urlsafe(32)
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(sha256_token(token) + "\n", encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:
        pass
    return token


def sha256_token(token: str) -> str:
    return hashlib.sha256((token or "").encode("utf-8")).hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def validate_bind_host(
    host: str,
    *,
    approved_tailnet_cidrs: Iterable[str] = (),
) -> None:
    text = str(host or "").strip()
    if not text:
        raise HTTPConfigError("Bind host is required")
    if text == "localhost":
        return
    try:
        address = ipaddress.ip_address(text)
    except ValueError as exc:
        raise HTTPConfigError("Bind host must be an IP address") from exc
    if address.is_loopback:
        return
    for cidr in approved_tailnet_cidrs:
        try:
            if address in ipaddress.ip_network(str(cidr), strict=False):
                return
        except ValueError:
            continue
    raise HTTPConfigError("HTTP service may bind only to loopback or an approved tailnet address")


def validate_local_ollama_endpoint(endpoint: str) -> None:
    parsed = urlparse(str(endpoint or ""))
    if parsed.scheme not in {"http", "https"}:
        raise HTTPConfigError("Ollama endpoint must be http(s)")
    if parsed.username or parsed.password:
        raise HTTPConfigError("Ollama endpoint credentials are not allowed")
    host = parsed.hostname or ""
    if host not in {"127.0.0.1", "localhost"}:
        raise HTTPConfigError("HTTP service may use only a local loopback Ollama endpoint")


def _parse_ask_request(value: Any) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise HTTPRequestError("invalid_json", "Request body must be a JSON object.")
    unknown = set(value) - REQUEST_FIELDS
    sensitive = unknown & SENSITIVE_CONTROL_FIELDS
    if unknown:
        code = "control_field_rejected" if sensitive else "unsupported_field"
        raise HTTPRequestError(code, "Request contains unsupported fields.")
    question = str(value.get("question") or "").strip()
    if not question:
        raise HTTPRequestError("invalid_question", "Question is required.")
    level = str(value.get("level") or "normal").strip().lower()
    if level not in LEVELS:
        raise HTTPRequestError("invalid_level", "Level must be fast or normal.")
    session_id = value.get("session_id")
    if session_id is not None and not isinstance(session_id, str):
        raise HTTPRequestError("invalid_session", "Session id must be a string.")
    filters = value.get("filters") or {}
    if not isinstance(filters, dict):
        raise HTTPRequestError("invalid_filters", "Filters must be an object.")
    unknown_filters = set(filters) - FILTER_FIELDS
    if unknown_filters:
        raise HTTPRequestError("unsupported_filter", "Request contains unsupported filters.")
    _validate_filters(question, filters)
    return {
        "question": question,
        "session_id": session_id,
        "level": level,
        "filters": filters,
    }


def _validate_filters(question: str, filters: Dict[str, Any]) -> None:
    date_range = filters.get("date_range")
    payload = {
        "version": "1",
        "query": question,
        "document_types": filters.get("document_types"),
        "source_types": filters.get("source_types"),
        "visibility": filters.get("visibility"),
        "date_range": date_range,
        "entity_ids": filters.get("entity_ids"),
        "order": filters.get("order"),
        "limit": filters.get("limit", DEFAULT_LIMIT),
    }
    validate_plan(payload)


def _overrides(question: str, filters: Dict[str, Any]) -> PlanOverrides:
    date_range = filters.get("date_range") if isinstance(filters.get("date_range"), dict) else {}
    limit = filters.get("limit", DEFAULT_LIMIT)
    try:
        parsed_limit = int(limit)
    except (TypeError, ValueError):
        parsed_limit = DEFAULT_LIMIT
    return PlanOverrides(
        since=str(date_range.get("start") or ""),
        until=str(date_range.get("end") or ""),
        document_types=list(filters.get("document_types") or []),
        source_types=list(filters.get("source_types") or []),
        entity_ids=list(filters.get("entity_ids") or []),
        visibility=filters.get("visibility"),
        order=filters.get("order"),
        limit=max(1, min(parsed_limit, MAX_LIMIT)),
    )


def _options_for(level: str) -> ConversationOptions:
    if level == "fast":
        return ConversationOptions(
            use_ai=False,
            use_cache=False,
            persist=True,
            premium=False,
            local_only=True,
            mode_override=None,
        )
    return ConversationOptions(
        use_ai=True,
        use_cache=False,
        persist=True,
        provider="ollama",
        model=HTTP_LOCAL_MODEL,
        premium=False,
        local_only=True,
        mode_override=None,
    )


def _http_projection(result: Dict[str, Any], *, request_id: str) -> Dict[str, Any]:
    clean = {key: value for key, value in result.items() if key not in HTTP_RESULT_DROP_FIELDS}
    research = clean.get("research")
    if isinstance(research, dict):
        clean["research"] = {key: value for key, value in research.items() if key != "provider_calls"}
    synthesis = clean.get("synthesis")
    if isinstance(synthesis, dict):
        clean["synthesis"] = {
            key: value
            for key, value in synthesis.items()
            if key not in {"endpoint", "error"}
        }
    clean["request_id"] = request_id
    return clean


def _authorized(header: str, token_hash: str) -> bool:
    prefix = "Bearer "
    if not header.startswith(prefix):
        return False
    supplied = sha256_token(header[len(prefix) :])
    return hmac.compare_digest(supplied, token_hash)


def _token_hash_from_env_or_token(token: Optional[str]) -> str:
    from_env = str(os.environ.get(TOKEN_HASH_ENV) or "").strip()
    if from_env:
        return from_env
    return sha256_token(token) if token else ""


def _error(
    code: str,
    message: str,
    *,
    status: int,
    request_id: Optional[str] = None,
    headers: Optional[Dict[str, str]] = None,
) -> tuple[Response, int] | tuple[Response, int, Dict[str, str]]:
    response = jsonify(
        {"error": {"code": code, "message": message, "request_id": request_id or uuid.uuid4().hex}}
    )
    if headers:
        return response, status, headers
    return response, status


def _token_hash_prefix(header: str) -> str:
    prefix = "Bearer "
    if not header.startswith(prefix):
        return ""
    return sha256_token(header[len(prefix) :])[:12]


def _caused_by_timeout(exc: BaseException) -> bool:
    current: Optional[BaseException] = exc
    while current is not None:
        if isinstance(current, ProviderTimeoutError):
            return True
        current = current.__cause__
    return False


def _append_jsonl_private(path: Path | str, record: Dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    opened = False
    try:
        try:
            os.chmod(target, 0o600)
        except OSError:
            pass
        opened = True
        with os.fdopen(descriptor, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True, default=str) + "\n")
    except Exception:
        if not opened:
            os.close(descriptor)
        raise


def _block_seconds(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _now(clock: Optional[Any] = None) -> str:
    if clock is not None:
        return clock().isoformat(timespec="seconds")
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _safe_arguments(arguments: Dict[str, Any]) -> Dict[str, Any]:
    safe = dict(arguments)
    plan = safe.get("plan")
    if isinstance(plan, dict):
        safe["plan"] = {
            key: value
            for key, value in plan.items()
            if key
            in {
                "version",
                "query",
                "text_queries",
                "entity_ids",
                "relationship_filters",
                "document_types",
                "source_types",
                "visibility",
                "date_range",
                "enrichment_status",
                "order",
                "limit",
            }
        }
    return safe


def _result_summary(result: Any) -> Dict[str, Any]:
    if isinstance(result, list):
        return {
            "count": len(result),
            "document_ids": [
                str(item.get("document_id") or "")
                for item in result
                if isinstance(item, dict) and item.get("document_id")
            ][:50],
        }
    if isinstance(result, dict):
        return {
            "count": len(result),
            "document_ids": [
                str(key)
                for key, value in result.items()
                if key and (str(key).startswith("01") or isinstance(value, str))
            ][:50],
        }
    return {"count": 1 if result is not None else 0}
