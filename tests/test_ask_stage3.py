import json
import os
import subprocess
import sys
import textwrap
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "cli" / "gang"))

from core.ask.http_service import CSP_HEADER, create_app
from core.ask.session import Session, SessionStore
from core.private_index import PrivateKnowledgeIndex


DOC_ID = "01a0bcc1-7f14-7b41-a4e3-f4dbd6a37f01"


def write_markdown(path, frontmatter, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n\n" + body,
        encoding="utf-8",
    )


class Stage3ChatTests(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        patcher = mock.patch.dict(
            os.environ,
            {
                "ANTHROPIC_API_KEY": "",
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
        self.token = "stage3-token"
        for name in ("raw", "blobs", "entities", "ingestion"):
            (self.home / name).mkdir(parents=True)
        write_markdown(
            self.home / "vault/documents/qi.md",
            {
                "id": DOC_ID,
                "type": "knowledge",
                "source_type": "drive-file",
                "title": "Qi Certification",
                "visibility": "private",
                "status": "active",
                "source_id": "drive_qi",
                "created": "2026-09-10",
                "updated": "2026-09-10",
            },
            "Qi certification requires WPC review.\n",
        )
        PrivateKnowledgeIndex(root_path=self.root, private_home=self.home).build()

    def app(self, **kwargs):
        return create_app(
            root_path=self.root,
            private_home=self.home,
            auth_token=self.token,
            **kwargs,
        )

    def auth(self, token=None):
        return {"Authorization": f"Bearer {token or self.token}"}

    def test_get_root_serves_chat_app_with_csp(self):
        response = self.app().test_client().get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<script src="/app.js" defer></script>', response.data)
        self.assertEqual(response.headers["Content-Security-Policy"], CSP_HEADER)
        self.assertIn("script-src 'self';", response.headers["Content-Security-Policy"])
        self.assertIn("connect-src 'self';", response.headers["Content-Security-Policy"])

    def test_static_assets_have_no_external_origins_or_inline_html_script(self):
        for relative in ("apps/ask/index.html", "apps/ask/app.js", "apps/ask/style.css"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            with self.subTest(relative=relative):
                self.assertNotIn("http://", text)
                self.assertNotIn("https://", text)
                self.assertNotIn("//", text.replace("http://", "").replace("https://", ""))
        html = (ROOT / "apps/ask/index.html").read_text(encoding="utf-8")
        self.assertNotIn("<script>", html)
        self.assertNotIn("style=", html)

    def test_client_never_uses_inner_html(self):
        for relative in ("apps/ask/index.html", "apps/ask/app.js", "apps/ask/style.css"):
            with self.subTest(relative=relative):
                self.assertNotIn("innerHTML", (ROOT / relative).read_text(encoding="utf-8"))

    def test_invalid_token_gets_unauthorized_for_api_while_static_shell_loads(self):
        client = self.app().test_client()

        self.assertEqual(client.get("/").status_code, 200)
        response = client.get("/v1/whoami", headers=self.auth("wrong"))

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json["error"]["code"], "unauthorized")

    def test_whoami_principal_is_returned_for_display(self):
        response = self.app().test_client().get("/v1/whoami", headers=self.auth())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["display_name"], "Daniel")

    def test_session_listing_and_delete_use_authenticated_principal_store(self):
        store = SessionStore(self.home / "sessions/daniel")
        session = Session.new("stage3demo")
        session.record_turn(
            question="What is Qi?",
            resolved_question="What is Qi?",
            policy="lookup",
            mode="evidence",
            answer="Qi requires review.",
            evidence=[],
            claims=[],
        )
        store.save(session)
        client = self.app().test_client()

        listed = client.get("/v1/sessions", headers=self.auth())
        self.assertEqual([item["session_id"] for item in listed.json["sessions"]], ["stage3demo"])

        loaded = client.get("/v1/sessions/stage3demo", headers=self.auth())
        self.assertEqual(loaded.json["session"]["turns"][0]["question"], "What is Qi?")

        deleted = client.delete("/v1/sessions/stage3demo", headers=self.auth())
        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(store.list_sessions(), [])

    def test_frontend_payload_and_rendering_contract(self):
        output = run_node_stage3_check(
            """
            const payloadFast = window.GangAskTesting.buildAskPayload(' fast question ', 'abc123', 'fast');
            assert(payloadFast.level === 'fast', 'fast level allowed');
            assert(payloadFast.session_id === 'abc123', 'session id included only when continuing');
            assert(Object.keys(payloadFast).sort().join(',') === 'level,question,session_id', 'no sensitive controls sent');

            const payloadNormal = window.GangAskTesting.buildAskPayload('normal question', '', 'deep');
            assert(payloadNormal.level === 'normal', 'normal is default and only other level');
            assert(!('session_id' in payloadNormal), 'new conversation has no prior session id');

            const mount = document.createElement('div');
            window.GangAskTesting.renderAssistantResult(mount, {
              intent: {mode: 'advisory'},
              answer: '<script>alert(1)</script>',
              claims: [
                {id: 'c1', type: 'fact', status: 'accepted', text: '<script>alert(1)</script>', citations: [1]},
                {id: 'c2', type: 'inference', status: 'accepted', text: 'Likely blocked by review.', citations: [1]},
                {id: 'c3', type: 'recommendation', status: 'accepted', text: 'Put one owner on WPC follow-up.'}
              ],
              uncertainty: '<script>alert(2)</script>',
              uncertainties: ['Evidence does not settle timing.'],
              insufficient_evidence: true,
              sources: [
                {citation_id: 1, title: '<script>alert(3)</script>', source_type: 'drive-file', updated: '2026-09-10', excerpt: 'must not render'}
              ]
            });
            const text = collectText(mount);
            assert(text.includes('<script>alert(1)</script>'), 'answer and claims render literally as text');
            assert(text.includes('<script>alert(3)</script>'), 'citation title renders literally as text');
            assert(text.includes('Advisory'), 'advisory mode visible');
            assert(text.includes('Inference'), 'inference section visible');
            assert(text.includes('GANG recommendation'), 'recommendation section visible');
            assert(text.includes('Generated from the cited evidence; not a recorded company decision.'), 'recommendation note visible');
            assert(text.includes('Insufficient evidence'), 'insufficient evidence visible');
            assert(!text.includes('must not render'), 'raw evidence excerpts are not rendered');
            """
        )
        self.assertEqual(output.strip(), "ok")

    def test_job_polling_status_labels_and_forget_key(self):
        output = run_node_stage3_check(
            """
            assert(window.GangAskTesting.statusLabel('queued') === 'Waiting...', 'queued label');
            assert(window.GangAskTesting.statusLabel('running') === 'Thinking...', 'running label');
            localStorage.setItem(window.GangAskTesting.tokenKey, 'secret');
            localStorage.removeItem(window.GangAskTesting.tokenKey);
            assert(localStorage.getItem(window.GangAskTesting.tokenKey) === null, 'forget removes token');
            """
        )
        self.assertEqual(output.strip(), "ok")


def run_node_stage3_check(check_source):
    script = textwrap.dedent(
        f"""
        class TextNode {{
          constructor(value) {{
            this.nodeType = 3;
            this.textContent = String(value);
            this.children = [];
          }}
        }}

        class Element {{
          constructor(tag) {{
            this.tagName = tag;
            this.children = [];
            this.dataset = {{}};
            this.className = '';
            this.attributes = {{}};
            this.value = '';
            this.disabled = false;
            this.type = '';
          }}
          set textContent(value) {{
            this.children = [new TextNode(value)];
          }}
          get textContent() {{
            return this.children.map((child) => child.textContent || '').join('');
          }}
          appendChild(child) {{
            this.children.push(child);
            return child;
          }}
          append(...children) {{
            children.forEach((child) => this.appendChild(child));
          }}
          replaceChildren(...children) {{
            this.children = [];
            this.append(...children);
          }}
          setAttribute(name, value) {{
            this.attributes[name] = String(value);
          }}
          addEventListener() {{}}
          focus() {{}}
          querySelector() {{
            return null;
          }}
          querySelectorAll() {{
            return [];
          }}
          get classList() {{
            const self = this;
            return {{
              add(value) {{ self.className = self.className ? self.className + ' ' + value : value; }},
              remove(value) {{ self.className = self.className.split(' ').filter((item) => item !== value).join(' '); }},
              toggle(value, active) {{
                if (active) {{
                  this.add(value);
                }} else {{
                  this.remove(value);
                }}
              }}
            }};
          }}
        }}

        Object.defineProperty(Element.prototype, 'innerHTML', {{
          set() {{
            throw new Error('innerHTML must not be used');
          }},
          get() {{
            return '';
          }}
        }});

        const storage = new Map();
        global.window = {{}};
        global.document = {{
          createElement(tag) {{ return new Element(tag); }},
          createTextNode(value) {{ return new TextNode(value); }},
          getElementById() {{ return new Element('div'); }},
          querySelector() {{ return null; }},
          addEventListener() {{}}
        }};
        global.localStorage = {{
          getItem(key) {{ return storage.has(key) ? storage.get(key) : null; }},
          setItem(key, value) {{ storage.set(key, String(value)); }},
          removeItem(key) {{ storage.delete(key); }}
        }};
        global.fetch = function () {{ throw new Error('unexpected fetch'); }};
        function assert(condition, message) {{
          if (!condition) {{
            throw new Error(message);
          }}
        }}
        function collectText(node) {{
          if (!node) {{
            return '';
          }}
          if (node.nodeType === 3) {{
            return node.textContent;
          }}
          return (node.children || []).map(collectText).join('\\n');
        }}
        require({json.dumps(str(ROOT / "apps/ask/app.js"))});
        {textwrap.dedent(check_source)}
        console.log('ok');
        """
    )
    return subprocess.check_output(["node", "-e", script], text=True, cwd=ROOT)


if __name__ == "__main__":
    unittest.main()
