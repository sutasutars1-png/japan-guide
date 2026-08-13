"""Presets — named base-skill bundles per stage (roadmap Phase 4, design §主スキル).

A preset is a reusable selection of skills for a stage. Each built-in agent has a
default preset (equal to its base skills); "reset to preset" restores it, undoing
edits. Extra presets (e.g. Builder web vs data) let the user switch a whole
skill-set at once. Serializable → exports with the environment template.
"""
from __future__ import annotations

from .skills import AGENT_BASE_SKILLS

PRESETS: list[dict] = [
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

_BY_ID = {p["id"]: p for p in PRESETS}

# Which preset each built-in agent starts on.
AGENT_DEFAULT_PRESET = {
    "Planner": "preset.planner",
    "Researcher": "preset.researcher",
    "Builder": "preset.builder",
    "Reviewer": "preset.reviewer",
    "Executor": "preset.executor",
}


def list_presets(stage: str | None = None) -> list[dict]:
    if stage is None:
        return PRESETS
    return [p for p in PRESETS if p["stage"] == stage]


def get_preset(preset_id: str) -> dict | None:
    return _BY_ID.get(preset_id)
