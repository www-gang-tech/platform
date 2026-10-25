"""The single AI provider boundary for GANG.

Every AI-assisted feature — enrichment proposals, entity proposals, and ``gang
ask`` synthesis — calls the provider through this module. Exactly one file
imports remote provider SDKs, talks to local Ollama, and turns a response body
into a JSON object, so there is one place to audit for credential handling,
model selection, endpoint selection, and response parsing.

Two rules hold for every caller:

* Remote API keys are read from the environment and never travel in a prompt, a
  log line, an audit record, or an exception message.
* Retrieved corpus content is always DATA in a user message. Callers build the
  system prompt from constants they own; nothing read out of the vault is ever
  promoted into system or developer position.

A third rule belongs to the callers, with a backstop here. Restricted and
local-only documents (``core.sensitivity``) are filtered out before a remote
context is built. This module does not filter anything; it refuses. A request
bound for a remote endpoint that still carries a strongly structured sensitive
identifier is never sent, because reaching that point means a filter upstream
was missed, and the only safe response to a missed filter is not to transmit.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from core import sensitivity


#: Model used by the proposal flows (enrichment, entity resolution).
DEFAULT_MODEL = "claude-sonnet-4-6"

#: Local model used by ordinary Ask. GANG's bounded retrieval means the model
#: sees small evidence sets rather than the whole private corpus.
DEFAULT_LOCAL_MODEL = "mistral-small3.1"

#: Premium remote model, used only after an explicit Ask escalation.
DEFAULT_PREMIUM_MODEL = "claude-opus-5"

#: Backwards-compatible name used by older Ask classes.
DEFAULT_SYNTHESIS_MODEL = DEFAULT_PREMIUM_MODEL

DEFAULT_OLLAMA_ENDPOINT = "http://127.0.0.1:11434"
LOCAL_PROVIDERS = {"ollama"}
REMOTE_PROVIDERS = {"anthropic"}
ASK_ROLES = {"default", "planning", "research", "synthesis"}
DEFAULT_OLLAMA_TIMEOUT_SECONDS = 180.0

API_KEY_ENV = "ANTHROPIC_API_KEY"

class ProviderError(Exception):
    """Raised when the configured AI provider cannot produce a response.

    Feature modules re-wrap this in their own error type so their public API is
    unchanged.
    """


class ProviderTimeoutError(ProviderError):
    """Raised when a provider call reaches its configured timeout."""


class SensitiveEgressError(ProviderError):
    """Raised instead of sending a remote request that carries a sensitive identifier."""


def is_remote_provider(provider: Any) -> bool:
    """Whether text handed to ``provider`` leaves this machine.

    Clients and the Ask wrappers answer through ``is_remote``. Anything that
    does not say is judged by its provider name, and a name this module does
    not know as local is remote: a boundary that has to guess guesses closed.
    """
    declared = getattr(provider, "is_remote", None)
    if isinstance(declared, bool):
        return declared
    return str(getattr(provider, "provider_name", "") or "") not in LOCAL_PROVIDERS


def is_loopback_endpoint(endpoint: str) -> bool:
    """Whether ``endpoint`` names this machine.

    A hostname that merely begins with ``127.`` (``127.0.0.1.example``) is a
    DNS name, not the loopback network. Only ``localhost`` and an address
    ``ipaddress`` accepts as loopback count, including an IPv4-mapped loopback.
    Anything else is remote, so sensitive evidence is kept off it.
    """
    raw = endpoint if "://" in str(endpoint or "") else f"http://{endpoint}"
    host = (urlparse(raw).hostname or "").strip().lower().rstrip(".")
    if host == "localhost":
        return True
    host = host.split("%", 1)[0]
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    mapped = getattr(address, "ipv4_mapped", None)
    if mapped is not None:
        address = mapped
    return bool(address.is_loopback)


def refuse_sensitive_egress(request: Dict[str, Any], *, purpose: str, provider: str) -> None:
    """Refuse a remote request that still carries a sensitive identifier.

    A backstop, not the filter. It names the detectors that fired and never
    the values, so the refusal is as safe to log as the request was not.
    """
    detectors = sensitivity.contains_sensitive_identifier(_request_text(request))
    if detectors:
        raise SensitiveEgressError(
            f"Refused to send {purpose} to remote provider {provider}: the request contains "
            f"sensitive identifiers ({', '.join(sorted(set(detectors)))}). Restricted and "
            "local-only evidence must be filtered out before a remote context is built. "
            "Nothing was sent."
        )


def _request_text(request: Dict[str, Any]) -> str:
    parts: List[str] = [str(request.get("system") or "")]
    for message in request.get("messages") or []:
        content = message.get("content") if isinstance(message, dict) else message
        if isinstance(content, list):
            parts.extend(
                str(block.get("text") or "") if isinstance(block, dict) else str(block)
                for block in content
            )
        else:
            parts.append(str(content or ""))
    return "\n".join(parts)


@dataclass(frozen=True)
class RoleConfig:
    provider: str
    model: str


@dataclass(frozen=True)
class ModelBudget:
    max_context_tokens: int = 32768
    max_prompt_chars: int = 120000


@dataclass(frozen=True)
class SynthesisPacketBudget:
    """What local synthesis is allowed to spend on one answer.

    ``think`` is off by default. A reasoning model spends its thinking inside
    the same generation budget, and on the real corpus that meant hundreds of
    tokens of deliberation before a four-sentence answer — the single largest
    contributor to local latency. The evidence packet is already small and
    ranked, so the deliberation is buying much less than it costs here.
    """

    max_prompt_tokens: int = 3500
    max_evidence_tokens: int = 2500
    max_documents: int = 4
    max_excerpts_per_document: int = 2
    max_output_tokens: int = 500
    max_excerpt_chars: int = 260
    think: bool = False


@dataclass(frozen=True)
class AIConfig:
    """Centralized AI routing configuration.

    The repository still has legacy flat ``ai.provider`` settings for content
    optimization. Ask only reads the nested role settings below so adding local
    Ask does not unexpectedly repoint older enrichment jobs.
    """

    roles: Dict[str, RoleConfig]
    premium: RoleConfig
    ollama_endpoint: str = DEFAULT_OLLAMA_ENDPOINT
    ollama_timeout_seconds: float = DEFAULT_OLLAMA_TIMEOUT_SECONDS
    local_only: bool = False
    budgets: Dict[str, ModelBudget] | None = None
    local_synthesis_budget: SynthesisPacketBudget = SynthesisPacketBudget()

    @classmethod
    def load(cls, root_path: Path | str | None = None) -> "AIConfig":
        data: Dict[str, Any] = {}
        config_path = Path(root_path or ".").resolve() / "gang.config.yml"
        if config_path.exists():
            try:
                import yaml

                loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
                data = loaded if isinstance(loaded, dict) else {}
            except Exception:
                data = {}
        return cls.from_mapping(data.get("ai") if isinstance(data.get("ai"), dict) else {})

    @classmethod
    def from_mapping(cls, ai: Dict[str, Any]) -> "AIConfig":
        roles = {
            role: _role_config(ai.get(role), fallback=RoleConfig("ollama", DEFAULT_LOCAL_MODEL))
            for role in ASK_ROLES
        }
        default = roles["default"]
        for role in ASK_ROLES - {"default"}:
            if role not in ai:
                roles[role] = default

        premium = _role_config(
            ai.get("premium"), fallback=RoleConfig("anthropic", DEFAULT_PREMIUM_MODEL)
        )
        ollama = ai.get("ollama") if isinstance(ai.get("ollama"), dict) else {}
        endpoint = (
            os.environ.get("GANG_OLLAMA_ENDPOINT")
            or str(ollama.get("endpoint") or DEFAULT_OLLAMA_ENDPOINT)
        )
        timeout = _float(
            os.environ.get("GANG_OLLAMA_TIMEOUT_SECONDS")
            or ollama.get("timeout_seconds")
            or ollama.get("timeout"),
            DEFAULT_OLLAMA_TIMEOUT_SECONDS,
            1.0,
            1800.0,
        )
        budgets = {
            role: _budget(ai.get("input_budget") or ai.get("budgets") or {}, role)
            for role in ASK_ROLES
        }
        packet_budget = _synthesis_packet_budget(
            ai.get("local_synthesis") or ai.get("synthesis_packet") or {}
        )
        return cls(
            roles=roles,
            premium=premium,
            ollama_endpoint=endpoint.rstrip("/"),
            ollama_timeout_seconds=timeout,
            local_only=_truthy(os.environ.get("GANG_LOCAL_ONLY", ai.get("local_only", False))),
            budgets=budgets,
            local_synthesis_budget=packet_budget,
        )

    def select(
        self,
        role: str,
        *,
        premium: bool = False,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        local_only: Optional[bool] = None,
    ) -> RoleConfig:
        selected = self.premium if premium else self.roles.get(role, self.roles["default"])
        env_provider = os.environ.get(f"GANG_{role.upper()}_PROVIDER") or os.environ.get(
            "GANG_ASK_PROVIDER"
        )
        env_model = os.environ.get(f"GANG_{role.upper()}_MODEL") or os.environ.get("GANG_ASK_MODEL")
        provider_override = provider or env_provider
        provider_name = _provider(provider_override or selected.provider)
        model_default = selected.model
        if provider_override and provider_name != selected.provider and not (model or env_model):
            model_default = DEFAULT_LOCAL_MODEL if provider_name == "ollama" else DEFAULT_PREMIUM_MODEL
        model_name = str(model or env_model or model_default or "").strip()
        if not model_name:
            model_name = DEFAULT_LOCAL_MODEL if provider_name == "ollama" else DEFAULT_PREMIUM_MODEL

        strict_local = self.local_only if local_only is None else bool(local_only)
        if strict_local and provider_name in REMOTE_PROVIDERS:
            raise ProviderError(
                "local_only is enabled, so remote AI providers are disabled. "
                "Use the local Ollama provider or disable local_only deliberately."
            )
        return RoleConfig(provider=provider_name, model=model_name)

    def budget_for(self, role: str) -> ModelBudget:
        return (self.budgets or {}).get(role, ModelBudget())


class ConfiguredAIClient:
    """Routes one model role to Ollama or Anthropic without fallback."""

    def __init__(
        self,
        *,
        role: str = "default",
        root_path: Path | str | None = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        premium: bool = False,
        api_key: Optional[str] = None,
        local_only: Optional[bool] = None,
        config: Optional[AIConfig] = None,
    ):
        self.config = config or AIConfig.load(root_path)
        if api_key is not None and provider is None:
            provider = "anthropic"
        selected = self.config.select(
            role, premium=premium, provider=provider, model=model, local_only=local_only
        )
        self.provider_name = selected.provider
        self.model = selected.model
        self.role = role
        self._budget = self.config.budget_for(role)
        if selected.provider == "anthropic":
            self._client = AnthropicClient(model=selected.model, api_key=api_key)
        elif selected.provider == "ollama":
            self._client = OllamaClient(
                model=selected.model,
                endpoint=self.config.ollama_endpoint,
                timeout=self.config.ollama_timeout_seconds,
                budget=self._budget,
            )
        else:
            raise ProviderError(f"Unsupported AI provider: {selected.provider}")

    @property
    def has_credentials(self) -> bool:
        return self._client.has_credentials

    @property
    def endpoint(self) -> str:
        return getattr(self._client, "endpoint", "")

    @property
    def is_remote(self) -> bool:
        return self._client.is_remote

    @property
    def telemetry(self) -> Dict[str, Any]:
        return getattr(self._client, "telemetry", {})

    @property
    def local_synthesis_budget(self) -> SynthesisPacketBudget:
        return self.config.local_synthesis_budget

    def complete_json(self, request: Dict[str, Any], *, purpose: str) -> Dict[str, Any]:
        return self._client.complete_json(request, purpose=purpose)


class AnthropicClient:
    """Narrow wrapper over ``anthropic.Anthropic`` that returns JSON objects."""

    provider_name = "anthropic"
    is_remote = True

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        default_model: str = DEFAULT_MODEL,
    ):
        self.model = model or default_model
        self.api_key = api_key or os.environ.get(API_KEY_ENV)
        self.telemetry: Dict[str, Any] = {}

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key)

    def complete_json(self, request: Dict[str, Any], *, purpose: str) -> Dict[str, Any]:
        """Send one request and parse the reply as a JSON object.

        ``request`` carries ``system``, ``messages``, and ``max_tokens``. The
        credential is never included in the error text raised from here.
        """
        refuse_sensitive_egress(request, purpose=purpose, provider=self.provider_name)
        if not self.api_key:
            raise ProviderError(f"{API_KEY_ENV} is required for {purpose}")

        try:
            import anthropic
        except ImportError as exc:
            raise ProviderError(f"anthropic package is required for {purpose}") from exc

        client = anthropic.Anthropic(api_key=self.api_key)
        started = time.monotonic()
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=request["max_tokens"],
                system=request["system"],
                messages=request["messages"],
            )
        except Exception as exc:
            self.telemetry = {
                "provider": self.provider_name,
                "model": self.model,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "status": "failed",
                "error": _redact(exc),
            }
            raise ProviderError(f"AI provider request failed: {_redact(exc)}") from exc
        else:
            self.telemetry = {
                "provider": self.provider_name,
                "model": self.model,
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "status": "ok",
            }

        return load_json_object(response_text(response))


class OllamaClient:
    """Local Ollama HTTP client that returns JSON objects."""

    provider_name = "ollama"

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        endpoint: str = DEFAULT_OLLAMA_ENDPOINT,
        timeout: float = DEFAULT_OLLAMA_TIMEOUT_SECONDS,
        budget: Optional[ModelBudget] = None,
    ):
        self.model = model or DEFAULT_LOCAL_MODEL
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.budget = budget or ModelBudget()
        self.telemetry: Dict[str, Any] = {}

    @property
    def has_credentials(self) -> bool:
        return True

    @property
    def is_remote(self) -> bool:
        """An Ollama server on another host is a remote provider.

        The provider name says nothing about where the text goes. An endpoint
        pointed at a LAN box or a hosted GPU is exactly as remote as Anthropic
        for the purposes of sensitive evidence.
        """
        return not is_loopback_endpoint(self.endpoint)

    def complete_json(self, request: Dict[str, Any], *, purpose: str) -> Dict[str, Any]:
        if self.is_remote:
            refuse_sensitive_egress(request, purpose=purpose, provider=f"ollama at {self.endpoint}")
        messages = [{"role": "system", "content": request["system"]}]
        messages.extend(request.get("messages") or [])
        # A caller that knows the shape it wants sends a JSON Schema, and
        # Ollama constrains decoding to it. "json" alone only promises the
        # response will parse, not that it will contain anything in particular.
        response_format = request.get("format")
        if not isinstance(response_format, dict) or not response_format:
            response_format = "json"
        payload: Dict[str, Any] = {
            "model": self.model,
            "stream": False,
            "messages": messages,
            "format": response_format,
            "options": {
                "num_ctx": self.budget.max_context_tokens,
                "num_predict": _int(request.get("max_tokens"), 500, 128, 4000),
            },
        }
        if "think" in request:
            payload["think"] = bool(request["think"])
        started = time.monotonic()
        try:
            try:
                body = _post_json(f"{self.endpoint}/api/chat", payload, timeout=self.timeout)
            except ProviderError as exc:
                # An older Ollama, or a model with no thinking mode, rejects the
                # field outright. Losing the whole answer over a latency knob
                # would be the wrong trade, so retry once without it.
                if "think" not in payload or not _rejects_thinking(exc):
                    raise
                payload.pop("think")
                body = _post_json(f"{self.endpoint}/api/chat", payload, timeout=self.timeout)
        except ProviderError as exc:
            elapsed = round(time.monotonic() - started, 3)
            self.telemetry = {
                "provider": self.provider_name,
                "model": self.model,
                "endpoint": self.endpoint,
                "timeout_seconds": self.timeout,
                "elapsed_seconds": elapsed,
                "status": "timeout" if isinstance(exc, ProviderTimeoutError) else "failed",
                "error": str(exc),
            }
            raise
        elapsed = round(time.monotonic() - started, 3)
        self.telemetry = {
            "provider": self.provider_name,
            "model": self.model,
            "endpoint": self.endpoint,
            "timeout_seconds": self.timeout,
            "elapsed_seconds": elapsed,
            "status": "ok",
        }
        self.telemetry.update(_ollama_telemetry(body))
        content = ""
        if isinstance(body.get("message"), dict):
            content = str(body["message"].get("content") or "")
        if not content and isinstance(body.get("response"), str):
            content = body["response"]
        if not content:
            self.telemetry.update({"status": "failed", "error": f"Ollama did not return text for {purpose}"})
            raise ProviderError(f"Ollama did not return text for {purpose}")
        try:
            return load_json_object(content)
        except ProviderError as exc:
            # Constrained decoding will happily spend the whole generation
            # budget and stop mid-object. The text before the cut is real
            # model output, so it is closed off and parsed rather than thrown
            # away — a partial answer the ledger can still check beats no
            # answer, and the repair is recorded either way.
            if body.get("done_reason") == "length":
                repaired = repair_truncated_json(content)
                if repaired is not None:
                    self.telemetry.update({"status": "ok", "response": "truncated-repaired"})
                    return repaired
                self.telemetry.update({"status": "failed", "response": "truncated", "error": str(exc)})
                raise ProviderError(
                    "The local model ran out of output budget mid-response and what it "
                    "produced could not be repaired. Raise ai.local_synthesis.max_output_tokens "
                    "or ask a narrower question."
                ) from exc
            self.telemetry.update({"status": "failed", "error": str(exc)})
            raise

    def model_available(self) -> Optional[bool]:
        try:
            body = _get_json(f"{self.endpoint}/api/tags", timeout=5)
        except ProviderError:
            return None
        models = body.get("models") if isinstance(body, dict) else []
        names = {str(item.get("name") or "").split(":")[0] for item in models if isinstance(item, dict)}
        full_names = {str(item.get("name") or "") for item in models if isinstance(item, dict)}
        return self.model in names or self.model in full_names


def ai_status(root_path: Path | str | None = None) -> Dict[str, Any]:
    """Report Ask provider status without sending private corpus content."""
    config = AIConfig.load(root_path)
    selected = config.select("default")
    status: Dict[str, Any] = {
        "default_provider": selected.provider,
        "model": selected.model,
        "remote_fallback": "disabled",
        "local_only": config.local_only,
        "api_cost": "$0" if selected.provider in LOCAL_PROVIDERS else "remote provider",
    }
    if selected.provider == "ollama":
        client = OllamaClient(
            model=selected.model,
            endpoint=config.ollama_endpoint,
            timeout=config.ollama_timeout_seconds,
        )
        status["endpoint"] = client.endpoint
        status["timeout_seconds"] = client.timeout
        available = client.model_available()
        status["reachable"] = available is not None
        status["model_available"] = bool(available)
    else:
        client = AnthropicClient(model=selected.model)
        status["has_credentials"] = client.has_credentials
    return status


def response_text(response: Any) -> str:
    """Concatenate the text blocks of a response, skipping the rest.

    A response may open with a thinking block, and on current models often
    does. Indexing ``content[0]`` assumes the first block is text and raises
    ``AttributeError`` when it is not, so walk the blocks and take the text.
    """
    parts = [
        block.text
        for block in (getattr(response, "content", None) or [])
        if getattr(block, "type", None) == "text" and isinstance(getattr(block, "text", None), str)
    ]
    return "".join(parts) or "{}"


def load_json_object(text: str) -> Dict[str, Any]:
    """Parse a provider reply that should be a single JSON object."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            raise ProviderError("AI provider did not return JSON")
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise ProviderError("AI provider did not return JSON") from exc
    if not isinstance(data, dict):
        raise ProviderError("AI provider did not return a JSON object")
    return data


