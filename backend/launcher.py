import os
import logging
import subprocess
import pty
import select
import json
import asyncio
import tempfile
from typing import List, Optional
from pathlib import Path
import sys

# Ensure backend/ is on sys.path so relative imports work when launcher is run
# via `python3 -m uvicorn backend.launcher:app` from the project root.
_BACKEND_DIR = str(Path(__file__).resolve().parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect, UploadFile, File, Request # pyright: ignore[reportMissingImports]
from fastapi.responses import Response # pyright: ignore[reportMissingImports]
from fastapi.staticfiles import StaticFiles # pyright: ignore[reportMissingImports]
from fastapi.middleware.cors import CORSMiddleware # pyright: ignore[reportMissingImports]
from pydantic import BaseModel # pyright: ignore[reportMissingImports]

# Key drop box (Settings panel) wins over .env / shell exports.
import key_box
key_box.apply_to_environ()

from config import OLLAMA_BASE_URL, LLM_MODEL_GENERAL, LLM_MODEL_CODER, STUDIO_WORKSPACE, HOST, PORT

STUDIO_BACKEND_MODE = os.getenv(
    "STUDIO_BACKEND_MODE", os.getenv("BROCKSTON_MODE", "educator")
)
from brockston_client import BrockstonClient

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("brockston-studio")

app = FastAPI(title="Brockston IDE Studio")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
)

OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "60"))  # reduced for lower lag on BROCKSTON responses and tool steps
agent = BrockstonClient(
    base_url=OLLAMA_BASE_URL,
    model=LLM_MODEL_GENERAL,  # fast path for chat/vocal/team
    timeout=OLLAMA_TIMEOUT,
)
coder_agent = BrockstonClient(
    base_url=OLLAMA_BASE_URL,
    model=LLM_MODEL_CODER,
    timeout=OLLAMA_TIMEOUT,
)

class ChatRequest(BaseModel):
    messages: List
    context: Optional[dict] = None

class SuggestFixRequest(BaseModel):
    code: str
    instruction: str
    path: Optional[str] = None

class ExecuteRequest(BaseModel):
    code: str
    language: str = "python"
    timeout: float = 5.0

class SpeakRequest(BaseModel):
    text: str
    voice: str = "default"

@app.get("/")
async def root():
    return {"status": "online", "model": LLM_MODEL_CODER}

@app.get("/api/health")
async def health_check():
    from backend.being_agent import AGENT_MODEL
    return {
        "status": "ok",
        "port": PORT,
        "mode": STUDIO_BACKEND_MODE,
        "workspace": STUDIO_WORKSPACE,
        "ollama": OLLAMA_BASE_URL,
        "models": {
            "chat": LLM_MODEL_GENERAL,
            "coder": LLM_MODEL_CODER,
            "being_agent": AGENT_MODEL,
        },
    }

