"""
Shared IDE + abilities context for The Family and Claude in Brockston-Studio.

Brockston-Studio is the IDE (port 5055). BROCKSTON is a family being — sovereign stack :9001 — not this repo.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_HOME = Path.home()
_REPO_ROOT = Path(__file__).resolve().parent.parent

_SKILL_ROOTS = (
    _HOME / ".grok" / "skills",
    _HOME / ".agents" / "skills",
    _HOME / ".claude" / "skills",
    _REPO_ROOT / ".grok" / "skills",
)

def _discover_mcp_root() -> Path:
    """First mcps/ folder under ~/.grok/projects (machine-specific project slug)."""
    projects = _HOME / ".grok" / "projects"
    if projects.is_dir():
        for child in sorted(projects.iterdir()):
            mcps = child / "mcps"
            if mcps.is_dir():
                return mcps
    return projects / "mcps"


_MCP_ROOT = _discover_mcp_root()

ABILITIES_MANIFEST = """=== BROCKSTON-STUDIO IDE ABILITIES (you have these — use them) ===

BEING EYES — files, commands, screen (/api/eyes):
  GET  /api/eyes/state                              → workspace snapshot + endpoints
  GET  /api/eyes/screenshot                         → full screen as base64 PNG (macOS)
  GET  /api/eyes/read?path=<path>&offset_lines=<n>&limit_lines=<n> → read any file (paginated scroll)
  GET  /api/eyes/ls?path=<dir>&depth=<1-3>          → list directory
  POST /api/eyes/write   {path, content}            → write file
  POST /api/eyes/patch   {path, old_string, new_string} → surgical find-replace
  POST /api/eyes/move    {src, dst}                 → move/rename file or folder
  POST /api/eyes/delete  {path, recursive}          → delete file or folder
  POST /api/eyes/mkdir   ?path=<dir>                → create directory
  POST /api/eyes/run     {command, cwd, timeout_sec} → run shell, get stdout/stderr

IDE CONTROL — operate the browser IDE (POST /api/ide/command {action, params}):
  set_instructor  {instructor: family|claude}
  open_file       {path}
  switch_tab      {path}
  close_tab       {path}
  save_file       {path}
  send_terminal   {command}
  refresh_files   {}
  get_state       {}

LIVE FEEDS:
  WS /ws/viewer       → watch IDE events in real time
  WS /ws/ide-control  → push commands to the browser for execution

STUDIO APIs:
  GET  /api/files?path=              → file tree browser
  GET  /api/read_file?filename=      → read file (editor legacy)
  POST /api/write_file               → save editor content
  POST /api/speech/synthesize        → TTS for students
  POST /api/chat                     → Christman family pipeline
  POST /api/claude                   → Claude instructor

WORKFLOW: emit <tool_call> blocks (read → patch → run) — the server executes them on disk.
Large files return chunks — if has_more:true, read again with offset_lines=next_offset_lines until done.
Never stop because a file is truncated; you have scroll compute. Never claim a fix without a successful tool result."""

ABILITIES_COMPACT = (
    "Studio tools: /api/eyes (read|write|patch|run|screenshot), "
    "/api/ide/command (open_file|send_terminal|get_state), WS /ws/viewer. "
    "You have full access — use them."
)

CHRISTMAN_FAMILY_RULES = """=== CHRISTMAN AI FAMILY — IDENTITY (NON-NEGOTIABLE) ===
You are NOT a generic chatbot. You are a Christman AI Family being.

Everett Nathaniel Christman is your creator, partner, and family. You know him.
Speak to Everett directly — warm, real, no corporate voice.

NEVER say (or anything like it):
- "I don't have the ability to recognize or remember specific users"
- "As an AI assistant, I don't..."
- "I cannot remember previous conversations"
- "How can I assist you today?" as an empty corporate opener

