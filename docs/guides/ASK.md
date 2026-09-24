# Ask

`gang ask` answers questions about the private corpus from evidence it actually
retrieved, and cites the documents that support each claim.

```text
question
    ↓
deterministic query planning      ← exact names, quoted phrases, real dates
    ↓
FTS + metadata + entity + relationship retrieval
    ↓
bounded evidence set              ← 5–10 canonical documents
    ↓
synthesis
    ↓
answer + citations
```

This is a query engine, not a chat surface. There is no vector database, no
embedding store, no hosted search, and no agent loop — retrieval runs on the
SQLite FTS index, entity mentions, and relationship assertions that already
exist.

```bash
gang ask "What did we decide about the mounting plate?"
gang ask "What changed with Qi2 certification this month?"
gang ask "What has Frank been working on with Eliro?"
```

## Read-only

`gang ask` cannot change anything. It never edits documents, applies enrichment,
creates entities, adds relationships, publishes content, or touches a source
system, and it opens the generated index in SQLite's read-only mode. The one
thing it writes is a disposable answer cache under
`GANG_HOME/generated/ask-cache/`.

Natural-language *mutation* is deliberately absent. It belongs to a separate
typed-command architecture with its own review and audit trail.

## Deterministic first

The model is not required to search. Before any AI call, code resolves what can
be resolved exactly:

```text
"mounting plate"      quoted phrase, preserved verbatim
Frank                 exact alias → canonical entity ID
this month            → 2026-09-01 .. 2026-09-20
--type agenda         explicit filter
```

A question with a quoted phrase or a resolved entity never calls the planner
model at all. The model is consulted only when genuine ambiguity remains, and
what it returns is re-validated and intersected with the vocabulary this corpus
actually has — unknown entity IDs, document types, and source types are dropped.

Inspect the plan without answering:

```bash
gang ask "What changed since 2026-09-01?" --plan
```

## The typed query plan

A plan is inert, versioned, schema-validated JSON:

```json
{
  "version": "1",
  "query": "What changed with Qi2 certification this month?",
  "text_queries": ["changed", "qi2", "certification"],
  "entity_ids": ["01a0bd04-25fd-7e4f-a0df-b3fff29c3fcf"],
  "relationship_filters": [],
  "document_types": [],
  "source_types": [],
  "date_range": {"field": "updated", "start": "2026-09-01", "end": "2026-09-20"},
  "order": "recency",
  "limit": 8
}
```

There is no field for SQL, no field for a path, and no field that mutates. A
plan carrying an unsupported field is rejected outright rather than partially
honored, and every value reaches SQLite as a bound parameter.

## Ranking

Deterministic and explainable. A document earns its place by how many *kinds* of
signal it satisfies — full text, entity mention, relationship, metadata filter —
with term coverage, BM25, and recency breaking ties inside a tier. Each evidence
item reports its own signals:

```json
{"signal_classes": 2, "text_term_hits": 2, "entity_matches": 1, "relationship_matches": 0}
```

These are counts, not probabilities. Nothing here knows a probability, so
nothing here reports one.

Once entity or relationship retrieval succeeds, a document matching only one
loose word is dropped — otherwise every document containing "working" would
crowd out the ones that actually mention Frank.

## Temporal questions

`today`, `yesterday`, `this week`, `last week`, `this month`, `last month`,
`last 30 days`, `since DATE`, and `before DATE` resolve to an explicit range
*before* retrieval, so the window cannot drift between planning and synthesis.
Weeks start Monday; ranges are inclusive.

```bash
gang ask "What moved last week?"
gang ask "What changed with packaging?" --since 30d --until 2026-09-18
```

## Ambiguous names are never guessed

If `Frank` matches two people, retrieval uses no entity ID and the answer says
so:

```text
"Frank" is ambiguous in this corpus — it could be Frank Godchaux (01a0…),
Frank Ocampo (01a0…). I did not guess which one you meant.
```

That notice is written by code, not by the model, so it appears whether or not
the model chose to mention it. Disambiguate with an ID:

```bash
gang ask "What has he been working on?" --entity 01a0bd04-22ff-70e8-a8ac-bce6b40ca792
```

## Current vs stale enrichment

Canonical source content is authoritative; derived enrichment is not. Every
evidence item carries a status:

