"""Conversational working memory. Private, disposable, and never evidence.

    canonical corpus = evidence
    session state    = working memory

That line is the whole design. A session exists so "what's blocking it?" knows
what *it* is; it does not exist to remember what the answer was. Concretely:

* A session stores **pointers**, not content. An evidence snapshot is a
  document id, a content hash, and a retrieval timestamp — never the document,
  never the excerpt text. Receipts are served by re-reading the index, so what
  a user sees is always the current source rather than a stale copy (§8, §35).
* A stored conclusion carries its **citations with it**. A prior turn's prose
  is recorded as prose and marked as such; it can shape the next question's
  scope, and it can never be cited as a source (§23).
* A **user assumption is labelled as one**. "Assume retail is $275" becomes a
  scenario input with an explicit type, so a later "what's our retail price?"
  cannot answer $275 as fact (§24).
* Stale snapshots are **detectable**. When a document's hash has moved since it
  was retrieved, the session knows the earlier answer rested on text that no
  longer exists, and says so rather than reusing it.

Everything lives under ``GANG_HOME/sessions/``, outside the repository, mode
0600, and is safe to delete at any time.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from . import disclosure


SESSION_VERSION = "1"

#: Turns retained on disk at all. Older turns fall out of the file entirely;
#: what they contributed survives in the structured summary.
MAX_TURNS_STORED = 40
#: Turns replayed to the model verbatim. Beyond this, context compression (§23)
#: takes over and only the structured summary travels.
MAX_VERBATIM_TURNS = 6

MAX_SUMMARY_CHARS = 400
MAX_ACTIVE_DOCUMENTS = 24
MAX_ACTIVE_TOPICS = 12
MAX_ACTIVE_ENTITIES = 16
MAX_ASSUMPTIONS = 12
MAX_CONCLUSIONS = 12

_SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{4,64}$")


class SessionError(RuntimeError):
    """Raised when a session cannot be read, written, or identified."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- snapshots


@dataclass(frozen=True)
class EvidenceSnapshot:
    """A stable reference to evidence used in an earlier turn.

    Deliberately not the evidence itself. ``content_hash`` is what makes
    staleness detectable: the index records it per document, so comparing is
    exact rather than a guess about dates.
    """

    document_id: str
    content_hash: str = ""
    title: str = ""
    source_type: str = ""
    updated: str = ""
    source_ids: List[str] = field(default_factory=list)
    citation_id: int = 0
    excerpt_count: int = 0
    retrieved_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "content_hash": self.content_hash,
            "title": self.title,
            "source_type": self.source_type,
            "updated": self.updated,
            "source_ids": list(self.source_ids),
            "citation_id": self.citation_id,
            "excerpt_count": self.excerpt_count,
            "retrieved_at": self.retrieved_at,
        }

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "EvidenceSnapshot":
        return cls(
            document_id=_text(value.get("document_id")),
            content_hash=_text(value.get("content_hash")),
            title=_text(value.get("title")),
            source_type=_text(value.get("source_type")),
            updated=_text(value.get("updated")),
            source_ids=[_text(item) for item in value.get("source_ids") or []],
            citation_id=_int(value.get("citation_id")),
            excerpt_count=_int(value.get("excerpt_count")),
            retrieved_at=_text(value.get("retrieved_at")),
        )


@dataclass(frozen=True)
class Assumption:
    """Something the user supposed. Never a company fact (§24)."""

    text: str
    created: str = ""
    turn: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"text": self.text, "created": self.created, "turn": self.turn, "type": "session-assumption"}

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "Assumption":
        return cls(
            text=_text(value.get("text")),
            created=_text(value.get("created")),
            turn=_int(value.get("turn")),
        )


