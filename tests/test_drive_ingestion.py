import hashlib
import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import yaml
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli" / "gang"))

import cli as gang_cli
from core.content_loader import load_public_content
from core.ingestion.drive import (
    DRIVE_READONLY_SCOPE,
    GOOGLE_DOC_MIME,
    PDF_MIME,
    DriveChangeBatch,
    DriveFile,
    DriveIngestionError,
    DriveRetryPolicy,
    DriveSyncService,
    GoogleDriveProvider,
)
from core.private_index import PrivateKnowledgeIndex

sys.path.insert(0, str(Path(__file__).resolve().parent))
from document_fixtures import text_pdf  # noqa: E402


def gang_home(root):
    return root / "gang-home"


def drive_file(
    file_id="drive-doc-1",
    name="Certification Plan",
    mime_type=GOOGLE_DOC_MIME,
    modified_time="2026-01-02T00:00:00Z",
    parents=None,
    version="1",
):
    return DriveFile(
        file_id=file_id,
        name=name,
        mime_type=mime_type,
        web_view_link=f"https://drive.google.com/file/d/{file_id}/view",
        created_time="2026-01-01T00:00:00Z",
        modified_time=modified_time,
        owners=["alice@example.test"],
        parents=parents or ["folder-a"],
        version=version,
    )


def frontmatter(path):
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])


def registry_record(root, source_id):
    registry = json.loads((gang_home(root) / "ingestion/registry.json").read_text(encoding="utf-8"))
    return registry["sources"][source_id]


def assert_raw_versions_match_physical(testcase, service, record):
    seen_refs = set()
    for item in record["versions"]:
        testcase.assertIn("raw_version", item)
        testcase.assertIn("payload_hash", item)
        testcase.assertNotIn(item["raw_ref"], seen_refs)
        seen_refs.add(item["raw_ref"])
        payload = service.raw_store.read(item["raw_ref"])
        testcase.assertEqual(hashlib.sha256(payload).hexdigest(), item["payload_hash"])


class MockDriveProvider:
    def __init__(self, files=None, payloads=None, changes=None, fail_files=None):
        self.files = files or []
        self.payloads = payloads or {}
        self.changes = changes or {}
        self.fail_files = set(fail_files or [])
        self.discover_calls = []
        self.change_calls = []
        self.fetch_calls = []
        self.token = "token-1"

    def discover_files(self, *, since=None, folder_id=None):
        self.discover_calls.append({"since": since, "folder_id": folder_id})
        return list(self.files)

    def discover_changes(self, page_token):
        self.change_calls.append(page_token)
        files, token = self.changes.get(page_token, ([], page_token))
        return DriveChangeBatch(list(files), token)

    def fetch_file(self, drive_file):
        self.fetch_calls.append(drive_file.file_id)
        if drive_file.file_id in self.fail_files:
            raise RuntimeError("temporary Drive quota failure")
        payload = self.payloads[drive_file.file_id]
        filename = drive_file.name
        export_mime_type = None
        if drive_file.mime_type == GOOGLE_DOC_MIME:
            filename = f"{drive_file.name}.md"
            export_mime_type = "text/markdown"
        return type("Payload", (), {"payload": payload, "filename": filename, "export_mime_type": export_mime_type})()

    def current_start_page_token(self):
        return self.token


class FakeResponse:
    def __init__(self, status, headers=None):
        self.status = status
        self.headers = headers or {}

    def get(self, key, default=None):
        for header, value in self.headers.items():
            if header.lower() == key.lower():
                return value
        return default


class FakeGoogleError(Exception):
    def __init__(self, status, message, headers=None):
        super().__init__(message)
        self.resp = FakeResponse(status, headers=headers)
        self.content = json.dumps({"error": {"code": status, "message": message}}).encode("utf-8")


class SequencedRequest:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def execute(self):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeClock:
    def __init__(self):
        self.now = 100.0
        self.sleeps = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def drive_service(provider, root):
    return DriveSyncService(provider, root_path=root, private_home=gang_home(root))


def private_index(root):
    return PrivateKnowledgeIndex(root_path=root, private_home=gang_home(root))