def repair_truncated_json(text: str) -> Optional[Dict[str, Any]]:
    """Close off a JSON object that was cut off mid-write, or return None.

    Deterministic and additive only. The function never edits a character the
    model wrote: it rewinds to the last point where a value had finished, drops
    the unfinished fragment after it, and appends the closing delimiters the
    surrounding structure already implies. If no rewind point yields valid
    JSON it gives up rather than guessing at content.
    """
    value = (text or "").strip()
    start = value.find("{")
    if start < 0:
        return None
    value = value[start:]

    points = _safe_points(value)
    if points is None:
        return None
    for position, closers in reversed(points[-MAX_REPAIR_ATTEMPTS:]):
        candidate = value[:position].rstrip().rstrip(",")
        candidate = _drop_dangling_key(candidate) + closers
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


#: How far back to rewind looking for a parseable prefix. Well past the tail
#: of any truncated claim, and short of rewriting the response.
MAX_REPAIR_ATTEMPTS = 40


def _safe_points(value: str) -> Optional[List[tuple]]:
    """Positions where a value had just finished, with the closers still owed.

    Returns ``None`` when the text is not a truncated object at all — either
    the brackets are inconsistent, or the object closed and the parse failure
    was something this function has no business repairing.
    """
    points: List[tuple] = []
    stack: List[str] = []
    in_string = False
    escaped = False

    def owed() -> str:
        return "".join(reversed(stack))

    for position, character in enumerate(value):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
                points.append((position + 1, owed()))
            continue
        if character == '"':
            in_string = True
        elif character in "{[":
            stack.append("}" if character == "{" else "]")
        elif character in "}]":
            if not stack or stack[-1] != character:
                return None
            stack.pop()
            if not stack:
                return None
            points.append((position + 1, owed()))
        elif character in ",:" or character.isspace():
            continue
        else:
            end = _scalar_end(value, position)
            if end:
                points.append((end, owed()))
    return points if stack else None


