#!/bin/bash
# Start Agent Portal - works in both Docker and local environments
set -euo pipefail

is_enabled() {
    local value="${1:-}"
    case "${value,,}" in
        1|true|yes|on) return 0 ;;
        *) return 1 ;;
    esac
}

echo "🚀 Starting Apex Agent Portal..."
echo "📅 Current time: $(date)"
echo "🐍 Python version: $(python3 --version 2>&1)"
echo "📍 Working directory: $(pwd)"

# Check if we're in Docker (no .venv needed)
if [ -f /.dockerenv ] || [ -n "$DOCKER_CONTAINER" ]; then
    echo "🐳 Running in Docker container"
else
    # Local environment - check for virtual environment
    if [ -d ".venv" ]; then
        echo "🔧 Activating virtual environment..."
        source .venv/bin/activate
    fi
fi

# Check if Azure packages are installed
echo "🔍 Checking critical imports..."
python3 -c "
import sys
sys.path.insert(0, '.')
try:
    from azure.data.tables import TableServiceClient
    print('✅ Azure SDK available')
except ImportError as e:
    print('⚠️  Azure SDK not available:', e)

try:
    from callback_system import callback_system
    if callback_system:
        print('✅ Callback system initialized')
    else:
        print('⚠️  Callback system not initialized (check Azure Storage config)')
except ImportError as e:
    print('❌ Failed to import callback_system:', e)
    print('   Agent portal will have limited functionality')

try:
    import agent_portal
    print('✅ Agent portal module available')
except ImportError as e:
    print('❌ Failed to import agent_portal:', e)
    exit(1)
"

# Check for Azure Storage configuration
if [ -n "$AZURE_STORAGE_CONNECTION_STRING" ]; then
    echo "✅ Azure Storage connection string found"
else
    REQUIRE_STORAGE="${REQUIRE_AZURE_STORAGE_CONNECTION_STRING:-true}"
    ALLOW_FALLBACK="${ALLOW_STORAGE_FALLBACK:-false}"
    if is_enabled "$REQUIRE_STORAGE" && ! is_enabled "$ALLOW_FALLBACK"; then
        echo "❌ AZURE_STORAGE_CONNECTION_STRING is required by startup policy."
        echo "   Set ALLOW_STORAGE_FALLBACK=true only for controlled exceptions."
        exit 1
    fi
    echo "⚠️  Azure Storage connection string not found - running with fallback mode"
fi

# Set default port if not specified
export AGENT_PORTAL_PORT=${AGENT_PORTAL_PORT:-8001}
export LOG_LEVEL=${LOG_LEVEL:-info}
export PYTHONUNBUFFERED=1

echo "🌐 Starting Agent Portal on port $AGENT_PORTAL_PORT..."
echo "📊 Conversation history functionality enabled"

# Start the agent portal with unbuffered output
exec python3 -u agent_portal.py
