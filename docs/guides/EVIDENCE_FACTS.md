# Evidence facts

Entity linking establishes that a document *refers to* someone. It says
nothing about what the document *states*. Asked "who is Daniel?", a corpus
with a thousand mailbox mentions of `daniel@gang.tech` and one signature
reading `GANG, Co-Founder` should answer with the signature. The mentions
alone don't support that answer.

Evidence facts close that gap. They are explicit statements, materialized as
structured records, each carrying the exact words that state it:

```
Daniel Hirunrusme is a co-founder of GANG. [1]
  Evidence: "Daniel Hirunrusme GANG, Co-Founder daniel@gang.tech" — email
  signature in "GANG TECH, LLC | WPC Registration Document Request…"
  (2026-01-23, an ordinary email)
```

Decisions get the same treatment:

```
Decisions (newest first)
- 2026-09-21 — Outer shipping carton applied in China.
  (decided; 6. Double-Box Packaging Strategy) [1]
- 2026-08-05 — Continue refining premium packaging using the magnetic
  fold-over design. (aligned) [6]
```

The layer is **generated**. Facts are rebuilt from canonical documents, never
written back to them, and a human's authored description always wins. No
model is called anywhere on this path.

---

## What gets extracted

### Relationship facts

A small controlled vocabulary, separate from the canonical relationship
predicates because these are generated claims rather than human assertions:

```
cofounder_of   founder_of   works_for   partner_at
advisor_to     vendor_for   manufacturer_for   responsible_for
```

Only explicit statements produce a fact:

| rule | example |
| --- | --- |
| `copular-role` | "Daniel Hirunrusme is a co-founder of GANG." |
| `appositive-role` | "Daniel Hirunrusme, co-founder of GANG, signed…" |
| `organization-role-prefix` | "GANG co-founders Daniel Hirunrusme and Frank Godchaux…" |
| `founders-of-list` | "…the founders of GANG, Frank Godchaux and Daniel Hirunrusme." |
| `signature-block` | name line, `Organization, Title`, and the person's own canonical address, in a message that address sent |
| `responsible-for` | "Dana Reyes is responsible for certification." |

A title stated in the evidence ("Chief Executive Officer") is kept verbatim as
the fact's `role`. It is never promoted into a different predicate.

**None of the following ever produces a fact:**

- attendee lists
- `From` / `To` / `Cc` / `Participants` lines
- a shared email domain
- appearing in fifty threads
- "X said Y is a co-founder" (a misattribution)
- a negated, former, potential, or conditional role
- a question

Entities are recognized only by unambiguous canonical names, aliases, and
addresses, matched as written. `GANG-Tech` is not `GANG`, and `Gang Tech,
LLC` resolves only once someone adds it as an alias.

A person named only by a short alias ("Daniel", "Dan") yields a
**medium-confidence** fact. It is stored but not stated in answers, because
another person might share the first name.

### Decision records

A decision is materialized only where the document marks it as one:

| rule | marker |
| --- | --- |
| `decision-section` | a `Decision` / `Decisions` / `Key Decisions` / `Decisions / Alignment` heading and the items under it; status lines (`Aligned`, `Approved / Aligned`) and item labels (`*Packaging*`) are kept |
| `decision-inline` | `Decision made: …`, `Decision: …` |
| `decision-topic` | a meeting-summary topic "… decisions" and its `: …` paragraph, keeping the sentences with a decision verb |
| `group-agreement` | formal notes only: "The team approved…", "The group aligned on…"; also "No decision was made to…", recorded as `not decided` |

**Never a decision:**

