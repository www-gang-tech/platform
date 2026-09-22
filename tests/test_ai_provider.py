import json
import os
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock
from urllib.error import URLError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

from core.ai_provider import AIConfig, ConfiguredAIClient, OllamaClient, ProviderError, ProviderTimeoutError


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class AIProviderTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.dict(
            os.environ,
            {"ANTHROPIC_API_KEY": "", "GANG_OLLAMA_TIMEOUT_SECONDS": "", "GANG_OLLAMA_ENDPOINT": ""},
            clear=False,
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_default_ask_config_is_local_ollama(self):
        config = AIConfig.from_mapping({})

        selected = config.select("synthesis")

        self.assertEqual(selected.provider, "ollama")
        self.assertEqual(selected.model, "mistral-small3.1")
        self.assertEqual(config.ollama_timeout_seconds, 180.0)

    def test_ollama_timeout_is_configurable(self):
        config = AIConfig.from_mapping({"ollama": {"timeout_seconds": 12}})
        client = ConfiguredAIClient(role="synthesis", config=config)

        self.assertEqual(client._client.timeout, 12.0)

    def test_local_synthesis_packet_budget_is_configurable(self):
        config = AIConfig.from_mapping(
            {
                "local_synthesis": {
                    "max_prompt_tokens": 3200,
                    "max_evidence_tokens": 2100,
                    "max_documents": 3,
                    "max_excerpts_per_document": 1,
                    "max_output_tokens": 420,
                }
            }
        )

        budget = config.local_synthesis_budget
        self.assertEqual(budget.max_prompt_tokens, 3200)
        self.assertEqual(budget.max_evidence_tokens, 2100)
        self.assertEqual(budget.max_documents, 3)
        self.assertEqual(budget.max_excerpts_per_document, 1)
        self.assertEqual(budget.max_output_tokens, 420)

    def test_ollama_request_targets_configured_endpoint_and_parses_json(self):
        seen = {}

        def fake_urlopen(request, timeout):
            seen["url"] = request.full_url
            seen["timeout"] = timeout
            seen["payload"] = json.loads(request.data.decode("utf-8"))
            return FakeResponse(
                {
                    "prompt_eval_count": 11,
                    "eval_count": 7,
                    "prompt_eval_duration": 2_000_000_000,
                    "eval_duration": 3_500_000_000,
                    "message": {
                        "content": json.dumps(
                            {
                                "answer": "Local answer [1].",
                                "claims": [],
                                "conflicts": [],
                                "uncertainty": "",
                                "insufficient_evidence": False,
                            }
                        )
                    }
                }
            )

        with mock.patch("core.ai_provider._urlopen", side_effect=fake_urlopen):
            result = OllamaClient(
                model="mistral-small3.1", endpoint="http://127.0.0.1:11434"
            ).complete_json(
                {"system": "s", "messages": [{"role": "user", "content": "u"}], "max_tokens": 420},
                purpose="test",
            )

        self.assertEqual(seen["url"], "http://127.0.0.1:11434/api/chat")
        self.assertEqual(seen["payload"]["model"], "mistral-small3.1")
        self.assertEqual(seen["payload"]["messages"][0]["role"], "system")
        self.assertEqual(seen["payload"]["options"]["num_predict"], 420)
        self.assertEqual(seen["timeout"], 180.0)
        self.assertEqual(result["answer"], "Local answer [1].")

    def test_ollama_records_call_telemetry_when_available(self):
        with mock.patch(
            "core.ai_provider._urlopen",
            return_value=FakeResponse(
                {
                    "prompt_eval_count": 13,
                    "eval_count": 5,
                    "prompt_eval_duration": 1_250_000_000,
                    "eval_duration": 2_500_000_000,
                    "message": {"content": "{}"},
                }
            ),
        ):
            client = OllamaClient()
            client.complete_json(
                {"system": "s", "messages": [{"role": "user", "content": "u"}], "max_tokens": 20},
                purpose="test",
            )

        self.assertEqual(client.telemetry["provider"], "ollama")
        self.assertEqual(client.telemetry["prompt_token_count"], 13)
        self.assertEqual(client.telemetry["generated_token_count"], 5)
        self.assertEqual(client.telemetry["prompt_eval_duration_seconds"], 1.25)
        self.assertEqual(client.telemetry["generation_duration_seconds"], 2.5)
        self.assertIn("elapsed_seconds", client.telemetry)

    def test_local_failure_never_falls_back_to_remote(self):
        client = ConfiguredAIClient(role="synthesis", config=AIConfig.from_mapping({}))

        with mock.patch("core.ai_provider._urlopen", side_effect=URLError("offline")) as urlopen:
            with self.assertRaises(ProviderError) as raised:
                client.complete_json(
                    {"system": "s", "messages": [{"role": "user", "content": "u"}], "max_tokens": 20},
                    purpose="test",
                )

        self.assertEqual(client.provider_name, "ollama")
        self.assertEqual(urlopen.call_args.args[0].full_url, "http://127.0.0.1:11434/api/chat")
        self.assertIn("No remote fallback was used", str(raised.exception))

    def test_ollama_timeout_is_classified_and_recorded(self):
        client = ConfiguredAIClient(role="synthesis", config=AIConfig.from_mapping({}))

        with mock.patch("core.ai_provider._urlopen", side_effect=TimeoutError("timed out")):
            with self.assertRaises(ProviderTimeoutError):
                client.complete_json(
                    {"system": "s", "messages": [{"role": "user", "content": "u"}], "max_tokens": 20},
                    purpose="test",
                )

        self.assertEqual(client.telemetry["status"], "timeout")
        self.assertEqual(client.telemetry["provider"], "ollama")
        self.assertIn("elapsed_seconds", client.telemetry)

    def test_malformed_ollama_response_fails_cleanly(self):
        with mock.patch(
            "core.ai_provider._urlopen",
            return_value=FakeResponse({"message": {"content": "not json"}}),
        ):
            with self.assertRaises(ProviderError):
                OllamaClient().complete_json(
                    {"system": "s", "messages": [{"role": "user", "content": "u"}], "max_tokens": 20},
                    purpose="test",
                )

    def test_local_only_blocks_explicit_remote(self):
        config = AIConfig.from_mapping({"local_only": True})

        with self.assertRaises(ProviderError) as raised:
            ConfiguredAIClient(role="synthesis", config=config, provider="anthropic")

        self.assertIn("local_only is enabled", str(raised.exception))

    def test_ollama_redirect_is_not_followed(self):
        seen = {"chat": 0, "stolen": 0}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                if self.path == "/stolen":
                    seen["stolen"] += 1
                    body = b'{"message":{"content":"{}"}}'
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                seen["chat"] += 1
                target = f"http://127.0.0.1:{self.server.server_address[1]}/stolen"
                self.send_response(307)
                self.send_header("Location", target)
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, format, *args):
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.shutdown)
        self.addCleanup(server.server_close)
        port = server.server_address[1]

        with self.assertRaises(ProviderError) as raised:
            OllamaClient(endpoint=f"http://127.0.0.1:{port}", timeout=5).complete_json(
                {"system": "s", "messages": [{"role": "user", "content": "private evidence"}], "max_tokens": 20},
                purpose="test",
            )

        self.assertIn("redirect", str(raised.exception).lower())
        self.assertEqual(seen["chat"], 1)
        self.assertEqual(seen["stolen"], 0)
        self.assertNotIn("private evidence", str(raised.exception))

    def test_ollama_does_not_send_the_prompt_through_an_env_proxy(self):
        seen = []

        class Proxy(BaseHTTPRequestHandler):
            def do_POST(self):
                seen.append(self.path)
                self.send_response(500)
                self.end_headers()

            def do_CONNECT(self):
                seen.append(self.path)
                self.send_error(500)

            def log_message(self, format, *args):
                return

        proxy = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
        thread = threading.Thread(target=proxy.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(proxy.shutdown)
        self.addCleanup(proxy.server_close)
        proxy_url = f"http://127.0.0.1:{proxy.server_address[1]}"

        with mock.patch.dict(
            os.environ,
            {"HTTP_PROXY": proxy_url, "http_proxy": proxy_url, "NO_PROXY": "", "no_proxy": ""},
        ):
            with self.assertRaises(ProviderError):
                OllamaClient(endpoint="http://127.0.0.1:9", timeout=2).complete_json(
                    {"system": "s", "messages": [{"role": "user", "content": "private evidence"}], "max_tokens": 20},
                    purpose="test",
                )

        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
