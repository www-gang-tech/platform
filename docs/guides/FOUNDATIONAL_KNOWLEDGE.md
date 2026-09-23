# Foundational canonical knowledge

> **A company's basic identity must not have to be inferred from email traffic.**

Asked *"what is GANG?"*, a system with no authored identity has to reconstruct
the company from whatever documents happen to mention it. That is how a
scheduling thread becomes a definition. The answer comes back technically
grounded — every sentence cited — and still wrong, because the evidence was
never about what GANG *is*.

Foundational knowledge is the fix: an authored, human-approved account of what
a core entity is, stored on the canonical entity record, indexed so retrieval
can find it, and preferred when someone asks a definitional question.

---

## What it is

An entity record may carry a `description`: one paragraph stating what the
entity is. Longer prose goes in the record body. Together they are the
entity's **identity text**.

```yaml
---
id: 01a0bd04-28ea-769c-a1a7-00a45963989e
record: entity
type: company
name: GANG
aliases: [GANG Systems]
description: >-
  GANG is a design and manufacturing company building intentional objects,
  beginning with the Qi2 wireless charger.
visibility: private
---

# GANG

Longer authored account, if the one-paragraph description is not enough.
```

A record with neither is still a perfectly valid identity — it anchors
mentions and relationships — it simply has nothing authoritative to say about
what the thing is. It is then **not** foundational, and no description is
invented to fill the gap. What happens instead is a
[derived profile](#derived-profiles-when-nobody-has-authored-one): a
reconstruction assembled from cited evidence and labelled as one.

---

## It is authored, never generated

This is the point, not a detail.

`gang entity describe` has no `--use-ai` flag, no `--model`, and no provider
argument, and it never will. A generated company description is a generated
company fact, which is the one thing this system exists to prevent.

Enforced in several places, each independently:

* `EntityService.describe` and `EntityStore.describe` take no provider or model
  parameter — a test asserts their signatures.
* `EntityStore.create` cannot set a description at all.
* Enrichment and entity proposals — the two AI-assisted flows — have no code
  path to `description`; it is listed in `PROTECTED_IDENTITY_FIELDS` and a test
  greps their modules to keep it that way.
* Every write is audited with `"authored_by": "human"`.

If you want a model's help drafting the words, write them yourself somewhere
else and paste the result. The boundary is that nothing generated arrives here
without a person putting it there.

---

## Authoring it

```bash
# The one-paragraph definition.
gang entity describe <entity-id> --description "GANG is a design and
  manufacturing company building intentional objects."

# A longer authored account.
gang entity describe <entity-id> --from-file about-gang.md

# Remove it.
gang entity describe <entity-id> --clear
```

What is worth recording for a core company entity:

| | |
| --- | --- |
| **what it is** | the `description` — one paragraph, no hedging |
| **canonical name** | the record's `name` |
| **aliases** | `gang entity alias add` — every form documents actually use |
| **description** | `description` plus the record body for longer prose |
| **products and projects** | `gang entity relationship` — typed, evidence-backed |
| **corporate / legal relationships** | the same, **only where explicitly recorded** in a document |

That last constraint is deliberate. A relationship needs a document and an
excerpt from it, so "GANG Holdings is the legal entity" is recordable exactly
when some document says so. Suspecting it from a signature block is not enough.

---

## How it reaches an answer

A described record is indexed as a **citable document** alongside its identity
row:

| field | value |
| --- | --- |
| `document_id` | the entity's own ID — a citation to it *is* a citation to the canonical record |
| `type` | `entity` |
| `source_type` | `entity-company`, `entity-project`, … |
| `content_trust` | `trusted` — unlike ingested mail, a person wrote this |

An undescribed record produces no document at all.

### Definitional questions

`intent.py` infers a `definition` policy for questions like:

```
what is gang?        who is Frank Godchaux?       what does GANG do?
tell me about GANG   describe the packaging direction
```

It is matched **last** of all the policies, so a question that looks like
status, discovery, or advice is that instead. `"What is our current BOM?"`
stays a value lookup — the leading possessive is what distinguishes asking for
a value from asking for a definition.

For a definitional question the research loop seeds the evidence set with the
resolved entity's authored record *before any search runs*. Incidental
documents are still retrieved and still cited; they simply are not what leads.

### Source authority

`foundational` is the highest authority role, above a signed document:

```
foundational 120  >  signed-final 100  >  operating-plan 90  >  …  >  email 40
```

Asked what something *is*, the record someone authored outranks a contract
that happens to mention it. As everywhere else in the authority model, this is
a tiebreak that never deletes evidence, and the reason is recorded verbatim:

> Preferred for the definition because it is the canonical record for this
> entity rather than an ordinary email. Older and less formal sources remain
> cited where they differ.

---

## Derived profiles: when nobody has authored one

Most entities never get a description. Requiring one before *"who is Frank?"*
could be answered was too strict: the corpus often knows exactly who Frank is
— a recorded relationship, an address on a known domain, a sentence in a board
note saying so — and refusing to say any of it is not caution, it is silence.

So when a definitional question resolves to an entity with no authored
description, the answer is a **derived profile**: a short list of statements
assembled from explicit evidence, each one cited, the whole thing labelled as a
reconstruction.

```
Derived profile — reconstructed from cited corpus evidence. Nobody has
authored a description of this entity.

Frank Godchaux (person)
- The record states: "Frank Godchaux is a co-founder of GANG..." [1]
- Recorded relationship: Frank Godchaux is affiliated with GANG. [1]
- Uses the email address frank@gang.example, which is on GANG's canonical
  email domain. [1]
- Appears in 4 documents in the private corpus between 2026-03-02 and
  2026-09-18. [1][2][3][4]

This reconstruction is generated and rebuildable, not canonical knowledge.
`gang entity describe` authors the canonical account, which takes precedence.
```

### What it may read

Four kinds of evidence, strongest first:

| kind | what it is |
| --- | --- |
| `statement` | a sentence in a document that identifies the entity outright, **quoted verbatim** and attributed |
| `relationship` | an evidence-backed relationship assertion, using the controlled predicate vocabulary |
| `identifier` | a canonical email or domain on the record, **attested in a cited document** |
| `involvement` | where and when the entity appears — presence, and nothing more |

Which documents it reads is decided by **source class**, not recency alone
(`core/source_classes.py`). Bulk and automated mail — newsletters, receipts,
calendar notifications, list mail — is dropped before anything is read from
it: a mailbox owner is linked to every thread in the mailbox, and being the
recipient of a newsletter says nothing about who someone is. Among what
remains, corporate records and company documents come ahead of meeting notes,
and meeting notes ahead of ordinary email; recency breaks ties.

### What it may not conclude

Participation. Appearing in an attendee list, a cc line, or five meetings in a
row supports *"appears in the record"* and supports nothing else. There is no
path from a pattern of attendance to a title, a job, an employer, or an
ownership stake — the same rule `ask/affiliation.py` holds for participant
bands, applied to identity.

Two rules do the work:

* A person needs a **named role or relationship noun** in the complement, so
  *"Frank is out Friday"* is not an identity. A non-person needs a determiner,
  so *"GANG is scheduled for Friday"* is not a definition.
* The name has to sit **immediately before the verb**. A proximity window
  would read *"With Dana copied, Frank is the certification owner"* as a
  statement about Dana for sharing the sentence — which is precisely how
  someone acquires a job they do not hold.

Sentences on a header line (`Attendees:`, `To:`, `Cc:`) are skipped entirely.
And when nothing in the evidence states a role, the profile says so in as many
words rather than leaving the silence to be read as discretion.

### Generated, rebuildable, never canonical

Derived profiles live in their own SQLite database under
`GANG_HOME/generated/entity-profiles.sqlite`. Nothing is ever written back to
the entity's Markdown: a generated description filed as canonical knowledge is
exactly the new company fact this whole layer exists to prevent.

```bash
# Optional. Precompute every profile the evidence supports.
gang entity profiles build
gang entity profiles build --type person --force

# Inspect one, building it if needed.
gang entity profiles show <entity-id>

# Throw them all away. They rebuild on demand.
gang entity profiles clear
```

Precomputing only buys speed. `ask` builds the same profile lazily when none
has been precomputed, and caches it against a fingerprint of the evidence it
was built from, so changed evidence and a changed builder both invalidate it.
Deleting the file loses nothing.

No model is called on this path, at any point. The statements are structured
records and quoted source text; rendering them needs string formatting rather
than language generation.

### Precedence

1. **Authored description** — if one exists, it is the answer, and nothing
   else is consulted.
2. **Recorded relationship assertions** — evidence-backed relationships a
   person applied to a document (`gang entity relate`).
3. **High-confidence evidence facts** — explicit statements materialized with
   their quotes, e.g. *"Daniel Hirunrusme is a co-founder of GANG."* from his
   own signature block. See [Evidence facts](EVIDENCE_FACTS.md).
4. **Derived profile** — identifiers and involvement assembled from cited
   evidence, labelled as derived.
5. **No-evidence response** — when the evidence supports none of these.

Steps 2 and 3 answer together, relationships first. Authoring a description
later takes precedence immediately, and the derived profile for that entity is
dropped from the generated store on the next build.

---

## Entity types and reclassification

The ontology is small and deliberate: `person`, `company`, `project`,
`product`. Getting the type right matters more once identity is authored,
because type drives the vault directory, the `entity-*` source type, and how a
definitional answer describes the thing.

An entity's **ID is its identity** and never changes. But three things are
derived from its type and must move together:

1. the record's file, because the vault directory is chosen by type;
2. the denormalized `entity_type` on every document that mentions it;
3. the generated index.

Doing any of those by hand desynchronizes the corpus — a document still
calling GANG a project would contradict the canonical record, and nothing else
in the system would notice. So there is one operation that does all three:

```bash
gang entity reclassify <entity-id> company
```

It preserves the ID, the description, every mention, every relationship, and
all provenance; it refuses rather than guesses when the new type would collide
with an existing name or alias; and it writes an audit entry recording both
types and both paths. It prompts before changing anything.

See [the GANG classification review](../reviews/GANG_ENTITY_CLASSIFICATION.md)
for a worked example, including a rehearsal against a copy of the real corpus.

---

## What this does not do

It does not make the corpus self-describing. Foundational knowledge exists
only where someone wrote it, and a derived profile is not a quiet substitute
for one: it is a reconstruction, it says so, it cites every line, and it
refuses to turn attendance into a role. Asked about an entity nobody has
described, `ask` reports what the documents actually state and does not
promote it into a definition — which is the same contract as everywhere else:
**GANG may generate new ideas; it may not generate new company facts.**
