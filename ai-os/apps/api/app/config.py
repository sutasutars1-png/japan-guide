"""Runtime configuration from environment (Phase 0)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _origins() -> list[str]:
    raw = os.getenv("CORS_ORIGINS", "http://localhost:3000")
    return [o.strip() for o in raw.split(",") if o.strip()]


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


settings = Settings()
