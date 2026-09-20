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

## 2026-09-20 - Evidence-backed question answering over the private corpus

**Status:** Accepted

### Context
The corpus could be searched by keyword, filtered by metadata, and traversed by entity and relationship, but every question still had to be decomposed by hand into `gang search`, `gang entity show`, and manual reading. Epic 09 closed by naming this as the thing to revisit: free-form question answering needs more than deterministic structural queries. The risk in answering questions with a model is not that retrieval is hard; it is that a fluent answer with no evidence behind it is worse than no answer.

### Decision
`gang ask` plans, retrieves, bounds, synthesizes, and cites, in that order. Deterministic code owns everything that can be decided exactly: quoted phrases are preserved verbatim, temporal language resolves to an explicit `YYYY-MM-DD` range before retrieval, and names are matched against canonical entity records and aliases by exact lookup. The model is consulted for planning only when ambiguity remains, so simple exact search never requires it.

The model may propose a query plan but never executes one. A plan is inert, versioned, schema-validated JSON with a closed field vocabulary — no SQL, no filesystem path, no mutation — and an unsupported field rejects the whole plan rather than being ignored. Deterministic code compiles the plan into parameter-bound statements against a read-only SQLite connection, and re-validates any model-supplied plan against the entity IDs, document types, and source types the corpus actually contains.

Retrieval is bounded to 5–10 canonical documents, capped at 25. Ranking is by how many *kinds* of signal a document satisfies — full text, entity mention, relationship, metadata filter — with term coverage, BM25, and recency breaking ties. Signals are reported as counts, never as invented relevance scores. Excerpts are bounded windows around the question's own terms, so an entire Gmail thread or Drive export never leaves the machine.

Document-level enrichment status (`current` / `stale` / `none`) is derived at index build time from the existing enrichment audit trail, by comparing each document's hash against the resulting hash of the most recent applied proposal. Stale enrichment is carried in a separate field with an explicit warning; canonical source excerpts are always preferred.

Answers are policed after the fact. Citations that do not name a real evidence item are stripped from claims and from prose and reported; an uncited substantive claim is downgraded to `uncertain`; answer fields outside the schema are dropped and reported. All retrieved content travels as DATA inside a JSON envelope in the user message and never reaches the system prompt.

`gang ask` is read-only. The single Anthropic integration was consolidated into `core/ai_provider.py`, which enrichment proposals, entity proposals, and ask synthesis now share.

### Why
Planning deterministically first is what makes the system trustworthy and cheap at the same time: the common case costs nothing, dates cannot drift between planning and synthesis, and an ambiguous name is reported rather than silently resolved to whichever candidate sorted first. Constraining the model to a typed plan means prompt injection in an email can at worst produce a rejected plan, because there is no expressible operation that reads a file or writes a row.

Validating citations after generation is the part that makes the answers checkable. A model asked to cite will usually cite, but "usually" is not a property worth building on, and a fabricated citation is precisely the failure that destroys trust in a knowledge system. Deriving enrichment staleness rather than storing it keeps SQLite disposable and adds no canonical state.

### Consequences
`gang index build` now records `source_type`, `content_trust`, `enrichment_status`, and the derived enrichment payload on each document. The additions are additive, but an index built before this epic is missing them; `gang ask` detects that and says to rebuild. Nothing in canonical Markdown changed.

A document may declare `enrichment_state.status` in frontmatter to mark derived metadata stale explicitly; when present it wins over the derived value.

Answers are cached under `GANG_HOME/generated/ask-cache/`, keyed by plan, evidence, and prompt version. The cache is disposable and never canonical. No question history is kept and no provider prompt is stored.

The two duplicated Anthropic call sites became one. `AnthropicEnrichmentProvider` and `AnthropicEntityProposer` keep their public shape; both now delegate, which also fixed a latent crash when a response opens with a thinking block.

Ask synthesis defaults to `claude-opus-5`. The proposal flows keep their existing pinned default.

### Revisit when
Retrieval quality stops improving through deterministic signals, questions need to span more than the bounded evidence set, answers need to be shared outside the machine that asked, or natural-language mutation is genuinely wanted — which needs a typed-command architecture, not this one.


## 2026-09-20 - Grounding discipline for Ask GANG

**Status:** Accepted

