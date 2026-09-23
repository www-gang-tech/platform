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
   ~/.gang/ingestion/gmail/oauth_client_secret.json
   ```

   Or set `GANG_HOME=/custom/path` and save it under `$GANG_HOME/ingestion/gmail/`. Do not commit OAuth credentials or tokens.

4. Authorize the local workspace:

   ```sh
   python3 cli/gang/cli.py ingest gmail auth
   ```

The connector requests `gmail.readonly` only. The generated token is stored at `GANG_HOME/ingestion/gmail/token.json` and is never written to canonical Markdown.

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

## Attachments

Every attachment with a readable text layer becomes its own private canonical document under `GANG_HOME/vault/attachments/`. Sync does this automatically. For threads ingested earlier, backfill from the bytes already in raw custody. Nothing is downloaded again:

```sh
python3 cli/gang/cli.py ingest gmail attachments --dry-run   # report only, writes nothing
python3 cli/gang/cli.py ingest gmail attachments             # extract, link, refresh facts and index
python3 cli/gang/cli.py ingest gmail attachments --thread THREAD_ID --since 2026-01-01
python3 cli/gang/cli.py ingest gmail status --failures       # attachments that need OCR or could not be read
```

- **Formats:** plain text, Markdown, PDF with an embedded text layer, and DOCX. Images, calendar invites, spreadsheets, archives, and CAD files are reported as `unsupported`.
- **No OCR.** A PDF without a text layer is recorded as `requires-ocr` and left for a human decision. Password-protected, corrupt, empty, and oversized files get their own statuses. None of them aborts a run, and every original stays in raw custody.
- **Identity:** an attachment occurrence is (Gmail message ID, SHA-256 of its bytes). Gmail's `attachmentId` changes on every API response and is never used. The MIME part ID is recorded when Gmail provides it.
- **One document per distinct payload.** The same PDF attached to five replies is extracted once. Its document lists all five occurrences (message, thread, filename, received time, source account) under `provenance.occurrences`, and each occurrence keeps its own registry record.
- **The thread document is unchanged.** It still lists attachment filenames and never includes their contents.
- **Idempotent.** Re-running over unchanged sources writes nothing: same documents, same registry, no new raw versions.

Trace any document or evidence fact back to its source:

```sh
python3 cli/gang/cli.py ingest inspect DOCUMENT_ID_OR_FACT_ID
```

This reports the attachment, every email and thread that carried it, the raw reference, whether the original bytes still match the hash recorded at extraction, and which facts the document supports.

## Storage Model

- Raw Gmail message MIME is stored immutably under `GANG_HOME/raw/gmail-message/`.
- Raw thread manifests are stored under `GANG_HOME/raw/gmail-thread/`.
- Attachment bytes are stored immutably under `GANG_HOME/raw/gmail-attachment/`, one source per (message, content hash).
- Extracted attachment documents are stored under `GANG_HOME/vault/attachments/` with `type: document`, `source_type: gmail-attachment`, `visibility: private`, and `content_trust: untrusted`.
- Connector registry and checkpoints are stored under `GANG_HOME/ingestion/`.
- Canonical documents are thread-level Markdown files with `type: email-thread`.
- Canonical email documents are stored under `GANG_HOME/vault/emails/`.
- Email-derived canonical documents default to `visibility: private` and `status: active`.

Run `python3 cli/gang/cli.py index build` after syncing to rebuild private FTS search.
