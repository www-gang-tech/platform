"""The closed vocabulary of grounding warnings, and how each one reads.

A grounding warning is how the system reports that it did not fully believe
something it just printed. Two layers emit them — one-shot synthesis and the
conversational claim ledger — and they grew apart: one wrote the claim text
under ``claim``, the other under ``text``. The renderer knew about one shape,
so a perfectly correct warning from the other crashed `gang ask` with a
``KeyError``.

The lesson is not "be careful with dict keys". It is that a diagnostic channel
needs a schema as much as an answer does. So the variants live here, in one
closed table:

* ``numeric`` — a figure is absent from the cited evidence, or the evidence
  never connected two figures the claim connects.
* ``entity_linkage`` — a claim relates two entities that no cited source
  mentions together.
* ``citation`` — a factual claim had nothing behind it and was downgraded.
* ``scenario`` — a claim rests on a figure the user supposed, not the corpus.
* ``decision_framing`` — generated advice was phrased as a decision the
  company already took.

Two rules hold at the rendering boundary, and both matter:

1. **Every variant renders explicitly.** Each has its own sentence, because
   "no citation supports this" and "these two numbers were never related by a
   source" are different things to tell a reader.
2. **A warning can never crash the command.** A well-formed warning with an
   unfamiliar ``check`` still renders, in the generic form. A structurally
   broken warning is *reported as broken* rather than dropped — swallowing it
   would hide the very failure it exists to surface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence


#: The checks that can produce a warning. Anything else renders generically.
NUMERIC = "numeric"
ENTITY_LINKAGE = "entity_linkage"
CITATION = "citation"
SCENARIO = "scenario"
DECISION_FRAMING = "decision_framing"

CHECKS = (NUMERIC, ENTITY_LINKAGE, CITATION, SCENARIO, DECISION_FRAMING)

#: The canonical serialized shape. ``claim`` is the claim text the warning is
#: about; it is named for what the reader sees, and kept from the original
#: one-shot schema so existing consumers keep working.
WARNING_FIELDS = ("check", "status", "claim", "claim_id")

MAX_CLAIM_CHARS = 300


@dataclass(frozen=True)
class GroundingWarning:
    check: str
    status: str
    claim: str = ""
    claim_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        payload = {"check": self.check, "status": self.status, "claim": self.claim}
        if self.claim_id:
            payload["claim_id"] = self.claim_id
        return payload


def warning(check: str, status: str, claim: str = "", claim_id: str = "") -> Dict[str, Any]:
    """Build one warning in the canonical shape. The only way to emit one."""
    return GroundingWarning(
        check=_text(check) or "unknown",
        status=_text(status) or "unspecified",
        claim=_truncate(_text(claim), MAX_CLAIM_CHARS),
        claim_id=_text(claim_id),
    ).to_dict()


def normalize(value: Any) -> Optional[Dict[str, Any]]:
    """Coerce an untrusted warning into the canonical shape, or return None.

    Accepts the conversational ledger's ``text`` key as well as the canonical
    ``claim``, so a warning that crossed a version boundary still renders.
    Returns ``None`` only when there is genuinely nothing to render — the
    caller reports that rather than skipping it.
    """
    if not isinstance(value, dict):
        return None
    check = _text(value.get("check"))
    if not check:
        return None
    claim = _text(value.get("claim")) or _text(value.get("text"))
    return warning(
        check=check,
        status=_text(value.get("status")),
        claim=claim,
        claim_id=_text(value.get("claim_id")),
    )


#: One sentence per variant. Explicit rather than templated, because these say
#: materially different things and a reader should not have to decode a status
#: slug to tell them apart.
def describe(value: Any) -> str:
    """The stderr line for one warning. Never raises."""
    item = normalize(value)
    if item is None:
        # Deliberately loud. A diagnostic that cannot be read is itself a
        # finding, and hiding it defeats the purpose of the channel.
        return f"(malformed grounding warning, not rendered: {value!r})"

    check, status, claim = item["check"], item["status"], item["claim"]
    suffix = f": {claim}" if claim else ""

    if check == NUMERIC:
        return f"(unverified numeric claim [{status}]{suffix})"
    if check == ENTITY_LINKAGE:
        return f"(unverified entity_linkage claim [{status}]{suffix})"
    if check == CITATION:
        return f"(downgraded to uncertain, no citation supports it{suffix})"
    if check == SCENARIO:
        return f"(scenario claim, rests on your assumption rather than the corpus{suffix})"
    if check == DECISION_FRAMING:
        return f"(generated claim phrased as an existing company decision{suffix})"
    # A check this version does not know about is still a real warning.
    return f"(unverified {check} claim [{status}]{suffix})"


def describe_all(values: Sequence[Any]) -> List[str]:
    """Render a whole list. One bad entry never costs the others."""
    return [describe(item) for item in values or ()]


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _text(value: Any) -> str:
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value).strip()
