#!/bin/bash
# Start health server, optional FastAPI HTTP wrapper, and Chainlit app
# for Azure Container Apps.
set -euo pipefail

echo "🚀 Starting Lucy AI Assistant services..."

# Run startup verification first
echo "🔍 Running startup verification..."
if ! python startup_verification.py; then
    echo "❌ Startup verification failed. Refusing to start services."
    echo "   To allow temporary fallback, set ALLOW_STORAGE_FALLBACK=true."
    exit 1
fi

# Check if callback_system.py exists
if [ ! -f "/app/callback_system.py" ]; then
    echo "❌ CRITICAL ERROR: callback_system.py not found in /app!"
    ls -la /app/*.py | head -20
    exit 1
else
    echo "✅ callback_system.py found in /app"
fi

# Start health check server in background
echo "🏥 Starting health check server on port 8080..."
python health_server.py &
HEALTH_PID=$!

# Optionally start the FastAPI HTTP wrapper for Foundry AI Gateway registration.
# Disabled with LUCY_HTTP_ENABLED=false (e.g. for emergency rollback). Default on.
HTTP_PID=""
if [ "${LUCY_HTTP_ENABLED:-true}" = "true" ]; then
    LUCY_HTTP_PORT="${LUCY_HTTP_PORT:-8002}"
    echo "🌐 Starting FastAPI HTTP wrapper on port ${LUCY_HTTP_PORT}..."
    python -m uvicorn lucy_core.http_app:create_app \
        --factory \
        --host 0.0.0.0 \
        --port "${LUCY_HTTP_PORT}" &
    HTTP_PID=$!
fi

# Give background services a moment to start
sleep 2

# Start Chainlit app (runs in foreground)
echo "💬 Starting Chainlit app on port 8000..."
chainlit run apex.py --port 8000

# If Chainlit exits, kill background services
kill "$HEALTH_PID" 2>/dev/null || true
[ -n "$HTTP_PID" ] && kill "$HTTP_PID" 2>/dev/null || true
