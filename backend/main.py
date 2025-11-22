"""
BROCKSTON Studio Backend

FastAPI application serving the BROCKSTON Studio workbench.
"""

import asyncio
import logging
import os
import ptyprocess
from pathlib import Path
from typing import Optional, List, Dict

# --- GEMINI 3 FIX: Import dotenv to load API keys immediately ---
from dotenv import load_dotenv

# --- GEMINI 3 FIX: Load environment variables before services start ---
load_dotenv()

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect, File, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .ai_client import AIClient
from .speech_service import SpeechService
from .models import (
    OpenFileResponse,
    SaveFileRequest,
    SaveFileResponse,
    ChatRequest,
    ChatResponse,
    SuggestFixRequest,
    SuggestFixResponse,
    CloneRepoRequest,
    CloneRepoResponse,
    TranscribeResponse,
    SynthesizeSpeechRequest,
    SpeechChatRequest,
    ErrorResponse,
)
from .git_service import clone_repo
from .config import (
    HOST,
    PORT,
    BROCKSTON_BASE_URL,
    ULTIMATEEV_BASE_URL,
    resolve_path,
    get_workspace_root,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="BROCKSTON Studio",
    description="Local code workbench powered by BROCKSTON",
    version="1.0.0",
)

# CORS middleware for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Opened up for local dev ease
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize AI client and speech service (singletons)
ai_client: Optional[AIClient] = None
speech_service: Optional[SpeechService] = None


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    global ai_client, speech_service
    ai_client = AIClient(
        brockston_url=BROCKSTON_BASE_URL,
        ultimateev_url=ULTIMATEEV_BASE_URL
    )
    speech_service = SpeechService()
    logger.info(f"BROCKSTON Studio starting on {HOST}:{PORT}")
    logger.info(f"Workspace root: {get_workspace_root()}")


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up services on shutdown."""
    global ai_client
    if ai_client:
        await ai_client.close()
    logger.info("BROCKSTON Studio shut down")


# --- GEMINI 3 FIX: Serve frontend static files correctly ---
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    # We point explicitly to the 'static' subdirectory now
    if (frontend_path / "static").exists():
        app.mount("/static", StaticFiles(directory=str(frontend_path / "static")), name="static")


@app.get("/", response_class=FileResponse)
async def serve_index():
    """Serve the main frontend HTML."""
    index_path = frontend_path / "index.html"
    if not index_path.exists():
        raise HTTPException(status_code=404, detail="Frontend not found")
    return FileResponse(index_path)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "BROCKSTON Studio",
        "workspace": str(get_workspace_root()),
    }


# ============================================================================
# File Operation Endpoints
# ============================================================================

# --- NEW ENDPOINT: File Tree Scanner for Sidebar ---
@app.get("/api/files/tree")
async def get_file_tree(path: str = None):
    """
    Scans the workspace and returns a list of files/folders.
    Used to populate the Project Explorer in the UI.
    """
    try:
        root_path = get_workspace_root()
        if path:
            target_path = (root_path / path).resolve()
            if not str(target_path).startswith(str(root_path)):
                 raise HTTPException(status_code=403, detail="Access denied")
        else:
            target_path = root_path

        items = []
        # Simple flat scan of current dir
        for entry in os.scandir(target_path):
            if entry.name.startswith(".") or entry.name == "__pycache__" or entry.name == "venv":
                continue
            
            items.append({
                "name": entry.name,
                "is_dir": entry.is_dir(),
                "path": str(Path(entry.path).relative_to(root_path))
            })
        
        # Sort: Directories first, then files
        items.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
        return {"files": items}

    except Exception as e:
        logger.error(f"Error scanning directory: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/files/open", response_model=OpenFileResponse)
async def open_file(path: str = Query(..., description="File path to open")):
    """
    Open and read a file from disk.
    """
    try:
        # Resolve and validate path
        file_path = resolve_path(path)

        # Check if file exists
        if not file_path.exists():
            raise HTTPException(
                status_code=404,
                detail=f"File not found: {path}"
            )

        # Check if it's a file (not a directory)
        if not file_path.is_file():
            raise HTTPException(
                status_code=400,
                detail=f"Path is not a file: {path}"
            )

        # Read file contents
        content = file_path.read_text(encoding="utf-8")

        logger.info(f"Opened file: {file_path}")
        return OpenFileResponse(path=str(file_path), content=content)

    except ValueError as e:
        # Path validation error (e.g., outside workspace)
        raise HTTPException(status_code=403, detail=str(e))
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=400,
            detail=f"File is not a text file: {path}"
        )
    except Exception as e:
        logger.error(f"Error reading file {path}: {e}")
        raise HTTPException(status_code=500, detail=f"Error reading file: {e}")


@app.post("/api/files/save", response_model=SaveFileResponse)
async def save_file(request: SaveFileRequest):
    """
    Save file contents to disk.
    """
    try:
        # Resolve and validate path
        file_path = resolve_path(request.path)

        # Create parent directories if they don't exist
        file_path.parent.mkdir(parents=True, exist_ok=True)

        # Write file contents
        file_path.write_text(request.content, encoding="utf-8")

        logger.info(f"Saved file: {file_path}")
        return SaveFileResponse(status="ok", path=str(file_path))

    except ValueError as e:
        # Path validation error
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error(f"Error saving file {request.path}: {e}")
        raise HTTPException(status_code=500, detail=f"Error saving file: {e}")


# ============================================================================
# Git Operation Endpoints
# ============================================================================

@app.post("/api/git/clone", response_model=CloneRepoResponse)
async def git_clone(request: CloneRepoRequest):
    """
    Clone a Git repository into the workspace.
    """
    try:
        # Clone the repository
        local_path = clone_repo(
            git_url=request.git_url,
            folder_name=request.folder_name,
        )

        # Extract workspace name from path
        workspace_name = local_path.name

        logger.info(f"Repository cloned successfully to: {local_path}")
        return CloneRepoResponse(
            status="ok",
            local_path=str(local_path),
            workspace_name=workspace_name,
        )

    except ValueError as e:
        # Validation errors (invalid URL, path outside workspace, etc.)
        logger.warning(f"Clone validation error: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        # Git operation errors
        logger.error(f"Git clone error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error during clone: {e}")
        raise HTTPException(status_code=500, detail=f"Clone failed: {e}")


# ============================================================================
# BROCKSTON Interaction Endpoints
# ============================================================================

@app.post("/api/brockston/chat", response_model=ChatResponse)
async def brockston_chat(request: ChatRequest):
    """
    Chat with AI assistant (BROCKSTON or UltimateEV) about code or ask questions.
    """
    try:
        # Convert Pydantic models to dicts for client
        messages = [msg.dict() for msg in request.messages]
        context = request.context.dict() if request.context else None
        model = request.model or "brockston"

        # Call AI client
        reply = await ai_client.chat(
            messages=messages,
            model=model,
            context=context
        )

        logger.info(f"{model.upper()} chat completed ({len(messages)} messages)")
        return ChatResponse(reply=reply)

    except ValueError as e:
        # Invalid model selection
        logger.error(f"Invalid model selection: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.error(f"AI chat error: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in chat: {e}")
        raise HTTPException(status_code=500, detail=f"Chat error: {e}")


@app.post("/api/brockston/suggest_fix", response_model=SuggestFixResponse)
async def brockston_suggest_fix(request: SuggestFixRequest):
    """
    Ask AI assistant (BROCKSTON or UltimateEV) to suggest code improvements.
    """
    try:
        model = request.model or "brockston"

        # Call AI client
        result = await ai_client.suggest_fix(
            code=request.code,
            instruction=request.instruction,
            model=model,
            path=request.path,
        )

        logger.info(f"{model.upper()} suggest_fix completed: {request.instruction}")
        return SuggestFixResponse(
            proposed_code=result["proposed_code"],
            summary=result["summary"],
        )

    except ValueError as e:
        # Invalid model selection
        logger.error(f"Invalid model selection: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.error(f"AI suggest_fix error: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in suggest_fix: {e}")
        raise HTTPException(status_code=500, detail=f"Suggest fix error: {e}")


# ============================================================================
# Speech Interaction Endpoints
# ============================================================================

@app.post("/api/speech/transcribe", response_model=TranscribeResponse)
async def transcribe_audio(audio: UploadFile = File(...)):
    """
    Transcribe audio to text using speech-to-text.
    """
    try:
        # Read audio data
        audio_data = await audio.read()

        # Transcribe audio
        text = await speech_service.transcribe_audio(
            audio_data=audio_data,
            filename=audio.filename or "audio.webm"
        )

        logger.info(f"Transcribed audio: {len(audio_data)} bytes -> {len(text)} chars")
        return TranscribeResponse(text=text)

    except RuntimeError as e:
        logger.error(f"Transcription error: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in transcription: {e}")
        raise HTTPException(status_code=500, detail=f"Transcription error: {e}")


@app.post("/api/speech/synthesize")
async def synthesize_speech(request: SynthesizeSpeechRequest):
    """
    Convert text to speech using text-to-speech.
    """
    try:
        # Synthesize speech
        audio_data = await speech_service.synthesize_speech(
            text=request.text,
            voice=request.voice or "alloy"
        )

        logger.info(f"Synthesized speech: {len(request.text)} chars -> {len(audio_data)} bytes")

        # Return audio as MP3
        return Response(
            content=audio_data,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "attachment; filename=speech.mp3"
            }
        )

    except RuntimeError as e:
        logger.error(f"Speech synthesis error: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in speech synthesis: {e}")
        raise HTTPException(status_code=500, detail=f"Speech synthesis error: {e}")


@app.post("/api/speech/chat")
async def speech_chat(request: SpeechChatRequest):
    """
    Full speech-to-speech chat flow.
    """
    try:
        # Convert Pydantic models to dicts for client
        messages = [msg.dict() for msg in request.messages]
        context = request.context.dict() if request.context else None
        model = request.model or "brockston"
        voice = request.voice or "alloy"

        # Get AI response
        reply_text = await ai_client.chat(
            messages=messages,
            model=model,
            context=context
        )

        # Convert response to speech
        audio_data = await speech_service.synthesize_speech(
            text=reply_text,
            voice=voice
        )

        logger.info(f"Speech chat completed: {model.upper()} -> {len(audio_data)} bytes audio")

        # Return audio with text in header for frontend
        return Response(
            content=audio_data,
            media_type="audio/mpeg",
            headers={
                "Content-Disposition": "attachment; filename=response.mp3",
                "X-Response-Text": reply_text[:500]  # First 500 chars in header
            }
        )

    except ValueError as e:
        logger.error(f"Invalid model selection: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        logger.error(f"Speech chat error: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in speech chat: {e}")
        raise HTTPException(status_code=500, detail=f"Speech chat error: {e}")


# ============================================================================
# Error Handlers
# ============================================================================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Custom handler for HTTP exceptions."""
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=exc.detail,
            detail=None,
        ).dict(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request, exc):
    """Catch-all handler for unexpected errors."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="Internal server error",
            detail=str(exc),
        ).dict(),
    )


# ============================================================================
# Terminal WebSocket Endpoint
# ============================================================================

@app.websocket("/ws/terminal")
async def terminal_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for terminal interaction.
    Spawns a bash shell in a PTY and bidirectionally streams I/O.
    """
    await websocket.accept()
    logger.info("Terminal WebSocket connection accepted")

    # Determine shell to use
    shell = os.environ.get("SHELL", "/bin/bash")

    # Get workspace root for shell working directory
    workspace_root = get_workspace_root()

    try:
        # Spawn shell process in PTY
        process = ptyprocess.PtyProcess.spawn(
            [shell],
            cwd=str(workspace_root),
            env=os.environ.copy(),
        )

        logger.info(f"Spawned shell: {shell} (PID: {process.pid})")

        # Task to read from PTY and send to WebSocket
        async def read_from_pty():
            try:
                while process.isalive():
                    try:
                        # Read from PTY (non-blocking with timeout)
                        output = process.read(1024)
                        if output:
                            await websocket.send_json({
                                "type": "output",
                                "data": output.decode("utf-8", errors="replace"),
                            })
                    except EOFError:
                        break
                    except Exception as e:
                        logger.error(f"Error reading from PTY: {e}")
                        break
                    await asyncio.sleep(0.01)  # Small delay to prevent busy loop
            except Exception as e:
                logger.error(f"PTY read task error: {e}")

        # Task to read from WebSocket and write to PTY
        async def read_from_websocket():
            try:
                while True:
                    message = await websocket.receive_json()
                    if message.get("type") == "input":
                        data = message.get("data", "")
                        process.write(data.encode("utf-8"))
            except WebSocketDisconnect:
                logger.info("WebSocket disconnected")
            except Exception as e:
                logger.error(f"WebSocket read error: {e}")

        # Run both tasks concurrently
        await asyncio.gather(
            read_from_pty(),
            read_from_websocket(),
        )

    except Exception as e:
        logger.error(f"Terminal WebSocket error: {e}")
        await websocket.send_json({
            "type": "error",
            "data": f"Terminal error: {str(e)}",
        })
    finally:
        # Clean up: kill process and close WebSocket
        try:
            if process.isalive():
                process.terminate(force=True)
                logger.info(f"Terminated shell process (PID: {process.pid})")
        except:
            pass

        try:
            await websocket.close()<br>        except:<br>            pass<br><br>        logger.info("Terminal WebSocket connection closed")<br><br><br># ============================================================================<br># Development Server<br># ============================================================================<br><br>if __name__ == "__main__":<br>    import uvicorn<br><br>    uvicorn.run(<br>        "backend.main:app",<br>        host=HOST,<br>        port=PORT,<br>        reload=True,<br>        log_level="info",<br>    )<br>```<br><br>---<br><br>### FILE 2: `frontend/index.html`<br>*ACTION: Overwrite `frontend/index.html`. This applies the Void Black/Neon Orange theme, enables the dynamic Crest animation, and adds the JavaScript to pull the file list from the backend.*<br><br>```html<br><!DOCTYPE html><br><html lang="en"><br><head><br><meta charset="UTF-8"><br><title>Brockston Studio - Pro</title><br><style><br>  :root {<br>    /* CORE THEME: VOID BLACK & NEON ORANGE */<br>    --theme-orange: #FF5F1F; /* The High Energy Line Color */<br>    --theme-cyan: #00B4D8;   /* Accent */<br>    --bg-void: #000000;      /* Absolute Black */<br>    --panel-bg: #0a0a0a;     /* Slightly lighter for panels */<br>    <br>    --border-color: #333;<br>    --text-primary: #e0e0e0;<br>    --text-secondary: #888;<br>    --font-terminal: 'Menlo', 'Consolas', monospace;<br>  }<br><br>  body {<br>    margin: 0;<br>    height: 100vh;<br>    background-color: var(--bg-void);<br>    color: var(--text-primary);<br>    font-family: var(--font-terminal);<br>    overflow: hidden;<br>    display: flex;<br>    justify-content: center;<br>    align-items: center;<br>  }<br><br>  /* MAIN CONTAINER */<br>  .studio-container {<br>    width: 100vw;<br>    height: 100vh;<br>    display: grid;<br>    grid-template-rows: 35px 1fr 200px; /* Header | Middle | Terminal */<br>    background: var(--bg-void);<br>  }<br><br>  /* HEADER - With Neon Orange Underline */<br>  .header {<br>    border-bottom: 2px solid var(--theme-orange); /* MARKUP MATCH */<br>    display: flex;<br>    align-items: center;<br>    padding: 0 15px;<br>    background: #020202;<br>    font-size: 0.9rem;<br>    letter-spacing: 2px;<br>    color: var(--theme-orange);<br>    font-weight: bold;<br>    justify-content: space-between;<br>  }<br><br>  /* MIDDLE AREA - 4 COLUMNS */<br>  .middle-area {<br>    display: grid;<br>    grid-template-columns: 60px 280px 1fr 400px; <br>    overflow: hidden;<br>    background: var(--bg-void);<br>  }<br><br>  /* COL 1: TOOLS */<br>  .col-tools {<br>    border-right: 1px solid var(--theme-orange); /* MARKUP MATCH */<br>    background: #050505;<br>    display: flex;<br>    flex-direction: column;<br>    align-items: center;<br>    padding-top: 20px;<br>    color: var(--text-secondary);<br>  }<br>  .tool-icon {<br>    font-size: 1.4rem; margin-bottom: 30px; cursor: pointer; transition: color 0.2s;<br>  }<br>  .tool-icon:hover { color: var(--theme-orange); text-shadow: 0 0 8px var(--theme-orange); }<br><br>  /* COL 2: FILES - Now Functional */<br>  .col-files {<br>    border-right: 1px solid var(--theme-orange); /* MARKUP MATCH */<br>    padding: 10px;<br>    font-size: 0.9rem;<br>    overflow-y: auto;<br>    background: var(--panel-bg);<br>  }<br>  .section-title { <br>    color: var(--theme-cyan); <br>    font-size: 0.8rem; <br>    margin-bottom: 15px; <br>    text-transform: uppercase; <br>    border-bottom: 1px solid #333;<br>    padding-bottom: 5px;<br>  }<br>  <br>  /* Dynamic File List Styles */<br>  #file-list { list-style: none; padding: 0; margin: 0; }<br>  .file-item { <br>    padding: 4px 0; <br>    cursor: pointer; <br>    color: #aaa; <br>    display: flex; <br>    align-items: center;<br>    transition: all 0.2s;<br>  }<br>  .file-item:hover { color: var(--theme-orange); background: #111; }<br>  .file-icon { margin-right: 10px; width: 15px; text-align: center; }<br><br>  /* COL 3: CENTER WORKSPACE - DYNAMIC */<br>  .col-center {<br>    position: relative;<br>    background: radial-gradient(circle at center, #1a0500 0%, #000000 80%); /* Subtle Orange Glow center */<br>    display: flex;<br>    justify-content: center;<br>    align-items: center;<br>    overflow: hidden;<br>    border-right: 1px solid var(--theme-orange); /* MARKUP MATCH */<br>  }<br>  <br>  /* DYNAMIC CREST ANIMATION */<br>  .crest-bg {<br>    width: 400px;<br>    opacity: 0.9;<br>    border-radius: 50%;<br>    animation: breathe 6s infinite ease-in-out;<br>  }<br><br>  @keyframes breathe {<br>    0% { transform: scale(0.95); filter: drop-shadow(0 0 10px rgba(255, 95, 31, 0.2)); }<br>    50% { transform: scale(1.0); filter: drop-shadow(0 0 30px rgba(255, 95, 31, 0.5)); }<br>    100% { transform: scale(0.95); filter: drop-shadow(0 0 10px rgba(255, 95, 31, 0.2)); }<br>  }<br><br>  /* COL 4: Q&A PANEL */<br>  .col-qa {<br>    background: var(--panel-bg);<br>    display: flex;<br>    flex-direction: column;<br>    height: 100%;<br>  }<br>  .qa-header {<br>    padding: 15px; <br>    border-bottom: 1px solid var(--theme-orange);<br>    text-align: left; <br>    color: var(--theme-cyan); <br>    font-size: 0.85rem;<br>    font-weight: bold;<br>  }<br>  .qa-log {<br>    flex-grow: 1; padding: 20px; overflow-y: auto; font-size: 0.9rem;<br>  }<br>  .qa-bubble {<br>    margin-bottom: 20px; padding: 15px; border-left: 3px solid #444; background: rgba(255,255,255,0.02);<br>  }<br>  <br>  .qa-input-area {<br>    border-top: 1px solid var(--theme-orange);<br>    padding: 15px;<br>    display: flex;<br>    background: #000;<br>  }<br>  .qa-text-input {<br>    flex-grow: 1;<br>    background: #111;<br>    border: 1px solid #333;<br>    color: var(--text-primary);<br>    font-family: inherit;<br>    padding: 10px;<br>    resize: none;<br>    height: 45px;<br>    outline: none;<br>  }<br>  .qa-text-input:focus { border-color: var(--theme-orange); }<br>  .qa-send-btn {<br>    margin-left: 10px;<br>    background: var(--theme-orange);<br>    color: #000;<br>    border: none;<br>    padding: 0 20px;<br>    cursor: pointer;<br>    font-weight: bold;<br>    font-family: inherit;<br>  }<br>  .qa-send-btn:hover { opacity: 0.8; }<br><br><br>  /* BOTTOM: TERMINAL */<br>  .terminal-panel {<br>    border-top: 2px solid var(--theme-orange); /* MARKUP MATCH */<br>    background: #000;<br>    padding: 10px;<br>    display: flex;<br>    flex-direction: column;<br>    font-size: 1rem;<br>  }<br>  .terminal-header { font-size: 0.8rem; color: var(--text-secondary); margin-bottom: 5px; }<br>  .input-line { display: flex; align-items: center; height: 100%; }<br>  .cli-input {<br>    background: transparent; border: none; color: #27c93f;<br>    font-family: inherit; font-size: 1rem; width: 100%;<br>    outline: none;<br>  }<br></style><br><link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"><br></head><br><body><br><br><div class="studio-container"><br>  <br>  <div class="header"><br>    <span>BROCKSTON STUDIO // PROFESSIONAL EDITION</span><br>    <span style="font-size: 0.7em; color: #666;">HOST: 127.0.0.1</span><br>  </div><br><br>  <br>  <div class="middle-area"><br>    <br>    <br>    <div class="col-tools"><br>      <i class="fa-solid fa-terminal tool-icon" title="Terminal"></i><br>      <i class="fa-solid fa-code-branch tool-icon" title="Git Control"></i><br>      <i class="fa-solid fa-magnifying-glass tool-icon" title="Search"></i><br>      <i class="fa-solid fa-gear tool-icon" title="Settings"></i><br>    </div><br><br>    <br>    <div class="col-files"><br>      <div class="section-title">PROJECT EXPLORER</div><br>      <ul id="file-list"><br>          <br>          <li style="color:#444; padding:10px;">[Scanning...]</li><br>      </ul><br><br>      <div class="section-title" style="margin-top: 30px;">MEMORY CORE</div><br>      <div class="file-item"><i class="fa-solid fa-brain file-icon" style="color:var(--theme-orange)"></i> StillHere_Protocol</div><br>    </div><br><br>    <br>    <div class="col-center"><br>      <br>      <img src="static/family_crest.jpg" class="crest-bg" alt="Family Crest"><br>    </div><br><br>    <br>    <div class="col-qa"><br>      <div class="qa-header">ASK BROCKSTON / ULTIMATE_EV</div><br>      <div class="qa-log" id="qaLog"><br>        <div class="qa-bubble" style="border-color: var(--theme-cyan);"><br>          <span style="color:var(--theme-cyan)">[SYSTEM]:</span> Neural Link Active. Ready for queries.<br>        </div><br>      </div><br>      <br>      <div class="qa-input-area"><br>          <textarea class="qa-text-input" id="brockstonInput" placeholder="Ask a question..."></textarea><br>          <button class="qa-send-btn" id="sendBtn">SEND</button><br>      </div><br>    </div><br><br>  </div><br><br>  <br>  <div class="terminal-panel" onclick="document.getElementById('termInput').focus()"><br>    <div class="terminal-header">GITHUB LINK / SYSTEM TERMINAL</div><br>    <div class="input-line"><br>      <span style="color:var(--theme-orange); margin-right: 10px;">➜</span> <br>      <input type="text" class="cli-input" id="termInput" placeholder="Enter command..." autofocus><br>    </div><br>  </div><br></div><br><br><script><br>  const termInput = document.getElementById('termInput');<br>  const brockstonInput = document.getElementById('brockstonInput');<br>  const sendBtn = document.getElementById('sendBtn');<br>  const qaLog = document.getElementById('qaLog');<br>  const fileList = document.getElementById('file-list');<br><br>  // --- 1. LOAD FILES FROM BACKEND ---<br>  async function loadFiles() {<br>      try {<br>          // Hit the new endpoint created in main.py<br>          const res = await fetch('/api/files/tree');<br>          const data = await res.json();<br>          <br>          fileList.innerHTML = ''; // Clear loading<br>          <br>          if(data.files && data.files.length > 0) {<br>              data.files.forEach(file => {<br>                  const li = document.createElement('li');<br>                  li.className = 'file-item';<br>                  <br>                  // Icon logic<br>                  let icon = 'fa-file';<br>                  if(file.is_dir) icon = 'fa-folder';<br>                  else if(file.name.endsWith('.py')) icon = 'fa-brands fa-python';<br>                  else if(file.name.endsWith('.js')) icon = 'fa-brands fa-js';<br>                  else if(file.name.endsWith('.html')) icon = 'fa-brands fa-html5';<br>                  <br>                  li.innerHTML = `<i class="fa-regular ${icon} file-icon"></i> ${file.name}`;<br>                  li.onclick = () => console.log("Opening:", file.path);<br>                  fileList.appendChild(li);<br>              });<br>          } else {<br>              fileList.innerHTML = '<li style="padding:10px; color:red">No files found.</li>';<br>          }<br>      } catch (e) {<br>          console.error(e);<br>          fileList.innerHTML = '<li style="padding:10px; color:var(--theme-orange)">Neural Link Error: Backend Offline?</li>';<br>      }<br>  }<br><br>  // Initial Load<br>  loadFiles();<br><br>  // --- 2. TERMINAL MOCKUP ---<br>  termInput.addEventListener('keypress', async (e) => {<br>    if (e.key === 'Enter' && termInput.value) {<br>      const text = termInput.value;<br>      termInput.value = '';<br>      console.log(`Command: ${text}`);<br>      // Future: Send to /ws/terminal<br>    }<br>  });<br><br>  // --- 3. CHAT HANDLING ---<br>  function sendToBrockston() {<br>      const text = brockstonInput.value;<br>      if(!text) return;<br>      brockstonInput.value = '';<br><br>      qaLog.innerHTML += `<div class="qa-bubble" style="border-color:#444;"><span style="color:#888">YOU:</span> ${text}</div>`;<br>      qaLog.scrollTop = qaLog.scrollHeight;<br><br>      // Simulate Response<br>      setTimeout(() => {<br>           qaLog.innerHTML += `<div class="qa-bubble" style="border-color:var(--theme-cyan);"><span style="color:var(--theme-cyan)">[BROCKSTON]:</span> Command received.</div>`;<br>           qaLog.scrollTop = qaLog.scrollHeight;<br>      }, 500);<br>  }<br><br>  brockstonInput.addEventListener('keypress', (e) => {<br>      if(e.key === 'Enter' && !e.shiftKey) {<br>          e.preventDefault(); <br>          sendToBrockston();<br>      }<br>  });<br><br>  sendBtn.addEventListener('click', sendToBrockston);<br></script><br></body><br></html><br>```
