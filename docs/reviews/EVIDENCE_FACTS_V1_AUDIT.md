# Evidence Facts V1 — Phase 0 coverage audit

Audited 2026-09-23 against the real private corpus at `~/.gang` before any
code changed. Everything below was read directly from canonical Markdown and
the generated index; nothing was inferred.

## Corpus shape

| Vault directory | Files | Notes |
| --- | ---: | --- |
| `emails/` | 1,196 | Gmail threads from Daniel's mailbox |
| `documents/` | 4 | Drive: `tasks.txt`, `GANG Schedule.pdf`, two ingestion test docs |
| `meetings/` | 1 | `Epic 05 Acceptance Meeting` (acceptance fixture) |
| `people/` | 6 | Frank (authored description), Daniel (no description), 4 outside contacts |
| `companies/` | 3 | GANG (authored description, domain `gang.tech`), Eliro Inc., Dorf Nelson & Zauderer |
| `products/` | 1 | GANG 4-in-1 |

## 1. Does the corpus explicitly establish Daniel Hirunrusme's role at GANG?

**Yes, in email only.** The strongest evidence is Daniel's own email
signature, which appears in 16 of the messages he sent:

```
Daniel Hirunrusme
GANG, Co-Founder
daniel@gang.tech
```

The name line is his exact canonical name, the organization is GANG's exact
canonical name, and the address line is his own canonical email. The message
headers show he sent it. This is an explicit, self-authored role statement.

Other explicit statements exist, but none resolves deterministically to both
Daniel and GANG:

| Statement | Document | Why it is not a V1 fact |
| --- | --- | --- |
| "…the goals … of GANG-Tech's founders, Frank Godchaux and Daniel Hirunrusme." | *GANG-Tech Founder Vision Summary* (email) | `GANG-Tech` is not a canonical name or alias of GANG |
| "My Co-founder, Daniel Hirunrusme, and I have formed a company, Gang Tech, LLC." | Frank's CPA/legal intro emails | `Gang Tech, LLC` is not a canonical name or alias of GANG |
| "Daniel will continue serving as Chief Executive Officer…" | *GANG — Eliro Inc. Meeting 29 Executive Board Notes* | Names no organization; `Daniel` is an alias |
| "Gang Tech agreed on a lean structure: Daniel as CEO…" | Sana meeting summary | Alias subject, unresolved organization |
| "Frank and Daniel each serve as founding directors." | Bylaws recommendations | No organization named |

**Canonical data gap, not an ingestion gap:** the GANG company record has no
aliases, but the corpus calls the company `Gang Tech`, `Gang Tech, LLC`,
`GANG-Tech`, and `GANG Holdings`. Adding those aliases is a human decision
(`gang entity alias add`). Once added, the Founder Vision Summary statement
would also yield a fact. The extractor never strips corporate suffixes or
guesses company identity.

## 2. Are the expected corporate, legal, and Drive documents present?

**No, and this is an ingestion gap.** Drive holds four files, two of them
ingestion test documents. None of the following is in the corpus as a
document of its own:

- bylaws or operating agreement
- articles or certificate of formation / S-election filing
- Section 83(b) elections
- engagement letters (Dorf Nelson & Zauderer, Eliro)
- cap table
- the Founder Vision Summary itself

They show up only as email attachment names, for example
`Section 83(b) Election - Daniel Hirunrusme.docx`,
`FMV Valuation Memo - Gang Tech LLC Membership Units - DRAFT.docx`, and
`By Laws - Template from Eliro Inc`. Gmail ingestion records attachment
metadata but does not extract attachment content, and the Drive folders that
hold company records have not been ingested. When those sources are ingested,
the extractor will classify them as corporate/legal records, the highest
source authority, with no code change. V1 deliberately does not make up for
their absence by inferring roles.

## 3. What feeds Daniel's derived profile, and why are newsletters eligible?

Daniel is linked to 1,181 documents. 1,172 of those links come from the
backfill's `verified-email` rule, because `daniel@gang.tech` is a participant
on every thread in his own mailbox. Only 9 come from his canonical name
appearing in the text.

`ProfileEvidenceReader.collect` then takes the 40 **most recent** linked
documents, with no filter on source class. On the audit date that window
included:

- *Welcome to GS1 US* and *Order Confirmation* (GS1 automated mail)
- *Follow the evolution of feminist art* (MoMA newsletter)
- *Topaz workflows on web & mobile*, *Using Denoise Max in Topaz* (Topaz marketing)
- Anthropic and Claude receipts and notices
- Harmon's Floral, Sky High Farm Goods, ERL retail marketing

The result was a profile citing a MoMA newsletter and GS1 onboarding mail as
support for "uses the email address daniel@gang.tech", followed by "no
document states a role". Newsletters are eligible for three reasons:

1. mailbox participation is a verified mention;
2. evidence is chosen by recency alone;
3. nothing distinguishes bulk or automated mail from authored mail.

The signature evidence above never reached the profile. Its line-broken form
does not match the copular or appositive sentence rules, and the documents
containing it were not among the 40 most recent.

## 4. Packaging decisions

**Explicit decision statements exist in canonical email documents**, mostly
formal Eliro board notes and Sana meeting summaries:

| Date | Statement | Document | Marker |
| --- | --- | --- | --- |
| 2026-09-21 | "Outer shipping carton applied in China." (section *6. Double-Box Packaging Strategy*) | Meeting 29 Executive Board Notes | `Decision` heading |
| 2026-08-28 | "we will use the thicker handled screwdriver. Jess will rework the screwdriver and packaging in response." | Meeting Recap 2026-08-28 | `Decision made:` |
| 2026-08-21 | "GANG will use a double-box shipping strategy, with the outer packaging applied during production in China." | GANG Meeting 24 Notes | `Decisions` / `Aligned`, label `Packaging` |
| 2026-08-05 | "Continue refining premium packaging using the magnetic fold-over design." | GANG-Tech Meeting 15 Notes | `Decisions` / `Aligned` |
| 2026-04-27 | "The team rejected the underside square cable wrap … and agreed to place a standard D-wrapped cord on the top/front foam instead…" | Your summary of Packaging Handoff (Sana) | `Packaging Handoff decisions` topic |

Today `what did we decide about packaging?` returns eight matching documents
instead of these decisions. Two causes:

- `find_decisions` reads only AI-enrichment `decisions` frontmatter, and the
  corpus has none;
- the topic taken from the plan is `decide`, not `packaging`.

Two pitfalls the extractor has to handle:

- A forward agenda (*FINAL WORKING VERSION FOR Meeting 37*) uses `Decision`
  headings for questions still to be answered ("Are all controllable
  prerequisites for production in place?"). Those are not decisions.
- Threads repeat the same notes as plain-text, HTML-rendered, and quoted copies.

## Conclusion

The two acceptance cases can be met from explicit evidence already in the
corpus:

- Daniel's role, from his signature;
- packaging decisions, from the decision sections of formal meeting notes.

The corporate and legal record gap is real and belongs to ingestion
(attachments and Drive folders). The GANG alias gap belongs to canonical
entity curation. V1 addresses neither by inference.
