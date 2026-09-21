"""The shape of a synthesis response, declared once and enforced twice.

The local path used to ask for a shape in prose and hope. What came back was
usually right and occasionally not: a missing ``claims`` array, a citation
written as ``"[3]"`` instead of ``3``, a claim whose ``type`` was a sentence.
Every one of those was handled downstream by another hand-written coercion,
and the coercions were becoming the system.

So the shape is a Pydantic model, used at both ends of the same call:

* **Going out**, ``answer_schema(mode)`` is the JSON Schema handed to Ollama's
  structured-output ``format``. Constrained decoding then makes most malformed
  responses unrepresentable rather than merely detectable.
* **Coming back**, ``parse_answer`` validates and normalizes the response
  against the same model, so the rest of Ask receives one known shape.

What this layer does *not* do is judge anything. Types are declared here;
whether a claim declaring ``fact`` has earned it is the claim ledger's
question, and this module never answers it. Validation failure is reported,
not repaired — a response that will not fit the shape falls through to the
lenient path and is counted, so the structured-output failure rate is a number
somebody can look at rather than a feeling.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, ValidationError, field_validator

from . import intent as intent_module
from . import ledger as ledger_module


#: Outcomes of validating one response. Recorded per call so the failure rate
#: is observable rather than anecdotal.
STRUCTURED_OK = "ok"
STRUCTURED_INVALID = "invalid"
STRUCTURED_NOT_REQUESTED = "not-requested"

MAX_CLAIMS = ledger_module.MAX_CLAIMS
MAX_CLAIM_TEXT = ledger_module.MAX_CLAIM_TEXT
MAX_ANSWER_CHARS = 8000

#: Which claim types a mode may generate. The ledger enforces the same rule on
#: the way in; declaring it in the schema means a constrained decoder cannot
#: produce a recommendation for an evidence-mode question at all.
MODE_CLAIM_TYPES: Dict[str, Tuple[str, ...]] = {
    intent_module.ADVISORY_MODE: (
        ledger_module.FACT,
        ledger_module.SYNTHESIS,
        ledger_module.INFERENCE,
        ledger_module.RECOMMENDATION,
    ),
    intent_module.IDEATION: (
        ledger_module.FACT,
        ledger_module.SYNTHESIS,
        ledger_module.INFERENCE,
        ledger_module.RECOMMENDATION,
        ledger_module.IDEA,
    ),
}
DEFAULT_CLAIM_TYPES: Tuple[str, ...] = (
    ledger_module.FACT,
    ledger_module.SYNTHESIS,
    ledger_module.INFERENCE,
)


class Claim(BaseModel):
    """One ledger entry as the model is asked to write it."""

    id: str = Field(description="short unique id such as c1")
    type: str = Field(description="the epistemic type of this claim")
    text: str = Field(description="one substantive statement")
    citations: List[int] = Field(
        default_factory=list, description="citation ids supporting it; omit for generated advice"
    )
    derived_from: List[str] = Field(
        default_factory=list, description="ids of earlier claims this reasoning rests on"
    )
    based_on: List[str] = Field(
        default_factory=list, description="ids of earlier factual claims this advice rests on"
    )

    @field_validator("id", "type", "text", mode="before")
    @classmethod
    def _as_text(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()

    @field_validator("text")
    @classmethod
    def _bounded(cls, value: str) -> str:
        return value[:MAX_CLAIM_TEXT]

    @field_validator("citations", mode="before")
    @classmethod
    def _citation_ids(cls, value: Any) -> List[int]:
        return _ints(value)

    @field_validator("derived_from", "based_on", mode="before")
    @classmethod
    def _claim_ids(cls, value: Any) -> List[str]:
        return [str(item).strip() for item in _sequence(value) if str(item).strip()]


class Conflict(BaseModel):
    """Two cited sources disagreeing, as the answer reports it."""

    summary: str = Field(description="how the cited evidence disagrees")
    citations: List[int] = Field(default_factory=list, description="the citation ids that differ")

    @field_validator("summary", mode="before")
    @classmethod
    def _as_text(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()

    @field_validator("citations", mode="before")
    @classmethod
    def _citation_ids(cls, value: Any) -> List[int]:
        return _ints(value)


class SynthesisAnswer(BaseModel):
    """A whole synthesis response."""

    answer: str = Field(description="the answer prose, citing evidence inline as [citation_id]")
    claims: List[Claim] = Field(
        default_factory=list, description="one claim for every statement the answer makes"
    )
    conflicts: List[Conflict] = Field(default_factory=list)
    uncertainty: str = Field(default="", description="what the evidence does not settle")
    insufficient_evidence: bool = Field(
        default=False, description="true when the evidence cannot answer the question"
    )

    @field_validator("answer", "uncertainty", mode="before")
    @classmethod
    def _as_text(cls, value: Any) -> str:
        return "" if value is None else str(value).strip()

    @field_validator("answer")
    @classmethod
    def _bounded(cls, value: str) -> str:
        return value[:MAX_ANSWER_CHARS]

    @field_validator("claims", mode="before")
    @classmethod
    def _bounded_claims(cls, value: Any) -> Any:
        return _sequence(value)[:MAX_CLAIMS]

    @field_validator("insufficient_evidence", mode="before")
    @classmethod
    def _flag(cls, value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes"}
        return bool(value)


@lru_cache(maxsize=8)
def answer_schema(mode: str) -> Dict[str, Any]:
    """The JSON Schema for ``mode``, ready for Ollama's ``format``.

    Generated from :class:`SynthesisAnswer` and then narrowed in exactly one
    place: the claim ``type`` enum, which is mode-dependent. Inlined rather
    than left as ``$ref``/``$defs`` because a self-contained schema is what
    every structured-output backend agrees on.
    """
    schema = _inline_defs(SynthesisAnswer.model_json_schema())
    claim = schema["properties"]["claims"]["items"]
    claim["properties"]["type"]["enum"] = list(claim_types(mode))
    return schema


def claim_types(mode: str) -> Tuple[str, ...]:
    return MODE_CLAIM_TYPES.get(mode, DEFAULT_CLAIM_TYPES)


def parse_answer(payload: Any) -> Tuple[Optional[Dict[str, Any]], str]:
    """Validate a response against the schema.

    Returns ``(normalized payload, status)``. On failure the payload is
    ``None`` and the caller keeps whatever the model actually sent, so a
    schema this version did not anticipate degrades to the old lenient path
    instead of losing the turn.
    """
    if not isinstance(payload, dict):
        return None, STRUCTURED_INVALID
    try:
        answer = SynthesisAnswer.model_validate(payload)
    except ValidationError:
        return None, STRUCTURED_INVALID
    return answer.model_dump(), STRUCTURED_OK


def _inline_defs(schema: Dict[str, Any]) -> Dict[str, Any]:
    """Resolve ``$ref``/``$defs`` into one self-contained document."""
    definitions = schema.pop("$defs", {})

    def resolve(node: Any) -> Any:
        if isinstance(node, dict):
            reference = node.get("$ref")
            if isinstance(reference, str) and reference.startswith("#/$defs/"):
                return resolve(definitions.get(reference.split("/")[-1], {}))
            return {key: resolve(value) for key, value in node.items()}
        if isinstance(node, list):
            return [resolve(item) for item in node]
        return node

    return resolve(schema)


def _sequence(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _ints(value: Any) -> List[int]:
    found: List[int] = []
    for item in _sequence(value):
        try:
            number = int(str(item).strip().strip("[]"))
        except (TypeError, ValueError):
            continue
        if number not in found:
            found.append(number)
    return found
