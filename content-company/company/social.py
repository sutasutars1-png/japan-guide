"""X / TikTok チャネル (§32, §33)。

ロードマップの初期フェーズに忠実:「AI作成 → 人間確認 → 人間投稿」(§32)。
**このモジュールは外部ネットワークに一切アクセスしない**。AI は投稿の *下書き*
を作るだけで、実際の投稿は人間が行う。自動投稿は「効果と安全性が確認できたら」
段階的に検討する（§32）— それまで API 連携も自動投稿もしない（安全側の既定）。

フロー:
    draft(channel, product_id)  … Marketing が下書き生成 → sns_post 承認を要求(§21)
    人間が承認 → 人間が X/TikTok に投稿 → mark_posted(url) で記録
    record_inflow()             … note への流入を記録（§24 効果測定）
"""

from __future__ import annotations

from typing import Any

from . import ids
from .models import SocialPost

CHANNELS = ("x", "tiktok")
_TASK_TYPE = {"x": "x_post", "tiktok": "tiktok_script"}


class SocialChannel:
    def __init__(self, company):
        self.c = company

    # ---- 下書き生成 (§32 AI作成) -----------------------------------------

    def draft(self, channel: str, product_id: str) -> dict[str, Any]:
        if channel not in CHANNELS:
            raise ValueError(f"未知のチャネル: {channel}（x / tiktok）")
        product = self.c.storage.get("products", product_id)
        if product is None:
            raise KeyError(product_id)

        task = self.c.tasks.create(
            f"{channel}下書き: {product.get('title')}", agent="marketing",
            task_type=_TASK_TYPE[channel],
            skill="x-marketing" if channel == "x" else "tiktok-marketing",
            input={"product": product},
        )
        self.c.tasks.run(task.id)
        self.c.tasks.review(task.id, True)
        content = self.c.tasks.get(task.id).output  # type: ignore[union-attr]

        post = SocialPost(channel=channel, product_id=product_id, content=content)
        # 人間確認のための承認を要求（§32）。承認するまで投稿記録できない。
        apr = self.c.approvals.request(
            "sns_post", f"{channel} 投稿の人間確認: {product.get('title')}",
            {"social_id": post.id, "product_id": product_id, "channel": channel},
            requested_by="marketing",
        )
        post.approval_id = apr.id
        self.c.storage.put("social", post.to_dict())
        self.c.memory.add("note", f"{channel}下書き作成: {product.get('title')}",
                          "", tags=[channel], related=[product_id])
        return {"social_id": post.id, "channel": channel, "product_id": product_id,
                "approval_id": apr.id, "status": post.status, "content": content}

    # ---- 投稿記録 (§32 人間投稿) -----------------------------------------

    def mark_posted(self, social_id: str, url: str) -> SocialPost:
        """人間が投稿した後に URL を記録する。承認済みでなければ拒否（§21, §32）。"""
        raw = self.c.storage.get("social", social_id)
        if raw is None:
            raise KeyError(social_id)
        post = SocialPost.from_dict(raw)
        # 人間確認（sns_post 承認）を通していなければ投稿記録させない。
        self.c.approvals.guard("sns_post", post.approval_id)
        post.status = "posted"
        post.url = url
        post.posted_at = ids.now_iso()
        self.c.storage.put("social", post.to_dict())
        self.c.memory.add("customer", f"{post.channel}投稿: {url}",
                          "", tags=[post.channel], related=[post.product_id])
        return post

    def record_inflow(self, social_id: str, inflow: int) -> SocialPost:
        raw = self.c.storage.get("social", social_id)
        if raw is None:
            raise KeyError(social_id)
        post = SocialPost.from_dict(raw)
        post.inflow = int(inflow)
        self.c.storage.put("social", post.to_dict())
        return post

    # ---- 参照 -------------------------------------------------------------

    def list(self, channel: str | None = None, status: str | None = None) -> list[dict]:
        rows = self.c.storage.all("social")
        if channel:
            rows = [r for r in rows if r.get("channel") == channel]
        if status:
            rows = [r for r in rows if r.get("status") == status]
        return rows

    def has_draft(self, channel: str, product_id: str) -> bool:
        return any(r.get("channel") == channel and r.get("product_id") == product_id
                   for r in self.c.storage.all("social"))
