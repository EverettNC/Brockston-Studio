"""
christman_voice_sdk — LIVE public API (Brockston-Studio).

Runtime is the package tree under this directory:
  engines/  synthesis/  audio/  tone/  timbre/  integration/  ...

core.py (parent) is a symbolic guide only — not imported here.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Live modules use flat imports (engines.*, synthesis.*) — keep SDK root on path.
_SDK_ROOT = Path(__file__).resolve().parent
if str(_SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(_SDK_ROOT))

__all__ = [
    "XTTSEngine",
    "ShortyVoiceEngineV2",
    "VoiceSynthesisOrchestrator",
    "synthesize_to_wav",
    "play_audio",
    "wait_for_playback",
]


def __getattr__(name: str):
    """Lazy imports so import cost stays low when only one engine is needed."""
    if name == "XTTSEngine":
        from engines.xtts_engine import XTTSEngine

        return XTTSEngine
    if name == "ShortyVoiceEngineV2":
        from synthesis.shorty_voice_engine_v3 import ShortyVoiceEngineV2

        return ShortyVoiceEngineV2
    if name == "VoiceSynthesisOrchestrator":
        from synthesis.voice_synthesis_orchestrator import VoiceSynthesisOrchestrator

        return VoiceSynthesisOrchestrator
    if name == "synthesize_to_wav":
        return synthesize_to_wav
    if name == "play_audio":
        return play_audio
    if name == "wait_for_playback":
        return wait_for_playback
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def synthesize_to_wav(
    text: str,
    reference_audio: str | Path,
    output_path: str | Path | None = None,
    language: str = "en",
    emotion: str = "neutral",
) -> Optional[Path]:
    """
    Closed-loop local synthesis via live engines.

    Order:
      1. ShortyVoiceEngineV2 (emotion + XTTS) when available
      2. XTTSEngine direct

    Returns path to WAV, or None on failure. Never uses gTTS or core.py.
    """
    import os
    import tempfile

    import numpy as np
    from scipy.io.wavfile import write as write_wav

    os.environ.setdefault("COQUI_TOS_AGREED", "1")
    os.environ.setdefault("NUMBA_CACHE_DIR", "/tmp/christman_numba_cache")

    text = (text or "").strip()
    if not text:
        return None

    ref = Path(reference_audio)
    if not ref.is_file():
        return None

    out = Path(output_path) if output_path else Path(
        tempfile.mktemp(suffix=".wav", prefix="christman_sdk_")
    )

    result = None
    engine_name = "none"

    # 1) Shorty (live) — emotion layer + XTTS
    try:
        from synthesis.shorty_voice_engine_v3 import ShortyVoiceEngineV2

        shorty = ShortyVoiceEngineV2(reference_audio=ref)
        result = shorty.synthesize(
            text=text,
            emotion_params={"emotion": emotion or "neutral"},
        )
        engine_name = "shorty_xtts"
    except Exception:
        result = None

    # 2) XTTSEngine direct (live)
    if result is None or getattr(result, "audio", None) is None:
        try:
            from engines.xtts_engine import XTTSEngine

            engine = XTTSEngine()
            engine.load_voice(ref)
            result = engine.synthesize(text=text, language=language)
            engine_name = "xtts_engine"
        except Exception:
            return None

    if result is None or getattr(result, "audio", None) is None:
        return None

    audio = np.asarray(result.audio)
    if audio.dtype != np.int16:
        audio = (audio * 32767.0).astype(np.int16)
    sr = int(getattr(result, "sample_rate", 24000) or 24000)
    out.parent.mkdir(parents=True, exist_ok=True)
    write_wav(str(out), sr, audio)
    if not out.is_file() or out.stat().st_size < 100:
        return None
    # Stash engine name for honest callers
    try:
        out.with_suffix(".engine.txt").write_text(engine_name, encoding="utf-8")
    except Exception:
        pass
    return out


def play_audio(wav_path: str | Path) -> bool:
    """Play a WAV locally if possible. Returns True if playback was started."""
    path = Path(wav_path)
    if not path.is_file():
        return False
    try:
        import sounddevice as sd
        import soundfile as sf

        data, sr = sf.read(str(path), dtype="float32")
        sd.play(data, sr)
        return True
    except Exception:
        pass
    # afplay on macOS
    try:
        import subprocess
        import shutil

        if shutil.which("afplay"):
            subprocess.Popen(["afplay", str(path)])
            return True
    except Exception:
        pass
    return False


def wait_for_playback(timeout: float = 120.0) -> None:
    """Block until sounddevice playback finishes (no-op if not playing)."""
    try:
        import sounddevice as sd

        sd.wait()
    except Exception:
        pass
