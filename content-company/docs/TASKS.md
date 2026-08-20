# TASKS — Task ワークフロー (§18)

すべての AI 作業を Task として管理する。AI 同士が無秩序に会話する構造にしない。

## ライフサイクル

```
create → doing → review → done
                    └ reject → doing（差し戻し）/ blocked
```

`company/tasks.py` の `TaskManager`:

1. `create(title, agent, task_type, skill=..., input=..., depends_on=...)`
   - Router がモデル Tier と予算レベルを決定（§15, §37）
2. `run(task_id)`
   - **日次スループット上限を確認**（`CostController.check_daily_budget`, 付録A #3）
   - `AgentRunner.run(task_type, input)` を実行
   - コストを計上（tier→units）、成果物を `output` に保存、status=`review`
3. `review(task_id, passed, notes)`
   - pass なら done + `completed_at`、reject なら doing に戻す（Reviewer 差し戻し, §4）

## Task モデル（`models.Task`）

Task ID / 担当Agent / 使用Skill / 予算レベル / 入力 / 実行 / 成果物 /
Reviewer 結果 / model_tier / est_cost_units / parent_id / depends_on。

## パイプラインでの連鎖（§5, §39）

`Company._plan_one()` が 1 商品につき 4 Task を親子で連鎖:

```
research(researcher) → product_plan(cpo) → article_write(writer) → review_final(reviewer)
```

レビュー通過で商品を `awaiting_approval` にし、公開承認（§21）を要求する。
不通過なら `review` に留め Writer へ差し戻す。

## task_type とモデル方針

`company/router.py` の `TASK_PROFILE` が task_type ごとに難易度・重要度・予算を
持つ。新しい task_type を足すときはここに profile を追加する。
