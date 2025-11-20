"""
Git Service Module for BROCKSTON Studio

Handles Git operations like cloning repositories.
"""

import logging
import subprocess
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .config import WORKSPACE_ROOT, GITHUB_TOKEN

logger = logging.getLogger(__name__)


def clone_repo(git_url: str, folder_name: Optional[str] = None) -> Path:
    """
    Clone a GitHub repository into WORKSPACE_ROOT.

    Args:
        git_url: The Git repository URL (HTTPS format)
        folder_name: Optional custom folder name. If None, derives from repo name.

    Returns:
        Path object pointing to the cloned repository

    Raises:
        ValueError: If URL is invalid or target is outside workspace
        RuntimeError: If git clone command fails
    """
    # Validate URL is HTTPS and points to GitHub
    try:
        parsed = urlparse(git_url)
        if parsed.scheme not in ("https", "http"):
            raise ValueError("Only HTTPS/HTTP URLs are supported")
        if "github.com" not in parsed.netloc.lower():
            raise ValueError("Only GitHub URLs are supported in v1")
    except Exception as e:
        raise ValueError(f"Invalid Git URL: {e}")

    # Derive folder name from URL if not provided
    if folder_name is None:
        # Extract repo name from URL
        # Example: https://github.com/EverettNC/BROCKSTON.git -> BROCKSTON
        path_parts = git_url.rstrip("/").split("/")
        folder_name = path_parts[-1]
        if folder_name.endswith(".git"):
            folder_name = folder_name[:-4]

    # Validate folder name is safe
    if not folder_name or "/" in folder_name or "\\" in folder_name:
        raise ValueError(f"Invalid folder name: {folder_name}")

    # Build target directory path
    target_dir = (WORKSPACE_ROOT / folder_name).resolve()

    # Security check: ensure target is within workspace
    try:
        target_dir.relative_to(WORKSPACE_ROOT)
    except ValueError:
        raise ValueError(
            f"Target directory '{target_dir}' is outside workspace root '{WORKSPACE_ROOT}'. "
            "Access denied for security."
        )

    # Check if directory already exists
    if target_dir.exists():
        raise ValueError(
            f"Directory '{folder_name}' already exists in workspace. "
            "Please choose a different name or remove the existing directory."
        )

    # Ensure parent directory exists
    target_dir.parent.mkdir(parents=True, exist_ok=True)

    # Build authenticated URL if we have a GitHub token
    auth_url = git_url
    if GITHUB_TOKEN and git_url.startswith("https://github.com/"):
        # Insert token into URL for authentication
        # https://github.com/owner/repo.git -> https://TOKEN@github.com/owner/repo.git
        auth_url = git_url.replace(
            "https://github.com/",
            f"https://{GITHUB_TOKEN}@github.com/",
            1,
        )
        logger.info(f"Cloning repository with authentication: {git_url}")
    else:
        logger.info(f"Cloning repository without authentication: {git_url}")

    # Execute git clone
    try:
        result = subprocess.run(
            ["git", "clone", auth_url, str(target_dir)],
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout for clone
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip() if result.stderr else "Unknown error"
            # Don't leak token in error messages
            error_msg = error_msg.replace(GITHUB_TOKEN, "***") if GITHUB_TOKEN else error_msg
            raise RuntimeError(f"git clone failed: {error_msg}")

        logger.info(f"Successfully cloned repository to: {target_dir}")
        return target_dir

    except subprocess.TimeoutExpired:
        raise RuntimeError("Git clone timed out after 5 minutes")
    except FileNotFoundError:
        raise RuntimeError(
            "Git command not found. Please ensure Git is installed and available in PATH."
        )
    except Exception as e:
        # Clean up partial clone if it exists
        if target_dir.exists():
            import shutil
            shutil.rmtree(target_dir, ignore_errors=True)
        raise RuntimeError(f"Git clone failed: {e}")


def get_repo_status(repo_path: Path) -> dict:
    """
    Get the status of a Git repository.

    Args:
        repo_path: Path to the repository

    Returns:
        Dictionary with status information

    Raises:
        ValueError: If path is not a Git repository
        RuntimeError: If git command fails
    """
    # Validate path is within workspace
    try:
        repo_path = repo_path.resolve()
        repo_path.relative_to(WORKSPACE_ROOT)
    except ValueError:
        raise ValueError(f"Path '{repo_path}' is outside workspace root")

    # Check if it's a Git repository
    if not (repo_path / ".git").exists():
        raise ValueError(f"Path '{repo_path}' is not a Git repository")

    try:
        # Get current branch
        branch_result = subprocess.run(
            ["git", "-C", str(repo_path), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        current_branch = branch_result.stdout.strip() if branch_result.returncode == 0 else "unknown"

        # Get status
        status_result = subprocess.run(
            ["git", "-C", str(repo_path), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        has_changes = bool(status_result.stdout.strip()) if status_result.returncode == 0 else False

        return {
            "branch": current_branch,
            "has_changes": has_changes,
            "is_repo": True,
        }

    except subprocess.TimeoutExpired:
        raise RuntimeError("Git status command timed out")
    except FileNotFoundError:
        raise RuntimeError("Git command not found")
    except Exception as e:
        raise RuntimeError(f"Failed to get repository status: {e}")
