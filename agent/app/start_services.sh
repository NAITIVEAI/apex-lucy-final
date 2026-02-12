#!/bin/bash
# Start both the health check server and Chainlit app for Azure Container Apps
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

# Give health server a moment to start
sleep 2

# Start Chainlit app (runs in foreground)
echo "💬 Starting Chainlit app on port 8000..."
chainlit run apex.py --port 8000

# If Chainlit exits, kill health server
kill $HEALTH_PID 2>/dev/null || true
