# Epic 11 — High-Authority Document Ingestion: Phase 0 audit

Audited 2026-09-23, before any architecture changed. The findings below come
from reading the ingestion code (`core/ingestion/`), the Evidence Facts layer
(`core/facts/`, `core/source_classes.py`), and the real private corpus at
`~/.gang`. Nothing here is inferred.

## Baseline

- Code base: `cb5d5c7 feat: add evidence-backed facts and decisions`.
- That commit imports `core.source_classes`, but the module and
  `tests/test_evidence_facts.py` were never committed. Both existed only as
  untracked files in the Evidence Facts workspace and were copied here
  unchanged. Without them, `core.facts` doesn't import.
- Test suite at baseline: 774 passed, 352 subtests passed.

## Corpus

| Store | Contents |
| --- | --- |
| `raw/gmail-thread/` | 1,196 thread manifests |
| `raw/gmail-message/` | 2,169 raw RFC 822 messages (`format=raw`) |
| `raw/gmail-attachment/` | 6,405 source directories, 1.30 GB, **773 distinct payloads** |
| `raw/drive-file/` | 5 Drive sources |
| `vault/emails/` | 1,196 canonical thread documents |
| `vault/documents/` | 4 canonical Drive documents (two are ingestion test files) |
| `ingestion/registry.json` | 1,196 `gmail-thread` + 5 `drive-file` sources, 1.8 MB |

Attachment MIME types by raw directory: PNG 4,025, PDF 765, JPEG 561,
calendar (`text/calendar` + `application/ics`) 569, DOCX 274, octet-stream 56,
XLSX 50, other 105.

High-value attachments present only as filenames today include
`Section 83(b) Election - Daniel Hirunrusme.docx`,
`Section 83(b) Election - Frank Godchaux.docx`, `Eliro Inc - ByLaws v1-0.docx`,
`Dorf Nelson Zauderer LLP - Gang Tech Engagement Letter 1-24-2025__Signed.pdf`,
`LLC Articles OR Certificate of Organization.pdf`,
`GANG HOLDINGS INC. - DE FORMATION.pdf`,
`GANG HOLDINGS INC. - EIN LETTER 8-24-2028.pdf`,
`Gang Tech Holdings, Inc. S-Corp Election Form 2553.pdf`, and several
engagement letters and professional services agreement amendments.

## Questions

### What attachment bytes are already downloaded and preserved?

**All of them.** `GmailSyncService._ingest_thread` calls
`provider.fetch_attachment` for every part that has a Gmail `attachmentId`,
including inline images, and stores the decoded bytes in the raw store as
`gmail-attachment`. The raw `.eml` for each message (`gmail-message`) also
carries every MIME part. Counting inline parts too, every raw attachment
payload but 4 can be recovered byte-for-byte from the `.eml` files. The 4 are
3 forwarded `message/rfc822` parts (the `.eml` re-encodes them) and one PDF
nested inside one of those.

Attachment contents are never extracted. The thread document body lists
`- filename (mime/type)` and nothing else.

### What attachment metadata is retained?

In the raw record's `metadata.json` and in each message of the thread
manifest: Gmail `attachment_id`, filename, MIME type, parent message ID,
parent thread ID, content SHA-256, and `raw_ref`. **Not retained:** the MIME
`partId`, the attachment size, the receiving account, and any extraction
status.

### Do blobs have stable hashes and paths?

Hashes, yes: every raw version records its SHA-256, and `LocalRawStore.put`
dedupes identical bytes *within one source directory*. Paths, **no**:

> **Defect.** The Gmail attachment source ID is
> `stable_source_id("gmail-attachment", "gmail", f"{message_id}:{attachment_id}")`,
> but Gmail's `attachmentId` is not stable. It changes on every API response
> for the same message. 2,256 distinct (message, filename) pairs have produced
> 6,405 attachment source directories; 1,906 pairs have more than one. Every
> re-fetch of a thread stores the same bytes again under a new directory, and
> because the thread manifest embeds `attachment_id`, the manifest hash
> changes, so the thread counts as `updated` even when nothing changed.

