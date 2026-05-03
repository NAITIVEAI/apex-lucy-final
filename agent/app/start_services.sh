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

cleanup() {
    kill "$HEALTH_PID" 2>/dev/null || true
    [ -n "${HTTP_PID:-}" ] && kill "$HTTP_PID" 2>/dev/null || true
}
trap cleanup EXIT

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

if [ -n "$HTTP_PID" ]; then
    echo "🔍 Checking FastAPI HTTP wrapper health..."
    HTTP_HEALTH_URL="http://127.0.0.1:${LUCY_HTTP_PORT}/agent/health"
    HTTP_READY="false"
    for _ in $(seq 1 15); do
        if ! kill -0 "$HTTP_PID" 2>/dev/null; then
            echo "❌ FastAPI HTTP wrapper exited before becoming healthy."
            exit 1
        fi
        if HTTP_HEALTH_URL="$HTTP_HEALTH_URL" python - <<'PY'
import os
import sys
import urllib.request

try:
    with urllib.request.urlopen(os.environ["HTTP_HEALTH_URL"], timeout=1) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
        then
            echo "✅ FastAPI HTTP wrapper is healthy."
            HTTP_READY="true"
            break
        fi
        sleep 1
    done
    if [ "$HTTP_READY" != "true" ]; then
        echo "❌ FastAPI HTTP wrapper did not become healthy at ${HTTP_HEALTH_URL}."
        exit 1
    fi
fi

if [ "${LUCY_CHAINLIT_ENABLED:-true}" != "true" ]; then
    if [ -z "$HTTP_PID" ]; then
        echo "❌ LUCY_CHAINLIT_ENABLED=false requires LUCY_HTTP_ENABLED=true."
        exit 1
    fi
    echo "🌐 Chainlit disabled; running gateway HTTP wrapper as foreground service."
    wait "$HTTP_PID"
    exit $?
fi

# Start Chainlit app (runs in foreground)
echo "💬 Starting Chainlit app on port 8000..."
chainlit run apex.py --port 8000
