# Legacy Content Rollback Source

`content/` is deprecated as a production authoring source.

Production public builds now load canonical public documents from:

`brain/vault/public/`

Use `content/` only for explicit rollback builds:

`gang build --source legacy`

Do not add new public content here. New public documents belong in the canonical vault.