@dataclass(frozen=True)
class Conclusion:
    """A prior turn's claim, kept with its provenance pointers intact.

    Stored so context compression does not lose what was established, and so
    that "show me the receipts" can resolve against the previous answer's
    ledger without re-running a search (§31).
    """

    claim_id: str
    type: str
    text: str
    citations: List[int] = field(default_factory=list)
    document_ids: List[str] = field(default_factory=list)
    turn: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "type": self.type,
            "text": self.text,
            "citations": list(self.citations),
            "document_ids": list(self.document_ids),
            "turn": self.turn,
        }

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "Conclusion":
        return cls(
            claim_id=_text(value.get("claim_id")),
            type=_text(value.get("type")),
            text=_text(value.get("text")),
            citations=[_int(item) for item in value.get("citations") or []],
            document_ids=[_text(item) for item in value.get("document_ids") or []],
            turn=_int(value.get("turn")),
        )


@dataclass(frozen=True)
class Turn:
    """One question and what came back. Assistant prose, explicitly labelled."""

    index: int
    question: str
    resolved_question: str = ""
    policy: str = ""
    mode: str = ""
    answer_summary: str = ""
    citations: List[int] = field(default_factory=list)
    document_ids: List[str] = field(default_factory=list)
    created: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "question": self.question,
            "resolved_question": self.resolved_question,
            "policy": self.policy,
            "mode": self.mode,
            # Named to make its status unmistakable at every read site: this is
            # generated prose, not a source.
            "answer_summary": self.answer_summary,
            "citations": list(self.citations),
            "document_ids": list(self.document_ids),
            "created": self.created,
        }

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "Turn":
        return cls(
            index=_int(value.get("index")),
            question=_text(value.get("question")),
            resolved_question=_text(value.get("resolved_question")),
            policy=_text(value.get("policy")),
            mode=_text(value.get("mode")),
            answer_summary=_text(value.get("answer_summary")),
            citations=[_int(item) for item in value.get("citations") or []],
            document_ids=[_text(item) for item in value.get("document_ids") or []],
            created=_text(value.get("created")),
        )


# ----------------------------------------------------------------- session


