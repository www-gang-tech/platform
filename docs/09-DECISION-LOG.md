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
