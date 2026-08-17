"""Deliverables store — capture, persist, and export a run's 成果物.

An orchestration/flow/agent run produces reports (each worker's DONE output,
chained into a final result). Until now those only streamed to the UI and were
lost when the run ended. This module turns them into a **deliverable**: a saved
bundle the user can list, re-open, and **download** as Markdown / plain text /
JSON.

Persistence mirrors `agents_store`: a small git-ignored JSON file next to `.env`
(`.aios-deliverables.json`), so saved deliverables survive an API restart. All
writes are best-effort — a persistence failure never breaks a request.

Rendering (Markdown/text) is done on demand from the stored artifacts, so the
download format is chosen at export time, not baked in at save time.
"""
from __future__ import annotations

import io
import json
import logging
import mimetypes
import re
import time
import zipfile
from copy import deepcopy
from uuid import uuid4

from .env_file import env_path

_FILE_TASK_PREFIX = "ファイル: "

log = logging.getLogger("aios")

MAX_DELIVERABLES = 200  # keep the store bounded (newest kept, oldest dropped)


def _state_path():
    # Next to the .env: ai-os/.aios-deliverables.json (repo) or /srv/… (container).
    return env_path().parent / ".aios-deliverables.json"


def _load() -> list[dict]:
    path = _state_path()
    try:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
    except Exception as exc:  # noqa: BLE001 — corrupt/unreadable → start empty
        log.warning("deliverables state unreadable (%s); starting empty", exc)
    return []


_items: list[dict] = _load()


def _save() -> None:
    try:
        path = _state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_items, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 — never break a request on a write error
        log.warning("could not persist deliverables: %s", exc)


def _slug(text: str, fallback: str = "deliverable") -> str:
    """A filesystem-safe stem for the downloaded file name."""
    text = (text or "").strip()
    # keep unicode letters/digits, collapse everything else to '-'
    slug = re.sub(r"[^\w぀-ヿ一-鿿-]+", "-", text, flags=re.UNICODE).strip("-")
    return (slug or fallback)[:60]


def _title_from(goal: str) -> str:
    goal = (goal or "").strip().replace("\n", " ")
    return (goal[:80] + "…") if len(goal) > 80 else (goal or "無題の成果物")


def _clean_artifacts(artifacts: list[dict] | None) -> list[dict]:
    out: list[dict] = []
    for a in artifacts or []:
        content = (a.get("content") or "").strip()
        if not content:
            continue
        out.append({
            "agent": (a.get("agent") or "").strip() or "AI",
            "task": (a.get("task") or "").strip(),
            "content": content,
        })
    return out


# Log-line types that carry a worker's actual output (vs. system chatter).
_OUTPUT_TYPES = {"out"}
_STEP_RE = re.compile(r"^▶\s*工程\s*\d+\s*[:：]\s*([^\s—-]+)\s*[—-]\s*(.*)$")
_TAG_RE = re.compile(r"^\[([^\]]+)\]\s?(.*)$", re.DOTALL)


def _try_json(s: str) -> dict | None:
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else None
    except Exception:  # noqa: BLE001
        return None


def artifacts_from_lines(lines: list[dict]) -> list[dict]:
    """Best-effort reconstruction of artifacts from streamed log lines.

    Handles three shapes, so the UI can save any run it captured client-side:
    - orchestrator/flow logs: `▶ 工程 N: <agent> — <task>` markers grouping the
      `[agent] …` output that follows;
    - a plain agent run with no step markers: capture the DONE report that follows
      an `agent finished ✓` line;
    - `file` lines (JSON {path, size, content}) become their own artifacts.
    """
    steps: list[dict] = []
    cur: dict | None = None

    def push() -> None:
        nonlocal cur
        if cur and cur["content"].strip():
            cur["content"] = cur["content"].strip()
            steps.append(cur)
        cur = None

    for ln in lines or []:
        t = (ln.get("t") or "").strip()
        s = ln.get("s") or ""

        if t == "file":  # a generated file → its own artifact
            meta = _try_json(s)
            if meta and (meta.get("content") or "").strip():
                steps.append({
                    "agent": (cur or {}).get("agent", "AI"),
                    "task": f"ファイル: {meta.get('path', '')}",
                    "content": meta["content"],
                })
            continue

        m = _STEP_RE.match(s.strip())
        if m:  # a new ▶ 工程 step
            push()
            cur = {"agent": m.group(1).strip(), "task": m.group(2).strip(), "content": ""}
            continue

        tag = _TAG_RE.match(s)
        body = tag.group(2) if tag else s
        if body.strip() == "agent finished ✓":  # begin a default report bucket
            if cur is None:
                cur = {"agent": (tag.group(1).strip() if tag else "AI"), "task": "", "content": ""}
            continue

        if cur is None or t not in _OUTPUT_TYPES:
            continue
        if body.strip():
            cur["content"] += (body.rstrip() + "\n")

    push()
    return _clean_artifacts(steps)


def save(
    *,
    goal: str,
    artifacts: list[dict],
    source: str = "orchestrate",
    orchestrator: str | None = None,
    title: str | None = None,
    status: str = "complete",
) -> dict:
    """Persist a new deliverable and return its record. Newest first."""
    item = {
        "id": "dlv_" + uuid4().hex[:12],
        "title": (title or _title_from(goal)),
        "goal": (goal or "").strip(),
        "source": source,
        "orchestrator": orchestrator,
        "status": status,
        "created": time.time(),
        "artifacts": _clean_artifacts(artifacts),
    }
    _items.insert(0, item)
    del _items[MAX_DELIVERABLES:]
    _save()
    log.info("deliverable saved · %s · %d artifact(s)", item["id"], len(item["artifacts"]))
    return item


