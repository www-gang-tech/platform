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

### Company-record folders

Ingest one or more explicitly configured folders and all their subfolders. Only those folders are listed; the rest of the Drive never is, and shortcuts aren't followed out of the tree.

```sh
python3 cli/gang/cli.py ingest drive folders add DRIVE_FOLDER_ID --label "Company Records"
python3 cli/gang/cli.py ingest drive folders                 # list configured folders
python3 cli/gang/cli.py ingest drive --configured --dry-run  # what would change; writes nothing
python3 cli/gang/cli.py ingest drive --configured            # ingest, link, refresh facts and index
python3 cli/gang/cli.py ingest drive --folder ID --recursive # one-off, without configuring
python3 cli/gang/cli.py ingest drive status --failures       # files that need OCR or could not be read
```

The configuration lives in `GANG_HOME/ingestion/drive/folders.yml`. Traversal is bounded (8 levels, 5,000 files per folder) so a wrong ID can't become a crawl. Each document records its folder path (`drive.folder_path`, e.g. `Company Records/Legal`), the configured root folder, the Drive revision, modified time, content hash, and source URL. A file whose revision, metadata, and extractor version are all unchanged isn't downloaded again.

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

- Google Docs are exported deterministically as Markdown and normalized.
- PDF, DOCX, Markdown, and plain text go through the same extractor as Gmail attachments (`core/ingestion/extract.py`). PDF text comes from the embedded text layer via `pypdf`. OCR is never performed: a PDF without a text layer is recorded as `requires-ocr`, and no canonical document is written or overwritten.
- Password-protected, corrupt, and empty files are recorded with their status and never abort a run.

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
