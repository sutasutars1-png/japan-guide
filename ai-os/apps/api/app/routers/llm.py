"""LLM endpoints — status + a one-shot completion to verify a configured key.

The PLAN→EXECUTE→OBSERVE loop is a later Phase 4 stage; this router just lets
the UI/user confirm the provider adapter works once a key is set.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import settings
from ..core.llm import LLMMessage, get_llm_provider
from ..core.secrets import store as secret_store

router = APIRouter(prefix="/llm", tags=["llm"])


class LLMStatus(BaseModel):
    provider: str
    model: str
    key_present: bool


class CompleteRequest(BaseModel):
    prompt: str
    model: str | None = None
    max_tokens: int = 1024


class CompleteResult(BaseModel):
    text: str
    provider: str
    model: str
    input_tokens: int
    output_tokens: int


def _key_present() -> bool:
    # A provider is "ready" if the secret store holds its key.
    names = set(secret_store.names())
    if settings.llm_provider == "gemini":
        return bool({"GEMINI_API_KEY", "GOOGLE_API_KEY"} & names)
    if settings.llm_provider == "anthropic":
        return "ANTHROPIC_API_KEY" in names
    return False


@router.get("", response_model=LLMStatus)
def status() -> LLMStatus:
    return LLMStatus(
        provider=settings.llm_provider,
        model=settings.llm_model,
        key_present=_key_present(),
    )


@router.post("/complete", response_model=CompleteResult)
async def complete(body: CompleteRequest) -> CompleteResult:
    """One-shot completion — handy to verify a newly-added API key works."""
    provider = get_llm_provider()
    model = body.model or settings.llm_model
    try:
        resp = await provider.complete(
            [LLMMessage(role="user", content=body.prompt)],
            model=model,
            max_tokens=body.max_tokens,
        )
    except RuntimeError as exc:  # missing key etc.
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — surface provider/transport errors cleanly
        raise HTTPException(status_code=502, detail=f"LLM call failed: {exc}") from exc
    return CompleteResult(
        text=resp.text,
        provider=provider.name,
        model=model,
        input_tokens=resp.usage.input_tokens,
        output_tokens=resp.usage.output_tokens,
    )
