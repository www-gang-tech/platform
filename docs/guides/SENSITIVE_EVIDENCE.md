# Sensitive evidence

High-authority ingestion brings in the documents that matter most, and some of
them are the most sensitive the corpus holds: tax records, payroll paperwork,
bank letters. Such a document belongs in the private vault. It does not belong
in a prompt sent to a remote AI provider.

Every indexed document has exactly one sensitivity level:

| level | locally (deterministic answers, loopback Ollama) | remote providers |
| --- | --- | --- |
| `normal` | existing behavior | existing behavior |
| `restricted` | used, for anyone the existing access rules trust | never included |
| `local-only` | used | never included, under any configuration |

The level controls **disclosure**, not custody. No canonical document or raw
evidence is redacted, moved, or rewritten because it is sensitive. What
changes is which contexts it may enter.

---

## How a level is decided

1. **Explicit override.** A human decision in the document's frontmatter wins
   outright, in either direction:

   ```yaml
   sensitivity: restricted        # or normal, or local-only
   sensitivity_reason: board only # optional, shown in diagnostics
   ```

   Gmail, attachment, and Drive connectors carry both fields across
   re-ingestion, the same way they carry entity references. An unrecognized
   value is ignored and reported.

2. **Deterministic detection.** Any hit makes the document `local-only`:

   | detector | matches |
   | --- | --- |
   | `us-ssn` | a dash-formatted SSN with a valid area, group, and serial (`000-`, `666-`, `9xx-`, `-00-`, `-0000` never match) |
   | `us-ssn-labeled` | nine digits, bare or space-separated, directly after an SSN label |
   | `us-itin` | a dash-formatted ITIN |
   | `us-taxpayer-id-labeled` | nine digits after an EIN, TIN, "employer identification number", or payer/recipient TIN label |
   | `bank-routing-labeled` | nine digits after a routing/ABA label that pass the ABA checksum |
   | `bank-account-labeled` | 6–17 digits after a *bank*, *checking*, *savings*, *deposit*, or *beneficiary* account label |
   | `iban` | an IBAN that passes its mod-97 checksum |
   | `payment-card` | a grouped card number with a known prefix that passes Luhn |
   | `passport-labeled`, `drivers-license-labeled` | an ID-shaped value after a passport or driver's license number label |
   | `tax-form` | the printed title of a W-2, W-9, W-4, 1040, 1099, or K-1 *and* one of that form's field labels |

   Loose shapes need a label, and labels need a strict shape. A phone number,
   an invoice number, a bare "account number" on a utility bill, a masked
   `XXX-XX-1234`, or an email saying "please send your W-2" is `normal`. There
   is no probabilistic PII scoring.

Detection reads the title, the raw body (including code blocks), and every
string in the frontmatter. Classification happens at `gang index build` and is
stored in the index along with the reasons.

## What a remote provider sees

When the provider about to receive a context is remote, restricted and
local-only material is removed **before the request is built**. Nothing is
cut out of a prompt afterward.

* **Evidence items** are dropped whole — excerpts, title, enrichment,
  relationship evidence. Citation ids are preserved, so the answer still points
  into the full local source list. The model is told only how many sources
  were withheld, so it doesn't read the gap as absence of evidence.
* **Structured records, conversation state, authority guidance, and research
  observations** lose every entry that cites a withheld document. A generated
  evidence fact keeps its provenance in the local facts store; it just can't
  carry its quote into a remote prompt. An earlier turn whose answer drew on
  sensitive evidence is left out of the conversation state.
* **A document id the index doesn't know** is treated as withheld.
* **Enrichment and AI entity proposals** refuse to send a restricted or
  local-only document at all, and remote enrichment context excludes them. The
  deterministic entity proposer still works on every document.

If every retrieved source is withheld, the remote provider isn't called. The
answer falls back to the deterministic listing of matching documents, with a
note saying why.

"Remote" is about where the text goes, not the provider's name. Anthropic is
remote. Ollama is local only when its endpoint is loopback
(`localhost`, `127.x`, `::1`). An Ollama server on a LAN box or a hosted GPU is
remote. Anything that can't say where it sends text is treated as remote.

### Egress backstop

`core/ai_provider.py` scans every request bound for a remote endpoint. If a
detector fires, the request is **refused** and nothing is sent. The error names
the detectors, never the values. The backstop is the last layer, not the
mechanism: reaching it means a filter upstream was missed. It also applies to a
document manually overridden to `normal` if that document still contains an
SSN-shaped value.

## Local behavior

Deterministic answers and loopback local models use restricted and local-only
evidence exactly as before. A fact stated only in a local-only document still
answers "who is …?" with its citation.

Excerpts from restricted or local-only documents replace detected identifier
values with a marker, e.g. `social security number: [ssn withheld]`. These
excerpts appear in answers, JSON results, session snapshots, and answer caches.
The canonical document still holds the value for anyone who opens it.
`gang search` prints no snippet for a local-only hit and points you to
`gang sensitivity show` instead.

## Diagnostics

```bash
gang sensitivity status              # counts at each level
gang sensitivity list                # everything that is not normal, with detectors
gang sensitivity list --level restricted
gang sensitivity show DOCUMENT_ID    # level, basis, and why
gang index status                    # includes the three counts
```

```
Payroll onboarding packet
  document_id: 01b0bcc1-…
  sensitivity: local-only
  basis: detected
  remote AI providers: never sent
  why:
    - detected US Social Security number (1 match)
    - detected labelled ABA routing number (1 match)
  Matched values are never stored or printed. The canonical document is unchanged.
```

Reports carry detector names and counts only. The matched text is never
stored in the index, so no diagnostic can print it. `--format json` is
available on every subcommand.

When a remote provider was used, `gang ask` lists the sources it did not see
under "Retrieved but not sent to the remote AI provider". JSON results carry
the same list as `synthesis.withheld_sources`, and each source has a
`sensitivity` field.

## Requirements

The index gains `sensitivity` and `sensitivity_detail` columns. An index built
before this feature is refused by Ask rather than read as all-`normal`:

```bash
gang index build
```

## Out of scope

This is a V1 boundary: no RBAC beyond the existing owner-trust principals, no
DLP service, no encryption changes, no general PII ontology, and no remote
moderation.
