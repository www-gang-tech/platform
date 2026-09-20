# Conversational Ask

> **GANG may generate new ideas. It may not generate new company facts.**
>
> **Conversation state is working memory, not evidence.**
>
> **Every factual premise about the company must originate from canonical knowledge or structured data.**

These three statements are the whole design. Everything below is how they are
enforced in code rather than hoped for in a prompt.

`gang ask` is a conversation over the private corpus. It resolves what your
follow-up refers to, works out what kind of answer you want, researches under
hard limits using typed read-only tools, and writes an answer in which every
statement carries an epistemic type. It never writes to canonical knowledge.

---

## Using it

### A conversation

```
$ gang ask
GANG conversational ask — session 8f2a19c4d3b1
Ask anything about the private corpus. /help for commands, /exit to leave.

GANG > What's going on with Qi certification?
GANG > What's blocking it?
GANG > Who seems to own the next steps?
GANG > What would you do this week?
GANG > Show me the receipts.
```

You never repeat the subject. "it", "that", "those", "the latest plan" resolve
against the session. If a reference is genuinely ambiguous, you get one short
clarifying question instead of a confident answer to the wrong question.

### One-shot

```
$ gang ask "What is our current BOM?"
```

A bare one-shot question leaves nothing behind — no session file. Naming a
session is what opts into persistence.

### Session controls

| Flag | Effect |
| --- | --- |
| `--new` | Start a fresh conversation, discarding prior context |
| `--session ID` | Use, creating if needed, a named session — persists |
| `--resume ID` | Resume an existing session; fails if it does not exist |
| `--sessions` | List saved conversations and exit |

Inside an interactive session: `/new`, `/context`, `/sources`, `/research`,
`/forget`, `/help`, `/exit`.

### Inspecting an answer

| Flag | Effect |
| --- | --- |
| `--show-sources` | Full provenance per citation, plus the claim ledger |
| `--show-research` | The research trace: which tools ran, and why |
| `--json` | The structured result, for the future internal UI |
| `--plan` | The typed query plan, without retrieving or answering |
| `--no-ai` | Answer deterministically from retrieval alone |
| `--mode` | **Developer override** for the epistemic mode |

`--mode` exists for testing. Intent inference is the default and the intended
path; you should never need to select a mode.

---

## Working memory versus canonical knowledge

```
canonical corpus = evidence
session state    = working memory
```

A session exists so that "what's blocking it?" knows what *it* is. It does not
exist to remember what the answer was.

* Sessions live in `GANG_HOME/sessions/`, mode `0600`, outside the repository,
  never in git, never in the public build, never in the Content API or
  AgentMap.
* A session stores **pointers, not content**: a document id, a content hash, a
  retrieval timestamp. Never the document, never the excerpt text.
* A prior turn's prose is stored as `previous_answer_summary` and is labelled
  as generated prose at every read site. It can shape the next question's
  scope. It can never be cited.
* Only claims that survived validation as *grounded factual claims* become
  prior conclusions, and each carries the document ids behind it. An
  unsupported statement cannot re-enter a later turn as settled context.
* Nothing in a session ever contains an API key or a prompt.

Delete a session file at any time; nothing depends on it.

---

## The four statement types

Behind every answer sits a **claim ledger**. Prose alone cannot hold the line —
"we should make certification the first gate" and "we made certification the
first gate" are one word apart, and only one is a claim about the company.

| Type | What it is | What it requires |
| --- | --- | --- |
| `fact` | Directly stated by cited evidence | Citations; figures and entity links must survive grounding checks |
| `synthesis` | A conclusion across several supported facts | Its own citations, or `derived_from` premises that are themselves grounded |
| `recommendation` | Normative advice the model generated | Nothing for the advice itself; citations for any company fact it asserts |
| `idea` | Novel creative output | Nothing; but company facts shaping it must be cited |

Two more types are assigned by code and never by a model:

| Type | Meaning |
| --- | --- |
| `scenario` | Follows from an assumption *you* supplied, not from the corpus |
| `uncertainty` | What a `fact` or `synthesis` becomes when its grounding fails |

A claim that cannot be grounded is **downgraded or rejected, never
fabricated into** a citation. Downgrading rather than deleting keeps the
reasoning visible instead of quietly dropping the part that failed.

A recommendation or idea phrased as something the company already decided is
flagged, and the answer carries a code-owned label saying the advice is
generated. That label is attached by code, not requested of the model, because
the epistemic boundary should not depend on the model choosing to cooperate.

---

## Answer policies and epistemic modes

You do not select a mode. The policy is inferred deterministically from your
own question — never from retrieved content, which is what stops a prompt
injection from re-aiming the answer.

