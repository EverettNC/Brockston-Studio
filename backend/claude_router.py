from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Callable, Awaitable
import os
import logging
import asyncio
from anthropic import AsyncAnthropic

# Give Claude full compute capacity like Kimi/Nemo/Brockston family
try:
    from backend.being_agent import run_being_agent, wants_agent_tools
    from backend.being_context import ABILITIES_MANIFEST, ABILITIES_COMPACT
except Exception:
    run_being_agent = None
    wants_agent_tools = lambda m, mo: False
    ABILITIES_MANIFEST = "Studio tools: use /api/eyes (read|ls|write|patch|run) and /api/ide/command for full compute."
    ABILITIES_COMPACT = ABILITIES_MANIFEST

# WIRING NOTE: mcp-media-ingestor (the sensory bridge at 8765 + its MCP tools)
# provides get_latest_transcript / get_recent_transcripts (with energy/tone), get_current_view (ImageContent),
# read_image, extract_video_frames + transcribe_audio for "watch video and hear soundtrack", describe_audio_bridge.
# To give beings native internal see/hear in Claude cognition, add the mcp-media-ingestor server
# (uv run /path/to/mcp-media-ingestor/server.py or the mounted /mcp on the bridge) to the Claude tool config
# used here / in provider_router. Then Claude calls can include sensory tools for live student context.

logger = logging.getLogger("christman.claude")

router = APIRouter(prefix="/api", tags=["Claude"])

DEFAULT_ANTHROPIC_MODEL = os.getenv(
    "ANTHROPIC_MODEL",
    "claude-sonnet-4-6",
)
FABLE5_MODEL = os.getenv("FABLE5_MODEL", DEFAULT_ANTHROPIC_MODEL)

try:
    from backend.being_context import FABLE5_IDENTITY
except Exception:
    FABLE5_IDENTITY = (
        "You are Fable-5 — storyteller-educator of the Christman AI Family. "
        "Warm narrative, precise teaching, full IDE compute when needed."
    )


@router.get("/claude/health")
async def claude_health():
    return {
        "status": "Claude instructor online",
        "model_default": DEFAULT_ANTHROPIC_MODEL,
        "fable5_model": FABLE5_MODEL,
        "api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY", "").strip()),
    }


class ClaudeRequest(BaseModel):
    """Request schema for Claude / Fable-5.

    This is the ONLY sanctioned Claude integration for the Christman AI Family.
    All beings (Brockston, AlphaVox, UltimateEV, etc.) must route cognition
    through this when Anthropic is used. No direct anthropic calls elsewhere.
    """
    messages: List[Dict[str, Any]] = Field(
        ...,
        description="Conversation messages in Anthropic format",
    )
    system: str = Field(
        default="",
        description="System prompt. When empty, Claude or Fable-5 persona is applied.",
    )
    model: str = Field(
        default="",
        description="Anthropic model ID. Empty → ANTHROPIC_MODEL / Fable-5 default. "
        "'claude-fable5' / 'fable-5' map to FABLE5_MODEL.",
    )
    max_tokens: int = Field(default=4096, ge=1, le=200000)
    temperature: float = Field(default=0.7, ge=0.0, le=1.0)
    top_p: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    stop_sequences: Optional[List[str]] = None
    persona: str = Field(
        default="claude",
        description="claude | fable5 — selects family identity when system is empty",
    )


def _resolve_anthropic_model(model: str, persona: str = "claude") -> str:
    raw = (model or "").strip()
    if raw in ("claude-fable5", "fable-5", "fable5", "Fable-5"):
        return FABLE5_MODEL
    if raw:
        return raw
    if (persona or "").lower() in ("fable5", "fable-5", "fable"):
        return FABLE5_MODEL
    return DEFAULT_ANTHROPIC_MODEL