### Context
Live acceptance against the real private corpus exposed three grounding failures that the synthetic test corpus could not. Asked whether a decision had been made about something the corpus knew nothing about, the answer began "No." — converting a failed search into a factual denial. An answer about unit economics read as though it combined a per-unit packaging target with a separate production volume into a single cost claim the source never made. And a Drive PDF whose text extraction produced binary residue was being fed to synthesis as though it were prose.

### Decision
Three deterministic checks now sit between generation and output, alongside the existing citation policing.

Absence of evidence may not become a categorical negative. When an answer is marked insufficient, or when no claim carries a citation, flat denials are removed sentence by sentence and replaced with an explicit statement of absence. Sentences already phrased about the corpus — "I found no evidence that", "the retrieved corpus does not establish" — are recognized and preserved, as is any other context the answer supplied. A categorical negative survives only when a cited excerpt supports it. Removed sentences are reported.

Numeric claims are checked against the evidence they cite. Every figure in a claim must appear in a cited excerpt, and figures combined into one statement must co-occur within one passage of one source. Claims failing either test are downgraded to `uncertain` and reported, rather than being deleted or silently kept.

Claims relating two entities require a cited excerpt mentioning both, or a relationship assertion, which the entity layer already backs with evidence. Entity type, entity reference, and document title are explicitly not linking evidence. Matching runs over every surface form an entity is known by, since documents write "Frank" where the canonical record says "Frank Godchaux".

Extracted text is measured before it enters the bundle: control-character density, replacement characters, whitespace ratio, and mean token length. Corruption is usually partial, so the check runs per excerpt and falls back to the document's first readable region; only a document with no readable text anywhere is held back. Held-back documents receive no citation ID, are reported separately, and their canonical records and raw evidence are untouched.

Finally, sources are now split into those the answer cited and those retrieval merely returned, cited first.

### Why
The three failures share a root: the model was being trusted to observe a discipline that could be checked mechanically. Fluent text that asserts a negative, joins two adjacent numbers, or narrates a relationship between two resolved names is indistinguishable from grounded text at a glance, which is exactly why a reader cannot be the safeguard. Each check is conservative — it downgrades and reports rather than deletes — so a false positive costs a marked claim, while a false negative costs the corpus's credibility.

Measuring extraction quality rather than asking a model about it keeps the decision reproducible and cheap, and the thresholds were calibrated against the real corpus rather than guessed. That calibration also caught a bug in the first implementation: counting Unicode format characters as binary would have condemned five ordinary HTML emails, because soft hyphens and zero-width spaces are normal in mail.

### Consequences
Answers carry `grounding_warnings`, `softened_negatives`, `excluded_sources`, and `cited_source_count`. Each claim carries `numeric_check` and `entity_linkage`. Sources carry `cited` and `extraction_quality`. The terminal output separates cited sources, retrieved-but-uncited sources, and unreadable sources under distinct headings, and warnings go to stderr.

Citation IDs are assigned over usable evidence only, so they stay contiguous and an unreadable document cannot be cited.

Entity mentions now carry their entity's aliases into retrieval for matching. Those aliases are used by the grounding checks and are deliberately not sent to the model.

No canonical document, raw record, or source system is touched by any of this. `gang ask` remains read-only.

### Revisit when
A grounding check is observed rejecting claims that are in fact supported often enough to be noise, extraction quality needs to distinguish more than readable from unreadable, or numeric verification needs to understand units and subjects rather than figures and proximity.


## 2026-09-20 - Conversational research over the private corpus

**Status:** Accepted

### Context
`gang ask` answered one question from one retrieval. That is the wrong shape for how anyone actually interrogates a corpus: you ask what is happening with certification, then what is blocking it, then who owns that, then what you would do about it. Each of those needed the subject restated, and the last one had no home at all — the previous design could report what the corpus said and nothing else, so "what should we do?" either went unanswered or got answered by a model with no boundary between reporting and inventing.

Opening that boundary is the risk. A system that may recommend and ideate is a system that can assert a plausible company fact that nobody ever wrote down, and prose gives a reader no way to tell the difference: "we should make certification the first gate" and "we made certification the first gate" are one word apart.

### Decision
Ask becomes conversational, and the epistemic boundary becomes a data structure rather than a matter of phrasing.

