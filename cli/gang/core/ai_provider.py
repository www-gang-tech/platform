"""The single Anthropic boundary for GANG.

Every AI-assisted feature — enrichment proposals, entity proposals, and ``gang
ask`` synthesis — calls the provider through this module. Exactly one file
imports ``anthropic``, constructs a client, and turns a response body into a
JSON object, so there is one place to audit for credential handling, model
selection, and response parsing.

Two rules hold for every caller:

* The API key is read from the environment and never travels in a prompt, a
  log line, an audit record, or an exception message.
* Retrieved corpus content is always DATA in a user message. Callers build the
  system prompt from constants they own; nothing read out of the vault is ever
  promoted into system or developer position.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Optional


#: Model used by the proposal flows (enrichment, entity resolution).
DEFAULT_MODEL = "claude-sonnet-4-6"

#: Model used for evidence-grounded answer synthesis, which benefits from the
#: strongest available reasoning. Override per call or via ``GANG_ASK_MODEL``.
DEFAULT_SYNTHESIS_MODEL = "claude-opus-5"

API_KEY_ENV = "ANTHROPIC_API_KEY"


class ProviderError(Exception):
    """Raised when the configured AI provider cannot produce a response.

    Feature modules re-wrap this in their own error type so their public API is
    unchanged.
    """


class AnthropicClient:
    """Narrow wrapper over ``anthropic.Anthropic`` that returns JSON objects."""

    provider_name = "anthropic"

    def __init__(
        self,
        *,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        default_model: str = DEFAULT_MODEL,
    ):
        self.model = model or default_model
        self.api_key = api_key or os.environ.get(API_KEY_ENV)

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key)

    def complete_json(self, request: Dict[str, Any], *, purpose: str) -> Dict[str, Any]:
        """Send one request and parse the reply as a JSON object.

        ``request`` carries ``system``, ``messages``, and ``max_tokens``. The
        credential is never included in the error text raised from here.
        """
        if not self.api_key:
            raise ProviderError(f"{API_KEY_ENV} is required for {purpose}")

        try:
            import anthropic
        except ImportError as exc:
            raise ProviderError(f"anthropic package is required for {purpose}") from exc

        client = anthropic.Anthropic(api_key=self.api_key)
        try:
            response = client.messages.create(
                model=self.model,
                max_tokens=request["max_tokens"],
                system=request["system"],
                messages=request["messages"],
            )
        except Exception as exc:
            raise ProviderError(f"AI provider request failed: {_redact(exc)}") from exc

        return load_json_object(response_text(response))


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


def _redact(exc: Exception) -> str:
    """Strip anything key-shaped out of provider error text before surfacing it."""
    return re.sub(r"sk-[A-Za-z0-9_\-]{8,}", "sk-***", str(exc))
