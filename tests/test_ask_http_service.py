import json
import os
import stat
import sys
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import yaml
from click.testing import CliRunner

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

import cli as gang_cli
from core.access import PrincipalDirectory, PrincipalError
from core.ai_provider import ProviderTimeoutError
from core.ask import ConversationOptions, ConversationService, validate_plan
from core.ask.http_service import (
    DEFAULT_QUEUE_DEPTH,
    AuditedRetriever,
    AskHTTPServer,
    HTTPConfigError,
    create_app,
    sha256_token,
    validate_bind_host,
    validate_local_ollama_endpoint,
)
from core.ask.retrieval import Retriever
from core.ask.session import Session, SessionStore
from core.private_index import PrivateKnowledgeIndex


DOC_ID = "01a0bcc1-7f14-7b41-a4e3-f4dbd6a37e01"


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class HTTPStubSynthesizer:
    provider_name = "stub"
    model = "stub-model"
    has_credentials = True

    def __init__(self, payload):
        self.payload = payload
        self.contexts = []

    def synthesize(self, context):
        self.contexts.append(context)
        return self.payload(context) if callable(self.payload) else self.payload


class StopDirector:
    provider_name = "stub"
    model = "stub-model"
    has_credentials = True

    def decide(self, context):
        return {"decision": "ENOUGH_EVIDENCE", "reason": "enough"}


def write_markdown(path, frontmatter, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n" + body,
        encoding="utf-8",
    )