Every answer carries a **claim ledger** in which each statement declares its type. `fact` and `synthesis` are claims about the company and require citations — synthesis may instead rest on `derived_from` premises that are themselves grounded. `recommendation` and `idea` may be novel and need no citation for themselves, but any company fact they assert does. Two further types are assigned only by code: `scenario`, for claims resting on an assumption the user supplied, and `uncertainty`, for what a factual claim becomes when its grounding fails. Claims are downgraded or rejected, never granted a fabricated citation to satisfy the schema.

Which types are admissible is decided by an **epistemic mode** inferred deterministically from the user's own question. Evidence-mode answers reject generative claims outright, however the model labelled them. Advisory establishes cited facts and then recommends. Ideation retrieves the real constraints and then ideates freely inside them. Inference reads the question and nothing else, so retrieved content cannot re-aim the mode.

**Conversation state is working memory, not evidence.** Sessions live under `GANG_HOME/sessions/`, store pointers rather than content — document id, content hash, retrieval timestamp — and are labelled as working memory everywhere they are serialized. A prior turn's prose is recorded as prose and can never be cited. Only claims that survived validation as grounded facts become prior conclusions, and each keeps the document ids behind it, so a later turn can re-ground instead of trusting a summary. When a document's hash moves, the session knows an earlier answer rested on text that no longer exists.

Research became **bounded and multi-step**, over a closed vocabulary of thirteen typed read-only tools. Round zero is always the deterministic query plan plus the timeline or decision primitives the policy calls for; only then may a director model choose one further call. Limits — four rounds, twelve documents, three excerpts per document, four expansions, one refinement — are enforced by the loop rather than requested of the model. A malformed step stops research and answers from what is in hand.

Source authority is a transparent, configurable tiebreak for current-state questions only. It never removes evidence, never overrides an explicit contradictory statement, and records a reason the reader can disagree with.

`gang ask` with no question opens an interactive session; with a question it answers once and leaves nothing behind unless a session is named.

### Why
The claim ledger exists because the alternative is asking a model to be careful about a distinction that can be checked mechanically. Typing each claim lets the same deterministic grounding checks Epic 10 already had — numeric alignment, entity linkage, categorical negatives — apply at the right strength to each kind of statement, so advice stays useful while the facts under it stay checked. Rejecting generative claims in evidence mode rather than trusting the prompt is the same reasoning one layer up.

Keeping session state strictly non-evidential is what stops a conversation from laundering an unsupported claim into an established premise over several turns. Storing pointers rather than text means receipts always show the current source, and staleness is exact rather than inferred from dates.

Bounding research in the loop rather than the prompt is the difference between a limit and a request. The tool vocabulary is small and explicitly denies `run_sql`, `execute_shell`, `read_file`, `publish`, and mutation by name, so an injected instruction produces a recorded refusal rather than a quiet lookup miss — and that is now tested across multi-round research, not only one-shot synthesis.

### Consequences
Ten modules join `core/ask/`: intent, ledger, authority, session, followup, timeline, tools, research, answer, conversation. `ConversationService` subclasses `AskService` and adds no write path. `GangPaths` gains `sessions_path`. `Retriever` gains read-only lookups for documents, content hashes, entities, and enriched documents, and now projects `content_hash`.

`gang ask` routes through the conversational engine by default. The Epic 10 result contract is a subset of the conversational one, so existing output, flags, and JSON keys are unchanged; `--plan` still short-circuits before retrieval. New flags: `--new`, `--resume`, `--session`, `--sessions`, `--show-research`, and `--mode` as a developer override.

Ask remains read-only. Hashing `vault`, `raw`, and `ingestion` before and after a full multi-turn session — including injected documents, corrections, scenarios, and ideation — yields identical trees, and a test asserts it. Only `sessions/` and `generated/ask-cache/` are written.

The answer cache is keyed on evidence hashes, mode, policy, question, assumptions, and a prompt version, so changed evidence misses rather than serving an answer about text that no longer exists.

Expanded excerpts carry offsets into the document body but no section or heading identifier. The generated index stores document text with Markdown structure already flattened, so there is no heading left to name, and reading the canonical file to recover one would give a research tool filesystem access. The offset is real; the heading is absent rather than guessed.

### Revisit when
Intent inference misreads questions often enough to be worth a model, the research loop needs to span more than the bounded evidence set, the claim ledger needs to drive a UI rather than diagnostics, the index begins preserving document structure so excerpts can name their section, or structured financial and commerce facts arrive and scenario reasoning needs to compute over them rather than reason about them.