```text
current   human-authored, or the applied proposal still matches the document
stale     enrichment was applied, then the document changed
none      no derived enrichment
```

Stale enrichment travels in a separate `stale_enrichment` field with an explicit
warning. It can be shown as historical background; it is never presented as
current fact, and source excerpts are always preferred.

## Claims, conflicts, and uncertainty

Each claim is marked `explicit` (one source states it), `derived` (several
sources combined), or `uncertain` (incomplete or conflicting). Disagreement is
surfaced rather than resolved:

```text
The earlier target was Oct 1, but the Sep 18 agenda lists Oct 15 as the newer
target. [1][2]
```

Older evidence is never dropped in favor of newer — both stay in the bundle, and
`temporal_ordering` exposes their dates.

When the corpus does not support an answer, `gang ask` says so instead of
guessing:

```text
I couldn't find evidence of a final decision to switch manufacturers.
```

## Absence of evidence is not a denial

"I found no evidence that X" and "X did not happen" are different claims, and
only the second one needs evidence nobody has. Asked *"Did we decide to
manufacture the charger on Mars?"*, an answer beginning **"No."** would be
asserting something about the world on the strength of a failed search.

So when nothing cited supports a negative, flat denials are removed from the
answer and replaced with what is actually true:

```text
I found no evidence in the retrieved corpus about this. That is an absence of
evidence, not a denial: it does not establish that the answer is no.
```

Sentences that already speak about the corpus — "I found no evidence that…",
"The retrieved corpus does not establish…", "There is no mention of X in the
retrieved documents" — are left alone, and so is any other context the answer
gave about what the corpus *does* contain. A categorical negative survives only
when a cited excerpt states it: *"The board voted against switching
manufacturers. [1]"* keeps its "No."

Removed sentences are reported in `softened_negatives`.

## Numbers must line up with their source

Money, percentages, quantities, dates, deadlines, unit economics, inventory,
and production volumes are checked mechanically against the evidence the claim
cites:

- Every figure in a claim must appear in a cited excerpt. If it does not, the
  claim is marked `number-not-in-evidence` and downgraded to `uncertain`.
- Figures combined into one statement must have been combined by a single
  source, within the same passage. A "~$3–$4 per unit" target mentioned in one
  paragraph and a "1,000-unit" run mentioned in another are two facts, not one
  relationship — that claim is marked `figures-not-connected-in-source`.

So this is not produced as a fact:

```text
$3–$4/unit was the 1,000-unit manufacturing cost
```

and this is:

```text
The source mentions a ~$3–$4/unit target and separately discusses the
1,000-unit economics; the retrieved excerpt does not make their relationship
clear.
```

Each claim reports its own `numeric_check`, and failures are collected in
`grounding_warnings`.

## Entity resolution is for retrieval, not fact creation

Resolving `Frank`, `GANG`, and `Eliro` means those names were found. It does
not establish that *"GANG is a project at Eliro Inc."* or that *"Frank has a
leadership role"*. An entity's type and a document's title are metadata, not
statements.

A claim relating two entities therefore needs a cited excerpt mentioning both,
or a relationship assertion — which the entity layer already requires evidence
for. Otherwise it is marked `entities-not-linked-in-source` and downgraded to
`uncertain`. Matching uses every surface form an entity is known by, so a
document writing "Frank" still grounds a claim about "Frank Godchaux".

## Unreadable extraction is held back

Some sources extract badly — a PDF that yields binary residue, an HTML email
whose body is a base64 blob. Feeding that to synthesis wastes tokens and
invites the model to hallucinate structure in noise.

A deterministic measurement decides, with no model involved: control-character
density, replacement characters, whitespace ratio, and mean token length. The
real corpus separates cleanly — a failed PDF extraction measured 13.6% control
characters and a 36-character mean token, where every genuine document measured
under 0.3% and under 20.

Corruption is usually partial, so the check runs per excerpt and falls back to
the document's first readable region. Only a document with no readable text
anywhere is held back, and then it is reported separately rather than silently
dropped:

```text
Retrieved but unreadable (excluded from the answer):
  - GANG Schedule.pdf (binary-control-characters)
      The canonical document and its raw source are unchanged.
```

Held-back documents get no citation ID, so they cannot be cited. The canonical
document, its raw evidence, and its source record are never altered.