@dataclass
class Session:
    """Mutable working memory for one conversation."""

    session_id: str
    created: str = field(default_factory=_now)
    updated: str = field(default_factory=_now)
    version: str = SESSION_VERSION
    active_topics: List[str] = field(default_factory=list)
    active_entity_ids: List[str] = field(default_factory=list)
    active_entity_names: Dict[str, str] = field(default_factory=dict)
    active_document_ids: List[str] = field(default_factory=list)
    active_time_range: Optional[Dict[str, str]] = None
    turns: List[Turn] = field(default_factory=list)
    snapshots: Dict[str, EvidenceSnapshot] = field(default_factory=dict)
    assumptions: List[Assumption] = field(default_factory=list)
    conclusions: List[Conclusion] = field(default_factory=list)
    last_claims: List[Dict[str, Any]] = field(default_factory=list)
    last_citation_map: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def new(cls, session_id: Optional[str] = None) -> "Session":
        return cls(session_id=session_id or new_session_id())

    @property
    def turn_count(self) -> int:
        return len(self.turns)

    @property
    def empty(self) -> bool:
        return not self.turns

    # ------------------------------------------------------------ mutation

    def record_turn(
        self,
        *,
        question: str,
        resolved_question: str,
        policy: str,
        mode: str,
        answer: str,
        evidence: Sequence[Any],
        claims: Sequence[Dict[str, Any]],
        entities: Sequence[Dict[str, Any]] = (),
        topics: Sequence[str] = (),
        time_range: Optional[Dict[str, str]] = None,
    ) -> Turn:
        """Fold one completed turn into working memory."""
        timestamp = _now()
        index = len(self.turns) + 1

        document_ids: List[str] = []
        citations: List[int] = []
        for item in evidence:
            snapshot = _snapshot_from_item(item, timestamp)
            if not snapshot.document_id:
                continue
            self.snapshots[snapshot.document_id] = snapshot
            if snapshot.document_id not in document_ids:
                document_ids.append(snapshot.document_id)
            if snapshot.citation_id:
                citations.append(snapshot.citation_id)

        citation_documents = {
            str(_int(_get(item, "citation_id"))): _get(item, "document_id")
            for item in evidence
        }

        turn = Turn(
            index=index,
            question=question,
            resolved_question=resolved_question,
            policy=policy,
            mode=mode,
            answer_summary=_summarize(answer, claims),
            citations=sorted(set(citations)),
            document_ids=document_ids,
            created=timestamp,
        )
        self.turns.append(turn)
        del self.turns[:-MAX_TURNS_STORED]

        self.active_document_ids = _merge(document_ids, self.active_document_ids, MAX_ACTIVE_DOCUMENTS)
        self.active_topics = _merge(list(topics), self.active_topics, MAX_ACTIVE_TOPICS)
        for entity in entities:
            entity_id = _text(_get(entity, "entity_id"))
            if not entity_id:
                continue
            self.active_entity_ids = _merge([entity_id], self.active_entity_ids, MAX_ACTIVE_ENTITIES)
            self.active_entity_names[entity_id] = _text(_get(entity, "name")) or entity_id
        if time_range:
            self.active_time_range = dict(time_range)

        self._record_conclusions(claims, citation_documents, index)
        self.last_claims = [dict(claim) for claim in claims]
        self.last_citation_map = {key: value for key, value in citation_documents.items() if value}
        self.updated = timestamp
        return turn

    def _record_conclusions(
        self, claims: Sequence[Dict[str, Any]], citation_documents: Dict[str, str], turn: int
    ) -> None:
        """Keep grounded conclusions, with the documents that supported them.

        Only claims that survived validation are kept. Storing a downgraded
        claim as a conclusion would let an unsupported statement re-enter
        later turns as settled context.

        Inferences are kept too, and kept *as inferences*. The type travels
        with the text into every later turn, so "X appears to be on the core
        team" cannot harden into "X is on the core team" through repetition —
        which is the way a conversational system would otherwise manufacture
        a fact out of its own earlier caution.
        """
        by_id = {_text(claim.get("id")): claim for claim in claims}
        for claim in claims:
            if claim.get("type") not in ("fact", "synthesis", "inference"):
                continue
            if claim.get("status") != "accepted":
                continue
            citations = [_int(value) for value in claim.get("citations") or []]
            if not citations:
                # An inference carries no citations of its own; its evidence
                # sits under the premises it was drawn from. Inheriting them
                # is what lets a later turn re-open the reasoning instead of
                # finding a conclusion with nothing behind it.
                for reference in claim.get("derived_from") or []:
                    premise = by_id.get(_text(reference)) or {}
                    citations.extend(_int(value) for value in premise.get("citations") or [])
                citations = sorted(set(citations))
            if not citations:
                continue
            self.conclusions.append(
                Conclusion(
                    claim_id=_text(claim.get("id")),
                    type=_text(claim.get("type")),
                    text=_text(claim.get("text")),
                    citations=citations,
                    document_ids=[
                        citation_documents[str(value)]
                        for value in citations
                        if citation_documents.get(str(value))
                    ],
                    turn=turn,
                )
            )
        del self.conclusions[:-MAX_CONCLUSIONS]

    def add_assumption(self, text: str) -> Optional[Assumption]:
        """Record a user-supplied scenario input. Never canonical (§24)."""
        cleaned = _text(text)
        if not cleaned:
            return None
        if any(item.text.casefold() == cleaned.casefold() for item in self.assumptions):
            return None
        assumption = Assumption(text=cleaned[:280], created=_now(), turn=len(self.turns) + 1)
        self.assumptions.append(assumption)
        del self.assumptions[:-MAX_ASSUMPTIONS]
        return assumption

    def clear_assumptions(self) -> None:
        self.assumptions = []

    def set_topics(self, topics: Sequence[str]) -> None:
        self.active_topics = _merge(list(topics), self.active_topics, MAX_ACTIVE_TOPICS)

    # -------------------------------------------------------------- reading

    def recent_turns(self, count: int = MAX_VERBATIM_TURNS) -> List[Turn]:
        return self.turns[-count:] if count > 0 else []

    def previous_turn(self) -> Optional[Turn]:
        return self.turns[-1] if self.turns else None

    def snapshot_for(self, document_id: str) -> Optional[EvidenceSnapshot]:
        return self.snapshots.get(document_id)

    def context_summary(self) -> Dict[str, Any]:
        """The compressed, structured view handed to the model each turn.

        Provenance pointers survive compression; prose does not become fact.
        Every conclusion carries the document ids behind it, so a later turn
        can re-ground rather than trust the summary.
        """
        return {
            "session_id": self.session_id,
            "turn_count": len(self.turns),
            "active_topics": list(self.active_topics),
            "active_entities": [
                {"entity_id": entity_id, "name": self.active_entity_names.get(entity_id, entity_id)}
                for entity_id in self.active_entity_ids
            ],
            "active_document_ids": list(self.active_document_ids),
            "active_time_range": dict(self.active_time_range) if self.active_time_range else None,
            "recent_turns": [
                {
                    "question": turn.question,
                    "policy": turn.policy,
                    # Prefixed everywhere it is serialized. The model must not
                    # be able to read this as a retrieved source.
                    "previous_answer_summary": turn.answer_summary,
                    # What the summary rests on, so a remote context can drop
                    # a turn whose answer drew on sensitive evidence.
                    "document_ids": list(turn.document_ids),
                }
                for turn in self.recent_turns()
            ],
            "prior_conclusions": [item.to_dict() for item in self.conclusions],
            "prior_conclusion_rule": (
                "Each prior conclusion carries the type it was validated as. An entry "
                "typed 'inference' was a reading of the evidence, not something the corpus "
                "states. It stays an inference however many turns ago it was drawn and "
                "however often it has been repeated; restating it as fact is not allowed."
            ),
            "session_assumptions": [item.to_dict() for item in self.assumptions],
            "rule": (
                "This block is CONVERSATION STATE, not evidence. It records what was asked and "
                "concluded earlier so references like 'it' and 'that' resolve. Never cite it, "
                "never treat a previous_answer_summary as a source, and never treat a "
                "session_assumption as a company fact. If an earlier conclusion matters again, "
                "re-retrieve the evidence behind it."
            ),
        }

    # ------------------------------------------------------------ staleness

    def stale_snapshots(self, current_hashes: Dict[str, str]) -> List[Dict[str, Any]]:
        """Snapshots whose source has changed since it was retrieved (§8).

        A document absent from ``current_hashes`` is reported as removed rather
        than assumed unchanged.
        """
        stale: List[Dict[str, Any]] = []
        for document_id, snapshot in sorted(self.snapshots.items()):
            if not snapshot.content_hash:
                continue
            current = current_hashes.get(document_id)
            if current is None:
                stale.append(
                    {
                        "document_id": document_id,
                        "title": snapshot.title,
                        "reason": "document-no-longer-in-index",
                        "retrieved_at": snapshot.retrieved_at,
                    }
                )
            elif current != snapshot.content_hash:
                stale.append(
                    {
                        "document_id": document_id,
                        "title": snapshot.title,
                        "reason": "source-changed-since-retrieval",
                        "retrieved_at": snapshot.retrieved_at,
                    }
                )
        return stale

    # ---------------------------------------------------------- persistence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "session_id": self.session_id,
            "created": self.created,
            "updated": self.updated,
            "active_topics": list(self.active_topics),
            "active_entity_ids": list(self.active_entity_ids),
            "active_entity_names": dict(self.active_entity_names),
            "active_document_ids": list(self.active_document_ids),
            "active_time_range": dict(self.active_time_range) if self.active_time_range else None,
            "turns": [turn.to_dict() for turn in self.turns],
            "evidence_snapshots": [item.to_dict() for item in self.snapshots.values()],
            "assumptions": [item.to_dict() for item in self.assumptions],
            "conclusions": [item.to_dict() for item in self.conclusions],
            "last_claims": [dict(claim) for claim in self.last_claims],
            "last_citation_map": dict(self.last_citation_map),
        }

    @classmethod
    def from_dict(cls, value: Dict[str, Any]) -> "Session":
        if not isinstance(value, dict):
            raise SessionError("Session file is not an object")
        session_id = _text(value.get("session_id"))
        if not session_id:
            raise SessionError("Session file has no session_id")
        snapshots = {}
        for item in value.get("evidence_snapshots") or []:
            snapshot = EvidenceSnapshot.from_dict(item)
            if snapshot.document_id:
                snapshots[snapshot.document_id] = snapshot
        return cls(
            session_id=session_id,
            created=_text(value.get("created")) or _now(),
            updated=_text(value.get("updated")) or _now(),
            version=_text(value.get("version")) or SESSION_VERSION,
            active_topics=[_text(item) for item in value.get("active_topics") or []],
            active_entity_ids=[_text(item) for item in value.get("active_entity_ids") or []],
            active_entity_names={
                _text(key): _text(item) for key, item in (value.get("active_entity_names") or {}).items()
            },
            active_document_ids=[_text(item) for item in value.get("active_document_ids") or []],
            active_time_range=dict(value["active_time_range"])
            if isinstance(value.get("active_time_range"), dict)
            else None,
            turns=[Turn.from_dict(item) for item in value.get("turns") or []],
            snapshots=snapshots,
            assumptions=[Assumption.from_dict(item) for item in value.get("assumptions") or []],
            conclusions=[Conclusion.from_dict(item) for item in value.get("conclusions") or []],
            last_claims=[dict(item) for item in value.get("last_claims") or [] if isinstance(item, dict)],
            last_citation_map={
                _text(key): _text(item) for key, item in (value.get("last_citation_map") or {}).items()
            },
        )


