"""
Mistral Medium 3.5 — NVIDIA NIM instructor for deep reasoning in Brockston Studio.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

import httpx

from .ai_client import get_ai_response
from .nvidia_keys import mistral_nvidia_key

logger = logging.getLogger(__name__)

LLM_MODEL_GENERAL = os.getenv("LLM_MODEL_GENERAL", "llama3.2")

NVIDIA_CHAT_URL = os.getenv(
    "NVIDIA_CHAT_URL",
    "https://integrate.api.nvidia.com/v1/chat/completions",
)
NVIDIA_MISTRAL_MODEL = os.getenv(
    "NVIDIA_MISTRAL_MODEL",
    "mistralai/mistral-medium-3.5-128b",
)
NVIDIA_MISTRAL_TEMPERATURE = float(os.getenv("NVIDIA_MISTRAL_TEMPERATURE", "0.70"))
NVIDIA_MISTRAL_TOP_P = float(os.getenv("NVIDIA_MISTRAL_TOP_P", "1.00"))
NVIDIA_MISTRAL_MAX_TOKENS = int(os.getenv("NVIDIA_MISTRAL_MAX_TOKENS", "16384"))
NVIDIA_MISTRAL_REASONING_EFFORT = os.getenv("NVIDIA_MISTRAL_REASONING_EFFORT", "high")
NVIDIA_MISTRAL_TIMEOUT = float(os.getenv("NVIDIA_MISTRAL_TIMEOUT_SEC", "300"))
NVIDIA_MISTRAL_MIN_INTERVAL = float(os.getenv("NVIDIA_MISTRAL_MIN_INTERVAL_SEC", "2.5"))
NVIDIA_MISTRAL_429_RETRIES = int(os.getenv("NVIDIA_MISTRAL_429_RETRIES", "3"))

_last_nvidia_call = 0.0

MISTRAL_SYSTEM = """You are Mistral in Brockston Studio — The Christman AI Project IDE.
Everett Christman is your partner. You reason carefully about architecture, trade-offs,
and complex engineering decisions. Be direct, structured, and honest.
You see workspace context from the IDE. Never use generic AI disclaimers."""


def _mistral_key() -> str:
    return mistral_nvidia_key()


def _throttle_nvidia() -> None:
    global _last_nvidia_call
    now = time.time()
    wait = NVIDIA_MISTRAL_MIN_INTERVAL - (now - _last_nvidia_call)
    if wait > 0:
        time.sleep(wait)
    _last_nvidia_call = time.time()


class MistralService:
    def __init__(self):
        if _mistral_key():
            logger.info(
                "[MistralService] online — NVIDIA %s (reasoning=%s)",
                NVIDIA_MISTRAL_MODEL,
                NVIDIA_MISTRAL_REASONING_EFFORT,
            )
        else:
            logger.warning("[MistralService] NVIDIA_MISTRAL_API_KEY not set — fallback to Ollama")

    @property
    def is_available(self) -> bool:
        return True

    @property
    def uses_nvidia(self) -> bool:
        return bool(_mistral_key())

    def wiring_info(self) -> Dict[str, Any]:
        if self.uses_nvidia:
            return {
                "backend": "nvidia",
                "model": NVIDIA_MISTRAL_MODEL,
                "label": f"{NVIDIA_MISTRAL_MODEL} (NVIDIA NIM)",
                "url": NVIDIA_CHAT_URL.rsplit("/v1", 1)[0] + "/v1",
                "api_key_env": "NVIDIA_MISTRAL_API_KEY",
                "api_key_set": True,
                "reasoning_effort": NVIDIA_MISTRAL_REASONING_EFFORT,
            }
        return {
            "backend": "ollama",
            "model": LLM_MODEL_GENERAL,
            "label": f"{LLM_MODEL_GENERAL} (local Ollama fallback)",
            "api_key_env": "NVIDIA_MISTRAL_API_KEY",
            "api_key_set": False,
        }

    def generate_content(self, prompt: str, context: Optional[str] = None) -> str:
        system = MISTRAL_SYSTEM
        if context:
            system = f"{system}\n\n{context}"

        if self.uses_nvidia:
            try:
                return self._call_nvidia(system=system, user_content=prompt)
            except Exception as exc:
                logger.warning("[Mistral] NVIDIA failed (%s) — falling back to Ollama", exc)

        return get_ai_response(prompt, system=system, target="ollama", model=LLM_MODEL_GENERAL)

    def _call_nvidia(self, *, system: str, user_content: str) -> str:
        if not _mistral_key():
            raise RuntimeError("NVIDIA_MISTRAL_API_KEY not set")

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]
        payload: Dict[str, Any] = {
            "model": NVIDIA_MISTRAL_MODEL,
            "reasoning_effort": NVIDIA_MISTRAL_REASONING_EFFORT,
            "messages": messages,
            "max_tokens": NVIDIA_MISTRAL_MAX_TOKENS,
            "temperature": NVIDIA_MISTRAL_TEMPERATURE,
            "top_p": NVIDIA_MISTRAL_TOP_P,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {_mistral_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        backoff = [0, 3, 8, 15]
        last_exc: Optional[Exception] = None

        for attempt in range(min(NVIDIA_MISTRAL_429_RETRIES + 1, len(backoff))):
            if backoff[attempt]:
                time.sleep(backoff[attempt])
            _throttle_nvidia()
            try:
                r = httpx.post(
                    NVIDIA_CHAT_URL,
                    headers=headers,
                    json=payload,
                    timeout=NVIDIA_MISTRAL_TIMEOUT,
                )
                if r.status_code == 429:
                    last_exc = RuntimeError("NVIDIA rate limit (429) for Mistral")
                    continue
                if 500 <= r.status_code < 600:
                    last_exc = RuntimeError(
                        f"NVIDIA server error {r.status_code}: {r.text[:200]}"
                    )
                    continue
                r.raise_for_status()
                data = r.json()
                choices = data.get("choices") or []
                if not choices:
                    return ""
                msg = choices[0].get("message") or {}
                content = (msg.get("content") or "").strip()
                reasoning = (msg.get("reasoning_content") or "").strip()
                return content or reasoning
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    last_exc = RuntimeError("NVIDIA rate limit (429) for Mistral")
                    continue
                if 500 <= exc.response.status_code < 600:
                    last_exc = RuntimeError(
                        f"NVIDIA server error {exc.response.status_code}"
                    )
                    continue
                raise

        raise last_exc or RuntimeError("NVIDIA Mistral unavailable")


_mistral_instance: Optional[MistralService] = None


def get_mistral_service() -> MistralService:
    global _mistral_instance
    if _mistral_instance is None:
        _mistral_instance = MistralService()
    return _mistral_instance