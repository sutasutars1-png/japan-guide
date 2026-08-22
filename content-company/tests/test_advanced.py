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


class _RewriteStub:
    """実LLMを模したランナー。指定回の再執筆後に review を pass させる。"""
    def __init__(self, pass_after_rewrites: int):
        self.writes = 0
        self.pass_after = pass_after_rewrites

    def run(self, tt, payload):
        if tt == "research":
            return {"theme": payload.get("theme"), "demand_signals": [], "note": ""}
        if tt == "product_plan":
            return {"product_name": "P", "why_sells": "x", "target": "t"}
        if tt == "article_write":
            self.writes += 1
            # 体裁・価格連動の品質ゲートを通す本文（見出し/分量/例/箇条書き）。
            body = ("# 見出し v%d\n" % self.writes
                    + "この記事では具体的な手順を説明します。たとえば実際のケースを挙げます。" * 70
                    + "\n- 手順1\n- 手順2\n")
            return {"title": "P", "body_markdown": body,
                    "_llm": True, "outline": ["導入", "本論", "まとめ"], "cta": ""}
        if tt == "review_final":
            passed = self.writes > self.pass_after
            return {"verdict": "pass" if passed else "reject",
                    "checklist": {}, "notes": "具体例を追加して"}
        return {}


class RewriteLoopTest(unittest.TestCase):
    def test_passes_after_one_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp, max_rewrites=3)
            c.tasks.runner = _RewriteStub(pass_after_rewrites=1)
            res = c.plan_products(1)[0]
            self.assertEqual(res["rewrites"], 1)
            self.assertEqual(res["status"], "awaiting_approval")

    def test_stops_at_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp, max_rewrites=3)
            c.tasks.runner = _RewriteStub(pass_after_rewrites=99)  # 決して通らない
            res = c.plan_products(1)[0]
            self.assertEqual(res["rewrites"], 3)  # 上限3で打ち切り
            self.assertEqual(res["status"], "review")  # 人間へ差し戻し
            # 上限到達が失敗メモリに残る
            self.assertTrue(any(m.get("kind") == "failure"
                                for m in c.storage.read_log("memory")))

    def test_template_runner_does_not_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp, max_rewrites=3)  # 既定 TemplateRunner（雛形）
            res = c.plan_products(1)[0]
            self.assertEqual(res["rewrites"], 0)  # 雛形は再執筆しない


