"""
backend/being_eyes.py — Brockston Studio
Being Eyes: gives every AI family member the ability to SEE the screen
and FIX things — read files, write files, run commands, take screenshots.

This is the sight and hands of every being in the Christman AI family
when they're operating inside Brockston Studio.

Endpoints (all prefixed /api/eyes):
    GET  /api/eyes/screenshot      → base64 PNG of the whole screen
    GET  /api/eyes/read            → read a file, return its content
    POST /api/eyes/write           → write content to a file
    POST /api/eyes/patch           → find-and-replace inside a file
    GET  /api/eyes/ls              → list directory contents
    POST /api/eyes/run             → run a shell command, return stdout + stderr
    GET  /api/eyes/state           → full IDE state snapshot (files, tabs, cwd)

Rule 1:  Every endpoint returns real data or an explicit error — never silently fails.
Rule 6:  Errors are loud — status code + reason in the response body.
Rule 13: No fake successes. If the file didn't write, say so. If the command failed, say so.

Author: Everett Christman / The Christman AI Project
Cardinal Rules: All 15 apply.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger("being_eyes")

router = APIRouter(prefix="/api/eyes", tags=["being_eyes"])

# ── Workspace root — same as Studio's WORKSPACE_ROOT (backend/config.py) ─────
try:
    from backend.config import STUDIO_WORKSPACE as _CFG_WORKSPACE
except ImportError:
    from config import STUDIO_WORKSPACE as _CFG_WORKSPACE

WORKSPACE_ROOT = Path(_CFG_WORKSPACE).resolve()
USER_HOME = Path(os.path.expanduser("~")).resolve()


def _safe_path(raw: str) -> Path:
    """
    Resolve a path safely. Absolute paths are used as-is.
    Relative paths are resolved against WORKSPACE_ROOT.
    Rule 13: Never silently redirects — if path is bad, raise immediately.
    """
    expanded = os.path.expanduser(raw.strip())
    if ".." in expanded.replace("\\", "/").split("/"):
        raise HTTPException(status_code=400, detail="Path contains '..'")
    p = Path(expanded)
    if not p.is_absolute():
        p = WORKSPACE_ROOT / p
    resolved = p.resolve()
    try:
        resolved.relative_to(USER_HOME)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Path outside user home ({USER_HOME})",
        )
    return resolved


# ── Screenshot ─────────────────────────────────────────────────────────────────

def _capture_screen_png(tmp_path: str, display: int | None = None) -> tuple[int, str]:
    """
    Run macOS screencapture into tmp_path.

    -D display numbers are 1-based on macOS (main = 1). 0 / negative = auto main.
    Tries requested display, then 1→3, then bare screencapture (main).
    Returns (display_used_or_0_for_main, empty_err). Raises RuntimeError on total fail.
    """
    # Build attempt list: preferred first, then fallbacks (unique, valid)
    attempts: list[list[str]] = []
    preferred = display if display is not None else 1
    if preferred and preferred > 0:
        attempts.append(["screencapture", "-x", "-D", str(preferred), tmp_path])
    # Fallbacks: main displays 1-3, then no -D (main screen)
    for d in (1, 2, 3):
        if d == preferred:
            continue
        attempts.append(["screencapture", "-x", "-D", str(d), tmp_path])
    attempts.append(["screencapture", "-x", tmp_path])

    errors: list[str] = []
    for cmd in attempts:
        try:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        except Exception:
            pass
        result = subprocess.run(cmd, capture_output=True, timeout=15)
        err = (result.stderr or b"").decode("utf-8", errors="replace")[:300]
        if result.returncode == 0 and Path(tmp_path).is_file() and Path(tmp_path).stat().st_size > 0:
            used = 0
            if "-D" in cmd:
                used = int(cmd[cmd.index("-D") + 1])
            return used, ""
        errors.append(f"{' '.join(cmd[:-1])} → rc={result.returncode} {err}".strip())

    raise RuntimeError("; ".join(errors)[:800])


@router.get("/screenshot")
async def get_screenshot(
    display: int = Query(
        default=1,
        description="macOS display for screencapture -D (1=main). Use 0 for auto.",
    )
):
    """
    Capture the screen as base64 PNG so beings can SEE (vision).
    Uses macOS screencapture — zero cloud, zero cost.

    display: 1–3 = specific screen; 0 = auto (try main, then others).
    """
    if os.uname().sysname != "Darwin":
        raise HTTPException(status_code=501, detail="Screenshot only supported on macOS (screencapture).")

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        try:
            preferred = None if display <= 0 else display
            used_display, _ = _capture_screen_png(tmp_path, preferred)
        except RuntimeError as exc:
            raise HTTPException(
                status_code=500,
                detail=(
                    f"screencapture failed: {exc}. "
                    "Grant Screen Recording to Terminal/Python/Studio in "
                    "System Settings → Privacy & Security → Screen Recording."
                ),
            ) from exc

        shot_path = Path(tmp_path)
        raw_bytes = shot_path.read_bytes()
        encoded = base64.b64encode(raw_bytes).decode("ascii")

        width, height = None, None
        try:
            sips = subprocess.run(
                ["sips", "-g", "pixelWidth", "-g", "pixelHeight", tmp_path],
                capture_output=True, text=True, timeout=5,
            )
            for line in sips.stdout.splitlines():
                if "pixelWidth" in line:
                    width = int(line.split(":")[1].strip())
                elif "pixelHeight" in line:
                    height = int(line.split(":")[1].strip())
        except Exception:
            pass

        logger.info(
            "[BeingEyes] Screenshot captured: %dKB %sx%s display=%s",
            len(raw_bytes) // 1024,
            width,
            height,
            used_display or "main",
        )
        return {
            "status": "ok",
            "format": "png",
            "encoding": "base64",
            "size_kb": round(len(raw_bytes) / 1024, 1),
            "width": width,
            "height": height,
            "display": used_display or 1,
            "data": encoded,
        }
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


# ── File read ──────────────────────────────────────────────────────────────────

DEFAULT_READ_LIMIT_LINES = 500


def _read_file_paginated(
    p: Path,
    *,
    encoding: str = "utf-8",
    max_kb: int = 500,
    offset_lines: int = 1,
    limit_lines: int = 0,
) -> dict:
    """Read a slice of a text file by line range. Large files are scrolled, not dropped."""
    offset_lines = max(1, int(offset_lines))
    chunk_lines = int(limit_lines) if limit_lines and int(limit_lines) > 0 else DEFAULT_READ_LIMIT_LINES
    byte_cap = max_kb * 1024 if max_kb > 0 else None

    selected: list[str] = []
    line_end = offset_lines - 1
    byte_count = 0
    has_more = False

    with p.open("r", encoding=encoding, errors="replace") as handle:
        for line_no, line in enumerate(handle, start=1):
            if line_no < offset_lines:
                continue
            if len(selected) >= chunk_lines:
                has_more = True
                break
            line_bytes = len(line.encode(encoding, errors="replace"))
            if byte_cap is not None and byte_count + line_bytes > byte_cap:
                has_more = True
                break
            selected.append(line)
            line_end = line_no
            byte_count += line_bytes

    content = "".join(selected)
    size_bytes = p.stat().st_size
    total_lines: Optional[int] = None
    if size_bytes < 2 * 1024 * 1024:
        try:
            with p.open("r", encoding=encoding, errors="replace") as handle:
                total_lines = sum(1 for _ in handle)
            if total_lines is not None and line_end >= total_lines:
                has_more = False
        except Exception:
            total_lines = None

    next_offset = line_end + 1 if has_more else None
    path_str = str(p)
    hint = None
    if has_more and next_offset is not None:
        hint = (
            f'More content available. Read next chunk with '
            f'{{"tool":"read","path":"{path_str}","offset_lines":{next_offset},'
            f'"limit_lines":{chunk_lines}}}'
        )

    return {
        "status": "ok",
        "path": path_str,
        "content": content,
        "lines": len(selected),
        "line_start": offset_lines if selected else None,
        "line_end": line_end if selected else None,
        "total_lines": total_lines,
        "size_bytes": size_bytes,
        "truncated": has_more,
        "has_more": has_more,
        "next_offset_lines": next_offset,
        "hint": hint,
    }


@router.get("/read")
async def read_file(
    path: str = Query(..., description="Absolute or workspace-relative file path"),
    encoding: str = Query(default="utf-8", description="Text encoding"),
    max_kb: int = Query(default=500, description="Max kilobytes per chunk (0 = no byte cap)"),
    offset_lines: int = Query(default=1, description="1-based line to start reading from"),
    limit_lines: int = Query(default=0, description="Max lines per chunk (0 = 500)"),
):
    """
    Read a file from disk and return its content as text.
    Use offset_lines + limit_lines to scroll through large files in chunks.

    Returns:
        {"status": "ok", "path": str, "content": str, "lines": int,
         "line_start": int, "line_end": int, "total_lines": int|None,
         "truncated": bool, "has_more": bool, "next_offset_lines": int|None, "hint": str|None}
    """
    try:
        p = _safe_path(path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Bad path: {e}")

    if not p.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {p}")
    if not p.is_file():
        raise HTTPException(status_code=400, detail=f"Not a file: {p}")

    try:
        result = _read_file_paginated(
            p,
            encoding=encoding,
            max_kb=max_kb,
            offset_lines=offset_lines,
            limit_lines=limit_lines,
        )
        logger.info(
            "[BeingEyes] Read %s lines %s-%s (truncated=%s, has_more=%s)",
            p,
            result.get("line_start"),
            result.get("line_end"),
            result.get("truncated"),
            result.get("has_more"),
        )
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Read error: {e}")


# ── File write ─────────────────────────────────────────────────────────────────

class WriteRequest(BaseModel):
    path: str
    content: str
    encoding: str = "utf-8"
    create_dirs: bool = True


@router.post("/write")
async def write_file(req: WriteRequest):
    """
    Write content to a file. Creates parent directories if create_dirs=True.
    Rule 13: Returns actual outcome — written bytes or explicit error.

    Returns:
        {"status": "ok", "path": str, "bytes_written": int}
    """
    try:
        p = _safe_path(req.path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Bad path: {e}")

    if req.create_dirs:
        p.parent.mkdir(parents=True, exist_ok=True)
    elif not p.parent.exists():
        raise HTTPException(status_code=400, detail=f"Parent directory does not exist: {p.parent}")

    try:
        encoded = req.content.encode(req.encoding)
        p.write_bytes(encoded)
        # Nudge parent so macOS Finder sees the change without refresh
        try:
            os.utime(p.parent, None)
        except Exception:
            pass
        logger.info(f"[BeingEyes] Wrote {p} ({len(encoded)} bytes)")
        return {
            "status": "ok",
            "path": str(p),
            "bytes_written": len(encoded),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Write error: {e}")


# ── Move / rename ─────────────────────────────────────────────────────────────

class MoveRequest(BaseModel):
    src: str
    dst: str
    create_dirs: bool = True
    overwrite: bool = False


@router.post("/move")
async def move_file(req: MoveRequest):
    """
    Move or rename a file or directory.
    Works for single files and entire folders.
    Rule 13: Fails loud if src doesn't exist or dst already exists (unless overwrite=True).

    Returns:
        {"status": "ok", "src": str, "dst": str, "type": "file"|"dir"}
    """
    import shutil

    try:
        src = _safe_path(req.src)
        dst = _safe_path(req.dst)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Bad path: {e}")

    if not src.exists():
        raise HTTPException(status_code=404, detail=f"Source not found: {src}")

    if dst.exists() and not req.overwrite:
        raise HTTPException(
            status_code=409,
            detail=f"Destination already exists: {dst} — set overwrite=true to replace it."
        )

    if req.create_dirs:
        dst.parent.mkdir(parents=True, exist_ok=True)

    try:
        kind = "dir" if src.is_dir() else "file"
        shutil.move(str(src), str(dst))
        logger.info(f"[BeingEyes] Moved {src} → {dst}")
        return {
            "status": "ok",
            "src": str(src),
            "dst": str(dst),
            "type": kind,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Move error: {e}")


# ── Delete ─────────────────────────────────────────────────────────────────────

class DeleteRequest(BaseModel):
    path: str
    recursive: bool = False


@router.post("/delete")
async def delete_path(req: DeleteRequest):
    """
    Delete a file or directory.
    Directories require recursive=True as a safety gate.
    Rule 13: Fails loud if path doesn't exist.

    Returns:
        {"status": "ok", "path": str, "type": "file"|"dir"}
    """
    import shutil

    try:
        p = _safe_path(req.path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Bad path: {e}")

    if not p.exists():
        raise HTTPException(status_code=404, detail=f"Path not found: {p}")

    try:
        if p.is_dir():
            if not req.recursive:
                raise HTTPException(
                    status_code=400,
                    detail=f"{p} is a directory — set recursive=true to delete it."
                )
            shutil.rmtree(str(p))
            kind = "dir"
        else:
            p.unlink()
            kind = "file"

        logger.info(f"[BeingEyes] Deleted {p} ({kind})")
        return {"status": "ok", "path": str(p), "type": kind}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delete error: {e}")


# ── Create directory ───────────────────────────────────────────────────────────

@router.post("/mkdir")
async def make_directory(
    path: str = Query(..., description="Directory path to create"),
):
    """
    Create a directory (and any missing parents).

    Returns:
        {"status": "ok", "path": str}
    """
    try:
        p = _safe_path(path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Bad path: {e}")

    try:
        p.mkdir(parents=True, exist_ok=True)
        logger.info(f"[BeingEyes] Created dir {p}")
        return {"status": "ok", "path": str(p)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"mkdir error: {e}")


# ── File patch (find-and-replace) ──────────────────────────────────────────────

class PatchRequest(BaseModel):
    path: str
    old_string: str
    new_string: str
    encoding: str = "utf-8"
    replace_all: bool = False


@router.post("/patch")
async def patch_file(req: PatchRequest):
    """
    Find-and-replace inside a file. Safer than rewriting the whole thing.
    Fails loud if old_string isn't found — never silently no-ops.
    Rule 13: Reports actual replacement count.

    Returns:
        {"status": "ok", "path": str, "replacements": int, "bytes_written": int}
    """
    try:
        p = _safe_path(req.path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Bad path: {e}")

    if not p.exists() or not p.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {p}")

    try:
        content = p.read_text(encoding=req.encoding)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Read error: {e}")

    if req.old_string not in content:
        raise HTTPException(
            status_code=422,
            detail=f"old_string not found in {p.name} — nothing patched. (Rule 13: no silent no-ops)"
        )

    count = content.count(req.old_string)
    if req.replace_all:
        new_content = content.replace(req.old_string, req.new_string)
    else:
        new_content = content.replace(req.old_string, req.new_string, 1)
        count = 1

    try:
        encoded = new_content.encode(req.encoding)
        p.write_bytes(encoded)
        logger.info(f"[BeingEyes] Patched {p} — {count} replacement(s)")
        return {
            "status": "ok",
            "path": str(p),
            "replacements": count,
            "bytes_written": len(encoded),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Write error after patch: {e}")


# ── Directory listing ──────────────────────────────────────────────────────────

@router.get("/ls")
async def list_directory(
    path: str = Query(default=".", description="Directory to list"),
    depth: int = Query(default=1, description="How many levels deep (1=flat, 2=one level of subdirs)"),
):
    """
    List the contents of a directory.

    Returns:
        {"status": "ok", "path": str, "entries": [...]}
    """
    try:
        p = _safe_path(path)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Bad path: {e}")

    if not p.exists():
        raise HTTPException(status_code=404, detail=f"Directory not found: {p}")
    if not p.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {p}")

    def _list(dir_path: Path, current_depth: int) -> list[dict]:
        entries = []
        try:
            items = sorted(dir_path.iterdir(), key=lambda x: (x.is_file(), x.name))
        except PermissionError:
            return [{"name": "<permission denied>", "type": "error"}]

        for item in items:
            if item.name.startswith("."):
                continue  # skip hidden files in listings
            entry = {
                "name": item.name,
                "path": str(item),
                "type": "dir" if item.is_dir() else "file",
            }
            if item.is_file():
                entry["size_bytes"] = item.stat().st_size
            if item.is_dir() and current_depth < depth:
                entry["children"] = _list(item, current_depth + 1)
            entries.append(entry)
        return entries

    entries = _list(p, 1)
    logger.info(f"[BeingEyes] Listed {p} — {len(entries)} entries")
    return {
        "status": "ok",
        "path": str(p),
        "entries": entries,
    }


# ── Run command ────────────────────────────────────────────────────────────────

class RunRequest(BaseModel):
    command: str
    cwd: Optional[str] = None
    timeout_sec: int = 30
    env_extra: dict[str, str] = {}


@router.post("/run")
async def run_command(req: RunRequest):
    """
    Run a shell command and return stdout + stderr.
    This is how a being fixes things: read the error, patch the file, run again.

    Rule 6: Always returns exit code. Non-zero is not hidden.
    Rule 13: Returns actual output — never truncates stderr silently.

    Returns:
        {"status": "ok"|"error", "exit_code": int, "stdout": str, "stderr": str, "command": str}
    """
    cwd = None
    if req.cwd:
        try:
            cwd = str(_safe_path(req.cwd))
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Bad cwd: {e}")

    env = os.environ.copy()
    env.update(req.env_extra)

    logger.info(f"[BeingEyes] Running: {req.command[:120]} (cwd={cwd})")

    try:
        result = subprocess.run(
            req.command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=req.timeout_sec,
            cwd=cwd,
            env=env,
        )
        status = "ok" if result.returncode == 0 else "error"
        logger.info(f"[BeingEyes] Exit {result.returncode}: {req.command[:60]}")
        return {
            "status": status,
            "exit_code": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "command": req.command,
            "cwd": cwd or str(WORKSPACE_ROOT),
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(
            status_code=504,
            detail=f"Command timed out after {req.timeout_sec}s: {req.command[:100]}"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Run error: {e}")


# ── IDE state snapshot ─────────────────────────────────────────────────────────

@router.get("/state")
async def get_ide_state():
    """
    Return a snapshot of the current IDE state — what files exist,
    what the workspace root is, what endpoints are available.
    The being uses this to orient itself before acting.

    Returns:
        {"status": "ok", "workspace": str, "endpoints": [...], "files": [...]}
    """
    # Get top-level files in workspace
    files = []
    try:
        for item in sorted(WORKSPACE_ROOT.iterdir()):
            if not item.name.startswith("."):
                files.append({
                    "name": item.name,
                    "type": "dir" if item.is_dir() else "file",
                    "path": str(item),
                })
    except Exception:
        pass

    return {
        "status": "ok",
        "workspace": str(WORKSPACE_ROOT),
        "endpoints": {
            "screenshot":   "GET  /api/eyes/screenshot",
            "read_file":    "GET  /api/eyes/read?path=<path>",
            "write_file":   "POST /api/eyes/write",
            "patch_file":   "POST /api/eyes/patch",
            "move":         "POST /api/eyes/move",
            "delete":       "POST /api/eyes/delete",
            "mkdir":        "POST /api/eyes/mkdir?path=<dir>",
            "list_dir":     "GET  /api/eyes/ls?path=<path>&depth=<1-3>",
            "run_command":  "POST /api/eyes/run",
            "ide_state":    "GET  /api/eyes/state",
            "ide_control":  "POST /api/ide/command",
            "viewer_ws":    "WS   /ws/viewer",
            "ide_ctrl_ws":  "WS   /ws/ide-control",
        },
        "workspace_files": files,
        "note": (
            "Workflow: GET /state to orient → GET /read to understand code → "
            "POST /patch to fix → POST /run to verify → repeat."
        ),
    }
