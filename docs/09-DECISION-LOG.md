# Decision Log

Record durable architecture decisions, not routine implementation details.

## 2026-09-18 - Migration identity and source classification

**Status:** Accepted

### Context
The legacy `content/` tree mixes production Markdown, examples, documentation, fake people records, and system data. A dry-run migration needs stable canonical IDs without making paths, titles, slugs, or mutable content into permanent identity.

### Decision
Canonical migration candidates receive random UUIDv7 document IDs that are allocated once and frozen in `reports/migration-manifest.json`. Excluded fixtures, examples, documentation, and legacy system data do not receive canonical vault IDs by default.

### Why
UUIDv7 preserves opaque stable identity without coupling identity to mutable content or filesystem layout. Explicit source classification keeps examples and docs out of the knowledge vault unless a future migration deliberately opts them in.

### Consequences
Dry-run reports must reuse the frozen manifest allocation on subsequent runs. Migration review queues must distinguish `excluded_from_migration` from `review_required`.

### Revisit when
The future migration command persists IDs into frontmatter or a separate long-term identity registry.

## 2026-09-18 - Generated metadata migration policy

**Status:** Accepted

### Context
Legacy Markdown may contain hand-maintained or AI-filled `jsonld` and `seo` fields. The target architecture treats public structured data as deterministic output from canonical content and contracts.

### Decision
Legacy `jsonld` frontmatter is classified as `generated_legacy`. It may be preserved for rendering-equivalence checks during migration, but it is not long-term canonical knowledge.

Authored SEO metadata is preserved as a human override when present. Missing SEO metadata is allowed; future agents may suggest or generate SEO values, but SEO fields are not required for every knowledge note.

### Why
This avoids making generated state canonical while preserving current public output behavior during the transition.

### Consequences
Future JSON-LD should be regenerated from canonical fields and validated contracts. SEO validation should preserve authored overrides without treating absent SEO as a knowledge-model failure.

### Revisit when
Structured-data generation and SEO suggestion workflows are deterministic and covered by validators.

## 2026-09-19 - Public build source cutover to canonical vault

**Status:** Accepted

### Context
Epic 02.7 resolved the final legacy public post, `content/posts/qi2-launch.md`, and migrated all current public URLs into `brain/vault/public/`. The legacy `content/` tree remains useful as a rollback source, but it also contains examples, fake people records, and documentation that must not be treated as canonical public knowledge.

### Decision
`brain/vault/public/` is the default production source for public builds. `content/` remains available only through explicit rollback mode with `gang build --source legacy`.

All page rendering and generated public outputs must consume the same validated public document collection loaded through `load_public_content()`. Generators must not independently scan `content/` or `brain/vault/public/` to decide what is public.

The Qi2 post is canonically titled `Qi2 Launch` with `created: 2025-10-12` and `updated: 2025-10-12`. The body heading `What's New in Qi2` is preserved. Provenance is recorded in `migrations/legacy-content-v1.json`.

### Why
This creates one source of truth for public knowledge and prevents silent dual-source fallback. A missing vault document must fail validation instead of being filled from legacy content.

### Consequences
New public documents must be created under `brain/vault/public/`. The legacy `content/` tree is deprecated for production authoring and may only be used for explicit rollback while this transition remains fresh.

### Revisit when
Legacy rollback mode is no longer needed and `content/` can be archived or removed in a later deprecation epic.

## 2026-09-20 - Gmail ingestion source boundary

**Status:** Accepted

### Context
Private email should be searchable in the local knowledge vault, but Gmail remains the external source of record. Email contains untrusted HTML, remote resources, attachments, quoted history, and private secrets. Ingestion must also stay separate from AI enrichment.

### Decision
Gmail is implemented as a single production connector behind a narrow provider boundary. OAuth uses the local installed-app flow with the minimum practical read-only scope, `gmail.readonly`. OAuth client secrets and tokens are private generated state under `GANG_HOME/ingestion/gmail/`, and are never written to Git or canonical Markdown.

Canonical vault records are thread-level documents with `type: email-thread`; individual Gmail messages remain immutable raw evidence. Canonical email Markdown is stored in `GANG_HOME/vault/emails/...`; raw message MIME is stored in `GANG_HOME/raw/gmail-message/...`; thread manifests are stored in `GANG_HOME/raw/gmail-thread/...`; attachments are stored in `GANG_HOME/raw/gmail-attachment/...` with filename, MIME type, parent message, content hash, and raw reference. Source identity uses Gmail thread IDs, Gmail message IDs, and Gmail attachment IDs, never subject, sender, or timestamp alone.

