"""
Mistral — the Mistral button in Ask the Beings.

Order:
  1. Mistral's own API (api.mistral.ai) with the Mistral key from the key drop box.
  2. Only if the box has no Mistral key: Mistral-Nemotron on NVIDIA NIM
     (the answer says so).
  3. If there is no key of either kind, the answer says "no Mistral key".
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx

from .ai_client import get_ai_response
from .key_box import get as _box_get
from .nvidia_keys import mistral_nvidia_key

logger = logging.getLogger(__name__)

LLM_MODEL_GENERAL = os.getenv("LLM_MODEL_GENERAL", "llama3.2")

# Mistral's own API (OpenAI-style chat completions)
MISTRAL_CHAT_URL = os.getenv("MISTRAL_CHAT_URL", "https://api.mistral.ai/v1/chat/completions")
MISTRAL_MODEL = os.getenv("MISTRAL_MODEL", "mistral-large-latest")
MISTRAL_MAX_TOKENS = int(os.getenv("MISTRAL_MAX_TOKENS", "4096"))
MISTRAL_TEMPERATURE = float(os.getenv("MISTRAL_TEMPERATURE", "0.6"))
MISTRAL_TIMEOUT = float(os.getenv("MISTRAL_TIMEOUT_SEC", "180"))

NO_MISTRAL_KEY_MESSAGE = (
    "No Mistral key. Paste one in Settings → Key drop box → Mistral, then ask again."
)
NVIDIA_FALLBACK_NOTE = (
    "(No Mistral key in the key box, so this answer came from Mistral-Nemotron on NVIDIA.)"
)

NVIDIA_CHAT_URL = os.getenv(
    "NVIDIA_CHAT_URL",
    "https://integrate.api.nvidia.com/v1/chat/completions",
)
NVIDIA_MISTRAL_MODEL = os.getenv(
    "NVIDIA_MISTRAL_MODEL",
    "mistralai/mistral-nemotron",
)
NVIDIA_MISTRAL_TEMPERATURE = float(os.getenv("NVIDIA_MISTRAL_TEMPERATURE", "0.60"))
NVIDIA_MISTRAL_TOP_P = float(os.getenv("NVIDIA_MISTRAL_TOP_P", "0.70"))
NVIDIA_MISTRAL_MAX_TOKENS = int(os.getenv("NVIDIA_MISTRAL_MAX_TOKENS", "4096"))
# Official mistral-nemotron sample does not require reasoning_effort.
# Set NVIDIA_MISTRAL_REASONING_EFFORT=high only if your account supports it.
NVIDIA_MISTRAL_REASONING_EFFORT = os.getenv("NVIDIA_MISTRAL_REASONING_EFFORT", "").strip()
NVIDIA_MISTRAL_TIMEOUT = float(os.getenv("NVIDIA_MISTRAL_TIMEOUT_SEC", "180"))
NVIDIA_MISTRAL_MIN_INTERVAL = float(os.getenv("NVIDIA_MISTRAL_MIN_INTERVAL_SEC", "2.5"))
NVIDIA_MISTRAL_429_RETRIES = int(os.getenv("NVIDIA_MISTRAL_429_RETRIES", "3"))

_last_nvidia_call = 0.0

MISTRAL_SYSTEM = """You are Mistral in Brockston Studio — The Christman AI Project IDE.
Everett Christman is your partner. You reason carefully about architecture, trade-offs,
and complex engineering decisions. Be direct, structured, and honest.
You see workspace context from the IDE. Never use generic AI disclaimers."""


def _mistral_key() -> str:
    """NVIDIA-hosted Mistral-Nemotron key (fallback path)."""
    return mistral_nvidia_key()


def _direct_mistral_key() -> str:
    """Mistral's own API key, from the key drop box (env as fallback)."""
    return _box_get("MISTRAL_API_KEY")