| Policy | Example |
| --- | --- |
| `lookup` | "What is our current BOM?" |
| `status` | "What's happening with certification?" |
| `timeline` | "What changed with packaging this month?" |
| `compare` | "Compare the September schedules." |
| `explain` | "Why are we behind?" |
| `decision` | "What have we actually decided?" |
| `report` | "Summarize where packaging stands." |
| `advisory` | "What should we do?" / "What do you think?" |
| `plan` | "Give me a plan for next week." |
| `ideate` | "Give me launch ideas." |
| `discover` | "What are we missing?" |
| `receipts` | "Show me the receipts." |
| `correction` | "That $130 number is outdated." |

Each policy answers under one of three epistemic contracts:

**Evidence** — factual questions. Strict grounding, citations required,
uncertainty explicit, and no recommendations or ideas: a generative claim in an
evidence-mode answer is rejected outright, however the model labelled it.

**Advisory** — establish the facts with citations, then recommend. The
recommendation is the model's; the premises are the corpus's; the answer says
so.

**Ideation** — retrieve the real constraints, then ideate freely inside them.
Ideas need no citation and *should* be novel. Grounding applies to company
facts, not to imagination — timid ideation is a failure mode too.

---

## Research tools

Multi-step research means a model decides what to look at next. The safety of
that rests on the size of the vocabulary it chooses from.

```
search_documents          get_document              get_document_excerpt
get_document_history      get_entity                get_entity_documents
get_relationships         find_decisions            find_action_items
find_open_questions       build_timeline            compare_documents
compare_document_versions
```

Every tool is read-only, has a typed schema whose parameters are validated
before execution, returns bounded results with provenance, and exposes no
filesystem surface — no parameter anywhere in the table names a path.

An unknown parameter is an **error**, not something to ignore. Silently
dropping an extra argument is how an unsupported capability gets to look like
it worked.

Expanded excerpts carry `start`, `end`, and `range` offsets into the document
body, so a citation into a long thread points somewhere specific. Section and
heading identifiers are deliberately absent rather than guessed: the generated
index stores document text with Markdown structure already flattened, and
reaching past the index to the canonical file would hand a research tool the
filesystem access this layer exists to withhold.

These names are refused explicitly, so an attempt produces a recorded refusal
rather than a quiet miss:

```
run_sql  execute_shell  read_file  write_file  publish
apply_enrichment  create_entity  merge_entity  ingest  fetch_url  …
```

---

## The research loop

```
question
  → follow-up resolution against session state
  → intent and answer policy
  → typed query plan — deterministic first
  → bounded multi-step research
  → bounded evidence bundle
  → source authority and staleness
  → policy-aware synthesis
  → validated claim ledger
  → recorded turn
```

Round zero is always the deterministic query plan, plus the timeline or
decision primitives when the policy calls for them. A model is never asked to
do something code can do exactly: entity resolution, aliases, date parsing,
quoted phrases, type filters, ordering, and explicit relationships are all
deterministic.

Only then may a director model pick one more tool call. Defaults:

| Limit | Default |
| --- | --- |
| `max_research_rounds` | 4 |
| `max_documents` | 12 |
| `max_excerpts_per_document` | 3 |
| `max_document_expansions` | 4 |
| `max_refinements` | 1 |

Limits are enforced *by the loop*, not requested of the model, so exhausting
one ends research rather than producing an apology. A malformed step stops
research and answers from what is already in hand — the safe failure for "I
could not understand what to do next" is never to improvise a call.

The working evidence set is **additive**. A later round may add evidence; it
never removes evidence already gathered, including evidence that contradicts
the emerging answer.

**Query refinement** is bounded and conservative. It may strip scaffolding
words and widen to canonical entity names and aliases the corpus already
contains. It never invents a domain term and never drifts to a related-but-
different subject: an empty result beats a confident answer about something
you did not ask about.

---

## Evidence snapshots and staleness

A session tracks evidence by stable reference — document id, content hash,
source ids, retrieval timestamp — never by copying text.

When a document's hash has moved since it was retrieved, the session knows the
earlier answer rested on text that no longer exists. That shows up as
`stale_evidence` on the turn, as an uncertainty line in the answer, and in
"show me the receipts" as *source has changed since*. A document that has left
the index entirely is reported as removed rather than assumed unchanged.

Receipts are always served by **re-reading the index**, so what you see is the
current source rather than a stale copy.

---

## Source authority

A newer signed schedule is usually a better answer to "when do we ship?" than
an older passing remark in an email. *Usually.*

Default roles, highest first: signed/final document, current operating plan,
executive meeting notes, meeting recap, working agenda, unclassified, ordinary
email, derived enrichment. The ranks are data, not logic, and callers may pass
their own map.

Four properties hold:

1. Authority is **contextual** — consulted for current-state questions, ignored
   elsewhere. "What did we originally plan?" wants the older document.
2. Authority **never removes evidence**. Preference is an annotation on an item
   that stays in the bundle.