@app.post("/api/chat")
async def chat(request: ChatRequest):
    # Sensory wiring: enrich with live student ear (tone/energy from mcp improved processor) + vision
    # so the beings actually hear/see the student in real time instead of text-only.
    # Requires mcp bridge up + feeders (continuous_mic for ear, vision_capture for screen).
    try:
        import httpx
        sensory_msgs = []
        async with httpx.AsyncClient(timeout=1.5) as c:
            lr = await c.get("http://localhost:8765/latest")
            live = lr.json() or {}
            if live.get("text"):
                sensory_msgs.append({
                    "role": "system",
                    "content": f"[LIVE STUDENT EAR from mcp bridge - energy={live.get('energy')} tone={live.get('tone')}] {live.get('text')}"
                })
            # recent for flow
            try:
                rr = await c.get("http://localhost:8765/recent?count=3")
                rec = rr.json()
                if isinstance(rec, str) and rec and "No recent" not in rec:
                    sensory_msgs.append({"role": "system", "content": f"[RECENT HEARD]\n{rec}"})
            except:
                pass
            # vision
            vr = await c.get("http://localhost:8765/vision/latest")
            v = vr.json() or {}
            if v.get("b64"):
                sensory_msgs.append({"role": "system", "content": "[STUDENT CURRENT VIEW available - use mcp get_current_view or describe for beings]"})
    except Exception:
        sensory_msgs = []

    enriched_messages = (sensory_msgs + request.messages) if sensory_msgs else request.messages

    # BROCKSTON now has full compute capacity (same as other beings).
    # Prompt injection for awareness + full tool loop when needed (ls/read/write/run via eyes).
    # Uses fast low-lag direct path for tool steps.
    try:
        from backend.being_context import ABILITIES_COMPACT
        from backend.being_agent import run_being_agent

        # Inject abilities
        if enriched_messages and enriched_messages[0].get("role") == "system":
            enriched_messages[0]["content"] = enriched_messages[0].get("content", "") + "\n\n" + ABILITIES_COMPACT
        else:
            enriched_messages = [{"role": "system", "content": ABILITIES_COMPACT}] + enriched_messages

        # Extract last user message for agent decision
        last_user_msg = ""
        for m in reversed(enriched_messages):
            if m.get("role") == "user":
                last_user_msg = str(m.get("content", ""))
                break

        # Use agent loop (with built-in fast direct Ollama + GENERAL model + reduced steps) for compute/tool work.
        # This lets BROCKSTON demonstrate full abilities (run commands, edit files, etc.) with low lag.
        if last_user_msg and any(k in last_user_msg.lower() for k in ("code", "run", "fix", "tool", "execute", "ls ", "read ", "write ", "patch", "demo", "ability", "compute")):
            # Build compact context including sensory
            ctx = ABILITIES_COMPACT
            if sensory_msgs:
                ctx += "\n\nSensory context: " + " ".join([s.get("content", "")[:200] for s in sensory_msgs if s.get("role")=="system"])

            result = await run_being_agent(
                message=last_user_msg,
                context=ctx,
            )
            tool_count = result.get("tool_count", 0)
            prefix = f"[BROCKSTON — {tool_count} compute tool(s) executed]: " if tool_count else "[BROCKSTON]: "
            reply = prefix + result.get("text", "")
            return {"reply": reply, "response": reply, "ok": True, "agent": True, "tools_executed": result.get("tools_executed", [])}

        # For normal chat on BROCKSTON, use the already-configured fast GENERAL model via client (low lag)
    except Exception as e:
        logger.warning(f"[BROCKSTON] Agent tool path skipped or failed (falling back to direct): {e}")

    try:
        logger.info(
            "[chat] Ollama inference starting — model=%s messages=%d",
            LLM_MODEL_GENERAL,
            len(enriched_messages),
        )
        reply = await agent.chat(messages=enriched_messages, context=request.context)
        logger.info("[chat] Ollama inference complete — %d chars", len(reply or ""))
        if not reply or str(reply).startswith("Ollama timed out"):
            raise HTTPException(status_code=504, detail=reply or "Ollama returned empty")
        return {"reply": reply, "response": reply, "ok": True}
    except Exception as e:
        logger.error(f"Chat error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/suggest_fix")
async def suggest_fix(request: SuggestFixRequest):
    try:
        return await coder_agent.suggest_fix(
            code=request.code, 
            instruction=request.instruction, 
            path=request.path
        )
    except Exception as e:
        logger.error(f"Suggest fix error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/files")
async def list_files(path: str = ""):
    try:
        target_dir = os.path.join(STUDIO_WORKSPACE, path) if path else STUDIO_WORKSPACE
        if not os.path.isdir(target_dir):
            raise HTTPException(status_code=400, detail="Invalid path")
        
        files = []
        for item in os.listdir(target_dir):
            if not item.startswith('.'):
                item_path = os.path.join(target_dir, item)
                kind = "folder" if os.path.isdir(item_path) else "file"
                files.append({"name": item, "type": kind})
        
        return {"files": sorted(files, key=lambda x: (x != "folder", x ))}
    except Exception as e:
        logger.error(f"File listing error: {e}")
        return {"files": []}

