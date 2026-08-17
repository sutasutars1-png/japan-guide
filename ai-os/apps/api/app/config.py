"""Runtime configuration from environment (Phase 0)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    return [o.strip() for o in raw.split(",") if o.strip()]


def _csv(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [x.strip() for x in raw.split(",") if x.strip()]


@dataclass
class Settings:
    env: str = os.getenv("AIOS_ENV", "development")
    database_url: str = os.getenv(
        "DATABASE_URL", "postgresql+psycopg://aios:aios_dev_password@localhost:5432/aios"
    )
    sandbox_runtime: str = os.getenv("SANDBOX_RUNTIME", "docker")
    llm_provider: str = os.getenv("LLM_PROVIDER", "gemini")
    llm_model: str = os.getenv("LLM_MODEL", "gemini-2.5-flash")
    llm_token_budget: int = int(os.getenv("LLM_TOKEN_BUDGET", "40000"))
    cors_origins: list[str] = field(default_factory=_origins)
    # Claude Code CLI provider (#5): the backend shells out to the user's own
    # logged-in `claude` binary — no API key, no token injection.
    claude_cli_path: str = os.getenv("AIOS_CLAUDE_CLI", "claude")
    claude_cli_model: str = os.getenv("AIOS_CLAUDE_CLI_MODEL", "")  # "" = CLI default
    claude_cli_timeout: int = int(os.getenv("AIOS_CLAUDE_CLI_TIMEOUT", "300"))
    # Override the invocation entirely (version-proofing); space-separated.
    claude_cli_args: str = os.getenv("AIOS_CLAUDE_CLI_ARGS", "")
    # Billing safety: strip ANTHROPIC_API_KEY / _AUTH_TOKEN from the CLI's env so
    # `claude` uses your SUBSCRIPTION login, never metered API billing. Default on.
    # If not logged in, the CLI fails cleanly instead of silently charging the API.
    claude_cli_force_subscription: bool = (
        os.getenv("AIOS_CLAUDE_CLI_FORCE_SUBSCRIPTION", "1").lower() not in ("0", "false", "no")
    )
    # --- Sandbox session / deliverable-file collection (Phase 4 · deliverables) ---
    # An agent loop runs all its commands in ONE sandbox so files persist between
    # steps; at the end, files created under the workdir are collected as
    # deliverable artifacts (bounded by the caps below).
    persistent_agent_sandbox: bool = (
        os.getenv("AIOS_PERSISTENT_SANDBOX", "1").lower() not in ("0", "false", "no")
    )
    collect_deliverable_files: bool = (
        os.getenv("AIOS_COLLECT_FILES", "1").lower() not in ("0", "false", "no")
    )
    deliverable_max_files: int = int(os.getenv("AIOS_DELIVERABLE_MAX_FILES", "20"))
    deliverable_max_bytes: int = int(os.getenv("AIOS_DELIVERABLE_MAX_BYTES", str(256 * 1024)))
    # Copy-in materials: a host directory whose (filtered) files are uploaded into
    # each sandbox at <workdir>/materials so agents have source material to work
    # from. This is a COPY, never a live host mount (the isolation invariant).
    workspace_mount: str = os.getenv("AIOS_WORKSPACE_MOUNT", "")
    materials_max_files: int = int(os.getenv("AIOS_MATERIALS_MAX_FILES", "80"))
    materials_max_bytes: int = int(os.getenv("AIOS_MATERIALS_MAX_BYTES", str(512 * 1024)))
    # A network allowlist applied to every agent sandbox on top of each agent's
    # own allow_domains (both human-set; the LLM can never widen them).
    default_allow_domains: list[str] = field(default_factory=lambda: _csv("AIOS_DEFAULT_ALLOW_DOMAINS"))
    # --- Host-side web.fetch tool (research without opening the sandbox) ---
    # The backend (not the sandbox) fetches a URL the LLM asks for and returns
    # text, so the code sandbox stays Default-Deny. SSRF-guarded: private/loopback/
    # link-local/metadata targets are refused, GET-only, size/redirect capped.
    web_fetch_enabled: bool = (
        os.getenv("AIOS_WEB_FETCH", "1").lower() not in ("0", "false", "no")
    )
    web_fetch_max_bytes: int = int(os.getenv("AIOS_WEB_FETCH_MAX_BYTES", str(512 * 1024)))
    web_fetch_timeout: int = int(os.getenv("AIOS_WEB_FETCH_TIMEOUT", "15"))
    web_fetch_max_redirects: int = int(os.getenv("AIOS_WEB_FETCH_MAX_REDIRECTS", "4"))


settings = Settings()