def tree_fingerprint(root):
    root = Path(root)
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): sha256_file(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def sha256_file(path):
    import hashlib

    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


class AskHTTPServiceTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        patcher = mock.patch.dict(
            os.environ,
            {
                "ANTHROPIC_API_KEY": "sk-should-not-matter",
                "GANG_OLLAMA_ENDPOINT": "",
                "GANG_HTTP_TOKEN_SHA256": "",
            },
            clear=False,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

        self._temp = TemporaryDirectory()
        self.addCleanup(self._temp.cleanup)
        self.root = Path(self._temp.name) / "repo"
        self.home = Path(self._temp.name) / "gang-home"
        self.token = "stage1-test-token"
        for name in ("raw", "blobs", "entities", "ingestion"):
            (self.home / name).mkdir(parents=True)
        self.write_corpus()
        PrivateKnowledgeIndex(root_path=self.root, private_home=self.home).build()

    def write_corpus(self):
        write_markdown(
            self.home / "vault/documents/qi2.md",
            {
                "id": DOC_ID,
                "type": "knowledge",
                "source_type": "drive-file",
                "title": "Qi2 Certification",
                "visibility": "private",
                "status": "active",
                "source_id": "drive-file_qi2",
                "created": "2026-09-10",
                "updated": "2026-09-10",
            },
            "Qi2 certification is active. Frank owns the certification work. "
            "The target ship date is October 1.\n",
        )

    def app(self, **kwargs):
        return create_app(
            root_path=self.root,
            private_home=self.home,
            auth_token=self.token,
            **kwargs,
        )

    def auth(self, token=None):
        return {"Authorization": f"Bearer {token or self.token}"}

    def create_stage2_principals(self):
        directory = PrincipalDirectory(self.home / "access/principals.yml")
        directory.add_principal("daniel", "Daniel")
        directory.add_principal("frank", "Frank")
        daniel_token = directory.issue_token("daniel", "iphone")
        frank_token = directory.issue_token("frank", "iphone")
        return directory, daniel_token, frank_token

    def post_ask(self, client, payload):
        return client.post("/v1/ask", json=payload, headers=self.auth())

    def await_job(self, client, job_id, *, block=5):
        return client.get(f"/v1/jobs/{job_id}?block={block}", headers=self.auth())

    def test_request_contract_rejects_each_sensitive_control_field(self):
        client = self.app().test_client()
        sensitive = [
            "mode",
            "provider",
            "model",
            "premium",
            "local_only",
            "endpoint",
            "GANG_HOME",
            "root",
            "path",
            "filesystem",
            "cache",
            "cache_settings",
            "research",
            "research_controls",
        ]

        for field in sensitive:
            with self.subTest(field=field):
                response = self.post_ask(
                    client,
                    {"question": "What is Qi2?", "level": "fast", field: "x"},
                )
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json["error"]["code"], "control_field_rejected")

    def test_request_contract_accepts_valid_filters_and_rejects_bad_filters(self):
        client = self.app().test_client()

        ok = self.post_ask(
            client,
            {
                "question": "Summarize certification",
                "level": "fast",
                "filters": {
                    "source_types": ["drive-file"],
                    "visibility": "private",
                    "date_range": {"field": "updated", "start": "2026-09-01", "end": "2026-09-30"},
                    "limit": 2,
                },
            },
        )
        self.assertEqual(ok.status_code, 202)
        self.assertEqual(self.await_job(client, ok.json["job_id"]).json["status"], "succeeded")

        unknown = self.post_ask(
            client,
            {"question": "What is Qi2?", "level": "fast", "filters": {"sql": "select *"}},
        )
        self.assertEqual(unknown.status_code, 400)
        self.assertEqual(unknown.json["error"]["code"], "unsupported_filter")

        malformed = self.post_ask(
            client,
            {"question": "What is Qi2?", "level": "fast", "filters": {"limit": "nope"}},
        )
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(malformed.json["error"]["code"], "invalid_filters")

    def test_fast_and_normal_tiers_pass_exact_server_options_and_disable_cache(self):
        app = self.app()
        server = app.config["GANG_SERVER"]
        captured = []

        def fake_converse(question, *, session=None, overrides=None, options=None):
            captured.append(options)
            session.record_turn(
                question=question,
                resolved_question=question,
                policy="lookup",
                mode="evidence",
                answer="ok",
                evidence=[],
                claims=[],
            )
            return {
                "session_id": session.session_id,
                "turn": session.turn_count,
                "intent": {"mode": "evidence", "policy": "lookup"},
                "answer": "ok",
                "claims": [],
                "claim_ledger": {"version": "1", "claims": []},
                "claim_ledger_origin": "model",
                "conflicts": [],
                "uncertainties": [],
                "uncertainty": "",
                "insufficient_evidence": False,
                "sources": [],
                "synthesis": {"cached": False},
                "research": {"provider_calls": []},
            }

        server.service.converse = fake_converse
        client = app.test_client()

        fast = self.post_ask(client, {"question": "fast", "level": "fast"}).json
        normal = self.post_ask(client, {"question": "normal", "level": "normal"}).json
        self.await_job(client, fast["job_id"])
        self.await_job(client, normal["job_id"])

        fast_options, normal_options = captured
        self.assertEqual(
            (
                fast_options.use_ai,
                fast_options.use_cache,
                fast_options.premium,
                fast_options.local_only,
                fast_options.mode_override,
            ),
            (False, False, False, True, None),
        )
        self.assertEqual(
            (
                normal_options.use_ai,
                normal_options.use_cache,
                normal_options.provider,
                normal_options.model,
                normal_options.premium,
                normal_options.local_only,
                normal_options.mode_override,
            ),
            (True, False, "ollama", "qwen3:8b", False, True, None),
        )

    def test_remote_inference_is_impossible_with_env_key_and_timeout_does_not_fallback(self):
        seen_payloads = []

        def fake_urlopen(request, timeout):
            payload = json.loads(request.data.decode("utf-8"))
            seen_payloads.append(payload)
            raise TimeoutError("raw timeout detail /tmp/secret")

        with mock.patch("core.ai_provider.AnthropicClient", side_effect=AssertionError) as anthropic, mock.patch(
            "urllib.request.urlopen", side_effect=fake_urlopen
        ):
            client = self.app().test_client()
            created = self.post_ask(
                client,
                {"question": "What should we do about certification?", "level": "normal"},
            )
            self.assertEqual(created.status_code, 202)
            job = self.await_job(client, created.json["job_id"])

        self.assertEqual(job.status_code, 504)
        self.assertEqual(job.json["error"]["code"], "provider_timeout")
        self.assertEqual(anthropic.call_count, 0)
        self.assertTrue(seen_payloads)
        self.assertTrue(all(payload["model"] == "qwen3:8b" for payload in seen_payloads))
        self.assertNotIn("raw timeout detail", json.dumps(job.json))

    def test_cli_premium_selection_is_unchanged(self):
        options = gang_cli._with_premium(ConversationOptions(use_cache=True))

        self.assertTrue(options.premium)
        self.assertEqual(options.provider, "anthropic")
        self.assertTrue(options.use_cache)

    def test_ollama_endpoint_env_cannot_point_at_lan_or_public_host(self):
        with mock.patch.dict(os.environ, {"GANG_OLLAMA_ENDPOINT": "http://192.168.1.10:11434"}):
            with self.assertRaises(HTTPConfigError):
                self.app()
        with mock.patch.dict(os.environ, {"GANG_OLLAMA_ENDPOINT": "http://8.8.8.8:11434"}):
            with self.assertRaises(HTTPConfigError):
                self.app()

    def test_auth_is_required_for_every_v1_route_and_only_healthz_is_public(self):
        client = self.app().test_client()
        created = self.post_ask(client, {"question": "Summarize certification", "level": "fast", "session_id": "demo"}).json
        self.await_job(client, created["job_id"])
        routes = [
            ("get", "/v1/health"),
            ("get", "/v1/whoami"),
            ("post", "/v1/ask"),
            ("get", f"/v1/jobs/{created['job_id']}"),
            ("get", "/v1/sessions"),
            ("get", "/v1/sessions/demo"),
            ("delete", "/v1/sessions/demo"),
        ]

        self.assertEqual(client.get("/healthz").status_code, 200)
        for method, path in routes:
            with self.subTest(path=path):
                response = getattr(client, method)(path, json={"question": "x"} if method == "post" else None)
                self.assertEqual(response.status_code, 401)

        for method, path in routes:
            with self.subTest(authenticated=path):
                response = getattr(client, method)(
                    path,
                    headers=self.auth(),
                    json={"question": "x", "level": "fast"} if method == "post" else None,
                )
                self.assertNotEqual(response.status_code, 401)

    def test_required_routes_exist(self):
        client = self.app().test_client()

        created = self.post_ask(client, {"question": "Summarize certification", "level": "fast", "session_id": "demo"})
        self.assertEqual(created.status_code, 202)
        self.assertEqual(self.await_job(client, created.json["job_id"]).status_code, 200)
        self.assertEqual(client.get("/v1/sessions", headers=self.auth()).status_code, 200)
        self.assertEqual(client.get("/v1/sessions/demo", headers=self.auth()).status_code, 200)
        self.assertEqual(client.get("/v1/whoami", headers=self.auth()).status_code, 200)
        self.assertEqual(client.get("/v1/health", headers=self.auth()).status_code, 200)
        self.assertEqual(client.get("/healthz").status_code, 200)
        self.assertEqual(client.delete("/v1/sessions/demo", headers=self.auth()).status_code, 200)

    def test_bind_and_ollama_endpoint_restrictions_are_hard_failures(self):
        validate_bind_host("127.0.0.1")
        validate_bind_host("localhost")
        validate_bind_host("100.64.1.2", approved_tailnet_cidrs=["100.64.0.0/10"])
        validate_local_ollama_endpoint("http://localhost:11434")

        for host in ("0.0.0.0", "192.168.1.10", "8.8.8.8"):
            with self.subTest(host=host):
                with self.assertRaises(HTTPConfigError):
                    validate_bind_host(host)
        with self.assertRaises(HTTPConfigError):
            validate_local_ollama_endpoint("http://192.168.1.10:11434")

    def test_http_request_does_not_mutate_corpus_or_write_cache(self):
        watched = ("vault", "raw", "blobs", "entities", "ingestion")
        before = {name: tree_fingerprint(self.home / name) for name in watched}
        client = self.app().test_client()

        created = self.post_ask(client, {"question": "Summarize certification", "level": "fast"})
        self.await_job(client, created.json["job_id"])

        for name in watched:
            self.assertEqual(tree_fingerprint(self.home / name), before[name], name)
        self.assertFalse((self.home / "generated/ask-cache").exists())

    def test_sanitized_errors_do_not_leak_paths_tokens_env_prompts_or_provider_details(self):
        app = self.app()
        server = app.config["GANG_SERVER"]
        secret_env = "ENV-SHOULD-NOT-LEAK"
        token = self.token

        def fail(*args, **kwargs):
            raise RuntimeError(
                f"traceback /tmp/private {secret_env} {token} system prompt gang.config.yml raw provider"
            )

        server.service.converse = fail
        with mock.patch.dict(os.environ, {"LEAK_ME": secret_env}):
            client = app.test_client()
            created = self.post_ask(client, {"question": "Summarize certification", "level": "fast"})
            job = self.await_job(client, created.json["job_id"]).json

        text = json.dumps(job)
        self.assertEqual(job["status"], "failed")
        self.assertIn("request_id", job["error"])
        for forbidden in (
            "traceback",
            "/tmp/private",
            secret_env,
            token,
            "system prompt",
            "gang.config.yml",
            "raw provider",
        ):
            self.assertNotIn(forbidden, text)

    def test_session_id_validation_is_reused(self):
        client = self.app().test_client()

        created = self.post_ask(
            client,
            {"question": "What is Qi2?", "level": "fast", "session_id": "../bad"},
        ).json
        job = self.await_job(client, created["job_id"]).json

        self.assertEqual(job["status"], "failed")
        self.assertEqual(job["error"]["code"], "ask_failed")
        self.assertNotIn(str(self.home), json.dumps(job))

    def test_epistemic_projection_preserves_ledger_and_mode_boundaries(self):
        payload = {
            "answer": "The target ship date is October 1 [1]. I would make certification the first gate.",
            "claims": [
                {
                    "id": "c1",
                    "type": "fact",
                    "text": "The target ship date is October 1.",
                    "citations": [1],
                },
                {
                    "id": "c2",
                    "type": "synthesis",
                    "text": "Certification schedule risk is visible.",
                    "derived_from": ["c1"],
                },
                {
                    "id": "c3",
                    "type": "recommendation",
                    "text": "I would make certification the first launch-readiness gate.",
                    "based_on": ["c1"],
                },
                {
                    "id": "c4",
                    "type": "fact",
                    "text": "Unsupported model fact.",
                    "citations": [],
                },
            ],
            "conflicts": [{"summary": "No conflict in fixture.", "citations": [1]}],
            "uncertainty": "Fixture uncertainty.",
            "insufficient_evidence": False,
        }
        service = ConversationService(
            root_path=self.root,
            private_home=self.home,
            synthesizer=HTTPStubSynthesizer(payload),
            director=StopDirector(),
        )
        app = self.app(server=AskHTTPServer(service=service))
        client = app.test_client()

        factual = self.post_ask(client, {"question": "What is the target ship date?", "level": "fast"})
        factual_result = self.await_job(client, factual.json["job_id"]).json["result"]
        self.assertEqual(factual_result["intent"]["mode"], "evidence")

        advisory = self.post_ask(
            client,
            {"question": "What should we do about certification?", "level": "normal"},
        )
        result = self.await_job(client, advisory.json["job_id"]).json["result"]

        self.assertEqual(result["intent"]["mode"], "advisory")
        self.assertIn("not a decision GANG has made", result["answer"])
        self.assertEqual(result["claim_ledger_origin"], "model")
        self.assertIn("Fixture uncertainty.", result["uncertainty"])
        self.assertEqual(result["conflicts"][0]["citations"], [1])
        self.assertFalse(result["insufficient_evidence"])
        self.assertTrue(result["sources"][0]["cited"])
        by_id = {claim["id"]: claim for claim in result["claims"]}
        self.assertEqual(by_id["c1"]["type"], "fact")
        self.assertEqual(by_id["c1"]["citations"], [1])
        self.assertEqual(by_id["c1"]["status"], "accepted")
        self.assertEqual(by_id["c2"]["derived_from"], ["c1"])
        self.assertEqual(by_id["c4"]["type"], "uncertainty")

        rejected = self.post_ask(
            client,
            {"question": "What is Qi2?", "level": "fast", "mode": "ideation"},
        )
        self.assertEqual(rejected.status_code, 400)

    def test_audit_records_auth_retrieval_success_timeout_permissions_and_no_prose(self):
        client = self.app().test_client()
        client.get("/v1/whoami", headers={"Authorization": f"Bearer {self.token}-wrong"})
        created = self.post_ask(
            client,
            {"question": "Summarize certification status", "level": "fast", "session_id": "demo"},
        ).json
        self.await_job(client, created["job_id"])

        http_audit = self.home / "audit/http.jsonl"
        retrieval_audit = self.home / "audit/retrieval.jsonl"
        http_records = read_jsonl(http_audit)
        retrieval_records = read_jsonl(retrieval_audit)
        self.assertEqual(stat.S_IMODE(http_audit.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(retrieval_audit.stat().st_mode), 0o600)
        self.assertTrue(any(record["kind"] == "auth" for record in http_records))
        self.assertTrue(any(record["kind"] == "turn" and record["outcome"] == "ok" for record in http_records))
        self.assertTrue(any(record["kind"] == "retrieval" for record in retrieval_records))
        serialized = "\n".join(json.dumps(record, sort_keys=True) for record in http_records + retrieval_records)
        self.assertNotIn(self.token, serialized)
        self.assertNotIn("Qi2 certification is active", serialized)
        self.assertNotIn("ok", [record.get("answer") for record in http_records])

    def test_audit_records_provider_timeout_turn(self):
        app = self.app()
        app.config["GANG_SERVER"].service.converse = lambda *a, **k: (_ for _ in ()).throw(
            ProviderTimeoutError("timed out with private details")
        )
        client = app.test_client()

        created = self.post_ask(client, {"question": "Summarize certification", "level": "normal"})
        self.await_job(client, created.json["job_id"])

        records = read_jsonl(self.home / "audit/http.jsonl")
        self.assertTrue(
            any(
                record["kind"] == "turn"
                and record["outcome"] == "provider-timeout"
                and record["error_code"] == "provider_timeout"
                for record in records
            )
        )

    def test_audited_retriever_covers_every_public_read_method(self):
        public = {
            name
            for name, value in Retriever.__dict__.items()
            if callable(value) and not name.startswith("_") and name != "connect"
        }
        self.assertTrue(public <= set(AuditedRetriever.__dict__))

        retriever = AuditedRetriever(
            self.home / "generated/brain.sqlite",
            audit_path=self.home / "audit/retrieval.jsonl",
        )
        plan = validate_plan({"query": "certification", "text_queries": ["certification"]})
        calls = [
            ("retrieve", lambda: retriever.retrieve(plan)),
            ("documents", lambda: retriever.documents([DOC_ID])),
            ("content_hashes", lambda: retriever.content_hashes([DOC_ID])),
            ("entity", lambda: retriever.entity("missing")),
            ("entity_document_ids", lambda: retriever.entity_document_ids("missing")),
            ("entity_relationships", lambda: retriever.entity_relationships("missing")),
            ("foundational_documents", lambda: retriever.foundational_documents(["missing"])),
            ("recent_documents", lambda: retriever.recent_documents()),
            ("enriched_documents", lambda: retriever.enriched_documents()),
        ]

        with retriever.bind_request("req"):
            for _, call in calls:
                call()

        methods = {record["method"] for record in read_jsonl(self.home / "audit/retrieval.jsonl")}
        self.assertTrue({name for name, _ in calls} <= methods)

    def test_full_queue_returns_429_retry_after_and_concurrency_stays_one(self):
        app = self.app(queue_depth=1)
        server = app.config["GANG_SERVER"]
        started = threading.Event()
        release = threading.Event()
        active = 0
        max_active = 0
        lock = threading.Lock()

        def slow_converse(question, *, session=None, overrides=None, options=None):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            started.set()
            release.wait(timeout=5)
            with lock:
                active -= 1
            session.record_turn(
                question=question,
                resolved_question=question,
                policy="lookup",
                mode="evidence",
                answer="ok",
                evidence=[],
                claims=[],
            )
            return {
                "session_id": session.session_id,
                "turn": session.turn_count,
                "intent": {"mode": "evidence"},
                "claims": [],
                "claim_ledger": {"version": "1", "claims": []},
                "claim_ledger_origin": "model",
                "conflicts": [],
                "uncertainties": [],
                "uncertainty": "",
                "insufficient_evidence": False,
                "sources": [],
                "synthesis": {"cached": False},
                "research": {},
            }

        server.service.converse = slow_converse
        client = app.test_client()

        first = self.post_ask(client, {"question": "first", "level": "fast"})
        self.assertEqual(first.status_code, 202)
        self.assertTrue(started.wait(timeout=5))
        second = self.post_ask(client, {"question": "second", "level": "fast"})
        self.assertEqual(second.status_code, 202)
        third = self.post_ask(client, {"question": "third", "level": "fast"})
        self.assertEqual(third.status_code, 429)
        self.assertEqual(third.headers["Retry-After"], "1")
        self.assertEqual(third.json["error"]["code"], "queue_full")
        self.assertIn("request_id", third.json["error"])

        release.set()
        self.await_job(client, first.json["job_id"])
        self.await_job(client, second.json["job_id"])
        self.assertEqual(server.worker_count, 1)
        self.assertEqual(max_active, 1)

    def test_default_queue_depth_is_eight(self):
        self.assertEqual(DEFAULT_QUEUE_DEPTH, 8)

    def test_token_hash_helper_stores_no_plaintext_secret(self):
        digest = sha256_token(self.token)

        self.assertEqual(len(digest), 64)
        self.assertNotIn(self.token, digest)

    def test_principal_directory_round_trip_authentication_and_private_mode(self):
        directory = PrincipalDirectory(self.home / "access/principals.yml")
        daniel = directory.add_principal("daniel", "Daniel")
        token = directory.issue_token("daniel", "iphone")

        loaded = directory.load()
        self.assertEqual(daniel.principal_id, "daniel")
        self.assertEqual(loaded[0].principal_id, "daniel")
        self.assertEqual(loaded[0].display_name, "Daniel")
        self.assertEqual(loaded[0].scope, "full")
        self.assertEqual(stat.S_IMODE(directory.path.stat().st_mode), 0o600)
        self.assertEqual(directory.resolve_token(token).principal_id, "daniel")
        self.assertIsNone(directory.resolve_token("unknown-token"))
        self.assertNotIn(token, directory.path.read_text(encoding="utf-8"))
        self.assertIn(sha256_token(token), directory.path.read_text(encoding="utf-8"))

        with self.assertRaises(PrincipalError):
            directory.add_principal("../bad", "Bad")

    def test_principal_directory_uses_full_digest_compare_digest(self):
        directory = PrincipalDirectory(self.home / "access/principals.yml")
        directory.add_principal("daniel", "Daniel")
        token = directory.issue_token("daniel", "iphone")
        compared = []

        def record_compare(left, right):
            compared.append((left, right))
            return hmac_compare_digest(left, right)

        import hmac

        hmac_compare_digest = hmac.compare_digest
        with mock.patch("core.access.principals.hmac.compare_digest", side_effect=record_compare):
            self.assertEqual(directory.resolve_token(token).principal_id, "daniel")

        self.assertTrue(compared)
        supplied, stored = compared[0]
        self.assertEqual(supplied, sha256_token(token))
        self.assertEqual(stored, sha256_token(token))
        self.assertEqual(len(supplied), 64)
        self.assertEqual(len(stored), 64)

    def test_access_cli_adds_principals_and_issues_separate_device_tokens(self):
        runner = CliRunner()
        env = {"GANG_HOME": str(self.home)}

        with runner.isolated_filesystem():
            daniel = runner.invoke(gang_cli.cli, ["access", "add-principal", "--id", "daniel", "--name", "Daniel"], env=env)
            frank = runner.invoke(gang_cli.cli, ["access", "add-principal", "--id", "frank", "--name", "Frank"], env=env)
            self.assertEqual(daniel.exit_code, 0, daniel.output)
            self.assertEqual(frank.exit_code, 0, frank.output)

            daniel_token = runner.invoke(gang_cli.cli, ["access", "issue-token", "--id", "daniel", "--label", "iphone"], env=env)
            frank_token = runner.invoke(gang_cli.cli, ["access", "issue-token", "--id", "frank", "--label", "iphone"], env=env)
            self.assertEqual(daniel_token.exit_code, 0, daniel_token.output)
            self.assertEqual(frank_token.exit_code, 0, frank_token.output)

        daniel_plaintext = daniel_token.output.strip()
        frank_plaintext = frank_token.output.strip()
        directory = PrincipalDirectory(self.home / "access/principals.yml")
        self.assertEqual(directory.resolve_token(daniel_plaintext).principal_id, "daniel")
        self.assertEqual(directory.resolve_token(frank_plaintext).principal_id, "frank")
        self.assertNotEqual(directory.resolve_token(daniel_plaintext).principal_id, "frank")
        contents = directory.path.read_text(encoding="utf-8")
        self.assertNotIn(daniel_plaintext, contents)
        self.assertNotIn(frank_plaintext, contents)

    def test_http_sessions_are_structurally_isolated_per_principal(self):
        _, daniel_token, frank_token = self.create_stage2_principals()
        app = create_app(root_path=self.root, private_home=self.home)
        server = app.config["GANG_SERVER"]

        def fake_converse(question, *, session=None, overrides=None, options=None):
            session.record_turn(
                question=question,
                resolved_question=question,
                policy="lookup",
                mode="evidence",
                answer="ok",
                evidence=[],
                claims=[],
            )
            server.service.sessions.save(session)
            return {
                "session_id": session.session_id,
                "turn": session.turn_count,
                "intent": {"mode": "evidence"},
                "claims": [],
                "claim_ledger": {"version": "1", "claims": []},
                "claim_ledger_origin": "model",
                "conflicts": [],
                "uncertainties": [],
                "uncertainty": "",
                "insufficient_evidence": False,
                "sources": [],
                "synthesis": {"cached": False},
                "research": {},
            }

        server.service.converse = fake_converse
        client = app.test_client()
        daniel_auth = self.auth(daniel_token)
        frank_auth = self.auth(frank_token)

        self.assertEqual(
            client.get("/v1/whoami", headers=daniel_auth).json["principal_id"],
            "daniel",
        )
        created = client.post(
            "/v1/ask",
            json={"question": "Daniel turn", "level": "fast", "session_id": "abcd1234"},
            headers=daniel_auth,
        )
        self.assertEqual(created.status_code, 202)
        self.await_job_with_auth(client, created.json["job_id"], daniel_auth)

        self.assertEqual(client.get("/v1/sessions/abcd1234", headers=frank_auth).status_code, 404)
        self.assertEqual(client.get("/v1/sessions", headers=frank_auth).json["sessions"], [])
        self.assertEqual(client.delete("/v1/sessions/abcd1234", headers=frank_auth).status_code, 404)

        frank_created = client.post(
            "/v1/ask",
            json={"question": "Frank turn", "level": "fast", "session_id": "wxyz5678"},
            headers=frank_auth,
        )
        self.assertEqual(frank_created.status_code, 202)
        self.await_job_with_auth(client, frank_created.json["job_id"], frank_auth)

        self.assertEqual(client.get("/v1/sessions/wxyz5678", headers=daniel_auth).status_code, 404)
        self.assertEqual(client.delete("/v1/sessions/wxyz5678", headers=daniel_auth).status_code, 404)
        self.assertEqual(client.delete("/v1/sessions/wxyz5678", headers=frank_auth).status_code, 200)
        self.assertEqual(client.get("/v1/sessions/abcd1234", headers=daniel_auth).status_code, 200)

    def await_job_with_auth(self, client, job_id, headers, *, block=5):
        return client.get(f"/v1/jobs/{job_id}?block={block}", headers=headers)

    def test_legacy_cli_sessions_remain_outside_principal_http_session_stores(self):
        legacy_store = SessionStore(self.home / "sessions")
        legacy_store.save(Session.new("legacy1234"))

        self.assertEqual(legacy_store.list_sessions()[0]["session_id"], "legacy1234")
        self.assertEqual(SessionStore(self.home / "sessions/daniel").list_sessions(), [])
        self.assertEqual(SessionStore(self.home / "sessions/frank").list_sessions(), [])


if __name__ == "__main__":
    unittest.main()
