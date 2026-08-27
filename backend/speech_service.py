"""
Speech Service

Handles speech-to-text transcription and text-to-speech synthesis.
"""

import os
import logging
from typing import Optional
import httpx
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Long chunks kill XTTS (cold load + RTF~2×). Keep closed-loop chunks short.
TTS_MAX_CHUNK_CHARS = int(os.getenv("TTS_MAX_CHUNK_CHARS", "3500"))
# Used for christman_sound XTTS worker path (macOS say can still use larger)
XTTS_CHUNK_CHARS = int(os.getenv("XTTS_CHUNK_CHARS", "280"))


def _chunk_text_for_tts(text: str, max_chars: int = TTS_MAX_CHUNK_CHARS) -> list[str]:
    """Split long replies at sentence boundaries so TTS reads the full message."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    if len(cleaned) <= max_chars:
        return [cleaned]
    chunks: list[str] = []
    rest = cleaned
    while rest:
        if len(rest) <= max_chars:
            chunks.append(rest)
            break
        window = rest[:max_chars]
        cut_at = -1
        for sep in ("\n\n", ". ", "? ", "! ", ".\n", ";\n", "\n", " "):
            idx = window.rfind(sep)
            if idx > max_chars // 3:
                cut_at = idx + len(sep)
                break
        if cut_at <= 0:
            cut_at = max_chars
        piece = rest[:cut_at].strip()
        if piece:
            chunks.append(piece)
        rest = rest[cut_at:].strip()
    return chunks


class SpeechService:
    """
    Service for speech operations: transcription and synthesis.
    """

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize speech service.

        Args:
            api_key: Optional API key for the configured speech provider
        """
        self.api_key = api_key or os.getenv("SPEECH_SERVICE_API_KEY")
        self.base_url = "https://api.speech-service.local"
        self.timeout = 60.0  # 60 seconds for audio processing
        # Rule 13 honesty — last engine used for readback (xtts vs robot fallback)
        self.last_engine: str = "unknown"
        self.last_engine_detail: str = ""

        if self.api_key:
            logger.info("Speech service initialized with configured API key")
        else:
            logger.info(
                "Speech service initialized without SPEECH_SERVICE_API_KEY "
                "(local christman_sound / macOS say only — not cloud STT mock for TTS)"
            )

    async def transcribe_audio(self, audio_data: bytes, filename: str = "audio.webm") -> str:
        """
        Transcribe audio to text using the configured speech service.

        Args:
            audio_data: Audio file bytes (supports mp3, mp4, mpeg, mpga, m4a, wav, webm)
            filename: Name of the audio file (with extension)

        Returns:
            Transcribed text

        Raises:
            RuntimeError: If transcription fails
        """
        # Wire to mcp-media-ingestor live ear bridge first (real-time improved ear with energy/tone).
        # This is the high-quality student "hear" path for the beings when the sensory bus is running.
        try:
            import httpx
            r = await httpx.AsyncClient(timeout=1.5).get("http://localhost:8765/latest")
            data = r.json()
            if data.get("text"):
                # Rich output from our processor: includes energy + tone now
                tone_info = f" [e:{data.get('energy')} t:{data.get('tone')}]" if data.get('energy') else ""
                return f"{data.get('text')}{tone_info}"
        except Exception:
            pass

        if not self.api_key:
            return self._mock_transcribe(audio_data, filename)

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                files = {
                    "file": (filename, audio_data, "audio/webm")
                }
                data = {
                    "model": "whisper-1"
                }
                headers = {
                    "Authorization": f"Bearer {self.api_key}"
                }

                response = await client.post(
                    f"{self.openai_url}/audio/transcriptions",
                    files=files,
                    data=data,
                    headers=headers
                )
                response.raise_for_status()

                result = response.json()
                return result.get("text", "")

        except httpx.HTTPError as e:
            logger.error(f"Transcription failed: {e}")
            raise RuntimeError(f"Failed to transcribe audio: {e}")

    async def synthesize_speech(self, text: str, voice_id: str = "default") -> bytes:
        """
        christman_sound XTTS when a being reference WAV exists, else macOS say.
        One XTTS worker call per utterance (model loads once; worker splits sentences).
        christman_sound only — ear canal, voice SDK, reference WAVs. No Polly/ElevenLabs.
        """
        import asyncio

        cleaned = (text or "").strip()
        if not cleaned:
            raise RuntimeError("No text to synthesize")

        logger.info("[TTS] synthesize %d char(s) voice_id=%s", len(cleaned), voice_id)

        loop = asyncio.get_event_loop()
        # Single pass: worker handles sentence packing (avoids N× model reloads)
        audio = await loop.run_in_executor(
            None, lambda: self._synthesize_one_chunk(cleaned, voice_id)
        )
        if not audio:
            raise RuntimeError("TTS produced no audio")
        return audio

    def _synthesize_one_chunk(self, text: str, voice_id: str) -> bytes | None:
        """Synthesize a single chunk — express → XTTS → macOS male say."""
        import subprocess
        import tempfile
        import os
        from pathlib import Path

        from backend.christman_sound_config import macos_voice_for_being, resolve_tts_being

        being = resolve_tts_being(voice_id)

        express_audio = self._audio_from_voice_center_express(text, being)
        if express_audio:
            self.last_engine = "voice_center_express"
            self.last_engine_detail = f"being={being}"
            return express_audio

        christman_audio = self._synthesize_christman_sound(text, being)
        if christman_audio:
            self.last_engine = "christman_sound_xtts"
            self.last_engine_detail = f"being={being}"
            return christman_audio

        # Apple TTS is OFF by default once closed-loop stack exists.
        # Set CHRISTMAN_ALLOW_ROBOT_TTS=1 only if you explicitly want macOS say.
        allow_robot = os.getenv("CHRISTMAN_ALLOW_ROBOT_TTS", "0").strip().lower() in (
            "1", "true", "yes", "on",
        )
        if not allow_robot:
            self.last_engine = "xtts_failed"
            self.last_engine_detail = (
                f"being={being} — closed-loop XTTS failed; Apple say blocked "
                f"(CHRISTMAN_ALLOW_ROBOT_TTS=0). Check warm server :8766 or logs."
            )
            logger.error(
                "[TTS] REFUSING Apple robot voice being=%s chars=%d — XTTS offline/slow. "
                "Start: christman_sound/.venv_py311/bin/python backend/xtts_server.py",
                being,
                len(text),
            )
            raise RuntimeError(
                "Closed-loop christman_sound XTTS unavailable — "
                "Apple TTS blocked. Warm XTTS server on :8766 or check logs/ide.log."
            )

        # macOS say — explicit opt-in only (not closed-loop)
        voice = macos_voice_for_being(voice_id)
        if voice_id and voice_id not in ("default", "") and voice_id in (
            "Daniel", "Fred", "Alex", "Albert", "Ralph", "Reed", "Eddy", "Grandpa"
        ):
            voice = voice_id

        aiff_path = tempfile.mktemp(suffix=".aiff")
        mp3_path = tempfile.mktemp(suffix=".mp3")

        try:
            r = subprocess.run(
                ["say", "-v", voice, "-o", aiff_path, text],
                capture_output=True,
                timeout=90,
            )
            if r.returncode != 0 or not Path(aiff_path).exists():
                raise RuntimeError(f"say failed: {r.stderr.decode()[:200]}")

            r = subprocess.run(
                ["ffmpeg", "-y", "-i", aiff_path,
                 "-codec:a", "libmp3lame", "-qscale:a", "2", mp3_path],
                capture_output=True,
                timeout=60,
            )
            if r.returncode != 0 or not Path(mp3_path).exists():
                raise RuntimeError(f"ffmpeg failed: {r.stderr.decode()[:200]}")

            audio = Path(mp3_path).read_bytes()
            self.last_engine = "macos_say_fallback"
            self.last_engine_detail = (
                f"voice={voice} being={being} — EXPLICIT robot fallback "
                f"(CHRISTMAN_ALLOW_ROBOT_TTS=1)"
            )
            logger.error(
                "[TTS] ROBOT VOICE (opt-in) — macOS say voice=%s being=%s (%d chars).",
                voice,
                being,
                len(text),
            )
            return audio

        finally:
            for p in (aiff_path, mp3_path):
                try:
                    os.unlink(p)
                except Exception:
                    pass
    @staticmethod
    def _concat_mp3(parts: list[bytes]) -> bytes:
        """Join MP3 chunks into one stream for uninterrupted playback."""
        import subprocess
        import tempfile
        import os
        from pathlib import Path

        if len(parts) == 1:
            return parts[0]

        temp_files: list[str] = []
        list_path = tempfile.mktemp(suffix=".txt")
        out_path = tempfile.mktemp(suffix=".mp3")
        try:
            with open(list_path, "w", encoding="utf-8") as handle:
                for i, blob in enumerate(parts):
                    chunk_path = tempfile.mktemp(suffix=f"_{i}.mp3")
                    Path(chunk_path).write_bytes(blob)
                    temp_files.append(chunk_path)
                    handle.write(f"file '{chunk_path}'\n")

            r = subprocess.run(
                [
                    "ffmpeg", "-y", "-f", "concat", "-safe", "0",
                    "-i", list_path, "-codec:a", "libmp3lame", "-qscale:a", "2", out_path,
                ],
                capture_output=True,
                timeout=120,
            )
            if r.returncode == 0 and Path(out_path).exists():
                logger.info("[TTS] concatenated %d chunks → %dKB", len(parts), Path(out_path).stat().st_size // 1024)
                return Path(out_path).read_bytes()
            logger.warning("[TTS] ffmpeg concat failed — returning first chunk only")
            return parts[0]
        finally:
            for p in temp_files + [list_path, out_path]:
                try:
                    os.unlink(p)
                except Exception:
                    pass

    def _audio_from_voice_center_express(self, text: str, being: str) -> bytes | None:
        """Voice_Creation_Center express cache — pre-rendered phrases."""
        import subprocess
        import tempfile
        from pathlib import Path

        try:
            from backend.christman_sound_config import try_express_audio

            raw = try_express_audio(text, being)
            if not raw:
                return None
            return self._to_mp3_bytes(raw)
        except Exception as exc:
            logger.debug("[TTS] Voice_Creation_Center express miss: %s", exc)
            return None

    @staticmethod
    def _to_mp3_bytes(audio: bytes) -> bytes | None:
        """Convert WAV/raw bytes to MP3 for the IDE player."""
        import subprocess
        import tempfile
        from pathlib import Path

        if audio[:4] == b"\xff\xfb" or audio[:3] == b"ID3":
            return audio
        wav_path = tempfile.mktemp(suffix=".wav")
        mp3_path = tempfile.mktemp(suffix=".mp3")
        try:
            Path(wav_path).write_bytes(audio)
            r = subprocess.run(
                ["ffmpeg", "-y", "-i", wav_path, "-codec:a", "libmp3lame", "-qscale:a", "2", mp3_path],
                capture_output=True,
                timeout=45,
            )
            if r.returncode != 0 or not Path(mp3_path).exists():
                return None
            return Path(mp3_path).read_bytes()
        finally:
            for p in (wav_path, mp3_path):
                try:
                    import os
                    os.unlink(p)
                except Exception:
                    pass

    def _synthesize_christman_sound(self, text: str, being: str) -> bytes | None:
        """
        Closed-loop christman_sound XTTS via Studio christman_voice_sdk.

        Order: warm daemon :8766 → in-process → cold worker subprocess.
        """
        from pathlib import Path

        try:
            from backend.christman_sound_config import (
                ensure_sound_paths,
                find_reference_wav,
                load_being_manifest,
                resolve_xtts_python,
                xtts_worker_script,
            )

            ensure_sound_paths()
            manifest = load_being_manifest(being)
            ref = find_reference_wav(being)
            if not ref:
                logger.warning(
                    "[TTS] No reference WAV for being=%s — cannot clone voice",
                    being,
                )
                return None

            chunk = text[:TTS_MAX_CHUNK_CHARS]

            # 1) Warm daemon (model stays loaded — kills Apple fallback from timeouts)
            warm = self._synthesize_xtts_daemon(chunk, ref)
            if warm:
                logger.info(
                    "[TTS] christman_sound XTTS daemon %dKB being=%s ref=%s",
                    len(warm) // 1024,
                    being,
                    ref.name,
                )
                return warm

            # 2) In-process (backend/venv usually lacks torch)
            in_proc = self._synthesize_xtts_inprocess(chunk, ref)
            if in_proc:
                logger.info(
                    "[TTS] christman_sound XTTS in-process %dKB being=%s pack=%s ref=%s",
                    len(in_proc) // 1024,
                    being,
                    (manifest or {}).get("pack_id"),
                    ref.name,
                )
                return in_proc

            # 3) Cold worker
            xtts_py = resolve_xtts_python()
            worker = xtts_worker_script()
            if not xtts_py:
                logger.warning(
                    "[TTS] No Studio XTTS python (need torch+TTS in christman_sound/.venv_py311). being=%s",
                    being,
                )
                return None
            if not worker.is_file():
                logger.warning("[TTS] xtts_worker.py missing at %s", worker)
                return None

            via_worker = self._synthesize_xtts_worker(chunk, ref, xtts_py, worker)
            if via_worker:
                logger.info(
                    "[TTS] christman_sound XTTS worker %dKB being=%s ref=%s py=%s",
                    len(via_worker) // 1024,
                    being,
                    ref.name,
                    xtts_py,
                )
                return via_worker

            logger.warning(
                "[TTS] christman_sound XTTS returned no audio for being=%s ref=%s",
                being,
                ref.name,
            )
            return None
        except Exception as exc:
            logger.warning("[TTS] christman_sound failed being=%s: %s", being, exc)
            return None

    def _synthesize_xtts_daemon(self, text: str, ref: "Path") -> bytes | None:
        """POST to warm XTTS server on :8766 (model already in RAM)."""
        import json

        host = os.getenv("CHRISTMAN_XTTS_HOST", "127.0.0.1")
        port = int(os.getenv("CHRISTMAN_XTTS_PORT", "8766"))
        url = f"http://{host}:{port}/synth"
        timeout = float(os.getenv("CHRISTMAN_XTTS_DAEMON_TIMEOUT", "900"))
        try:
            import urllib.request

            payload = json.dumps(
                {"text": text, "ref": str(ref), "language": "en"}
            ).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=payload,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                wav = resp.read()
            if not wav or len(wav) < 100:
                return None
            return self._to_mp3_bytes(wav)
        except Exception as exc:
            logger.info("[TTS] warm daemon unavailable (%s) — try worker", exc)
            return None

    def _synthesize_xtts_inprocess(self, text: str, ref: "Path") -> bytes | None:
        """Try XTTSEngine in this process (backend/venv often lacks torch)."""
        from pathlib import Path
        import tempfile

        try:
            import torch  # noqa: F401
            import TTS  # noqa: F401
            from christman_voice_sdk.engines.xtts_engine import XTTSEngine
            import numpy as np
            from scipy.io.wavfile import write as write_wav

            engine = XTTSEngine()
            engine.load_voice(ref)
            synth_result = engine.synthesize(text, language="en")
            if not synth_result or getattr(synth_result, "audio", None) is None:
                return None
            tmp = Path(tempfile.mktemp(suffix=".wav"))
            sr = getattr(synth_result, "sample_rate", 24000)
            audio_arr = np.asarray(synth_result.audio)
            if audio_arr.dtype != np.int16:
                audio_arr = (audio_arr * 32767).astype(np.int16)
            write_wav(str(tmp), sr, audio_arr)
            audio = self._to_mp3_bytes(tmp.read_bytes())
            tmp.unlink(missing_ok=True)
            return audio
        except Exception as exc:
            logger.debug("[TTS] in-process XTTS unavailable: %s", exc)
            return None

    def _synthesize_xtts_worker(
        self,
        text: str,
        ref: "Path",
        xtts_py: "Path",
        worker: "Path",
    ) -> bytes | None:
        """Spawn Studio christman_sound/.venv worker — full XTTS via voice SDK."""
        import subprocess
        import tempfile
        from pathlib import Path

        out_wav = Path(tempfile.mktemp(suffix=".wav"))
        try:
            env = os.environ.copy()
            env.setdefault("COQUI_TOS_AGREED", "1")
            env.setdefault("NUMBA_CACHE_DIR", "/tmp/christman_numba_cache")
            env.setdefault("XTTS_CHUNK_CHARS", str(XTTS_CHUNK_CHARS))
            # One process: load model once + N sentence packs. RTF can be high on CPU.
            base = int(os.getenv("CHRISTMAN_XTTS_TIMEOUT", "600"))
            timeout_s = max(base, 120 + len(text) * 3)
            timeout_s = min(timeout_s, int(os.getenv("CHRISTMAN_XTTS_TIMEOUT_CAP", "1200")))
            text_file = Path(tempfile.mktemp(suffix=".txt"))
            text_file.write_text(text, encoding="utf-8")
            logger.info(
                "[TTS] xtts_worker start chars=%d timeout=%ds ref=%s",
                len(text),
                timeout_s,
                ref.name,
            )
            try:
                r = subprocess.run(
                    [
                        str(xtts_py),
                        str(worker),
                        "--text-file",
                        str(text_file),
                        "--ref",
                        str(ref),
                        "--out",
                        str(out_wav),
                        "--language",
                        "en",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=timeout_s,
                    env=env,
                )
            finally:
                try:
                    text_file.unlink(missing_ok=True)
                except Exception:
                    pass
            if r.returncode != 0 or not out_wav.is_file():
                err = (r.stderr or r.stdout or "")[-800:]
                logger.warning(
                    "[TTS] xtts_worker failed rc=%s: %s",
                    r.returncode,
                    err,
                )
                return None
            return self._to_mp3_bytes(out_wav.read_bytes())
        except subprocess.TimeoutExpired:
            logger.warning("[TTS] xtts_worker timed out for ref=%s", ref.name)
            return None
        except Exception as exc:
            logger.warning("[TTS] xtts_worker error: %s", exc)
            return None
        finally:
            try:
                out_wav.unlink(missing_ok=True)
            except Exception:
                pass

    def _mock_transcribe(self, audio_data: bytes, filename: str) -> str:
        logger.info(f"MOCK: Received {len(audio_data)} bytes of audio ({filename})")
        return (
            "This is a mock transcription. "
            "Configure SPEECH_SERVICE_API_KEY to use real speech-to-text. "
            f"Audio file size: {len(audio_data)} bytes."
        )

    def _mock_synthesize(self, text: str, voice: str) -> bytes:
        """
        Mock speech synthesis for development/testing.
        Returns a minimal valid MP3 header to avoid errors.
        """
        logger.info(f"MOCK: Would synthesize with voice '{voice}': {text[:100]}...")
        mp3_header = b'\xff\xfb\x90\x00' + b'\x00' * 100
        return mp3_header
