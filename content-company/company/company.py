"""Company — AI会社 OS のファサード。

各コンポーネント (Memory / Router / Cost / Approval / Tasks / KPI / Experiments)
を1つに束ね、上位 (CLI / ダッシュボード / 将来のUI) から使う入口にする。

MVP 成功条件 (§39) の 2 つの振る舞いをここに実装する:

* ``plan_products(n)`` — 「今月noteで売れる商品を N 個企画して」
  → 調査→企画→記事→レビュー→公開待ち まで自律で進める。
* ``report(period)`` — 「先月の商品はどうだった?」
  → 売上/PV/購入率/成功/失敗/原因/次回改善案 を返す。
"""

from __future__ import annotations

import difflib
from typing import Any

from . import agents as agents_mod
from . import ids
from .approval import ApprovalGateway
from .config import Config, load_config
from .cost import CostController
from .experiments import DEFAULT_CATEGORIES, ExperimentDesign
from .kpi import KPI
from .memory import CompanyMemory
from . import quality as quality_mod
from .models import Decision, Hypothesis, Product
from .router import ModelRouter
from .runner import AgentRunner
from .skill_improve import SkillLab
from .storage import Storage
from .tasks import TaskManager


class Company:
    def __init__(self, config: Config | None = None, runner: AgentRunner | None = None):
        self.config = config or load_config()
        self.storage = Storage(self.config.data_dir)
        self.config.load_overlay()  # data_dir に保存済みの GUI 設定を反映
        self.memory = CompanyMemory(self.storage)
        self.router = ModelRouter()
        self.cost = CostController(self.storage, self.config)
        self.approvals = ApprovalGateway(self.storage)
        self.tasks = TaskManager(self.storage, self.router, self.cost, runner)
        self.kpi = KPI(self.storage, self.config, self.cost)
        self.experiments = ExperimentDesign(self.storage, self.config)
        self.skills_lab = SkillLab(self.storage, self.approvals, self.memory)
        from .note_channel import NoteExporter, NoteImporter
        from .social import SocialChannel
        from .scheduler import JobScheduler
        self.note_export = NoteExporter(self)
        self.note_import = NoteImporter(self)
        self.social = SocialChannel(self)
        self.scheduler = JobScheduler(self)

    # ---- 設定変更（GUI/CLI からの安全な更新, §21 config） ----------------

    def update_config(self, changes: dict[str, Any]) -> dict[str, Any]:
        applied = self.config.update(changes)
        self.config.persist()
        return {"applied": applied, "config": self.config.editable_snapshot()}

    # ---- ランナー切り替え -------------------------------------------------

    def enable_llm(self, **kwargs: Any) -> bool:
        """タスク実行を実 LLM (Claude Code CLI) に切り替える (§42)。

        現行採用版の Skill 定義 (§20) をプロンプトに反映する。CLI が無ければ
        False を返し、既定の TemplateRunner のまま。
        """
        from .runner_claude import ClaudeRunner

        if ClaudeRunner.available(kwargs.get("claude_bin", "claude")) is None:
            return False
        self.tasks.runner = ClaudeRunner(skill_text=self.skills_lab.text, **kwargs)
        return True

    def disable_llm(self) -> None:
        """タスク実行を既定の雛形ランナー (TemplateRunner) に戻す。

        GUI の「実LLM生成」チェックを外したときに、同一セッション内でも
        雛形生成へ戻せるようにする（enable_llm と対称）。
        """
        from .runner import TemplateRunner

        self.tasks.runner = TemplateRunner()

    # ---- 意思決定ログ -----------------------------------------------------

    def log_decision(
        self, context: str, decision: str, rationale: str, *, actor: str = "ceo",
        options: list[str] | None = None, related: list[str] | None = None,
    ) -> Decision:
        dec = Decision(
            actor=actor, context=context, options=options or [], decision=decision,
            rationale=rationale, related=related or [],
        )
        self.storage.append("decisions", dec.to_dict())
        self.memory.add("decision", context, f"{decision}\n根拠: {rationale}",
                        related=related or [])
        return dec

    # ---- 現在のラウンド番号 ----------------------------------------------

    def current_round(self) -> int:
        rounds = [int(p.get("experiment_round", 0)) for p in self.storage.all("products")]
        return (max(rounds) + 1) if rounds else 1

    # ==================================================================
    #  MVP パイプライン (§39): 企画 → 記事 → レビュー → 公開待ち
    # ==================================================================

    def plan_products(
        self, n: int = 5, *, month: str | None = None, categories: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        cats = categories or DEFAULT_CATEGORIES
        round_no = self.current_round()

        # CEO: 実験配分を決定 (§4, §11) → 判断根拠を保存 (§44)
        # 既存の作成数を見て手薄なカテゴリーを優先（n=1 でも A に偏らない）。
        alloc = self.experiments.next_categories(n)
        while len(alloc) < n:  # 念のための穴埋め
            alloc.append(list(cats)[len(alloc) % len(cats)])
        self.log_decision(
            context=f"Round {round_no}: {n}商品の企画方針",
            decision=f"カテゴリー配分 {alloc}",
            rationale="Round1は均等に需要を探索、以降は購入実績上位へ重点配分 (§11)",
            options=["均等配分", "上位集中"],
        )

        # 各商品は独立して企画する。1件が失敗（タスク上限/LLMエラー等）しても
        # 残りは続行し、成功分は必ず反映する（1件のせいで全滅させない）。
        results: list[dict[str, Any]] = []
        for idx, cat in enumerate(alloc, start=1):
            theme = cats.get(cat, cat)
            try:
                results.append(self._plan_one(cat, theme, round_no))
            except Exception as exc:  # noqa: BLE001
                self.memory.add("failure", f"企画失敗: {theme}", str(exc)[:200])
                results.append({"category": cat, "theme": theme,
                                "status": "error", "error": str(exc)[:200]})
        return results

    # ---- 重複回避 (付録A #5) ---------------------------------------------

    @staticmethod
    def _article_signature(art: dict) -> str:
        """記事の指紋（タイトル＋見出し＋本文冒頭）。類似度計算に使う。"""
        parts = [str(art.get("title", ""))]
        outline = art.get("outline")
        if isinstance(outline, list):
            parts += [str(x) for x in outline]
        parts.append((str(art.get("body_markdown", "")))[:400])
        return " ".join(parts).lower()

    def _existing_signatures(self, exclude_pid: str | None) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for a in self.storage.all("articles"):
            if exclude_pid and a.get("product_id") == exclude_pid:
                continue
            title = a.get("title") or a.get("product_id", "")
            out.append((title, self._article_signature(a)))
        return out

    def _max_similarity(self, sig: str, existing: list[tuple[str, str]]) -> tuple[float, str]:
        best = (0.0, "")
        for title, esig in existing:
            r = difflib.SequenceMatcher(None, sig, esig).ratio()
            if r > best[0]:
                best = (r, title)
        return best

    # ---- 学習ループ (§20): 差し戻し理由を教訓化して次に活かす ------------

    # 却下理由の分類 → 恒久的な改善ガイドライン。
    _LESSON_RULES: tuple[tuple[tuple[str, ...], str, str], ...] = (
        (("具体例", "事例", "例が不足"), "examples",
         "再現できる具体例を最低3件、数値・固有名詞・手順つきで入れる（抽象論で終わらせない）"),
        (("短い", "薄い", "分量", "文字"), "depth",
         "価格に見合う分量と具体性を確保し、各主張に根拠・手順・数値を添える"),
        (("類似", "重複", "似て"), "dedup",
         "既存記事と切り口・見出し・具体例を変えて差別化する"),
        (("プレースホルダ", "見出し", "体裁", "空のリンク"), "format",
         "プレースホルダを残さず、見出し構造を整え、体裁を崩さない"),
        (("完結", "予告", "続きは"), "complete",
         "この記事だけで悩みを完全解決し、予告・要約で終わらせない"),
        (("断定", "誇張", "景表", "優良誤認", "出典", "数値"), "compliance",
         "効果・数値は断定しない。出典不明の具体数値（例『平均10〜15分』）は削除するか"
         "『個人差があります』等の留保と幅表現（『数分程度』等）に必ず言い換える"),
    )

    def _classify_reject(self, notes: str) -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        for keys, rkey, guide in self._LESSON_RULES:
            if any(k in notes for k in keys):
                out.append((rkey, guide))
        return out

    def _active_lessons(self, skill: str, limit: int = 6) -> list[str]:
        recs = [r for r in self.storage.find("lessons", skill=skill) if r.get("active")]
        recs.sort(key=lambda r: r.get("count", 0), reverse=True)
        return [r["guideline"] for r in recs[:limit]]

    def _learn_from_reject(self, skill: str, notes: str) -> None:
        """差し戻し理由を教訓として蓄積。閾値に達したら以後必ず反映＋改善提案。"""
        if not notes:
            return
        for rkey, guide in self._classify_reject(notes):
            lid = f"{skill}:{rkey}"
            rec = self.storage.get("lessons", lid) or {
                "id": lid, "skill": skill, "key": rkey, "guideline": guide,
                "count": 0, "active": False}
            rec["count"] = int(rec.get("count", 0)) + 1
            rec["guideline"] = guide
            newly_active = (not rec.get("active")) and \
                rec["count"] >= self.config.lesson_threshold
            if rec["count"] >= self.config.lesson_threshold:
                rec["active"] = True
            self.storage.put("lessons", rec)
            if newly_active:
                self.memory.add("lesson", f"教訓を獲得: {skill}", guide, tags=[skill])
                self._auto_propose_skill(skill)

    def _auto_propose_skill(self, skill: str) -> None:
        """獲得した教訓を Skill 改善案として自動起票し、承認待ちに出す (§20)。"""
        try:
            lessons = self._active_lessons(skill)
            if not lessons:
                return
            guidance = " / ".join(lessons)
            # 既に現行版に反映済みなら不要。
            try:
                if guidance.strip() and guidance.strip() in \
                        (self.skills_lab.current(skill).get("guidance") or ""):
                    return
            except KeyError:
                pass
            # 既にこの Skill の採用提案が承認待ちなら二重起票しない
            # （却下・未対応で不備が続く場合は再度上がる）。
            for a in self.approvals.pending():
                if a.get("kind") == "config" and \
                        a.get("payload", {}).get("skill") == skill:
                    return
            cand = self.skills_lab.propose(skill, guidance=guidance, author="growth")
            self.skills_lab.request_adoption(skill, cand["version"])
            self.log_decision(
                context=f"Skill 自動改善: {skill}",
                decision=f"教訓を反映した v{cand['version']} を提案・採用申請",
                rationale=guidance, actor="growth", options=["現状維持", "改善版を採用"])
        except Exception:  # noqa: BLE001
            pass

    def _performance_hints(self, limit: int = 8) -> dict[str, list[str]]:
        """実績評価(§31)の結果を次の企画・執筆へ渡す（B: 学習の反映）。

        evaluate() が付けた outcome を読み、売れた/外した切り口を LLM に渡して
        成功パターンへ寄せ、失敗パターンを避けさせる。
        """
        win: list[str] = []
        lose: list[str] = []
        for p in self.storage.all("products"):
            label = f"{p.get('title')}（{p.get('theme', '')}）"
            oc = p.get("outcome")
            if oc == "success":
                win.append(label)
            elif oc == "fail":
                lose.append(label)
        return {"winning_angles": win[-limit:], "losing_angles": lose[-limit:]}

    def _avoid_list(self, exclude_pid: str | None = None, limit: int = 15) -> list[str]:
        """既に作った切り口の一覧（タイトル（テーマ））。LLM に差別化を促す入力。"""
        seen: list[str] = []
        for p in self.storage.all("products"):
            if exclude_pid and p.get("id") == exclude_pid:
                continue
            t = p.get("title")
            if t:
                seen.append(f"{t}（{p.get('theme', '')}）")
        return seen[-limit:]

    def _plan_one(self, category: str, theme: str, round_no: int) -> dict[str, Any]:
        # 1) Researcher: 市場調査 (§4)
        t_res = self.tasks.create(
            f"調査: {theme}", agent="researcher", task_type="research",
            skill="market-research", input={"theme": theme, "category": category},
        )
        self.tasks.run(t_res.id)
        self.tasks.review(t_res.id, True)
        research = self.tasks.get(t_res.id).output  # type: ignore[union-attr]
        self.storage.put("research", {"id": ids.new_id("res"), "category": category,
                                      "theme": theme, **research})

        # 2) CPO: 商品企画 (§13) + 仮説 (§9)
        t_plan = self.tasks.create(
            f"企画: {theme}", agent="cpo", task_type="product_plan",
            skill="product-planning", parent_id=t_res.id,
            input={"theme": theme, "category": category,
                   "price_jpy": self.config.initial_price_jpy, "research": research,
                   "avoid_similar": self._avoid_list(),
                   "performance_hints": self._performance_hints(),
                   "lessons": self._active_lessons("product-planning")},
        )
        self.tasks.run(t_plan.id)
        self.tasks.review(t_plan.id, True)
        plan = self.tasks.get(t_plan.id).output  # type: ignore[union-attr]

        hyp = Hypothesis(
            statement=f"{theme} は {category} カテゴリーで購入される",
            rationale=plan.get("why_sells", ""), action=f"{self.config.initial_price_jpy}円商品を投入",
            kpi="購入率・購入数", category=category, round=round_no,
        )
        self.storage.put("hypotheses", hyp.to_dict())
        self.memory.add("hypothesis", hyp.statement, hyp.rationale,
                        tags=[category], related=[hyp.id])

        product = Product(
            title=plan.get("product_name", theme), theme=theme, category=category,
            target=plan.get("target", ""), price_jpy=self.config.initial_price_jpy,
            status="writing", hypothesis_id=hyp.id, experiment_round=round_no,
        )
        hyp.product_ids.append(product.id)
        self.storage.put("hypotheses", hyp.to_dict())

        # 3-4) Writer → Reviewer。reject なら指摘を反映して自動再執筆 (§4)。
        #      上限は config.max_rewrites 回。実 LLM 生成時のみ再執筆する
        #      （雛形は書き直しても骨格のままで意味がないため）。
        article, review, rewrites = self._write_and_review(product, plan, t_plan.id)
        passed = review.get("verdict") == "pass"
        article_id = ids.new_id("art")
        self.storage.put("articles", {"id": article_id, "product_id": product.id,
                                      "rewrites": rewrites, **article})

        # 5) 公開待ち or 差し戻し
        approval_id = None
        if passed:
            product.status = "awaiting_approval"
            apr = self.approvals.request(
                "publish", f"note公開の承認待ち: {product.title}",
                {"product_id": product.id, "article_id": article_id},
                requested_by="reviewer",
            )
            approval_id = apr.id
        else:
            product.status = "review"  # Writerへ差し戻し (§4)

        self.storage.put("products", product.to_dict())
        self.memory.add("product", f"企画: {product.title}",
                        f"カテゴリー{category} / {product.status}", tags=[category],
                        related=[product.id])

        return {
            "product_id": product.id, "title": product.title, "category": category,
            "status": product.status, "hypothesis_id": hyp.id,
            "approval_id": approval_id, "plan": plan, "review": review,
            "rewrites": rewrites,
        }

    def _write_and_review(self, product: Product, plan: dict, parent_id: str,
                          *, seed_feedback: str = "", seed_prev_body: str = "",
                          human: bool = False):
        """執筆→レビューを行い、reject なら自動再執筆する (§4)。

        seed_feedback / seed_prev_body を渡すと、その内容を初回の執筆に反映する
        （人間の修正依頼を起点に、満足するまでループさせるため）。human=True の
        ときは人間の指示を毎回保持し、レビュアーの直近指摘を足して回す。
        Returns (article, review, rewrites)。rewrites は再執筆回数。
        """
        human_note = (seed_feedback or "").strip()
        feedback = human_note
        prev_body = seed_prev_body or ""
        article: dict = {}
        review: dict = {}
        rewrites = 0
        existing = self._existing_signatures(exclude_pid=product.id)
        avoid = self._avoid_list(exclude_pid=product.id)
        hints = self._performance_hints()
        price_req = quality_mod.price_requirement_text(product.price_jpy)
        # 初回 + 最大 max_rewrites 回の書き直し
        for attempt in range(self.config.max_rewrites + 1):
            w_input: dict = {"plan": plan, "avoid_similar": avoid,
                             "performance_hints": hints, "price_requirement": price_req,
                             "lessons": self._active_lessons("article-writing")}
            if feedback:
                w_input["feedback"] = feedback
                w_input["previous_body"] = prev_body
            label = ("修正依頼(人間)" if human else "執筆") if attempt == 0 \
                else (f"再執筆{attempt}" + ("(人間依頼)" if human else ""))
            t_write = self.tasks.create(
                f"{label}: {product.title}",
                agent="writer", task_type="article_write",
                skill="article-writing", parent_id=parent_id, input=w_input,
            )
            self.tasks.run(t_write.id)
            self.tasks.review(t_write.id, True)
            article = self.tasks.get(t_write.id).output  # type: ignore[union-attr]

            t_review = self.tasks.create(
                f"レビュー: {product.title}", agent="reviewer",
                task_type="review_final", skill="quality-review",
                parent_id=t_write.id, input={"article": article},
            )
            self.tasks.run(t_review.id)
            review = self.tasks.get(t_review.id).output  # type: ignore[union-attr]
            passed = review.get("verdict") == "pass"
            # 以降の自動ガードは実 LLM 記事のみ対象（雛形/デモは対象外）。
            if passed and article.get("_llm"):
                # 体裁(C) + 価格連動要件(A): 崩れ・薄さを差し戻す (付録A #4-5)
                q_issues = quality_mod.quality_issues(article, product.price_jpy)
                if q_issues:
                    passed = False
                    review = {**review, "verdict": "reject", "quality_issues": q_issues,
                              "notes": (review.get("notes", "") + " / 品質差し戻し: "
                                        + " / ".join(q_issues)).strip()}
                # 重複ガード(付録A #5): 既存記事と似すぎたら切り口を変えさせる
                elif existing:
                    sim, sim_title = self._max_similarity(
                        self._article_signature(article), existing)
                    if sim >= self.config.similarity_threshold:
                        passed = False
                        review = {**review, "verdict": "reject",
                                  "similar_to": sim_title, "similarity": round(sim, 3),
                                  "notes": (review.get("notes", "")
                                            + f" / 既存記事『{sim_title}』と類似度が高い"
                                            f"({sim:.0%})。切り口・見出し・具体例を"
                                            "変えて差別化すること。").strip()}
            self.tasks.review(t_review.id, passed, notes=review.get("notes", ""))
            self.memory.add(
                "review", f"レビュー: {product.title}"
                + (f" (再執筆{attempt})" if attempt else ""),
                review.get("notes", ""), related=[product.id])

            if not passed:
                # 差し戻し理由を教訓化（同じ失敗を繰り返さないよう学習, §20）。
                self._learn_from_reject("article-writing", review.get("notes", ""))
            if passed:
                break
            # 再執筆は「実 LLM が書いた記事」に対してのみ意味がある。
            if not article.get("_llm"):
                break
            if attempt >= self.config.max_rewrites:
                self.memory.add(
                    "failure", f"再執筆上限到達: {product.title}",
                    f"{self.config.max_rewrites}回改稿しても reject。人間対応へ.",
                    related=[product.id])
                break
            # 人間の指示は毎回保持し、レビュアーの直近指摘を足して次に渡す。
            review_note = review.get("notes", "")
            feedback = (f"{human_note} / 直近レビュー指摘: {review_note}"
                        if human_note else review_note)
            prev_body = article.get("body_markdown", "")
            rewrites += 1
        return article, review, rewrites

    # ---- システム改修提案 (§20 メタ改善): AIは提案のみ・実装は人間 --------

    def propose_system_improvements(self, *, use_llm: bool = False) -> dict:
        """売上を上げるためのシステム改修案を生成して起票する（重複は除外）。

        決定論ヒューリスティック＋（任意で）Growth エージェントの LLM 提案。
        いずれも『提案』であり、コードの自動改変はしない（人間が採否）。
        """
        from . import system_improve

        candidates = system_improve.heuristic_proposals(self)
        if use_llm:
            candidates += self._llm_system_proposals()
        added = 0
        for c in candidates:
            if self.storage.get("improvements", c["id"]) is None:
                self.storage.put("improvements", c)
                added += 1
        self.memory.add("system", "システム改修提案を生成",
                        f"{added}件を新規起票", tags=["improvement"])
        return {"added": added, "total": len(self.storage.all("improvements"))}

    def _llm_system_proposals(self) -> list[dict]:
        from . import system_improve
        try:
            summary = {"kpi": self.kpi.summary(),
                       "patterns": self.kpi.patterns(),
                       "lessons": [r.get("guideline") for r in
                                   self.storage.all("lessons") if r.get("active")]}
            t = self.tasks.create(
                "システム改修提案", agent="growth", task_type="system_improve",
                skill="growth-strategy", input={"summary": summary})
            self.tasks.run(t.id)
            out = self.tasks.get(t.id).output or {}
            props = out.get("proposals") or []
            result = []
            for p in props:
                if not isinstance(p, dict) or not p.get("title"):
                    continue
                result.append({
                    "id": system_improve.slug(str(p["title"])),
                    "title": str(p.get("title"))[:120],
                    "problem": str(p.get("problem", ""))[:400],
                    "hypothesis": str(p.get("hypothesis", ""))[:400],
                    "expected_effect": str(p.get("expected_effect", ""))[:200],
                    "category": str(p.get("category", "ux"))[:20],
                    "effort": str(p.get("effort", "M"))[:2],
                    "source": "llm", "status": "new", "created_at": ids.now_iso()})
            return result
        except Exception:  # noqa: BLE001
            return []

    def set_improvement_status(self, imp_id: str, status: str) -> dict:
        rec = self.storage.get("improvements", imp_id)
        if rec is None:
            raise KeyError(imp_id)
        if status not in ("new", "accepted", "rejected", "done"):
            raise ValueError(status)
        rec["status"] = status
        self.storage.put("improvements", rec)
        return rec

    def reset_data(self, *, backup: bool = True) -> dict:
        """台帳データ（商品/記事/タスク/承認/実績など）を初期化する。

        破壊的操作なので、実行前に data/ 全体を zip バックアップする（付録A #6）。
        設定（config.local.json）とスケジュール（schedule.json）は data 直下の
        ファイルなので消さない。GUI からは二重確認の上で呼ぶ。
        """
        import pathlib
        import shutil

        root = pathlib.Path(self.storage.data_dir)
        info: dict = {"backup": None, "cleared": []}
        if backup and root.exists() and any(root.iterdir()):
            stamp = ids.now_iso().replace(":", "").replace("-", "").replace("T", "_")[:15]
            dest = root.parent / f"{root.name}_backup_{stamp}"
            try:
                info["backup"] = str(self.storage.snapshot(dest))
            except Exception:  # noqa: BLE001
                info["backup"] = None
        for sub in sorted(root.iterdir()) if root.exists() else []:
            if not sub.is_dir() or sub.name == "backups":
                continue
            for f in sub.iterdir():
                if f.name == ".gitkeep":
                    continue
                if f.is_file():
                    f.unlink()
                else:
                    shutil.rmtree(f, ignore_errors=True)
            info["cleared"].append(sub.name)
        self.memory.add("system", "データ初期化", f"backup={info['backup']}")
        return info

    def delete_product(self, product_id: str) -> dict:
        """商品と、それに紐づく記事を削除する（§21 delete は要人間確認）。

        GUI からは確認ダイアログを経て呼ぶ。承認・実績データはそのまま残す。
        """
        raw = self.storage.get("products", product_id)
        if raw is None:
            raise KeyError(product_id)
        removed_articles = 0
        for a in self.storage.find("articles", product_id=product_id):
            if self.storage.delete("articles", a["id"]):
                removed_articles += 1
        self.storage.delete("products", product_id)
        self.memory.add("system", "商品削除", raw.get("title", ""), related=[product_id])
        return {"deleted": product_id, "title": raw.get("title"),
                "removed_articles": removed_articles}

    def human_reject_publish(self, approval_id: str, note: str = "") -> dict:
        """人間が公開を却下したときの処理。

        却下コメントを (1) 商品に保存して次の修正依頼で使い、(2) 学習にも回し、
        (3) 商品を review に戻して承認待ちの滞留を解消する。publish 以外の
        承認（Skill採用など）は通常の却下のみ。
        """
        raw = self.storage.get("approvals", approval_id)
        apr = self.approvals.reject(approval_id, note=note)
        note = (note or "").strip()
        if raw and raw.get("kind") == "publish":
            pid = raw.get("payload", {}).get("product_id")
            prod = self.storage.get("products", pid) if pid else None
            if prod:
                prod["status"] = "review"  # 承認待ちから外す（滞留解消）
                if note:
                    prod["pending_feedback"] = note  # 次の修正依頼で使う
                self.storage.put("products", prod)
            if note and pid:
                self._learn_from_reject("article-writing", note)  # 学習にも回す
        return {"approval": apr.to_dict(), "note": note}

    def request_rewrite(self, product_id: str, feedback: str) -> dict:
        """人間の修正依頼を反映して記事を書き直し、再レビューする (§4, §21)。

        修正後は承認をやり直す（前の承認は無効化し、pass すれば新しい承認待ちへ）。
        実 LLM 生成が有効なときに意味を持つ（雛形は書き直しても骨格のまま）。
        """
        raw = self.storage.get("products", product_id)
        if raw is None:
            raise KeyError(product_id)
        product = Product.from_dict(raw)
        arts = self.storage.find("articles", product_id=product_id)
        if not arts:
            raise ValueError(f"記事が見つかりません: {product_id}")
        prev = arts[-1]
        # 指示が空なら、人間の却下コメント（保存済み）を使う。
        feedback = (feedback or "").strip() or str(raw.get("pending_feedback", "")).strip() \
            or "具体例・分量・完結性を高めて改稿する"
        # 古い公開承認が承認待ちに残っていれば閉じる（滞留解消）。
        for a in self.approvals.pending():
            if a.get("kind") == "publish" and \
                    a.get("payload", {}).get("product_id") == product_id:
                self.approvals.reject(a["id"], note="修正依頼により再作成")
        plan = {
            "product_name": product.title, "theme": product.theme,
            "target": product.target, "price_jpy": product.price_jpy,
            "category": product.category,
        }
        # 単発ではなく、満足するまで最大 max_rewrites 回ループさせる（§4）。
        # 人間の指示を毎回保持し、レビュアーの直近指摘を足して改稿する。
        article, review, rewrites = self._write_and_review(
            product, plan, parent_id=None,
            seed_feedback=feedback, seed_prev_body=prev.get("body_markdown", ""),
            human=True)
        passed = review.get("verdict") == "pass"

        article_id = ids.new_id("art")
        self.storage.put("articles", {
            "id": article_id, "product_id": product.id,
            "rewrites": int(prev.get("rewrites", 0)) + rewrites + 1, **article})
        approval_id = None
        if passed:
            product.status = "awaiting_approval"
            apr = self.approvals.request(
                "publish", f"note公開の承認待ち(修正後): {product.title}",
                {"product_id": product.id, "article_id": article_id}, requested_by="writer")
            approval_id = apr.id
        else:
            product.status = "review"
        self.storage.put("products", product.to_dict())
        self.memory.add("rewrite", f"修正依頼を反映: {product.title}（改稿{rewrites + 1}回）",
                        feedback[:200], related=[product.id])
        return {"product_id": product_id, "status": product.status, "passed": passed,
                "rounds": rewrites + 1, "approval_id": approval_id, "review": review,
                "llm": bool(article.get("_llm"))}

    # ---- 公開 (§21, §22): 人間承認後にのみ実行 --------------------------

    def publish(self, product_id: str, url: str, approval_id: str) -> Product:
        self.approvals.guard("publish", approval_id)  # 未承認なら例外
        raw = self.storage.get("products", product_id)
        if raw is None:
            raise KeyError(product_id)
        product = Product.from_dict(raw)
        product.status = "published"
        product.url = url
        product.published_at = ids.now_iso()
        self.storage.put("products", product.to_dict())
        self.memory.add("result", f"公開: {product.title}", url, related=[product_id])
        return product

    def article_for(self, product_id: str) -> dict | None:
        """商品に紐づく最新の記事レコードを返す（本文確認用）。

        雛形/実LLMを問わず、生成された記事本文（body_markdown 等）と
        is_skeleton フラグを GUI/CLI から確認できるようにする。
        """
        arts = self.storage.find("articles", product_id=product_id)
        return arts[-1] if arts else None

    # ---- 実績の取り込み (§30-31, 付録A #2: 当面は手動入力) --------------

    def record_metrics(
        self, product_id: str, *, pv: int = 0, purchases: int = 0,
        revenue_jpy: int = 0, likes: int = 0, source: dict[str, int] | None = None,
        rating: float | None = None,
    ) -> Product:
        raw = self.storage.get("products", product_id)
        if raw is None:
            raise KeyError(product_id)
        product = Product.from_dict(raw)
        product.pv = pv
        product.purchases = purchases
        product.revenue_jpy = revenue_jpy
        product.likes = likes
        if source:
            product.source_breakdown = source
        if rating is not None:
            product.rating = rating
        self.storage.put("products", product.to_dict())
        self.storage.put("analytics", {
            "id": ids.new_id("anl"), "product_id": product_id, "ts": ids.now_iso(),
            "pv": pv, "purchases": purchases, "revenue_jpy": revenue_jpy,
            "conversion_rate": product.conversion_rate,
        })
        return product

    # ==================================================================
    #  分析・改善 (§31, §39 「先月どうだった?」)
    # ==================================================================

    def evaluate(self) -> dict[str, Any]:
        """Analytics → Growth: 成功/失敗の評価と次アクションを決める (§6, §31)。"""
        patterns = self.kpi.patterns()
        actions: list[dict[str, str]] = []

        for p in self.kpi.products():
            if int(p.get("pv", 0)) == 0:
                continue
            conv = float(p.get("conversion_rate", 0))
            pid = p.get("id", "")
            title = p.get("title", "")
            if conv >= self.config.target_conversion_rate and int(p.get("pv", 0)) > 0:
                outcome, action = "success", "成功パターンとして横展開 (§4 商品C)"
                self.memory.add("pattern_success", f"成功: {title}",
                                f"購入率 {conv:.1%}", related=[pid])
            elif int(p.get("pv", 0)) > 0 and p.get("purchases", 0) == 0:
                outcome, action = "fail", "テーマ/タイトル/価格/無料部分を見直し or 撤退検討"
                self.memory.add("pattern_failure", f"未購入: {title}",
                                f"PV {p.get('pv')} / 購入0", related=[pid])
            else:
                outcome, action = "learning", "集客を増やして再評価 (§4 商品B)"
            # 商品レコードに評価を反映
            raw = self.storage.get("products", pid)
            if raw:
                raw["outcome"] = outcome
                raw["improvement"] = action
                self.storage.put("products", raw)
            actions.append({"product_id": pid, "title": title,
                            "outcome": outcome, "next_action": action})

        # 撤退判定 (付録A)
        retreated = self.experiments.retreated_categories()
        if retreated:
            self.log_decision(
                context="撤退基準チェック", decision=f"打ち切り: {retreated}",
                rationale=f"{self.config.retreat_zero_purchase_rounds}ラウンド連続 購入0 (付録A)",
                actor="ceo",
            )

        return {"summary": self.kpi.summary(), "patterns": patterns,
                "actions": actions, "retreated": retreated}

    def report(self, period: str | None = None) -> dict[str, Any]:
        """「先月の商品はどうだった?」への回答 (§39)。"""
        products = self.kpi.products()
        if period:
            products = [p for p in products
                        if str(p.get("published_at") or "").startswith(period)]
        summary = self.kpi.summary()
        winners = [p for p in products if p.get("outcome") == "success"]
        losers = [p for p in products if p.get("outcome") == "fail"]
        return {
            "period": period or "all",
            "summary": summary,
            "top_products": self.kpi.ranking("revenue_jpy", 5),
            "success_products": [{"id": p["id"], "title": p["title"],
                                  "conversion_rate": p.get("conversion_rate")} for p in winners],
            "fail_products": [{"id": p["id"], "title": p["title"],
                               "cause": p.get("improvement", ""),
                               "pv": p.get("pv")} for p in losers],
            "next_improvements": [
                {"id": p["id"], "action": p.get("improvement", "")}
                for p in products if p.get("improvement")
            ],
        }