The first sync must be explicitly bounded with a value such as `gang ingest gmail --since 30d`. Later `gang ingest gmail` runs use a private checkpoint based on the maximum successfully processed Gmail internal date. The checkpoint is only advanced after a failure-free sync, so a partial failure cannot skip undiscovered or unprocessed source evidence.

Canonical email-thread documents default to `visibility: private` and `status: active`. They are written outside `brain/vault/public/`, are indexed only by the private SQLite FTS index, and must not enter the public renderer, sitemap, feeds, Content API, AgentMap, or public search. Gmail ingestion is deterministic and never invokes AI; optional enrichment remains an explicit later `gang enrich DOCUMENT_ID` workflow.

### Why
This preserves Gmail as authoritative source evidence while allowing local deterministic search and provenance. Thread-level canonical documents match how email conversations are understood by humans without duplicating one Markdown file per message.

### Consequences
Local setup requires creating a Google OAuth desktop client, saving the client secret JSON as `GANG_HOME/ingestion/gmail/oauth_client_secret.json`, running `gang ingest gmail auth`, and then starting with a bounded sync. HTML email is normalized to safe text for canonical Markdown while the original MIME remains authoritative in raw storage. Attachments are preserved for provenance only; they are not OCRed, executed, summarized, or transformed.

### Revisit when
Additional connectors are approved or Gmail incremental history IDs are needed for high-volume mailbox synchronization.

## 2026-09-20 - Google Drive ingestion source boundary

**Status:** Accepted

### Context
Private documents in Google Drive should become durable local knowledge without making Drive a second vault, search database, or AI workflow. Drive files are mutable external source records with stable file IDs, mutable names, folder locations, revision markers, and format-specific download/export behavior.

### Decision
Google Drive is implemented as one production connector behind a narrow provider boundary. OAuth uses a local installed-app flow with the read-only Drive scope, `drive.readonly`. OAuth client secrets and tokens are stored separately from Gmail under `GANG_HOME/ingestion/drive/`, and are never written to Git, canonical Markdown, or searchable output.

Source identity is the Google Drive file ID mapped to one stable GANG source ID and one stable canonical document UUID. Filenames, titles, folder paths, and URLs are metadata only. Renames and folder moves do not create new canonical documents. Unchanged content is idempotent; modified content creates a new immutable raw version and updates the same canonical UUID.

Supported v1 formats are Google Docs, PDFs, Markdown/plain text, and a replaceable DOCX extraction boundary. Google Sheets, Slides, Forms, drawings, audio/video, and arbitrary binaries are explicitly unsupported for semantic normalization. Unsupported files preserve source/raw evidence where practical but do not create misleading canonical knowledge.

Canonical Drive documents are stored under `GANG_HOME/vault/documents/` with `type: document`, `visibility: private`, `status: active`, untrusted-content marking, Drive metadata, and provenance back to source ID, Drive file ID, source version/revision marker, content hash, and raw evidence. Private FTS indexes normalized Drive documents through the existing SQLite index. Drive ingestion never calls AI; enrichment remains an explicit later proposal workflow.

Initial sync must be bounded by `--since` and/or `--folder`. Later unbounded `gang ingest drive` uses the Drive changes checkpoint. Checkpoints advance only after a failure-free sync, preserving retry safety across partial failures and rate limits.

### Why
This preserves Drive as the authoritative external source while making deterministic local private search possible. Keeping Drive state in the existing raw store, registry, vault, and FTS index avoids a parallel knowledge system and keeps the public/private boundary auditable.

### Consequences
Operators must create a Google OAuth desktop client, save it as `GANG_HOME/ingestion/drive/oauth_client_secret.json`, run `gang ingest drive auth`, and begin with a bounded sync such as `gang ingest drive --since 30d` or `gang ingest drive --folder DRIVE_FOLDER_ID`.

Drive-derived content remains private by default and is excluded from public builds, feeds, public search, Content API, AgentMap, and generated public structured output. OCR, Sheets/Slides semantic modeling, comments ingestion, embeddings, background scheduling, and automatic AI enrichment remain out of scope.

### Revisit when
Additional Drive formats need deliberate semantic models, or a dedicated document conversion adapter is introduced for richer non-Google office formats.

## Durable Private Brain Home

**Status:** Accepted

### Context
Private knowledge was previously written inside individual Git worktrees under ignored paths such as `brain/vault/emails/`, `brain/raw/`, and `brain/generated/`. That made private knowledge accidentally dependent on one checkout or Conductor workspace.

