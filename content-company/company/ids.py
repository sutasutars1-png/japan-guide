"""短くて読みやすい ID の生成。"""

from __future__ import annotations

import datetime as _dt
import secrets

_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyz"


def _rand(n: int = 4) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def new_id(prefix: str) -> str:
    """``prefix_YYYYMMDD_xxxx`` 形式の ID を返す。

    人が台帳を見たときに、種類と日付がひと目で分かるようにしている。
    """
    day = _dt.date.today().strftime("%Y%m%d")
    return f"{prefix}_{day}_{_rand()}"


def now_iso() -> str:
    """タイムゾーン付き ISO8601 (秒精度) の現在時刻。"""
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