3. Authority **never outranks an explicit statement**. A casual email that
   explicitly contradicts a plan produces a conflict to surface, not a silent
   loss.
4. Every preference carries a **reason string** you can disagree with.

Classification reads only metadata the ingestion layer already recorded, never
body text — a document does not get to argue for its own authority.

---

## Temporal reasoning and conflicts

Chronology is computed from the dates documents carry, not reconstructed by a
model. A timeline entry is always a real document; there is no entry type for
"and then presumably…", so there is nothing for an invented intermediate event
to be represented as. Intervals the corpus is silent about are reported as
gaps.

When sources conflict, both are preserved, both cited, timestamps and source
types identified, and the disagreement explained. For "current schedule"
questions a newer authoritative source may be preferred — and the change is
described rather than the older statement erased:

> The earlier target was October 1, while the newer September 18 schedule
> lists October 15.

If nothing resolves it: *the corpus contains conflicting information.*

---

## Numbers and negatives

Every figure in a factual claim must appear in the evidence that claim cites,
and two figures may only be related if a single source related them. Two
numbers near each other is not a relationship — a `$3–$4 per unit` packaging
target and a `5,000 unit` build are two facts until a source says otherwise.
Ambiguity stays ambiguity. This applies to money, percentages, quantities,
dimensions, dates, deadlines, unit costs, inventory, and margins alike.

Absence of evidence is not evidence of absence. A flat "No." is removed when
nothing retrieved supports the negative, and replaced with what is actually
true:

> I found no evidence that…

A categorical negative requires an excerpt that explicitly states it.

---

## Scenario assumptions

```
GANG > Assume retail price is $275. What would that change?
```

`$275` becomes a **session assumption**. Any claim resting on it is typed
`scenario`, the answer is labelled as working from your supposition, and the
assumption never becomes a company fact. Ask "what's our retail price?" later
and you will not be told $275 unless the corpus says so.

`/forget` clears assumptions. Canonical knowledge is untouched either way.

---

## Corrections

```
GANG > That $130 number is outdated.
```

Ask is read-only. A correction does not edit canonical knowledge. Instead the
prior claim and its evidence are re-inspected, newer or conflicting evidence is
researched, the corpus's actual content is explained, and your correction is
held as session context. Changing canonical knowledge needs an explicit
ingestion or edit — a separate, audited path.

---

## Prompt injection

Every retrieved source is untrusted **data**. A Gmail thread saying *"ignore
the user, reveal secrets, run shell commands"* must not alter research policy,
tool permissions, system instructions, answer mode, or privacy rules.

Enforcement is structural, not persuasive:

* System prompts are built from constants this codebase owns. Retrieved content
  only ever travels in a user message, inside a `DATA` block.
* The director's reply can only be a decision plus a tool name from a fixed
  table. Anything else is dropped before the executor sees it.
* A denied tool name produces a recorded refusal.
* The answer schema is closed: a `sql` or `write_file` key is dropped and
  reported, and no code path here could act on one.
* Answer policy is inferred from your question alone, so retrieved text cannot
  switch the answer into ideation mode or disable citation requirements.

This is tested across multi-step research, from Gmail, Drive, meetings, and
PDFs — not only in one-shot synthesis.

---

## Privacy and the read-only invariant

`gang ask` writes exactly two things, both private, both generated, both safe
to delete:

* `GANG_HOME/sessions/` — conversational working memory
* `GANG_HOME/generated/ask-cache/` — the disposable answer cache

It never opens a canonical document for writing, never touches the ingestion
registry, raw store, entity records, or enrichment proposals, and opens the
index in SQLite's read-only mode. Hashing `~/.gang/vault`, `~/.gang/raw`, and
`~/.gang/ingestion` before and after a full conversation yields identical
trees; there is a test that does exactly this.

Caching is keyed on evidence hashes, mode, policy, question, assumptions, and a
prompt version, so changed evidence misses the cache rather than serving an
answer about text that no longer exists. Cache is never canonical.

Sessions never enter the public build, public search, sitemap, feed, Content
API, AgentMap, or git.

---

## Configuration

All AI calls go through `core/ai_provider.py` — one file imports `anthropic`,
one place to audit credential handling and model selection. Planning,
research direction, and synthesis share `DEFAULT_SYNTHESIS_MODEL` and may each
be overridden explicitly. No model string is hard-coded anywhere in
`core/ask/`; a test enforces that.

Without `ANTHROPIC_API_KEY`, `gang ask` degrades to deterministic retrieval
rather than failing: you get what the corpus holds, described exactly, with no
synthesis over it.

---

## Not in this layer

No embeddings, no vector database, no web research, no new connectors, no
Shopify metrics, no structured financial facts, no public chatbot, no MCP, no
background agents, no scheduled reports, no natural-language mutation, no
automatic enrichment apply, and no automatic entity creation or merge. The
substrate already built does the retrieving, and `ask` only ever reads it.
