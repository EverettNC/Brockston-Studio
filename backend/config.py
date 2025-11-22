"""
BROCKSTON Studio Configuration

Handles environment configuration and secure path resolution.
"""

import os
from pathlib import Path
from typing import Optional


# Server configuration
HOST = os.getenv("BROCKSTON_HOST", "127.0.0.1")
PORT = int(os.getenv("BROCKSTON_PORT", "7777"))

# AI Model endpoints
BROCKSTON_BASE_URL = os.getenv("BROCKSTON_BASE_URL", "http://localhost:6006")
ULTIMATEEV_BASE_URL = os.getenv("ULTIMATEEV_BASE_URL", "http://localhost:6007")

# Default AI model
DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "brockston")

# Workspace root - default to user's home directory
# Can be overridden with BROCKSTON_WORKSPACE environment variable
DEFAULT_WORKSPACE = Path.home() / "Code"
WORKSPACE_ROOT = Path(os.getenv("BROCKSTON_WORKSPACE", str(DEFAULT_WORKSPACE)))

# Ensure workspace exists
WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)

# GitHub configuration
# Personal Access Token for GitHub operations (clone, etc.)
# Should have 'repo' scope for private repos
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")


def resolve_path(relative_or_abs: str) -> Path:
    """
    Resolve a file path safely within the workspace.

    Args:
        relative_or_abs: Path string (relative or absolute)

    Returns:
        Resolved absolute Path object

    Raises:
        ValueError: If resolved path is outside workspace
    """
    p = Path(relative_or_abs)

    # If not absolute, make it relative to workspace
    if not p.is_absolute():
        p = WORKSPACE_ROOT / p

    # Resolve to absolute path (handles .. and symlinks)
    p = p.resolve()

    # Security check: ensure path is within workspace
    try:
        p.relative_to(WORKSPACE_ROOT)
    except ValueError:
        raise ValueError(
            f"Path '{p}' is outside workspace root '{WORKSPACE_ROOT}'. "
            "Access denied for security."
        )

    return p


def get_workspace_root() -> Path:
    """Get the configured workspace root directory."""
    return WORKSPACE_ROOT
