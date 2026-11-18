"""
Key drop box — the editable place for provider keys in Brockston Studio.

Keys are pasted into the Settings panel, not into a .env file. They live on
this Mac only, outside the repo:

    ~/Library/Application Support/BrockstonStudio/keys.json   (mode 600)

Lookup order for every slot: the box first, then the process environment
(so an existing .env or shell export keeps working as a fallback).

Full key values never leave this module through the API: reads are masked.

To add a provider later, add one entry to PROVIDERS below. Nothing else needs
to change; the Settings panel builds itself from this list.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Dict, List, Optional

# ---------------------------------------------------------------------------
# Provider registry. Each slot is one value in the box.
#   env      the name the code already reads (os.getenv / nvidia_keys)
#   also     extra env names that receive the same value
#   secret   True = masked on read; False = shown plainly (e.g. a host URL)
# ---------------------------------------------------------------------------
PROVIDERS: List[dict] = [
    {
        "id": "nvidia",
        "label": "NVIDIA",
        "slots": [
            {"env": "NVIDIA_API_KEY", "label": "NVIDIA (general, used when a being has no key of its own)", "secret": True},
            {"env": "NVIDIA_NEMO_API_KEY", "label": "Nemo / Nemotron", "secret": True},
            {"env": "NVIDIA_MISTRAL_API_KEY", "label": "Mistral on NVIDIA", "secret": True},
            {"env": "NVIDIA_KIMI_API_KEY", "label": "Kimi (Moonshot) on NVIDIA", "secret": True},
            {"env": "NVIDIA_GEMMA_API_KEY", "label": "Gemma", "secret": True, "also": ["NVIDIA_API_KEY_GEMMA"]},
        ],
    },
    {
        "id": "mistral",
        "label": "Mistral",
        "slots": [
            {"env": "MISTRAL_API_KEY", "label": "Mistral API key (the Mistral button uses this)", "secret": True},
        ],
    },
    {
        "id": "moonshot",
        "label": "Moonshot",
        "slots": [
            {"env": "MOONSHOT_API_KEY", "label": "Moonshot API key", "secret": True},
        ],
    },
    {
        "id": "ollama",
        "label": "Ollama",
        "slots": [
            {
                "env": "OLLAMA_BASE_URL",
                "label": "Ollama host (local by default)",
                "secret": False,
                "also": ["OLLAMA_HOST"],
                "placeholder": "http://127.0.0.1:11434",
                "restart": True,
            },
            {"env": "OLLAMA_API_KEY", "label": "Ollama key (optional)", "secret": True},
        ],
    },
]

_SLOTS: Dict[str, dict] = {s["env"]: s for p in PROVIDERS for s in p["slots"]}
# What the environment held before the box exported anything (the fallback).
_ORIGINAL_ENV: Dict[str, Optional[str]] = {
    env: os.environ.get(env)
    for s in _SLOTS.values()
    for env in [s["env"], *s.get("also", [])]
}
_EXPORTED: Dict[str, str] = {}
_LOCK = threading.Lock()
_CACHE: dict = {"mtime": None, "data": {}}


def box_path() -> Path:
    override = os.getenv("BROCKSTON_KEYBOX_PATH", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / "Library" / "Application Support" / "BrockstonStudio" / "keys.json"


def _read() -> Dict[str, str]:
    path = box_path()
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        _CACHE.update(mtime=None, data={})
        return {}
    if _CACHE["mtime"] == mtime:
        return dict(_CACHE["data"])
    try:
        raw = json.loads(path.read_text(encoding="utf-8") or "{}")
    except (OSError, ValueError):
        raw = {}
    data = {k: str(v) for k, v in raw.items() if k in _SLOTS and isinstance(v, str) and v.strip()}
    _CACHE.update(mtime=mtime, data=data)
    return dict(data)


def _write(data: Dict[str, str]) -> None:
    path = box_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path.parent, 0o700)
    except OSError:
        pass
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".keys-", suffix=".tmp")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    os.chmod(path, 0o600)
    _CACHE["mtime"] = None  # force re-read


def mask(value: str) -> str:
    value = value or ""
    if not value:
        return ""
    tail = value[-4:] if len(value) > 8 else ""
    return "•" * 8 + tail


def get(name: str) -> str:
    """Box first, then environment. Works for any slot env name or alias."""
    data = _read()
    if name in data:
        return data[name].strip()
    for env, slot in _SLOTS.items():
        if name in slot.get("also", []) and env in data:
            return data[env].strip()
    return _env_fallback(name)


def _env_fallback(name: str) -> str:
    """Environment value, ignoring a stale copy this process exported from the box
    (e.g. a key cleared in the Settings panel while another studio process runs)."""
    value = os.getenv(name, "").strip()
    if value and _EXPORTED.get(name) == value:
        return (_ORIGINAL_ENV.get(name) or "").strip()
    return value


def is_slot(name: str) -> bool:
    return name in _SLOTS


def set_value(name: str, value: str) -> None:
    if name not in _SLOTS:
        raise KeyError(name)
    value = (value or "").strip()
    with _LOCK:
        data = _read()
        if value:
            data[name] = value
        else:
            data.pop(name, None)
        _write(data)
    _export(name, value)


def clear(name: str) -> None:
    set_value(name, "")


def _export(name: str, value: str) -> None:
    """Make a box value visible to code that reads os.environ in this process.

    An empty value puts back whatever the environment held before the box
    touched it (a .env or shell value), or removes the variable.
    """
    slot = _SLOTS[name]
    for env in [name, *slot.get("also", [])]:
        if value:
            os.environ[env] = value
            _EXPORTED[env] = value
        else:
            _EXPORTED.pop(env, None)
            original = _ORIGINAL_ENV.get(env)
            if original:
                os.environ[env] = original
            else:
                os.environ.pop(env, None)


def apply_to_environ() -> int:
    """Copy every box value into os.environ (box wins over .env). Returns count."""
    data = _read()
    for name, value in data.items():
        _export(name, value)
    return len(data)


def describe() -> List[dict]:
    """Masked view for the Settings panel. Never contains a full secret."""
    data = _read()
    out = []
    for p in PROVIDERS:
        slots = []
        for s in p["slots"]:
            env = s["env"]
            in_box = env in data
            value = data.get(env) if in_box else _env_fallback(env)
            source = "box" if in_box else ("environment" if value else "unset")
            shown = (mask(value) if s.get("secret", True) else value) if value else ""
            slots.append({
                "env": env,
                "label": s["label"],
                "secret": s.get("secret", True),
                "placeholder": s.get("placeholder", ""),
                "restart": bool(s.get("restart")),
                "set": bool(value),
                "source": source,
                "display": shown,
            })
        out.append({"id": p["id"], "label": p["label"], "slots": slots})
    return out
