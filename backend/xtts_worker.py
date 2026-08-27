#!/usr/bin/env python3
"""
Studio-local XTTS worker — LIVE engines/xtts_engine only.

Loads XTTS **once**, synthesizes sentence chunks, writes one WAV.
Run with: christman_sound/.venv_py311/bin/python backend/xtts_worker.py ...
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import traceback
from pathlib import Path


def _studio_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _ensure_paths() -> None:
    root = _studio_root()
    sound = root / "christman_sound"
    sdk = sound / "christman_voice_sdk"
    for p in (sound, sdk):
        s = str(p)
        if p.is_dir() and s not in sys.path:
            sys.path.insert(0, s)


def _split_sentences(text: str, max_chars: int = 280) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    # Split on sentence ends, then pack up to max_chars
    parts = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    buf = ""
    for p in parts:
        p = p.strip()
        if not p:
            continue
        if not buf:
            buf = p
        elif len(buf) + 1 + len(p) <= max_chars:
            buf = f"{buf} {p}"
        else:
            chunks.append(buf)
            buf = p
        # hard split very long pieces
        while len(buf) > max_chars:
            chunks.append(buf[:max_chars].rsplit(" ", 1)[0] or buf[:max_chars])
            rest = buf[len(chunks[-1]) :].strip()
            buf = rest
    if buf:
        chunks.append(buf)
    return chunks


def synthesize_to_wav(text: str, ref_wav: Path, out_wav: Path, language: str = "en") -> None:
    os.environ.setdefault("COQUI_TOS_AGREED", "1")
    os.environ.setdefault("NUMBA_CACHE_DIR", "/tmp/christman_numba_cache")
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

    _ensure_paths()

    if not text or not text.strip():
        raise ValueError("empty text")
    if not ref_wav.is_file():
        raise FileNotFoundError(f"reference WAV not found: {ref_wav}")

    from engines.xtts_engine import XTTSEngine  # type: ignore
    import numpy as np
    from scipy.io.wavfile import write as write_wav

    max_chars = int(os.getenv("XTTS_CHUNK_CHARS", "280"))
    pieces = _split_sentences(text.strip(), max_chars=max_chars)
    print(f"CHUNKS {len(pieces)} total_chars={len(text)}", flush=True)

    engine = XTTSEngine(device="cpu")
    engine.load_voice(ref_wav)

    audio_parts: list[np.ndarray] = []
    sr = 24000
    for i, piece in enumerate(pieces):
        print(f"SYNTH {i+1}/{len(pieces)} chars={len(piece)}", flush=True)
        result = engine.synthesize(piece, language=language)
        if result is None or getattr(result, "audio", None) is None:
            raise RuntimeError(f"XTTS returned no audio for chunk {i+1}")
        arr = np.asarray(result.audio, dtype=np.float32)
        audio_parts.append(arr)
        sr = int(getattr(result, "sample_rate", sr) or sr)

    audio = np.concatenate(audio_parts) if len(audio_parts) > 1 else audio_parts[0]
    if audio.dtype != np.int16:
        audio = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    write_wav(str(out_wav), sr, audio)
    if not out_wav.is_file() or out_wav.stat().st_size < 100:
        raise RuntimeError(f"wrote empty/missing wav: {out_wav}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Brockston-Studio christman_sound XTTS worker")
    parser.add_argument("--text", default="", help="Text to synthesize")
    parser.add_argument("--text-file", type=Path, default=None, help="Read text from file (long)")
    parser.add_argument("--ref", required=True, type=Path, help="Reference WAV path")
    parser.add_argument("--out", required=True, type=Path, help="Output WAV path")
    parser.add_argument("--language", default="en")
    args = parser.parse_args()

    text = args.text
    if args.text_file and args.text_file.is_file():
        text = args.text_file.read_text(encoding="utf-8")

    try:
        synthesize_to_wav(text, args.ref, args.out, language=args.language)
        print(f"OK {args.out} {args.out.stat().st_size}", flush=True)
        return 0
    except Exception as exc:
        print(f"FAIL {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
