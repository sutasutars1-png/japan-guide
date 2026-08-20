"""コマンドライン入口。

    python -m company plan --n 5
    python -m company status
    python -m company approvals
    python -m company approve <approval_id>
    python -m company publish <product_id> --url https://note.com/... --approval <id>
    python -m company metrics <product_id> --pv 1200 --purchases 30 --revenue 3000
    python -m company evaluate
    python -m company report [--period 2026-07]
    python -m company memory [--query ...] [--kind ...]
    python -m company dashboard [--out dashboard.html]
    python -m company backup [--out backups/snapshot]
"""

from __future__ import annotations

import argparse
import json
import sys

from .company import Company


def _print(obj: object) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="company", description="AIコンテンツ販売会社 OS")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan", help="N商品を企画→記事→レビュー→公開待ちまで")
    p_plan.add_argument("--n", type=int, default=5)
    p_plan.add_argument("--month", default=None)

    sub.add_parser("status", help="経営KPIサマリ")
    sub.add_parser("approvals", help="承認待ち一覧 (§21)")

    p_ap = sub.add_parser("approve", help="承認する")
    p_ap.add_argument("approval_id")
    p_ap.add_argument("--note", default="")

    p_rej = sub.add_parser("reject", help="却下する")
    p_rej.add_argument("approval_id")
    p_rej.add_argument("--note", default="")

    p_pub = sub.add_parser("publish", help="承認済み商品をnote公開として記録")
    p_pub.add_argument("product_id")
    p_pub.add_argument("--url", required=True)
    p_pub.add_argument("--approval", required=True)

    p_met = sub.add_parser("metrics", help="販売/PVデータを入力 (§30-31, 付録A #2)")
    p_met.add_argument("product_id")
    p_met.add_argument("--pv", type=int, default=0)
    p_met.add_argument("--purchases", type=int, default=0)
    p_met.add_argument("--revenue", type=int, default=0)
    p_met.add_argument("--likes", type=int, default=0)
    p_met.add_argument("--rating", type=float, default=None)

    sub.add_parser("evaluate", help="成功/失敗の評価と次アクション (§31)")

    p_rep = sub.add_parser("report", help="「先月どうだった?」レポート (§39)")
    p_rep.add_argument("--period", default=None, help="例: 2026-07")

    p_mem = sub.add_parser("memory", help="Company Memory 検索 (§7)")
    p_mem.add_argument("--query", default=None)
    p_mem.add_argument("--kind", default=None)
    p_mem.add_argument("--n", type=int, default=20)

    p_dash = sub.add_parser("dashboard", help="ダッシュボードHTMLを生成 (§25)")
    p_dash.add_argument("--out", default="dashboard.html")

    p_bak = sub.add_parser("backup", help="data/ をzipバックアップ (付録A #6)")
    p_bak.add_argument("--out", default="backups/snapshot")

    sub.add_parser("demo", help="架空データで全ループを実演 (企画→承認→公開→実績→評価)")

    args = ap.parse_args(argv)
    c = Company()

    if args.cmd == "plan":
        res = c.plan_products(args.n, month=args.month)
        _print(res)
        print(f"\n{len(res)}商品を公開待ちまで進めました。"
              f"承認は `python -m company approvals` で確認。", file=sys.stderr)
    elif args.cmd == "status":
        _print(c.kpi.summary())
    elif args.cmd == "approvals":
        _print(c.approvals.pending())
    elif args.cmd == "approve":
        _print(c.approvals.approve(args.approval_id, note=args.note).to_dict())
    elif args.cmd == "reject":
        _print(c.approvals.reject(args.approval_id, note=args.note).to_dict())
    elif args.cmd == "publish":
        _print(c.publish(args.product_id, args.url, args.approval).to_dict())
    elif args.cmd == "metrics":
        _print(c.record_metrics(
            args.product_id, pv=args.pv, purchases=args.purchases,
            revenue_jpy=args.revenue, likes=args.likes, rating=args.rating,
        ).to_dict())
    elif args.cmd == "evaluate":
        _print(c.evaluate())
    elif args.cmd == "report":
        _print(c.report(args.period))
    elif args.cmd == "memory":
        if args.query or args.kind:
            _print(c.memory.query(text=args.query, kind=args.kind))
        else:
            _print(c.memory.recent(args.n))
    elif args.cmd == "dashboard":
        from . import dashboard
        out = dashboard.write(c, args.out)
        print(f"ダッシュボードを生成: {out}")
    elif args.cmd == "backup":
        path = c.storage.snapshot(args.out)
        print(f"バックアップ作成: {path}")
    elif args.cmd == "demo":
        from .seed import seed_demo, DemoRunner
        c.tasks.runner = DemoRunner()
        out = seed_demo(c)
        _print(out["summary"])
        print("\n架空データで全ループを実演しました。"
              "`python -m company dashboard` で可視化できます。", file=sys.stderr)
    else:  # pragma: no cover
        ap.print_help()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
