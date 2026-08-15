"""Claude Code CLI provider (Phase 4 · #5) — the honest keyless orchestrator.

The backend shells out to the user's own, already-logged-in `claude` binary and
reads its stdout. This is how "Claude as the orchestrator, without an API key"
works cleanly:

- no API key and no metered API cost — it uses the user's Claude Code login;
- no token injection — we never extract or smuggle a credential; we just run the
  tool the user already installed, as the user (legitimate personal use);
- runs on the HOST (the backend process), never inside the task sandbox — the
  "brain" channel is kept separate from the "hands" channel, so a prompt-injected
  agent in the sandbox can never reach this credential.

Safety of the invocation itself:
- the prompt is masked (Phase 3) before it is passed to the CLI;
- `--dangerously-skip-permissions` is NEVER passed, so in headless `-p` mode any
  tool the model tries to use is auto-denied — it can only return text;
- common mutating tools are additionally disallowed, and it runs in a throwaway
  temp cwd, as defense in depth. The whole invocation is overridable via
  `AIOS_CLAUDE_CLI_ARGS` so a CLI version change is a config edit, not a code one.

Import-safe without the binary: `complete()` raises a clear error if `claude`
isn't found, so the API still boots.
"""
from __future__ import annotations

import asyncio
import shutil
import tempfile
from typing import Any

from ...config import settings
from .base import LLMMessage, LLMProvider, LLMResponse, LLMUsage
from .manual_provider import render_prompt  # flattens + masks messages

# Text-only defaults: no skip-permissions (so tools are denied in headless mode),
# plus an explicit disallow list as belt-and-suspenders.
_DEFAULT_ARGS = [
    "-p", "--output-format", "text",
    "--disallowed-tools", "Bash,Edit,Write,NotebookEdit,WebFetch,WebSearch,TodoWrite",
]


def _build_args() -> list[str]:
    if settings.claude_cli_args.strip():
        args = settings.claude_cli_args.split()
    else:
        args = list(_DEFAULT_ARGS)
        if settings.claude_cli_model:
            args += ["--model", settings.claude_cli_model]
    return args


class ClaudeCliProvider(LLMProvider):
    name = "claude-cli"

    def __init__(self, cli_path: str | None = None, timeout_s: int | None = None) -> None:
        self._cli = cli_path or settings.claude_cli_path
        self._timeout = timeout_s if timeout_s is not None else settings.claude_cli_timeout

    @staticmethod
    def available(cli_path: str | None = None) -> str | None:
        """Resolved absolute path of the `claude` binary, or None if not found."""
        return shutil.which(cli_path or settings.claude_cli_path)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 4096,
    ) -> LLMResponse:
        resolved = shutil.which(self._cli)
        if not resolved:
            raise RuntimeError(
                f"`{self._cli}` が見つかりません。Claude Code CLI をインストールし、"
                "バックエンドを実行する環境でログインしてください。"
            )
        prompt = render_prompt(messages)  # masked, flattened
        args = [resolved, *_build_args()]
        with tempfile.TemporaryDirectory(prefix="aios-claude-") as cwd:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,  # empty throwaway dir: nothing here to touch
            )
            try:
                out_b, err_b = await asyncio.wait_for(
                    proc.communicate(input=prompt.encode()), timeout=self._timeout
                )
            except asyncio.TimeoutError as exc:
                proc.kill()
                raise RuntimeError("claude CLI がタイムアウトしました。") from exc

        if proc.returncode != 0:
            err = (err_b.decode(errors="replace") or "").strip()[:400]
            raise RuntimeError(f"claude CLI がエラー終了 (code {proc.returncode}): {err}")
        text = out_b.decode(errors="replace").strip()
        # Usage is not reported by the CLI text output; never fabricate counts.
        return LLMResponse(text=text, usage=LLMUsage())
