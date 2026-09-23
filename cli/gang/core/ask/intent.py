"""What is this question actually asking for? Decided by code, not by a model.

The user never selects a mode. They ask "what's happening with certification?"
and then "what would you do?", and the second question needs a different
epistemic contract from the first: the first may only report what the corpus
says, the second is allowed to recommend something nobody has written down.

Two things are inferred here, both deterministically:

* an **answer policy** — the shape of the answer (lookup, timeline, decision,
  plan, ideation, …), which drives which research primitives are worth running;
* an **epistemic mode** — evidence, advisory, or ideation — which drives what
  the synthesis layer is permitted to generate.

Keyword inference is deliberate. It is inspectable, testable, costs nothing,
and cannot be talked out of its answer by a retrieved document, because it only
ever sees the user's own question. A model that also guessed the mode would be
a model that a prompt injection could re-aim (§33).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


# ------------------------------------------------------------------ policies

LOOKUP = "lookup"
DEFINITION = "definition"
STATUS = "status"
TIMELINE = "timeline"
COMPARE = "compare"
EXPLAIN = "explain"
DECISION = "decision"
AFFILIATION = "affiliation"
OWNERSHIP = "ownership"
REPORT = "report"
ADVISORY = "advisory"
PLAN = "plan"
IDEATE = "ideate"
DISCOVER = "discover"

#: Two conversational policies beyond the eleven answer shapes. They are about
#: the conversation rather than the corpus: one re-opens the previous answer's
#: evidence (§31), the other handles being told the previous answer was wrong
#: (§32). Both are still strictly read-only.
RECEIPTS = "receipts"
CORRECTION = "correction"

POLICIES = (
    LOOKUP,
    DEFINITION,
    STATUS,
    TIMELINE,
    COMPARE,
    EXPLAIN,
    DECISION,
    AFFILIATION,
    OWNERSHIP,
    REPORT,
    ADVISORY,
    PLAN,
    IDEATE,
    DISCOVER,
    RECEIPTS,
    CORRECTION,
)


# --------------------------------------------------------------------- modes

EVIDENCE = "evidence"
ADVISORY_MODE = "advisory"
IDEATION = "ideation"

MODES = (EVIDENCE, ADVISORY_MODE, IDEATION)

#: Which epistemic contract each policy answers under. Everything defaults to
#: the strictest one; only the policies that exist to generate something new
#: are allowed out of it.
POLICY_MODES = {
    LOOKUP: EVIDENCE,
    DEFINITION: EVIDENCE,
    STATUS: EVIDENCE,
    TIMELINE: EVIDENCE,
    COMPARE: EVIDENCE,
    EXPLAIN: EVIDENCE,
    DECISION: EVIDENCE,
    AFFILIATION: EVIDENCE,
    OWNERSHIP: EVIDENCE,
    REPORT: EVIDENCE,
    DISCOVER: EVIDENCE,
    RECEIPTS: EVIDENCE,
    CORRECTION: EVIDENCE,
    ADVISORY: ADVISORY_MODE,
    PLAN: ADVISORY_MODE,
    IDEATE: IDEATION,
}


# ------------------------------------------------------------------ patterns

#: Who an ownership question is about: a capitalized name as the user typed
#: it, or the first person. Case-sensitive on purpose, so "what does it need
#: to do?" and "what do we need to do?" are not read as questions about a
#: person called "it" or "we".
_NAME = r"[A-Z][\w-]*(?:['’][A-Z][\w-]*)?(?:\s+[A-Z][\w-]*(?:['’][A-Z][\w-]*)?){0,2}"
_SUBJECT = r"(?P<subject>\b[Ii]\b|\b[Mm]e\b|" + _NAME + r")"
_POSSESSIVE = r"(?:(?P<subject>\b[Mm]y)\b|(?P<owner>" + _NAME + r")['’]s)"

#: Capitalized words that open a clause rather than name a person.
_NOT_A_SUBJECT = frozenset(
    """
    it we they he she you this that these those the there everyone anyone someone
    everybody anybody somebody nobody what who which
    """.split()
)


class _AnyOf:
    """Several patterns read as one table entry; the first to match wins.

    Ownership phrasing puts the person in different places ("what does X need
    to do", "X's action items", "what is due for X"), and a regex group can
    only be named once per pattern, so each shape is its own pattern.
    """

    def __init__(self, *patterns: re.Pattern):
        self.patterns = patterns

    def search(self, text: str):
        for pattern in self.patterns:
            for found in pattern.finditer(text):
                if _subject_of(found).casefold() not in _NOT_A_SUBJECT:
                    return found
        return None


def _subject_of(found: "re.Match") -> str:
    groups = found.groupdict()
    return (groups.get("subject") or groups.get("owner") or "").strip()


#: Work explicitly assigned to one person. Ahead of affiliation, decision,
#: and definition, because "what does Daniel need to do?" looks like all three
#: to a looser pattern — "what does X … do" is a definition shape, and a bare
#: "action items" is a decision shape — and is none of them: it asks for a
#: task list scoped to an owner. It still sits behind advice and planning, so
#: "what should I do this week?" keeps asking for a recommendation.
_OWNERSHIP = _AnyOf(
    re.compile(
        r"(?i:\bwhat\s+(?:else\s+)?(?:does|do|did)\s+)" + _SUBJECT
        + r"(?i:\s+(?:still\s+)?(?:need|have|has|got)\s+to\s+(?:do|deliver|finish|handle|get\s+done)\b)"
    ),
    re.compile(
        r"(?i:\bwhat\s+(?:is|are|am|was|were)\s+)" + _SUBJECT
        + r"(?i:\s+(?:supposed|expected|meant|scheduled|assigned|due)\s+to\s+(?:do|deliver|handle|finish)\b)"
    ),
    re.compile(
        r"(?i:\bwhat\s+(?:is|are|am)\s+)" + _SUBJECT
        + r"(?i:\s+(?:responsible|accountable|on\s+the\s+hook)\s+for\b)"
    ),
    re.compile(r"(?i:\bwhat\s+(?:does|do)\s+)" + _SUBJECT + r"(?i:\s+own\b)"),
    re.compile(
        r"(?i:\bwhat(?:'s|\s+is|\s+are)?\s+(?:still\s+|currently\s+)?"
        r"(?:due|assigned|outstanding|open|pending|overdue)\s+(?:for|to|from)\s+)" + _SUBJECT + r"\b"
    ),
    re.compile(
        r"(?i:\b(?:action\s+items?|tasks?|to-?dos?|deliverables?|assignments?)\s+"
        r"(?:for|assigned\s+to|owned\s+by|on)\s+)" + _SUBJECT + r"\b"
    ),
    re.compile(
        r"(?i:\bwhat\s+(?:tasks?|action\s+items?|deliverables?)\s+(?:does|do|is|are|am)\s+)" + _SUBJECT
        + r"(?i:\s+(?:have|has|own|owns|assigned|responsible|working))"
    ),
    re.compile(
        _POSSESSIVE
        + r"(?i:\s+(?:(?:open|current|outstanding|pending|remaining|upcoming|next)\s+)?"
        r"(?:action\s+items?|tasks?|to-?dos?|to-?do\s+list|deliverables?|assignments?|"
        r"responsibilities|plate)\b)"
    ),
)


#: Ordered. The first pattern that matches wins, so the list runs from the most
#: specific intent to the most general. Every entry is anchored on phrasing a
#: person would actually type.
_PATTERNS: Tuple[Tuple[str, Any], ...] = (
    (
        RECEIPTS,
        re.compile(
            r"\b(?:show|give)\s+(?:me\s+)?the\s+receipts\b"
            r"|\bwhat(?:'s| is| are)\s+(?:that|this|it|you)\s+based\s+(?:on|upon)\b"
            r"|\bwhat\s+are\s+you\s+basing\s+(?:that|this|it)\s+on\b"
            r"|\bwhere\s+did\s+(?:that|this|it)\s+come\s+from\b"
            r"|\bwhere(?:'s| is)\s+(?:that|this)\s+from\b"
            r"|\b(?:cite|citation|sources?)\s+(?:for\s+)?(?:that|this|it)\b"
            r"|\bhow\s+do\s+you\s+know\s+(?:that|this)\b",
            re.IGNORECASE,
        ),
    ),
    (
        CORRECTION,
        re.compile(
            r"\bthat(?:'s| is)\s+(?:wrong|incorrect|not right|outdated|out of date|stale)\b"
            r"|\bthis\s+is\s+(?:wrong|incorrect|outdated)\b"
            r"|\b(?:is|are|was|were)\s+(?:outdated|out of date|stale|no longer (?:true|current|right))\b"
            r"|\byou(?:'re| are)\s+(?:wrong|mistaken|incorrect)\b"
            r"|\bthat number\s+is\s+\w+",
            re.IGNORECASE,
        ),
    ),
    (
        IDEATE,
        re.compile(
            r"\bbrainstorm\b"
            r"|\b(?:give|show)\s+me\s+(?:\w+\s+){0,3}"
            r"(?:ideas?|concepts?|alternatives?|options)\b"
            r"|\b(?:ideas?|concepts?|alternatives?|options)\s+for\b"
            r"|\b(?:launch|campaign|naming|marketing|product)\s+ideas?\b"
            r"|\bunconventional\b"
            r"|\bways\s+(?:we\s+)?could\b"
            r"|\bwhat\s+if\s+we\b"
            r"|\bcome\s+up\s+with\b"
            r"|\bthree\s+ways\b|\bfive\s+ways\b|\bten\s+ways\b",
            re.IGNORECASE,
        ),
    ),
    (
        PLAN,
        re.compile(
            r"\b(?:give|draw|write|make)\s+(?:me\s+)?a\s+plan\b"
            r"|\ba\s+plan\s+for\b"
            r"|\bplan\s+for\s+(?:this|next|the)\s+(?:week|month|quarter|sprint)\b"
            r"|\broadmap\b"
            r"|\bwhat\s+should\s+(?:we|i)\s+do\s+(?:this|next)\s+(?:week|month|quarter)\b"
            r"|\bwhat\s+would\s+you\s+do\s+(?:this|next)\s+(?:week|month|quarter)\b"
            r"|\bprioriti[sz]e\b",
            re.IGNORECASE,
        ),
    ),
    (
        ADVISORY,
        re.compile(
            r"\bwhat\s+should\s+(?:we|i|they)\b"
            r"|\bwhat\s+would\s+you\s+(?:do|change|recommend|suggest|focus)\b"
            r"|\bwhat\s+do\s+you\s+think\b"
            r"|\byour\s+(?:opinion|take|view|advice|recommendation)\b"
            r"|\brecommend\b|\bsuggest\b|\badvice\b"
            r"|\bhow\s+should\s+(?:we|i)\b"
            r"|\bshould\s+we\b",
            re.IGNORECASE,
        ),
    ),
    (
        DISCOVER,
        re.compile(
            r"\bwhat\s+(?:are\s+we|am\s+i)\s+missing\b"
            r"|\bwhat\s+(?:don't|do not|haven't|have not)\s+(?:we|i)\b"
            r"|\bwhat\s+else\s+(?:should|do|is)\b"
            r"|\bblind\s+spots?\b"
            r"|\bgaps?\s+(?:in|we)\b"
            r"|\banything\s+(?:we|i)\s+(?:missed|are missing|should)\b",
            re.IGNORECASE,
        ),
    ),
    (OWNERSHIP, _OWNERSHIP),
    (
        AFFILIATION,
        re.compile(
            r"\bwho(?:'s| is| are| was| were)?\s+(?:all\s+)?(?:on|in)\s+the\s+"
            r"(?:team|crew|group|project|company)\b"
            r"|\bwho\s+(?:works?|worked|is working|are working|has worked|have worked)\s+"
            r"(?:on|with|for)\b"
            r"|\bwho(?:'s| is| has| have)?\s*(?:been\s+)?involved\b"
            r"|\bwho\s+seems?\s+(?:to\s+be\s+)?(?:responsible|involved|to own)\b"
            r"|\bwho\s+(?:else\s+)?(?:is|are)\s+(?:part\s+of|around|here)\b"
            r"|\bwho\s+(?:are|is)\s+(?:the\s+)?(?:people|team|players|participants)\b"
            r"|\bwho\s+(?:attends?|attended|shows?\s+up|turns?\s+up)\b"
            r"|\bthe\s+team\b.{0,20}\bwho\b",
            re.IGNORECASE,
        ),
    ),
    (
        DECISION,
        re.compile(
            r"\bwhat\s+(?:have|did|has)\s+(?:we|they)\s+(?:actually\s+)?(?:decided|agreed|settled)\b"
            r"|\bwhat\s+(?:decisions?|action items?|open questions?)\b"
            r"|\b(?:needs?|requires?|still needs?)\s+(?:a\s+)?decision\b"
            r"|\bopen\s+questions?\b"
            r"|\baction\s+items?\b"
            r"|\bwho\s+(?:owns?|is responsible|is accountable|signs? off)\b"
            r"|\bwho\s+seems?\s+to\s+own\b"
            r"|\bwhat\s+is\s+\w+\s+responsible\s+for\b"
            r"|\bundecided\b",
            re.IGNORECASE,
        ),
    ),
    (
        COMPARE,
        re.compile(
            r"\bcompare\b"
            r"|\bdifference(?:s)?\s+between\b"
            r"|\bhow\s+does\s+.+\s+(?:compare|differ)\b"
            r"|\bversus\b|\bvs\.?\b"
            r"|\b(?:changed|differ)\s+between\b",
            re.IGNORECASE,
        ),
    ),
    (
        TIMELINE,
        re.compile(
            r"\bhistory\s+of\b"
            r"|\btimeline\b"
            r"|\bwhat\s+changed\b"
            r"|\bwhat(?:'s| has)\s+changed\b"
            r"|\bhow\s+did\s+.+\s+(?:get|go|move|change)\s+from\b"
            r"|\bover\s+time\b"
            r"|\bevolution\s+of\b"
            r"|\bwhen\s+did\s+.+\s+change\b",
            re.IGNORECASE,
        ),
    ),
    (
        EXPLAIN,
        re.compile(
            r"^\s*why\b"
            r"|\bwhy\s+(?:are|is|do|does|did|would|were|was|have|has)\b"
            r"|\bhow\s+come\b"
            r"|\bexplain\b"
            r"|\bwhat(?:'s| is)\s+causing\b"
            r"|\breason\s+(?:for|why)\b",
            re.IGNORECASE,
        ),
    ),
    (
        REPORT,
        re.compile(
            r"\b(?:give|write)\s+me\s+a\s+(?:report|summary|brief|rundown|overview)\b"
            r"|\bsummari[sz]e\b"
            r"|\bbrief\s+me\b"
            r"|\boverview\s+of\b"
            r"|\bwhere\s+do\s+things\s+stand\b",
            re.IGNORECASE,
        ),
    ),
    (
        STATUS,
        re.compile(
            r"\bwhat(?:'s| is)\s+(?:happening|going on|up)\s+with\b"
            r"|\bstatus\s+of\b|\bcurrent\s+status\b"
            r"|\bwhere\s+are\s+we\s+(?:on|with)\b"
            r"|\bcurrent\s+state\b"
            r"|\bwhat(?:'s| is)\s+blocking\b"
            r"|\bblocked\s+(?:on|by)\b"
            r"|\bhow(?:'s| is)\s+.+\s+going\b"
            r"|\bon\s+track\b"
            r"|\bwhat(?:'s| is)\s+the\s+(?:latest|current)\b",
            re.IGNORECASE,
        ),
    ),
    (
        DEFINITION,
        re.compile(
            # Last in the table on purpose. A question that looks like status,
            # discovery, or advice is that; only a bare "what is X" falls
            # through to here. Excluding a leading determiner is what keeps
            # "what is our current BOM?" a value lookup rather than a definition.
            r"^\s*(?:so\s+)?(?:what|who)(?:'s|\s+is|\s+are|\s+was|\s+were)\s+"
            r"(?!our\b|my\b|your\b|their\b|its\b|the\b|this\b|that\b|these\b|those\b)"
            r"(?:a\s+|an\s+)?[\w&.'-]+(?:\s+[\w&.'-]+){0,3}\s*\??\s*$"
            r"|\bwhat\s+does\s+[\w&.'-]+(?:\s+[\w&.'-]+){0,3}\s+do\b"
            r"|^\s*tell\s+me\s+about\s+"
            r"|^\s*describe\s+"
            r"|\bwhat\s+kind\s+of\s+(?:company|business|product|project)\b",
            re.IGNORECASE,
        ),
    ),
)


#: A question that supposes something rather than asking about it. The supposed
#: value is a scenario input, never a company fact (§24, §25).
_SCENARIO_PATTERN = re.compile(
    r"\bassume\b|\bassuming\b|\bsuppose\b|\bhypothetical(?:ly)?\b"
    r"|\bif\s+.{0,80}?\bwer[et]\b|\bif\s+.{0,60}?\bslips?\b"
    r"|\bwhat\s+if\b|\bpretend\b|\bsay\s+(?:that\s+)?(?:the\s+)?price\s+(?:is|were|was)\b",
    re.IGNORECASE,
)

#: "Show me the documents" is retrieval; it does not need prose over it.
_LISTING_PATTERN = re.compile(
    r"^\s*(show|list|find|search|display|give)\b.{0,80}?"
    r"\b(documents?|files?|emails?|threads?|notes?|sources?|everything|anything)\b",
    re.IGNORECASE,
)

#: "What is required?" is a question about obligations, and an obligation is
#: the kind of thing a certification body states and an internal recap
#: paraphrases. Recognizing the shape lets synthesis insist on the source that
#: imposed the requirement rather than the one that mentioned it.
_REQUIREMENT_QUESTION = re.compile(
    r"\b(?:required|requirement|requirements|require|requires)\b"
    r"|\bmust\b|\bmandatory\b|\bobligated\b|\bobligation\b"
    r"|\bneed(?:ed|s)?\s+(?:to|for)\b|\bnecessary\b"
    r"|\bprerequisites?\b|\bwhat\s+do\s+we\s+have\s+to\b",
    re.IGNORECASE,
)


def asks_for_requirements(question: str) -> bool:
    """Whether the question asks what is required rather than what happened."""
    return bool(_REQUIREMENT_QUESTION.search(question or ""))


#: Policies whose answer is mostly about *when*, and so benefit from the
#: deterministic timeline primitive being run up front (§12).
TEMPORAL_POLICIES = frozenset({TIMELINE, COMPARE, STATUS})

#: Policies answered first from authored identity, before any email traffic
#: is considered (§ foundational knowledge).
FOUNDATIONAL_POLICIES = frozenset({DEFINITION})

#: Policies served by the structured decision/action/open-question primitives
#: rather than by generic text retrieval (§13).
STRUCTURED_POLICIES = frozenset({DECISION, DISCOVER, PLAN})

#: Policies answered by assembling who is involved, from participation
#: signals rather than from a roster document.
PEOPLE_POLICIES = frozenset({AFFILIATION})

#: Policies answered from work explicitly assigned to one person, never from
#: participation and never from an authored description (§ ownership).
ASSIGNMENT_POLICIES = frozenset({OWNERSHIP})


@dataclass(frozen=True)
class Intent:
    """The resolved reading of one question. Inert data."""

    policy: str = LOOKUP
    mode: str = EVIDENCE
    scenario: bool = False
    listing: bool = False
    matched: str = ""
    #: Whom an ownership question is about, exactly as written ("Daniel",
    #: "I", "me"). Resolved to a person later, against canonical names and
    #: verified aliases; never guessed here.
    subject: str = ""

    @property
    def allows_recommendation(self) -> bool:
        return self.mode in (ADVISORY_MODE, IDEATION)

    @property
    def allows_idea(self) -> bool:
        return self.mode == IDEATION

    @property
    def wants_people(self) -> bool:
        """Whether this question is about who is involved with something."""
        return self.policy in PEOPLE_POLICIES

    @property
    def wants_assignments(self) -> bool:
        """Whether this question asks for the work assigned to one person."""
        return self.policy in ASSIGNMENT_POLICIES

    @property
    def wants_identity(self) -> bool:
        """Whether authored identity should answer this before evidence does."""
        return self.policy in FOUNDATIONAL_POLICIES

    @property
    def wants_timeline(self) -> bool:
        return self.policy in TEMPORAL_POLICIES

    @property
    def wants_structured(self) -> bool:
        return self.policy in STRUCTURED_POLICIES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "policy": self.policy,
            "mode": self.mode,
            "scenario": self.scenario,
            "listing": self.listing,
            "matched": self.matched,
            "subject": self.subject,
        }


def infer_intent(question: str, *, override_mode: Optional[str] = None) -> Intent:
    """Read a question's answer policy and epistemic mode. Never asks a model.

    ``override_mode`` exists for development and tests only; the CLI exposes it
    behind a flag that ordinary use never needs (§27). It widens or narrows
    what synthesis may generate, and cannot come from retrieved content.
    """
    text = (question or "").strip()
    policy, matched, subject = _match_policy(text)
    mode = POLICY_MODES.get(policy, EVIDENCE)

    if override_mode:
        if override_mode not in MODES:
            raise ValueError(f"Unsupported answer mode: {override_mode}")
        mode = override_mode

    return Intent(
        policy=policy,
        mode=mode,
        scenario=bool(_SCENARIO_PATTERN.search(text)),
        listing=bool(_LISTING_PATTERN.search(text)),
        matched=matched,
        subject=subject,
    )


def _match_policy(text: str) -> Tuple[str, str, str]:
    for policy, pattern in _PATTERNS:
        found = pattern.search(text)
        if found:
            subject = _subject_of(found) if policy == OWNERSHIP else ""
            return policy, found.group(0).strip(), subject
    return LOOKUP, "", ""


# ------------------------------------------------------------- explanations

#: Shown in diagnostics so an inferred policy is never a black box (§37).
POLICY_DESCRIPTIONS = {
    LOOKUP: "Retrieve what the corpus states about a subject.",
    DEFINITION: "Answer what something is, from authored canonical identity first.",
    STATUS: "Report the current state of something, newest evidence first.",
    TIMELINE: "Narrate how something changed, in chronological order.",
    COMPARE: "Set two things side by side and describe the differences.",
    EXPLAIN: "Explain a cause, using evidence for each premise.",
    DECISION: "Retrieve decisions, action items, and open questions structurally.",
    AFFILIATION: "Assemble who is involved, from participation signals rather than a roster.",
    OWNERSHIP: "List the work explicitly assigned to one person, from owners stated in the evidence.",
    REPORT: "Summarize a topic across the evidence found.",
    ADVISORY: "Recommend a course of action, grounded in cited facts.",
    PLAN: "Propose a concrete plan, grounded in cited facts.",
    IDEATE: "Generate new ideas within the constraints the corpus establishes.",
    DISCOVER: "Identify what the corpus does not cover or settle.",
    RECEIPTS: "Re-present the evidence behind the previous answer.",
    CORRECTION: "Re-examine a prior claim against the corpus, without mutating it.",
}

MODE_DESCRIPTIONS = {
    EVIDENCE: "Facts only, every claim cited; absence reported as absence.",
    ADVISORY_MODE: "Recommendations allowed; their factual premises must be cited.",
    IDEATION: "Novel ideas allowed; company facts shaping them must be cited.",
}


def describe(intent: Intent) -> Dict[str, str]:
    return {
        "policy": intent.policy,
        "policy_description": POLICY_DESCRIPTIONS.get(intent.policy, ""),
        "mode": intent.mode,
        "mode_description": MODE_DESCRIPTIONS.get(intent.mode, ""),
        "matched": intent.matched,
        "subject": intent.subject,
    }
