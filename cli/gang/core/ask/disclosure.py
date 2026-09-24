"""Keep restricted and local-only evidence out of remote-provider contexts.

Sensitivity (``core.sensitivity``) is decided per document at index time. This
module is where Ask honors it, and it has one rule: when the provider about to
receive a context is remote, everything that came from a document which is not
``normal`` is left out *before* the request is built. Deterministic answers and
loopback local models see the full evidence set, exactly as before.

Three kinds of material reach a model, and each is narrowed the same way:

* **Evidence items** — `EvidenceBundle.for_remote_provider` drops them whole.
* **Structured records, conversation state, authority guidance, research
  observations** — `remote_data` drops every entry that cites a withheld
  document through a ``document_id`` (or ``*_document_id``) or
  ``document_ids`` field. A generated
  evidence fact keeps its provenance in the local store; it simply cannot carry
  its supporting quote into a remote prompt. Pointer lists such as
  ``active_document_ids`` lose the withheld ids and keep the rest.
* **Unknown documents** — an id the index does not know has no established
  sensitivity, so it is treated as withheld.

Nothing here edits a string. Material is kept or omitted; redacting text after
it has been gathered into a remote context is precisely what this avoids.

The boundary also decides what happens when the loopback model that was the
only place such evidence could go is unavailable, times out, or errors. There
is no second provider to try, so Ask answers evidence-only — the same
deterministic listing `--no-ai` produces, under a notice saying synthesis did
not happen — rather than aborting (`local_fallback_basis`). The same holds
when the user explicitly asked for local-only Ask: they ruled out remote
disclosure themselves, so there is equally nothing to fall back to.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set

from core import sensitivity
from core.ai_provider import is_remote_provider


#: A function from document ids to their disclosure levels.
SensitivityLookup = Callable[[Sequence[str]], Mapping[str, str]]

#: Prepended by code when a remote provider was chosen but every piece of
#: evidence was withheld from it, so the answer fell back to a local listing.
SENSITIVE_EVIDENCE_NOTICE = (
    "The evidence for this question is restricted or local-only, so it was not sent "
    "to the remote AI provider. These are the matching documents; ask with a local "
    "provider to have them summarized."
)

SENSITIVE_EVIDENCE_REASON = "sensitive-evidence-local-only"

#: Prepended by code when a loopback model was the only provider the evidence
#: could reach and it failed, so the answer fell back to a local listing.
LOCAL_SYNTHESIS_UNAVAILABLE_NOTICE = (
    "Local synthesis was unavailable, so this response is evidence-only: nothing was "
    "summarized. Some of this evidence is restricted or local-only, so it was not sent "
    "to a remote AI provider instead. Here is the evidence GANG can safely show."
)

#: The same, when the evidence is ordinary but the user explicitly asked that
#: nothing go to a remote provider.
LOCAL_ONLY_SYNTHESIS_UNAVAILABLE_NOTICE = (
    "Local synthesis was unavailable, so this response is evidence-only: nothing was "
    "summarized. Remote AI providers were disabled for this question (local-only), so it "
    "was not sent to one instead. Here is the evidence GANG can safely show."
)

LOCAL_SYNTHESIS_UNAVAILABLE_REASON = "local-synthesis-unavailable"

#: Why an evidence-only fallback was allowed, recorded in synthesis metadata.
SENSITIVE_EVIDENCE_BASIS = "sensitive-evidence"
LOCAL_ONLY_REQUESTED_BASIS = "local-only-requested"

LOCAL_FALLBACK_NOTICES = {
    SENSITIVE_EVIDENCE_BASIS: LOCAL_SYNTHESIS_UNAVAILABLE_NOTICE,
    LOCAL_ONLY_REQUESTED_BASIS: LOCAL_ONLY_SYNTHESIS_UNAVAILABLE_NOTICE,
}

_DROP = object()


def applies(provider: Any) -> bool:
    """Whether contexts for ``provider`` must be narrowed."""
    return provider is not None and is_remote_provider(provider)


def local_fallback_basis(provider: Any, bundle: Any, *, local_only: bool = False) -> Optional[str]:
    """Why a failed ``provider`` call may degrade to an evidence-only answer, or ``None``.

    Only a loopback provider qualifies, and only when no remote provider may
    take its place: the evidence includes something no remote provider may
    see, or the user explicitly asked for local-only Ask. Everywhere else a
    failed call keeps its existing behavior.
    """
    if provider is None or applies(provider):
        return None
    if any(
        not sensitivity.permits_remote(getattr(item, "sensitivity", None))
        for item in getattr(bundle, "items", []) or []
    ):
        return SENSITIVE_EVIDENCE_BASIS
    if local_only:
        return LOCAL_ONLY_REQUESTED_BASIS
    return None


def referenced_document_ids(value: Any) -> Set[str]:
    """Every document id ``value`` cites or points at, at any depth."""
    found: Set[str] = set()

    def walk(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                name = str(key)
                if name.endswith("document_id") and isinstance(child, str) and child:
                    found.add(child)
                elif name.endswith("document_ids") and isinstance(child, (list, tuple)):
                    found.update(str(entry) for entry in child if isinstance(entry, str) and entry)
                else:
                    walk(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                walk(child)

    walk(value)
    return found


def withheld_ids(document_ids: Iterable[str], lookup: SensitivityLookup) -> Set[str]:
    """The subset of ``document_ids`` a remote provider may not see."""
    wanted = sorted({value for value in document_ids if value})
    if not wanted:
        return set()
    levels = lookup(wanted) or {}
    return {value for value in wanted if not sensitivity.permits_remote(levels.get(value))}


def remote_data(value: Any, lookup: SensitivityLookup) -> Any:
    """``value`` without any entry that cites a withheld document."""
    withheld = withheld_ids(referenced_document_ids(value), lookup)
    if not withheld:
        return value
    scrubbed = _scrub(value, withheld)
    return {} if scrubbed is _DROP and isinstance(value, Mapping) else scrubbed


def withheld_summary(bundle: Any) -> List[Dict[str, Any]]:
    """What a remote provider did not see, for the local reader. No text."""
    return [dict(entry) for entry in getattr(bundle, "withheld", []) or []]


def _scrub(value: Any, withheld: Set[str]) -> Any:
    if isinstance(value, Mapping):
        if _cites(value, withheld):
            return _DROP
        result: Dict[str, Any] = {}
        for key, child in value.items():
            name = str(key)
            if name.endswith("document_ids") and isinstance(child, (list, tuple)):
                # A pointer list rather than provenance: keep the entry, lose
                # the ids. Provenance fields are handled by `_cites`.
                result[key] = [entry for entry in child if entry not in withheld]
                continue
            cleaned = _scrub(child, withheld)
            if cleaned is not _DROP:
                result[key] = cleaned
        return result
    if isinstance(value, (list, tuple)):
        return [
            cleaned
            for cleaned in (_scrub(child, withheld) for child in value)
            if cleaned is not _DROP and not (isinstance(cleaned, str) and cleaned in withheld)
        ]
    return value


def _cites(entry: Mapping[str, Any], withheld: Set[str]) -> bool:
    """Whether this entry's own content came from a withheld document."""
    if any(
        str(key).endswith("document_id") and isinstance(value, str) and value in withheld
        for key, value in entry.items()
    ):
        return True
    cited = entry.get("document_ids")
    return isinstance(cited, (list, tuple)) and any(value in withheld for value in cited)
