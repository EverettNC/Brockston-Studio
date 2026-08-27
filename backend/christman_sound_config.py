"""
christman_sound paths for Brockston Studio.

This repo only: ./christman_sound and ./Voice_Creation_Center.
Override with CHRISTMAN_SOUND_ROOT in .env if you must — no other default.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
LOCAL_CHRISTMAN_SOUND = BASE_DIR / "christman_sound"

CHRISTMAN_SOUND_ROOT = Path(
    os.getenv("CHRISTMAN_SOUND_ROOT", str(LOCAL_CHRISTMAN_SOUND))
).expanduser()

_media_installer_env = os.getenv("CHRISTMAN_MEDIA_INSTALLER_ROOT", "").strip()
CHRISTMAN_MEDIA_INSTALLER_ROOT: Optional[Path] = (
    Path(_media_installer_env).expanduser() if _media_installer_env else None
)

VOICE_CENTER = Path(
    os.getenv("CHRISTMAN_VOICE_CENTER", str(BASE_DIR / "Voice_Creation_Center"))
).expanduser()

VOICEPACK_DIR = Path(
    os.getenv("CHRISTMAN_VOICEPACK_DIR", str(BASE_DIR / "data" / "voicepacks"))
).expanduser()

_SDK_FOLDER_NAMES = ("christman_voice_sdk", "christman_voice_sdk ")


def sdk_root() -> Path:
    for name in _SDK_FOLDER_NAMES:
        candidate = CHRISTMAN_SOUND_ROOT / name
        if candidate.is_dir():
            return candidate
    return CHRISTMAN_SOUND_ROOT / "christman_voice_sdk"


# Read-aloud: map chat instructors → Christman being reference WAVs
TTS_BEING_ALIASES: dict[str, str] = {
    "family": "brockston",
    "claude": "brockston",
    "fable5": "brockston",
    "fable-5": "brockston",
    "auto": "brockston",
    "default": "brockston",
    # NVIDIA swarm → Nemo pack when present, else brockston ref in find_reference_wav
    "nemoclaw": "nemo",
    "nemotron": "nemo",
    "nemo-tron": "nemo",
    "nemo_tron": "nemo",
    "nvidia-nemotron": "nemo",
    "nvidia_nemotron": "nemo",
    "mistral": "nemo",  # Mistral-Nemotron → Nemo voice pack
    "mistral-nemotron": "nemo",
    "mistral_nemotron": "nemo",
    "kimi": "kimi",
    "kimi26": "kimi",
    "kimi27": "kimi",
    "k2.6": "kimi",
    "k2.7": "kimi",
    "grok": "ultimateev",
    "superheavy": "ultimateev",
    "super_heavy_grok": "ultimateev",
}

# macOS `say` male fallbacks when XTTS is unavailable (all English male voices on this Mac)
MACOS_MALE_VOICES: dict[str, str] = {
    "brockston": "Daniel",
    "derek": "Daniel",
    "ultimateev": "Alex",
    "nemo": "Fred",
    "kimi": "Alex",
    "inferno": "Daniel",
    "aegis": "Daniel",
    "alphawolf": "Daniel",
    "giuseppe": "Daniel",
    "default": "Daniel",
}

BEINGS: dict[str, dict] = {
    "brockston": {"label": "Brockston", "tier": "ultra", "emotions": ["warm", "direct", "grounded"]},
    "kimi": {"label": "Kimi", "tier": "ultra", "emotions": ["warm", "patient", "clear"]},
    "nemo": {"label": "Nemo", "tier": "ultra", "emotions": ["warm", "direct", "protective"]},
    "alphavox": {"label": "AlphaVox", "tier": "ultra", "emotions": ["gentle", "patient", "clear"]},
    "alphawolf": {"label": "AlphaWolf", "tier": "ultra", "emotions": ["calm", "steady", "reassuring"]},
    "inferno": {"label": "Inferno", "tier": "ultra", "emotions": ["grounded", "fierce", "tender"]},
    "aegis": {"label": "Aegis", "tier": "ultra", "emotions": ["protective", "calm", "clear"]},
    "derek": {"label": "Derek", "tier": "ultra", "emotions": ["direct", "confident", "calm"]},
    "giuseppe": {"label": "Giuseppe", "tier": "ultra", "emotions": ["expressive", "warm", "passionate"]},
    "siera": {"label": "Siera", "tier": "ultra", "emotions": ["safe", "calm", "steady"]},
    "ultimateev": {"label": "UltimateEV", "tier": "ultra", "emotions": ["precise", "direct", "surgical"]},
}


def resolve_tts_being(being: str) -> str:
    """Which being's reference WAV to use for read-aloud (male Brockston by default)."""
    key = (being or "default").lower().strip()
    override = os.getenv("TTS_READ_BEING", "").strip().lower()
    if override:
        return override
    return TTS_BEING_ALIASES.get(key, key if key in BEINGS else "brockston")


