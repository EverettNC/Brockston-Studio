import os
import subprocess
import pty
import select
import json
import logging
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

# Import your AI client (ensure ai_client.py is in the same folder)
try:
    from .ai_client import get_ai_response
except ImportError:
    # Fallback for direct execution
    from ai_client import get_ai_response

# Setup Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BrockstonStudio")

app = FastAPI()

# --- CORS POLICY (The Fix for "Failed to Fetch") ---
origins = [
    "http://localhost:7777",
    "http://127.0.0.1:7777",
    "*"  # Open for dev speed
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- DATA MODELS ---
class ChatRequest(BaseModel):
    message: str

# --- API ENDPOINTS ---

@app.get("/api/health")
async def health_check():
    return {"status": "10 Toes Down", "system": "Online"}

@app.post("/api/chat")
async def chat_endpoint(request: ChatRequest):
    """Direct line to OpenAI via ai_client.py"""
    try:
        logger.info(f"AI Request received: {request.message}")
        response_text = get_ai_response(request.message)
        return {"response": response_text}
    except Exception as e:
        logger.error(f"AI Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/files")
async def list_files():
    """Lists files in the current directory (excluding hidden/system)"""
    try:
        root_dir = "."
        files = []
        for item in os.listdir(root_dir):
            if not item.startswith(".") and not item.startswith("__"):
                if os.path.isfile(item) or os.path.isdir(item):
                     # Simple categorization
                    kind = "folder" if os.path.isdir(item) else "file"
                    files.append({"name": item, "type": kind})
        return {"files": files}
    except Exception as e:
        logger.error(f"File Listing Error: {e}")
        return {"files": []}

@app.get("/api/read_file")
async def read_file(filename: str):
    """Reads content of a file for the editor"""
    try:
        # Security: Basic prevention of directory traversal
        if ".." in filename or filename.startswith("/"):
             raise HTTPException(status_code=400, detail="Invalid filename")
        
        with open(filename, "r", encoding="utf-8") as f:
            content = f.read()
        return {"content": content, "filename": filename}
    except Exception as e:
        logger.error(f"Read Error: {e}")
        raise HTTPException(status_code=404, detail="File not found or unreadable")

# --- TERMINAL WEBSOCKET (The "Scrubber" Backend) ---
@app.websocket("/ws/terminal")
async def websocket_terminal(websocket: WebSocket):
    await websocket.accept()
    
    # Create a pseudo-terminal
    master_fd, slave_fd = pty.openpty()
    
    # Start a shell (zsh if available, else bash)
    shell = os.environ.get("SHELL", "/bin/bash")
    
    # Run the process attached to the PTY
    process = subprocess.Popen(
        [shell],
        preexec_fn=os.setsid,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        universal_newlines=True
    )
    
    os.close(slave_fd) # Close slave in parent

    try:
        while True:
            # Wait for input from websocket or output from pty
            # 0.1 timeout for responsiveness
            await websocket.send_text("") # Keepalive ping mechanism if needed
            
            # Check for output from the shell
            r, w, x = select.select([master_fd], [], [], 0.01)
            if master_fd in r:
                output = os.read(master_fd, 10240).decode('utf-8', errors='ignore')
                if output:
                    await websocket.send_text(json.dumps({"type": "output", "data": output}))

            # Check for input from the frontend (non-blocking via asyncio technically, 
            # but here we rely on the receive_text in a loop logic usually. 
            # To make this truly async concurrent, we'd separate read/write tasks.
            # For simplicity/stability in this monolith, we use a slightly different approach below)
            
            # REVISION: The simple loop blocks. We need asyncio gather or specific logic.
            # Let's switch to a robust reader/writer task structure.
            break 
    except Exception:
        pass
    
    # --- Robust Async Handler ---
    # Re-accepting logic for clean separation
    
    async def read_from_pty():
        while True:
            try:
                r, _, _ = select.select([master_fd], [], [], 0.1)
                if master_fd in r:
                    output = os.read(master_fd, 10240).decode('utf-8', errors='ignore')
                    if output:
                        await websocket.send_text(json.dumps({"type": "output", "data": output}))
                else:
                    # Brief sleep to yield control
                    import asyncio
                    await asyncio.sleep(0.01)
            except Exception as e:
                break

    async def write_to_pty():
        while True:
            try:
                data = await websocket.receive_text()
                payload = json.loads(data)
                if payload.get("type") == "input":
                    cmd = payload.get("data")
                    os.write(master_fd, cmd.encode())
                elif payload.get("type") == "resize":
                    # Handle resize if needed, skipping for now
                    pass
            except WebSocketDisconnect:
                process.terminate()
                break
            except Exception:
                break

    import asyncio
    await asyncio.gather(read_from_pty(), write_to_pty())

# --- STATIC FILES SERVING ---
# This serves the frontend directory at root
app.mount("/", StaticFiles(directory="../frontend", html=True), name="frontend")
