# BROCKSTON Studio

**Local code workbench powered by BROCKSTON.**

BROCKSTON Studio lets you open a file, edit code, and ask BROCKSTON to explain, refactor, or repair it – with no external models, no GitHub billing, and no cloud dependencies.

---

## Features

### v1 Capabilities

- **Open and edit files** from your local workspace
- **Chat with BROCKSTON** about your code - ask questions, get explanations
- **Request code improvements** - BROCKSTON proposes full rewrites with explanations
- **Review and apply changes** with a side-by-side comparison view
- **Monaco Editor** integration (same engine as VS Code)
- **No external dependencies** - runs entirely on localhost

### Out of Scope (for now)

- Multi-file project navigation
- Git integration
- Test runners and linters
- Fine-grained code patching
- User accounts / authentication

---

## Architecture

### Components

1. **Backend**: FastAPI (Python) running on `http://localhost:5055`
2. **Frontend**: Single-page web app with Monaco Editor
3. **BROCKSTON Bridge**: Abstraction layer for communicating with the BROCKSTON model

### Directory Structure

```
BROCKSTON-Studio/
├── backend/
│   ├── __init__.py
│   ├── main.py              # FastAPI application
│   ├── brockston_client.py  # BROCKSTON communication layer
│   ├── models.py            # Pydantic request/response models
│   └── config.py            # Configuration and path resolution
├── frontend/
│   ├── index.html           # Main UI
│   ├── app.js               # Frontend logic
│   └── styles.css           # Styling
├── requirements.txt
└── README.md
```

---

## Installation

### Prerequisites

- **Python 3.10+**
- **BROCKSTON model** accessible at `http://localhost:6006` (or configured endpoint)

### Setup

1. **Clone the repository**

   ```bash
   git clone <repository-url>
   cd Brockston-Studio
   ```

2. **Install Python dependencies**

   ```bash
   pip install -r requirements.txt
   ```

3. **Configure environment** (optional)

   Create a `.env` file or export environment variables:

   ```bash
   export BROCKSTON_HOST=127.0.0.1        # Server host (default: 127.0.0.1)
   export BROCKSTON_PORT=5055              # Server port (default: 5055)
   export BROCKSTON_BASE_URL=http://localhost:6006  # BROCKSTON endpoint
   export BROCKSTON_WORKSPACE=/path/to/your/code    # Workspace root
   ```

   If `BROCKSTON_BASE_URL` is not set, the app runs in **mock mode** for testing.

---

## Usage

### Starting the Server

Run the backend server:

```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 5055 --reload
```

Or use the built-in development server:

```bash
python -m backend.main
```

### Opening the UI

Navigate to **http://localhost:5055** in your browser.

### Workflow

1. **Open a file**
   - Enter a file path (absolute or relative to workspace)
   - Click "Open" or press Enter
   - File loads into Monaco Editor

2. **Ask BROCKSTON a question**
   - Type your question in the instruction box
   - Click "Ask BROCKSTON"
   - BROCKSTON's response appears in the chat panel

3. **Request code improvements**
   - Type an instruction like "Refactor for clarity" or "Add error handling"
   - Click "Suggest Fix"
   - Review the proposed changes in the comparison modal
   - Click "Apply Changes" to update the editor

4. **Save changes**
   - Click "Save" or press `Ctrl+S` (or `Cmd+S` on Mac)
   - File is written to disk

---

## API Documentation

### File Operations

#### `GET /api/files/open`

**Query Parameters:**
- `path`: File path (absolute or workspace-relative)

**Response:**
```json
{
  "path": "/absolute/path/to/file.py",
  "content": "file contents as string"
}
```

#### `POST /api/files/save`

**Request Body:**
```json
{
  "path": "/path/to/file.py",
  "content": "updated file contents"
}
```

**Response:**
```json
{
  "status": "ok",
  "path": "/absolute/path/to/file.py"
}
```

### BROCKSTON Operations

#### `POST /api/brockston/chat`

**Request Body:**
```json
{
  "messages": [
    {"role": "system", "content": "You are BROCKSTON..."},
    {"role": "user", "content": "Explain this function"}
  ],
  "context": {
    "path": "/path/to/file.py",
    "code": "current file contents"
  }
}
```

**Response:**
```json
{
  "reply": "BROCKSTON's explanation"
}
```

#### `POST /api/brockston/suggest_fix`

**Request Body:**
```json
{
  "instruction": "Refactor for clarity",
  "path": "/path/to/file.py",
  "code": "current file contents"
}
```

**Response:**
```json
{
  "proposed_code": "full rewritten version",
  "summary": "Brief description of changes"
}
```

---

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `BROCKSTON_HOST` | `127.0.0.1` | Server bind address |
| `BROCKSTON_PORT` | `5055` | Server port |
| `BROCKSTON_BASE_URL` | `http://localhost:6006` | BROCKSTON model endpoint |
| `BROCKSTON_WORKSPACE` | `~/Code` | Workspace root directory |

### Security

- All file operations are restricted to the configured `BROCKSTON_WORKSPACE` directory
- Paths outside the workspace are rejected with a 403 error
- Server runs on localhost only (127.0.0.1)
- No authentication in v1 (single-user, local development)

---

## Development

### Running in Development Mode

```bash
# With auto-reload
python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 5055
```

### Mock Mode (No BROCKSTON Required)

If `BROCKSTON_BASE_URL` is not configured or BROCKSTON is unavailable, the app runs in mock mode:

- Chat responses include a `[MOCK BROCKSTON RESPONSE]` prefix
- Suggested fixes add a mock comment to the code
- Useful for frontend development and testing

### Extending BROCKSTON Client

To add support for different model backends, modify `backend/brockston_client.py`:

```python
class BrockstonClient:
    async def chat(self, messages, context=None):
        # Implement your model communication here
        pass

    async def suggest_fix(self, code, instruction, path=None):
        # Implement your code suggestion logic here
        pass
```

---

## Troubleshooting

### "Failed to communicate with BROCKSTON"

- Ensure BROCKSTON is running at the configured `BROCKSTON_BASE_URL`
- Check that the endpoint is accessible: `curl http://localhost:6006/health`
- Review backend logs for detailed error messages

### "Path is outside workspace root"

- The requested file path is outside the configured workspace
- Update `BROCKSTON_WORKSPACE` environment variable
- Or use a path relative to the current workspace

### Monaco Editor Not Loading

- Check browser console for JavaScript errors
- Ensure internet connection (Monaco loads from CDN)
- Try clearing browser cache

---

## Future Enhancements

- Multi-file project tree navigation
- Git integration (status, diff, commit)
- Inline code suggestions (LSP-style)
- Multiple model support (BROCKSTON, Derek, Sierra)
- Terminal integration
- Test runner and linter integration

---

## License

Proprietary - BROCKSTON Studio

---

## Credits

Built with:
- [FastAPI](https://fastapi.tiangolo.com/) - Modern Python web framework
- [Monaco Editor](https://microsoft.github.io/monaco-editor/) - VS Code's editor engine
- [BROCKSTON](https://brockston.ai) - Reasoning model by Everett

**Made with ruthless efficiency.**
