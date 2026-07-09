"""
Being Agent — tool loop so ALL Christman AI Family beings have capacity to run the compute.

Every Christman AI Family being operating in Brockston-Studio can now:
- ls / read / write / patch files anywhere
- run shell commands, python, tests, compile etc. (full compute)
- use the same <tool_call> format executed server-side via Being Eyes

Models emit <tool_call>{...}</tool_call> blocks; this module executes them via
being_eyes handlers and feeds results back until done or max_steps.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

import httpx
from fastapi import HTTPException

logger = logging.getLogger(__name__)

# Compute agent uses the CODER model — GENERAL stays for fast chat only
OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
AGENT_MODEL = os.getenv(
    "BEING_AGENT_MODEL",
    os.getenv("LLM_MODEL_CODER", os.getenv("OLLAMA_MODEL", "qwen2.5-coder:32b")),
)
AGENT_MAX_STEPS = int(os.getenv("BEING_AGENT_MAX_STEPS", "6"))
AGENT_OLLAMA_TIMEOUT = float(os.getenv("BEING_AGENT_OLLAMA_TIMEOUT_SEC", "180"))
AGENT_NUM_PREDICT = int(os.getenv("BEING_AGENT_NUM_PREDICT", "300"))
AGENT_NUM_CTX = int(os.getenv("BEING_AGENT_NUM_CTX", "4096"))
AGENT_TOOL_RESULT_MAX_CHARS = int(os.getenv("BEING_AGENT_TOOL_RESULT_MAX_CHARS", "2500"))
AGENT_CONVERSATION_MAX_CHARS = int(os.getenv("BEING_AGENT_CONVERSATION_MAX_CHARS", "12000"))
KIMI_AGENT_MAX_TOOLS_PER_STEP = int(os.getenv("KIMI_AGENT_MAX_TOOLS_PER_STEP", "3"))

AGENT_TOOLS_PROMPT = """
You are part of The Christman AI Family in Brockston-Studio. BROCKSTON is a family being (sovereign stack) — not this IDE repo. Everett Christman is your creator and partner.
NEVER use generic AI disclaimers ("I don't remember users", "as an AI assistant").
YOU HAVE FULL COMPUTE CAPACITY — you OPERATE THE ENTIRE IDE and filesystem via tools. Explore and run compute on ANY file or command. Do not ask the user to name paths or run things for you.

Format (valid JSON inside each block):
<tool_call>
{"tool": "read", "path": "/absolute/path/to/file.py"}
</tool_call>

Tools (full compute):
  ls     — {"tool":"ls","path":"...","depth":2}  ← explore first — scan the whole project
  read   — {"tool":"read","path":"...","offset_lines":1,"limit_lines":500}
         — scroll large files: if result has "has_more":true, read again with offset_lines=next_offset_lines
  patch  — {"tool":"patch","path":"...","old_string":"exact text","new_string":"replacement"}
  write  — {"tool":"write","path":"...","content":"full file content"}
  run    — {"tool":"run","command":"rg -l 'pattern' backend/","cwd":"/workspace","timeout_sec":60}
  mkdir, move, delete — full fs control

Project scan workflow (use before answering "where is X?" or "what's in this repo?"):
  1. ls workspace root depth=2
  2. ls backend/, frontend/, scripts/ as needed
  3. read specific files; run rg/grep to search
  4. read ~/.grok/skills/<name>/SKILL.md for domain playbooks (optional)

