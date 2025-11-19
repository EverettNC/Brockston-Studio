# BROCKSTON Studio - Quick Start

Get up and running in 60 seconds.

---

## Installation

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the server (using the startup script)
./start.sh

# OR start manually
python -m uvicorn backend.main:app --host 127.0.0.1 --port 5055 --reload
```

## First Run

1. **Open browser**: http://localhost:5055

2. **Open a file**:
   - Enter a file path in the top bar
   - Examples:
     - `test.py` (relative to workspace)
     - `/absolute/path/to/file.js`
   - Click "Open" or press Enter

3. **Ask BROCKSTON a question**:
   - Type in the instruction box: "Explain what this code does"
   - Click "Ask BROCKSTON"
   - See response in chat panel

4. **Request code improvements**:
   - Type instruction: "Refactor for clarity and add comments"
   - Click "Suggest Fix"
   - Review changes in modal
   - Click "Apply Changes"

5. **Save your work**:
   - Click "Save" or press `Ctrl+S`

---

## Environment Setup (Optional)

Create a `.env` file or export variables:

```bash
export BROCKSTON_BASE_URL=http://localhost:6006  # Your BROCKSTON endpoint
export BROCKSTON_WORKSPACE=/path/to/your/code    # Where your code lives
```

If `BROCKSTON_BASE_URL` is not set, the app runs in **mock mode** (useful for testing UI).

---

## Keyboard Shortcuts

- **Enter** (in file path field) → Open file
- **Ctrl+S** / **Cmd+S** → Save file

---

## Troubleshooting

**"Failed to communicate with BROCKSTON"**
- BROCKSTON model is not running or not accessible
- Check `BROCKSTON_BASE_URL` environment variable
- The app will work in mock mode if BROCKSTON is unavailable

**"Path is outside workspace root"**
- File path is outside the configured workspace directory
- Set `BROCKSTON_WORKSPACE` to a parent directory
- Or use absolute paths

**Monaco Editor doesn't load**
- Check internet connection (Monaco loads from CDN)
- Check browser console for errors

---

## What's Next?

Check out the full [README.md](README.md) for:
- Complete API documentation
- Architecture details
- Configuration options
- Development guide

---

**Happy coding with BROCKSTON!**