The MIME `partId` Gmail reports alongside the attachment is stable, and so is
the pair (message ID, content hash).

`GangPaths.blobs_path` (`GANG_HOME/blobs`) is declared but unused. The raw
store is the only binary custody in use.

### Which document MIME types are extractable today?

| Path | Types | Quality |
| --- | --- | --- |
| `FileAdapter` (local files) | `.md`, `.txt`, `.json`, `.jsonl` | fine |
| Drive | Google Docs (exported as `text/markdown`), `text/plain`, `text/markdown`, `.md`/`.txt` names, PDF, DOCX | see below |
| Gmail attachments | none | — |

- **PDF extraction is broken in practice.** `_extract_pdf_text` tries `pypdf`,
  which isn't in `requirements.txt` or installed, and falls back to
  scraping printable characters from the raw PDF bytes. For any compressed
  content stream that produces binary junk. The corpus's one Drive PDF,
  `GANG Schedule.pdf`, is canonical today as 12,525 lines of mojibake.
- A PDF with no text layer becomes a canonical document whose body is
  `(No extractable PDF text.)`. There is no `requires-ocr` status.
- DOCX extraction (zip + regex over `word/document.xml`) is dependency-free
  and adequate. It drops tabs and line breaks, and an encrypted DOCX (an OLE
  compound file, not a zip) surfaces as a generic failure.
- Password-protected and malformed files aren't distinguished from each
  other.
- No OCR anywhere. None will be added.

Libraries checked: `pypdf`, `python-docx`, `pdfminer`, and PyMuPDF are all
absent. `cryptography` is installed (pypdf uses it for AES-encrypted PDFs).

### How does Drive folder traversal and versioning work?

- `--folder ID` lists only the folder's **direct children**
  (`'ID' in parents`). No recursion, and no folder path is recorded (only
  parent IDs).
- Only one folder per run. There is no configuration of company-record
  folders.
- After any bounded run, a plain `gang ingest drive` uses the Drive Changes
  API, which reports changes across the whole Drive.
- Versioning: `source_version` is `headRevisionId`, `version`, or
  `md5Checksum`, whichever is present. Each distinct payload becomes a new
  raw version under the Drive file's source ID; the document UUID is stable
  across rename, move, and edit; registry `versions[]` keeps history.
- Every run downloads every discovered file, even when its revision hasn't
  changed.
- Google Docs are exported as `text/markdown`. Sheets, Slides, Forms, and
  Drawings are recorded as unsupported with no document. **Keeping the
  existing Docs export path; no other representation is added.**

### How is duplicate source material detected?

- Raw store: identical bytes under the *same* source ID aren't stored twice.
- Registry: a source whose payload or manifest hash is unchanged is skipped.
- Nothing detects identical bytes under *different* sources. That includes
  the same PDF attached to three messages in a reply chain (common here: 773
  distinct payloads across 2,256 attachments), and a Drive file that is also
  an attachment.

### How is source → canonical document provenance represented?

Consistently across adapters:

- `registry.json` maps `source_id` to `document_id`, `document_path`,
  `raw_ref`, `content_hash`, `version`, and `versions[]`.
- Canonical frontmatter carries `source_id`, `source_ids`, `sources[]`,
  `raw_ref`, `content_hash`, `version`, a `provenance` block, and
  `ingestion_envelope` (the manifest). `content_trust: untrusted` marks
  imported prose as evidence, never instructions.
- The entity layer protects all of these fields from modification
  (`PROTECTED_FRONTMATTER_FIELDS`).
- An Evidence Fact records `document_id`, `source_hash`, `source_class`, and
  `source_rank`; `gang ingest inspect` prints a registry record by source ID.
