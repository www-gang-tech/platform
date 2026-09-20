# Gmail Ingestion

Gmail ingestion imports private email threads into the local knowledge vault. Gmail remains the source of record; canonical Markdown is a private, deterministic view over immutable raw evidence.

## Local Setup

1. Install dependencies:

   ```sh
   pip install -r requirements.txt
   ```

2. Create a Google OAuth desktop application client.

3. Save the downloaded client secret JSON here:

   ```text
   brain/vault/.ingestion/gmail/oauth_client_secret.json
   ```

   This directory is gitignored. Do not commit OAuth credentials or tokens.

4. Authorize the local workspace:

   ```sh
   python3 cli/gang/cli.py ingest gmail auth
   ```

The connector requests `gmail.readonly` only. The generated token is stored at `brain/vault/.ingestion/gmail/token.json` and is never written to canonical Markdown.

## Sync

The first sync must be bounded:

```sh
python3 cli/gang/cli.py ingest gmail --since 30d
```

Later syncs use the private checkpoint:

```sh
python3 cli/gang/cli.py ingest gmail
```

Check connector state:

```sh
python3 cli/gang/cli.py ingest gmail status
```

Routine output reports counts, document IDs, source IDs, and checkpoint state. It does not print full email bodies.

## Storage Model

- Raw Gmail message MIME is stored immutably under `brain/raw/gmail-message/`.
- Raw thread manifests are stored under `brain/raw/gmail-thread/`.
- Attachments are stored under `brain/raw/gmail-attachment/` with provenance only.
- Canonical documents are thread-level Markdown files with `type: email-thread`.
- Email-derived canonical documents default to `visibility: private` and `status: active`.

Run `python3 cli/gang/cli.py index build` after syncing to rebuild private FTS search.
