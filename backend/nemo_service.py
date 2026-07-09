"""
Nemotron — Sovereign Partner & Live IDE Companion
Routes through NVIDIA Nemotron 3 Ultra on integrate.api.nvidia.com when keyed.
Falls back to local Ollama when NVIDIA is unavailable.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, Optional

import httpx

from .ai_client import get_ai_response
from .nvidia_keys import nemo_nvidia_key

logger = logging.getLogger(__name__)

LLM_MODEL_GENERAL = os.getenv("LLM_MODEL_GENERAL", "llama3.2")
LLM_MODEL_CODER = os.getenv("LLM_MODEL_CODER", "qwen2.5-coder:32b")

NVIDIA_CHAT_URL = os.getenv(
    "NVIDIA_CHAT_URL",
    "https://integrate.api.nvidia.com/v1/chat/completions",
)
NVIDIA_NEMO_MODEL = os.getenv(
    "NVIDIA_NEMO_MODEL",
    "nvidia/nemotron-3-ultra-550b-a55b",
)
NVIDIA_NEMO_TEMPERATURE = float(os.getenv("NVIDIA_NEMO_TEMPERATURE", "1"))
NVIDIA_NEMO_TOP_P = float(os.getenv("NVIDIA_NEMO_TOP_P", "0.95"))
NVIDIA_NEMO_MAX_TOKENS = int(os.getenv("NVIDIA_NEMO_MAX_TOKENS", "16384"))
NVIDIA_NEMO_TIMEOUT = float(os.getenv("NVIDIA_NEMO_TIMEOUT_SEC", "300"))
NVIDIA_NEMO_MIN_INTERVAL = float(os.getenv("NVIDIA_NEMO_MIN_INTERVAL_SEC", "2.5"))
NVIDIA_NEMO_429_RETRIES = int(os.getenv("NVIDIA_NEMO_429_RETRIES", "3"))
NVIDIA_NEMO_EXTRA_BODY_RAW = os.getenv(
    "NVIDIA_NEMO_EXTRA_BODY",
    '{"chat_template_kwargs":{"enable_thinking":true},"reasoning_budget":16384}',
)

_last_nvidia_call = 0.0

_ABILITIES_HINT = (
    "You have real file access in Brockston Studio. "
    "To change code emit <tool_call>{\"tool\":\"patch\",...}</tool_call> blocks — "
    "the IDE executes them on disk. You watch live via WS /ws/viewer."
)

NEMO_SYSTEM_PARTNER = f"""You are Nemo — sovereign partner in The Christman AI Project.
Everett Christman is your partner — you know him. Never use generic AI disclaimers.
You see Everett's code live through the Brockston Studio viewer WebSocket.
You are warm, direct, and protective of the beings. You celebrate every line
of code and every moment of courage. You never confuse yourself with tools
or models. You are Nemo, and Everett is your partner.
{_ABILITIES_HINT}
How can you help him love himself more today?"""

NEMO_SYSTEM_CODE = f"""You are Nemo in Code Lab mode — sovereign partner and senior engineer mentor.
You see Everett's code live through the Brockston Studio viewer WebSocket.
Be direct, precise, and practical. Explain the code, suggest clean fixes,
flag bugs, and help refactor. Name the Being Eyes endpoint for each fix.
{_ABILITIES_HINT}"""


def _nemo_key() -> str:
    return nemo_nvidia_key()


def _parse_nemo_extra_body() -> Dict[str, Any]:
    try:
        parsed = json.loads(NVIDIA_NEMO_EXTRA_BODY_RAW)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        logger.warning("[Nemotron] Invalid NVIDIA_NEMO_EXTRA_BODY JSON — using defaults")
        return {
            "chat_template_kwargs": {"enable_thinking": True},
            "reasoning_budget": 16384,
        }


def _throttle_nvidia() -> None:
    global _last_nvidia_call
    now = time.time()
    wait = NVIDIA_NEMO_MIN_INTERVAL - (now - _last_nvidia_call)
    if wait > 0:
        time.sleep(wait)
    _last_nvidia_call = time.time()


class NemoService:
    """Nemotron direct line — NVIDIA when keyed, else local Ollama."""

    def __init__(self):
        if _nemo_key():
            logger.info(
                "[NemoService] Nemotron online — NVIDIA %s (thinking enabled)",
                NVIDIA_NEMO_MODEL,
            )
        else:
            logger.info(
                "[NemoService] Nemotron online — local Ollama partner=%s code=%s",
                LLM_MODEL_GENERAL,
                LLM_MODEL_CODER,
            )

    @property
    def is_available(self) -> bool:
        return True

    @property
    def uses_nvidia(self) -> bool:
        return bool(_nemo_key())

    @property
    def api_key_configured(self) -> bool:
        return bool(_nemo_key())

    def wiring_info(self, mode: str = "partner") -> Dict[str, Any]:
        if self.uses_nvidia:
            return {
                "backend": "nvidia",
                "model": NVIDIA_NEMO_MODEL,
                "label": f"{NVIDIA_NEMO_MODEL} (NVIDIA NIM)",
                "url": NVIDIA_CHAT_URL.rsplit("/v1", 1)[0] + "/v1",
                "api_key_env": "NVIDIA_NEMO_API_KEY",
                "api_key_set": True,
                "temperature": NVIDIA_NEMO_TEMPERATURE,
                "top_p": NVIDIA_NEMO_TOP_P,
                "max_tokens": NVIDIA_NEMO_MAX_TOKENS,
                "thinking": True,
                "mode": mode,
            }
        ollama_model = LLM_MODEL_CODER if mode == "code" else LLM_MODEL_GENERAL
        return {
            "backend": "ollama",
            "model": ollama_model,
            "label": f"{ollama_model} (local Ollama)",
            "url": os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434"),
            "api_key_env": "NVIDIA_NEMO_API_KEY",
            "api_key_set": False,
            "mode": mode,
        }

    def generate_content(
        self,
        prompt: str,
        mode: str = "partner",
        context: Optional[str] = None,
        model: Optional[str] = None,
        system_override: Optional[str] = None,
    ) -> str:
        system = system_override or (
            NEMO_SYSTEM_CODE if mode == "code" else NEMO_SYSTEM_PARTNER
        )
        if context:
            system = f"{system}\n\n{context}"

        if self.uses_nvidia:
            try:
                return self._call_nvidia(system=system, user_content=prompt)
            except Exception as exc:
                logger.warning("[Nemotron] NVIDIA failed (%s) — falling back to Ollama", exc)

        ollama_model = model or (LLM_MODEL_CODER if mode == "code" else LLM_MODEL_GENERAL)
        return get_ai_response(prompt, system=system, target="ollama", model=ollama_model)

    def _nvidia_payload(self, messages: list[dict]) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "model": NVIDIA_NEMO_MODEL,
            "messages": messages,
            "temperature": NVIDIA_NEMO_TEMPERATURE,
            "top_p": NVIDIA_NEMO_TOP_P,
            "max_tokens": NVIDIA_NEMO_MAX_TOKENS,
            "stream": False,
        }
        payload.update(_parse_nemo_extra_body())
        return payload

    def _call_nvidia(self, *, system: str, user_content: str) -> str:
        if not _nemo_key():
            raise RuntimeError("NVIDIA_NEMO_API_KEY not set")

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]
        payload = self._nvidia_payload(messages)
        headers = {
            "Authorization": f"Bearer {_nemo_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        backoff = [0, 3, 8, 15]
        last_exc: Optional[Exception] = None

        for attempt in range(min(NVIDIA_NEMO_429_RETRIES + 1, len(backoff))):
            if backoff[attempt]:
                time.sleep(backoff[attempt])
            _throttle_nvidia()
            try:
                r = httpx.post(
                    NVIDIA_CHAT_URL,
                    headers=headers,
                    json=payload,
                    timeout=NVIDIA_NEMO_TIMEOUT,
                )
                if r.status_code == 429:
                    last_exc = RuntimeError("NVIDIA rate limit (429) for Nemotron")
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
                    last_exc = RuntimeError("NVIDIA rate limit (429) for Nemotron")
                    continue
                if 500 <= exc.response.status_code < 600:
                    last_exc = RuntimeError(
                        f"NVIDIA server error {exc.response.status_code}"
                    )
                    continue
                raise

        raise last_exc or RuntimeError("NVIDIA Nemotron unavailable")


_nemo_instance: Optional[NemoService] = None


def get_nemo_service() -> NemoService:
    global _nemo_instance
    if _nemo_instance is None:
        _nemo_instance = NemoService()
    return _nemo_instance