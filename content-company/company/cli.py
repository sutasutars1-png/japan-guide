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
    p_plan.add_argument("--llm", action="store_true",
                        help="Claude Code CLI で実文章を生成 (§42)。未ログイン/未検出時は雛形")

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

    # Skill 自己改善 (§20)
    p_skill = sub.add_parser("skill", help="Skill 自己改善ループ (§20)")
    ssub = p_skill.add_subparsers(dest="skill_cmd", required=True)
    ssub.add_parser("list", help="全 Skill の現行版一覧")
    sp_ver = ssub.add_parser("versions", help="ある Skill のバージョン履歴")
    sp_ver.add_argument("key")
    sp_prop = ssub.add_parser("propose", help="改善案を新バージョンとして提案")
    sp_prop.add_argument("key")
    sp_prop.add_argument("--purpose", default=None)
    sp_prop.add_argument("--success", default=None)
    sp_prop.add_argument("--guidance", default=None)
    sp_prop.add_argument("--forbidden", default=None, help="カンマ区切り")
    sp_eval = ssub.add_parser("evaluate", help="改善効果を評価（旧版比較）")
    sp_eval.add_argument("key")
    sp_eval.add_argument("version", type=int)
    sp_req = ssub.add_parser("request-adoption", help="採用の承認を申請")
    sp_req.add_argument("key")
    sp_req.add_argument("version", type=int)
    sp_adopt = ssub.add_parser("adopt", help="承認済みバージョンを採用（旧版は退役）")
    sp_adopt.add_argument("key")
    sp_adopt.add_argument("version", type=int)
    sp_adopt.add_argument("--approval", required=True)

    # note 連携 (§22, 付録A #2)
    p_note = sub.add_parser("note", help="note 連携（公開用エクスポート / 実績CSV取込）")
    nsub = p_note.add_subparsers(dest="note_cmd", required=True)
    np_exp = nsub.add_parser("export", help="承認済み記事を note 公開用 Markdown に書き出す")
    np_exp.add_argument("product_id")
    np_imp = nsub.add_parser("import", help="note の売上/アクセス CSV を取り込む")
    np_imp.add_argument("csv", help="CSV ファイルパス")
    np_imp.add_argument("--dry-run", action="store_true")
    nsub.add_parser("template", help="取り込み用 CSV のサンプル列を表示")

    # X / TikTok チャネル (§32, §33)
    p_soc = sub.add_parser("social", help="X / TikTok 下書き（投稿は人間, §32）")
    ssub2 = p_soc.add_subparsers(dest="social_cmd", required=True)
    sp_d = ssub2.add_parser("draft", help="下書きを生成（承認待ちに追加）")
    sp_d.add_argument("channel", choices=["x", "tiktok"])
    sp_d.add_argument("product_id")
    sp_d.add_argument("--llm", action="store_true")
    sp_l = ssub2.add_parser("list", help="下書き一覧")
    sp_l.add_argument("--channel", default=None)
    sp_p = ssub2.add_parser("posted", help="人間が投稿した URL を記録（要承認）")
    sp_p.add_argument("social_id")
    sp_p.add_argument("--url", required=True)

    # 定期スケジュール（既定オフ）
    p_sch = sub.add_parser("schedule", help="定期スケジュール（既定オフ・安全ジョブのみ）")
    schsub = p_sch.add_subparsers(dest="sch_cmd", required=True)
    schsub.add_parser("status", help="状態表示")
    sc_m = schsub.add_parser("master", help="マスターのオン/オフ")
    sc_m.add_argument("state", choices=["on", "off"])
    sc_j = schsub.add_parser("job", help="ジョブのオン/オフ・間隔設定")
    sc_j.add_argument("name", choices=["evaluate", "note_import", "social_draft"])
    sc_j.add_argument("--on", dest="on", action="store_true")
    sc_j.add_argument("--off", dest="off", action="store_true")
    sc_j.add_argument("--interval", type=int, default=None, help="分")
    sc_r = schsub.add_parser("run", help="ジョブを今すぐ実行")
    sc_r.add_argument("name", choices=["evaluate", "note_import", "social_draft"])

    # 設定 (§23, §36)
    p_cfg = sub.add_parser("config", help="運用パラメータの表示 / 変更")
    cfgsub = p_cfg.add_subparsers(dest="cfg_cmd", required=True)
    cfgsub.add_parser("show", help="現在の編集可能な設定を表示")
    cf_s = cfgsub.add_parser("set", help="設定を変更（例: set x_enabled true）")
    cf_s.add_argument("key")
    cf_s.add_argument("value")

    p_gui = sub.add_parser("gui", help="ローカル Web GUI を起動")
    p_gui.add_argument("--port", type=int, default=8787)
    p_gui.add_argument("--host", default="127.0.0.1")
    p_gui.add_argument("--llm", action="store_true", help="実 LLM 生成を有効化")

    args = ap.parse_args(argv)
    c = Company()

    if args.cmd == "plan":
        if getattr(args, "llm", False):
            if c.enable_llm():
                print("実 LLM (Claude Code CLI) を有効化しました。", file=sys.stderr)
            else:
                print("claude CLI 未検出。雛形 (TemplateRunner) で継続します。", file=sys.stderr)
        res = c.plan_products(args.n, month=args.month)
        _print(res)
        print(f"\n{len(res)}商品を進めました。承認待ちは "
              f"`python -m company approvals` で確認。", file=sys.stderr)
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
    elif args.cmd == "skill":
        lab = c.skills_lab
        if args.skill_cmd == "list":
            _print(lab.all_current())
        elif args.skill_cmd == "versions":
            _print(lab.versions(args.key))
        elif args.skill_cmd == "propose":
            forb = args.forbidden.split(",") if args.forbidden else None
            _print(lab.propose(args.key, purpose=args.purpose, success=args.success,
                               guidance=args.guidance, forbidden=forb))
        elif args.skill_cmd == "evaluate":
            _print(lab.evaluate(args.key, args.version))
        elif args.skill_cmd == "request-adoption":
            _print(lab.request_adoption(args.key, args.version))
        elif args.skill_cmd == "adopt":
            _print(lab.adopt(args.key, args.version, args.approval))
    elif args.cmd == "note":
        if args.note_cmd == "export":
            r = c.note_export.export(args.product_id)
            print(f"note公開用に書き出しました: {r['path']}")
            print(f"タイトル: {r['title']} / {r['price_jpy']}円 / "
                  f"{' '.join('#'+t for t in r['hashtags'])}", file=sys.stderr)
        elif args.note_cmd == "import":
            _print(c.note_import.import_csv(args.csv, dry_run=args.dry_run))
        elif args.note_cmd == "template":
            from .note_channel import NoteImporter
            print(NoteImporter.template_csv())
    elif args.cmd == "social":
        if args.social_cmd == "draft":
            if getattr(args, "llm", False):
                c.enable_llm()
            _print(c.social.draft(args.channel, args.product_id))
        elif args.social_cmd == "list":
            _print(c.social.list(args.channel))
        elif args.social_cmd == "posted":
            _print(c.social.mark_posted(args.social_id, args.url).to_dict())
    elif args.cmd == "schedule":
        if args.sch_cmd == "status":
            _print(c.scheduler.get_state())
        elif args.sch_cmd == "master":
            _print(c.scheduler.set_enabled(args.state == "on"))
        elif args.sch_cmd == "job":
            enabled = True if args.on else (False if args.off else None)
            _print(c.scheduler.set_job(args.name, enabled=enabled,
                                       interval_min=args.interval))
        elif args.sch_cmd == "run":
            _print(c.scheduler.run_job(args.name))
    elif args.cmd == "config":
        if args.cfg_cmd == "show":
            _print(c.config.editable_snapshot())
        elif args.cfg_cmd == "set":
            _print(c.update_config({args.key: args.value}))
    elif args.cmd == "gui":
        from .webgui import serve
        serve(c, host=args.host, port=args.port, llm=args.llm)
    else:  # pragma: no cover
        ap.print_help()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