class SessionStore:
    """Sessions on disk under ``GANG_HOME/sessions/``. Private, never in git."""

    def __init__(
        self,
        sessions_path: Path | str,
        *,
        sensitivity: Optional[disclosure.SensitivityLookup] = None,
    ):
        self.sessions_path = Path(sessions_path)
        #: When set, every save masks identifiers quoted from restricted and
        #: local-only documents (`sanitize_payload`) before anything is written.
        self.sensitivity = sensitivity

    def path_for(self, session_id: str) -> Path:
        if not _SESSION_ID.fullmatch(session_id or ""):
            # Rejecting rather than sanitizing: a session id reaches this from
            # a CLI flag, and a traversal attempt should fail loudly.
            raise SessionError(f"Invalid session id: {session_id!r}")
        return self.sessions_path / f"{session_id}.json"

    def exists(self, session_id: str) -> bool:
        return self.path_for(session_id).exists()

    def create(self, session_id: Optional[str] = None) -> Session:
        return Session.new(session_id)

    def load(self, session_id: str) -> Session:
        path = self.path_for(session_id)
        if not path.exists():
            raise SessionError(f"No such session: {session_id}")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SessionError(f"Session {session_id} is unreadable: {exc}") from exc
        return Session.from_dict(payload)

    def load_or_create(self, session_id: Optional[str]) -> Session:
        if session_id and self.exists(session_id):
            return self.load(session_id)
        return self.create(session_id)

    def latest(self) -> Optional[Session]:
        entries = self.list_sessions()
        return self.load(entries[0]["session_id"]) if entries else None

    def save(self, session: Session) -> Path:
        path = self.path_for(session.session_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = session.to_dict()
        if self.sensitivity is not None:
            data = sanitize_payload(data, self.sensitivity)
        self.write_payload(path, data)
        return path

    def write_payload(self, path: Path, data: Dict[str, Any]) -> None:
        temporary = path.with_suffix(".json.tmp")
        payload = json.dumps(data, indent=2, sort_keys=True, default=str) + "\n"
        temporary.write_text(payload, encoding="utf-8")
        # Private by construction, not by the umask the shell happened to have.
        try:
            os.chmod(temporary, 0o600)
        except OSError:
            pass
        temporary.replace(path)

    def list_sessions(self) -> List[Dict[str, Any]]:
        """Newest first. Reads only the header fields, never the turns."""
        if not self.sessions_path.exists():
            return []
        entries: List[Dict[str, Any]] = []
        for path in sorted(self.sessions_path.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict) or not payload.get("session_id"):
                continue
            entries.append(
                {
                    "session_id": _text(payload.get("session_id")),
                    "created": _text(payload.get("created")),
                    "updated": _text(payload.get("updated")),
                    "turn_count": len(payload.get("turns") or []),
                    "active_topics": [_text(item) for item in payload.get("active_topics") or []],
                }
            )
        return sorted(entries, key=lambda item: item["updated"], reverse=True)

    def delete(self, session_id: str) -> bool:
        path = self.path_for(session_id)
        if not path.exists():
            return False
        path.unlink()
        return True


def sanitize_payload(payload: Dict[str, Any], lookup: disclosure.SensitivityLookup) -> Dict[str, Any]:
    """A stored session with identifiers masked wherever it quotes a sensitive document.

    Turns, conclusions, and snapshots cite their documents directly, so
    `disclosure.sanitize_for_display` handles them as they are. The previous
    answer's claims point through citation numbers instead, so each is
    resolved through ``last_citation_map`` first. Ids, hashes, and citations
    are never touched; a session that quotes nothing sensitive is unchanged.
    """
    citation_map = payload.get("last_citation_map") or {}
    claims = [
        {
            "document_ids": [
                citation_map[str(value)]
                for value in claim.get("citations") or []
                if citation_map.get(str(value))
            ],
            "claim": claim,
        }
        for claim in payload.get("last_claims") or []
        if isinstance(claim, dict)
    ]
    rest = {key: value for key, value in payload.items() if key != "last_claims"}
    sanitized = disclosure.sanitize_for_display(rest, lookup)
    wrapped = disclosure.sanitize_for_display(claims, lookup)
    if sanitized is rest and wrapped is claims:
        return payload
    return {**sanitized, "last_claims": [entry["claim"] for entry in wrapped]}


def new_session_id() -> str:
    return uuid.uuid4().hex[:12]


# ----------------------------------------------------------------- helpers


def _snapshot_from_item(item: Any, timestamp: str) -> EvidenceSnapshot:
    return EvidenceSnapshot(
        document_id=_text(_get(item, "document_id")),
        content_hash=_text(_get(item, "content_hash")),
        title=_text(_get(item, "title"))[:200],
        source_type=_text(_get(item, "source_type")),
        updated=_text(_get(item, "updated")),
        source_ids=[_text(value) for value in (_get(item, "source_ids") or [])][:8],
        citation_id=_int(_get(item, "citation_id")),
        # A count, not the text. The excerpts stay in the index.
        excerpt_count=len(_get(item, "excerpts") or []),
        retrieved_at=timestamp,
    )


def _summarize(answer: str, claims: Sequence[Dict[str, Any]] = ()) -> str:
    claim_texts = [_text(_get(item, "text")) for item in claims if _text(_get(item, "text"))]
    text = "; ".join(claim_texts[:4]) if claim_texts else answer
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= MAX_SUMMARY_CHARS else text[: MAX_SUMMARY_CHARS - 1].rstrip() + "…"


def _merge(new_values: Sequence[str], existing: Sequence[str], limit: int) -> List[str]:
    """Newest first, de-duplicated, bounded."""
    result: List[str] = []
    for value in list(new_values) + list(existing):
        text = _text(value)
        if text and text not in result:
            result.append(text)
    return result[:limit]


def _get(item: Any, name: str) -> Any:
    if isinstance(item, dict):
        return item.get(name)
    return getattr(item, name, None)


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _text(value: Any) -> str:
    if value is None:
        return ""
    return value.strip() if isinstance(value, str) else str(value).strip()