def _scalar_end(value: str, position: int) -> int:
    """Where the literal starting at ``position`` ends, if it is complete."""
    match = _JSON_SCALAR.match(value, position)
    if match is None:
        return 0
    end = match.end()
    # A literal running to the very end may itself be truncated ("tru", "12").
    return end if end < len(value) else 0


_JSON_SCALAR = re.compile(r"true|false|null|-?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?")


def _drop_dangling_key(candidate: str) -> str:
    """Remove a key whose value never arrived."""
    stripped = candidate.rstrip()
    if stripped.endswith(":"):
        stripped = stripped[:-1].rstrip()
    else:
        return stripped
    match = re.search(r'"(?:[^"\\\\]|\\\\.)*"$', stripped)
    if match:
        stripped = stripped[: match.start()].rstrip().rstrip(",")
    return stripped


def _redact(exc: Exception) -> str:
    """Strip anything key-shaped out of provider error text before surfacing it."""
    return re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-***", str(exc))


def _post_json(url: str, payload: Dict[str, Any], *, timeout: float) -> Dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return _open_json(request, timeout=timeout)


def _get_json(url: str, *, timeout: float) -> Dict[str, Any]:
    request = urllib.request.Request(url, method="GET")
    return _open_json(request, timeout=timeout)


class _RefuseRedirectHandler(urllib.request.HTTPRedirectHandler):
    """A loopback Ollama must not be talked into forwarding the request."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ProviderError(
            "Refused to follow an Ollama redirect. The request stays on the configured endpoint."
        )


def _safe_opener() -> urllib.request.OpenerDirector:
    # An empty proxy map ignores HTTP_PROXY / HTTPS_PROXY. The default opener
    # would send the evidence packet to whichever proxy the environment names.
    return urllib.request.build_opener(_RefuseRedirectHandler, urllib.request.ProxyHandler({}))


_SAFE_OPENER = _safe_opener()
_REAL_URLOPEN = urllib.request.urlopen


def _urlopen(request: urllib.request.Request, timeout: float):
    """Open one Ollama request.

    Tests replace ``urllib.request.urlopen`` with a fake that records the
    request. Honor that replacement. The process opener never follows a
    redirect and never consults environment proxies, so a loopback endpoint
    cannot be turned into an outbound send.
    """
    current = urllib.request.urlopen
    if current is not _REAL_URLOPEN:
        return current(request, timeout=timeout)
    return _SAFE_OPENER.open(request, timeout=timeout)


def _open_json(request: urllib.request.Request, *, timeout: float) -> Dict[str, Any]:
    try:
        with _urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8") or "{}")
    except (TimeoutError, socket.timeout) as exc:
        raise ProviderTimeoutError(_ollama_help(str(exc))) from exc
    except urllib.error.URLError as exc:
        if _is_timeout_error(exc):
            raise ProviderTimeoutError(_ollama_help(str(exc))) from exc
        raise ProviderError(_ollama_help(str(exc))) from exc
    except json.JSONDecodeError as exc:
        raise ProviderError("Ollama returned malformed JSON") from exc
    if not isinstance(data, dict):
        raise ProviderError("Ollama returned a non-object response")
    if data.get("error"):
        raise ProviderError(_ollama_help(str(data["error"])))
    return data


def _ollama_help(detail: str) -> str:
    return (
        f"Ollama is unavailable or could not serve the configured model: {detail}. "
        "Start Ollama locally and run `ollama pull mistral-small3.1`, or choose "
        "another local model with `--provider ollama --model <name>`. No remote "
        "fallback was used."
    )


def _rejects_thinking(exc: Exception) -> bool:
    """Whether the server refused the request because of the ``think`` field."""
    return "think" in str(exc).lower()


def _is_timeout_error(exc: Exception) -> bool:
    reason = getattr(exc, "reason", None)
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return True
    return "timed out" in str(exc).lower() or "timeout" in str(exc).lower()


def _ollama_telemetry(body: Dict[str, Any]) -> Dict[str, Any]:
    telemetry: Dict[str, Any] = {}
    for source, target in (
        ("prompt_eval_count", "prompt_token_count"),
        ("eval_count", "generated_token_count"),
    ):
        value = body.get(source)
        if isinstance(value, int):
            telemetry[target] = value
    for source, target in (
        ("prompt_eval_duration", "prompt_eval_duration_seconds"),
        ("eval_duration", "generation_duration_seconds"),
        ("load_duration", "model_load_duration_seconds"),
        ("total_duration", "total_duration_seconds"),
    ):
        value = body.get(source)
        if isinstance(value, (int, float)):
            telemetry[target] = round(float(value) / 1_000_000_000, 3)
    return telemetry


def _role_config(value: Any, *, fallback: RoleConfig) -> RoleConfig:
    if not isinstance(value, dict):
        return fallback
    return RoleConfig(
        provider=_provider(value.get("provider") or fallback.provider),
        model=str(value.get("model") or fallback.model),
    )


def _budget(value: Any, role: str) -> ModelBudget:
    if isinstance(value, dict) and isinstance(value.get(role), dict):
        value = value[role]
    if not isinstance(value, dict):
        value = {}
    return ModelBudget(
        max_context_tokens=_int(value.get("max_context_tokens"), 32768, 4096, 65536),
        max_prompt_chars=_int(value.get("max_prompt_chars"), 120000, 20000, 250000),
    )


def _synthesis_packet_budget(value: Any) -> SynthesisPacketBudget:
    if not isinstance(value, dict):
        value = {}
    return SynthesisPacketBudget(
        max_prompt_tokens=_int(value.get("max_prompt_tokens"), 3500, 1000, 20000),
        max_evidence_tokens=_int(value.get("max_evidence_tokens"), 2500, 500, 15000),
        max_documents=_int(value.get("max_documents"), 4, 1, 20),
        max_excerpts_per_document=_int(value.get("max_excerpts_per_document"), 2, 1, 6),
        max_output_tokens=_int(value.get("max_output_tokens"), 500, 128, 4000),
        max_excerpt_chars=_int(value.get("max_excerpt_chars"), 260, 120, 1000),
        think=_truthy(value.get("think", False)),
    )


def _provider(value: Any) -> str:
    provider = str(value or "ollama").strip().lower()
    return provider


def _truthy(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _int(value: Any, default: int, lower: int, upper: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(lower, min(upper, parsed))


def _float(value: Any, default: float, lower: float, upper: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(lower, min(upper, parsed))