def list_deliverables() -> list[dict]:
    """Metadata only (no artifact bodies) — for the list view."""
    return [_meta(i) for i in _items]


def _meta(item: dict) -> dict:
    return {
        "id": item["id"],
        "title": item.get("title", ""),
        "goal": item.get("goal", ""),
        "source": item.get("source", ""),
        "orchestrator": item.get("orchestrator"),
        "status": item.get("status", "complete"),
        "created": item.get("created", 0),
        "artifact_count": len(item.get("artifacts", [])),
    }


def get(deliverable_id: str) -> dict | None:
    return next((i for i in _items if i["id"] == deliverable_id), None)


def remove(deliverable_id: str) -> bool:
    for i, item in enumerate(_items):
        if item["id"] == deliverable_id:
            del _items[i]
            _save()
            return True
    return False


def clear() -> None:
    """Drop all deliverables (used by tests)."""
    global _items
    _items = []
    _save()


# ---- rendering / export -----------------------------------------------------

def _stamp(ts: float) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))
    except Exception:  # noqa: BLE001
        return ""


def render_markdown(item: dict) -> str:
    """Combine a deliverable into a single Markdown document."""
    lines = [f"# {item.get('title') or '成果物'}", ""]
    goal = (item.get("goal") or "").strip()
    if goal:
        lines += ["> **ゴール:** " + goal.replace("\n", " "), ""]
    meta = []
    if item.get("orchestrator"):
        meta.append(f"統括AI: {item['orchestrator']}")
    if item.get("source"):
        meta.append(f"実行: {item['source']}")
    if item.get("created"):
        meta.append(f"作成: {_stamp(item['created'])}")
    if meta:
        lines += ["_" + " · ".join(meta) + "_", ""]
    arts = item.get("artifacts", [])
    if not arts:
        lines += ["_（成果物なし）_", ""]
    for i, a in enumerate(arts, 1):
        head = f"## {i}. {a.get('agent', 'AI')}"
        if a.get("task"):
            head += f" — {a['task']}"
        lines += [head, "", a.get("content", "").rstrip(), ""]
    return "\n".join(lines).rstrip() + "\n"


def render_text(item: dict) -> str:
    """Plain-text export (Markdown with the heading marks stripped)."""
    md = render_markdown(item)
    out = []
    for ln in md.splitlines():
        ln = re.sub(r"^#{1,6}\s+", "", ln)
        ln = re.sub(r"^>\s?", "", ln)
        ln = ln.replace("**", "").replace("_", "")
        out.append(ln)
    return "\n".join(out).rstrip() + "\n"


def export(item: dict, fmt: str) -> tuple[str, str, str]:
    """Return (body, media_type, filename) for a download in the given format."""
    stem = _slug(item.get("title") or item.get("goal") or item["id"], item["id"])
    fmt = (fmt or "md").lower()
    if fmt in ("md", "markdown"):
        return render_markdown(item), "text/markdown; charset=utf-8", f"{stem}.md"
    if fmt in ("txt", "text"):
        return render_text(item), "text/plain; charset=utf-8", f"{stem}.txt"
    if fmt == "json":
        body = json.dumps(item, ensure_ascii=False, indent=2)
        return body, "application/json; charset=utf-8", f"{stem}.json"
    raise ValueError(f"unsupported format: {fmt}")


# ---- per-artifact + ZIP export ---------------------------------------------

def _safe_member(name: str) -> str:
    """A zip/download-safe relative path: no leading '/', no '..' traversal."""
    name = (name or "").replace("\\", "/").lstrip("/")
    parts = [p for p in name.split("/") if p not in ("", ".", "..")]
    return "/".join(parts) or "artifact"


def artifact_filename(a: dict, index: int) -> str:
    """Filename for one artifact. File-artifacts keep their original path; a text
    report becomes `NN-<agent>.md`."""
    task = a.get("task", "") or ""
    if task.startswith(_FILE_TASK_PREFIX):
        path = task[len(_FILE_TASK_PREFIX):].strip()
        if path:
            return _safe_member(path)
    return f"{index:02d}-{_slug(a.get('agent', 'AI'))}.md"


def _artifact_media_type(name: str) -> str:
    mt = mimetypes.guess_type(name)[0] or "text/plain"
    if mt.startswith("text/") or mt in ("application/json", "application/xml"):
        mt += "; charset=utf-8"
    return mt


def export_artifact(item: dict, index: int, fmt: str = "raw") -> tuple[str, str, str]:
    """Return (body, media_type, filename) for ONE artifact of a deliverable."""
    arts = item.get("artifacts", [])
    if index < 0 or index >= len(arts):
        raise IndexError("artifact index out of range")
    a = arts[index]
    content = a.get("content", "")
    name = artifact_filename(a, index + 1).rsplit("/", 1)[-1]  # basename for a single file
    fmt = (fmt or "raw").lower()
    if fmt in ("txt", "text"):
        stem = name.rsplit(".", 1)[0]
        return content.rstrip() + "\n", "text/plain; charset=utf-8", f"{stem}.txt"
    return content, _artifact_media_type(name), name


def export_zip(item: dict) -> tuple[bytes, str, str]:
    """Bundle the whole deliverable as a ZIP: a combined `deliverable.md` plus each
    artifact as its own file under `artifacts/`."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("deliverable.md", render_markdown(item))
        used: set[str] = set()
        for i, a in enumerate(item.get("artifacts", []), 1):
            member = _safe_member(artifact_filename(a, i))
            if member in used:  # de-dupe collisions
                member = f"{i:02d}-{member}"
            used.add(member)
            z.writestr(f"artifacts/{member}", a.get("content", ""))
    stem = _slug(item.get("title") or item.get("goal") or item["id"], item["id"])
    return buf.getvalue(), "application/zip", f"{stem}.zip"
