# Review: should GANG be the canonical company entity?

**Status: proposal. Nothing in the real corpus has been changed.**

Recommendation: **yes — reclassify GANG from `project` to `company`**, then
author its description. The migration is safe, has been rehearsed against a
copy of the real corpus, and preserves identity and every reference. It needs
your approval before it runs, and the description text needs you to write it.

---

## Current state

Read from `~/.gang` on 2026-09-20, read-only:

```
vault/projects/01a0bd04-28ea-769c-a1a7-00a45963989e-gang.md
  type: project   name: GANG   aliases: []   description: (none)   body: "# GANG"

vault/companies/01a0bd04-25fd-7e4f-a0df-b3fff29c3fcf-eliro-inc.md
  type: company   name: Eliro Inc.   aliases: [Eliro]

vault/people/…-frank-godchaux.md
  type: person    name: Frank Godchaux   aliases: [Frank]
```

GANG has 2 mentions across 2 documents, 1 relationship, 3 source IDs, and no
authored identity content.

## Why `project` looks wrong

The corpus treats GANG as the operating company and Eliro Inc. as an outside
firm. Quoting documents rather than inferring:

| Evidence | What it indicates |
| --- | --- |
| *"Frank reaffirmed that GANG does **not** intend to broadly pursue outside institutional financing while **the company** remains pre-revenue."* | The corpus calls GANG "the company", in a relationship excerpt already recorded in the entity graph |
| *"GANG Holdings/corporate binder"* | A corporate/legal structure under the GANG name |
| *"Is the GANG **commercial operating system** functioning as designed…"* | GANG operates a business, not a workstream |
| *"GANG Systems - Shopify synchronization"*, *"Proprietary GANG typeface"*, *"GANG / Creative Engineering - Final BOM?"* | Systems, brand assets, and manufacturing owned under the GANG name |
| *"Steven Gormley, Co-Founder & Managing Partner, **Eliro Inc.**"*, *"By Laws - Template from Eliro Inc"* | Eliro's principals are principals *of Eliro*, advising GANG — an external firm |
| Thread titles: *"GANG — Eliro Inc. Weekly Executive Operating Agenda"* | Two distinct parties meeting, not a project inside a company |

A project is a unit of work with a beginning and an end. GANG has a BOM, a
commercial system, brand assets, a corporate binder, and a financing posture.
Those are properties of a company.

**This is inference, and that is exactly the problem the change fixes.** The
right resolution is not for the system to conclude GANG is a company from
email — it is for you to record that it is.

## What the Qi2 work then becomes

Today "GANG" is doing double duty: the company *and* the charger programme.
After reclassification, the programme should be its own `project` or `product`
entity, related to GANG explicitly:

```
GANG (company) --involved_in--> Qi2 charger programme (project)
```

That relationship needs a document stating it, as all relationships do.

## Does this violate an identity contract?

No. Checked against `core/entities/model.py`:

| Contract | Effect |
| --- | --- |
| Identity is the opaque UUID | **Unchanged.** `01a0bd04-28ea-769c-a1a7-00a45963989e` survives, so every mention, relationship, and provenance chain stays valid |
| `type` must be in the ontology | `company` is valid |
| Vault directory is derived from type | File moves `projects/` → `companies/`. Handled |
| Mentions denormalize `entity_type` | 2 documents carry `entity_type: project` and must be rewritten. Handled |
| Name must be unique per type | No company named GANG exists. Checked, and the migration refuses if one appears |
| Aliases must not collide per type | GANG has no aliases today. Checked, and the migration refuses on collision |
| Relationships are keyed by entity ID | Type-agnostic; unaffected |

The one real hazard was the denormalized `entity_type` in document
frontmatter: editing the record by hand would leave two documents asserting
GANG is a project while the canonical record said otherwise, and nothing in
the system would have caught it. That is why this is one audited operation
rather than a file move.

## Rehearsal

Run against a **copy** of the real corpus at `/tmp/gang-rehearsal`, since
deleted. `~/.gang` was never opened for writing.

