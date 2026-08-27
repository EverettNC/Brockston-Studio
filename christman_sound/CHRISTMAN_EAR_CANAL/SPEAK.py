"""SPEAK.py — speech output via LIVE christman_voice_sdk engines.

Order (closed-loop, honest):
  1. christman_voice_sdk.synthesize_to_wav  (Shorty → XTTSEngine)
  2. macOS `say` only if allow_fallback=True

core.py is not used. gTTS is not used.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Optional

from ._paths import ensure_family_paths, require_file


def speak(
    text: str,
    emotion: str = "neutral",
    reference_audio: str | Path | None = None,
    allow_fallback: bool = True,
    play: bool = True,
) -> Dict[str, Any]:
    """Speak text using live christman_voice_sdk engines + optional macOS fallback."""
    ensure_family_paths()

    if not text or not text.strip():
        raise ValueError("text is required")

    # Prefer explicit ref; else config models.reference_audio
    ref: Optional[Path] = None
    xtts_error = ""
    try:
        from audio.config import get_config

        config = get_config()
        default_ref = config.get("models.reference_audio", "models/default_voice.wav")
    except Exception:
        default_ref = "models/default_voice.wav"

    try:
        ref = require_file(reference_audio or default_ref, "Reference voice WAV")
    except Exception as exc:
        xtts_error = f"reference: {type(exc).__name__}: {exc}"
        ref = None

    os.environ.setdefault("COQUI_TOS_AGREED", "1")
    os.environ.setdefault("NUMBA_CACHE_DIR", "/tmp/christman_numba_cache")

    if ref is not None:
        try:
            from christman_voice_sdk import play_audio, synthesize_to_wav, wait_for_playback

            wav = synthesize_to_wav(
                text=text.strip(),
                reference_audio=ref,
                emotion=emotion or "neutral",
            )
            if wav and Path(wav).is_file():
                engine_tag = "christman_voice_sdk_xtts"
                tag_file = Path(wav).with_suffix(".engine.txt")
                if tag_file.is_file():
                    engine_tag = f"christman_voice_sdk_{tag_file.read_text(encoding='utf-8').strip()}"
                    try:
                        tag_file.unlink()
                    except Exception:
                        pass
                played = False
                if play:
                    played = bool(play_audio(wav))
                    if played:
                        wait_for_playback()
                return {
                    "status": "spoken",
                    "engine": engine_tag,
                    "wav": str(wav),
                    "played": played,
                }
            xtts_error = "synthesize_to_wav returned no WAV"
        except Exception as exc:
            xtts_error = f"{type(exc).__name__}: {exc}"

    if allow_fallback and shutil.which("say"):
        subprocess.run(["say", text], check=True, timeout=60)
        return {
            "status": "spoken",
            "engine": "macos_say_fallback",
            "wav": None,
            "played": True,
            "xtts_error": xtts_error or "closed-loop XTTS unavailable",
        }

    return {
        "status": "failed",
        "engine": "none",
        "wav": None,
        "played": False,
        "xtts_error": xtts_error or "no engine available",
    }