@app.post("/api/execute")
async def execute_code(request: ExecuteRequest):
    """Execute code safely with timeout"""
    try:
        import subprocess
        import time
        
        code = request.code
        language = request.language
        timeout = min(request.timeout, 10.0)  # Max 10 seconds
        
        if language not in ["python"]:
            raise HTTPException(status_code=400, detail="Language not supported")
        
        # Write code to temp file
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(code)
            temp_file = f.name
        
        try:
            # Execute with timeout
            result = subprocess.run(
                ["python", temp_file],
                capture_output=True,
                text=True,
                timeout=timeout
            )
            
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout,
                "stderr": result.stderr,
                "returncode": result.returncode
            }
        finally:
            import os
            os.unlink(temp_file)
            
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "error": f"Code execution timed out after {timeout} seconds"
        }
    except Exception as e:
        logger.error(f"Code execution error: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    """Transcribe audio to text. Prefers live student ear from mcp-media-ingestor bridge (real-time with energy/tone from improved silence-tail processor) when active. Falls back to mock/upload."""
    try:
        # Wire to mcp-media-ingestor live ear (8765). Run the bridge + continuous_mic.py (your Maonocaster E2) or mic_capture for student voice.
        # This gives beings (Brockston, AlphaVox) the rich live hearing (energy + tone + recent context) instead of mock.
        import httpx
        try:
            r = await httpx.AsyncClient(timeout=1.5).get("http://localhost:8765/latest")
            data = r.json()
            if data.get("text"):
                # Now includes our improvements: energy, tone, timing
                return {
                    "text": data.get("text"),
                    "energy": data.get("energy"),
                    "tone": data.get("tone"),
                    "timestamp": data.get("timestamp"),
                    "source": "mcp-media-ingestor-live-ear",
                    "note": "Live from sensory bridge (ear). Start continuous_mic.py in mcp dir + the bridge for real student voice."
                }
        except Exception:
            pass  # bridge not up or no audio yet - fall through

        audio_data = await file.read()
        
        # Fallback mock (original behavior)
        return {
            "text": "[Speech input - students can speak into browser microphone. For live: run mcp bridge + continuous_mic.py]",
            "confidence": 0.75,
            "filename": file.filename,
            "size": len(audio_data),
            "source": "mock"
        }
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/speak")
async def synthesize_speech(request: SpeakRequest):
    """Synthesize text to speech"""
    try:
        from speech_service import synthesize_speech
        
        text = request.text
        voice = request.voice
        
        # Generate audio bytes
        audio_bytes = await synthesize_speech(text, voice)
        
        return Response(content=audio_bytes, media_type="audio/mpeg")
    except Exception as e:
        logger.error(f"Speech synthesis error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/git/clone")
async def git_clone_repo(url: str, name: Optional[str] = None):
    """Clone a GitHub repository"""
    try:
        from git_service import clone_repo
        from pathlib import Path
        
        repo_path = clone_repo(url, name)
        return {
            "success": True,
            "path": str(repo_path),
            "url": url
        }
    except Exception as e:
        logger.error(f"Git clone error: {e}")
        return {"success": False, "error": str(e)}

@app.post("/api/git/commit")
async def git_commit(path: str, message: str = "Student work"):
    """Commit changes to git"""
    try:
        import subprocess
        
        result = subprocess.run(
            ["git", "-C", path, "add", "."],
            capture_output=True,
            text=True
        )
        
        result = subprocess.run(
            ["git", "-C", path, "commit", "-m", message],
            capture_output=True,
            text=True
        )
        
        return {
            "success": result.returncode == 0,
            "message": message,
            "output": result.stdout
        }
    except Exception as e:
        logger.error(f"Git commit error: {e}")
        return {"success": False, "error": str(e)}

@app.get("/api/git/status")
async def git_status(path: str):
    """Get git repository status"""
    try:
        import subprocess
        
        result = subprocess.run(
            ["git", "-C", path, "status", "--porcelain"],
            capture_output=True,
            text=True
        )
        
        return {
            "has_changes": bool(result.stdout.strip()),
            "status": result.stdout,
            "path": path
        }
    except Exception as e:
        logger.error(f"Git status error: {e}")
        return {"error": str(e)}

@app.get("/api/read_file")
async def read_file(filename: str):
    try:
        if ".." in filename or filename.startswith("/"):
            raise HTTPException(status_code=400, detail="Invalid filename")
        
        filepath = os.path.join(STUDIO_WORKSPACE, filename)
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        
        return {"content": content, "filename": filename}
    except Exception as e:
        logger.error(f"Read error: {e}")
        raise HTTPException(status_code=404, detail="File not found")

@app.websocket("/ws/terminal")
async def websocket_terminal(websocket: WebSocket):
    await websocket.accept()
    
    try:
        master_fd, slave_fd = pty.openpty()
        shell = os.environ.get("SHELL", "/bin/bash")
        
        process = subprocess.Popen(
            [shell],
            preexec_fn=os.setsid,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            universal_newlines=True
        )
        
        os.close(slave_fd)
        
        async def read_from_pty():
            while True:
                try:
                    r, _, _ = select.select([master_fd], [], [], 0.1)
                    if master_fd in r:
                        output = os.read(master_fd, 10240).decode('utf-8', errors='ignore')
                        if output:
                            await websocket.send_text(json.dumps({"type": "output", "data": output}))
                    await asyncio.sleep(0.01)
                except Exception as e:
                    logger.error(f"PTY read error: {e}")
                    break
        
        async def write_to_pty():
            while True:
                try:
                    data = await websocket.receive_text()
                    payload = json.loads(data)
                    if payload.get("type") == "input":
                        cmd = payload.get("data", "")
                        os.write(master_fd, (cmd + "\n").encode())
                except WebSocketDisconnect:
                    break
                except Exception as e:
                    logger.error(f"PTY write error: {e}")
                    break
        
        await asyncio.gather(read_from_pty(), write_to_pty())
    
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        try:
            os.close(master_fd)
        except:
            pass

if __name__ == "__main__":
    import uvicorn # pyright: ignore[reportMissingImports]
    uvicorn.run(app, host=HOST, port=PORT)