- "Decision required"
- a question (a forward agenda's `Decision` headings are questions still to be answered)
- a "Requires Follow-Up" or "Needs Further Discussion" list
- anything in an agenda or in bulk mail
- quoted replies
- "we agreed to revisit…"

A meeting's decisions are dated by the meeting date in the notes' title when
there is one.

---

## Source authority

Every document is classified before extraction (`core/source_classes.py`):

| class | rank | identity evidence | decisions |
| --- | ---: | :---: | :---: |
| `corporate-record` — bylaws, operating agreement, 83(b), engagement letter | 100 | ✓ | ✓ |
| `company-document` — other Drive and uploaded documents | 80 | ✓ | ✓ |
| `meeting-notes` — notes, minutes, recaps, meeting summaries | 70 | ✓ | ✓ |
| `agenda` — working agendas and drafts | 50 | ✓ | — |
| `email` — ordinary correspondence | 40 | ✓ | ✓ |
| `bulk` — newsletters, marketing, receipts, calendar notifications | 0 | — | — |

The classifier reads the title, the source type, and the sender headers
ingestion recorded. It reads body text for exactly one thing: unsubscribe and
"you are receiving this" boilerplate. That signal can only ever *demote* a
document, so a document can argue its way down but never up.

Mail from an address or domain with a canonical entity record is always
correspondence, whatever boilerplate it carries.

When one claim is stated in several documents, the strongest source is cited
first. Derived entity profiles use the same classes to choose their evidence,
so a newsletter sent to someone is never cited as evidence of who they are.

---

## Asking

Definition questions resolve in this order:

1. human-authored canonical description;
2. recorded relationship assertions (`gang entity relate`);
3. high-confidence generated evidence facts;
4. derived profile: identifiers and involvement;
5. no evidence.

Steps 2 and 3 answer together, relationships first. "Who is Frank?" still
returns Frank's authored description, even when the corpus also contains an
extractable statement about him.

Decision questions ("what did we decide about packaging?") return
materialized decisions, newest first, with date, status, section, and
citations. Enrichment-derived decisions follow, if they add anything. When
nothing explicit matches, the ordinary path runs unchanged.

Ownership questions ("what does Daniel need to do?") are untouched. They
still read explicitly assigned work.

Every fact and decision shown is **re-verified against the current text of the
document it cites** at answer time. A quote that is no longer in its source is
stale and is not shown. Definition and decision questions make **zero
provider calls**: no model plans them, and no model writes the answer.

---

## Storage, invalidation, and correction

```
GANG_HOME/generated/evidence-facts.sqlite   generated, rebuildable, safe to delete
GANG_HOME/facts/overrides.yml               human suppressions, durable
```

Each fact records:

- subject
- predicate
- object entity or typed value
- stated role
- source document
- exact excerpt
- document date
- extraction method and rule
- extractor version
- source hash
- source class
- confidence

Invalidation is per document:

- **File stat unchanged** (path, mtime, size): the document is not even
  re-read, so a refresh is cheap enough to run before every question.
- **Source hash changed**: the document's facts are re-extracted.
- **Document gone**: its facts are removed.
- **New extractor version, or an entity registry change** (a new alias, a new
  person): everything is re-extracted.

Rebuilding twice over unchanged evidence changes nothing.

```bash
gang facts build            # incremental; --force re-extracts everything
gang facts status
gang facts show Daniel      # --all includes medium-confidence and suppressed
gang facts decisions --topic packaging
gang facts suppress fact_…  --reason "misread signature"
gang facts unsuppress fact_…
gang facts clear            # deletes the generated store, keeps suppressions
```

`gang index build` refreshes the store after rebuilding the index, and
`gang ask` refreshes it on demand. Running `gang facts build` yourself only
ever buys speed.

A wrong fact is corrected in one of three ways:

- fix the extractor, and bump `EXTRACTOR_VERSION`;
- author a description, which takes precedence;
- suppress the fact.

None of them touches the source document. Fact and decision IDs are derived
from the claim and its exact words, not from a build, so a suppression keeps
applying across rebuilds and extractor upgrades.

---

## The proposal boundary (future local enrichment)

Every fact enters the store as a `ClaimProposal` and passes
`validate_proposal` or is not stored. The deterministic rules are one
proposer. A future on-device enrichment worker, for high-signal documents the
rules cannot parse, would be another, and it would face the same gate:

- the predicate must be in the controlled vocabulary;
- subject and object must be resolved, active canonical entities of the right
  types;
- the supporting quote must actually appear in the source, which is verified,
  not trusted;
- the quote must name both the subject and the object;
- remote models are not a permitted method at all;
- any non-deterministic method is capped at medium confidence, below what Ask
  states.

Nothing in V1 produces model claims. The boundary exists so that adding one
later cannot quietly turn generated text into company knowledge.

---

## What this does not do

It is not a knowledge graph, an ontology, or semantic search. There are no
embeddings and no fuzzy extraction.

It doesn't cover documents the corpus doesn't hold. On the audit date, the
bylaws, operating agreement, 83(b) elections, and engagement letters existed
only as email attachment names. See the
[Phase 0 audit](../reviews/EVIDENCE_FACTS_V1_AUDIT.md). That is an ingestion
gap, and V1 does not paper over it by inference.