```
BEFORE: type=project  mentions=2  relationships=1  documents=2  source_ids=3
RECLASSIFY: project -> company | changed: True
  new path: vault/companies/01a0bd04-…-gang.md
  documents updated: 01a0bcb6-6805-…, 01a0bc67-8218-…
AFTER:  type=company  mentions=2  relationships=1  documents=2  source_ids=3

IDENTITY PRESERVED:      True
MENTIONS PRESERVED:      True
RELATIONSHIPS PRESERVED: True   (Frank Godchaux --involved_in--> GANG intact)
DOCUMENTS PRESERVED:     True
vault/projects/ is now empty; no duplicate record left behind
both documents' entity_refs now read entity_type: 'company'
```

Then, with a placeholder description authored and the index rebuilt:

```
$ gang ask --show-sources "what is gang?"

Cited sources:
  [1] GANG
      document_id: 01a0bd04-28ea-769c-a1a7-00a45963989e
      type: entity / entity-company
      excerpt: GANG is the operating company. …
  [2] GANG — Eliro Inc. Executive Board Meeting 28 Notes…
      type: email-thread / gmail-thread
```

The canonical record leads; the board-meeting thread is retained as secondary
evidence; the corrupt `GANG Schedule.pdf` stays excluded. No crash.

## Proposed migration

Nothing below has been run against `~/.gang`. Each step is reversible except
where noted, and step 1 makes the rest reversible.

```bash
# 0. Back up. The vault is the source of truth; the index is disposable.
cp -R ~/.gang/vault ~/.gang/vault.backup-$(date +%Y%m%d)

# 1. Reclassify. Prompts before changing anything; --yes skips the prompt.
gang entity reclassify 01a0bd04-28ea-769c-a1a7-00a45963989e company

# 2. Author the identity. THIS TEXT MUST BE YOURS — the system will not
#    generate it, and should not.
gang entity describe 01a0bd04-28ea-769c-a1a7-00a45963989e \
  --description "GANG is …"

# 3. Aliases the documents actually use.
gang entity alias add 01a0bd04-28ea-769c-a1a7-00a45963989e "GANG Systems"

# 4. Separate the programme from the company, if you want that split.
gang entity create project "Qi2 Charger Programme"
gang entity relationship <gang-id> involved_in <programme-id> \
  --document <document-id> --excerpt "…"

# 5. Rebuild and check.
gang index build
gang ask "what is gang?"
```

### Verify afterwards

```bash
gang entity show 01a0bd04-28ea-769c-a1a7-00a45963989e
# expect: type company, 2 mentions, 1 relationship, 3 source ids, ID unchanged
grep -r "entity_type: project" ~/.gang/vault   # expect: no matches for GANG
```

### Rollback

```bash
gang entity reclassify 01a0bd04-28ea-769c-a1a7-00a45963989e project
gang entity describe 01a0bd04-28ea-769c-a1a7-00a45963989e --clear
gang index build
```

Reclassification is symmetric, so step 1 reverses cleanly. Only the authored
description is new information, and `--clear` removes it.

## Risks

| Risk | Mitigation |
| --- | --- |
| The ontology has no "legal entity" type, so `GANG Holdings` cannot be modelled as distinct from `GANG` | Record it as a separate `company` entity with an explicit relationship, if a document states the structure. Expanding the ontology is a future epic, not a config change |
| `type: project` may be load-bearing somewhere outside the entity layer | Searched: type is used for the vault directory, the `entity-*` source type, and display. The reclassify operation covers all three |
| A future ingestion could recreate GANG as a project | Ingestion does not create entities; entity creation is explicit. Not a current risk |
| The description could drift from reality | It is canonical knowledge with an audit trail, updated the same way it was written |

## What I need from you

1. **Approval to reclassify** GANG to `company` in the real corpus.
2. **The description text.** I will not write it: an authored account of what
   your company is has to come from someone who can speak for it. One
   paragraph is enough.
3. **A decision on the Qi2 programme** — whether to split it into its own
   `project`/`product` entity, and if so, a document that states the
   relationship so it can be recorded with evidence.

Until then the code is in place, tested, and unused against `~/.gang`.
