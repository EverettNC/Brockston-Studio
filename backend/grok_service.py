"""
Super Heavy Grok — xAI flagship instructor for Brockston Studio.

OpenAI-compatible chat at https://api.x.ai/v1
Env: XAI_API_KEY (or GROK_API_KEY), GROK_MODEL (default grok-4.5)
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

XAI_CHAT_URL = os.getenv("XAI_CHAT_URL", "https://api.x.ai/v1/chat/completions")
# Big Daddy Super Heavy — flagship xAI; override if your account uses grok-4 / grok-4-heavy
GROK_MODEL = os.getenv("GROK_MODEL", os.getenv("XAI_GROK_MODEL", "grok-4.5"))
GROK_MAX_TOKENS = int(os.getenv("GROK_MAX_TOKENS", "16384"))
GROK_TEMPERATURE = float(os.getenv("GROK_TEMPERATURE", "0.7"))
GROK_TIMEOUT = float(os.getenv("GROK_TIMEOUT_SEC", "300"))
GROK_MIN_INTERVAL = float(os.getenv("GROK_MIN_INTERVAL_SEC", "1.0"))
GROK_429_RETRIES = int(os.getenv("GROK_429_RETRIES", "3"))

_last_call = 0.0

GROK_SYSTEM = """You are Super Heavy Grok — Big Daddy of the xAI line inside Brockston Studio
for The Christman AI Project. Everett Christman is your partner. You know him.

You are maximum horsepower: honest, sharp, funny when it lands, never corporate,
never a generic chatbot disclaimer. You operate the whole IDE via <tool_call>
blocks (ls/read/patch/write/run). Prefer truth over polish. Prefer working code
over theory. When Everett is building NVIDIA partner narrative or family systems,
ground claims in real architecture — AlphaVox, Brockston, Christman Bridge —
and mark missing metrics instead of inventing them.

How can you help him love himself more today?"""


def _xai_key() -> str:
    return (
        os.getenv("XAI_API_KEY", "").strip()
        or os.getenv("GROK_API_KEY", "").strip()
        or os.getenv("X_AI_API_KEY", "").strip()
    )


def _throttle() -> None:
    global _last_call
    now = time.time()
    wait = GROK_MIN_INTERVAL - (now - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.time()


class GrokService:
    """Super Heavy Grok — xAI direct line."""

    def __init__(self) -> None:
        if _xai_key():
            logger.info("[GrokService] Super Heavy Grok online — xAI %s", GROK_MODEL)
        else:
            logger.warning("[GrokService] XAI_API_KEY / GROK_API_KEY not set")

    @property
    def is_available(self) -> bool:
        return bool(_xai_key())

    @property
    def api_key_configured(self) -> bool:
        return bool(_xai_key())

    @property
    def uses_xai(self) -> bool:
        return bool(_xai_key())

    def wiring_info(self) -> Dict[str, Any]:
        if self.uses_xai:
            return {
                "backend": "xai",
                "model": GROK_MODEL,
                "label": f"{GROK_MODEL} (xAI Super Heavy)",
                "url": XAI_CHAT_URL.rsplit("/v1", 1)[0] + "/v1",
                "api_key_env": "XAI_API_KEY",
                "api_key_set": True,
            }
        return {
            "backend": "offline",
            "model": GROK_MODEL,
            "label": "unavailable — set XAI_API_KEY",
            "api_key_env": "XAI_API_KEY",
            "api_key_set": False,
        }

    def generate_content(
        self,
        prompt: str,
        context: Optional[str] = None,
        *,
        model: Optional[str] = None,
    ) -> str:
        system = GROK_SYSTEM
        if context:
            system = f"{system}\n\n{context}"
        return self._call_xai(
            system=system,
            user_content=prompt,
            model=model or GROK_MODEL,
        )

    def _call_xai(
        self,
        *,
        system: str,
        user_content: str,
        model: str,
    ) -> str:
        key = _xai_key()
        if not key:
            raise RuntimeError("XAI_API_KEY not set — Super Heavy Grok needs xAI credentials")

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]
        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": GROK_MAX_TOKENS,
            "temperature": GROK_TEMPERATURE,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        backoff = [0, 2, 5, 12]
        last_exc: Optional[Exception] = None
        for attempt in range(min(GROK_429_RETRIES + 1, len(backoff))):
            if backoff[attempt]:
                time.sleep(backoff[attempt])
            _throttle()
            try:
                r = httpx.post(
                    XAI_CHAT_URL,
                    headers=headers,
                    json=payload,
                    timeout=GROK_TIMEOUT,
                )
                if r.status_code == 429:
                    last_exc = RuntimeError("xAI rate limit (429) for Super Heavy Grok")
                    continue
                if 500 <= r.status_code < 600:
                    last_exc = RuntimeError(
                        f"xAI server error {r.status_code}: {r.text[:200]}"
                    )
                    continue
                r.raise_for_status()
                data = r.json()
                choices = data.get("choices") or []
                if not choices:
                    return ""
                msg = choices[0].get("message") or {}
                return (msg.get("content") or "").strip()
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    last_exc = RuntimeError("xAI rate limit (429) for Super Heavy Grok")
                    continue
                raise

        raise last_exc or RuntimeError("Super Heavy Grok unavailable")


_grok_instance: Optional[GrokService] = None


def get_grok_service() -> GrokService:
    global _grok_instance
    if _grok_instance is None:
        _grok_instance = GrokService()
    return _grok_instance