### Decision
Private GANG knowledge and runtime state now live under a centralized private home. The default is `~/.gang`, and `GANG_HOME=/custom/path` overrides it. Repository-owned public content remains under `brain/vault/public/`.

The logical search corpus is `brain/vault/public/` plus `GANG_HOME/vault/`. The generated SQLite FTS database is stored under `GANG_HOME/generated/brain.sqlite`. Public builds continue to consume only `brain/vault/public/`.

Private ingestion state, Gmail checkpoints, OAuth token state, raw evidence, enrichment proposals/audit, and connector runtime state are stored under `GANG_HOME`. Secrets are not searchable and are never copied into canonical Markdown.

### Consequences
Multiple Git worktrees that use the same `GANG_HOME` see the same private corpus. `gang brain status` reports counts and paths without printing private content. `gang brain migrate` dry-runs migration from the old repo-local layout, and `gang brain migrate --apply` copies private state into `GANG_HOME` without deleting source files.

## 2026-09-20 - Stable entity identity and evidence-backed relationships

**Status:** Accepted

### Context
The corpus could search documents from Gmail, Drive, meetings, and local files, but concepts such as `Frank`, `Eliro`, and `GANG` existed only as repeated strings. Nothing connected a Gmail thread and a Drive document that referred to the same person. Epic 05 enrichment already proposed `people`, `companies`, and `projects` string arrays, which look like identity but are not.

### Decision
Canonical entity identity is an opaque UUIDv7 stored in a Markdown/YAML record under `GANG_HOME/vault/{people,companies,projects,products}`, marked with `record: entity`. Names, aliases, slugs, paths, email addresses, and domains are lookup keys, never identity. The ontology is limited to `person`, `company`, `project`, and `product`; arbitrary nouns, tags, topics, and technologies stay tags.

Mentions and relationships are modeled separately. A mention (`entity_refs`) records that a document refers to an entity and proves nothing else. A relationship assertion (`entity_relationships`) is typed against a small versioned predicate vocabulary, stored on the document that carries its evidence, and must include an evidence excerpt that literally appears in that document. Co-occurrence never produces an edge.

Both fields are additive. Legacy `people`/`companies`/`projects` strings are preserved unchanged and treated only as resolution candidates. No destructive migration was performed.

Resolution is deterministic and ordered: exact canonical name, exact normalized alias, strong deterministic identifier (email, domain), then unresolved. Normalization folds case, unicode form, and whitespace only, so `ELIRO` matches `Eliro` while `Eliro Inc.` stays distinct. Similar names are surfaced as candidates requiring confirmation and are never auto-merged. Shared lookup keys resolve to `ambiguous` with no winner.

AI may propose mentions and relationships; only an explicit `gang entity apply` mutates canonical data. `gang entity propose` defaults to a deterministic proposer over existing metadata, and AI is opt-in via `--ai`. Proposals record the base document hash and reject as stale when the document changed, reusing Epic 05 enrichment semantics. New entities named in a proposal require `--create-new`.

Merge is supported but always explicit: `gang entity merge SOURCE TARGET` tombstones the source rather than deleting it, absorbs its aliases and identifiers, deterministically rewrites stable references, supersedes self-collapsing edges, and writes an audit record.

Generated entity, alias, mention, and relationship tables live inside the single existing `GANG_HOME/generated/brain.sqlite` database. No graph database, second database, embedding store, or vector index was introduced.

### Why
Separating identity from names is what lets Gmail and Drive documents converge on one entity without guessing. Requiring verifiable evidence for relationships keeps the graph grounded in immutable source evidence instead of model inference. Keeping canonical state in Markdown and SQLite disposable means the graph can always be rebuilt, and a schema change never risks knowledge loss. Keeping the ontology and predicate vocabulary small avoids an unbounded modeling project that the current use cases do not need.

### Consequences
Canonical documents gain optional additive `entity_refs` and `entity_relationships` frontmatter. Connectors carry these fields forward when regenerating a document from changed source evidence, so applied references survive normal Gmail and Drive syncing. Applied enrichment fields such as `summary` are still regenerated from source on re-ingestion, which predates this epic and remains open.

Private entities never reach public output: they live only under `GANG_HOME`, writing entity references to a public document is refused, and public content validation rejects `entity_refs`/`entity_relationships` in public frontmatter. The public build is byte-identical apart from timestamps whether or not entities exist.

`gang index build` now also rebuilds the entity graph, and `gang index status` reports entity, mention, and relationship counts.

### Revisit when
Additional entity types are genuinely needed, legacy `people`/`companies`/`projects` strings are ready for a deliberate migration onto stable references, or free-form question answering requires the graph to expose more than deterministic structural queries.
