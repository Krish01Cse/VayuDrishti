#!/usr/bin/env bash
# =============================================================================
# start_backend.sh — Launch VayuDrishti FastAPI backend (Mac/Linux/WSL)
# Usage: ./start_backend.sh
# =============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/backend"

# Determine python command
if command -v python3 >/dev/null 2>&1; then
    PY_CMD="python3"
elif command -v python >/dev/null 2>&1; then
    PY_CMD="python"
else
    echo "Error: Python 3 is not installed or not in PATH."
    exit 1
fi

echo "🚀 Starting VayuDrishti backend..."
echo "   URL: http://127.0.0.1:8000"
echo "   Docs: http://127.0.0.1:8000/docs"
echo "   Health: http://127.0.0.1:8000/health"
echo "   Press Ctrl+C to stop."
echo ""

$PY_CMD -m uvicorn main:app --reload --port 8000
