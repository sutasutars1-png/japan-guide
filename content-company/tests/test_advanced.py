"""LLMランナー(フォールバック) / Skill自己改善 / Web GUI の検証。

実 LLM は呼ばない（CLI 未検出パスとJSON整形のみ検証）。GUI は ephemeral port の
実サーバに urllib で叩く。すべて標準ライブラリ。
"""

from __future__ import annotations

import json
import pathlib
import sys
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from company.approval import PermissionError_  # noqa: E402
from company.company import Company  # noqa: E402
from company.config import Config  # noqa: E402
from company.runner_claude import ClaudeRunner, _extract_json  # noqa: E402


def make_company(tmp: str, **ov) -> Company:
    cfg = Config(data_dir=pathlib.Path(tmp))
    for k, v in ov.items():
        setattr(cfg, k, v)
    return Company(cfg)


class ClaudeRunnerTest(unittest.TestCase):
    def test_extract_json_variants(self):
        self.assertEqual(_extract_json('{"a":1}'), {"a": 1})
        self.assertEqual(_extract_json('前置き {"a":1} 後'), {"a": 1})
        self.assertEqual(_extract_json('```json\n{"a":2}\n```'), {"a": 2})
        self.assertIsNone(_extract_json("no json here"))
        self.assertIsNone(_extract_json(""))

    def test_fallback_when_binary_missing(self):
        r = ClaudeRunner(claude_bin="definitely-no-such-binary-xyz")
        out = r.run("research", {"task_type": "research", "theme": "x"})
        self.assertIn("_llm_error", out)
        self.assertIn("demand_signals", out)  # TemplateRunner の形

    def test_coerce_review_verdict(self):
        r = ClaudeRunner()
        self.assertEqual(r._coerce("review_final", {"verdict": "PASS"})["verdict"], "pass")
        self.assertEqual(r._coerce("review_final", {"verdict": "却下 reject"})["verdict"], "reject")
        # article には is_skeleton を付けない（レビュー通過しうる）
        self.assertNotIn("is_skeleton", r._coerce("article_write", {"title": "t"}))

    def test_build_prompt_has_role_and_keys(self):
        r = ClaudeRunner()
        p = r._build_prompt("product_plan", {"task_type": "product_plan", "theme": "副業"})
        self.assertIn("CPO", p)
        self.assertIn("product_name", p)
        self.assertIn("JSON", p)


class SkillLabTest(unittest.TestCase):
    def test_full_improvement_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            lab = c.skills_lab
            # seed: v1 adopted
            cur = lab.current("article-writing")
            self.assertEqual(cur["version"], 1)
            self.assertEqual(cur["status"], "adopted")

            # 改善案 → v2 candidate。current は変わらない（直接上書き禁止）
            cand = lab.propose("article-writing",
                               guidance="冒頭200字で読者の悩みを言語化する",
                               forbidden=["誇張", "誤情報", "AIっぽさ"])
            self.assertEqual(cand["version"], 2)
            self.assertEqual(cand["status"], "candidate")
            self.assertEqual(lab.current("article-writing")["version"], 1)

            # 評価（旧版比較）→ guidance追加で改善
            ev = lab.evaluate("article-writing", 2)
            self.assertTrue(ev["improved"])

            # 承認前は採用できない（§21）
            apr = lab.request_adoption("article-writing", 2)
            with self.assertRaises(PermissionError_):
                lab.adopt("article-writing", 2, apr["id"])

            # 承認 → 採用。current=2、旧版は retired
            c.approvals.approve(apr["id"])
            adopted = lab.adopt("article-writing", 2, apr["id"])
            self.assertEqual(adopted["status"], "adopted")
            self.assertEqual(lab.current("article-writing")["version"], 2)
            v1 = next(v for v in lab.versions("article-writing") if v["version"] == 1)
            self.assertEqual(v1["status"], "retired")
            # 決定ログに履歴が残る（§44-12）
            self.assertTrue(any(d.get("context", "").startswith("Skill採用")
                                for d in c.storage.read_log("decisions")))

    def test_text_reflects_current_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            t1 = c.skills_lab.text("seo")
            self.assertIn("v1", t1)
            cand = c.skills_lab.propose("seo", guidance="検索意図を3分類する")
            apr = c.skills_lab.request_adoption("seo", cand["version"])
            c.approvals.approve(apr["id"])
            c.skills_lab.adopt("seo", cand["version"], apr["id"])
            self.assertIn("検索意図を3分類する", c.skills_lab.text("seo"))


class WebGuiTest(unittest.TestCase):
    def _server(self, c: Company):
        from company.webgui import _Handler
        _Handler.company = c
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        return httpd, httpd.server_address[1]

    def _get(self, port, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
            return json.loads(r.read().decode()) if path.startswith("/api") else r.read()

    def _post(self, port, path, body):
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as r:
            return json.loads(r.read().decode())

    def test_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            httpd, port = self._server(c)
            try:
                # index + dashboard は HTML
                self.assertIn(b"<title>", self._get(port, "/"))
                self.assertIn(b"KPI", self._get(port, "/dashboard"))
                # state
                st = self._get(port, "/api/state")
                self.assertIn("summary", st)
                self.assertEqual(st["runner"], "TemplateRunner")
                # plan（雛形。承認は作られない=review 差し戻し）
                r = self._post(port, "/api/plan", {"n": 2})
                self.assertEqual(len(r["planned"]), 2)
                # skill propose → 承認待ちが1件できる
                cand = self._post(port, "/api/skill/propose",
                                  {"key": "seo", "guidance": "x"})
                self.assertEqual(cand["version"], 2)
                apr = self._post(port, "/api/skill/request-adoption",
                                 {"key": "seo", "version": 2})
                self.assertEqual(apr["kind"], "config")
                st2 = self._get(port, "/api/state")
                self.assertTrue(any(a["kind"] == "config" for a in st2["pending"]))
            finally:
                httpd.shutdown()
                httpd.server_close()


if __name__ == "__main__":
    unittest.main()
