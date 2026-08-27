import os
from dotenv import load_dotenv

load_dotenv()

import subprocess
import pty
import select
import json
import logging
import asyncio
from pathlib import Path
import fastapi # pyright: ignore[reportMissingImports]
import fastapi.middleware.cors # pyright: ignore[reportMissingImports]
from fastapi.staticfiles import StaticFiles # pyright: ignore[reportMissingImports]
from fastapi.responses import HTMLResponse, FileResponse, Response # pyright: ignore[reportMissingImports]
from pydantic import BaseModel # pyright: ignore[reportMissingImports]

try:
    from backend.ai_client import get_ai_response
except ImportError:
    get_ai_response = None

try:
    from backend.speech_service import SpeechService
except ImportError:
    SpeechService = None

# Logger must exist regardless of whether SpeechService imported.
# (Previously this was nested inside the except block above, so when
# SpeechService imported cleanly `logger` was never defined and every
# endpoint that called logger.info crashed with NameError.)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BrockstonStudio")

app = fastapi.FastAPI()

origins = ["*"]

app.add_middleware(
    fastapi.middleware.cors.CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Claude as additional instructor
# MUST be after app = FastAPI() and logger setup
try:
    from backend.claude_router import router as claude_router
    app.include_router(claude_router)
    logger.info("Claude router mounted — additional instructor available at /api/claude")
except Exception as e:
    logger.warning(f"Claude router not available: {e}")

# Being Eyes — screen capture, file read/write, command execution for all beings
try:
    from backend.being_eyes import router as being_eyes_router
    app.include_router(being_eyes_router)
    logger.info("Being Eyes mounted — beings can see and fix at /api/eyes/*")
except Exception as e:
    logger.warning(f"Being Eyes not available: {e}")

# Nemotron — NVIDIA Nemotron 3 Ultra instructor
try:
    from backend.nemo_service import get_nemo_service
    _nemo_svc = get_nemo_service()
    logger.info("Nemotron linked — available at /api/nemotron")
except Exception as e:
    _nemo_svc = None
    logger.warning(f"Nemotron service not available: {e}")

# NemoClaw — agent instructor (Nemotron + tool loop)
try:
    from backend.nemoclaw_service import get_nemoclaw_service
    _nemoclaw_svc = get_nemoclaw_service()
    logger.info("NemoClaw linked — available at /api/nemoclaw")
except Exception as e:
    _nemoclaw_svc = None
    logger.warning(f"NemoClaw service not available: {e}")

# Mistral-Nemotron — NVIDIA reasoning instructor
try:
    from backend.mistral_service import get_mistral_service
    _mistral_svc = get_mistral_service()
    logger.info("Mistral-Nemotron linked — available at /api/mistral")
except Exception as e:
    _mistral_svc = None
    logger.warning(f"Mistral-Nemotron service not available: {e}")

# Kimi K2.6 + K2.7 — NVIDIA NIM learning tutor swarm (partner deck + code + kids)
try:
    from backend.kimi_service import get_kimi_service
    _kimi_svc = get_kimi_service()
    if not _kimi_svc.is_available:
        logger.warning("Kimi linked but not available (NVIDIA_KIMI_API_KEY or proxy)")
    else:
        logger.info("Kimi NVIDIA NIM swarm linked — /api/kimi (K2.6 + K2.7)")
except Exception as e:
    _kimi_svc = None
    logger.warning(f"Kimi service not available: {e}")

# Super Heavy Grok — Big Daddy xAI flagship
try:
    from backend.grok_service import get_grok_service
    _grok_svc = get_grok_service()
    if not _grok_svc.is_available:
        logger.warning("Super Heavy Grok offline — set XAI_API_KEY or GROK_API_KEY")
    else:
        logger.info("Super Heavy Grok linked — available at /api/grok")
except Exception as e:
    _grok_svc = None
    logger.warning(f"Grok service not available: {e}")

class ChatRequest(BaseModel):
    message: str
    context: str | None = None

class NemotronRequest(BaseModel):
    message: str
    mode: str = "partner"
    context: str | None = None

class NemoClawRequest(BaseModel):
    message: str
    context: str | None = None

class MistralRequest(BaseModel):
    message: str
    context: str | None = None

class KimiRequest(BaseModel):
    message: str
    mode: str = "tutor"
    context: str | None = None
    domain: str | None = None
    variant: str = "k2.6"  # k2.6 | k2.7
    model: str | None = None

class GrokRequest(BaseModel):
    message: str
    context: str | None = None

class ProjectReviewRequest(BaseModel):
    path: str | None = None
    message: str | None = None
    instructor: str = "family"  # + fable5 | grok | kimi26 | kimi27 | auto

@app.get("/api/health")
async def health_check():
    from backend.being_agent import AGENT_MODEL
    from backend.nemo_service import NVIDIA_NEMO_MODEL
    from backend.mistral_service import NVIDIA_MISTRAL_MODEL
    from backend.kimi_service import NVIDIA_KIMI_K26_MODEL, NVIDIA_KIMI_K27_MODEL
    from backend.grok_service import GROK_MODEL as XAI_GROK_MODEL

    fable5_model = os.getenv("FABLE5_MODEL", os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"))
    anthropic_key = bool(os.getenv("ANTHROPIC_API_KEY", "").strip())

    nemo_wiring = (
        _nemo_svc.wiring_info("partner") if _nemo_svc else {"backend": "offline", "label": "unavailable"}
    )
    nemo_code_wiring = (
        _nemo_svc.wiring_info("code") if _nemo_svc else nemo_wiring
    )
    nemoclaw_wiring = (
        _nemoclaw_svc.wiring_info() if _nemoclaw_svc else {"backend": "offline", "label": "unavailable"}
    )
    mistral_wiring = (
        _mistral_svc.wiring_info() if _mistral_svc else {"backend": "offline", "label": "unavailable"}
    )
    kimi26_wiring = (
        _kimi_svc.wiring_info("k2.6") if _kimi_svc else {"backend": "offline", "label": "unavailable"}
    )
    kimi27_wiring = (
        _kimi_svc.wiring_info("k2.7") if _kimi_svc else {"backend": "offline", "label": "unavailable"}
    )
    grok_wiring = (
        _grok_svc.wiring_info() if _grok_svc else {"backend": "offline", "label": "unavailable"}
    )
    kimi_key_set = bool(_kimi_svc and _kimi_svc.api_key_configured)

    # Stronger NVIDIA labels for health / Settings
    if kimi26_wiring.get("backend") == "nvidia":
        kimi26_wiring = {
            **kimi26_wiring,
            "label": f"{kimi26_wiring.get('model', NVIDIA_KIMI_K26_MODEL)} (NVIDIA NIM · Kimi)",
        }
    if kimi27_wiring.get("backend") == "nvidia":
        kimi27_wiring = {
            **kimi27_wiring,
            "label": f"{kimi27_wiring.get('model', NVIDIA_KIMI_K27_MODEL)} (NVIDIA NIM · Kimi)",
        }

    return {
        "status": "10 Toes Down",
        "system": "Online",
        "workspace": str(WORKSPACE_ROOT),
        "ollama": OLLAMA_BASE_URL,
        "models": {
            "general": LLM_MODEL_GENERAL,
            "coder": LLM_MODEL_CODER,
            "being_agent": AGENT_MODEL,
            "ultimateev": LLM_MODEL_CODER,
            "nemotron": nemo_wiring.get("label", NVIDIA_NEMO_MODEL),
            "mistral": mistral_wiring.get("label", NVIDIA_MISTRAL_MODEL),
            "kimi26": kimi26_wiring.get("label", NVIDIA_KIMI_K26_MODEL),
            "kimi27": kimi27_wiring.get("label", NVIDIA_KIMI_K27_MODEL),
            "fable5": f"{fable5_model} (Fable-5 · Anthropic)",
            "grok": grok_wiring.get("label", XAI_GROK_MODEL),
        },
        "instructors": {
            "family": {
                "name": "The Family",
                "backend": "ollama",
                "model": LLM_MODEL_GENERAL,
                "label": f"{LLM_MODEL_GENERAL} (local Ollama)",
                "api_key_env": "OLLAMA (local)",
                "api_key_set": True,
            },
            "claude": {
                "name": "Claude",
                "backend": "anthropic",
                "model": os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
                "label": f"{os.getenv('ANTHROPIC_MODEL', 'claude-sonnet-4-6')} (Anthropic)",
                "api_key_env": "ANTHROPIC_API_KEY",
                "api_key_set": anthropic_key,
            },
            "fable5": {
                "name": "Fable-5",
                "backend": "anthropic" if anthropic_key else "offline",
                "model": fable5_model,
                "label": f"{fable5_model} (Fable-5 · Anthropic)",
                "api_key_env": "ANTHROPIC_API_KEY",
                "api_key_set": anthropic_key,
            },
            "nemoclaw": {
                "name": "NemoClaw",
                "backend": nemoclaw_wiring.get("backend", "offline"),
                "model": nemo_code_wiring.get("model", NVIDIA_NEMO_MODEL),
                "label": nemoclaw_wiring.get("label", "unavailable"),
                "api_key_env": "NVIDIA_NEMO_API_KEY",
                "api_key_set": bool(_nemo_svc and _nemo_svc.api_key_configured),
            },
            "nemotron": {
                "name": "Nemotron",
                "backend": nemo_wiring.get("backend", "offline"),
                "model": nemo_wiring.get("model", NVIDIA_NEMO_MODEL),
                "label": nemo_wiring.get("label", "unavailable"),
                "api_key_env": "NVIDIA_NEMO_API_KEY",
                "api_key_set": bool(_nemo_svc and _nemo_svc.api_key_configured),
            },
            "mistral": {
                "name": "Mistral-Nemotron",
                "backend": mistral_wiring.get("backend", "offline"),
                "model": mistral_wiring.get("model", NVIDIA_MISTRAL_MODEL),
                "label": mistral_wiring.get("label", "unavailable"),
                "api_key_env": "NVIDIA_MISTRAL_API_KEY",
                "api_key_set": bool(_mistral_svc and _mistral_svc.uses_nvidia),
            },
            "kimi26": {
                "name": "Kimi · NVIDIA K2.6",
                "backend": kimi26_wiring.get("backend", "offline"),
                "model": kimi26_wiring.get("model", NVIDIA_KIMI_K26_MODEL),
                "label": kimi26_wiring.get("label", "unavailable"),
                "api_key_env": "NVIDIA_KIMI_API_KEY",
                "api_key_set": kimi_key_set,
            },
            "kimi27": {
                "name": "Kimi · NVIDIA K2.7",
                "backend": kimi27_wiring.get("backend", "offline"),
                "model": kimi27_wiring.get("model", NVIDIA_KIMI_K27_MODEL),
                "label": kimi27_wiring.get("label", "unavailable"),
                "api_key_env": "NVIDIA_KIMI_API_KEY",
                "api_key_set": kimi_key_set,
            },
            "kimi": {
                "name": "Kimi · NVIDIA K2.6",
                "backend": kimi26_wiring.get("backend", "offline"),
                "model": kimi26_wiring.get("model", NVIDIA_KIMI_K26_MODEL),
                "label": kimi26_wiring.get("label", "unavailable"),
                "api_key_env": "NVIDIA_KIMI_API_KEY",
                "api_key_set": kimi_key_set,
            },
            "grok": {
                "name": "Super Heavy Grok",
                "backend": grok_wiring.get("backend", "offline"),
                "model": grok_wiring.get("model", XAI_GROK_MODEL),
                "label": grok_wiring.get("label", "unavailable"),
                "api_key_env": "XAI_API_KEY",
                "api_key_set": bool(_grok_svc and _grok_svc.api_key_configured),
            },
            "auto": {
                "name": "Auto",
                "backend": "router",
                "model": "auto-switcher",
                "label": "Auto — Grok / Kimi / Nemotron / Fable-5 / Family by task",
                "api_key_env": "—",
                "api_key_set": True,
            },
        },
        "beings": {
            "family_chat": LLM_MODEL_GENERAL,
            "nemotron_partner": nemo_wiring.get("label", LLM_MODEL_GENERAL),
            "nemotron_code": nemo_code_wiring.get("label", LLM_MODEL_CODER),
            "nemoclaw": nemoclaw_wiring.get("label", "unavailable"),
            "mistral_chat": mistral_wiring.get("label", "unavailable"),
            "kimi26": kimi26_wiring.get("label", "unavailable"),
            "kimi27": kimi27_wiring.get("label", "unavailable"),
            "fable5": f"{fable5_model} (Fable-5)",
            "grok": grok_wiring.get("label", "unavailable"),
            "being_agent_tools": AGENT_MODEL,
        },
        "features": {
            "review_project": True,
            "auto_switcher": True,
            "kimi_swarm": True,
            "fable5": True,
            "super_heavy_grok": True,
        },
    }


@app.get("/api/sound/status")
async def sound_status():
    """christman_sound wiring status — local repo paths, per-being WAV folders."""
    try:
        from backend.christman_sound_config import sound_stack_status
        return sound_stack_status()
    except Exception as e:
        logger.error(f"Sound status error: {e}")
        raise fastapi.HTTPException(status_code=500, detail=str(e))

async def _resolve_review_path(raw: str | None) -> str:
    """Resolve project path for review — explorer path or workspace default."""
    if raw and raw.strip():
        return str(_resolve_user_path(raw.strip(), WORKSPACE_ROOT))
    return str(WORKSPACE_ROOT)


async def _run_project_review(
    *,
    project_path: str,
    user_message: str,
    instructor: str = "family",
) -> dict:
    from backend.being_agent import (
        PROJECT_REVIEW_TASK,
        review_agent_max_steps,
        run_being_agent,
        strip_tool_blocks,
        _is_tool_leak,
        _fallback_summary_from_tools,
    )
    from backend.being_context import build_being_context

    task = (
        f"{PROJECT_REVIEW_TASK}\n\n[PROJECT ROOT: {project_path}]\n\n"
        f"{user_message or 'Review this entire project.'}"
    )
    instructor = (instructor or "family").lower()
    if instructor == "auto":
        if _kimi_svc and _kimi_svc.is_available:
            instructor = "kimi27"
        elif _nemoclaw_svc:
            instructor = "nemoclaw"
        else:
            instructor = "family"
    if instructor == "kimi":
        instructor = "kimi26"
    if instructor not in (
        "family", "claude", "fable5", "nemotron", "nemoclaw", "mistral",
        "kimi", "kimi26", "kimi27", "grok",
    ):
        instructor = "family"

    prefix = "PROJECT REVIEW"
    for_kimi = instructor in ("kimi", "kimi26", "kimi27")

    full_context = await build_being_context(
        message=task,
        project_path=project_path,
        compact=True,
        for_kimi=for_kimi,
        for_review=True,
        read_open_file=False,
    )
    max_steps = review_agent_max_steps()

    logger.info(
        "Project review agent: %s (instructor=%s, max_steps=%d)",
        project_path,
        instructor,
        max_steps,
    )

    if instructor in ("kimi26", "kimi27", "kimi") and _kimi_svc:
        from backend.being_agent import run_kimi_agent
        variant = "k2.7" if instructor == "kimi27" else "k2.6"
        result = await run_kimi_agent(
            _kimi_svc,
            message=task,
            context=full_context,
            mode="codelab",
            max_steps=max_steps,
            scope_root=project_path,
            variant=variant,
        )
    elif instructor == "nemoclaw" and _nemoclaw_svc:
        from backend.being_agent import run_nemoclaw_agent
        result = await run_nemoclaw_agent(
            _nemoclaw_svc,
            message=task,
            context=full_context,
            max_steps=max_steps,
            scope_root=project_path,
        )
    elif instructor == "nemotron" and _nemo_svc:
        from backend.being_agent import run_nemo_agent
        result = await run_nemo_agent(
            _nemo_svc,
            message=task,
            context=full_context,
            mode="code",
            max_steps=max_steps,
            scope_root=project_path,
        )
    elif instructor == "mistral" and _mistral_svc:
        # Tool-loop review like other NVIDIA instructors (not a raw one-shot).
        # generate_content already falls back to Ollama on NVIDIA 404/timeout.
        from backend.being_agent import run_nvidia_agent
        try:
            result = await run_nvidia_agent(
                _mistral_svc,
                message=task,
                context=full_context,
                mode="code",
                max_steps=max_steps,
                scope_root=project_path,
            )
        except Exception as exc:
            logger.warning(
                "Mistral-Nemotron review agent failed (%s) — one-shot fallback",
                exc,
            )
            loop = asyncio.get_event_loop()
            reply = await loop.run_in_executor(
                None,
                lambda: _mistral_svc.generate_content(task, context=full_context),
            )
            result = {"text": reply, "tool_count": 0, "tools_executed": []}
    elif instructor == "grok" and _grok_svc and _grok_svc.is_available:
        from backend.being_agent import run_being_agent as _run_ba
        loop = asyncio.get_event_loop()

        async def _grok_gen(prompt: str) -> str:
            return await loop.run_in_executor(
                None,
                lambda: _grok_svc.generate_content(prompt, context=None),
            )

        result = await _run_ba(
            _grok_gen,
            message=task,
            context=full_context,
            max_steps=max_steps,
            scope_root=project_path,
            review_instructor="grok",
        )
    else:
        result = await run_being_agent(
            message=task,
            context=full_context,
            max_steps=max_steps,
            scope_root=project_path,
        )

    tool_count = result.get("tool_count", 0)
    text = strip_tool_blocks(result.get("text", ""))
    if _is_tool_leak(text) and result.get("tools_executed"):
        text = _fallback_summary_from_tools(
            result["tools_executed"],
            user_message=user_message or task,
        )
    return {
        "response": f"[{prefix} — {tool_count} tool(s) on {project_path}]: {text}",
        "project_path": project_path,
        "tool_count": tool_count,
        "tools_executed": result.get("tools_executed", []),
        "agent": True,
        "review": True,
    }


@app.post("/api/review/project")
async def review_project_endpoint(request: ProjectReviewRequest):
    """Scan and review the whole project at path (explorer folder or workspace root)."""
    project_path = await _resolve_review_path(request.path)
    logger.info("Project review: %s (instructor=%s)", project_path, request.instructor)
    try:
        return await _run_project_review(
            project_path=project_path,
            user_message=request.message or "",
            instructor=request.instructor,
        )
    except fastapi.HTTPException:
        raise
    except Exception as e:
        logger.error("Project review error: %s", e)
        raise fastapi.HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    """Christman Family — Brockston (and whole family) via local pipeline.
    Now with full compute capacity: all beings can ls/read/write/patch/run via tools.
    """
    logger.info(f"Chat request: {request.message[:120]}")
    if not get_ai_response:
        raise fastapi.HTTPException(status_code=503, detail="AI client not available")
    try:
        from backend.being_agent import run_being_agent, wants_project_review, review_agent_max_steps
        from backend.being_context import build_being_context, extract_project_root_path

        is_review = wants_project_review(request.message)
        project_path = extract_project_root_path(request.message)

        # Build rich context so beings see the full workspace + abilities for compute
        full_context = await build_being_context(
            message=request.message,
            extra_context=request.context,
            project_path=project_path,
            compact=not is_review,
            ollama_route=not is_review,
            for_review=is_review,
            read_open_file=not is_review,
        )

        # Special reduced-lag demo path so beings can quickly demonstrate abilities
        demo_trigger = any(w in (request.message or "").lower() for w in ("demonstrate", "demo abilities", "show your abilities", "run compute demo"))
        if demo_trigger:
            from backend.being_agent import run_being_agent as _demo_run
            demo_task = "Demonstrate your compute abilities: ls a dir, read a small file, run 'echo DEMO SUCCESS', write+run a tiny temp python script that prints a success message, then summarize the tools used."
            result = await _demo_run(message=demo_task, context=full_context)
            return {"response": f"[DEMO — {result.get('tool_count',0)} tools]: {result.get('text','')}", "agent": True, "demo": True}

        # Normal fast path for chat (reduced lag). 
        # Only use the full agent tool loop (compute) when the query needs it (code, fix, demo, ls/run etc).
        from backend.being_agent import wants_agent_tools
        if wants_agent_tools(request.message, "code") or any(k in (request.message or "").lower() for k in ("tool", "run command", "execute", "patch", "write file", "demonstrate")):
            result = await run_being_agent(
                message=request.message,
                context=full_context,
                max_steps=review_agent_max_steps() if is_review else None,
                scope_root=project_path if is_review else None,
            )
            text = result.get("text", "")
            tool_count = result.get("tool_count", 0)
            prefix = f"[FAMILY/BROCKSTON — {tool_count} compute tool(s) executed]: " if tool_count else "[FAMILY]: "
            return {
                "response": f"{prefix}{text}",
                "source": "family",
                "tools_executed": result.get("tools_executed", []),
                "tool_count": tool_count,
                "agent": True,
            }

        # Fast direct low-lag chat path for normal questions (no agent overhead)
        import httpx
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                r = await client.post(
                    f"{OLLAMA_BASE_URL}/api/chat",
                    json={
                        "model": LLM_MODEL_GENERAL,
                        "messages": [
                            {"role": "system", "content": full_context[:1500] if full_context else "You are BROCKSTON, helpful and direct."},
                            {"role": "user", "content": request.message}
                        ],
                        "stream": False,
                        "options": {"num_predict": 256, "num_ctx": 4096, "temperature": 0.7}
                    }
                )
                r.raise_for_status()
                reply = r.json().get("message", {}).get("content", "No response")
                return {"response": f"[FAMILY]: {reply}", "source": "family", "agent": False}
        except Exception as e:
            logger.warning(f"Fast chat failed, falling back: {e}")
            # ultimate fallback
            loop = asyncio.get_event_loop()
            response_text = await loop.run_in_executor(None, get_ai_response, request.message)
            return {"response": response_text}
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise fastapi.HTTPException(status_code=500, detail=str(e))


@app.post("/api/nemotron")
async def nemotron_endpoint(request: NemotronRequest):
    """Nemotron 3 Ultra — sovereign partner / code mentor."""
    logger.info("Nemotron request: %s", request.message[:120])
    if not _nemo_svc:
        raise fastapi.HTTPException(status_code=503, detail="Nemotron service not available")
    try:
        mode = request.mode if request.mode in ("partner", "code") else "partner"
        from backend.being_agent import (
            run_nemo_agent,
            wants_agent_tools,
            wants_project_review,
            review_agent_max_steps,
            strip_tool_blocks,
            _is_tool_leak,
            _fallback_summary_from_tools,
        )
        from backend.being_context import build_being_context, extract_project_root_path

        is_review = wants_project_review(request.message)
        project_path = extract_project_root_path(request.message)
        if is_review:
            mode = "code"

        full_context = await build_being_context(
            message=request.message,
            extra_context=request.context,
            project_path=project_path,
            compact=not is_review,
            ollama_route=not is_review,
            for_review=is_review,
            read_open_file=not is_review,
        )

        if wants_agent_tools(request.message, mode):
            result = await run_nemo_agent(
                _nemo_svc,
                message=request.message,
                context=full_context,
                mode=mode,
                max_steps=review_agent_max_steps() if is_review else 6,
                scope_root=project_path if is_review else None,
            )
            text = strip_tool_blocks(result.get("text", ""))
            if _is_tool_leak(text) and result.get("tools_executed"):
                text = _fallback_summary_from_tools(
                    result["tools_executed"],
                    user_message=request.message,
                )
            tool_count = result.get("tool_count", 0)
            prefix = f"[NEMOTRON — {tool_count} tool(s) executed]: " if tool_count else "[NEMOTRON]: "
            wiring = _nemo_svc.wiring_info(mode)
            return {
                "response": f"{prefix}{text}",
                "source": "nemotron",
                "mode": mode,
                "model": wiring.get("model"),
                "wiring": wiring,
                "tools_executed": result.get("tools_executed", []),
                "tool_count": tool_count,
                "agent": True,
            }

        loop = asyncio.get_event_loop()
        reply = await loop.run_in_executor(
            None,
            lambda: _nemo_svc.generate_content(
                request.message, mode=mode, context=full_context
            ),
        )
        wiring = _nemo_svc.wiring_info(mode)
        return {
            "response": f"[NEMOTRON]: {reply}",
            "source": "nemotron",
            "mode": mode,
            "model": wiring.get("model"),
            "wiring": wiring,
            "agent": False,
        }
    except Exception as e:
        logger.error("Nemotron error: %s", e)
        raise fastapi.HTTPException(status_code=500, detail=str(e))


@app.post("/api/nemoclaw")
async def nemoclaw_endpoint(request: NemoClawRequest):
    """NemoClaw — NVIDIA agent instructor with full tool loop."""
    logger.info("NemoClaw request: %s", request.message[:120])
    if not _nemoclaw_svc:
        raise fastapi.HTTPException(status_code=503, detail="NemoClaw service not available")
    try:
        from backend.being_agent import (
            run_nemoclaw_agent,
            wants_project_review,
            review_agent_max_steps,
            strip_tool_blocks,
            _is_tool_leak,
            _fallback_summary_from_tools,
        )
        from backend.being_context import build_being_context, extract_project_root_path

        is_review = wants_project_review(request.message)
        project_path = extract_project_root_path(request.message)

        full_context = await build_being_context(
            message=request.message,
            extra_context=request.context,
            project_path=project_path,
            compact=not is_review,
            for_review=is_review,
            read_open_file=not is_review,
        )

        result = await run_nemoclaw_agent(
            _nemoclaw_svc,
            message=request.message,
            context=full_context,
            max_steps=review_agent_max_steps() if is_review else 6,
            scope_root=project_path if is_review else None,
        )
        text = strip_tool_blocks(result.get("text", ""))
        if _is_tool_leak(text) and result.get("tools_executed"):
            text = _fallback_summary_from_tools(
                result["tools_executed"],
                user_message=request.message,
            )
        tool_count = result.get("tool_count", 0)
        prefix = f"[NEMOCLAW — {tool_count} tool(s) executed]: " if tool_count else "[NEMOCLAW]: "
        wiring = _nemoclaw_svc.wiring_info()
        return {
            "response": f"{prefix}{text}",
            "source": "nemoclaw",
            "model": wiring.get("model"),
            "wiring": wiring,
            "tools_executed": result.get("tools_executed", []),
            "tool_count": tool_count,
            "agent": True,
        }
    except Exception as e:
        logger.error("NemoClaw error: %s", e)
        raise fastapi.HTTPException(status_code=500, detail=str(e))


@app.post("/api/mistral")
async def mistral_endpoint(request: MistralRequest):
    """Mistral-Nemotron — deep reasoning instructor (NVIDIA NIM)."""
    logger.info("Mistral-Nemotron request: %s", request.message[:120])
    if not _mistral_svc:
        raise fastapi.HTTPException(status_code=503, detail="Mistral-Nemotron service not available")
    try:
        from backend.being_context import build_being_context, extract_project_root_path

        project_path = extract_project_root_path(request.message)
        full_context = await build_being_context(
            message=request.message,
            extra_context=request.context,
            project_path=project_path,
            compact=True,
            read_open_file=True,
        )

        loop = asyncio.get_event_loop()
        reply = await loop.run_in_executor(
            None,
            lambda: _mistral_svc.generate_content(request.message, context=full_context),
        )
        wiring = _mistral_svc.wiring_info()
        return {
            "response": f"[MISTRAL]: {reply}",
            "source": "mistral",
            "model": wiring.get("model"),
            "wiring": wiring,
            "agent": False,
        }
    except Exception as e:
        logger.error("Mistral error: %s", e)
        raise fastapi.HTTPException(status_code=500, detail=str(e))


@app.post("/api/kimi")
async def kimi_endpoint(request: KimiRequest):
    """Kimi K2.6 / K2.7 — NVIDIA swarm instructor for learning, code, partner decks."""
    if not _kimi_svc or not _kimi_svc.is_available:
        raise fastapi.HTTPException(
            status_code=503,
            detail="Kimi not available — set NVIDIA_KIMI_API_KEY in .env",
        )
    try:
        from backend.being_agent import (
            run_kimi_agent,
            wants_agent_tools,
            wants_project_review,
            review_agent_max_steps,
            strip_tool_blocks,
            _is_tool_leak,
            _fallback_summary_from_tools,
        )
        from backend.being_context import build_being_context, extract_project_root_path
        from backend.kimi_service import KimiRateLimitError, resolve_kimi_model

        variant_raw = (request.variant or "k2.6").lower().strip()
        if variant_raw in ("k2.7", "k27", "kimi27"):
            variant = "k2.7"
            tag = "KIMI K2.7"
        else:
            variant = "k2.6"
            tag = "KIMI K2.6"

        mode = request.mode if request.mode in (
            "tutor", "codelab", "learning", "coach", "partner"
        ) else "tutor"

        is_review = wants_project_review(request.message)
        project_path = extract_project_root_path(request.message)

        full_context = await build_being_context(
            message=request.message,
            extra_context=request.context,
            project_path=project_path,
            compact=not is_review,
            for_kimi=True,
            for_review=is_review,
            read_open_file=not is_review,
        )

        agent_mode = mode
        if is_review:
            agent_mode = "codelab"
        model_id = resolve_kimi_model(variant, request.model)
        loop = asyncio.get_event_loop()

        if wants_agent_tools(request.message, agent_mode):
            result = await run_kimi_agent(
                _kimi_svc,
                message=request.message,
                context=full_context,
                mode=agent_mode,
                max_steps=review_agent_max_steps() if is_review else 6,
                domain=request.domain,
                scope_root=project_path if is_review else None,
                variant=variant,
                model=request.model,
            )
            text = strip_tool_blocks(result.get("text", ""))
            if _is_tool_leak(text) and result.get("tools_executed"):
                text = _fallback_summary_from_tools(
                    result["tools_executed"],
                    user_message=request.message,
                )
            tool_count = result.get("tool_count", 0)
            prefix = (
                f"[{tag} — {tool_count} tool(s) executed on disk]: "
                if tool_count
                else f"[{tag}]: "
            )
            wiring = _kimi_svc.wiring_info(variant)
            return {
                "response": f"{prefix}{text}",
                "ok": True,
                "source": "kimi",
                "variant": variant,
                "model": model_id,
                "wiring": wiring,
                "tools_executed": result.get("tools_executed", []),
                "tool_count": tool_count,
                "agent": True,
                "agent_steps": result.get("agent_steps", 0),
            }

        result = await loop.run_in_executor(
            None,
            lambda: _kimi_svc.interact(
                message=request.message,
                mode=agent_mode,
                context=full_context,
                domain=request.domain,
                thinking=False,
                variant=variant,
                model=request.model,
            ),
        )
        text = result.get("text", "")
        wiring = _kimi_svc.wiring_info(variant)
        return {
            "response": f"[{tag}]: {text}",
            "ok": True,
            "source": "kimi",
            "variant": variant,
            "model": result.get("model") or model_id,
            "wiring": wiring,
            "agent": False,
        }
    except Exception as e:
        from backend.kimi_service import KimiRateLimitError
        if isinstance(e, KimiRateLimitError):
            logger.warning("Kimi rate limit: %s", e)
            raise fastapi.HTTPException(status_code=429, detail=str(e))
        logger.error("Kimi error: %s", e)
        err = str(e)
        if "429" in err:
            raise fastapi.HTTPException(
                status_code=429,
                detail="NVIDIA rate limit — wait 30–60s. Code Lab agent mode uses multiple calls; use Tutor for chat.",
            )
        if "timed out" in err.lower() or "timeout" in err.lower():
            raise fastapi.HTTPException(
                status_code=504,
                detail="Kimi timed out — NVIDIA NIM was slow. Retry in 30s or switch instructor.",
            )
        if "500" in err or "server error" in err.lower():
            raise fastapi.HTTPException(
                status_code=502,
                detail="NVIDIA Kimi returned 500. Retry in 30s, smaller scope, or switch to NemoClaw/Mistral.",
            )
        raise fastapi.HTTPException(status_code=500, detail=err)


@app.post("/api/grok")
async def grok_endpoint(request: GrokRequest):
    """Super Heavy Grok — Big Daddy xAI flagship instructor."""
    logger.info("Super Heavy Grok request: %s", request.message[:120])
    if not _grok_svc or not _grok_svc.is_available:
        raise fastapi.HTTPException(
            status_code=503,
            detail="Super Heavy Grok offline — set XAI_API_KEY or GROK_API_KEY in .env",
        )
    try:
        from backend.being_agent import (
            run_being_agent,
            wants_agent_tools,
            wants_project_review,
            review_agent_max_steps,
            strip_tool_blocks,
            _is_tool_leak,
            _fallback_summary_from_tools,
        )
        from backend.being_context import (
            build_being_context,
            extract_project_root_path,
            GROK_IDENTITY,
        )

        is_review = wants_project_review(request.message)
        project_path = extract_project_root_path(request.message)
        full_context = await build_being_context(
            message=request.message,
            extra_context=request.context,
            project_path=project_path,
            compact=not is_review,
            for_review=is_review,
            read_open_file=not is_review,
        )
        full_context = f"{GROK_IDENTITY}\n\n{full_context}"

        loop = asyncio.get_event_loop()

        async def generate(prompt: str) -> str:
            return await loop.run_in_executor(
                None,
                lambda: _grok_svc.generate_content(prompt, context=None),
            )

        if wants_agent_tools(request.message, "code") or is_review:
            result = await run_being_agent(
                generate,
                message=request.message,
                context=full_context,
                max_steps=review_agent_max_steps() if is_review else 6,
                scope_root=project_path if is_review else None,
                review_instructor="grok" if is_review else None,
            )
            text = strip_tool_blocks(result.get("text", ""))
            if _is_tool_leak(text) and result.get("tools_executed"):
                text = _fallback_summary_from_tools(
                    result["tools_executed"],
                    user_message=request.message,
                )
            tool_count = result.get("tool_count", 0)
            prefix = (
                f"[SUPER HEAVY GROK — {tool_count} tool(s)]: "
                if tool_count
                else "[SUPER HEAVY GROK]: "
            )
            wiring = _grok_svc.wiring_info()
            return {
                "response": f"{prefix}{text}",
                "source": "grok",
                "model": wiring.get("model"),
                "wiring": wiring,
                "tools_executed": result.get("tools_executed", []),
                "tool_count": tool_count,
                "agent": True,
            }

        reply = await loop.run_in_executor(
            None,
            lambda: _grok_svc.generate_content(
                request.message, context=full_context
            ),
        )
        wiring = _grok_svc.wiring_info()
        return {
            "response": f"[SUPER HEAVY GROK]: {reply}",
            "source": "grok",
            "model": wiring.get("model"),
            "wiring": wiring,
            "agent": False,
        }
    except Exception as e:
        logger.error("Super Heavy Grok error: %s", e)
        raise fastapi.HTTPException(status_code=500, detail=str(e))


# ==========================================
# AUDIO ROUTE (This makes the kids' TTS work)
# ==========================================
@app.post("/api/speech/synthesize")
async def synthesize_speech_route(request: fastapi.Request):
    try:
        data = await request.json()
        text = data.get("text", "")
        # Prefer being pack id (brockston/kimi/nemo) over macOS voice name
        voice = data.get("being") or data.get("voice") or "default"

        speech_svc = SpeechService()
        audio_bytes = await speech_svc.synthesize_speech(text=text, voice_id=voice)
        engine = getattr(speech_svc, "last_engine", "unknown")
        detail = getattr(speech_svc, "last_engine_detail", "")
        if engine == "macos_say_fallback":
            logger.warning(
                "[TTS] Readback used ROBOT FALLBACK (not closed-loop). %s",
                detail,
            )
        # HTTP headers must be latin-1 — strip fancy punctuation
        def _hdr(s: str) -> str:
            return (s or "").replace("—", "-").replace("–", "-").encode("ascii", "replace").decode("ascii")[:200]

        return Response(
            content=audio_bytes,
            media_type="audio/mpeg",
            headers={
                "X-TTS-Engine": _hdr(engine),
                "X-TTS-Detail": _hdr(detail),
                "Access-Control-Expose-Headers": "X-TTS-Engine, X-TTS-Detail",
            },
        )
    except Exception as e:
        logger.error(f"Speech Synthesis Error: {e}")
        raise fastapi.HTTPException(status_code=500, detail=str(e))


# ==========================================
# AUDIO PLAYER ROUTE - For students to play their old school rock and Soul Train
# ==========================================
@app.get("/api/audio")
async def get_audio(filename: str):
    """Serve audio files (mp3, wav, etc.) from anywhere in the user's home for the music player.
    Lets senior students (and everyone) play their own old school rock and Soul Train tracks
    right inside the IDE while coding and talking to the beings.
    """
    try:
        target = _resolve_user_path(filename, WORKSPACE_ROOT)
        if not target.exists() or not target.is_file():
            raise fastapi.HTTPException(status_code=404, detail="Audio file not found")

        ext = target.suffix.lower()
        mime_types = {
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".ogg": "audio/ogg",
            ".m4a": "audio/mp4",
            ".flac": "audio/flac",
            ".aac": "audio/aac",
        }
        media_type = mime_types.get(ext, "audio/mpeg")

        with open(target, "rb") as f:
            content = f.read()

        logger.info(f"Playing audio: {target}")
        return Response(content=content, media_type=media_type)
    except fastapi.HTTPException:
        raise
    except Exception as e:
        logger.error(f"Audio Playback Error: {e}")
        raise fastapi.HTTPException(status_code=500, detail=str(e))

# ----------------------------------------------------------------------------
# File operations
#
# The IDE is allowed to read/list/write anywhere inside the user's HOME
# directory. "workspace" is the starting point, not a cage — when the user
# cd's into another project (AlphaVox, AlphaWolf, etc.), the explorer should
# follow them there. The HOME guard prevents path traversal into system files
# like /etc/passwd while keeping every real project reachable.
# ----------------------------------------------------------------------------
from backend.config import (
    STUDIO_WORKSPACE,
    LLM_MODEL_GENERAL,
    LLM_MODEL_CODER,
    OLLAMA_BASE_URL,
)

USER_HOME = Path(os.path.expanduser("~")).resolve()
WORKSPACE_ROOT = Path(STUDIO_WORKSPACE).resolve()

def _resolve_user_path(raw: str, default: Path) -> Path:
    """Resolve a path argument from the client.

    Rules:
      - Empty string -> `default` (usually workspace root)
      - Absolute path -> used as-is
      - Relative path -> resolved against the workspace root
      - Resolved path must live inside the user's HOME (security boundary)
      - '..' segments in the *input* are rejected as a defense-in-depth check
    """
    if not raw:
        return default
    # Reject literal traversal attempts in the raw input.
    parts = raw.replace("\\", "/").split("/")
    if any(p == ".." for p in parts):
        raise fastapi.HTTPException(status_code=400, detail="Path contains '..'")
    # Support ~ for home
    candidate = Path(os.path.expanduser(raw))
    if not candidate.is_absolute():
        candidate = WORKSPACE_ROOT / candidate
    resolved = candidate.resolve()
    # Stay inside the user's home tree.
    try:
        resolved.relative_to(USER_HOME)
    except ValueError:
        raise fastapi.HTTPException(
            status_code=400,
            detail=f"Path outside user home ({USER_HOME})",
        )
    return resolved

@app.get("/api/files")
async def list_files(path: str = ""):
    try:
        target = _resolve_user_path(path, WORKSPACE_ROOT)
        if not target.exists():
            raise fastapi.HTTPException(status_code=404, detail="Directory not found")
        if not target.is_dir():
            raise fastapi.HTTPException(status_code=400, detail="Not a directory")
        files = []
        for item in sorted(os.listdir(target)):
            if item.startswith(".") or item.startswith("__"):
                continue
            full_path = target / item
            try:
                if full_path.is_dir():
                    files.append({"name": item, "type": "folder"})
                elif full_path.is_file():
                    files.append({"name": item, "type": "file"})
            except (PermissionError, OSError):
                continue
        # Sort: folders first, then files, both alphabetically
        files.sort(key=lambda f: (f["type"] != "folder", f["name"].lower()))
        return {
            "files": files,
            "path": str(target),
            "is_workspace": str(target) == str(WORKSPACE_ROOT),
            "home": str(USER_HOME),
        }
    except fastapi.HTTPException:
        raise
    except Exception as e:
        logger.error(f"File Listing Error: {e}")
        return {"files": [], "path": path, "error": str(e)}

@app.get("/api/read_file")
async def read_file(filename: str):
    try:
        target = _resolve_user_path(filename, WORKSPACE_ROOT)
        if not target.exists() or not target.is_file():
            raise fastapi.HTTPException(status_code=404, detail="File not found")
        with open(target, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content, "filename": str(target)}
    except fastapi.HTTPException:
        raise
    except Exception as e:
        logger.error(f"Read Error: {e}")
        raise fastapi.HTTPException(status_code=404, detail=f"Cannot read file: {e}")

class WriteFileRequest(BaseModel):
    filename: str
    content: str

@app.post("/api/write_file")
async def write_file(request: WriteFileRequest):
    """Save editor content back to disk. Allowed anywhere inside $HOME."""
    try:
        target = _resolve_user_path(request.filename, WORKSPACE_ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(request.content)
        # Nudge FS so macOS Finder sees new/changed files promptly (no manual refresh needed)
        try:
            os.utime(target.parent, None)
        except Exception:
            pass
        logger.info(f"Saved {target} ({len(request.content)} bytes)")
        # Push refresh to any connected IDE clients / beings so explorer stays in sync
        await broadcast_ide_control("refresh_files", {})
        return {"ok": True, "filename": str(target), "bytes": len(request.content)}
    except fastapi.HTTPException:
        raise
    except Exception as e:
        logger.error(f"Write Error: {e}")
        raise fastapi.HTTPException(status_code=500, detail=str(e))

@app.websocket("/ws/terminal")
async def websocket_terminal(websocket: fastapi.WebSocket):
    """
    PTY-backed terminal. Spawns the user's shell with an OSC 7 hook so every
    prompt emits its working directory, which the frontend uses to sync the
    file explorer (real IDE behavior: cd in terminal -> explorer follows).
    """
    await websocket.accept()
    master_fd, slave_fd = pty.openpty()
    shell = os.environ.get("SHELL", "/bin/bash")
    workspace_root = str(WORKSPACE_ROOT)

    # Set initial terminal size from env or defaults (will be updated by frontend fit)
    try:
        import fcntl
        import termios
        import struct
        rows = int(os.environ.get("LINES", 24))
        cols = int(os.environ.get("COLUMNS", 80))
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
    except Exception:
        pass

    # Inject OSC 7 emission into the shell so every prompt reports its cwd.
    # Works for bash, zsh, fish-style POSIX shells via PROMPT_COMMAND / precmd.
    shell_name = os.path.basename(shell)
    env = os.environ.copy()
    env["STUDIO_WORKSPACE"] = workspace_root
    env.setdefault("TERM", "xterm-256color")  # better support for nano, vim, etc. TUIs

    # OSC 7 sequence: ESC ] 7 ; file://hostname/path ESC \
    # We install the hook via shell init files so the user never sees the
    # function definition appear at their prompt. This is how VSCode does it.
    import tempfile
    rc_dir = tempfile.mkdtemp(prefix="brockston_rc_")
    shell_args = [shell]

    if "zsh" in shell_name:
        # zsh: ZDOTDIR points to a dir containing .zshrc which sources the
        # user's real .zshrc first, then appends our hook.
        user_zshrc = os.path.expanduser("~/.zshrc")
        zshrc_lines = []
        if os.path.isfile(user_zshrc):
            zshrc_lines.append(f'source "{user_zshrc}"')
        zshrc_lines += [
            '_brockston_cwd_hook() {',
            '  printf "\\033]7;file://%s%s\\033\\\\" "${HOST:-localhost}" "$PWD"',
            '}',
            'typeset -ga precmd_functions',
            'precmd_functions=(${precmd_functions[@]:#_brockston_cwd_hook} _brockston_cwd_hook)',
        ]
        with open(os.path.join(rc_dir, ".zshrc"), "w") as f:
            f.write("\n".join(zshrc_lines) + "\n")
        env["ZDOTDIR"] = rc_dir
        # Don't source global zshenv changes that might override ZDOTDIR
    else:
        # bash: --rcfile points at our wrapper, which sources the user's real
        # bashrc then defines the hook.
        user_bashrc = os.path.expanduser("~/.bashrc")
        rc_path = os.path.join(rc_dir, "bashrc")
        bashrc_lines = []
        if os.path.isfile(user_bashrc):
            bashrc_lines.append(f'source "{user_bashrc}"')
        bashrc_lines += [
            '_brockston_cwd_hook() {',
            '  printf "\\033]7;file://%s%s\\033\\\\" "${HOSTNAME:-localhost}" "$PWD"',
            '}',
            'case ":${PROMPT_COMMAND:-}:" in',
            '  *:_brockston_cwd_hook:*) ;;',
            '  *) PROMPT_COMMAND="_brockston_cwd_hook${PROMPT_COMMAND:+;$PROMPT_COMMAND}" ;;',
            'esac',
        ]
        with open(rc_path, "w") as f:
            f.write("\n".join(bashrc_lines) + "\n")
        shell_args = [shell, "--rcfile", rc_path, "-i"]

    process = subprocess.Popen(
        shell_args,
        preexec_fn=os.setsid,
        stdin=slave_fd, stdout=slave_fd, stderr=slave_fd,
        universal_newlines=True,
        env=env,
        cwd=workspace_root,
    )
    os.close(slave_fd)

    # Send the initial working directory to the client immediately.
    await websocket.send_text(json.dumps({
        "type": "cwd",
        "path": workspace_root,
        "workspace": workspace_root,
    }))

    # Track temp dir for cleanup when the process exits.
    process._brockston_rc_dir = rc_dir  # type: ignore[attr-defined]

    async def read_from_pty():
        try:
            while True:
                r, _, _ = select.select([master_fd], [], [], 0.1)
                if master_fd in r:
                    output = os.read(master_fd, 10240).decode('utf-8', errors='ignore')
                    if output:
                        await websocket.send_text(json.dumps({"type": "output", "data": output}))
                else:
                    await asyncio.sleep(0.01)
                if process.poll() is not None:
                    break
        except Exception:
            pass

    async def write_to_pty():
        try:
            while True:
                data = await websocket.receive_text()
                if not data or data == '""': continue
                payload = json.loads(data)
                if payload.get("type") == "input":
                    os.write(master_fd, payload.get("data", "").encode())
                elif payload.get("type") == "resize":
                    # Support TUI apps like nano/vim by updating PTY window size
                    try:
                        import fcntl
                        import termios
                        import struct
                        cols = int(payload.get("cols", 80))
                        rows = int(payload.get("rows", 24))
                        winsize = struct.pack("HHHH", rows, cols, 0, 0)
                        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)
                    except Exception:
                        pass  # best effort
        except Exception:
            pass

    try:
        await asyncio.gather(read_from_pty(), write_to_pty(), return_exceptions=True)
    finally:
        process.kill()
        # Clean up the temporary rc directory we created for OSC 7 hook injection
        try:
            import shutil
            shutil.rmtree(getattr(process, "_brockston_rc_dir", ""), ignore_errors=True)
        except Exception:
            pass

# ==========================================
# REALTIME VIEWER WEBSOCKET — live IDE state for external viewers
# ==========================================
from typing import Set

# Store active viewer connections
viewer_connections: Set[fastapi.WebSocket] = set()

async def broadcast_to_viewers(event_type: str, data: dict):
    """Broadcast an event to all connected viewers."""
    if not viewer_connections:
        return
    message = json.dumps({"type": event_type, "data": data})
    dead = set()
    for ws in viewer_connections:
        try:
            await ws.send_text(json.dumps({"type": event_type, "data": data}))
        except Exception:
            dead.add(ws)
    for ws in dead:
        viewer_connections.discard(ws)

@app.websocket("/ws/viewer")
async def websocket_viewer(websocket: fastapi.WebSocket):
    """WebSocket for real-time IDE viewer."""
    await websocket.accept()
    viewer_connections.add(websocket)
    logger.info("Viewer connected")

    # Send initial state
    try:
        await websocket.send_text(json.dumps({
            "type": "init",
            "data": {
                "workspace": str(WORKSPACE_ROOT),
                "cwd": str(WORKSPACE_ROOT),
                "ide_models": {
                    "autocomplete": "qwen2.5-coder:32b (local, autocomplete only)",
                    "family": f"{LLM_MODEL_GENERAL} (local Ollama)",
                    "claude": "claude-sonnet-4 (Anthropic API)",
                    "nemoclaw": "nvidia/nemotron-3-ultra-550b-a55b (NemoClaw agent)",
                    "nemotron": "nvidia/nemotron-3-ultra-550b-a55b (NVIDIA NIM)",
                    "mistral": "mistralai/mistral-nemotron (NVIDIA NIM)",
                },
                "endpoints": {
                    "family_chat": "/api/chat",
                    "claude_chat": "/api/claude",
                    "nemoclaw_chat": "/api/nemoclaw",
                    "nemotron_chat": "/api/nemotron",
                    "mistral_chat": "/api/mistral",
                    "viewer_ws": "/ws/viewer",
                    "ide_control_ws": "/ws/ide-control"
                },
                "note": "Instructors: Family, Claude, NemoClaw, Nemotron, Mistral, Auto-switcher."
            }
        }))
    except Exception:
        pass

    try:
        while True:
            # Keep connection alive, listen for any client messages (ping/pong)
            data = await websocket.receive_text()
            # Could handle ping/pong or commands from viewer here
    except Exception:
        pass
    finally:
        viewer_connections.discard(websocket)
        logger.info("Viewer disconnected")

# ==========================================
# IDE CONTROL — Spotlight instructor operates the IDE
# ==========================================
ide_control_connections: Set[fastapi.WebSocket] = set()

async def broadcast_ide_control(action: str, params: dict):
    """Push a command to all connected IDE frontends."""
    if not ide_control_connections:
        return
    dead = set()
    message = json.dumps({"type": "command", "action": action, "params": params})
    for ws in ide_control_connections:
        try:
            await ws.send_text(message)
        except Exception:
            dead.add(ws)
    for ws in dead:
        ide_control_connections.discard(ws)

@app.websocket("/ws/ide-control")
async def websocket_ide_control(websocket: fastapi.WebSocket):
    """
    Server → browser command channel.
    The spotlight instructor/being sends commands via /api/ide/command;
    this socket pushes them to the IDE frontend for execution.
    """
    await websocket.accept()
    ide_control_connections.add(websocket)
    logger.info("IDE control client connected")
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            msg_type = msg.get("type")
            if msg_type == "pong":
                continue
            if msg_type == "state_response":
                # Forward IDE state to all viewers so instructors see it
                await broadcast_to_viewers("ide_state", msg.get("data", {}))
    except Exception:
        pass
    finally:
        ide_control_connections.discard(websocket)
        logger.info("IDE control client disconnected")

class IdeCommandRequest(BaseModel):
    action: str
    params: dict = {}

@app.post("/api/ide/command")
async def ide_command_endpoint(request: IdeCommandRequest):
    """
    Execute an IDE control command from the spotlight instructor.
    Commands that need browser-side execution are pushed over /ws/ide-control.
    Server-side commands (file read/list, instructor state) execute here.
    """
    action = request.action.lower().strip()
    params = request.params
    logger.info(f"IDE command: {action} {params}")

    if action == "set_instructor":
        instructor = params.get("instructor", "family")
        await broadcast_ide_control("set_instructor", {"instructor": instructor})
        return {"ok": True, "action": action, "note": f"Pushed set_instructor {instructor}"}

    if action == "open_file":
        path = params.get("path", "")
        if not path:
            raise fastapi.HTTPException(status_code=400, detail="path required")
        abs_path = _resolve_user_path(path, WORKSPACE_ROOT)
        content = ""
        if abs_path.is_file():
            try:
                content = abs_path.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Could not read {abs_path}: {e}")
        await broadcast_ide_control("open_file", {"path": str(abs_path), "content": content})
        return {"ok": True, "action": action, "path": str(abs_path)}

    if action == "switch_tab":
        path = params.get("path", "")
        if not path:
            raise fastapi.HTTPException(status_code=400, detail="path required")
        await broadcast_ide_control("switch_tab", {"path": str(_resolve_user_path(path, WORKSPACE_ROOT))})
        return {"ok": True, "action": action}

    if action == "close_tab":
        path = params.get("path", "")
        await broadcast_ide_control("close_tab", {"path": str(_resolve_user_path(path, WORKSPACE_ROOT)) if path else ""})
        return {"ok": True, "action": action}

    if action == "save_file":
        await broadcast_ide_control("save_file", {"path": params.get("path", "")})
        return {"ok": True, "action": action}

    if action == "send_terminal":
        command = params.get("command", "")
        if not command:
            raise fastapi.HTTPException(status_code=400, detail="command required")
        await broadcast_ide_control("send_terminal", {"command": command})
        return {"ok": True, "action": action}

    if action == "refresh_files":
        await broadcast_ide_control("refresh_files", {})
        return {"ok": True, "action": action}

    if action == "get_state":
        # Push get_state request to the IDE; browser replies over /ws/ide-control
        await broadcast_ide_control("get_state", {})
        return {"ok": True, "action": action, "note": "state requested from browser"}

    # Unknown action — fail loud (Rule 6)
    raise fastapi.HTTPException(status_code=400, detail=f"Unknown IDE command: {action}")

# ==========================================
# FRONTEND SERVING
# ==========================================
backend_dir = Path(__file__).parent
frontend_dir = backend_dir / "frontend"
static_dir = frontend_dir / "static"

if static_dir.is_dir():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

@app.get("/")
async def root():
    return FileResponse(str(frontend_dir / "index.html"))
