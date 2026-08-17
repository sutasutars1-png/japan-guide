"""Connections (Phase 4) — providers, keys, and live model discovery.

Two kinds of provider sit behind the one `LLMProvider` boundary:

- **api**   — called over HTTP (Gemini, Anthropic, OpenAI). Needs an API key,
              stored via `env_file` in the git-ignored `.env` and registered for
              masking. Its available models are **discovered live** from the
              provider after the key is set — no hard-coded version strings, so a
              new model release shows up without a code change.
- **manual** — no API; used through the manual bridge (Claude in the browser, the
              Claude Code CLI). No key; its model list is user-curated (there is
              no endpoint to ask), and completions are fulfilled by a human.

Everything a secret touches goes through the Secret Store + `.env`; keys are
never returned to the UI in the clear (only a masked hint) and never logged.
"""
from __future__ import annotations

import os
from typing import Any, Callable

from .core.secrets import store as secret_store
from .env_file import set_env_value, unset_env_value
from .json_store import load_json, save_json

_STATE_FILE = ".aios-connections.json"

# ---- provider catalog -------------------------------------------------------

PROVIDERS: list[dict[str, Any]] = [
    {"id": "gemini", "name": "Google Gemini", "kind": "api",
     "env": "GEMINI_API_KEY", "alt_env": ["GOOGLE_API_KEY"], "free": True},
    {"id": "anthropic", "name": "Anthropic (Claude API)", "kind": "api",
     "env": "ANTHROPIC_API_KEY", "free": False},
    {"id": "openai", "name": "OpenAI", "kind": "api",
     "env": "OPENAI_API_KEY", "free": False},
    {"id": "claude-cli", "name": "Claude Code（ローカルCLI・自動）", "kind": "cli",
     "free": True, "default_models": ["claude-cli"]},
    {"id": "claude-web", "name": "Claude（ブラウザ・コピペ）", "kind": "manual",
     "free": True, "default_models": ["claude-web"]},
]
_BY_ID = {p["id"]: p for p in PROVIDERS}

# Per-provider state (discovered models, manual model lists, errors).
# Keys/values never live here — only model ids and status. The model lists are
# **persisted** (git-ignored `.aios-connections.json`) so a manually-curated model
# (e.g. for claude-web) and the last discovered list survive a restart instead of
# resetting to defaults; api providers still re-discover on boot via `bootstrap`.
_state: dict[str, dict[str, Any]] = {
    p["id"]: {"models": list(p.get("default_models", [])), "error": None}
    for p in PROVIDERS
}


def _load_state() -> None:
    saved = load_json(_STATE_FILE, {})
    if not isinstance(saved, dict):
        return
    for pid, models in saved.items():
        if pid in _state and isinstance(models, list):
            _state[pid]["models"] = [str(m) for m in models if m]


def _persist_state() -> None:
    save_json(_STATE_FILE, {pid: st["models"] for pid, st in _state.items()})


_load_state()


def _env_names(p: dict) -> list[str]:
    return [p["env"], *p.get("alt_env", [])] if p.get("env") else []


def _cli_path() -> str | None:
    """Resolved path of the Claude Code CLI, or None if not on PATH."""
    from .core.llm.claude_cli_provider import ClaudeCliProvider
    return ClaudeCliProvider.available()


def _key_present(p: dict) -> bool:
    if p["kind"] == "manual":
        return True  # always "ready" — the transport is a human, no key needed
    if p["kind"] == "cli":
        return _cli_path() is not None  # ready iff the `claude` binary is found
    names = set(secret_store.names())
    return any(n in names for n in _env_names(p))


def _masked_hint(p: dict) -> str:
    if p["kind"] == "manual":
        return "APIキー不要（コピペ連携）"
    if p["kind"] == "cli":
        path = _cli_path()
        return f"CLI検出: {path}" if path else "claude CLI 未検出"
    for n in _env_names(p):
        val = secret_store.get(n)
        if val:
            tail = val[-4:] if len(val) >= 4 else ""
            return f"••••••••{tail}"
    return "未設定"


# ---- live model discovery ---------------------------------------------------
# Each returns a list of model ids or raises. Network calls are lazy + injectable
# (module-level names) so tests can substitute them without hitting the network.

def _discover_gemini(key: str) -> list[str]:
    import httpx

    url = "https://generativelanguage.googleapis.com/v1beta/models"
    r = httpx.get(url, params={"key": key}, timeout=30)
    r.raise_for_status()
    out = []
    for m in r.json().get("models", []):
        if "generateContent" in (m.get("supportedGenerationMethods") or []):
            out.append(str(m.get("name", "")).removeprefix("models/"))
    return [m for m in out if m]


def _discover_anthropic(key: str) -> list[str]:
    import httpx

    r = httpx.get(
        "https://api.anthropic.com/v1/models",
        headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
        timeout=30,
    )
    r.raise_for_status()
    return [str(m.get("id")) for m in r.json().get("data", []) if m.get("id")]


def _discover_openai(key: str) -> list[str]:
    import httpx

    r = httpx.get(
        "https://api.openai.com/v1/models",
        headers={"Authorization": f"Bearer {key}"},
        timeout=30,
    )
    r.raise_for_status()
    ids = [str(m.get("id")) for m in r.json().get("data", []) if m.get("id")]
    # Keep the chat-capable families; sort newest-ish first.
    return sorted([m for m in ids if m.startswith(("gpt", "o1", "o3", "o4"))], reverse=True)