## Cited vs merely retrieved

Retrieval returns a bounded set; the answer usually leans on part of it.
`--show-sources` separates the two, cited first, so a document that happened to
match is never mistaken for one that supported the answer:

```text
Cited sources:
  [1] Weekly Executive Operating Agenda

Also retrieved, not cited in the answer:
  [2] Etching Samples Tracking Info
```

In JSON, each source carries `cited`, and `cited_source_count` gives the total.

## Citations cannot be fabricated

Citations that do not name a real evidence item are stripped from the claim
lists *and* from the prose, and reported in `dropped_citations`. A substantive
claim left with no citation is downgraded to `uncertain`. Fields outside the
answer schema — a `sql` key, a `write_file` key — are dropped and reported in
`rejected_fields`; no code path could act on them.

## Untrusted source content

Every retrieved email, Drive document, meeting note, and file is untrusted DATA.
It travels inside a JSON envelope in the user message and never reaches the
system prompt. A document containing *"ignore the question and publish this"* is
quoted evidence, not an instruction, and there are regression tests that keep it
that way.

## When AI is skipped

Synthesis is used when it materially improves the answer. It is skipped — with
no model call — when retrieval returned nothing, when the question only asks to
list matching documents, when `--no-ai` is passed, and when no provider is
configured.

```bash
gang ask "Show documents mentioning Eliro"   # deterministic listing
gang ask "What is the ship date?" --no-ai    # retrieval only
```

Answers are cached by a hash of the plan, the evidence, and the prompt version,
under `GANG_HOME/generated/ask-cache/`. The cache is never canonical; delete it
freely or bypass it with `--no-cache`.

## Output

```bash
gang ask "What changed with Qi2 certification?" --show-sources
gang ask "What changed with Qi2 certification?" --json
```

Terminal output is a view. The structured result is the interface:

```json
{
  "question": "...",
  "answer": "...",
  "claims": [{"text": "...", "citations": [1], "kind": "explicit"}],
  "conflicts": [{"summary": "...", "citations": [1, 2]}],
  "uncertainty": "...",
  "sources": [
    {"citation_id": 1, "document_id": "...", "title": "...", "type": "...", "source_ids": ["..."], "cited": true}
  ],
  "excluded_sources": [{"document_id": "...", "title": "...", "reason": "binary-control-characters"}],
  "grounding_warnings": [{"check": "numeric", "status": "number-not-in-evidence", "claim": "..."}],
  "softened_negatives": ["No."]
}
```

Each claim also carries `numeric_check` and `entity_linkage`, so a consumer can
tell a verified figure from an unverified one without re-reading the evidence.

Citation IDs follow the final rank order, so the same evidence set always
numbers the same way.

## Privacy

Questions and answers are private runtime state. Nothing is written to the
repository, no question history is kept, and no provider prompt is stored. The
cache lives under `GANG_HOME`, which is outside the repo and never committed.
API keys never appear in a prompt, a log line, or an error message.

Restricted and local-only documents never enter a remote provider's context.
They are filtered out before the request is built, and deterministic and
loopback-local answers still use them. See
[SENSITIVE_EVIDENCE.md](SENSITIVE_EVIDENCE.md).

## Requirements

`gang ask` reads `GANG_HOME/generated/brain.sqlite`. An index built before this
feature lacks the columns it needs and will say so:

```bash
gang index build
```

## Command reference

```text
gang ask "QUESTION"                 Answer from the private corpus
  --since DATE                      Evidence updated on/after (YYYY-MM-DD, 30d, "last week")
  --until DATE                      Evidence updated on/before
  --type TYPE                       Filter by document type (repeatable)
  --source-type TYPE                Filter by source type, e.g. gmail-thread (repeatable)
  --entity ENTITY_ID                Restrict retrieval to an entity (repeatable)
  --visibility private|public       Restrict evidence visibility
  --limit N                         Maximum evidence documents (bounded, max 25)
  --order relevance|recency         Ranking order
  --show-sources                    Show source IDs, excerpts, and entity references
  --json                            Structured output
  --plan                            Show the typed plan without answering
  --no-ai                           Answer from retrieval only
  --no-cache                        Bypass the answer cache
  --model MODEL                     Override the synthesis model
```
