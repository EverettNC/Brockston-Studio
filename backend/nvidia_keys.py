"""
Per-being NVIDIA API keys — Nemo/Nemotron, Mistral, Kimi, Gemma each use their own nvapi key.
Falls back to legacy NVIDIA_API_KEY only when a being-specific key is unset.
"""

from __future__ import annotations

import os


def resolve_nvidia_key(*env_names: str) -> str:
    """Return the first non-empty key from env_names."""
    for name in env_names:
        value = os.getenv(name, "").strip()
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