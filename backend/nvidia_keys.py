"""
Per-being NVIDIA API keys — Nemo/Nemotron, Mistral, Kimi, Gemma each use their own nvapi key.
Falls back to legacy NVIDIA_API_KEY only when a being-specific key is unset.

Each name is looked up in the Studio key drop box first (Settings panel),
then in the environment.
"""

from __future__ import annotations

try:
    from .key_box import get as _box_get
except ImportError:  # backend/ on sys.path (launcher)
    from key_box import get as _box_get


def resolve_nvidia_key(*env_names: str) -> str:
    """Return the first non-empty key from env_names (box first, then environment)."""
    for name in env_names:
        value = _box_get(name)
        if value:
            return value
    return ""


def nemo_nvidia_key() -> str:
    return resolve_nvidia_key("NVIDIA_NEMO_API_KEY", "NVIDIA_API_KEY")


def mistral_nvidia_key() -> str:
    return resolve_nvidia_key("NVIDIA_MISTRAL_API_KEY", "NVIDIA_NEMO_API_KEY", "NVIDIA_API_KEY")


def kimi_nvidia_key() -> str:
    return resolve_nvidia_key("NVIDIA_KIMI_API_KEY", "NVIDIA_API_KEY")


def gemma_nvidia_key() -> str:
    return resolve_nvidia_key("NVIDIA_GEMMA_API_KEY", "NVIDIA_API_KEY_GEMMA", "NVIDIA_API_KEY")