class NoteChannelTest(unittest.TestCase):
    def _published_product(self, c, title="テスト商品", url="https://note.com/u/n/abc"):
        from company.models import Product
        p = Product(title=title, category="A", theme="AI 副業",
                    status="published", url=url, published_at="2026-07-01T00:00:00+00:00")
        c.storage.put("products", p.to_dict())
        c.storage.put("articles", {"id": "art1", "product_id": p.id,
                                   "body_markdown": "導入\n\n―― ここから有料 ――\n\n本編"})
        return p

    def test_export_writes_markdown_with_paid_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            p = self._published_product(c)
            r = c.note_export.export(p.id)
            self.assertTrue(pathlib.Path(r["path"]).exists())
            self.assertIn("有料エリア", r["markdown"])
            self.assertIn("#AI", " ".join("#" + t for t in r["hashtags"]) + " #AI")

    def test_export_no_duplicate_h1(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            from company.models import Product
            p = Product(title="重複しない見出し", category="A", theme="AI", status="published")
            c.storage.put("products", p.to_dict())
            c.storage.put("articles", {"id": "a", "product_id": p.id,
                                       "body_markdown": "# 重複しない見出し\n\n本文"})
            md = c.note_export.export(p.id)["markdown"]
            self.assertEqual(md.count("# 重複しない見出し"), 1)

    def test_import_matches_by_url_and_title(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            p1 = self._published_product(c, title="AIノート", url="https://note.com/u/n/aaa")
            p2 = self._published_product(c, title="副業ノート", url="https://note.com/u/n/bbb")
            csv = ("タイトル,URL,ビュー,購入数,売上金額,スキ\n"
                   "別名でも一致,https://note.com/u/n/aaa,1500,40,4000,60\n"
                   "副業ノート,,800,10,1000,20\n"
                   "存在しない,https://note.com/u/n/zzz,10,0,0,0\n")
            r = c.note_import.import_csv(csv)
            self.assertEqual(r["matched"], 2)
            self.assertEqual(len(r["unmatched"]), 1)
            # URL一致で p1 の実績が更新される
            up1 = c.storage.get("products", p1.id)
            self.assertEqual(up1["pv"], 1500)
            self.assertEqual(up1["purchases"], 40)
            up2 = c.storage.get("products", p2.id)
            self.assertEqual(up2["revenue_jpy"], 1000)

    def test_import_handles_yen_and_commas_and_english_headers(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            p = self._published_product(c, title="English Title", url="")
            csv = ("title,views,sales,revenue\n"
                   "English Title,\"1,200\",30,\"¥3,000\"\n")
            r = c.note_import.import_csv(csv)
            self.assertEqual(r["matched"], 1)
            up = c.storage.get("products", p.id)
            self.assertEqual(up["pv"], 1200)
            self.assertEqual(up["revenue_jpy"], 3000)

    def test_import_dry_run_does_not_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            p = self._published_product(c, title="X", url="https://note.com/u/n/x")
            csv = "タイトル,URL,ビュー\nX,https://note.com/u/n/x,999\n"
            r = c.note_import.import_csv(csv, dry_run=True)
            self.assertEqual(r["matched"], 1)
            self.assertTrue(r["dry_run"])
            self.assertEqual(c.storage.get("products", p.id)["pv"], 0)  # 未更新


class SocialChannelTest(unittest.TestCase):
    def _pub(self, c):
        from company.models import Product
        p = Product(title="売れ筋", category="A", theme="AI 副業", status="published",
                    url="https://note.com/u/n/x", revenue_jpy=5000)
        c.storage.put("products", p.to_dict())
        return p

    def test_draft_creates_approval_and_requires_it_before_posting(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            p = self._pub(c)
            d = c.social.draft("x", p.id)
            self.assertEqual(d["channel"], "x")
            self.assertTrue(d["approval_id"])
            # 承認前は投稿記録できない（§32 人間確認）
            with self.assertRaises(PermissionError_):
                c.social.mark_posted(d["social_id"], "https://x.com/i/status/1")
            c.approvals.approve(d["approval_id"])
            post = c.social.mark_posted(d["social_id"], "https://x.com/i/status/1")
            self.assertEqual(post.status, "posted")
            self.assertEqual(post.url, "https://x.com/i/status/1")

    def test_tiktok_draft_and_reject_channel(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            p = self._pub(c)
            d = c.social.draft("tiktok", p.id)
            self.assertEqual(d["content"]["channel"], "tiktok")
            with self.assertRaises(ValueError):
                c.social.draft("instagram", p.id)


class SchedulerTest(unittest.TestCase):
    def test_default_off_and_safe_jobs_only(self):
        from company.scheduler import SAFE_JOBS
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            self.assertFalse(c.scheduler.get_state()["enabled"])  # 既定オフ
            self.assertEqual(set(SAFE_JOBS), {"evaluate", "note_import", "social_draft"})
            with self.assertRaises(KeyError):
                c.scheduler.run_job("rm_rf")  # 未登録は実行不可

    def test_run_jobs_are_safe(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            self.assertTrue(c.scheduler.run_job("evaluate")["ok"])
            # note_import: inbox が無ければスキップ（エラーにしない）
            r = c.scheduler.run_job("note_import")
            self.assertIn("skipped", r["result"])
            # social_draft: チャネル無効ならスキップ（投稿もしない）
            r2 = c.scheduler.run_job("social_draft")
            self.assertIn("skipped", r2["result"])

    def test_social_draft_job_respects_channel_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            from company.models import Product
            p = Product(title="P", category="A", status="published", revenue_jpy=100)
            c.storage.put("products", p.to_dict())
            c.update_config({"x_enabled": True})
            r = c.scheduler.run_job("social_draft")
            self.assertTrue(r["result"]["made"])  # x 下書きが1件作られる
            self.assertTrue(c.social.has_draft("x", p.id))

    def test_persist_and_reload_schedule(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            c.scheduler.set_job("evaluate", enabled=True, interval_min=60)
            c.scheduler.set_enabled(True)
            c.scheduler.stop()
            c2 = make_company(tmp)
            st = c2.scheduler.get_state()
            self.assertTrue(st["enabled"])
            self.assertTrue(st["jobs"]["evaluate"]["enabled"])
            self.assertEqual(st["jobs"]["evaluate"]["interval_min"], 60)


class ConfigTest(unittest.TestCase):
    def test_update_rejects_unsafe_fields_and_persists(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            out = c.update_config({"x_enabled": "true", "max_rewrites": "9",
                                   "data_dir": "/etc", "unknown": 1})
            self.assertTrue(c.config.x_enabled)
            self.assertEqual(c.config.max_rewrites, 5)  # 上限5にクランプ
            self.assertEqual(str(c.config.data_dir), tmp)  # data_dir は不変
            self.assertNotIn("data_dir", out["applied"])
            # 再構築で永続化を確認
            c2 = make_company(tmp)
            self.assertTrue(c2.config.x_enabled)


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

    def test_csrf_blocks_cross_origin_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            httpd, port = self._server(c)
            try:
                def post(origin):
                    req = urllib.request.Request(
                        f"http://127.0.0.1:{port}/api/schedule/master",
                        data=b'{"enabled":true}',
                        headers={"Content-Type": "application/json", "Origin": origin},
                        method="POST")
                    try:
                        with urllib.request.urlopen(req, timeout=5) as r:
                            return r.status
                    except urllib.error.HTTPError as e:
                        return e.code
                self.assertEqual(post("http://evil.example.com"), 403)  # クロスサイトは拒否
                self.assertEqual(post(f"http://127.0.0.1:{port}"), 200)  # 同一オリジンは許可
            finally:
                httpd.shutdown()
                httpd.server_close()

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
                # config 更新（安全フィールドのみ）
                cfg = self._post(port, "/api/config", {"x_enabled": True, "data_dir": "/etc"})
                self.assertTrue(cfg["config"]["x_enabled"])
                # schedule master + job
                sm = self._post(port, "/api/schedule/master", {"enabled": False})
                self.assertFalse(sm["enabled"])
                sj = self._post(port, "/api/schedule/job",
                                {"name": "evaluate", "enabled": True, "interval_min": 120})
                self.assertTrue(sj["jobs"]["evaluate"]["enabled"])
                # social draft（公開商品を用意）
                from company.models import Product
                p = Product(title="pub", category="A", status="published")
                c.storage.put("products", p.to_dict())
                sd = self._post(port, "/api/social/draft", {"channel": "x", "product_id": p.id})
                self.assertEqual(sd["channel"], "x")
                st3 = self._get(port, "/api/state")
                self.assertTrue(st3["channels"]["x"])
                self.assertTrue(len(st3["social"]) >= 1)
            finally:
                httpd.shutdown()
                httpd.server_close()


if __name__ == "__main__":
    unittest.main()
