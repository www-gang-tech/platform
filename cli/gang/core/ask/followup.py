"""Resolve "what's blocking it?" against the conversation, before retrieval.

Conversation is elliptical. People establish a subject once and then stop
saying it, and a system that demands the subject in every turn is not a
conversation. So each question is read against session state first, and three
decisions are made deterministically:

1. **Does this question even need context?** A question that names its own
   subject does not, and injecting the previous topic into it would quietly
   answer the wrong question. "What are we doing with packaging?" switches
   topic and must be allowed to.
2. **What does the reference point at?** Pronouns and definite phrases
   ("it", "those", "the latest plan") resolve to the session's active topics,
   entities, and documents.
3. **Is it ambiguous?** If so, ask. A guess that lands on the wrong subject
   produces a confident answer to a question nobody asked, which is worse than
   one clarifying sentence.

What comes out is additive. The user's question is never rewritten — carried
context is attached alongside it, so the recorded question stays what they
actually typed, and every injected term is reported in ``carried``.

This module also spots user-supplied assumptions ("assume retail is $275") so
the layers above can treat them as scenario inputs rather than company facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from .planner import STOPWORDS


#: Words naming the *shape* of the request rather than its subject. A question
#: built only from these is a follow-up: "give me a plan for this week" has no
#: subject of its own and means the subject already on the table.
REQUEST_VOCABULARY = frozenset(
    """
    plan plans planning idea ideas option options way ways approach approaches
    recommend recommendation recommendations suggest suggestion suggestions advice
    think thoughts opinion take view receipts source sources citation citations
    evidence basing based decide decided decision decisions deciding undecided
    action actions item items owner owns own responsible accountable
    question questions open blocking blocked blocker blockers issue issues
    status update summary summarize summarise report brief overview rundown
    week weeks month months quarter today tomorrow now next last this
    change changed changes changing happening going missing
    three five ten several few many more first second third
    unconventional creative simple simplify better worse best worst
    do doing does done make made give given show tell
    actually really exactly simply honestly basically
    current currently latest recent recently still already ever
    """.split()
)

#: Anaphora proper: a reference with no antecedent inside this sentence.
_PRONOUN = re.compile(
    r"\b(?:it|its|that|this|those|these|them|they|their|there)\b", re.IGNORECASE
)

#: Definite phrases that point back at something already established.
_DEFINITE_REFERENCE = re.compile(
    r"\bthe\s+(?:project|plan|latest\s+plan|work|certification\s+work|issues?|"
    r"problems?|blockers?|decisions?|timeline|schedule|thread|document|doc|"
    r"topic|team|above|same)\b",
    re.IGNORECASE,
)

#: A question that starts with a bare verb phrase and names nothing.
_BARE_FOLLOWUP = re.compile(
    r"^\s*(?:and|so|ok|okay|then)?\s*(?:what|who|when|how|why|where)\b.{0,40}$",
    re.IGNORECASE,
)

_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9'._@-]*")

#: Supposition markers, and how much of the sentence the assumption covers.
_ASSUMPTION_PATTERNS = (
    re.compile(r"\bassum(?:e|ing)\s+(?:that\s+)?(?P<body>[^.?!;]{3,200})", re.IGNORECASE),
    re.compile(r"\bsuppose\s+(?:that\s+)?(?P<body>[^.?!;]{3,200})", re.IGNORECASE),
    re.compile(r"\bpretend\s+(?:that\s+)?(?P<body>[^.?!;]{3,200})", re.IGNORECASE),
    re.compile(r"\bif\s+(?P<body>[^.?!;]{3,200}?\bwer[et]\b[^.?!;]{0,120})", re.IGNORECASE),
    re.compile(r"\bwhat\s+if\s+(?P<body>[^.?!;]{3,200})", re.IGNORECASE),
    re.compile(r"\bsay\s+(?P<body>(?:the\s+)?\w+\s+(?:is|were|was)\s+[^.?!;]{1,120})", re.IGNORECASE),
)

MAX_CARRIED_TOPICS = 4
MAX_CARRIED_ENTITIES = 4


@dataclass(frozen=True)
class Resolution:
    """The question, plus whatever the conversation contributed to it."""

    question: str
    retrieval_text: str = ""
    carried_topics: List[str] = field(default_factory=list)
    carried_entity_ids: List[str] = field(default_factory=list)
    carried_document_ids: List[str] = field(default_factory=list)
    references: List[Dict[str, str]] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    clarification: str = ""
    followup: bool = False

    @property
    def needs_clarification(self) -> bool:
        return bool(self.clarification)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "question": self.question,
            "retrieval_text": self.retrieval_text,
            "followup": self.followup,
            "carried_topics": list(self.carried_topics),
            "carried_entity_ids": list(self.carried_entity_ids),
            "carried_document_ids": list(self.carried_document_ids),
            "resolved_references": list(self.references),
            "scenario_assumptions": list(self.assumptions),
            "clarification": self.clarification,
        }


def resolve(question: str, session: Optional[Any] = None) -> Resolution:
    """Read one question against session working memory."""
    text = (question or "").strip()
    assumptions = extract_assumptions(text)

    if session is None or getattr(session, "empty", True):
        # A new session has no context to carry, and a pronoun in the very
        # first question has nothing to point at.
        clarification = ""
        if _has_anaphora(text) and not _subject_terms(text):
            clarification = (
                "I don't have a subject for that yet — this is the first question in the "
                "session. What would you like me to look at?"
            )
        return Resolution(
            question=text,
            retrieval_text=text,
            assumptions=assumptions,
            clarification=clarification,
        )

    anaphora = _has_anaphora(text)
    subjects = _subject_terms(text)
    followup = bool(anaphora or not subjects)

    if not followup:
        # The question stands on its own. Carrying the old topic here is how a
        # topic switch silently fails.
        return Resolution(question=text, retrieval_text=text, assumptions=assumptions)

    topics = list(getattr(session, "active_topics", []) or [])[:MAX_CARRIED_TOPICS]
    entity_ids = list(getattr(session, "active_entity_ids", []) or [])[:MAX_CARRIED_ENTITIES]
    document_ids = list(getattr(session, "active_document_ids", []) or [])

    if not topics and not entity_ids:
        return Resolution(
            question=text,
            retrieval_text=text,
            followup=True,
            assumptions=assumptions,
            clarification=(
                "I'm not sure what that refers to — the previous turn didn't settle on a "
                "subject. Could you name the topic?"
            ),
        )

    ambiguity = _definite_ambiguity(text, session)
    if ambiguity:
        return Resolution(
            question=text,
            retrieval_text=text,
            followup=True,
            assumptions=assumptions,
            clarification=ambiguity,
        )

    references = _describe_references(text, topics, entity_ids, session)
    retrieval_text = " ".join([text, *topics]).strip()

    return Resolution(
        question=text,
        retrieval_text=retrieval_text,
        carried_topics=topics,
        carried_entity_ids=entity_ids,
        carried_document_ids=document_ids,
        references=references,
        assumptions=assumptions,
        followup=True,
    )


def extract_assumptions(question: str) -> List[str]:
    """Clauses the user asked us to suppose. Scenario inputs, never facts."""
    text = (question or "").strip()
    found: List[str] = []
    for pattern in _ASSUMPTION_PATTERNS:
        for match in pattern.finditer(text):
            body = (match.group("body") or "").strip(" ,.;:")
            if len(body) < 3:
                continue
            if not any(body.casefold() == item.casefold() for item in found):
                found.append(body)
    return found[:6]


# ----------------------------------------------------------------- internals


def _has_anaphora(text: str) -> bool:
    if _DEFINITE_REFERENCE.search(text):
        return True
    if not _PRONOUN.search(text):
        return False
    # "What is our current BOM?" has no pronoun; "what's blocking it?" does.
    # "Is there a decision?" uses "there" expletively, so require the question
    # to be short enough that the pronoun is carrying real weight, or to have
    # no subject of its own.
    return bool(_BARE_FOLLOWUP.match(text)) or not _subject_terms(text)


def _subject_terms(text: str) -> List[str]:
    """Content words that name a subject, rather than describe the request."""
    terms: List[str] = []
    for token in _TOKEN.findall(text or ""):
        value = _normalize(token).casefold()
        if _is_subject_term(value) and value not in terms:
            terms.append(value)
    return terms


def _normalize(token: str) -> str:
    """Strip the trailing punctuation the tokenizer keeps.

    The shared token pattern admits `.`, `_`, `-` and `@` inside a token so
    that identifiers and addresses survive retrieval intact. That also means a
    sentence-final word arrives as "week." — which matches nothing in any
    vocabulary and would be mistaken for a subject.
    """
    return (token or "").strip().strip(".,;:!?").strip()


def _definite_ambiguity(text: str, session: Any) -> str:
    """"The project" with two active projects is a question, not a reference."""
    match = _DEFINITE_REFERENCE.search(text)
    if not match:
        return ""
    phrase = match.group(0).lower()
    noun = phrase.replace("the ", "").strip()
    if noun not in ("project", "plan", "document", "doc", "thread"):
        return ""

    names = getattr(session, "active_entity_names", {}) or {}
    candidates = [names.get(entity_id, entity_id) for entity_id in getattr(session, "active_entity_ids", [])]
    candidates = [value for value in candidates if value]
    if len(candidates) < 2:
        return ""
    return (
        f"\"{phrase}\" could mean more than one thing we've discussed: "
        + ", ".join(candidates[:4])
        + ". Which did you mean?"
    )


def _describe_references(
    text: str, topics: Sequence[str], entity_ids: Sequence[str], session: Any
) -> List[Dict[str, str]]:
    """What each back-reference was taken to mean, for the trace and the UI."""
    names = getattr(session, "active_entity_names", {}) or {}
    target = topics[0] if topics else names.get(entity_ids[0], entity_ids[0]) if entity_ids else ""
    if not target:
        return []

    references: List[Dict[str, str]] = []
    seen: set = set()
    for match in _PRONOUN.finditer(text):
        token = match.group(0).lower()
        if token in seen or token == "there":
            continue
        seen.add(token)
        references.append({"reference": token, "resolved_to": target, "source": "active_topic"})
    for match in _DEFINITE_REFERENCE.finditer(text):
        phrase = match.group(0).lower()
        if phrase in seen:
            continue
        seen.add(phrase)
        references.append({"reference": phrase, "resolved_to": target, "source": "active_topic"})

    if not references:
        references.append(
            {"reference": "(implicit)", "resolved_to": target, "source": "active_topic"}
        )
    return references


def topics_from(resolved_entities: Sequence[Dict[str, Any]], text_queries: Sequence[str]) -> List[str]:
    """The subject terms worth remembering as this turn's topic.

    Canonical entity names first — they are the corpus's own vocabulary — then
    the question's surviving content terms.
    """
    topics: List[str] = []
    for entity in resolved_entities or ():
        name = str(entity.get("name") or "").strip()
        if name and name not in topics:
            topics.append(name)
    for term in text_queries or ():
        value = str(term or "").strip()
        if _is_subject_term(value) and value not in topics:
            topics.append(value)
    return topics[:MAX_CARRIED_TOPICS]


def _is_subject_term(value: str) -> bool:
    """Whether a retrieval term is worth remembering as the conversation's topic.

    Retrieval keeps terms a topic should not. "What's happening with
    certification?" plans a search for both `what's` and `certification`, and
    searching a contraction is harmless — but remembering it as the subject
    means the next turn's "it" resolves to "what's".
    """
    text = (value or "").strip()
    if len(text) < 3:
        return False
    lowered = text.casefold()
    if lowered in REQUEST_VOCABULARY or lowered in STOPWORDS:
        return False
    # "what's", "we're", "isn't" — the stem is what decides.
    stem = re.split(r"['’]", lowered)[0]
    return stem not in STOPWORDS and len(stem) >= 3