class DriveIngestionTests(unittest.TestCase):
    def test_initial_sync_requires_explicit_bound(self):
        with TemporaryDirectory() as tempdir:
            service = drive_service(MockDriveProvider(), Path(tempdir))

            with self.assertRaisesRegex(DriveIngestionError, "First Drive sync must be bounded"):
                service.sync()

    def test_bounded_sync_creates_private_document_and_raw_evidence(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            file = drive_file()
            provider = MockDriveProvider(
                files=[file],
                payloads={file.file_id: b"# Certification Plan\n\nUL certification requirements phrase.\n"},
            )
            service = drive_service(provider, root)

            result = service.sync(since="30d", folder_id="folder-a")

            self.assertEqual(provider.discover_calls, [{"since": "30d", "folder_id": "folder-a"}])
            self.assertEqual(result.files_discovered, 1)
            self.assertEqual(result.supported, 1)
            self.assertEqual(result.created, 1)
            self.assertEqual(result.failed, 0)
            self.assertTrue(result.checkpoint_advanced)

            doc_path = result.results[0].document_path
            self.assertTrue(str(doc_path).endswith("/vault/documents/" + doc_path.name))
            fm = frontmatter(doc_path)
            self.assertEqual(fm["type"], "document")
            self.assertEqual(fm["visibility"], "private")
            self.assertEqual(fm["status"], "active")
            self.assertEqual(fm["people"], [])
            self.assertEqual(fm["companies"], [])
            self.assertEqual(fm["projects"], [])
            self.assertEqual(fm["tags"], [])
            self.assertEqual(fm["drive"]["drive_file_id"], file.file_id)
            self.assertEqual(fm["drive"]["mime_type"], GOOGLE_DOC_MIME)
            self.assertEqual(fm["provenance"]["drive_file_id"], file.file_id)
            self.assertTrue(fm["raw_ref"].startswith("local://drive-file/"))
            self.assertIn("UL certification requirements phrase.", doc_path.read_text(encoding="utf-8"))
            self.assertIn(b"UL certification", service.raw_store.read(fm["raw_ref"]))

            record = registry_record(root, result.results[0].source_id)
            self.assertEqual(record["adapter"], "DriveSyncService")
            self.assertEqual(record["drive_file_id"], file.file_id)
            self.assertEqual(record["raw_version"], 1)
            self.assertEqual(record["payload_hash"], hashlib.sha256(provider.payloads[file.file_id]).hexdigest())
            self.assertEqual(record["versions"][0]["raw_version"], 1)
            self.assertEqual(record["versions"][0]["payload_hash"], record["payload_hash"])
            self.assertEqual(service.raw_store.read(record["versions"][0]["raw_ref"]), provider.payloads[file.file_id])
            assert_raw_versions_match_physical(self, service, record)

    def test_unchanged_sync_does_not_append_raw_version_history(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            file = drive_file(file_id="same-file")
            provider = MockDriveProvider(files=[file], payloads={"same-file": b"# Same\n\nSame body.\n"})
            service = drive_service(provider, root)

            initial = service.sync(since="30d")
            provider.changes = {"token-1": ([file], "token-2")}
            second = service.sync()

            self.assertEqual(second.unchanged, 1)
            record = registry_record(root, initial.results[0].source_id)
            self.assertEqual(len(record["versions"]), 1)
            self.assertEqual(record["versions"][0]["raw_version"], 1)
            assert_raw_versions_match_physical(self, service, record)

    def test_same_drive_file_rename_and_folder_move_preserve_document_uuid(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            first = drive_file(file_id="stable-file", name="Original Name", parents=["folder-a"], version="1")
            provider = MockDriveProvider(files=[first], payloads={"stable-file": b"# Original Name\n\nSame content.\n"})
            service = drive_service(provider, root)

            initial = service.sync(folder_id="folder-a")
            doc_id = initial.results[0].document_id
            doc_path = initial.results[0].document_path

            renamed = drive_file(file_id="stable-file", name="Renamed File", parents=["folder-b"], version="1")
            provider.changes = {"token-1": ([renamed], "token-2")}
            incremental = service.sync()

            self.assertEqual(incremental.results[0].document_id, doc_id)
            self.assertEqual(incremental.results[0].document_path, doc_path)
            self.assertEqual(incremental.unchanged, 1)
            fm = frontmatter(doc_path)
            self.assertEqual(fm["id"], doc_id)
            self.assertEqual(fm["drive"]["original_name"], "Renamed File")
            self.assertEqual(fm["drive"]["parent_folder_ids"], ["folder-b"])
            record = registry_record(root, incremental.results[0].source_id)
            self.assertEqual(record["source_name"], "Renamed File")
            self.assertEqual(len(record["versions"]), 1)
            self.assertEqual(record["versions"][0]["raw_version"], 1)
            assert_raw_versions_match_physical(self, service, record)

    def test_folder_move_only_preserves_raw_version_and_updates_metadata(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            first = drive_file(file_id="moved-file", parents=["folder-a"], version="1")
            provider = MockDriveProvider(files=[first], payloads={"moved-file": b"# Move\n\nSame content.\n"})
            service = drive_service(provider, root)

            initial = service.sync(folder_id="folder-a")
            moved = drive_file(file_id="moved-file", parents=["folder-c"], version="2")
            provider.changes = {"token-1": ([moved], "token-2")}
            incremental = service.sync()

            self.assertEqual(incremental.results[0].document_id, initial.results[0].document_id)
            self.assertEqual(incremental.unchanged, 1)
            fm = frontmatter(initial.results[0].document_path)
            self.assertEqual(fm["drive"]["parent_folder_ids"], ["folder-c"])
            record = registry_record(root, incremental.results[0].source_id)
            self.assertEqual(record["raw_version"], 1)
            self.assertEqual(len(record["versions"]), 1)
            assert_raw_versions_match_physical(self, service, record)

    def test_content_modification_creates_new_source_version_same_document_uuid(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            first = drive_file(file_id="mutable-file", version="1")
            provider = MockDriveProvider(files=[first], payloads={"mutable-file": b"# Plan\n\nFirst version.\n"})
            service = drive_service(provider, root)

            initial = service.sync(since="30d")
            doc_id = initial.results[0].document_id
            modified = drive_file(file_id="mutable-file", modified_time="2026-01-03T00:00:00Z", version="2")
            provider.payloads["mutable-file"] = b"# Plan\n\nSecond version has gallium nitride details.\n"
            provider.changes = {"token-1": ([modified], "token-2")}
            second = service.sync()

            self.assertEqual(second.updated, 1)
            self.assertEqual(second.results[0].document_id, doc_id)
            self.assertIn("gallium nitride", second.results[0].document_path.read_text(encoding="utf-8"))
            first_raw_ref = registry_record(root, second.results[0].source_id)["versions"][0]["raw_ref"]
            first_bytes = service.raw_store.read(first_raw_ref)

            modified_again = drive_file(file_id="mutable-file", modified_time="2026-01-04T00:00:00Z", version="3")
            provider.payloads["mutable-file"] = b"# Plan\n\nThird version has thermal foldback details.\n"
            provider.changes = {"token-2": ([modified_again], "token-3")}
            third = service.sync()

            self.assertEqual(third.updated, 1)
            self.assertEqual(third.results[0].document_id, doc_id)
            record = registry_record(root, third.results[0].source_id)
            self.assertEqual(record["document_id"], doc_id)
            self.assertEqual([item["raw_version"] for item in record["versions"]], [1, 2, 3])
            self.assertEqual(service.raw_store.read(first_raw_ref), first_bytes)
            self.assertIn("thermal foldback", third.results[0].document_path.read_text(encoding="utf-8"))
            assert_raw_versions_match_physical(self, service, record)

    def test_pdf_markdown_text_and_unsupported_behavior(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            pdf = drive_file(file_id="pdf-1", name="Spec.pdf", mime_type=PDF_MIME)
            text = drive_file(file_id="text-1", name="Notes.txt", mime_type="text/plain")
            unsupported = drive_file(file_id="sheet-1", name="Budget", mime_type="application/vnd.google-apps.spreadsheet")
            provider = MockDriveProvider(
                files=[pdf, text, unsupported],
                payloads={
                    "pdf-1": text_pdf(["Flux capacitor certification requirements for the housing."]),
                    "text-1": b"Plain text design note.\n",
                },
            )
            service = drive_service(provider, root)

            result = service.sync(folder_id="folder-a")

            self.assertEqual(result.supported, 2)
            self.assertEqual(result.unsupported, 1)
            self.assertEqual(result.created, 2)
            self.assertEqual(len(list((gang_home(root) / "vault/documents").glob("*.md"))), 2)
            self.assertTrue((gang_home(root) / "raw/drive-file").exists())
            docs_text = "\n".join(path.read_text(encoding="utf-8") for path in (gang_home(root) / "vault/documents").glob("*.md"))
            self.assertIn("Flux capacitor certification", docs_text)
            self.assertIn("Plain text design note", docs_text)

            registry = json.loads((gang_home(root) / "ingestion/registry.json").read_text(encoding="utf-8"))
            unsupported_records = [record for record in registry["sources"].values() if record["drive_file_id"] == "sheet-1"]
            self.assertEqual(unsupported_records[0]["supported"], False)
            self.assertEqual(unsupported_records[0]["document_id"], "")

    def test_incremental_failure_does_not_advance_checkpoint_and_recovery_is_idempotent(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            stable = drive_file(file_id="stable")
            failing = drive_file(file_id="failing")
            provider = MockDriveProvider(
                files=[stable],
                payloads={"stable": b"# Stable\n\nStable body.\n", "failing": b"# Failing\n\nRecovered body.\n"},
            )
            service = drive_service(provider, root)
            service.sync(since="30d")

            provider.fail_files = {"failing"}
            provider.changes = {"token-1": ([stable, failing], "token-2")}
            failed = service.sync()
            self.assertEqual(failed.failed, 1)
            self.assertFalse(failed.checkpoint_advanced)
            self.assertEqual(json.loads((gang_home(root) / "ingestion/drive/checkpoint.json").read_text())["start_page_token"], "token-1")

            provider.fail_files = set()
            recovered = service.sync()
            self.assertEqual(recovered.unchanged, 1)
            self.assertEqual(recovered.created, 1)
            self.assertTrue(recovered.checkpoint_advanced)
            self.assertEqual(json.loads((gang_home(root) / "ingestion/drive/checkpoint.json").read_text())["start_page_token"], "token-2")

    def test_drive_document_enters_private_fts_and_public_build_excludes_it(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            public_doc = root / "brain/vault/public/pages/public.md"
            public_doc.parent.mkdir(parents=True, exist_ok=True)
            public_doc.write_text(
                "---\n"
                "id: 0199da90-c200-7056-ac0b-6f1d82bd2f41\n"
                "type: page\n"
                "title: Public\n"
                "created: '2025-01-01'\n"
                "visibility: public\n"
                "status: published\n"
                "url: /pages/public/\n"
                "---\n# Public\n",
                encoding="utf-8",
            )
            file = drive_file()
            provider = MockDriveProvider(
                files=[file],
                payloads={file.file_id: b"# Certification Plan\n\nDistinctive beryllium washer phrase.\n"},
            )
            sync = drive_service(provider, root).sync(since="30d")

            index = private_index(root)
            index.build()
            results = index.search("beryllium washer", visibility="private", type="document")
            self.assertEqual([item["document_id"] for item in results], [sync.results[0].document_id])
            self.assertEqual(results[0]["source_ids"], [sync.results[0].source_id])

            docs = load_public_content({"build": {"content": "content"}}, source="vault", root_path=root)
            self.assertEqual([doc.url for doc in docs], ["/pages/public/"])
            self.assertNotIn("beryllium washer", json.dumps([doc.body for doc in docs]))

    def test_unexpected_zero_byte_google_doc_export_fails_without_canonical_document(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            file = drive_file(file_id="empty-export", name="Known Non Empty")
            provider = MockDriveProvider(files=[file], payloads={"empty-export": b""})
            service = drive_service(provider, root)

            result = service.sync(since="30d")

            self.assertEqual(result.failed, 1)
            self.assertFalse(result.checkpoint_advanced)
            self.assertFalse((gang_home(root) / "vault/documents").exists())
            self.assertFalse((gang_home(root) / "ingestion/registry.json").exists())

    def test_oauth_scope_and_private_token_defaults_are_drive_specific(self):
        with TemporaryDirectory() as tempdir:
            provider = GoogleDriveProvider(private_home=tempdir)

            home = Path(tempdir).resolve()
            self.assertEqual(provider.scopes, [DRIVE_READONLY_SCOPE])
            self.assertEqual(provider.token_path, home / "ingestion/drive/token.json")
            self.assertEqual(provider.credentials_path, home / "ingestion/drive/oauth_client_secret.json")

    def test_google_drive_provider_retries_quota_and_retry_after(self):
        clock = FakeClock()
        provider = GoogleDriveProvider(
            retry_policy=DriveRetryPolicy(max_attempts=3, base_delay_seconds=2, jitter_seconds=0, min_request_interval_seconds=0),
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
            random_fn=lambda: 0,
        )
        request = SequencedRequest(
            [
                FakeGoogleError(429, "Too Many Requests", headers={"Retry-After": "7"}),
                {"ok": True},
            ]
        )

        self.assertEqual(provider._execute(request), {"ok": True})
        self.assertEqual(request.calls, 2)
        self.assertEqual(clock.sleeps, [7.0])
        self.assertEqual(provider.retry_count, 1)

    def test_cli_surfaces_drive_without_real_account(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path("gang.config.yml").write_text("build: {}\n", encoding="utf-8")
            home = Path("gang-home").resolve()
            env = {"GANG_HOME": str(home)}
            help_result = runner.invoke(gang_cli.cli, ["ingest", "drive", "--help"], env=env)
            status_result = runner.invoke(gang_cli.cli, ["ingest", "drive", "status"], env=env)

        self.assertEqual(help_result.exit_code, 0)
        self.assertIn("--since", help_result.output)
        self.assertIn("--folder", help_result.output)
        self.assertIn("auth", help_result.output)
        self.assertIn("status", help_result.output)
        self.assertEqual(status_result.exit_code, 0)
        self.assertIn("Last successful sync: never", status_result.output)


if __name__ == "__main__":
    unittest.main()