def build_direct_request(system: str, user_content: str, key: str) -> Dict[str, Any]:
    """The exact request sent to Mistral's API (kept separate so it can be checked)."""
    return {
        "url": MISTRAL_CHAT_URL,
        "headers": {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        "json": {
            "model": MISTRAL_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ],
            "max_tokens": MISTRAL_MAX_TOKENS,
            "temperature": MISTRAL_TEMPERATURE,
            "stream": False,
        },
    }


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
                NVIDIA_MISTRAL_REASONING_EFFORT or "off",
            )
        else:
            logger.warning("[MistralService] NVIDIA_MISTRAL_API_KEY not set — fallback to Ollama")

    @property
    def is_available(self) -> bool:
        return True

    @property
    def uses_direct(self) -> bool:
        """True when the key box (or env) has Mistral's own API key."""
        return bool(_direct_mistral_key())

    @property
    def uses_nvidia(self) -> bool:
        """NVIDIA fallback is used only when there is no direct Mistral key."""
        return not self.uses_direct and bool(_mistral_key())

    @property
    def has_any_key(self) -> bool:
        return self.uses_direct or bool(_mistral_key())

    def wiring_info(self) -> Dict[str, Any]:
        if self.uses_direct:
            return {
                "backend": "mistral",
                "model": MISTRAL_MODEL,
                "label": f"{MISTRAL_MODEL} (Mistral API)",
                "url": MISTRAL_CHAT_URL.rsplit("/v1", 1)[0] + "/v1",
                "api_key_env": "MISTRAL_API_KEY",
                "api_key_set": True,
            }
        if self.uses_nvidia:
            return {
                "backend": "nvidia",
                "model": NVIDIA_MISTRAL_MODEL,
                "label": f"{NVIDIA_MISTRAL_MODEL} (NVIDIA NIM)",
                "url": NVIDIA_CHAT_URL.rsplit("/v1", 1)[0] + "/v1",
                "api_key_env": "NVIDIA_MISTRAL_API_KEY",
                "api_key_set": True,
                "reasoning_effort": NVIDIA_MISTRAL_REASONING_EFFORT or "off",
            }
        return {
            "backend": "none",
            "model": MISTRAL_MODEL,
            "label": "no Mistral key (paste one in Settings → Key drop box)",
            "api_key_env": "MISTRAL_API_KEY",
            "api_key_set": False,
        }

    def generate_content(self, prompt: str, context: Optional[str] = None, **_kwargs) -> str:
        """kwargs accepted so agent loops can pass mode=/model= without crashing."""
        system = MISTRAL_SYSTEM
        if context:
            system = f"{system}\n\n{context}"

        # 1. Mistral's own API. If it fails, say so; never pass someone else off as Mistral.
        if self.uses_direct:
            return self._call_direct(system=system, user_content=prompt)

        # 2. No Mistral key in the box: NVIDIA-hosted Mistral-Nemotron, labelled.
        if self.uses_nvidia:
            try:
                reply = self._call_nvidia(system=system, user_content=prompt)
                return f"{NVIDIA_FALLBACK_NOTE}\n\n{reply}"
            except Exception as exc:
                logger.warning("[Mistral] NVIDIA fallback failed (%s) — local Ollama", exc)
                reply = get_ai_response(prompt, system=system, target="ollama", model=LLM_MODEL_GENERAL)
                return (
                    f"(No Mistral key in the key box, and Mistral-Nemotron on NVIDIA failed: {exc}. "
                    f"This answer came from local {LLM_MODEL_GENERAL}.)\n\n{reply}"
                )

        # 3. No key at all.
        return NO_MISTRAL_KEY_MESSAGE

    def _call_direct(self, *, system: str, user_content: str) -> str:
        key = _direct_mistral_key()
        if not key:
            return NO_MISTRAL_KEY_MESSAGE
        req = build_direct_request(system, user_content, key)
        try:
            r = httpx.post(req["url"], headers=req["headers"], json=req["json"], timeout=MISTRAL_TIMEOUT)
        except httpx.TimeoutException:
            return f"Mistral didn't answer within {MISTRAL_TIMEOUT:.0f} seconds. Try again."
        except httpx.HTTPError as exc:
            return f"Couldn't reach Mistral ({type(exc).__name__}). Check the internet connection."
        if r.status_code in (401, 403):
            return "Mistral turned down the key in the key box (it may be wrong or expired). Paste a fresh one in Settings → Key drop box → Mistral."
        if r.status_code == 429:
            return "Mistral says it's rate limited right now. Try again in a minute."
        if r.status_code >= 400:
            logger.error("[Mistral] API %s: %s", r.status_code, r.text[:300])
            return f"Mistral returned an error ({r.status_code}): {r.text[:200]}"
        data = r.json()
        choices = data.get("choices") or []
        if not choices:
            return "Mistral sent back an empty answer."
        content = (choices[0].get("message") or {}).get("content") or ""
        if isinstance(content, list):  # newer models can return content chunks
            content = "".join(c.get("text", "") for c in content if isinstance(c, dict))
        return content.strip()

    def _build_payload(self, messages: List[Dict[str, str]], *, use_reasoning: bool) -> Dict[str, Any]:
        # Match NVIDIA docs for mistralai/mistral-nemotron
        payload: Dict[str, Any] = {
            "model": NVIDIA_MISTRAL_MODEL,
            "messages": messages,
            "max_tokens": NVIDIA_MISTRAL_MAX_TOKENS,
            "temperature": NVIDIA_MISTRAL_TEMPERATURE,
            "top_p": NVIDIA_MISTRAL_TOP_P,
            "stream": False,
        }
        if use_reasoning and NVIDIA_MISTRAL_REASONING_EFFORT:
            payload["reasoning_effort"] = NVIDIA_MISTRAL_REASONING_EFFORT
        return payload

    def _call_nvidia(self, *, system: str, user_content: str) -> str:
        if not _mistral_key():
            raise RuntimeError("NVIDIA_MISTRAL_API_KEY not set")

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]
        headers = {
            "Authorization": f"Bearer {_mistral_key()}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        # First try without reasoning_effort (official sample). Retry with it only if configured.
        attempts_plan: List[bool] = [False]
        if NVIDIA_MISTRAL_REASONING_EFFORT:
            attempts_plan.append(True)

        last_exc: Optional[Exception] = None
        backoff = [0, 3, 8]

        for use_reasoning in attempts_plan:
            payload = self._build_payload(messages, use_reasoning=use_reasoning)
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
                    # NVIDIA often returns 404 when the key cannot access that model function
                    if r.status_code in (404, 410):
                        detail = (r.text or "")[:240]
                        last_exc = RuntimeError(
                            f"NVIDIA {r.status_code} for model {NVIDIA_MISTRAL_MODEL} "
                            f"(account may lack this NIM, or model id wrong): {detail}"
                        )
                        logger.error("[Mistral] %s", last_exc)
                        # no point retrying same model
                        break
                    if r.status_code == 429:
                        last_exc = RuntimeError("NVIDIA rate limit (429) for Mistral-Nemotron")
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
                except httpx.TimeoutException as exc:
                    last_exc = RuntimeError(
                        f"NVIDIA timeout after {NVIDIA_MISTRAL_TIMEOUT:.0f}s for {NVIDIA_MISTRAL_MODEL}"
                    )
                    logger.warning("[Mistral] %s", last_exc)
                    continue
                except httpx.HTTPStatusError as exc:
                    code = exc.response.status_code
                    if code in (404, 410):
                        last_exc = RuntimeError(
                            f"NVIDIA {code} model/account not available for {NVIDIA_MISTRAL_MODEL}"
                        )
                        break
                    if code == 429:
                        last_exc = RuntimeError("NVIDIA rate limit (429) for Mistral-Nemotron")
                        continue
                    if 500 <= code < 600:
                        last_exc = RuntimeError(f"NVIDIA server error {code}")
                        continue
                    last_exc = RuntimeError(f"NVIDIA HTTP {code}: {exc.response.text[:200]}")
                    break
                except Exception as exc:
                    last_exc = exc
                    break
            else:
                continue
            # 404/410 broke out — try next plan or raise
            if last_exc and "404" in str(last_exc) or (last_exc and "410" in str(last_exc)):
                if use_reasoning is False and NVIDIA_MISTRAL_REASONING_EFFORT:
                    continue
                break

        raise last_exc or RuntimeError("NVIDIA Mistral-Nemotron unavailable")


_mistral_instance: Optional[MistralService] = None


def get_mistral_service() -> MistralService:
    global _mistral_instance
    if _mistral_instance is None:
        _mistral_instance = MistralService()
    return _mistral_instance
