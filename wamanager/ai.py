"""AI replies over the OpenAI-compatible wire format.

Works unchanged with OpenAI, Groq, Together, OpenRouter, vLLM, LM Studio and
Ollama (`/v1`). If no provider is configured the client raises a clear error —
the bot never invents a response.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings
from .errors import UpstreamError, ValidationError

log = logging.getLogger(__name__)


@dataclass
class AiReply:
    text: str
    model: str
    prompt_tokens: int
    output_tokens: int
    latency_ms: int


def _is_local(base_url: str) -> bool:
    """Local endpoints do not need credentials."""
    host = base_url.lower()
    return any(
        marker in host
        for marker in ("127.0.0.1", "localhost", "0.0.0.0", "::1", "host.docker.internal")
    )


class AiClient:
    """Stateless HTTP client; per-bot credentials are passed in per call."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    # --------------------------------------------------------------- config
    def resolve(self, bot_config: dict[str, Any]) -> tuple[str, str, str]:
        """Return (base_url, api_key, model) using the bot config then defaults."""
        base_url = (bot_config.get("ai_base_url") or self._settings.ai_base_url or "").rstrip("/")
        api_key = self._settings.ai_api_key or ""
        model = bot_config.get("ai_model") or self._settings.ai_model or ""
        if not base_url:
            raise ValidationError(
                "No AI provider configured. Set AI_BASE_URL in .env or per-bot in the panel."
            )
        if not model:
            raise ValidationError("No AI model configured (AI_MODEL or per-bot setting).")
        if not api_key and not _is_local(base_url):
            raise ValidationError(
                "No AI API key configured (AI_API_KEY). Local endpoints are exempt."
            )
        return base_url, api_key, model

    def configured(self, bot_config: dict[str, Any] | None = None) -> bool:
        """True only when a call could plausibly succeed.

        A local provider (Ollama, LM Studio, vLLM) needs no key, but a remote
        one does — reporting "configured" without a key would be a lie, and
        this panel never pretends.
        """
        try:
            base_url, api_key, _model = self.resolve(bot_config or {})
        except ValidationError:
            return False
        if _is_local(base_url):
            return True
        return bool(api_key)

    # ----------------------------------------------------------------- call
    def complete(
        self,
        messages: list[dict[str, str]],
        *,
        bot_config: dict[str, Any] | None = None,
        temperature: float = 0.6,
        max_tokens: int = 500,
    ) -> AiReply:
        config = bot_config or {}
        base_url, api_key, model = self.resolve(config)
        url = f"{base_url}/chat/completions"

        headers = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        started = time.monotonic()
        try:
            with httpx.Client(timeout=self._settings.ai_timeout) as client:
                response = client.post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            raise UpstreamError(f"AI provider unreachable: {exc}") from exc

        latency_ms = round((time.monotonic() - started) * 1000)

        if response.status_code == 401:
            raise UpstreamError("AI provider rejected the API key (401).")
        if response.status_code == 404:
            raise UpstreamError(
                f"AI endpoint not found ({url}). Check the base URL — for Ollama it usually "
                "ends with /v1."
            )
        if response.status_code >= 400:
            detail = response.text[:300]
            raise UpstreamError(f"AI provider error {response.status_code}: {detail}")

        try:
            data = response.json()
            text = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise UpstreamError(f"Unexpected AI response shape: {response.text[:200]}") from exc

        usage = data.get("usage") or {}
        return AiReply(
            text=(text or "").strip(),
            model=str(data.get("model") or model),
            prompt_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
            latency_ms=latency_ms,
        )

    def check(self, bot_config: dict[str, Any] | None = None) -> dict[str, Any]:
        """Round-trip the provider so the panel can prove it works."""
        started = time.monotonic()
        reply = self.complete(
            [{"role": "user", "content": "Reply with the single word: ok"}],
            bot_config=bot_config,
            temperature=0,
            max_tokens=5,
        )
        return {
            "ok": True,
            "model": reply.model,
            "latency_ms": round((time.monotonic() - started) * 1000),
            "sample": reply.text,
        }
