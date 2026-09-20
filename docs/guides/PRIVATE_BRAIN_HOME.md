# Private Brain Home

GANG separates repository content from private knowledge/runtime state.

Repository-owned:

- Code, schemas, migrations, docs, and tests.
- Explicitly public canonical content under `brain/vault/public/`.

Private-home owned:

- Private canonical Markdown under `GANG_HOME/vault/`.
- Raw source evidence under `GANG_HOME/raw/`.
- Attachment/blob storage under `GANG_HOME/blobs/`.
- Connector state, ingestion registry, Gmail checkpoint, and OAuth token state under `GANG_HOME/ingestion/`.
- Enrichment proposals and audit logs under `GANG_HOME/enrichment/`.
- Rebuildable private search index under `GANG_HOME/generated/brain.sqlite`.

## Location

Default:

```sh
~/.gang
```

Override:

```sh
export GANG_HOME=/path/to/private-gang-home
```

Use the same `GANG_HOME` from multiple worktrees to share one private corpus.

## Commands

Check status without printing private content:

```sh
python3 cli/gang/cli.py brain status
```

Rebuild the private search index from repo-public plus private-home documents:

```sh
python3 cli/gang/cli.py index build
```

Search the combined private index:

```sh
python3 cli/gang/cli.py search "distinctive phrase"
```

Public builds remain public-only and read `brain/vault/public/`; private-home documents are not published automatically.

## Migration

Dry run from the current workspace:

```sh
python3 cli/gang/cli.py brain migrate
```

Dry run from another workspace:

```sh
python3 cli/gang/cli.py brain migrate --from /path/to/old/workspace
```

Apply after reviewing the report:

```sh
python3 cli/gang/cli.py brain migrate --apply
```

Migration copies private documents, raw evidence, ingestion state, Gmail checkpoints, and enrichment state into `GANG_HOME`. It does not delete source files, does not touch `brain/vault/public/`, and refuses conflicting overwrites.

## Backup

`GANG_HOME` contains private canonical knowledge and runtime state. Back it up intentionally. Generated indexes are rebuildable, but raw evidence, registry state, OAuth state, and canonical private Markdown should be treated as durable private data.

Sync is not backup: if you later put `GANG_HOME` on a synced folder, keep an independent backup and avoid exposing secrets or private Markdown to systems you do not trust.