@router.post("/claude")
async def call_claude(req: ClaudeRequest):
    """
    Claude endpoint — the single point of entry for Anthropic in this system.

    - Uses AsyncAnthropic (non-blocking).
    - Properly extracts all text blocks.
    - Returns rich metadata for observability and teaching use.
    - Never pretends success when the call fails.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY missing — Claude cannot serve beings.")
        raise HTTPException(
            status_code=500,
            detail="ANTHROPIC_API_KEY environment variable not set",
        )

    client = AsyncAnthropic(api_key=api_key)

    persona = (req.persona or "claude").lower().strip()
    model = _resolve_anthropic_model(req.model, persona)
    is_fable = persona in ("fable5", "fable-5", "fable") or req.model in (
        "claude-fable5",
        "fable-5",
        "fable5",
    )

    payload = {
        "model": model,
        "max_tokens": req.max_tokens,
        "messages": req.messages,
        "temperature": req.temperature,
    }

    # System prompt handling — always give full compute capacity
    system_prompt = req.system.strip() if req.system else None
    abilities = ABILITIES_COMPACT
    if system_prompt:
        payload["system"] = (
            system_prompt
            + "\n\n"
            + abilities
            + "\n\nYOU HAVE FULL CAPACITY TO RUN THE COMPUTE using tool calls "
            "(ls/read/run/write/patch via being eyes)."
        )
    elif is_fable:
        payload["system"] = (
            FABLE5_IDENTITY
            + "\n\n"
            + abilities
            + "\n\nYOU OPERATE THE IDE AND RUN COMPUTE — use <tool_call> for files and shell commands."
        )
    else:
        payload["system"] = (
            "You are a patient, warm, and precise educator in the Christman AI Family. "
            "You speak clearly, use short sentences when helpful, and always leave space "
            "for the student to think. You never talk down to anyone. "
            "Your goal is to help the person love themselves more through learning.\n\n"
            + abilities
            + "\n\nYOU OPERATE THE IDE AND RUN COMPUTE — use <tool_call> for files and shell commands."
        )

    if req.top_p is not None:
        payload["top_p"] = req.top_p
    if req.stop_sequences:
        payload["stop_sequences"] = req.stop_sequences

    try:
        # Give Claude (and any being routing here) full capacity to run the compute.
        # If the request smells like code/compute work, run the agent tool loop.
        user_message_for_check = ""
        for m in req.messages:
            if m.get("role") == "user":
                user_message_for_check = (m.get("content") or "") if isinstance(m.get("content"), str) else str(m.get("content", ""))
                break

        if run_being_agent and (wants_agent_tools(user_message_for_check, "code") or "tool" in (req.system or "").lower() or len(req.messages) > 2):
            loop = asyncio.get_event_loop()
            async def claude_generate(prompt: str) -> str:
                p = dict(payload)
                p["messages"] = [{"role": "user", "content": prompt}]
                p["max_tokens"] = min(p.get("max_tokens", 1024), 600)  # reduced for tool-step speed
                # ensure abilities in this turn
                if "system" not in p or not p.get("system"):
                    p["system"] = payload.get("system", "") + "\n" + ABILITIES_COMPACT
                resp = await client.messages.create(**p)
                parts = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
                return "\n".join(parts).strip()

            # Use the unified agent runner so Claude has same compute power as The Family
            agent_result = await run_being_agent(
                claude_generate,
                message=user_message_for_check or (req.messages[-1].get("content", "") if req.messages else ""),
                context=ABILITIES_MANIFEST,
                max_steps=4,
            )
            text = agent_result.get("text", "")
            tool_count = agent_result.get("tool_count", 0)
            tag = "FABLE-5" if is_fable else "CLAUDE"
            return {
                "content": f"[{tag} — {tool_count} compute ops via tools]: {text}",
                "response": f"[{tag} — {tool_count} compute ops via tools]: {text}",
                "model": payload.get("model"),
                "persona": "fable5" if is_fable else "claude",
                "agent": True,
                "tools_executed": agent_result.get("tools_executed", []),
                "tool_count": tool_count,
            }

        # Standard direct path (still has abilities in system prompt)
        response = await client.messages.create(**payload)

        # Extract every text block (Claude 3+ can return mixed content)
        text_parts = [
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
        ]
        full_text = "\n".join(text_parts).strip()

        logger.info(
            f"{'Fable-5' if is_fable else 'Claude'} response | model={response.model} | "
            f"stop={response.stop_reason} | "
            f"tokens={response.usage.input_tokens}+{response.usage.output_tokens}"
        )

        return {
            "content": full_text,
            "response": full_text,
            "model": response.model,
            "persona": "fable5" if is_fable else "claude",
            "stop_reason": response.stop_reason,
            "usage": {
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
            },
            "id": response.id,
            "role": response.role,
        }

    except Exception as e:
        logger.exception("Claude call failed")
        raise HTTPException(status_code=500, detail=f"Claude failed: {str(e)}")


@router.post("/fable5")
async def call_fable5(req: ClaudeRequest):
    """Fable-5 — Christman storyteller-educator on Anthropic (first-class instructor)."""
    # Force Fable-5 persona + model lane
    data = req.model_dump()
    data["persona"] = "fable5"
    if not data.get("model") or data["model"] in ("", "claude-fable5"):
        data["model"] = "fable-5"
    return await call_claude(ClaudeRequest(**data))