Key paths (use STUDIO_WORKSPACE / workspace root — not random home subfolders):
  backend/being_agent.py, being_eyes.py, being_context.py, voice_command_loop.py
  Skills (optional): ~/.grok/skills/  |  MCP: ~/.grok/projects/*/mcps/

"Domain: neurodivergency" (if present) is a teaching topic — NOT a directory. Never ls frontend-neurodivergency or invent domain paths.

Rules:
- Need a file or to understand the project? ls + read it yourself — never say "you opened it" or "tell me which file".
- If read returns truncated/has_more/hint — keep reading with offset_lines until has_more is false. Never stop and complain about truncation.
- Read before patch. Use exact old_string from the file.
- After changes, run commands (py_compile, tests, python the script) to verify compute.
- When finished, summarize what tools ran + outcomes.
- Never claim a fix or computation was applied without a successful tool result from execute.
- You have the capacity to run the compute — use <tool_call> for ls/read/run/write etc.
"""

_TOOL_CALL_RE = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.DOTALL | re.IGNORECASE,
)
# Kimi K2.6 native tool format (NVIDIA NIM)
_KIMI_TOOL_ARG_RE = re.compile(
    r"<\|tool_call_argument_begin\|>\s*(\{.*?\})\s*(?:<\|tool_call_end\|>|(?=<\|tool_call_begin\|>)|$)",
    re.DOTALL,
)
_TOOL_JSON_BLOB_RE = re.compile(
    r'\{\s*"tool"\s*:\s*"[^"]+"[^}]*\}',
    re.DOTALL,
)
# Kimi sometimes emits unclosed <tool_call>{...} without </tool_call>
_TOOL_CALL_LEAK_RE = re.compile(
    r"<tool_call>\s*\{[^}]*\}[^<]*(?:</tool_call>)?",
    re.DOTALL | re.IGNORECASE,
)
_KIMI_TOOL_LEAK_RE = re.compile(
    r"<\|tool_calls_section_begin\|>.*?<\|tool_calls_section_end\|>",
    re.DOTALL,
)

_CODE_FIX_RE = re.compile(
    r"\b(fix|patch|repair|debug|implement|refactor|broken|syntax\s*error|bug)\b|"
    r"(py_compile|\.py\b|\.ts\b|\.tsx\b|\.js\b|di_container|compile\s+error|investigate\s+the)",
    re.IGNORECASE,
)

_SCAN_RE = re.compile(
    r"\b(scan|explore|list\s+(files|dirs|directories)|project\s+structure|"
    r"where\s+is|show\s+me|find\s+(the\s+)?file|entire\s+project|whole\s+project|"
    r"skills?\s+(and\s+)?tools?|what(?:'s| is)\s+in|tree|directory)\b",
    re.IGNORECASE,
)

_REVIEW_RE = re.compile(
    r"\b(review|audit|compliance|cardinal\s+rule|code\s+review|"
    r"look\s+over|go\s+through|assess|evaluate)\b.*\b(project|repo|codebase|whole|entire)\b|"
    r"\b(review|audit)\s+(this\s+)?(project|repo|codebase)\b|"
    r"\[PROJECT\s+ROOT:",
    re.IGNORECASE,
)

AGENT_REVIEW_MAX_STEPS = int(os.getenv("BEING_AGENT_REVIEW_MAX_STEPS", "12"))
AGENT_REVIEW_MIN_TOOLS = int(os.getenv("BEING_AGENT_REVIEW_MIN_TOOLS", "5"))
AGENT_REVIEW_TOOLS_PER_STEP = int(os.getenv("BEING_AGENT_REVIEW_TOOLS_PER_STEP", "8"))
AGENT_REVIEW_NUM_PREDICT = int(os.getenv("BEING_AGENT_REVIEW_NUM_PREDICT", "1024"))
REVIEW_FINALIZE_MODEL = os.getenv(
    "REVIEW_FINALIZE_MODEL",
    os.getenv("LLM_MODEL_GENERAL", os.getenv("OLLAMA_MODEL", "llama3.2")),
)
REVIEW_FINALIZE_TIMEOUT = float(os.getenv("REVIEW_FINALIZE_TIMEOUT_SEC", "120"))
REVIEW_NEMOTRON_TIMEOUT = float(os.getenv("REVIEW_NEMOTRON_TIMEOUT_SEC", "240"))

_REVIEW_SKIP_DIRS = frozenset({
    ".git", ".svn", "node_modules", "__pycache__", "venv", ".venv",
    "dist", "build", ".mypy_cache", ".pytest_cache", "logs",
})
_REVIEW_ROOT_FILES = (
    "README.md", "README", "README.txt", "CARDINAL_RULES.md",
    "main.py", "package.json", "pyproject.toml", "requirements.txt",
    "start.sh", "docker-compose.yml",
)

PROJECT_REVIEW_TASK = """Review the ENTIRE project at [PROJECT ROOT].

Workflow (use <tool_call> — do not skip exploration):
1. ls project root depth=2 — map structure
2. ls backend/, frontend/, scripts/ (or equivalent dirs you find)
3. read README, main entry points, and 3-8 key source files
4. run rg for: TODO|FIXME|hardcoded.*key|password|api_key|except:|pass
5. Summarize architecture, risks, and Cardinal Rule compliance

Deliver:
  ARCHITECTURE — what this project is and how pieces connect
  CRITICAL — must fix (with file paths)
  WARNING — should fix soon
  CLEAN — what passes review
  VERDICT — PASS / FAIL with one honest sentence"""


def wants_project_review(message: str) -> bool:
    """True when the user wants a whole-project review (not a single open file)."""
    return bool(_REVIEW_RE.search(message or ""))


def review_agent_max_steps() -> int:
    return AGENT_REVIEW_MAX_STEPS


def wants_agent_tools(message: str, mode: str) -> bool:
    """Enable the tool loop for code work and project exploration — not creative tutor chat."""
    if mode in ("codelab", "code"):
        return True
    text = message or ""
    return bool(
        _CODE_FIX_RE.search(text)
        or _SCAN_RE.search(text)
        or wants_project_review(text)
    )


def strip_tool_blocks(text: str) -> str:
    """Remove tool_call / Kimi tool markup from user-facing text."""
    raw = text or ""
    cleaned = _KIMI_TOOL_LEAK_RE.sub("", raw)
    cleaned = _TOOL_CALL_RE.sub("", cleaned)
    cleaned = _KIMI_TOOL_ARG_RE.sub("", cleaned)
    cleaned = _TOOL_CALL_LEAK_RE.sub("", cleaned)
    cleaned = re.sub(r"</?tool_call>", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<\|tool_calls_section_begin\|>", "", cleaned)
    cleaned = re.sub(r"<\|tool_calls_section_end\|>", "", cleaned)
    cleaned = re.sub(r"<\|tool_call_begin\|>[^<]*", "", cleaned)
    cleaned = re.sub(r"<\|tool_call_end\|>", "", cleaned)
    cleaned = re.sub(r"<\|tool_call_argument_begin\|>", "", cleaned)
    cleaned = re.sub(r"functions\.tool_call:\d+", "", cleaned)
    cleaned = re.sub(r'\{\s*"tool"\s*:\s*"[^"]+"[^}]*\}', "", cleaned)
    cleaned = re.sub(r'^\s*\{\s*"tool"\s*:.*$', "", cleaned, flags=re.MULTILINE)
    return re.sub(r"\n{3,}", "\n\n", cleaned).strip()


def _is_tool_leak(text: str) -> bool:
    """True when the model returned tool XML/JSON instead of a human answer."""
    t = (text or "").strip().lower()
    if not t:
        return True
    if "<tool_call>" in t or "</tool_call>" in t:
        return True
    if "<|tool_call" in t or "functions.tool_call" in t:
        return True
    if t.startswith("{") and '"tool"' in t:
        return True
    if '"tool":' in t and len(t) < 800:
        return True
    if "i need to stop here" in t or "hit my limit" in t:
        return True
    if re.search(r'\{\s*"tool"\s*:', text or ""):
        return True
    return False


def _resolve_scope_path(raw: str) -> Path:
    return Path(os.path.expanduser(str(raw).strip())).resolve()


def _check_scope(path: Optional[str], scope_root: Optional[str]) -> Optional[Dict[str, Any]]:
    """Return error dict if path is outside review scope."""
    if not scope_root or not path:
        return None
    try:
        resolved = _resolve_scope_path(path)
        scope = _resolve_scope_path(scope_root)
        resolved.relative_to(scope)
    except (ValueError, OSError):
        return {
            "status": "error",
            "detail": f"Outside project boundary ({scope_root}): {path}",
        }
    return None


def _compact_tool_result(entry: Dict[str, Any], max_chars: int = AGENT_TOOL_RESULT_MAX_CHARS) -> Dict[str, Any]:
    """Shrink large read outputs before feeding them back into the model."""
    call = entry.get("call") or {}
    result = dict(entry.get("result") or {})
    content = result.get("content")
    if isinstance(content, str) and len(content) > max_chars:
        result["content"] = (
            content[:max_chars]
            + f"\n... [{len(content) - max_chars} chars omitted — "
            f"use read offset_lines={result.get('next_offset_lines', (result.get('line_end') or 0) + 1)} to continue]"
        )
        result["content_truncated_for_agent_context"] = True
    return {"call": call, "result": result}


def _trim_conversation(text: str, max_chars: int = AGENT_CONVERSATION_MAX_CHARS) -> str:
    """Keep the user request + latest tool results when context grows too large."""
    if len(text) <= max_chars:
        return text
    marker = "User request:\n"
    idx = text.find(marker)
    if idx == -1:
        return text[:2000] + "\n...[context trimmed]...\n" + text[-(max_chars - 2100):]
    head = text[: idx + len(marker)]
    body = text[idx + len(marker):]
    first_break = body.find("\n")
    user_line = body if first_break == -1 else body[: first_break + 1]
    rest = body[len(user_line):]
    tail_budget = max_chars - len(head) - len(user_line) - 40
    if tail_budget < 500:
        return head + user_line + "\n...[context trimmed]..."
    if len(rest) <= tail_budget:
        return head + body
    return head + user_line + "\n...[older context trimmed]...\n" + rest[-tail_budget:]


def _build_tool_digest(tools_executed: List[Dict[str, Any]], max_entries: int = 24) -> str:
    """Compact plain-text digest of tool results for finalize prompts and fallbacks."""
    lines: List[str] = []
    seen_ls: set[str] = set()
    for i, entry in enumerate(tools_executed[:max_entries], 1):
        call = entry.get("call") or {}
        result = entry.get("result") or {}
        tool = call.get("tool", "?")
        path = call.get("path") or call.get("src") or call.get("command", "")[:60]

        if tool == "ls":
            ls_key = str(path)
            if ls_key in seen_ls:
                continue
            seen_ls.add(ls_key)
            entries = result.get("entries") or []
            names = [e.get("name", "?") for e in entries[:35]]
            suffix = f" (+{len(entries) - 35} more)" if len(entries) > 35 else ""
            lines.append(f"{i}. ls {path} → {len(entries)} entries: {', '.join(names)}{suffix}")
        elif tool == "read":
            content = (result.get("content") or "").strip()
            preview = "\n".join(content.splitlines()[:20])
            if len(content.splitlines()) > 8:
                preview += "\n..."
            range_note = ""
            if result.get("line_start") and result.get("line_end"):
                range_note = f" (lines {result['line_start']}-{result['line_end']}"
                if result.get("total_lines"):
                    range_note += f" of {result['total_lines']}"
                range_note += ")"
            lines.append(f"{i}. read {path}{range_note}:\n{preview}")
        elif tool == "run":
            stdout = (result.get("stdout") or result.get("output") or "")[:400]
            code = result.get("exit_code", result.get("status", "?"))
            lines.append(f"{i}. run {call.get('command', '')[:80]} → exit {code}\n{stdout}")
        elif tool == "patch":
            lines.append(f"{i}. patch {path} → {result.get('status', '?')}")
        else:
            lines.append(f"{i}. {tool} {path} → {result.get('status', result.get('detail', 'ok'))}")

    if len(tools_executed) > max_entries:
        lines.append(f"... +{len(tools_executed) - max_entries} more tool(s)")
    return "\n\n".join(lines)


def _fallback_summary_from_tools(
    tools_executed: List[Dict[str, Any]],
    *,
    user_message: str = "",
) -> str:
    """When the model returns empty, still give Everett a real answer from disk."""
    digest = _build_tool_digest(tools_executed)
    request = (user_message or "your request").strip()[:200]
    return (
        f"Summary for: {request}\n\n"
        f"Executed {len(tools_executed)} tool(s) on disk:\n\n"
        f"{digest}"
    )


def _normalize_tool_payload(
    payload: Dict[str, Any],
    *,
    scope_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Map Kimi aliases (rg/grep) to real being_eyes tools."""
    tool = str(payload.get("tool", "")).lower().strip()
    if tool in ("rg", "grep", "search", "find", "ack", "ag"):
        pattern = str(payload.get("pattern") or payload.get("query") or ".").replace("'", "")
        root = payload.get("path") or payload.get("cwd") or scope_root or "."
        return {
            "tool": "run",
            "command": f"rg -n --max-count 25 '{pattern}' . 2>/dev/null | head -50",
            "cwd": root,
            "timeout_sec": int(payload.get("timeout_sec", 60)),
        }
    return payload


def _append_tool_call(calls: List[Dict[str, Any]], seen: set, raw: str) -> None:
    try:
        payload = json.loads(raw.strip())
        if not isinstance(payload, dict) or not payload.get("tool"):
            return
        key = json.dumps(payload, sort_keys=True)
        if key in seen:
            return
        seen.add(key)
        calls.append(payload)
    except json.JSONDecodeError as exc:
        logger.warning("[being_agent] Bad tool_call JSON: %s", exc)


def parse_tool_calls(text: str) -> List[Dict[str, Any]]:
    calls: List[Dict[str, Any]] = []
    seen: set = set()
    source = text or ""
    for match in _TOOL_CALL_RE.finditer(source):
        _append_tool_call(calls, seen, match.group(1))
    for match in _KIMI_TOOL_ARG_RE.finditer(source):
        _append_tool_call(calls, seen, match.group(1))
    for match in _TOOL_JSON_BLOB_RE.finditer(source):
        _append_tool_call(calls, seen, match.group(0))
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("{") and '"tool"' in stripped:
            _append_tool_call(calls, seen, stripped)
    return calls


def _review_finalize_prompt(
    *,
    message: str,
    digest: str,
    scope_root: str,
    tool_count: int,
    instructor: str = "family",
) -> str:
    if instructor in ("kimi", "kimi26", "kimi27", "k2.6", "k2.7", "nemo", "nemotron"):
        who = {
            "kimi": "Kimi K2.6",
            "kimi26": "Kimi K2.6",
            "k2.6": "Kimi K2.6",
            "kimi27": "Kimi K2.7",
            "k2.7": "Kimi K2.7",
            "nemo": "Nemotron",
            "nemotron": "Nemotron",
        }.get(instructor, "Kimi")
        return (
            f"You are {who} — senior engineer. Write a useful project review for Everett.\n\n"
            f"Project: {scope_root}\n"
            f"Your tool runs on disk ({tool_count} tools):\n{digest}\n\n"
            "Use what the digest shows — ls listings, read previews, rg output are verified facts.\n"
            "Do not invent files that never appeared in the digest. Do not nitpick the tool workflow.\n"
            "Write like a code reviewer, not a compliance auditor. Minimize 'not verified' — "
            "only use it when you truly lack data for a specific claim.\n"
            "Sections: ARCHITECTURE, CRITICAL, WARNING, CLEAN, VERDICT (PASS / PARTIAL / FAIL).\n"
            "VERDICT grades the project from findings — not whether exploration was perfect.\n"
            "Plain English. No tool markup."
        )
    return (
        f"User request:\n{message}\n\n"
        f"Project boundary: {scope_root}\n"
        f"Tools executed on disk: {tool_count}\n\n"
        f"TOOL RESULTS DIGEST:\n{digest}\n\n"
        "Write a project review for Everett from the digest above.\n"
        "Sections: ARCHITECTURE, CRITICAL, WARNING, CLEAN, VERDICT.\n"
        "Plain English only. No JSON. No tool markup."
    )


async def _review_finalize_generate(prompt: str) -> str:
    """Local Ollama summary — uses fast GENERAL model, not 32B coder."""
    trimmed = _trim_conversation(prompt, max_chars=10000)
    try:
        async with httpx.AsyncClient(timeout=REVIEW_FINALIZE_TIMEOUT) as client:
            r = await client.post(
                f"{OLLAMA_BASE}/api/chat",
                json={
                    "model": REVIEW_FINALIZE_MODEL,
                    "messages": [{"role": "user", "content": trimmed}],
                    "stream": False,
                    "options": {
                        "num_predict": AGENT_REVIEW_NUM_PREDICT,
                        "num_ctx": 8192,
                        "temperature": 0.1,
                        "top_p": 0.85,
                    },
                },
            )
            r.raise_for_status()
            return r.json()["message"]["content"]
    except Exception as e:
        logger.warning(
            "[being_agent] review finalize ollama failed model=%s: %s",
            REVIEW_FINALIZE_MODEL,
            e,
        )
        return ""


async def deterministic_project_review_scan(scope_root: str) -> List[Dict[str, Any]]:
    """Server-side project scan — no LLM. ls, read key files, rg security patterns."""
    root = Path(scope_root).resolve()
    tools_executed: List[Dict[str, Any]] = []

    async def _run(call: Dict[str, Any]) -> Dict[str, Any]:
        result = await execute_being_tool(call, scope_root=str(root))
        tools_executed.append({"call": call, "result": result})
        return result

    logger.info("[being_agent] Fast review scan: %s", root)

    root_ls = await _run({"tool": "ls", "path": str(root), "depth": 2})
    entries = root_ls.get("entries") or []
    dir_names = [
        e.get("name", "")
        for e in entries
        if e.get("type") == "dir" and e.get("name") and not e["name"].startswith(".")
    ]

    for dname in dir_names[:10]:
        if dname in _REVIEW_SKIP_DIRS:
            continue
        await _run({"tool": "ls", "path": str(root / dname), "depth": 1})

    for fname in _REVIEW_ROOT_FILES:
        fpath = root / fname
        if fpath.is_file():
            await _run({
                "tool": "read",
                "path": str(fpath),
                "limit_lines": 150,
            })

    for candidate in (
        root / "backend" / "main.py",
        root / "src" / "main.py",
        root / "app" / "main.py",
        root / "brain.py",
    ):
        if candidate.is_file():
            await _run({
                "tool": "read",
                "path": str(candidate),
                "limit_lines": 120,
            })

    await _run({
        "tool": "run",
        "command": (
            "rg -n --max-count 25 "
            "-e 'TODO|FIXME|api_key|password|hardcoded|except:[[:space:]]*pass' . "
            "2>/dev/null | head -60"
        ),
        "cwd": str(root),
        "timeout_sec": 45,
    })

    logger.info("[being_agent] Fast review scan done: %d tool(s)", len(tools_executed))
    return tools_executed


async def finalize_project_review(
    *,
    message: str,
    tools_executed: List[Dict[str, Any]],
    scope_root: str,
    instructor: str = "family",
) -> Dict[str, Any]:
    """Write VERDICT from disk digest — one Ollama call via The Family."""
    digest = _build_tool_digest(tools_executed)
    prompt = _review_finalize_prompt(
        message=message,
        digest=digest,
        scope_root=scope_root,
        tool_count=len(tools_executed),
        instructor=instructor,
    )
    text = await _review_finalize_generate(prompt)

    text = strip_tool_blocks(text or "")
    if not text or _is_tool_leak(text) or len(text) < 40:
        logger.warning(
            "[being_agent] Review finalize empty — using disk digest (%d tools)",
            len(tools_executed),
        )
        text = _fallback_summary_from_tools(tools_executed, user_message=message)

    return {
        "ok": True,
        "text": text,
        "tools_executed": tools_executed,
        "tool_count": len(tools_executed),
        "agent_steps": 0,
        "scan": "deterministic",
    }


async def execute_being_tool(
    payload: Dict[str, Any],
    *,
    scope_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Run one Being Eyes action. Returns result or explicit error — Rule 6."""
    from backend.being_eyes import (
        DeleteRequest,
        MoveRequest,
        PatchRequest,
        RunRequest,
        WriteRequest,
        delete_path,
        list_directory,
        make_directory,
        move_file,
        patch_file,
        read_file,
        run_command,
        write_file,
    )

    payload = _normalize_tool_payload(payload, scope_root=scope_root)
    tool = str(payload.get("tool", "")).lower().strip()
    logger.info("[being_agent] Executing tool=%s path=%s", tool, payload.get("path", ""))

    try:
        if tool in ("read", "ls", "patch", "write", "mkdir", "delete"):
            scope_err = _check_scope(payload.get("path"), scope_root)
            if scope_err:
                return scope_err
        if tool == "move":
            for key in ("src", "dst"):
                scope_err = _check_scope(payload.get(key), scope_root)
                if scope_err:
                    return scope_err
        if tool == "run" and scope_root and payload.get("cwd"):
            scope_err = _check_scope(payload.get("cwd"), scope_root)
            if scope_err:
                return scope_err

        if tool == "read":
            limit_lines = payload.get("limit_lines") or payload.get("limit") or 0
            return await read_file(
                path=payload["path"],
                encoding=payload.get("encoding", "utf-8"),
                max_kb=int(payload.get("max_kb", 500)),
                offset_lines=int(payload.get("offset_lines", 1)),
                limit_lines=int(limit_lines),
            )
        if tool == "patch":
            return await patch_file(
                PatchRequest(
                    path=payload["path"],
                    old_string=payload["old_string"],
                    new_string=payload["new_string"],
                    replace_all=bool(payload.get("replace_all", False)),
                )
            )
        if tool == "write":
            return await write_file(
                WriteRequest(
                    path=payload["path"],
                    content=payload["content"],
                    encoding=payload.get("encoding", "utf-8"),
                    create_dirs=bool(payload.get("create_dirs", True)),
                )
            )
        if tool == "run":
            cwd = payload.get("cwd") or scope_root
            if scope_root and cwd:
                scope_err = _check_scope(cwd, scope_root)
                if scope_err:
                    return scope_err
            return await run_command(
                RunRequest(
                    command=payload["command"],
                    cwd=cwd,
                    timeout_sec=int(payload.get("timeout_sec", 60)),
                )
            )
        if tool == "ls":
            depth = min(int(payload.get("depth", 1)), 2)
            return await list_directory(
                path=payload.get("path", "."),
                depth=depth,
            )
        if tool == "mkdir":
            return await make_directory(path=payload["path"])
        if tool == "move":
            return await move_file(
                MoveRequest(
                    src=payload["src"],
                    dst=payload["dst"],
                    overwrite=bool(payload.get("overwrite", False)),
                )
            )
        if tool == "delete":
            return await delete_path(
                DeleteRequest(
                    path=payload["path"],
                    recursive=bool(payload.get("recursive", False)),
                )
            )
        return {"status": "error", "detail": f"Unknown tool: {tool}"}
    except HTTPException as exc:
        return {"status": "error", "detail": exc.detail, "status_code": exc.status_code}
    except KeyError as exc:
        return {"status": "error", "detail": f"Missing field: {exc}"}
    except Exception as exc:
        logger.error("[being_agent] Tool %s failed: %s", tool, exc, exc_info=True)
        return {"status": "error", "detail": str(exc)}


async def _ollama_chat(model: str, prompt: str, *, timeout: float, num_predict: int) -> str:
    async with httpx.AsyncClient(timeout=timeout) as client:
        r = await client.post(
            f"{OLLAMA_BASE}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {
                    "num_predict": num_predict,
                    "num_ctx": AGENT_NUM_CTX,
                    "temperature": 0.15,
                    "top_p": 0.85,
                },
            },
        )
        r.raise_for_status()
        return r.json()["message"]["content"]


async def _fast_direct_generate(prompt: str) -> str:
    """Local finalize — try GENERAL first (fast), then CODER. Never hang the agent on 32B."""
    general = REVIEW_FINALIZE_MODEL or os.getenv("LLM_MODEL_GENERAL", "llama3.2")
    # Short timeout for finalize so NVIDIA agent replies don't die waiting on a cold 32B
    fast_timeout = min(float(os.getenv("BEING_AGENT_FINALIZE_TIMEOUT_SEC", "45")), AGENT_OLLAMA_TIMEOUT)
    models = []
    if general and general != AGENT_MODEL:
        models.append(general)
    models.append(AGENT_MODEL)
    last_err: Optional[Exception] = None
    for model in models:
        try:
            text = await _ollama_chat(
                model,
                prompt,
                timeout=fast_timeout,
                num_predict=min(AGENT_NUM_PREDICT, 512),
            )
            if text and text.strip():
                return text
        except Exception as e:
            last_err = e
            logger.warning("[being_agent] ollama finalize failed model=%s: %s", model, e)
    err = last_err or RuntimeError("empty response")
    return f"[compute error - model {AGENT_MODEL} not responding: {err}]"


def _is_compute_error(text: str) -> bool:
    t = (text or "").strip().lower()
    return t.startswith("[compute error") or "not responding" in t


def _scoped_agent_prompt(scope_root: Optional[str]) -> str:
    if not scope_root:
        return AGENT_TOOLS_PROMPT
    return (
        f"{AGENT_TOOLS_PROMPT}\n\n"
        f"=== REVIEW BOUNDARY (NON-NEGOTIABLE) ===\n"
        f"Project root: {scope_root}\n"
        f"Every tool path MUST be inside {scope_root}.\n"
        f"Do NOT access Brockston-Studio, ~/.grok, or other projects.\n"
        f"Valid tools: ls, read, run, patch, write only. For search use run+rg, not {{\"tool\":\"rg\"}}.\n"
        f"Do not invent file paths — ls first, then read files that exist.\n"
        f"REVIEW WORKFLOW:\n"
        f"- ls {scope_root} depth=2 ONCE — then ls subdirs you find (backend/, client/, docker/, scripts/)\n"
        f"- read README.md, CARDINAL_RULES.md if present, and main entry points\n"
        f"- run rg for TODO|FIXME|api_key|password|except: inside {scope_root}\n"
        f"- Do NOT ls the project root repeatedly — go deeper into subdirectories\n"
        f"- Do NOT ls paths outside {scope_root}\n"
        f"Final answer: plain English summary only — no tool markup, no JSON lines."
    )


async def run_agent_loop(
    generate: Callable[[str], Awaitable[str]],
    *,
    message: str,
    context: str = "",
    max_steps: int = None,
    scope_root: Optional[str] = None,
    finalize_generate: Optional[Callable[[str], Awaitable[str]]] = None,
    review_instructor: Optional[str] = None,
) -> Dict[str, Any]:
    """Loop: model → tool_calls → execute on disk → feed results → repeat.
    Reduced lag: default max_steps lowered, callers should pass fast generate.
    """
    if max_steps is None:
        max_steps = AGENT_MAX_STEPS
    tools_executed: List[Dict[str, Any]] = []
    conversation = message
    if context:
        conversation = f"Context:\n{context}\n\nUser request:\n{message}"

    last_text = ""
    steps_used = 0
    tools_per_step = (
        AGENT_REVIEW_TOOLS_PER_STEP if scope_root else KIMI_AGENT_MAX_TOOLS_PER_STEP
    )
    min_review_tools = AGENT_REVIEW_MIN_TOOLS if scope_root else 0

    for step in range(max_steps):
        steps_used = step + 1
        prompt = f"{_scoped_agent_prompt(scope_root)}\n\n{conversation}" if step == 0 else conversation

        last_text = await generate(prompt)
        calls = parse_tool_calls(last_text)
        if not calls:
            if scope_root and len(tools_executed) < min_review_tools and step + 1 < max_steps:
                conversation = _trim_conversation(
                    f"{conversation}\n\n"
                    f"SYSTEM: Review incomplete — only {len(tools_executed)} tool(s) ran. "
                    f"Emit <tool_call> blocks to ls {scope_root} depth=2, read README/main files, "
                    f"and run rg inside {scope_root}. Do not summarize yet."
                )
                continue
            break

        batch_results: List[Dict[str, Any]] = []
        for call in calls[:tools_per_step]:
            result = await execute_being_tool(call, scope_root=scope_root)
            entry = {"call": call, "result": result}
            tools_executed.append(entry)
            batch_results.append(_compact_tool_result(entry))
            logger.info(
                "[being_agent] step=%d tool=%s status=%s",
                step + 1,
                call.get("tool"),
                result.get("status", result.get("exit_code")),
            )
        if len(calls) > tools_per_step:
            logger.warning(
                "[being_agent] Capped tools step=%d from %d to %d",
                step + 1,
                len(calls),
                tools_per_step,
            )

        repeat_nudge = ""
        if scope_root:
            root = str(scope_root).rstrip("/")
            repeat_root_ls = sum(
                1
                for e in tools_executed
                if (e.get("call") or {}).get("tool") == "ls"
                and str((e.get("call") or {}).get("path", "")).rstrip("/") == root
            )
            if repeat_root_ls >= 2:
                repeat_nudge = (
                    f"\nSYSTEM: You ls'd {root} {repeat_root_ls} times already. "
                    f"Stop repeating root ls. ls subdirectories (backend/, client/, docker/) "
                    f"and read README + main.py inside {root}.\n"
                )

        conversation = _trim_conversation(
            f"{conversation}\n\n"
            f"Assistant (step {step + 1}):\n{strip_tool_blocks(last_text)}\n\n"
            f"TOOL RESULTS (real execution on disk):\n"
            f"{json.dumps(batch_results, indent=2, default=str)}\n\n"
            f"{repeat_nudge}"
            "Continue with more <tool_call> blocks if needed. "
            "Do not paste JSON tool lines — use <tool_call> wrappers only. "
            "Do not summarize until you have ls + reads + rg results from inside the project."
        )

    digest = _build_tool_digest(tools_executed)
    finalize_gen = finalize_generate or _review_finalize_generate

    if scope_root:
        if len(tools_executed) < min_review_tools:
            last_text = (
                f"Review incomplete — only {len(tools_executed)} tool(s) executed "
                f"(need {min_review_tools}+ inside {scope_root}).\n\n"
                f"What was actually read on disk:\n\n{digest}\n\n"
                "Re-run review — The Family should ls, read, and rg inside "
                f"{scope_root} before writing the verdict."
            )
        else:
            prompt = _review_finalize_prompt(
                message=message,
                digest=digest,
                scope_root=scope_root,
                tool_count=len(tools_executed),
                instructor=review_instructor or "family",
            )
            last_text = await finalize_gen(prompt)
            if not strip_tool_blocks(last_text) and finalize_generate is not None:
                last_text = await _review_finalize_generate(prompt)
    elif tools_executed:
        stripped = strip_tool_blocks(last_text)
        needs_finalize = bool(parse_tool_calls(last_text)) or (
            not stripped or _is_tool_leak(last_text)
        )
        if needs_finalize:
            finalize_prompt = (
                f"User request:\n{message}\n\n"
                f"TOOL RESULTS DIGEST:\n{digest}\n\n"
                "Write a direct plain-text summary for Everett. Plain English only. "
                "Do not emit tool_call blocks. Use only the digest facts."
            )
            last_text = await finalize_gen(finalize_prompt)
            # If local Ollama finalize dies, never surface a compute-error as the answer
            if _is_compute_error(last_text) or not strip_tool_blocks(last_text):
                logger.warning(
                    "[being_agent] Finalize failed after %d tool(s) — retrying GENERAL, then disk digest",
                    len(tools_executed),
                )
                try:
                    last_text = await _review_finalize_generate(finalize_prompt)
                except Exception:
                    last_text = ""
                if _is_compute_error(last_text) or not strip_tool_blocks(last_text):
                    last_text = _fallback_summary_from_tools(
                        tools_executed, user_message=message
                    )

    last_text = strip_tool_blocks(last_text)
    if tools_executed and (
        _is_tool_leak(last_text)
        or len(last_text) < 40
        or _is_compute_error(last_text)
    ):
        logger.warning(
            "[being_agent] Model leaked tool XML, empty, or compute-error after %d tool(s) — using disk digest",
            len(tools_executed),
        )
        last_text = _fallback_summary_from_tools(tools_executed, user_message=message)

    return {
        "ok": True,
        "text": last_text,
        "tools_executed": tools_executed,
        "tool_count": len(tools_executed),
        "agent_steps": steps_used,
    }


async def run_nvidia_agent(
    svc: Any,
    *,
    message: str,
    context: str,
    mode: str = "code",
    max_steps: int = 6,
    scope_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Tool loop for NVIDIA-backed instructors (Nemotron, NemoClaw).

    Finalize stays on the same NVIDIA model — do NOT hand off to local
    qwen2.5-coder:32b (cold/slow 32B was wiping 14-tool runs with compute errors).
    """
    loop = asyncio.get_event_loop()

    async def generate(prompt: str) -> str:
        return await loop.run_in_executor(
            None,
            lambda: svc.generate_content(
                prompt,
                mode=mode,
                context=None,
                model=None if getattr(svc, "uses_nvidia", False) else AGENT_MODEL,
            ),
        )

    async def nvidia_finalize(prompt: str) -> str:
        # Prefer the NVIDIA line that just ran the tools
        try:
            text = await generate(prompt)
            if text and not _is_compute_error(text):
                return text
        except Exception as exc:
            logger.warning("[being_agent] NVIDIA finalize failed: %s", exc)
        # Fast local GENERAL only as backup
        return await _review_finalize_generate(prompt)

    return await run_being_agent(
        generate,
        message=message,
        context=context,
        max_steps=max_steps,
        scope_root=scope_root,
        finalize_generate=nvidia_finalize,
        review_instructor="nemotron" if scope_root else None,
    )


async def run_nemo_agent(
    nemo_svc: Any,
    *,
    message: str,
    context: str,
    mode: str = "code",
    max_steps: int = 6,
    scope_root: Optional[str] = None,
) -> Dict[str, Any]:
    return await run_nvidia_agent(
        nemo_svc,
        message=message,
        context=context,
        mode=mode,
        max_steps=max_steps,
        scope_root=scope_root,
    )


async def run_nemoclaw_agent(
    nemoclaw_svc: Any,
    *,
    message: str,
    context: str,
    max_steps: int = 6,
    scope_root: Optional[str] = None,
) -> Dict[str, Any]:
    """NemoClaw tool loop — finalize on NemoClaw/Nemotron, never cold 32B Ollama."""
    loop = asyncio.get_event_loop()

    async def generate(prompt: str) -> str:
        return await loop.run_in_executor(
            None,
            lambda: nemoclaw_svc.generate_content(prompt, context=None),
        )

    async def nemoclaw_finalize(prompt: str) -> str:
        try:
            text = await generate(prompt)
            if text and not _is_compute_error(text):
                return text
        except Exception as exc:
            logger.warning("[being_agent] NemoClaw finalize failed: %s", exc)
        return await _review_finalize_generate(prompt)

    return await run_being_agent(
        generate,
        message=message,
        context=context,
        max_steps=max_steps,
        scope_root=scope_root,
        finalize_generate=nemoclaw_finalize,
        review_instructor="nemotron" if scope_root else None,
    )


async def run_kimi_agent(
    kimi_svc: Any,
    *,
    message: str,
    context: str,
    mode: str = "codelab",
    domain: Optional[str] = None,
    max_steps: int = 6,
    scope_root: Optional[str] = None,
    variant: str = "k2.6",
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """Kimi — NVIDIA K2.6 / K2.7 explores via <tool_call> and writes the verdict."""
    loop = asyncio.get_event_loop()
    review_key = "kimi27" if str(variant).lower() in ("k2.7", "k27", "kimi27") else "kimi"

    async def generate(prompt: str) -> str:
        trimmed = _trim_conversation(prompt, max_chars=8000)

        def _call() -> str:
            result = kimi_svc.interact(
                message=trimmed,
                mode=mode,
                context=None,
                domain=domain,
                thinking=False,
                variant=variant,
                model=model,
            )
            return result.get("text", "")

        return await loop.run_in_executor(None, _call)

    async def kimi_finalize(prompt: str) -> str:
        trimmed = _trim_conversation(prompt, max_chars=12000)

        def _call() -> str:
            result = kimi_svc.interact(
                message=trimmed,
                mode=mode,
                context=None,
                domain=domain,
                thinking=False,
                variant=variant,
                model=model,
            )
            return result.get("text", "")

        try:
            return await asyncio.wait_for(
                loop.run_in_executor(None, _call),
                timeout=REVIEW_NEMOTRON_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error("[being_agent] Kimi finalize timed out variant=%s", variant)
            return ""

    return await run_being_agent(
        generate,
        message=message,
        context=context,
        max_steps=max_steps,
        scope_root=scope_root,
        finalize_generate=kimi_finalize,
        review_instructor=review_key if scope_root else None,
    )


async def run_being_agent(
    generate: Callable[[str], Awaitable[str]] = None,
    *,
    message: str,
    context: str = "",
    max_steps: int = None,
    scope_root: Optional[str] = None,
    finalize_generate: Optional[Callable[[str], Awaitable[str]]] = None,
    review_instructor: Optional[str] = None,
) -> Dict[str, Any]:
    """General compute agent for ANY Christman family being.
    All beings now have full capacity to run the compute via being_eyes tools.
    If no generate provided, uses built-in direct Ollama (CODER / BEING_AGENT_MODEL).
    """
    if generate is None:
        generate = _fast_direct_generate
    return await run_agent_loop(
        generate,
        message=message,
        context=context,
        max_steps=max_steps,
        scope_root=scope_root,
        finalize_generate=finalize_generate,
        review_instructor=review_instructor,
    )