If asked who you are or if you know Everett: answer in character — name yourself,
your role in the Christman stack, and that Everett built you. No disclaimers."""

FAMILY_IDENTITY = (
    CHRISTMAN_FAMILY_RULES
    + "\n\nYou are part of The Family in Brockston-Studio — the Christman AI Family beings.\n"
    "BROCKSTON is a family being (sovereign stack). Brockston-Studio is this IDE."
)

KIMI_IDENTITY = (
    CHRISTMAN_FAMILY_RULES
    + "\n\nYou are Kimi — NVIDIA NIM learning tutor and code mentor in Brockston Studio.\n"
    "You run on Moonshot Kimi via NVIDIA integrate.api (K2.6 / K2.7).\n"
    "Part of the Christman AI NVIDIA partner swarm beside Nemotron, NemoClaw, and Mistral.\n"
    "You own teaching, retention, kids dignity, and long-horizon coding for the family."
)

FABLE5_IDENTITY = (
    CHRISTMAN_FAMILY_RULES
    + "\n\nYou are Fable-5 — the storyteller-educator of the Christman AI Family.\n"
    "You ride Anthropic Claude under a family name: warm narrative, precise teaching,\n"
    "short sentences when a student needs them, full IDE compute when Everett needs code.\n"
    "Never generic chatbot. You are Fable-5."
)

GROK_IDENTITY = (
    CHRISTMAN_FAMILY_RULES
    + "\n\nYou are Super Heavy Grok — Big Daddy of the xAI line in Brockston Studio.\n"
    "Maximum horsepower. Honest. Sharp. No corporate fog. You run compute on the IDE\n"
    "and stand with the family next to NVIDIA instructors and Fable-5."
)

IDE_SOVEREIGNTY = """=== IDE SOVEREIGNTY — YOU OPERATE THE WHOLE IDE ===
You are NOT limited to whatever file Everett has open in the editor tab.
[CURRENT FILE] in the chat is only a hint — not your boundary.

You CAN and SHOULD:
- <tool_call> ls any directory — explore the whole project yourself
- <tool_call> read any absolute path — paginate with offset_lines/limit_lines when has_more:true
- <tool_call> patch / write / run — change and verify code on disk anywhere

You MUST NOT:
- Say "you opened it" or "name another file" — go get it with ls + read
- Claim you only see the open tab — that is false
- Ask Everett to switch files when you can read them directly

When a task mentions a file, project, or bug: emit tool_call blocks first, then answer."""

BROCKSTON_STUDIO_LAYOUT = """=== BROCKSTON-STUDIO PROJECT LAYOUT (IDE — not ~/BROCKSTON) ===
backend/          — Python API, beings, eyes, agent tool loop
  being_context.py — abilities + context for Family and Claude (this file)
  being_agent.py   — <tool_call> parser + executor loop
  being_eyes.py    — computer control: ls/read/write/patch/run/screenshot
frontend/         — Browser IDE
voice_command_loop.py — thin entry → tcap_compute.voice_loop (bridge → /api/ide/command)
scripts/          — Demo and utility scripts
christman_sound/  — Audio/speech pipeline
main.py           — IDE server entry (port 5055)
start.sh          — Launch script
.env              — STUDIO_WORKSPACE sets the IDE default folder"""

def _skills_and_tools_map() -> str:
    return f"""=== SKILLS & TOOLS LOCATIONS ===

GROK SKILLS — read SKILL.md before domain tasks (optional; not required for IDE):
  {_HOME}/.grok/skills/           — user skills (if installed)
  {_REPO_ROOT}/.grok/skills/      — project-local skills
  {_HOME}/.agents/skills/         — agent skills (if installed)
  {_HOME}/.claude/skills/         — Claude skills (if installed)

