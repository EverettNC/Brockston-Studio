"""
BROCKSTON Studio Backend

FastAPI application serving the BROCKSTON Studio workbench.
"""

import asyncio
import logging
import os
import ptyprocess
from pathlib import Path
from typing import Optional

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
    allow_origins=["*"], 
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
    Spawns a bash shell in
