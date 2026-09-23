import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import yaml
from click.testing import CliRunner

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli" / "gang"))

import cli as gang_cli
from core.content_loader import load_public_content
from core.ingestion.gmail import (
    GMAIL_READONLY_SCOPE,
    GmailAttachment,
    GmailIngestionError,
    GmailMessage,
    GmailRetryPolicy,
    GmailSyncService,
    GmailThread,
    GoogleGmailProvider,
)
from core.private_index import PrivateKnowledgeIndex


def raw_email(message_id, subject, sender, to, body):
    return (
        f"Message-ID: <{message_id}@example.test>\n"
        f"Subject: {subject}\n"
        f"From: {sender}\n"
        f"To: {to}\n"
        "Content-Type: text/plain; charset=utf-8\n"
        "\n"
        f"{body}\n"
    ).encode("utf-8")


def message(
    message_id,
    thread_id="thread-1",
    internal_date_ms=1_700_000_000_000,
    subject="PSU certification discussion",
    sender="Alice <alice@example.test>",
    to="Bob <bob@example.test>",
    body="Power supply certification phrase.",
    html_body="",
    attachments=None,
):
    return GmailMessage(
        message_id=message_id,
        thread_id=thread_id,
        internal_date_ms=internal_date_ms,
        history_id=f"h-{message_id}",
        headers={
            "Subject": subject,
            "From": sender,
            "To": to,
            "Date": "Tue, 14 Nov 2023 22:13:20 +0000",
            "Message-ID": f"<{message_id}@example.test>",
        },
        snippet=body[:80],
        raw_payload=raw_email(message_id, subject, sender, to, body),
        text_body=body,
        html_body=html_body,
        attachments=attachments or [],
    )


class MockGmailProvider:
    def __init__(self, threads, attachments=None, fail_threads=None, fail_attachments=None):
        self.threads = threads
        self.attachments = attachments or {}
        self.fail_threads = set(fail_threads or [])
        self.fail_attachments = set(fail_attachments or [])
        self.queries = []

    def discover_thread_ids(self, query):
        self.queries.append(query)
        return list(self.threads)

    def fetch_thread(self, thread_id):
        if thread_id in self.fail_threads:
            raise RuntimeError("network failure without private body")
        return self.threads[thread_id]

    def fetch_attachment(self, message_id, attachment_id):
        if attachment_id in self.fail_attachments:
            raise RuntimeError("attachment unavailable")
        return self.attachments[(message_id, attachment_id)]


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


class RecoveringGmailProvider(MockGmailProvider):
    def __init__(self, threads):
        super().__init__(threads)
        self.fail_once = set(threads)
        self.fetch_counts = {}

    def fetch_thread(self, thread_id):
        self.fetch_counts[thread_id] = self.fetch_counts.get(thread_id, 0) + 1
        if thread_id in self.fail_once:
            self.fail_once.remove(thread_id)
            raise RuntimeError("temporary Gmail quota failure")
        return self.threads[thread_id]


def frontmatter(path):
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])


def gang_home(root):
    return root / "gang-home"


def gmail_service(provider, root):
    return GmailSyncService(provider, root_path=root, private_home=gang_home(root))


def private_index(root):
    return PrivateKnowledgeIndex(root_path=root, private_home=gang_home(root))


