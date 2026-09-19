# Migration Analysis

Dry-run only. No content files were moved or rewritten.

## Summary

- Total files analyzed: 20
- Canonical migration candidates: 9
- Excluded from migration: 11
- Currently public: 9
- Drafts: 0
- Scheduled: 0
- Ambiguous: 0
- Migration-safe: 8
- Review-required: 1
- URL conflicts: 0
- Product records: 0
- Invalid records: 0

## Per-Document Table

| Path | Source Classification | UUID | Current URL | Proposed URL | Type | Visibility | Status | Target Vault Path | Migration Status | Warnings | Notices |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| content/comments/README.md | documentation |  |  |  | comment | private | draft |  | excluded_from_migration | Missing title<br>Not part of current production build inputs | Excluded from canonical migration: documentation |
| content/examples/drop-example.md | fixture/example |  |  |  | drop | private | draft |  | excluded_from_migration | Not part of current production build inputs | Excluded from canonical migration: fixture/example |
| content/examples/link-example.md | fixture/example |  |  |  | link | private | draft |  | excluded_from_migration | Not part of current production build inputs | Excluded from canonical migration: fixture/example |
| content/examples/note-example.md | fixture/example |  |  |  | note | private | draft |  | excluded_from_migration | Missing title<br>Not part of current production build inputs | Excluded from canonical migration: fixture/example |
| content/examples/product-example.md | fixture/example |  |  |  | product | private | draft |  | excluded_from_migration | Missing referenced media: /images/qi2-charger.jpg<br>Not part of current production build inputs | Excluded from canonical migration: fixture/example |
| content/examples/sheet-example.md | fixture/example |  |  |  | sheet | private | draft |  | excluded_from_migration | Not part of current production build inputs | Excluded from canonical migration: fixture/example |
| content/examples/shot-example.md | fixture/example |  |  |  | shot | private | draft |  | excluded_from_migration | Missing referenced media: /images/desk-setup.jpg<br>Not part of current production build inputs | Excluded from canonical migration: fixture/example |
| content/examples/update-example.md | fixture/example |  |  |  | update | private | draft |  | excluded_from_migration | Not part of current production build inputs | Excluded from canonical migration: fixture/example |
| content/newsletters/qi2-launch-newsletter.md | canonical_content | 01a0b77f-e414-7661-bcbc-4c96e6f3453d | /newsletters/qi2-launch-newsletter/ | /newsletters/qi2-launch-newsletter/ | newsletter | public | published | brain/vault/public/newsletters/qi2-launch-newsletter.md | migration_safe |  | legacy_publication_inferred: missing status maps to public/published because this file is a current production input |
| content/pages/about.md | canonical_content | 01a0b77f-e414-7c9a-8379-63d4fc9af42a | /pages/about/ | /pages/about/ | page | public | published | brain/vault/public/pages/about.md | migration_safe |  |  |
| content/pages/contact.md | canonical_content | 01a0b77f-e414-7884-93c8-82f380217ee2 | /pages/contact/ | /pages/contact/ | page | public | published | brain/vault/public/pages/contact.md | migration_safe |  | legacy_publication_inferred: missing status maps to public/published because this file is a current production input |
| content/pages/faq.md | canonical_content | 01a0b77f-e414-7314-964b-4b3fcc7175a2 | /pages/faq/ | /pages/faq/ | page | public | published | brain/vault/public/pages/faq.md | migration_safe |  | legacy_publication_inferred: missing status maps to public/published because this file is a current production input |
| content/pages/features.md | canonical_content | 01a0b77f-e414-756b-869b-e1ec878d81ff | /pages/features/ | /pages/features/ | page | public | published | brain/vault/public/pages/features.md | migration_safe |  | legacy_publication_inferred: missing status maps to public/published because this file is a current production input |
| content/pages/manifesto.md | canonical_content | 01a0b77f-e414-7fe4-bbf2-389f7dd9681b | /pages/manifesto/ | /pages/manifesto/ | page | public | published | brain/vault/public/pages/manifesto.md | migration_safe |  | legacy_publication_inferred: missing status maps to public/published because this file is a current production input |
| content/pages/wcag-conformance.md | canonical_content | 01a0b77f-e414-7efa-bc35-8542758bfb73 | /pages/wcag-conformance/ | /pages/wcag-conformance/ | page | public | published | brain/vault/public/pages/wcag-conformance.md | migration_safe |  | legacy_publication_inferred: missing status maps to public/published because this file is a current production input |
| content/people/contributor-example.md | fixture/example |  |  |  | person | private | published |  | excluded_from_migration | Not part of current production build inputs | Excluded from canonical migration: fixture/example |
| content/people/jane-doe.md | fixture/example |  |  |  | person | private | published |  | excluded_from_migration | Missing referenced media: /assets/images/jane-doe.jpg<br>Not part of current production build inputs | Excluded from canonical migration: fixture/example |
| content/people/john-smith.md | fixture/example |  |  |  | person | private | published |  | excluded_from_migration | Missing referenced media: /assets/images/john-smith.jpg<br>Not part of current production build inputs | Excluded from canonical migration: fixture/example |
| content/posts/qi2-launch.md | canonical_content | 01a0b77f-e414-7c87-a9c9-5604c425823c | /posts/qi2-launch/ | /posts/qi2-launch/ | post | public | published | brain/vault/public/posts/qi2-launch.md | review_required | Missing date<br>Missing title | legacy_publication_inferred: missing status maps to public/published because this file is a current production input |
| content/projects/design-system-rebuild.md | canonical_content | 01a0b77f-e414-7772-a2b8-b72621d2fa0d | /projects/design-system-rebuild/ | /projects/design-system-rebuild/ | project | public | published | brain/vault/public/projects/design-system-rebuild.md | migration_safe |  |  |

