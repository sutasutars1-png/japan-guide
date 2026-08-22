"""Company OS の主要フローの検証。標準ライブラリ (unittest) のみ。"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from company.approval import ApprovalGateway, PermissionError_  # noqa: E402
from company.company import Company  # noqa: E402
from company.config import Config  # noqa: E402
from company.cost import BudgetExceeded  # noqa: E402
from company.router import ModelRouter  # noqa: E402
from company.storage import Storage  # noqa: E402


def make_company(tmp: str, **overrides) -> Company:
    cfg = Config(data_dir=pathlib.Path(tmp))
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return Company(cfg)


class StorageTest(unittest.TestCase):
    def test_put_get_and_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Storage(tmp)
            s.put("products", {"id": "p1", "title": "A"})
            self.assertEqual(s.get("products", "p1")["title"], "A")
            self.assertIsNone(s.get("products", "missing"))
            self.assertEqual(len(s.all("products")), 1)

    def test_log_append_and_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Storage(tmp)
            s.append("memory", {"id": "m1", "title": "x"})
            s.append("memory", {"id": "m2", "title": "y"})
            rows = list(s.read_log("memory"))
            self.assertEqual([r["id"] for r in rows], ["m1", "m2"])

    def test_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = Storage(pathlib.Path(tmp) / "data")
            s.put("products", {"id": "p1"})
            dest = pathlib.Path(tmp) / "backup"
            archive = s.snapshot(dest)
            self.assertTrue(archive.exists())
            self.assertTrue(str(archive).endswith(".zip"))


class RouterTest(unittest.TestCase):
    def test_tiers(self):
        r = ModelRouter()
        self.assertEqual(r.route("classify").tier, 1)  # 簡単
        self.assertEqual(r.route("article_write").tier, 2)  # 難+重要度中
        self.assertEqual(r.route("ceo_decision").tier, 3)  # 難+重要
        self.assertEqual(r.route("review_final").tier, 3)


class ApprovalTest(unittest.TestCase):
    def test_guard_blocks_without_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = ApprovalGateway(Storage(tmp))
            with self.assertRaises(PermissionError_):
                g.guard("publish", None)
            apr = g.request("publish", "test", {})
            with self.assertRaises(PermissionError_):
                g.guard("publish", apr.id)  # まだ未承認
            g.approve(apr.id)
            g.guard("publish", apr.id)  # 承認後は通る

    def test_non_sensitive_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            g = ApprovalGateway(Storage(tmp))
            g.guard("summarize", None)  # 例外なし


class PipelineTest(unittest.TestCase):
    def test_plan_products_reaches_awaiting_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            res = c.plan_products(5)
            self.assertEqual(len(res), 5)
            # TemplateRunner の企画は雛形なのでレビューで差し戻される設計。
            statuses = {r["status"] for r in res}
            self.assertTrue(statuses.issubset({"awaiting_approval", "review"}))
            # タスクが5工程×5商品ぶん作られている (research/plan/write/review)
            self.assertGreaterEqual(len(c.storage.all("tasks")), 5 * 4)
            # 仮説・商品・記事が保存されている
            self.assertEqual(len(c.storage.all("products")), 5)
            self.assertEqual(len(c.storage.all("hypotheses")), 5)
            self.assertEqual(len(c.storage.all("articles")), 5)
            # 決定ログとメモリが積まれている
            self.assertGreaterEqual(len(list(c.storage.read_log("decisions"))), 1)
            self.assertGreaterEqual(len(c.memory.all()), 5)

    def test_article_for_returns_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            res = c.plan_products(1)
            pid = res[0]["product_id"]
            art = c.article_for(pid)
            self.assertIsNotNone(art)
            self.assertIn("body_markdown", art)
            self.assertTrue(art["body_markdown"])
            # 雛形は is_skeleton が立ち、確認できる
            self.assertTrue(art.get("is_skeleton"))
            # 未知の商品では None
            self.assertIsNone(c.article_for("nope"))

    def test_quality_format_and_price_tier(self):
        from company import quality
        # 体裁: 見出しなし・プレースホルダ残り
        bad = {"body_markdown": "本文だけ。[ここに具体例を記入]"}
        fi = quality.format_issues(bad)
        self.assertTrue(any("見出し" in x for x in fi))
        self.assertTrue(any("プレースホルダ" in x for x in fi))
        # 価格連動: 高価格帯に薄い本文は不足指摘
        thin = {"body_markdown": "# 見出し\n短い本文。"}
        ti = quality.tier_issues(thin, 3000)
        self.assertTrue(ti)  # 文字数・具体例・チェックリスト不足
        # 十分な入門記事は体裁OK
        ok = {"body_markdown": "# タイトル\n" + "本文です。" * 80 + "\n- 手順1\nたとえば具体例。"}
        self.assertEqual(quality.format_issues(ok), [])

    def test_performance_hints_reads_outcome(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            c.storage.put("products", {"id": "p1", "title": "勝ち", "theme": "副業",
                                       "outcome": "success"})
            c.storage.put("products", {"id": "p2", "title": "負け", "theme": "健康",
                                       "outcome": "fail"})
            h = c._performance_hints()
            self.assertTrue(any("勝ち" in x for x in h["winning_angles"]))
            self.assertTrue(any("負け" in x for x in h["losing_angles"]))

    def test_similarity_guard_detects_near_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            a = {"title": "副業の始め方", "outline": ["準備", "実践", "継続"],
                 "body_markdown": "副業を始めるための具体的な手順を解説します。"}
            b = {"title": "副業の始め方", "outline": ["準備", "実践", "継続"],
                 "body_markdown": "副業を始めるための具体的な手順を解説します。"}
            existing = [("既存A", c._article_signature(a))]
            sim, title = c._max_similarity(c._article_signature(b), existing)
            self.assertGreater(sim, c.config.similarity_threshold)
            self.assertEqual(title, "既存A")
            # 全く違う記事は閾値未満
            other = {"title": "料理の時短術", "outline": ["下ごしらえ"],
                     "body_markdown": "冷凍作り置きで平日の夕食を10分に。"}
            sim2, _ = c._max_similarity(c._article_signature(other), existing)
            self.assertLess(sim2, c.config.similarity_threshold)

    def test_request_rewrite_creates_new_article(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            res = c.plan_products(1)
            pid = res[0]["product_id"]
            before = len(c.storage.find("articles", product_id=pid))
            r = c.request_rewrite(pid, "冒頭を具体的に")
            after = len(c.storage.find("articles", product_id=pid))
            self.assertEqual(after, before + 1)          # 新しい記事版が保存される
            self.assertIn(r["status"], ("awaiting_approval", "review"))

    def test_renumber_ordered_lists(self):
        from company.note_channel import renumber_ordered_lists
        out = renumber_ordered_lists("1. a\n\n5. b\n\n2. c")
        self.assertEqual(out.count("1."), 1)   # 先頭のみ 1.
        self.assertIn("2. b", out)             # 5. → 2.
        self.assertIn("3. c", out)             # 2. → 3.

    def test_note_render_html_formats_markdown(self):
        from company.note_channel import md_to_html
        html = md_to_html("# 見出し\n本文**太字**\n\n- 箇条書き\n\n―― ここから有料 ――\n有料")
        self.assertIn("<h1>見出し</h1>", html)
        self.assertIn("<strong>太字</strong>", html)
        self.assertIn("<li>箇条書き</li>", html)
        self.assertIn('class="paid"', html)  # 有料境界が見える
        self.assertNotIn("# 見出し", html)     # Markdown 記号が残らない

    def test_publish_requires_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            # 手動で公開待ち商品を用意
            from company.models import Product
            p = Product(title="T", category="A", status="awaiting_approval")
            c.storage.put("products", p.to_dict())
            apr = c.approvals.request("publish", "x", {"product_id": p.id})
            with self.assertRaises(PermissionError_):
                c.publish(p.id, "https://note.com/x", apr.id)
            c.approvals.approve(apr.id)
            pub = c.publish(p.id, "https://note.com/x", apr.id)
            self.assertEqual(pub.status, "published")
            self.assertEqual(pub.url, "https://note.com/x")

    def test_metrics_evaluate_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            from company.models import Product
            # 成功商品 (高購入率) と 失敗商品 (PVあり購入0)
            win = Product(title="Win", category="A", status="published",
                          published_at="2026-07-01T00:00:00+00:00")
            lose = Product(title="Lose", category="B", status="published",
                           published_at="2026-07-02T00:00:00+00:00")
            c.storage.put("products", win.to_dict())
            c.storage.put("products", lose.to_dict())
            c.record_metrics(win.id, pv=1000, purchases=50, revenue_jpy=5000)
            c.record_metrics(lose.id, pv=800, purchases=0, revenue_jpy=0)

            ev = c.evaluate()
            outcomes = {a["title"]: a["outcome"] for a in ev["actions"]}
            self.assertEqual(outcomes["Win"], "success")
            self.assertEqual(outcomes["Lose"], "fail")

            rep = c.report("2026-07")
            self.assertEqual(rep["summary"]["purchases"], 50)
            self.assertTrue(any(p["title"] == "Win" for p in rep["success_products"]))
            self.assertTrue(any(p["title"] == "Lose" for p in rep["fail_products"]))

    def test_daily_budget_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp, max_tasks_per_day=3)
            with self.assertRaises(BudgetExceeded):
                c.plan_products(5)  # 4タスク/商品なので上限3をすぐ超える


class ExperimentTest(unittest.TestCase):
    def test_retreat_after_zero_purchase_rounds(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp, retreat_zero_purchase_rounds=2)
            from company.models import Product
            # カテゴリーC を2ラウンド 購入0
            for rnd in (1, 2):
                p = Product(title=f"C{rnd}", category="C", experiment_round=rnd,
                            status="published", pv=100, purchases=0)
                c.storage.put("products", p.to_dict())
            self.assertIn("C", c.experiments.retreated_categories())

    def test_memory_query(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            c.memory.add("hypothesis", "副業テーマは売れる", "検索需要が高い", tags=["A"])
            hits = c.memory.query(text="副業")
            self.assertEqual(len(hits), 1)
            self.assertEqual(c.memory.query(kind="hypothesis")[0]["tags"], ["A"])


class DemoSeedTest(unittest.TestCase):
    def test_full_loop_reaches_published_and_evaluated(self):
        from company.seed import seed_demo, DemoRunner
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            c.tasks.runner = DemoRunner()
            out = seed_demo(c)
            # DemoRunner の本文はレビューを通過する → 全商品が公開待ちへ
            self.assertTrue(all(r["status"] == "awaiting_approval" for r in out["planned"]))
            self.assertTrue(all(r["approval_id"] for r in out["planned"]))
            # 承認→公開→実績まで進み、評価に成功/失敗が出る
            self.assertEqual(out["summary"]["published_count"], 5)
            outcomes = {a["outcome"] for a in out["evaluation"]["actions"]}
            self.assertIn("success", outcomes)
            self.assertIn("fail", outcomes)


class DashboardTest(unittest.TestCase):
    def test_render_html(self):
        with tempfile.TemporaryDirectory() as tmp:
            c = make_company(tmp)
            from company import dashboard
            out = dashboard.write(c, str(pathlib.Path(tmp) / "d.html"))
            text = pathlib.Path(out).read_text(encoding="utf-8")
            self.assertIn("<title>", text)
            self.assertIn("経営 KPI", text)


if __name__ == "__main__":
    unittest.main()