class GmailIngestionTests(unittest.TestCase):
    def test_initial_sync_requires_explicit_bound(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            service = gmail_service(MockGmailProvider({}), root)

            with self.assertRaisesRegex(GmailIngestionError, "First Gmail sync must be bounded"):
                service.sync()

    def test_bounded_sync_creates_private_thread_document_and_raw_evidence(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            attachment = GmailAttachment(
                attachment_id="att-1",
                filename="certification.pdf",
                mime_type="application/pdf",
                message_id="msg-1",
                size=12,
            )
            provider = MockGmailProvider(
                {"thread-1": GmailThread("thread-1", [message("msg-1", attachments=[attachment])])},
                attachments={("msg-1", "att-1"): b"%PDF fixture"},
            )
            service = gmail_service(provider, root)

            result = service.sync(since="30d")

            self.assertEqual(provider.queries, ["newer_than:30d"])
            self.assertEqual(result.threads_discovered, 1)
            self.assertEqual(result.messages_discovered, 1)
            self.assertEqual(result.created, 1)
            self.assertEqual(result.failed, 0)
            self.assertTrue(result.checkpoint_advanced)

            doc_path = result.results[0].document_path
            fm = frontmatter(doc_path)
            self.assertEqual(fm["type"], "email-thread")
            self.assertEqual(fm["visibility"], "private")
            self.assertEqual(fm["status"], "active")
            self.assertEqual(fm["gmail"]["gmail_thread_id"], "thread-1")
            self.assertEqual(fm["gmail"]["message_count"], 1)
            self.assertEqual(fm["people"], [])
            self.assertEqual(fm["companies"], [])
            self.assertEqual(fm["projects"], [])
            self.assertEqual(fm["tags"], [])
            self.assertIn("Power supply certification phrase.", doc_path.read_text(encoding="utf-8"))

            provenance = fm["provenance"]["messages"][0]
            self.assertEqual(provenance["gmail_message_id"], "msg-1")
            self.assertTrue(provenance["raw_ref"].startswith("local://gmail-message/"))
            attachment_record = fm["ingestion_envelope"]["messages"][0]["attachments"][0]
            self.assertEqual(attachment_record["filename"], "certification.pdf")
            self.assertEqual(attachment_record["mime_type"], "application/pdf")
            self.assertEqual(attachment_record["parent_gmail_message_id"], "msg-1")
            self.assertTrue(attachment_record["raw_ref"].startswith("local://gmail-attachment/"))

            registry = json.loads((gang_home(root) / "ingestion/registry.json").read_text(encoding="utf-8"))
            records = [record for record in registry["sources"].values() if record["source_type"] == "gmail-thread"]
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["adapter"], "GmailSyncService")
            self.assertEqual(records[0]["gmail_thread_id"], "thread-1")

    def test_same_sync_twice_is_idempotent_and_new_message_updates_same_document(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            first_message = message("msg-1", body="First thread content.")
            provider = MockGmailProvider({"thread-1": GmailThread("thread-1", [first_message])})
            service = gmail_service(provider, root)

            first = service.sync(since="30d")
            second = service.sync()
            doc_id = first.results[0].document_id
            doc_path = first.results[0].document_path

            self.assertEqual(second.unchanged, 1)
            self.assertEqual(second.created, 0)
            self.assertEqual(second.results[0].document_id, doc_id)
            self.assertEqual(second.results[0].document_path, doc_path)

            second_message = message(
                "msg-2",
                internal_date_ms=1_700_000_010_000,
                sender="Bob <bob@example.test>",
                to="Alice <alice@example.test>",
                body="Second message adds the certification closure.",
            )
            provider.threads["thread-1"] = GmailThread("thread-1", [first_message, second_message])
            third = service.sync()

            self.assertEqual(third.updated, 1)
            self.assertEqual(third.results[0].document_id, doc_id)
            fm = frontmatter(doc_path)
            self.assertEqual(fm["gmail"]["message_count"], 2)
            self.assertEqual(fm["gmail"]["message_ids"], ["msg-1", "msg-2"])
            self.assertIn("Second message adds the certification closure.", doc_path.read_text(encoding="utf-8"))

            registry = json.loads((gang_home(root) / "ingestion/registry.json").read_text(encoding="utf-8"))
            record = registry["sources"][third.results[0].source_id]
            self.assertEqual(record["document_id"], doc_id)
            self.assertEqual([item["version"] for item in record["versions"]], [1, 2])
            self.assertTrue((gang_home(root) / "raw/gmail-message").exists())

    def test_html_is_sanitized_to_text_without_executable_markup_or_remote_resources(self):
        with TemporaryDirectory() as tempdir:
            html_message = message(
                "msg-html",
                body="",
                html_body=(
                    "<p>Visible HTML body</p>"
                    "<script>alert('x')</script>"
                    "<img src='https://tracker.example/pixel.png'>"
                    "<iframe src='https://evil.example'></iframe>"
                ),
            )
            service = gmail_service(
                MockGmailProvider({"thread-1": GmailThread("thread-1", [html_message])}),
                Path(tempdir),
            )

            result = service.sync(since="30d")

            text = result.results[0].document_path.read_text(encoding="utf-8")
            self.assertIn("Visible HTML body", text)
            self.assertNotIn("<script", text)
            self.assertNotIn("tracker.example", text)
            self.assertNotIn("<iframe", text)

    def test_failure_does_not_advance_checkpoint(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            provider = MockGmailProvider(
                {"thread-1": GmailThread("thread-1", [message("msg-1")])},
                fail_threads={"thread-1"},
            )
            service = gmail_service(provider, root)

            result = service.sync(since="30d")

            self.assertEqual(result.failed, 1)
            self.assertFalse(result.checkpoint_advanced)
            self.assertFalse((gang_home(root) / "ingestion/gmail/checkpoint.json").exists())

    def test_attachment_failure_does_not_advance_checkpoint_or_write_thread_doc(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            attachment = GmailAttachment("att-1", "bad.bin", "application/octet-stream", "msg-1")
            provider = MockGmailProvider(
                {"thread-1": GmailThread("thread-1", [message("msg-1", attachments=[attachment])])},
                fail_attachments={"att-1"},
            )
            service = gmail_service(provider, root)

            result = service.sync(since="30d")

            self.assertEqual(result.failed, 1)
            self.assertFalse(result.checkpoint_advanced)
            self.assertFalse((gang_home(root) / "vault/emails").exists())

    def test_gmail_thread_enters_private_fts_and_provenance_resolves_to_raw(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            service = gmail_service(
                MockGmailProvider(
                    {"thread-1": GmailThread("thread-1", [message("msg-1", body="Distinctive fluxgate phrase.")])}
                ),
                root,
            )
            sync = service.sync(since="30d")

            index = private_index(root)
            index.build()
            results = index.search("distinctive fluxgate", visibility="private", type="email-thread")

            self.assertEqual([item["document_id"] for item in results], [sync.results[0].document_id])
            self.assertEqual(results[0]["visibility"], "private")
            fm = frontmatter(sync.results[0].document_path)
            raw_ref = fm["provenance"]["messages"][0]["raw_ref"]
            raw_bytes = service.raw_store.read(raw_ref)
            self.assertIn(b"Distinctive fluxgate phrase.", raw_bytes)

    def test_gmail_content_never_enters_public_collection(self):
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
            service = gmail_service(
                MockGmailProvider(
                    {"thread-1": GmailThread("thread-1", [message("msg-1", body="Secret Gmail phrase.")])}
                ),
                root,
            )
            service.sync(since="30d")

            docs = load_public_content({"build": {"content": "content"}}, source="vault", root_path=root)

            self.assertEqual([doc.url for doc in docs], ["/pages/public/"])
            self.assertNotIn("Secret Gmail phrase", json.dumps([doc.body for doc in docs]))

    def test_oauth_scope_and_private_token_defaults_do_not_expose_secrets(self):
        with TemporaryDirectory() as tempdir, patch.dict("os.environ", {"GANG_HOME": tempdir}):
            provider = GoogleGmailProvider()

            self.assertEqual(provider.scopes, [GMAIL_READONLY_SCOPE])
            home = Path(tempdir).resolve()
            self.assertEqual(provider.token_path, home / "ingestion/gmail/token.json")
            self.assertEqual(provider.credentials_path, home / "ingestion/gmail/oauth_client_secret.json")

    def test_existing_cli_surfaces_gmail_without_real_account(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            Path("gang.config.yml").write_text("build: {}\n", encoding="utf-8")
            home = Path("gang-home").resolve()
            env = {"GANG_HOME": str(home)}
            help_result = runner.invoke(gang_cli.cli, ["ingest", "gmail", "--help"], env=env)
            status_result = runner.invoke(gang_cli.cli, ["ingest", "gmail", "status"], env=env)

        self.assertEqual(help_result.exit_code, 0)
        self.assertIn("--since", help_result.output)
        self.assertIn("auth", help_result.output)
        self.assertIn("status", help_result.output)
        self.assertEqual(status_result.exit_code, 0)
        self.assertIn("Last successful sync: never", status_result.output)

    def test_google_provider_retries_403_quota_then_succeeds(self):
        clock = FakeClock()
        provider = GoogleGmailProvider(
            retry_policy=GmailRetryPolicy(max_attempts=3, base_delay_seconds=2, jitter_seconds=0, min_request_interval_seconds=0),
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
            random_fn=lambda: 0,
        )
        request = SequencedRequest(
            [
                FakeGoogleError(403, "Quota exceeded for quota metric 'Total Query Cost'"),
                {"ok": True},
            ]
        )

        self.assertEqual(provider._execute(request), {"ok": True})
        self.assertEqual(request.calls, 2)
        self.assertEqual(clock.sleeps, [2])
        self.assertEqual(provider.retry_count, 1)

    def test_google_provider_retries_429_and_honors_retry_after(self):
        clock = FakeClock()
        provider = GoogleGmailProvider(
            retry_policy=GmailRetryPolicy(max_attempts=3, base_delay_seconds=2, jitter_seconds=0, min_request_interval_seconds=0),
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
            random_fn=lambda: 0,
        )
        request = SequencedRequest([FakeGoogleError(429, "Too Many Requests", headers={"Retry-After": "7"}), {"ok": True}])

        self.assertEqual(provider._execute(request), {"ok": True})
        self.assertEqual(clock.sleeps, [7.0])
        self.assertEqual(request.calls, 2)

    def test_google_provider_retries_temporary_5xx_then_succeeds(self):
        clock = FakeClock()
        provider = GoogleGmailProvider(
            retry_policy=GmailRetryPolicy(max_attempts=3, base_delay_seconds=1, jitter_seconds=0, min_request_interval_seconds=0),
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
            random_fn=lambda: 0,
        )
        request = SequencedRequest([FakeGoogleError(503, "Backend Error"), {"ok": True}])

        self.assertEqual(provider._execute(request), {"ok": True})
        self.assertEqual(clock.sleeps, [1])

    def test_google_provider_retry_exhaustion_raises_after_bounded_attempts(self):
        clock = FakeClock()
        provider = GoogleGmailProvider(
            retry_policy=GmailRetryPolicy(max_attempts=3, base_delay_seconds=1, jitter_seconds=0, min_request_interval_seconds=0),
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
            random_fn=lambda: 0,
        )
        request = SequencedRequest(
            [
                FakeGoogleError(429, "Too Many Requests"),
                FakeGoogleError(429, "Too Many Requests"),
                FakeGoogleError(429, "Too Many Requests"),
            ]
        )

        with self.assertRaises(FakeGoogleError):
            provider._execute(request)

        self.assertEqual(request.calls, 3)
        self.assertEqual(clock.sleeps, [1, 2])

    def test_retry_exhaustion_surfaces_as_failed_thread_without_checkpoint(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            provider = MockGmailProvider({"thread-1": GmailThread("thread-1", [message("msg-1")])})
            provider.fetch_thread = lambda thread_id: (_ for _ in ()).throw(FakeGoogleError(429, "Too Many Requests"))
            service = gmail_service(provider, root)

            result = service.sync(since="30d")

            self.assertEqual(result.failed, 1)
            self.assertEqual(result.results[0].status, "failed")
            self.assertFalse(result.checkpoint_advanced)
            self.assertFalse((gang_home(root) / "ingestion/gmail/checkpoint.json").exists())

    def test_google_provider_does_not_retry_permanent_4xx(self):
        clock = FakeClock()
        provider = GoogleGmailProvider(
            retry_policy=GmailRetryPolicy(max_attempts=5, base_delay_seconds=1, jitter_seconds=0, min_request_interval_seconds=0),
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
            random_fn=lambda: 0,
        )
        request = SequencedRequest([FakeGoogleError(403, "Permission denied")])

        with self.assertRaises(FakeGoogleError):
            provider._execute(request)

        self.assertEqual(request.calls, 1)
        self.assertEqual(clock.sleeps, [])

    def test_google_provider_paces_requests_without_real_sleep(self):
        clock = FakeClock()
        provider = GoogleGmailProvider(
            retry_policy=GmailRetryPolicy(max_attempts=1, min_request_interval_seconds=0.5),
            sleep_fn=clock.sleep,
            monotonic_fn=clock.monotonic,
            random_fn=lambda: 0,
        )

        self.assertEqual(provider._execute(SequencedRequest([{"first": True}])), {"first": True})
        self.assertEqual(provider._execute(SequencedRequest([{"second": True}])), {"second": True})

        self.assertEqual(clock.sleeps, [0.5])
        self.assertEqual(provider.rate_limit_sleep_count, 1)

    def test_prior_successful_threads_are_idempotent_after_failed_run_recovers(self):
        with TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            stable = message("msg-stable", thread_id="thread-stable", body="Stable thread body.")
            recovering = message("msg-recover", thread_id="thread-recover", body="Recovered thread body.")
            provider = RecoveringGmailProvider(
                {
                    "thread-stable": GmailThread("thread-stable", [stable]),
                    "thread-recover": GmailThread("thread-recover", [recovering]),
                }
            )
            provider.fail_once.remove("thread-stable")
            service = gmail_service(provider, root)

            first = service.sync(since="30d")
            second = service.sync(since="30d")

            self.assertEqual(first.created, 1)
            self.assertEqual(first.failed, 1)
            self.assertFalse(first.checkpoint_advanced)
            self.assertEqual(second.unchanged, 1)
            self.assertEqual(second.created, 1)
            self.assertEqual(second.failed, 0)
            self.assertTrue(second.checkpoint_advanced)

            docs = sorted((gang_home(root) / "vault/emails").glob("*.md"))
            self.assertEqual(len(docs), 2)
            registry = json.loads((gang_home(root) / "ingestion/registry.json").read_text(encoding="utf-8"))
            document_ids = [record["document_id"] for record in registry["sources"].values()]
            self.assertEqual(len(document_ids), len(set(document_ids)))
            self.assertEqual(len(list((gang_home(root) / "raw/gmail-thread").rglob("metadata.json"))), 2)


if __name__ == "__main__":
    unittest.main()
