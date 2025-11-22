import os
import subprocess
import pty
import select
import json
import logging
import asyncio
from pathlib import Path
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
async def list_files(path: str = ""):
    """Lists files in the specified directory (excluding hidden/system)"""
    try:
        # Security: prevent directory traversal
        if ".." in path or path.startswith("/"):
            raise HTTPException(status_code=400, detail="Invalid path")
        
        # Determine directory to list
        if path:
            root_dir = path
        else:
            root_dir = "."
        
        files = []
        for item in os.listdir(root_dir):
            if not item.startswith(".") and not item.startswith("__"):
                full_path = os.path.join(root_dir, item)
                if os.path.isfile(full_path) or os.path.isdir(full_path):
                    kind = "folder" if os.path.isdir(full_path) else "file"
                    files.append({"name": item, "type": kind})
        
        return {"files": files, "path": path}
    except Exception as e:
        logger.error(f"File Listing Error: {e}")
        return {"files": [], "path": path}

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

# --- TERMINAL WEBSOCKET (FIXED VERSION) ---
@app.websocket("/ws/terminal")
async def websocket_terminal(websocket: WebSocket):
    await websocket.accept()
    logger.info("Terminal WebSocket connection accepted")

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

    os.close(slave_fd)  # Close slave in parent
    logger.info(f"Shell process started with PID: {process.pid}")

    # Task for reading from PTY and sending to websocket
    async def read_from_pty():
        """Read output from the shell and send to websocket"""
        try:
            while True:
                # Non-blocking check for data
                r, _, _ = select.select([master_fd], [], [], 0.1)
                if master_fd in r:
                    try:
                        output = os.read(master_fd, 10240).decode('utf-8', errors='ignore')
                        if output:
                            await websocket.send_text(json.dumps({"type": "output", "data": output}))
                    except OSError as e:
                        logger.error(f"PTY read error: {e}")
                        break
                else:
                    # Yield control to event loop
                    await asyncio.sleep(0.01)
                    
                # Check if process is still alive
                if process.poll() is not None:
                    logger.info("Shell process terminated")
                    break
        except Exception as e:
            logger.error(f"Error in read_from_pty: {e}")
        finally:
            logger.info("read_from_pty task finished")

    # Task for receiving from websocket and writing to PTY
    async def write_to_pty():
        """Receive input from websocket and write to shell"""
        try:
            while True:
                data = await websocket.receive_text()
                
                # Handle empty keepalive messages
                if not data or data == '""':
                    continue
                    
                try:
                    payload = json.loads(data)
                    if payload.get("type") == "input":
                        cmd = payload.get("data", "")
                        os.write(master_fd, cmd.encode())
                    elif payload.get("type") == "resize":
                        # Handle terminal resize if needed in the future
                        pass
                except json.JSONDecodeError:
                    logger.warning(f"Invalid JSON received: {data}")
                except OSError as e:
                    logger.error(f"PTY write error: {e}")
                    break
        except WebSocketDisconnect:
            logger.info("WebSocket disconnected")
        except Exception as e:
            logger.error(f"Error in write_to_pty: {e}")
        finally:
            logger.info("write_to_pty task finished")

    # Run both tasks concurrently
    try:
        await asyncio.gather(
            read_from_pty(),
            write_to_pty(),
            return_exceptions=True
        )
    except Exception as e:
        logger.error(f"Terminal session error: {e}")
    finally:
        # Cleanup
        try:
            process.terminate()
            process.wait(timeout=1)
        except:
            process.kill()
        try:
            os.close(master_fd)
        except:
            pass
        logger.info("Terminal session cleaned up")

# --- STATIC FILES SERVING (FIXED WITH ABSOLUTE PATH) ---
# Get the absolute path to the frontend directory
backend_dir = Path(__file__).parent
frontend_dir = backend_dir.parent / "frontend"

logger.info(f"Serving static files from: {frontend_dir}")

app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