def _discoverer(provider_id: str) -> Callable[[str], list[str]] | None:
    # Resolved by name at call time so it stays swappable (tests) and reflects
    # the current module attribute rather than a cached reference.
    return globals().get(f"_discover_{provider_id.replace('-', '_')}")


def refresh_models(provider_id: str) -> dict[str, Any]:
    """Re-discover a provider's models from its key. Manual providers keep their
    curated list. Errors are captured (not raised) so the UI degrades gracefully.
    """
    p = _BY_ID.get(provider_id)
    if p is None:
        raise KeyError(provider_id)
    st = _state[provider_id]
    if p["kind"] != "api":  # manual + cli keep their curated model list
        st["error"] = None
        return connection(provider_id)
    key = next((secret_store.get(n) for n in _env_names(p) if secret_store.get(n)), None)
    if not key:
        st["error"] = None
        st["models"] = []
        return connection(provider_id)
    discover = _discoverer(provider_id)
    if discover is None:
        st["error"] = None
        return connection(provider_id)
    try:
        models = discover(key)
        st["models"] = models
        st["error"] = None
        _persist_state()
    except Exception as exc:  # noqa: BLE001 — surface as status, never crash
        st["error"] = f"モデル取得に失敗: {exc}"
    return connection(provider_id)


# ---- key management ---------------------------------------------------------

def set_key(provider_id: str, key: str) -> dict[str, Any]:
    """Store an API key (Secret Store + `.env`) and discover models. Never logs it."""
    p = _BY_ID.get(provider_id)
    if p is None:
        raise KeyError(provider_id)
    if p["kind"] != "api":
        raise ValueError("this provider needs no API key")
    key = (key or "").strip()
    if not key:
        raise ValueError("empty key")
    secret_store.set(p["env"], key)   # register for masking immediately
    set_env_value(p["env"], key)      # persist to git-ignored .env
    return refresh_models(provider_id)


def clear_key(provider_id: str) -> dict[str, Any]:
    p = _BY_ID.get(provider_id)
    if p is None:
        raise KeyError(provider_id)
    for n in _env_names(p):
        unset_env_value(n)
        secret_store._values.pop(n, None)  # noqa: SLF001 — same package, intentional
    secret_store._rebuild_pattern()        # noqa: SLF001
    _state[provider_id]["models"] = []
    _state[provider_id]["error"] = None
    _persist_state()
    return connection(provider_id)


def add_manual_model(provider_id: str, model: str) -> dict[str, Any]:
    p = _BY_ID.get(provider_id)
    if p is None or p["kind"] != "manual":
        raise ValueError("not a manual provider")
    model = (model or "").strip()
    if model and model not in _state[provider_id]["models"]:
        _state[provider_id]["models"].append(model)
        _persist_state()
    return connection(provider_id)


def remove_manual_model(provider_id: str, model: str) -> dict[str, Any]:
    p = _BY_ID.get(provider_id)
    if p is None or p["kind"] != "manual":
        raise ValueError("not a manual provider")
    models = _state[provider_id]["models"]
    if model in models:
        models.remove(model)
        _persist_state()
    return connection(provider_id)


# ---- serialization + resolution ---------------------------------------------

def connection(provider_id: str) -> dict[str, Any]:
    p = _BY_ID[provider_id]
    st = _state[provider_id]
    return {
        "id": p["id"],
        "name": p["name"],
        "kind": p["kind"],
        "free": p.get("free", False),
        "connected": _key_present(p),
        "key_hint": _masked_hint(p),
        "models": list(st["models"]),
        "error": st["error"],
    }


def list_connections() -> list[dict[str, Any]]:
    return [connection(p["id"]) for p in PROVIDERS]


def all_models() -> list[dict[str, Any]]:
    """Flat, de-duplicated model list across *connected* providers, for the UI's
    model pickers — so version strings come from live discovery, not constants."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for p in PROVIDERS:
        if not _key_present(p):
            continue
        for m in _state[p["id"]]["models"]:
            if m in seen:
                continue
            seen.add(m)
            out.append({"model": m, "provider": p["id"], "kind": p["kind"]})
    return out


def provider_id_for_model(model: str) -> str | None:
    """Which provider serves this model id (by its discovered/curated list)."""
    for p in PROVIDERS:
        if model in _state[p["id"]]["models"]:
            return p["id"]
    # Heuristic fallback for unseen ids so routing still works pre-discovery.
    m = (model or "").lower()
    if m.startswith("claude-cli") or m == "claude-code":
        return "claude-cli"
    if m == "claude-web":
        return "claude-web"
    if m.startswith("claude"):
        return "anthropic"
    if m.startswith(("gpt", "o1", "o3", "o4")):
        return "openai"
    if m.startswith("gemini"):
        return "gemini"
    return None


def bootstrap() -> None:
    """On boot: discover models for any provider whose key is already in the env."""
    for p in PROVIDERS:
        if p["kind"] == "api" and _key_present(p):
            refresh_models(p["id"])


def is_manual(provider_id: str | None) -> bool:
    p = _BY_ID.get(provider_id or "")
    return bool(p and p["kind"] == "manual")
