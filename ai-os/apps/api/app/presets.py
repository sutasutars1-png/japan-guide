"""Presets — named base-skill bundles per stage (roadmap Phase 4, design §主スキル).

A preset is a reusable selection of skills for a stage. Built-in presets are the
seed defaults below; **custom presets the user saves are persisted** to a
git-ignored `.aios-presets.json` so they survive a restart. Seed presets are
read-only (used by "reset to preset"); only custom presets can be edited/deleted.
"""
from __future__ import annotations

from uuid import uuid4

from .json_store import load_json, save_json
from .skills import AGENT_BASE_SKILLS

_STORE_FILE = ".aios-presets.json"
_CUSTOM_PREFIX = "custom."

SEED_PRESETS: list[dict] = [
    {"id": "preset.planner", "name": "Planner / 標準", "stage": "Planner",
     "skills": AGENT_BASE_SKILLS["Planner"]},
    {"id": "preset.researcher", "name": "Researcher / 標準", "stage": "Researcher",
     "skills": AGENT_BASE_SKILLS["Researcher"]},
    {"id": "preset.builder", "name": "Builder / Web・汎用", "stage": "Builder",
     "skills": AGENT_BASE_SKILLS["Builder"]},
    {"id": "preset.builder_data", "name": "Builder / データ分析", "stage": "Builder",
     "skills": ["BASE-ANA", "DOM-DATA", "exec.small_steps", "exec.data_shape",
                "exec.test_before_done", "exec.inspect_first", "exec.triage_failures",
                "exec.safe_report"]},
    {"id": "preset.reviewer", "name": "Reviewer / セキュリティ", "stage": "Reviewer",
     "skills": AGENT_BASE_SKILLS["Reviewer"]},
    {"id": "preset.executor", "name": "Executor / 標準", "stage": "Executor",
     "skills": AGENT_BASE_SKILLS["Executor"]},
]

# Which preset each built-in agent starts on.
AGENT_DEFAULT_PRESET = {
    "Planner": "preset.planner",
    "Researcher": "preset.researcher",
    "Builder": "preset.builder",
    "Reviewer": "preset.reviewer",
    "Executor": "preset.executor",
}


def _load_custom() -> list[dict]:
    data = load_json(_STORE_FILE, [])
    return [p for p in data if isinstance(p, dict) and p.get("id")] if isinstance(data, list) else []


_custom: list[dict] = _load_custom()


def _save() -> None:
    save_json(_STORE_FILE, _custom)


def is_custom(preset_id: str) -> bool:
    return str(preset_id).startswith(_CUSTOM_PREFIX)


def _all() -> list[dict]:
    return SEED_PRESETS + _custom


def list_presets(stage: str | None = None) -> list[dict]:
    items = _all()
    return items if stage is None else [p for p in items if p["stage"] == stage]


def get_preset(preset_id: str) -> dict | None:
    return next((p for p in _all() if p["id"] == preset_id), None)


def add_preset(name: str, stage: str, skills: list[str]) -> dict:
    preset = {
        "id": _CUSTOM_PREFIX + uuid4().hex[:8],
        "name": (name or "カスタム").strip(),
        "stage": stage,
        "skills": list(skills or []),
    }
    _custom.append(preset)
    _save()
    return preset


def update_preset(preset_id: str, changes: dict) -> dict | None:
    """Edit a CUSTOM preset. Seed presets are read-only (returns None)."""
    if not is_custom(preset_id):
        return None
    for p in _custom:
        if p["id"] == preset_id:
            for k in ("name", "stage", "skills"):
                if k in changes and changes[k] is not None:
                    p[k] = changes[k]
            _save()
            return p
    return None


def remove_preset(preset_id: str) -> bool:
    """Delete a CUSTOM preset. Seed presets can't be deleted."""
    if not is_custom(preset_id):
        return False
    for i, p in enumerate(_custom):
        if p["id"] == preset_id:
            del _custom[i]
            _save()
            return True
    return False


def reset_to_seed() -> None:
    """Drop all custom presets (used by tests)."""
    global _custom
    _custom = []
    _save()
