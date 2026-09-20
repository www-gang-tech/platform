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
