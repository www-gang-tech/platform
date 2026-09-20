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
what the thing is. It is then **not** foundational, and nothing is invented to
fill the gap.

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
only where someone wrote it. Asked about an entity nobody has described, `ask`
says what the documents say and does not pretend to a definition — which is
the same contract as everywhere else: **GANG may generate new ideas; it may
not generate new company facts.**