- **Gap:** nothing answers "which attachment, in which email, supports this
  fact, and has it changed since extraction?" end to end. The pieces exist but
  aren't joined.

## Evidence Facts integration

- `EvidenceFactService.build()`, the entity backfill, and
  `PrivateKnowledgeIndex` all walk **every** Markdown file under
  `GANG_HOME/vault` recursively. A new vault directory needs no reader
  changes.
- Ingest commands already run the deterministic entity backfill on the
  documents they touched. `gang index build` refreshes Evidence Facts
  incrementally.
- **Blocking issue for attachments:** `classify_source` treats any
  `source_type` starting with `gmail`, `email`, or `mail` as email. A
  `gmail-attachment` document would be classed as ordinary correspondence and
  could never reach `corporate-record`.
- **Filename-only authority:** for a non-email document,
  `corporate-record` is decided by the title alone. For an attachment, the
  title is its filename. Without an additional rule, a file named
  `Bylaws.docx` would be treated as authoritative whatever it contains. The
  epic forbids exactly that.

## Decisions

1. **Custody stays in the raw store.** No new blob store. Attachment bytes
   already in `raw/gmail-attachment/` are reused by `raw_ref`. They aren't
   copied again.
2. **Stable attachment identity** is (Gmail message ID, content SHA-256).
   This can be computed identically from the live API, from existing thread
   manifests, and from raw `.eml` files. The MIME `partId` is recorded when
   the API supplies it; the ephemeral `attachmentId` is dropped from the
   thread manifest so an unchanged thread hashes the same way twice.
3. **One canonical document per distinct attachment payload**, under
   `vault/attachments/`, with every occurrence (message, thread, filename,
   date, account) listed in its provenance. Identical bytes are extracted
   once; each occurrence keeps its own registry record pointing at the shared
   document.
4. **One shared extractor** (`core/ingestion/extract.py`) for Gmail
   attachments and Drive: plain text, Markdown, PDF via `pypdf` (added to
   `requirements.txt`), and DOCX via the existing dependency-free reader.
   Statuses: `extracted`, `requires-ocr`, `unsupported`, `password-protected`,
   `malformed`, `empty`, `too-large`, `extractor-unavailable`. Only
   `extracted` produces a canonical document. Every other status is recorded
   and reported, and no failure aborts a batch.
5. **Backfill is offline.** It reads thread manifests and raw bytes already
   in custody, so historical attachments need no Gmail API calls.
6. **Drive** gains recursive traversal of explicitly configured folders
   (`GANG_HOME/ingestion/drive/folders.yml`), folder paths in metadata,
   extractor-aware skipping of unchanged revisions, and the shared extractor.
   The existing Google Docs export and Changes API behavior are unchanged.
7. **Source classification:** `*-attachment` source types are documents, not
   email. A title that names a legal instrument earns `corporate-record` only
   if the document's own extracted text names one too. That is a demotion
   rule, consistent with the module's "a document can argue its way down,
   never up". Ranks, the fact ontology, and Ask are untouched.
8. **Provenance lookup** extends `gang ingest inspect` to accept a document
   ID or fact ID as well as a source ID. It reports the original source, the
   parent email and thread, the raw reference, and whether the raw bytes still
   match the hash recorded at extraction.

## Acceptance on the real corpus (2026-09-23)

The run used the code in this change against `~/.gang`. It was preceded by a
backup of `vault/`, `ingestion/`, `generated/`, and `entities/`
(`~/.gang/backup-epic11-20260923-135916`). Raw evidence was only read, and
added to only by the live sync.

### Gmail attachment backfill (`gang ingest gmail attachments`)