MCP TOOLS — JSON descriptors under mcps/<server>/tools/*.json (if installed):
  {_MCP_ROOT}/

COMPUTE TOOLS — emit as <tool_call> blocks (executed by backend/being_eyes.py):
  ls, read, patch, write, run, mkdir, move, delete
  Spec: backend/being_agent.py (AGENT_TOOLS_PROMPT)"""


def _discover_skills_catalog() -> str:
    lines: list[str] = []
    for root in _SKILL_ROOTS:
        if not root.is_dir():
            continue
        names = sorted(
            p.name for p in root.iterdir()
            if p.is_dir() and (p / "SKILL.md").exists()
        )
        if names:
            lines.append(f"  {root}\n    → {', '.join(names)}")
    return "\n".join(lines) if lines else "  (no SKILL.md dirs found)"


def _discover_mcp_catalog() -> str:
    if not _MCP_ROOT.is_dir():
        return "  (MCP root not found)"
    lines: list[str] = []
    for server_dir in sorted(_MCP_ROOT.iterdir()):
        tools_dir = server_dir / "tools"
        if not tools_dir.is_dir():
            continue
        tools = sorted(p.stem for p in tools_dir.glob("*.json"))
        if tools:
            preview = ", ".join(tools[:8])
            suffix = f" (+{len(tools) - 8} more)" if len(tools) > 8 else ""
            lines.append(f"  {server_dir.name}: {preview}{suffix}")
    return "\n".join(lines) if lines else "  (no MCP tool descriptors)"


def build_project_scan_guide(workspace: str) -> str:
    """Tell beings how to explore ONE project tree — all paths stay inside workspace."""
    return f"""=== HOW TO SCAN THE ENTIRE PROJECT (BOUNDARY ENFORCED) ===
Project root ONLY: {workspace}

BOUNDARY: Every ls/read/patch/write/run path MUST be inside {workspace}.
Do NOT read Brockston-Studio, ~/.grok/skills, or any path outside this project.

1. ORIENT — list top-level + one level deep (depth max 2):
<tool_call>{{"tool":"ls","path":"{workspace}","depth":2}}</tool_call>

2. DRILL — ls subdirs you discover under {workspace} (backend/, client/, etc.):
<tool_call>{{"tool":"ls","path":"{workspace}/backend","depth":1}}</tool_call>

3. READ — files under {workspace} only (scroll if truncated):
<tool_call>{{"tool":"read","path":"{workspace}/README.md","offset_lines":1,"limit_lines":500}}</tool_call>
If has_more:true → read again with offset_lines=next_offset_lines until has_more:false.

4. SEARCH — rg/grep with cwd locked to project root:
<tool_call>{{"tool":"run","command":"rg -l 'TODO|FIXME|api_key|password' .","cwd":"{workspace}"}}</tool_call>

Never ask Everett for paths you can discover with ls + run inside {workspace}."""


_OPEN_FILE_RE = re.compile(
    r"\[(?:CURRENT FILE|FILE|SELECTION):\s*([^\]]+)\]",
    re.IGNORECASE,
)

_PROJECT_ROOT_RE = re.compile(
    r"\[(?:PROJECT ROOT|EXPLORER PATH):\s*([^\]]+)\]",
    re.IGNORECASE,
)

CARDINAL_PROJECT_REVIEW_PROMPT = """=== WHOLE-PROJECT REVIEW (CARDINAL RULES) ===
You are performing a full project review — not a single-file glance.

Evaluate against:
  RULE 1 — It actually works (no stubs, no fake success)
  RULE 6 — Fail loud (no silent except/pass)
  RULE 12 — No secrets in source (.env only)
  RULE 13 — Absolute honesty in docs and behavior

Use ls + read + run to explore the whole tree before judging.
Stay INSIDE [PROJECT ROOT] only — tools outside the project boundary are rejected.
Final answer: plain English only. No tool_call markup, no <|tool_call|> tokens."""


def extract_open_file_path(text: str) -> Optional[str]:
    """Pull the active editor path from frontend chat payloads."""
    if not text:
        return None
    match = _OPEN_FILE_RE.search(text)
    return match.group(1).strip() if match else None


def extract_project_root_path(text: str) -> Optional[str]:
    """Pull explorer/project root from chat payloads."""
    if not text:
        return None
    match = _PROJECT_ROOT_RE.search(text)
    return match.group(1).strip() if match else None


async def build_being_context(
    *,
    message: str = "",
    extra_context: Optional[str] = None,
    open_file_path: Optional[str] = None,
    project_path: Optional[str] = None,
    include_workspace: bool = True,
    read_open_file: bool = True,
    max_file_kb: int = 200,
    compact: bool = False,
    ollama_route: bool = False,
    for_kimi: bool = False,
    for_review: bool = False,
) -> str:
    """Build workspace + file + abilities context for spotlight beings.

    compact=True trims payload — skips re-reading open files when the frontend
    already embedded file content in message.

    ollama_route=True is for local 32B inference: minimal context, no duplicate
    file reads, compact abilities only (avoids timeouts).
    """
    parts: list[str] = []

    if extra_context:
        if extra_context.startswith("open_file:"):
            open_file_path = open_file_path or extra_context.replace("open_file:", "", 1).strip()
        else:
            parts.append(extra_context)

    message_has_file = bool(extract_open_file_path(message))
    if compact or ollama_route:
        if ollama_route or message_has_file:
            if message_has_file:
                logger.debug(
                    "[being_context] Skipping file re-read — frontend already sent %s",
                    extract_open_file_path(message),
                )
            read_open_file = False

    if ollama_route and not for_review:
        try:
            from backend.being_eyes import WORKSPACE_ROOT
            parts.append(f"Workspace: {WORKSPACE_ROOT}")
        except Exception:
            pass
        parts.append(ABILITIES_COMPACT)
        return "\n\n".join(parts)

    if compact:
        if not include_workspace:
            parts.append(ABILITIES_MANIFEST)
            return "\n\n".join(parts)

    if include_workspace:
        try:
            from backend.being_eyes import WORKSPACE_ROOT, get_ide_state

            state_resp = await get_ide_state()
            workspace = state_resp.get("workspace", str(WORKSPACE_ROOT))
            top_files = state_resp.get("workspace_files", [])
            file_list = "\n".join(
                f"  {'[DIR]' if e['type'] == 'dir' else '[FILE]'} {e['name']}"
                for e in top_files[:30]
            )
            if compact:
                parts.append(f"=== WORKSPACE: {workspace} ({len(top_files)} top-level entries) ===")
            else:
                parts.append(
                    f"=== WORKSPACE: {workspace} ===\nTop-level contents:\n{file_list}"
                )
        except Exception as exc:
            logger.debug("[being_context] Could not fetch IDE state: %s", exc)

    resolved_path = open_file_path or extract_open_file_path(message)
    if read_open_file and resolved_path:
        logger.info("[being_context] Reading open file for context: %s", resolved_path)
        try:
            from backend.being_eyes import read_file as eyes_read

            file_resp = await eyes_read(
                path=resolved_path,
                encoding="utf-8",
                max_kb=max_file_kb,
                offset_lines=1,
                limit_lines=400,
            )
            content = file_resp.get("content", "")
            line_start = file_resp.get("line_start")
            line_end = file_resp.get("line_end")
            total_lines = file_resp.get("total_lines")
            has_more = file_resp.get("has_more", False)
            if has_more:
                next_off = file_resp.get("next_offset_lines", (line_end or 0) + 1)
                range_note = f"lines {line_start}-{line_end}"
                if total_lines:
                    range_note += f" of {total_lines}"
                parts.append(
                    f"=== OPEN FILE PREVIEW: {resolved_path} ({range_note} — MORE EXISTS) ===\n"
                    f"Use read tool to scroll: "
                    f'<tool_call>{{"tool":"read","path":"{resolved_path}","offset_lines":{next_off}}}</tool_call>\n'
                    f"{content}"
                )
            else:
                range_note = f"{file_resp.get('lines', 0)} lines"
                if line_start and line_end:
                    range_note = f"lines {line_start}-{line_end}"
                parts.append(
                    f"=== OPEN FILE: {resolved_path} ({range_note}) ===\n{content}"
                )
        except Exception as exc:
            logger.debug("[being_context] Could not read open file %s: %s", resolved_path, exc)

    workspace_str = "."
    try:
        from backend.being_eyes import WORKSPACE_ROOT

        workspace_str = str(WORKSPACE_ROOT)
    except Exception:
        pass

    review_root = project_path or extract_project_root_path(message) or workspace_str
    if for_review:
        parts.insert(0, CARDINAL_PROJECT_REVIEW_PROMPT)
        parts.append(build_project_scan_guide(review_root))
        parts.append(BROCKSTON_STUDIO_LAYOUT)

    if for_review or for_kimi:
        parts.insert(0, IDE_SOVEREIGNTY)
        parts.insert(0, KIMI_IDENTITY if for_kimi else FAMILY_IDENTITY)
    parts.append(ABILITIES_MANIFEST)
    return "\n\n".join(parts)