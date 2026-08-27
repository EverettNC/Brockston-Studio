#!/usr/bin/env python3
"""
Warm XTTS daemon — keeps christman_voice_sdk XTTSEngine loaded in memory.

Listen: http://127.0.0.1:8766
  GET  /health
  POST /synth  JSON { "text": "...", "ref": "/path/to.wav", "language": "en" }
       → audio/wav bytes

Run with christman_sound/.venv_py311 only.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

# ── paths ─────────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
SOUND = ROOT / "christman_sound"
SDK = SOUND / "christman_voice_sdk"
for p in (SOUND, SDK):
    s = str(p)
    if p.is_dir() and s not in sys.path:
        sys.path.insert(0, s)

os.environ.setdefault("COQUI_TOS_AGREED", "1")
os.environ.setdefault("NUMBA_CACHE_DIR", "/tmp/christman_numba_cache")
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

HOST = os.getenv("CHRISTMAN_XTTS_HOST", "127.0.0.1")
PORT = int(os.getenv("CHRISTMAN_XTTS_PORT", "8766"))
CHUNK = int(os.getenv("XTTS_CHUNK_CHARS", "280"))

_lock = threading.Lock()
_engine = None
_loaded_ref: str | None = None
_ready = False
_last_error = ""


def _split(text: str, max_chars: int = CHUNK) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
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
        while len(buf) > max_chars:
            cut = buf[:max_chars].rsplit(" ", 1)[0] or buf[:max_chars]
            chunks.append(cut)
            buf = buf[len(cut) :].strip()
    if buf:
        chunks.append(buf)
    return chunks


def _ensure_engine(ref: Path):
    global _engine, _loaded_ref, _ready, _last_error
    from engines.xtts_engine import XTTSEngine  # type: ignore

    ref_s = str(ref.resolve())
    if _engine is not None and _loaded_ref == ref_s:
        return _engine
    print(f"[xtts_server] Loading XTTS ref={ref.name}", flush=True)
    eng = XTTSEngine(device="cpu")
    eng.load_voice(ref)
    _engine = eng
    _loaded_ref = ref_s
    _ready = True
    _last_error = ""
    print("[xtts_server] XTTS ready", flush=True)
    return _engine


def synthesize(text: str, ref: Path, language: str = "en") -> bytes:
    import numpy as np
    from scipy.io.wavfile import write as write_wav

    with _lock:
        engine = _ensure_engine(ref)
        pieces = _split(text)
        print(f"[xtts_server] synth chars={len(text)} chunks={len(pieces)}", flush=True)
        parts = []
        sr = 24000
        for i, piece in enumerate(pieces):
            print(f"[xtts_server] chunk {i+1}/{len(pieces)} ({len(piece)} chars)", flush=True)
            result = engine.synthesize(piece, language=language)
            if result is None or getattr(result, "audio", None) is None:
                raise RuntimeError(f"no audio chunk {i+1}")
            parts.append(np.asarray(result.audio, dtype=np.float32))
            sr = int(getattr(result, "sample_rate", sr) or sr)
        audio = np.concatenate(parts) if len(parts) > 1 else parts[0]
        if audio.dtype != np.int16:
            audio = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
        tmp = Path(tempfile.mktemp(suffix=".wav"))
        write_wav(str(tmp), sr, audio)
        data = tmp.read_bytes()
        tmp.unlink(missing_ok=True)
        return data


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(f"[xtts_server] {args[0]}", flush=True)

    def _json(self, code: int, obj: dict):
        import json

        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/health", "/"):
            self._json(
                200,
                {
                    "status": "ok" if _ready else "loading",
                    "ready": _ready,
                    "ref": _loaded_ref,
                    "port": PORT,
                    "last_error": _last_error,
                },
            )
            return
        self._json(404, {"status": "error", "detail": "not found"})

    def do_POST(self):
        global _last_error
        path = urlparse(self.path).path
        if path != "/synth":
            self._json(404, {"status": "error", "detail": "not found"})
            return
        import json

        n = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(n) if n else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            self._json(400, {"status": "error", "detail": "bad json"})
            return
        text = (payload.get("text") or "").strip()
        ref = Path(payload.get("ref") or "")
        language = payload.get("language") or "en"
        if not text:
            self._json(400, {"status": "error", "detail": "empty text"})
            return
        if not ref.is_file():
            self._json(400, {"status": "error", "detail": f"ref missing: {ref}"})
            return
        try:
            wav = synthesize(text, ref, language=language)
        except Exception as exc:
            _last_error = f"{type(exc).__name__}: {exc}"
            traceback.print_exc()
            self._json(500, {"status": "error", "detail": _last_error})
            return
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(wav)))
        self.send_header("X-Christman-Engine", "xtts_v2")
        self.end_headers()
        self.wfile.write(wav)


def main():
    # Optional warm ref at boot
    warm = os.getenv("CHRISTMAN_XTTS_WARM_REF", "").strip()
    if warm and Path(warm).is_file():
        try:
            with _lock:
                _ensure_engine(Path(warm))
        except Exception as exc:
            print(f"[xtts_server] warm failed: {exc}", flush=True)

    # Threaded: board + parallel readbacks must not block each other on one synth
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"[xtts_server] listening http://{HOST}:{PORT} (threaded)", flush=True)
    httpd.serve_forever()


if __name__ == "__main__":
    main()
