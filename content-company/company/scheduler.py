"""定期スケジューラ（アプリ内・GUI からオン/オフ, 既定オフ）。

付録A #2 の「CSV 取り込みの定期化」等、**安全な内部ジョブだけ**を一定間隔で
実行する。GUI プロセスが動いている間だけ動く軽量なバックグラウンドスレッド。

セキュリティ設計（重要）:
- 実行できるのは下の ``SAFE_JOBS`` に**ハードコードされた関数だけ**。外部から
  任意の処理を差し込めない。
- ジョブは **公開・SNS投稿・承認などの重要操作を一切行わない**（§21）。
  生成（下書き）や内部集計、ローカルCSVの取り込みに限る。実際の公開/投稿は
  つねに人間が承認して行う。
- マスタースイッチと各ジョブは**既定でオフ**。設定は ``data/schedule.json`` に
  保存され、GUI から切り替える。
"""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
import threading
from typing import Any, Callable

_DEFAULT_JOBS = {
    "evaluate": {"enabled": False, "interval_min": 1440, "last_run": None},
    "note_import": {"enabled": False, "interval_min": 1440, "last_run": None},
    "social_draft": {"enabled": False, "interval_min": 1440, "last_run": None},
}


# ---- 安全なジョブ実装（この辞書が唯一の実行対象） -------------------------


def _job_evaluate(c) -> dict[str, Any]:
    ev = c.evaluate()
    return {"actions": len(ev.get("actions", []))}


def _job_note_import(c) -> dict[str, Any]:
    """data/inbox/note.csv があれば取り込む（固定の内部パスのみ）。"""
    path = pathlib.Path(c.config.data_dir) / "inbox" / "note.csv"
    if not path.exists():
        return {"skipped": "inbox/note.csv なし"}
    return c.note_import.import_csv(str(path))


def _job_social_draft(c) -> dict[str, Any]:
    """有効なチャネルについて、未作成の売れ筋商品に下書きを1件ずつ作る。

    下書き生成のみ（投稿はしない, §32-33）。チャネルが config で無効なら何もしない。
    """
    made = []
    channels = []
    if getattr(c.config, "x_enabled", False):
        channels.append("x")
    if getattr(c.config, "tiktok_enabled", False):
        channels.append("tiktok")
    if not channels:
        return {"skipped": "有効なSNSチャネルなし（x_enabled/tiktok_enabled）"}
    published = [p for p in c.storage.all("products") if p.get("status") == "published"]
    published.sort(key=lambda p: int(p.get("revenue_jpy", 0)), reverse=True)
    for channel in channels:
        for p in published:
            if not c.social.has_draft(channel, p["id"]):
                try:
                    c.social.draft(channel, p["id"])
                    made.append(f"{channel}:{p['id']}")
                except Exception as exc:  # noqa: BLE001 （予算超過等は握って次へ）
                    return {"made": made, "stopped": str(exc)[:120]}
                break  # 1 tick 1 チャネル 1 件（負荷を抑える）
    return {"made": made}


SAFE_JOBS: dict[str, Callable[[Any], dict[str, Any]]] = {
    "evaluate": _job_evaluate,
    "note_import": _job_note_import,
    "social_draft": _job_social_draft,
}


class JobScheduler:
    def __init__(self, company, tick_seconds: int = 30):
        self.c = company
        self.tick_seconds = tick_seconds
        self.path = pathlib.Path(company.config.data_dir) / "schedule.json"
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.state = self._load()

    # ---- 設定の読み書き --------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                raw = {}
        else:
            raw = {}
        jobs = dict(_DEFAULT_JOBS)
        for name, cfg in (raw.get("jobs") or {}).items():
            if name in jobs and isinstance(cfg, dict):
                jobs[name] = {**jobs[name], **{k: cfg.get(k, jobs[name][k])
                                               for k in ("enabled", "interval_min", "last_run")}}
        return {"enabled": bool(raw.get("enabled", False)), "jobs": jobs}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.state, ensure_ascii=False, indent=2),
                             encoding="utf-8")

    # ---- 制御 -------------------------------------------------------------

    def set_enabled(self, enabled: bool) -> dict[str, Any]:
        with self._lock:
            self.state["enabled"] = bool(enabled)
            self._save()
        if self.state["enabled"]:
            self.start()
        return self.get_state()

    def set_job(self, name: str, *, enabled: bool | None = None,
                interval_min: int | None = None) -> dict[str, Any]:
        if name not in SAFE_JOBS:
            raise KeyError(f"未知のジョブ: {name}")
        with self._lock:
            job = self.state["jobs"][name]
            if enabled is not None:
                job["enabled"] = bool(enabled)
            if interval_min is not None:
                job["interval_min"] = max(1, min(43200, int(interval_min)))  # 1分〜30日
            self._save()
        return self.get_state()

    def get_state(self) -> dict[str, Any]:
        return {"enabled": self.state["enabled"],
                "running": bool(self._thread and self._thread.is_alive()),
                "jobs": self.state["jobs"]}

    # ---- 実行ループ -------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="job-scheduler")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(self.tick_seconds):
            if not self.state.get("enabled"):
                continue
            self._run_due()

    def _run_due(self) -> None:
        now = _dt.datetime.now(_dt.timezone.utc)
        for name, job in list(self.state["jobs"].items()):
            if not job.get("enabled"):
                continue
            if not self._due(job, now):
                continue
            self.run_job(name)

    @staticmethod
    def _due(job: dict, now: _dt.datetime) -> bool:
        last = job.get("last_run")
        if not last:
            return True
        try:
            prev = _dt.datetime.fromisoformat(last)
        except ValueError:
            return True
        return (now - prev).total_seconds() >= job.get("interval_min", 1440) * 60

    def run_job(self, name: str) -> dict[str, Any]:
        """1 ジョブを実行（手動トリガにも使える）。安全な関数のみ。"""
        fn = SAFE_JOBS.get(name)
        if fn is None:
            raise KeyError(name)
        with self._lock:  # 同時実行を防ぐ
            try:
                result = fn(self.c)
                ok = True
            except Exception as exc:  # noqa: BLE001
                result = {"error": str(exc)[:200]}
                ok = False
            self.state["jobs"][name]["last_run"] = _dt.datetime.now(
                _dt.timezone.utc).replace(microsecond=0).isoformat()
            self._save()
        self.c.memory.add("note", f"スケジューラ実行: {name}",
                          json.dumps(result, ensure_ascii=False)[:200], tags=["scheduler"])
        return {"job": name, "ok": ok, "result": result}