| | First run | Second run |
| --- | ---: | ---: |
| Files discovered (occurrences) | 2,183 | 2,183 |
| Distinct payloads | 772 | 772 |
| Duplicates | 1,411 | 1,411 |
| Extracted | 357 | 357 |
| Requires OCR | 24 | 24 |
| Unsupported | 386 | 386 |
| Failures (all password-protected) | 5 | 5 |
| Canonical documents created / updated | 357 / 0 | 0 / 0 |
| Evidence facts (total, change) | 8 (+2 / −0) | unchanged |
| Decisions (total, change) | 251 (+123 / −0) | unchanged |

The second run left `vault/attachments/`, `registry.json`, and
`raw/gmail-attachment/` byte-identical and took 1.4 s. Unsupported payloads
were mostly images (PNG 142, JPEG 50, HEIC 5) and calendar invites (142),
plus 13 CAD/Pages files, 12 XLSX files, and 7 ZIP archives.

Example of the full path: `Section 83(b) Election - Daniel Hirunrusme.docx`
had been a filename in one thread. It is now:

- raw bytes in custody;
- a canonical document of class `corporate-record`;
- deterministic entity links to Daniel Hirunrusme, GANG, and Jennifer Nelson
  Flynn, each carrying an excerpt;
- Evidence Facts input.

`gang ingest inspect` traces it back to Gmail message `1a03f74796d7a1bb`, its
thread *Valuation Memo, Sec. 83(b) Elections, and S-corp election*, account
`daniel@gang.tech`, and intact original bytes.

15 attachment documents classify as `corporate-record`: both 83(b)
elections, the Eliro bylaws, eight engagement letters and revisions, the EIN
letter, and the LLC articles. Three legal-titled files were demoted to
`company-document` because their own text never names the instrument. For
example, the signed Dorf Nelson & Zauderer letter calls itself an "engagement
and retainer agreement". These are deliberate, conservative misses.

The 123 new decisions come from formal meeting and board notes that had
existed only as `.docx` attachments, e.g. *GANG Meeting 29 Executive Board
Notes*.

Authority ordering: Daniel's `founder_of` fact from the attached *GANG-Tech
Founder Vision Summary.docx* (`company-document`, rank 80) is now ranked
ahead of the same statement quoted in email (`email`, rank 40).

### Live Gmail sync

An incremental `gang ingest gmail` fetched 19 threads with 37 attachments
(8 extracted, 6 requires OCR, 22 unsupported, 0 failed) and recorded the
source account. Fetching the same window again (26 threads) twice:

1. First re-fetch: migrated three older threads once from the old manifest
   format.
2. Second re-fetch: 26 unchanged, 0 new raw attachment directories, and
   byte-identical attachment documents.

This confirms the rotating-`attachmentId` defect is fixed.

### Drive

The Drive account holds no company-record files. A read-only name search for
bylaws, agreements, certificates, 83(b), engagement letters, and the like
returned nothing. The only `Legal` folder is empty, and the Eliro meeting
folder holds a single shortcut, which was correctly not followed. The
recursive folder path was therefore demonstrated on the one real folder that
holds documents, *GANG Connector Test*:

| | Run 1 | Run 2 |
| --- | ---: | ---: |
| Files discovered | 5 | 5 |
| Updated (re-extracted with the shared extractor) | 3 | 0 |
| Unchanged | 0 | 3 (no downloads) |
| Requires OCR | 1 | 1 |
| Unsupported | 1 | 1 |
| Failures | 0 | 0 |

`GANG Schedule.pdf` has no text layer. Its existing canonical document is the
12,525-line binary scrape produced by the old fallback. Following the no-
overwrite rule, that document was left in place, and the file is now reported
as `requires-ocr`. Deleting or replacing the stale document is a human
decision.

A company-record Drive folder going through the same path is covered by
`tests/test_high_authority_ingestion.py::DriveFolderTests`. There, a bylaws
DOCX in `Company Records/Legal` becomes `corporate-record`, and a scanned
certificate becomes `requires-ocr`.

### Test suite

800 passed, 363 subtests passed (baseline: 774 passed, 352 subtests).