## Source Classification

| Classification | Count | Paths |
| --- | --- | --- |
| canonical_content | 9 | content/newsletters/qi2-launch-newsletter.md<br>content/pages/about.md<br>content/pages/contact.md<br>content/pages/faq.md<br>content/pages/features.md<br>content/pages/manifesto.md<br>content/pages/wcag-conformance.md<br>content/posts/qi2-launch.md<br>content/projects/design-system-rebuild.md |
| documentation | 1 | content/comments/README.md |
| fixture/example | 10 | content/examples/drop-example.md<br>content/examples/link-example.md<br>content/examples/note-example.md<br>content/examples/product-example.md<br>content/examples/sheet-example.md<br>content/examples/shot-example.md<br>content/examples/update-example.md<br>content/people/contributor-example.md<br>content/people/jane-doe.md<br>content/people/john-smith.md |

## URL Preservation

| Current URL | Proposed URL | Status | Path |
| --- | --- | --- | --- |
| /newsletters/qi2-launch-newsletter/ | /newsletters/qi2-launch-newsletter/ | unchanged | content/newsletters/qi2-launch-newsletter.md |
| /pages/about/ | /pages/about/ | unchanged | content/pages/about.md |
| /pages/contact/ | /pages/contact/ | unchanged | content/pages/contact.md |
| /pages/faq/ | /pages/faq/ | unchanged | content/pages/faq.md |
| /pages/features/ | /pages/features/ | unchanged | content/pages/features.md |
| /pages/manifesto/ | /pages/manifesto/ | unchanged | content/pages/manifesto.md |
| /pages/wcag-conformance/ | /pages/wcag-conformance/ | unchanged | content/pages/wcag-conformance.md |
| /posts/qi2-launch/ | /posts/qi2-launch/ | unchanged | content/posts/qi2-launch.md |
| /projects/design-system-rebuild/ | /projects/design-system-rebuild/ | unchanged | content/projects/design-system-rebuild.md |

## Conflicts

- **record_warning**: Missing date
- **record_warning**: Missing title

## Product Analysis

### content/examples/product-example.md

- Editorial knowledge fields: assets, cta, date, seo, syndicate, tags, title, type
- External authority fields: availability, price, sku
- Generated legacy fields: jsonld
- Unknown product fields: none

