#!/bin/bash

# BROCKSTON Studio Startup Script

echo "========================================="
echo "  BROCKSTON Studio"
echo "  Local Code Workbench"
echo "========================================="
echo ""

# Check if Python is available
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is not installed"
    exit 1
fi

# Check if dependencies are installed
if ! python3 -c "import fastapi" &> /dev/null; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
fi

# Load .env file if it exists
if [ -f .env ]; then
    echo "Loading environment variables from .env"
    export $(grep -v '^#' .env | grep -v '^$' | xargs)
fi

# Set default environment variables if not already set
export BROCKSTON_HOST="${BROCKSTON_HOST:-127.0.0.1}"
export BROCKSTON_PORT="${BROCKSTON_PORT:-7777}"
export BROCKSTON_BASE_URL="${BROCKSTON_BASE_URL:-http://localhost:6006}"

echo "Configuration:"
echo "  Host: $BROCKSTON_HOST"
echo "  Port: $BROCKSTON_PORT"
echo "  BROCKSTON URL: $BROCKSTON_BASE_URL"
echo "  OpenAI Key: ${OPENAI_API_KEY:0:20}..." 
echo ""
echo "Starting server..."
echo "Open http://localhost:$BROCKSTON_PORT in your browser"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Start the server
python3 -m uvicorn backend.main:app \
    --host "$BROCKSTON_HOST" \
    --port "$BROCKSTON_PORT" \
    --reload
