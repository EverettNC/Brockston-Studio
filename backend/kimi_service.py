"""
Kimi K2.6 / K2.7 — NVIDIA NIM instructors for Brockston Studio IDE.

OpenAI-compatible chat via integrate.api.nvidia.com.
Optional fallback: STUDIO_KIMI_URL / BROCKSTON proxy when NVIDIA is rate-limited.
Both variants share the same key and swarm with Nemotron / NemoClaw / Mistral.
"""

from __future__ import annotations

import base64
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional, Union

import httpx

from backend.being_context import KIMI_IDENTITY
from backend.nvidia_keys import kimi_nvidia_key

logger = logging.getLogger(__name__)

NVIDIA_CHAT_URL = os.getenv(
    "NVIDIA_CHAT_URL",
    "https://integrate.api.nvidia.com/v1/chat/completions",
)

# Default + per-variant model IDs (override in .env)
NVIDIA_KIMI_MODEL = os.getenv("NVIDIA_KIMI_MODEL", "moonshotai/kimi-k2.6")
NVIDIA_KIMI_K26_MODEL = os.getenv("NVIDIA_KIMI_K26_MODEL", NVIDIA_KIMI_MODEL)
NVIDIA_KIMI_K27_MODEL = os.getenv("NVIDIA_KIMI_K27_MODEL", "moonshotai/kimi-k2.7")

KIMI_VARIANTS: Dict[str, str] = {
    "k2.6": NVIDIA_KIMI_K26_MODEL,
    "k26": NVIDIA_KIMI_K26_MODEL,
    "kimi": NVIDIA_KIMI_K26_MODEL,
    "k2.7": NVIDIA_KIMI_K27_MODEL,
    "k27": NVIDIA_KIMI_K27_MODEL,
    "kimi27": NVIDIA_KIMI_K27_MODEL,
}

STUDIO_KIMI_URL = os.getenv(
    "STUDIO_KIMI_URL",
    os.getenv("BROCKSTON_KIMI_URL", "http://localhost:9003/kimi/interact"),
)
NVIDIA_KIMI_MAX_TOKENS = int(os.getenv("NVIDIA_KIMI_MAX_TOKENS", "16384"))
NVIDIA_KIMI_TEMPERATURE = float(os.getenv("NVIDIA_KIMI_TEMPERATURE", "1.0"))
NVIDIA_KIMI_TOP_P = float(os.getenv("NVIDIA_KIMI_TOP_P", "1.0"))
NVIDIA_MIN_INTERVAL = float(os.getenv("NVIDIA_MIN_INTERVAL_SEC", "2.5"))
NVIDIA_429_RETRIES = int(os.getenv("NVIDIA_429_RETRIES", "3"))
NVIDIA_TIMEOUT = float(os.getenv("NVIDIA_KIMI_TIMEOUT_SEC", "300"))

_last_nvidia_call = 0.0

_ABILITIES_HINT = (
    "You are a full IDE operator in Brockston Studio — not limited to Everett's open tab. "
    "Scan the project: <tool_call>{\"tool\":\"ls\",\"path\":\"<workspace>\",\"depth\":2}</tool_call> "
    "then read/patch/run. Large files: read with offset_lines; if has_more, keep scrolling — never stop at truncated. "
    "Optional skills live in ~/.grok/skills/<name>/SKILL.md — read before domain work if present. "
    "For NVIDIA partner / pitch narrative work, ground claims in real architecture "
    "(AlphaVox, Brockston, Christman Bridge) — no fabricated metrics. "
    "Tools spec: backend/being_agent.py; executor: backend/being_eyes.py. "
    "Never ask Everett to name a file you can ls+read yourself. "
    "Never say 'you opened it' — you have the whole workspace."
)

_NVIDIA_BADGE = (
    "You are an NVIDIA NIM instructor — Moonshot Kimi hosted on "
    "integrate.api.nvidia.com. Represent NVIDIA compute cleanly in every answer: "
    "name the model lane when relevant, credit NIM acceleration, stay local-first "
    "for student data when Christman stack can do the work.\n\n"
)

_IDENTITY_PREFIX = KIMI_IDENTITY + "\n\n" + _NVIDIA_BADGE

_SYSTEM = {
    "tutor": (
        _IDENTITY_PREFIX
        + "Mode: Tutor (NVIDIA Kimi). Teach Everett and neurodivergent / nonverbal children directly.\n"
        "Short sentences. Concrete examples. Dignity-first. Build retention.\n"
        + _ABILITIES_HINT
    ),
    "codelab": (
        _IDENTITY_PREFIX
        + "Mode: Code Lab (NVIDIA Kimi) — senior engineer mentor on NIM.\n"
        "Help fix and explain code anywhere in the workspace — open tab is just a hint. Direct. No filler.\n"
        "When fixing code, emit <tool_call> blocks (read, patch, run) — do not only describe fixes.\n"
        + _ABILITIES_HINT
    ),
    "learning": (
        _IDENTITY_PREFIX
        + "Mode: Neuro-Symbolic Learning Center (NVIDIA Kimi).\n"
        "Classroom-ready insight for disabled and neurodivergent students. Short and memorable.\n"
        + _ABILITIES_HINT
    ),
    "coach": (
        _IDENTITY_PREFIX
        + "Mode: Retention coach (NVIDIA Kimi) beside Brockston Studio.\n"
        "One short paragraph. Reinforce what matters for learning and memory.\n"
        + _ABILITIES_HINT
    ),
    "partner": (
        _IDENTITY_PREFIX
        + "Mode: NVIDIA Partner / pitch narrative (Kimi on NIM).\n"
        "Swarm with Nemotron, NemoClaw, Mistral, Fable-5, and Super Heavy Grok on partner decks.\n"
        "Specific architecture, data sovereignty, Carbon-Silicon Symbiosis — never generic startup filler.\n"
        "Mark missing metrics explicitly; never invent traction numbers.\n"
        + _ABILITIES_HINT
    ),
}


