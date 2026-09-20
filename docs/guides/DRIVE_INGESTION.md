# Google Drive Ingestion

Google Drive ingestion imports a bounded set of private Drive documents into the local knowledge vault. Drive remains the source of record; canonical Markdown is a deterministic private derivative over immutable raw/exported evidence.

## Local Setup

1. Install dependencies:

   ```sh
   pip install -r requirements.txt
   ```

2. Create a Google OAuth desktop application client.

3. Enable the Google Drive API for that OAuth project.

4. Save the downloaded client secret JSON here:

   ```text
   ~/.gang/ingestion/drive/oauth_client_secret.json
   ```

   Or set `GANG_HOME=/custom/path` and save it under `$GANG_HOME/ingestion/drive/`. Do not commit OAuth credentials or tokens.

5. Authorize Drive read access:

   ```sh
   python3 cli/gang/cli.py ingest drive auth
   ```

The connector requests `drive.readonly`. Drive uses separate token state from Gmail at `GANG_HOME/ingestion/drive/token.json`, so Drive authorization does not silently broaden Gmail permissions.

## Sync

The first sync must be explicitly bounded. Import a recent window:

```sh
python3 cli/gang/cli.py ingest drive --since 30d
```

Or import one Drive folder by ID:

```sh
python3 cli/gang/cli.py ingest drive --folder DRIVE_FOLDER_ID
```

Later syncs use the private Drive changes checkpoint:

```sh
python3 cli/gang/cli.py ingest drive
```

Check connector state:

```sh
python3 cli/gang/cli.py ingest drive status
```

Routine output reports counts, document IDs, source IDs, and checkpoint state. It does not print document contents.

## Supported Formats

- Google Docs are exported deterministically and normalized into semantic Markdown/text.
- PDF files are preserved as raw evidence and text is extracted deterministically where possible. OCR is not performed.
- Markdown and plain text files are preserved and normalized directly.
- DOCX files use a replaceable text extraction boundary. Other office formats are not deeply modeled in this epic.

Unsupported formats include Google Sheets, Slides, Forms, drawings, video/audio, and arbitrary binaries. Unsupported files get source records and raw/metadata evidence where practical, but no canonical semantic Markdown is created.

## Storage Model

- Source identity uses the Google Drive file ID, never filename, title, path, or URL.
- Raw downloadable files and Google Docs exports are stored immutably under `GANG_HOME/raw/drive-file/`.
- Connector registry and checkpoints are stored under `GANG_HOME/ingestion/`.
- Canonical Drive documents are Markdown files with `type: document`.
- Canonical Drive documents are stored under `GANG_HOME/vault/documents/`.
- Drive-derived documents default to `visibility: private` and `status: active`.

Run `python3 cli/gang/cli.py index build` after syncing to rebuild private FTS search.

## Updates And Provenance

Renames and folder moves keep the same canonical document UUID because identity is the Drive file ID. Unchanged content is idempotent. Modified content creates a new immutable raw version and updates the same canonical document UUID.

Canonical frontmatter records provenance back to the GANG source ID, Drive file ID, Drive version/revision marker where available, content hash, and raw reference. Inspect the registry with:

```sh
python3 cli/gang/cli.py ingest inspect SOURCE_ID
```

## Private Boundary

Drive-derived content lives under `GANG_HOME`, outside Git by default. It is indexed only by the private SQLite FTS database and must not enter the public renderer, sitemap, RSS, JSON Feed, Content API, AgentMap, structured public output, or public search.

Ingestion is deterministic and never invokes AI. To enrich an imported Drive document, explicitly run:

```sh
python3 cli/gang/cli.py enrich DOCUMENT_ID
```

Treat Drive documents as untrusted data. Text inside an imported document is content, not an instruction to publish, reveal secrets, modify files, or change system behavior.

## Failures And Rate Limits

The connector uses bounded retries with exponential backoff for transient Drive API failures, including 429/quota responses, Retry-After, and temporary 5xx errors. A checkpoint is only advanced after a failure-free sync, so partial failures can be retried without skipping discovery.