def macos_voice_for_being(being: str) -> str:
    """Male macOS voice when christman_sound XTTS is unavailable."""
    key = resolve_tts_being(being)
    return MACOS_MALE_VOICES.get(key, MACOS_MALE_VOICES["default"])


def incoming_dir(being: str) -> Path:
    return VOICE_CENTER / "incoming" / being.lower()


def packs_dir(being: str) -> Path:
    return VOICE_CENTER / "packs" / being.lower()


def ensure_voice_folders() -> list[Path]:
    """Create incoming + pack folders for every registered being."""
    created: list[Path] = []
    for being in BEINGS:
        for folder in (incoming_dir(being), packs_dir(being)):
            if not folder.exists():
                folder.mkdir(parents=True, exist_ok=True)
                created.append(folder)
    (VOICEPACK_DIR).mkdir(parents=True, exist_ok=True)
    return created


def ensure_sound_paths() -> list[str]:
    """Add christman_sound + SDK to sys.path. Returns paths added."""
    if not CHRISTMAN_SOUND_ROOT.is_dir():
        logger.error(
            "[christman_sound] Missing at %s — expected Brockston-Studio/christman_sound",
            CHRISTMAN_SOUND_ROOT,
        )
    added: list[str] = []
    for path in (CHRISTMAN_SOUND_ROOT, sdk_root(), VOICE_CENTER):
        s = str(path)
        if path.exists() and s not in sys.path:
            sys.path.insert(0, s)
            added.append(s)

    # Explicitly add the voice_sdk subdir for the import in SPEAK
    voice_sdk = CHRISTMAN_SOUND_ROOT / "christman_voice_sdk"
    if voice_sdk.exists():
        s = str(voice_sdk)
        if s not in sys.path:
            sys.path.insert(0, s)
            added.append(s)

    ear_paths = CHRISTMAN_SOUND_ROOT / "CHRISTMAN_EAR_CANAL"
    if ear_paths.is_dir():
        parent = str(CHRISTMAN_SOUND_ROOT)
        if parent not in sys.path:
            sys.path.insert(0, parent)
            added.append(parent)
    return added


def _ensure_voice_center_engines() -> None:
    engines = VOICE_CENTER / "engines"
    if engines.is_dir():
        s = str(engines)
        if s not in sys.path:
            sys.path.insert(0, s)


def load_being_manifest(being: str) -> Optional[dict]:
    """Load pack manifest via Voice_Creation_Center voice_loader."""
    _ensure_voice_center_engines()
    try:
        from voice_loader import load_pack

        return load_pack(being.lower().strip())
    except Exception:
        return None


