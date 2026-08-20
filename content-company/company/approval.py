"""Human Approval Gateway & Permission (§3.2, §21)。

AI が重要な外部操作を勝手に実行しない。以下は必ず人間承認を通す:

    外部公開 / アカウント操作 / APIキー / 支払い / 削除 / 大量投稿 /
    重要な設定変更

「人間は『記事を書く』のではなく『公開してよいか』を判断する」(§21)。
"""

from __future__ import annotations

from . import ids
from .models import Approval
from .storage import Storage

# 人間承認が必須の操作種別 (§3.2)。
SENSITIVE_OPERATIONS = {
    "publish",  # 外部公開
    "account",  # アカウント操作
    "api_key",  # APIキー
    "payment",  # 支払い
    "delete",  # 削除
    "bulk_post",  # 大量投稿
    "sns_post",  # SNS投稿（X/TikTok）: 人間確認を通す (§32)
    "config",  # 重要な設定変更
}


class PermissionError_(PermissionError):
    """未承認の重要操作を実行しようとした場合に送出。"""


class ApprovalGateway:
    def __init__(self, storage: Storage):
        self.storage = storage

    @staticmethod
    def is_sensitive(kind: str) -> bool:
        return kind in SENSITIVE_OPERATIONS

    # ---- 申請 → 承認/却下 ------------------------------------------------

    def request(
        self, kind: str, summary: str, payload: dict, requested_by: str = "system"
    ) -> Approval:
        apr = Approval(
            kind=kind, summary=summary, payload=payload, requested_by=requested_by
        )
        self.storage.put("approvals", apr.to_dict())
        return apr

    def decide(
        self, approval_id: str, approved: bool, by: str = "human", note: str = ""
    ) -> Approval:
        raw = self.storage.get("approvals", approval_id)
        if raw is None:
            raise KeyError(approval_id)
        raw["status"] = "approved" if approved else "rejected"
        raw["decided_at"] = ids.now_iso()
        raw["decided_by"] = by
        raw["note"] = note
        self.storage.put("approvals", raw)
        return Approval(**{k: v for k, v in raw.items() if k in Approval.__dataclass_fields__})

    def approve(self, approval_id: str, by: str = "human", note: str = "") -> Approval:
        return self.decide(approval_id, True, by, note)

    def reject(self, approval_id: str, by: str = "human", note: str = "") -> Approval:
        return self.decide(approval_id, False, by, note)

    def pending(self) -> list[dict]:
        return self.storage.find("approvals", status="pending")

    def is_approved(self, approval_id: str) -> bool:
        raw = self.storage.get("approvals", approval_id)
        return bool(raw and raw.get("status") == "approved")

    # ---- ガード -----------------------------------------------------------

    def guard(self, kind: str, approval_id: str | None) -> None:
        """重要操作を実行する直前に呼ぶ。承認が無ければ例外を送出する。"""
        if not self.is_sensitive(kind):
            return
        if approval_id is None or not self.is_approved(approval_id):
            raise PermissionError_(
                f"操作 '{kind}' には人間承認が必要です (§21)。"
                " ApprovalGateway.request → approve を通してください。"
            )
