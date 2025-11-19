"""
BROCKSTON Studio Backend

FastAPI application serving the BROCKSTON Studio workbench.
"""

import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

from .brockston_client import BrockstonClient
from .models import (
    OpenFileResponse,
    SaveFileRequest,
    SaveFileResponse,
    ChatRequest,
    ChatResponse,
    SuggestFixRequest,
    SuggestFixResponse,
    ErrorResponse,
)
from .config import (
    HOST,
    PORT,
    BROCKSTON_BASE_URL,
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
    allow_origins=["http://localhost:5055", "http://127.0.0.1:5055"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize BROCKSTON client (singleton)
brockston_client: Optional[BrockstonClient] = None


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    global brockston_client
    brockston_client = BrockstonClient(base_url=BROCKSTON_BASE_URL)
    logger.info(f"BROCKSTON Studio starting on {HOST}:{PORT}")
    logger.info(f"Workspace root: {get_workspace_root()}")


@app.on_event("shutdown")
async def shutdown_event():
    """Clean up services on shutdown."""
    global brockston_client
    if brockston_client:
        await brockston_client.close()
    logger.info("BROCKSTON Studio shut down")


# Serve frontend static files
frontend_path = Path(__file__).parent.parent / "frontend"
if frontend_path.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_path)), name="static")


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

@app.get("/api/files/open", response_model=OpenFileResponse)
async def open_file(path: str = Query(..., description="File path to open")):
    """
    Open and read a file from disk.

    Args:
        path: File path (absolute or relative to workspace)

    Returns:
        File path and contents

    Raises:
        HTTPException: If file not found or read error
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

    Args:
        request: File path and content to save

    Returns:
        Success status

    Raises:
        HTTPException: If write error occurs
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
# BROCKSTON Interaction Endpoints
# ============================================================================

@app.post("/api/brockston/chat", response_model=ChatResponse)
async def brockston_chat(request: ChatRequest):
    """
    Chat with BROCKSTON about code or ask questions.

    Args:
        request: Chat messages and optional file context

    Returns:
        BROCKSTON's reply

    Raises:
        HTTPException: If BROCKSTON communication fails
    """
    try:
        # Convert Pydantic models to dicts for client
        messages = [msg.dict() for msg in request.messages]
        context = request.context.dict() if request.context else None

        # Call BROCKSTON
        reply = await brockston_client.chat(messages=messages, context=context)

        logger.info(f"BROCKSTON chat completed ({len(messages)} messages)")
        return ChatResponse(reply=reply)

    except RuntimeError as e:
        logger.error(f"BROCKSTON chat error: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in chat: {e}")
        raise HTTPException(status_code=500, detail=f"Chat error: {e}")


@app.post("/api/brockston/suggest_fix", response_model=SuggestFixResponse)
async def brockston_suggest_fix(request: SuggestFixRequest):
    """
    Ask BROCKSTON to suggest code improvements.

    Args:
        request: Current code, instruction, and optional file path

    Returns:
        Proposed code and summary of changes

    Raises:
        HTTPException: If BROCKSTON communication fails
    """
    try:
        # Call BROCKSTON
        result = await brockston_client.suggest_fix(
            code=request.code,
            instruction=request.instruction,
            path=request.path,
        )

        logger.info(f"BROCKSTON suggest_fix completed: {request.instruction}")
        return SuggestFixResponse(
            proposed_code=result["proposed_code"],
            summary=result["summary"],
        )

    except RuntimeError as e:
        logger.error(f"BROCKSTON suggest_fix error: {e}")
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error in suggest_fix: {e}")
        raise HTTPException(status_code=500, detail=f"Suggest fix error: {e}")


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
# Development Server
# ============================================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "backend.main:app",
        host=HOST,
        port=PORT,
        reload=True,
        log_level="info",
    )