def find_reference_wav(being: str) -> Optional[Path]:
    """Resolve reference WAV through Voice_Creation_Center manifest, then incoming/.
    If the specific being has none, fall back to a default (brockston or first available)
    so every being gets christman_sound XTTS instead of raw macOS say.
    """
    key = being.lower().strip()
    if not key or key in ("default", "daniel"):
        key = "brockston"

    manifest = load_being_manifest(key)
    if manifest:
        for ref in manifest.get("reference_wavs") or []:
            path = Path(ref)
            if path.exists():
                return path

    # Being-specific only first (do not steal generic simple_phrases for named beings)
    search_dirs: list[Path] = [
        incoming_dir(key),
        packs_dir(key),
    ]
    for directory in search_dirs:
        if not directory.is_dir():
            continue
        audio_files = sorted(
            list(directory.glob("*.wav"))
            + list(directory.glob("*.mp3"))
            + list(directory.glob("*.m4a")),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if audio_files:
            return audio_files[0]

    # Until Nemo (etc.) has his own pack — use best available family ref
    if key != "brockston":
        default = find_reference_wav("brockston")
        if default:
            logger.info(
                "[TTS] No pack/ref for %s — using available brockston reference for XTTS",
                being,
            )
            return default

    # Last resort: simple phrases or any brockston incoming
    for directory in [incoming_dir("brockston"), VOICE_CENTER / "incoming" / "simple_phrases"]:
        if directory.is_dir():
            wavs = sorted(directory.glob("*.wav"), key=lambda p: p.stat().st_mtime, reverse=True)
            if wavs:
                return wavs[0]
    return None


_XTTS_PYTHON_CACHE: Optional[Path] = None
_XTTS_PYTHON_CHECKED: bool = False


def resolve_xtts_python() -> Optional[Path]:
    """
    Python that can import torch + Coqui TTS for christman_sound XTTS.

    Studio-local only (Brockston-Studio). Cached after first success.
    Order:
      1. CHRISTMAN_XTTS_PYTHON env
      2. christman_sound/.venv_py311  (Coqui TTS needs Python < 3.12)
      3. christman_sound/.venv
      4. backend/venv (only if torch+TTS installed there)
    """
    global _XTTS_PYTHON_CACHE, _XTTS_PYTHON_CHECKED
    if _XTTS_PYTHON_CHECKED:
        return _XTTS_PYTHON_CACHE

    candidates: list[Path] = []
    env_py = os.getenv("CHRISTMAN_XTTS_PYTHON", "").strip()
    if env_py:
        candidates.append(Path(env_py).expanduser())
    candidates.extend(
        [
            CHRISTMAN_SOUND_ROOT / ".venv_py311" / "bin" / "python",
            BASE_DIR / "christman_sound" / ".venv_py311" / "bin" / "python",
            CHRISTMAN_SOUND_ROOT / ".venv" / "bin" / "python",
            BASE_DIR / "christman_sound" / ".venv" / "bin" / "python",
            BASE_DIR / "backend" / "venv" / "bin" / "python",
            Path(sys.executable),
        ]
    )
    seen: set[str] = set()
    found: Optional[Path] = None
    for py in candidates:
        key = str(py)
        if key in seen:
            continue
        seen.add(key)
        if not py.is_file() and not py.is_symlink():
            continue
        if not os.access(py, os.X_OK):
            continue
        if _python_has_xtts_stack(py):
            found = py
            break
    _XTTS_PYTHON_CACHE = found
    _XTTS_PYTHON_CHECKED = True
    return found


def _python_has_xtts_stack(python: Path) -> bool:
    """True if this interpreter can import torch and TTS."""
    import subprocess

    try:
        r = subprocess.run(
            [
                str(python),
                "-c",
                "import torch; import TTS; print('ok')",
            ],
            capture_output=True,
            text=True,
            timeout=45,
            env={**os.environ, "COQUI_TOS_AGREED": "1"},
        )
        return r.returncode == 0 and "ok" in (r.stdout or "")
    except Exception:
        return False


def xtts_worker_script() -> Path:
    return BASE_DIR / "backend" / "xtts_worker.py"


def try_express_audio(text: str, being: str) -> Optional[bytes]:
    """Serve pre-rendered phrase from Voice_Creation_Center express lane."""
    key = being.lower().strip()
    profile = BEINGS.get(key, {})
    being_label = profile.get("label", being.title())
    vcc = str(VOICE_CENTER)
    if vcc not in sys.path:
        sys.path.insert(0, vcc)
    try:
        from voice_express import VoiceExpress

        express = VoiceExpress()
        express.load()
        result = express.serve(text[:3500], being_label)
        if result.success and result.audio_data:
            return result.audio_data
    except Exception:
        pass
    return None


def sound_stack_status() -> dict:
    """Truth report for wiring — Rule 13."""
    sdk = sdk_root()
    ear_paths = CHRISTMAN_SOUND_ROOT / "CHRISTMAN_EAR_CANAL" / "_paths.py"
    installer_cli = (
        CHRISTMAN_MEDIA_INSTALLER_ROOT / "christman_media_installer" / "cli.py"
        if CHRISTMAN_MEDIA_INSTALLER_ROOT
        else None
    )
    beings_ready = {}
    for name in BEINGS:
        inc = incoming_dir(name)
        wavs = list(inc.glob("*.wav")) if inc.is_dir() else []
        pack_manifest = packs_dir(name) / "manifest.json"
        beings_ready[name] = {
            "incoming_wavs": len(wavs),
            "pack_registered": pack_manifest.exists(),
            "incoming_path": str(inc),
        }
    xtts_py = resolve_xtts_python()
    return {
        "christman_sound_root": str(CHRISTMAN_SOUND_ROOT),
        "sound_root_exists": CHRISTMAN_SOUND_ROOT.is_dir(),
        "sdk_root": str(sdk),
        "sdk_exists": sdk.is_dir(),
        "ear_canal_paths_shim": ear_paths.exists(),
        "media_installer": str(CHRISTMAN_MEDIA_INSTALLER_ROOT or ""),
        "media_installer_exists": bool(installer_cli and installer_cli.exists()),
        "voice_center": str(VOICE_CENTER),
        "voice_creation_center_active": True,
        "registered_packs": _inventory_pack_ids(),
        "beings": beings_ready,
        "xtts_python": str(xtts_py) if xtts_py else None,
        "xtts_ready": bool(xtts_py),
        "xtts_worker": str(xtts_worker_script()),
        "xtts_worker_exists": xtts_worker_script().is_file(),
        "stack_note": (
            "Brockston-Studio christman_sound + christman_voice_sdk only "
            "(not BROCKSTON project)"
        ),
    }


def _inventory_pack_ids() -> list[str]:
    index = VOICE_CENTER / "inventory" / "index.json"
    if not index.exists():
        return []
    try:
        import json

        data = json.loads(index.read_text(encoding="utf-8"))
        return [p.get("pack_id", "") for p in data.get("packs", []) if p.get("pack_id")]
    except Exception:
        return []