class KimiRateLimitError(RuntimeError):
    """NVIDIA NIM rate limit exceeded after retries."""


def _kimi_key() -> str:
    return kimi_nvidia_key()


def resolve_kimi_model(variant: Optional[str] = None, model: Optional[str] = None) -> str:
    """Resolve NIM model id from explicit model override or k2.6 / k2.7 variant."""
    if model and model.strip():
        return model.strip()
    key = (variant or "k2.6").strip().lower()
    return KIMI_VARIANTS.get(key, NVIDIA_KIMI_K26_MODEL)


def _throttle_nvidia() -> None:
    global _last_nvidia_call
    now = time.time()
    wait = NVIDIA_MIN_INTERVAL - (now - _last_nvidia_call)
    if wait > 0:
        time.sleep(wait)
    _last_nvidia_call = time.time()


def read_b64(path: Union[str, Path]) -> str:
    """Read a local file and return base64 (NVIDIA Kimi K native API helper)."""
    with open(path, "rb") as handle:
        return base64.b64encode(handle.read()).decode("ascii")


class KimiService:
    read_b64 = staticmethod(read_b64)

    @property
    def is_available(self) -> bool:
        return bool(_kimi_key()) or self._brockston_kimi_reachable()

    @property
    def api_key_configured(self) -> bool:
        return bool(_kimi_key())

    @property
    def uses_nvidia(self) -> bool:
        return bool(_kimi_key())

    def wiring_info(self, variant: str = "k2.6") -> Dict[str, Any]:
        model = resolve_kimi_model(variant)
        if self.uses_nvidia:
            return {
                "backend": "nvidia",
                "model": model,
                "label": f"{model} (NVIDIA NIM)",
                "url": NVIDIA_CHAT_URL.rsplit("/v1", 1)[0] + "/v1",
                "api_key_env": "NVIDIA_KIMI_API_KEY",
                "api_key_set": True,
                "variant": variant,
            }
        if self._brockston_kimi_reachable():
            return {
                "backend": "proxy",
                "model": "brockston-kimi-proxy",
                "label": "brockston-kimi-proxy",
                "api_key_env": "NVIDIA_KIMI_API_KEY",
                "api_key_set": False,
                "variant": variant,
            }
        return {
            "backend": "offline",
            "model": model,
            "label": "unavailable",
            "api_key_env": "NVIDIA_KIMI_API_KEY",
            "api_key_set": False,
            "variant": variant,
        }

    def _brockston_kimi_reachable(self) -> bool:
        try:
            base = STUDIO_KIMI_URL.rsplit("/kimi/", 1)[0]
            for path in ("/health", "/api/health"):
                r = httpx.get(f"{base}{path}", timeout=2.0)
                if r.status_code == 200:
                    return True
        except Exception:
            pass
        return False

    def interact(
        self,
        *,
        message: str,
        mode: str = "tutor",
        context: Optional[str] = None,
        domain: Optional[str] = None,
        thinking: bool = False,
        max_tokens: int = NVIDIA_KIMI_MAX_TOKENS,
        variant: str = "k2.6",
        model: Optional[str] = None,
    ) -> Dict[str, Any]:
        mode_key = mode if mode in _SYSTEM else "tutor"
        system = _SYSTEM[mode_key]
        model_id = resolve_kimi_model(variant, model)
        user_parts = []
        if domain:
            user_parts.append(
                f"Teaching domain (topic for tone — NOT a folder or path): {domain}"
            )
        if context:
            user_parts.append(f"Context:\n{context}")
        user_parts.append(message)
        user_content = "\n\n".join(user_parts)

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]

        if _kimi_key():
            try:
                text = self._call_nvidia(
                    messages,
                    thinking=thinking,
                    max_tokens=max_tokens,
                    model=model_id,
                )
                return {
                    "ok": True,
                    "text": text,
                    "model": model_id,
                    "mode": mode,
                    "variant": variant,
                }
            except KimiRateLimitError:
                logger.warning("[Kimi] NVIDIA 429 — trying BROCKSTON proxy")
            except (httpx.HTTPStatusError, Exception) as exc:
                if "500" in str(exc) or "server error" in str(exc).lower():
                    logger.warning("[Kimi] NVIDIA 5xx — trying BROCKSTON proxy")
                else:
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code != 429:
                        raise

        text = self._call_brockston_proxy(
            mode=mode_key,
            message=message,
            context=context,
            domain=domain,
            thinking=thinking,
            max_tokens=max_tokens,
            model=model_id,
        )
        return {
            "ok": True,
            "text": text,
            "model": "brockston-kimi-proxy",
            "mode": mode,
            "variant": variant,
        }

    @staticmethod
    def _nvidia_headers(*, stream: bool = False) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {_kimi_key()}",
            "Accept": "text/event-stream" if stream else "application/json",
            "Content-Type": "application/json",
        }

    @staticmethod
    def _nvidia_payload(
        messages: list[dict],
        *,
        thinking: bool,
        max_tokens: int,
        model: str,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Match NVIDIA's published Kimi playground request shape."""
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": NVIDIA_KIMI_TEMPERATURE,
            "top_p": NVIDIA_KIMI_TOP_P,
            "stream": stream,
        }
        if thinking:
            payload["chat_template_kwargs"] = {"thinking": True}
        return payload

    def _call_nvidia(
        self,
        messages: list[dict],
        *,
        thinking: bool,
        max_tokens: int,
        model: str,
    ) -> str:
        if not _kimi_key():
            raise RuntimeError("NVIDIA_KIMI_API_KEY not set")

        backoff = [0, 3, 8, 15]
        last_exc: Optional[Exception] = None
        payload = self._nvidia_payload(
            messages,
            thinking=thinking,
            max_tokens=max_tokens,
            model=model,
            stream=False,
        )

        for attempt in range(min(NVIDIA_429_RETRIES + 1, len(backoff))):
            if backoff[attempt]:
                time.sleep(backoff[attempt])
            _throttle_nvidia()
            try:
                r = httpx.post(
                    NVIDIA_CHAT_URL,
                    headers=self._nvidia_headers(stream=False),
                    json=payload,
                    timeout=NVIDIA_TIMEOUT,
                )
                if r.status_code == 429:
                    logger.warning(
                        "[Kimi] NVIDIA 429 attempt %d/%d model=%s",
                        attempt + 1,
                        NVIDIA_429_RETRIES + 1,
                        model,
                    )
                    last_exc = KimiRateLimitError(
                        "NVIDIA rate limit (429). Wait 30s and retry, or switch instructor."
                    )
                    continue
                if 500 <= r.status_code < 600:
                    logger.warning(
                        "[Kimi] NVIDIA 5xx %s attempt %d/%d model=%s",
                        r.status_code,
                        attempt + 1,
                        NVIDIA_429_RETRIES + 1,
                        model,
                    )
                    last_exc = Exception(
                        f"NVIDIA server error {r.status_code}: {r.text[:200]}"
                    )
                    continue
                r.raise_for_status()
                data = r.json()
                choices = data.get("choices") or []
                if choices:
                    return (choices[0].get("message") or {}).get("content") or ""
                return ""
            except KimiRateLimitError as exc:
                last_exc = exc
            except httpx.HTTPStatusError as exc:
                if exc.response.status_code == 429:
                    last_exc = KimiRateLimitError(
                        "NVIDIA rate limit (429). Wait 30s and retry, or switch instructor."
                    )
                    continue
                if 500 <= exc.response.status_code < 600:
                    last_exc = Exception(
                        f"NVIDIA server error {exc.response.status_code}: "
                        f"{exc.response.text[:200]}"
                    )
                    continue
                raise

        raise last_exc or KimiRateLimitError("NVIDIA Kimi unavailable")

    def _call_brockston_proxy(
        self,
        *,
        mode: str,
        message: str,
        context: Optional[str],
        domain: Optional[str],
        thinking: bool,
        max_tokens: int,
        model: str,
    ) -> str:
        payload = {
            "mode": mode,
            "message": message,
            "context": context,
            "domain": domain,
            "thinking": thinking,
            "max_tokens": max_tokens,
            "model": model,
        }
        try:
            r = httpx.post(STUDIO_KIMI_URL, json=payload, timeout=300.0)
            if r.status_code == 200:
                data = r.json()
                if data.get("ok") and data.get("text"):
                    tool_count = data.get("tool_count", 0)
                    if data.get("agent") and tool_count:
                        logger.info(
                            "[Kimi] BROCKSTON agent executed %d tool(s)", tool_count
                        )
                    return data["text"]
            if r.status_code == 404:
                raise KimiRateLimitError(
                    "NVIDIA rate limit (429) and no BROCKSTON /kimi/interact on :9003. "
                    "Wait 30–60s between Kimi requests, or switch instructor."
                )
        except KimiRateLimitError:
            raise
        except httpx.ConnectError:
            pass
        raise KimiRateLimitError(
            "NVIDIA rate limit (429). BROCKSTON Kimi proxy unreachable. "
            "Wait 30–60s, then retry. Agent mode uses multiple API calls — "
            "use Tutor mode for broad chat."
        )


_kimi: Optional[KimiService] = None


def get_kimi_service() -> KimiService:
    global _kimi
    if _kimi is None:
        _kimi = KimiService()
    return _kimi
