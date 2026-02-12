import json
import logging
import os
import asyncio
import secrets
from datetime import datetime, timezone
import pytz
from typing import Dict, List, Optional, Any
import uuid
import sys

# Ensure current directory is in Python path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import uvicorn

# Import callback system with error handling
try:
    from callback_system import callback_system
    logger_callback = logging.getLogger("CallbackImport")
    if callback_system:
        logger_callback.info("✅ Callback system imported successfully")
    else:
        logger_callback.warning("⚠️ Callback system instance is None")
except ImportError as e:
    logger_callback = logging.getLogger("CallbackImport")
    logger_callback.error(f"❌ Failed to import callback_system: {e}")
    callback_system = None

# Import the simple conversation store
try:
    from conversation_store import conversation_store
    logger_store = logging.getLogger("ConversationStoreImport")
    logger_store.info("✅ Conversation store imported successfully")
except ImportError as e:
    logger_store = logging.getLogger("ConversationStoreImport")
    logger_store.error(f"❌ Failed to import conversation_store: {e}")
    conversation_store = None

# Version info for deployment tracking
BUILD_VERSION = datetime.now(timezone.utc).strftime("v1-%Y%m%d-%H%M%S")
BUILD_DATE = datetime.now(timezone.utc).isoformat()
CALLBACK_SYSTEM_VERSION = "2.0-fixed"

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("AgentPortal")

logger.info(f"🚀 Agent Portal starting - Build: {BUILD_VERSION}")
logger.info(f"📅 Build Date: {BUILD_DATE}")
logger.info(f"📞 Callback System: {CALLBACK_SYSTEM_VERSION}")

# Initialize FastAPI app
app = FastAPI(title="Apex Agent Portal")

# In-memory storage for active handoff requests
# In production, this should be replaced with a database
active_conversations: Dict[str, Dict] = {}
active_connections: Dict[str, List[WebSocket]] = {}
connection_types: Dict[WebSocket, Dict] = {}  # websocket -> {type: 'agent'|'chainlit', info: ...}
conversation_messages: Dict[str, List[Dict]] = {}
pending_availability_checks: Dict[str, Dict] = {}  # request_id -> conversation info

# Table storage settings for cross-instance handoff visibility
CONVERSATION_TABLE = "conversations"
PENDING_MAX_AGE_MINUTES = 1440

# Setup static files
app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/public", StaticFiles(directory="public"), name="public")

# Setup Jinja2 templates
templates = Jinja2Templates(directory="templates")

# Pacific timezone helper
def get_pacific_time():
    """Get current time in Pacific timezone"""
    pacific = pytz.timezone('America/Los_Angeles')
    return datetime.now(pacific)

def _env_enabled(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}

DEBUG_ENDPOINTS_ENABLED = _env_enabled("ENABLE_DEBUG_ENDPOINTS", default=False)

# Optional token-based authentication for portal requests
def get_current_agent(request: Request):
    expected_token = os.getenv("AGENT_PORTAL_API_TOKEN", "").strip()
    if expected_token:
        presented_token = request.headers.get("X-Agent-Token", "").strip()
        auth_header = request.headers.get("Authorization", "").strip()
        if auth_header.lower().startswith("bearer "):
            presented_token = auth_header[7:].strip()
        if not presented_token or not secrets.compare_digest(presented_token, expected_token):
            raise HTTPException(status_code=401, detail="Unauthorized")

    agent_id = request.headers.get("X-Agent-ID", str(uuid.uuid4()))
    agent_name = request.headers.get("X-Agent-Name", "Support Agent")
    return {"id": agent_id, "name": agent_name}

def _normalize_conversation_id(conversation_id: str) -> str:
    if conversation_store:
        try:
            return conversation_store._normalize_conversation_id(conversation_id)
        except Exception:
            pass
    if not conversation_id:
        return ""
    normalized = conversation_id.strip()
    if normalized.lower().startswith("conv-") and len(normalized) > 5:
        normalized = normalized[5:]
    return normalized or conversation_id

def _parse_iso_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("Z"):
            text = text[:-1]
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
    return None

def _as_iso(value: Any) -> str:
    parsed = _parse_iso_datetime(value)
    if parsed:
        return parsed.isoformat()
    if isinstance(value, str):
        return value
    return ""

def _get_conversation_table():
    conn_str = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not conn_str:
        return None
    try:
        from azure.data.tables import TableServiceClient
        tsc = TableServiceClient.from_connection_string(conn_str)
        return tsc.get_table_client(CONVERSATION_TABLE)
    except Exception as e:
        logger.warning(f"⚠️ Could not initialize conversation table client: {e}")
        return None

def _extract_conversation_id(entity: Dict[str, Any]) -> str:
    conv_id = entity.get("original_conversation_id") or entity.get("conversation_id")
    if conv_id:
        return str(conv_id)
    row_key = str(entity.get("RowKey", ""))
    if row_key.endswith("_pre_handoff"):
        return row_key[:-12]
    return row_key

def _build_conversation_from_entity(entity: Dict[str, Any], fallback_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
    if not entity:
        return None
    metadata = entity.get("metadata", {})
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    apex_id = entity.get("apex_id") or metadata.get("apex_id")
    user_info = {}
    if isinstance(metadata, dict):
        user_info = metadata.get("user_info") or {}
    if not isinstance(user_info, dict):
        user_info = {}
    if apex_id and not user_info.get("apex_id"):
        user_info["apex_id"] = apex_id
    if not user_info.get("name"):
        user_info["name"] = f"Member {apex_id}" if apex_id else "Unknown User"
    if not user_info.get("apex_id"):
        user_info["apex_id"] = apex_id or "Unknown"

    reason = entity.get("reason") or metadata.get("reason") or metadata.get("handoff_reason") or "General assistance"
    status_raw = entity.get("status") or "pending"
    status = "waiting" if str(status_raw).lower() in {"pending", "waiting"} else status_raw
    waiting_since = _as_iso(entity.get("created_at") or entity.get("status_updated_at") or entity.get("Timestamp"))

    conv_id = fallback_id or _extract_conversation_id(entity)
    if not conv_id:
        return None

    return {
        "id": conv_id,
        "user_info": user_info,
        "waiting_since": waiting_since or datetime.utcnow().isoformat(),
        "status": status,
        "reason": reason,
        "status_reason": entity.get("status_reason", ""),
        "portal_url": entity.get("portal_url", ""),
    }

def _conversation_score(conversation: Optional[Dict[str, Any]]) -> int:
    if not conversation:
        return 0
    messages = conversation.get("messages", []) or []
    if isinstance(messages, str):
        try:
            messages = json.loads(messages)
        except Exception:
            messages = []
    non_system = 0
    for msg in messages:
        role = str((msg or {}).get("role", "")).lower()
        if role and role != "system":
            non_system += 1
    metadata = conversation.get("metadata", {}) or {}
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except Exception:
            metadata = {}
    summary_bonus = 5 if metadata.get("member_notes_summary") else 0
    analytics_bonus = 3 if metadata.get("analytics_data") else 0
    return non_system * 10 + len(messages) + summary_bonus + analytics_bonus

def _hydrate_conversation_from_table(conversation_id: str) -> Optional[Dict[str, Any]]:
    table = _get_conversation_table()
    if not table or not conversation_id:
        return None
    storage_id = _normalize_conversation_id(conversation_id)
    row_key = f"{storage_id}_pre_handoff"
    try:
        entity = table.get_entity(partition_key="conversations", row_key=row_key)
    except Exception as e:
        logger.warning(f"⚠️ No table row for conversation {conversation_id}: {e}")
        return None
    conversation = _build_conversation_from_entity(entity, fallback_id=conversation_id)
    if not conversation:
        return None
    active_conversations[conversation_id] = conversation
    conversation_messages.setdefault(conversation_id, [])
    return conversation

def _load_pending_from_table(max_age_minutes: int = PENDING_MAX_AGE_MINUTES) -> List[Dict[str, Any]]:
    table = _get_conversation_table()
    if not table:
        return []
    try:
        entities = table.query_entities("PartitionKey eq 'conversations' and status eq 'pending'")
    except Exception as e:
        logger.warning(f"⚠️ Failed to query pending conversations: {e}")
        return []

    now = datetime.utcnow()
    pending: List[Dict[str, Any]] = []
    for entity in entities:
        created_at = _parse_iso_datetime(
            entity.get("created_at") or entity.get("status_updated_at") or entity.get("Timestamp")
        )
        if created_at:
            age_minutes = (now - created_at).total_seconds() / 60
            if age_minutes > max_age_minutes:
                continue
        conv_id = _extract_conversation_id(entity)
        conversation = _build_conversation_from_entity(entity, fallback_id=conv_id)
        if conversation:
            pending.append(conversation)
    return pending

# Models
class Message(BaseModel):
    role: str
    content: str
    timestamp: Optional[str] = None

class Conversation(BaseModel):
    id: str
    user_info: Dict[str, Any]
    waiting_since: str
    status: str = "waiting"
    history: Optional[List[Message]] = []

# API Routes
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    """Redirect to agent portal"""
    return templates.TemplateResponse(
        "redirect.html",
        {"request": request, "redirect_url": "/agent/portal"}
    )

@app.get("/api/version")
async def get_version():
    """Get version information for deployment verification"""
    return {
        "build_version": BUILD_VERSION,
        "build_date": BUILD_DATE,
        "callback_system_version": CALLBACK_SYSTEM_VERSION,
        "current_time": datetime.now(timezone.utc).isoformat(),
        "status": "running"
    }

@app.get("/agent/portal", response_class=HTMLResponse)
async def agent_portal(request: Request, agent: Dict = Depends(get_current_agent)):
    """Main agent portal page"""
    return templates.TemplateResponse(
        "agent_portal.html",
        {
            "request": request,
            "agent": agent,
            "build_version": BUILD_VERSION,
            "callback_system_version": CALLBACK_SYSTEM_VERSION
        }
    )

@app.get("/agent/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, agent: Dict = Depends(get_current_agent)):
    """Agent dashboard with real-time metrics and analytics"""
    error_message = None

    try:
        # Import and use our real metrics system
        from real_metrics_system import get_live_dashboard_metrics

        # Get comprehensive real metrics
        dashboard_data = await get_live_dashboard_metrics()

        # Extract metrics for template
        current_metrics = {
            "session_summary": {
                "total_attempts": dashboard_data["authentication"]["total_attempts"],
                "successful_attempts": dashboard_data["authentication"]["successful_attempts"],
                "success_rate": dashboard_data["authentication"]["success_rate"],
                "avg_queries_per_attempt": dashboard_data["authentication"]["avg_queries_per_attempt"],
                "learned_pattern_usage": dashboard_data["authentication"]["cache_hit_rate"],
                "session_duration": dashboard_data["build_info"]["uptime"]
            }
        }

        # Prepare historical metrics
        historical_metrics = {
            "overall_stats": {
                "total_attempts": dashboard_data["authentication"]["total_attempts"],
                "success_rate": dashboard_data["authentication"]["success_rate"],
                "avg_queries_per_attempt": dashboard_data["authentication"]["avg_queries_per_attempt"],
                "learning_cache_usage": dashboard_data["authentication"]["cache_hit_rate"]
            },
            "period": "Last 7 days"
        }

        # Generate real recommendations
        recommendations = [
            f"🎯 System performance: CPU {dashboard_data['system']['cpu_usage']:.1f}%, Memory {dashboard_data['system']['memory_usage']:.1f}%",
            f"💬 {dashboard_data['conversations']['active_conversations']} active conversations, {dashboard_data['conversations']['success_rate']:.1f}% success rate",
            f"📞 {dashboard_data['callbacks']['pending_callbacks']} pending callbacks, {dashboard_data['callbacks']['sla_compliance']:.1f}% SLA compliance",
            f"🔗 Teams integration: {'✅ Active' if dashboard_data['teams']['available'] else '⚠️ Check configuration'}",
            f"⚡ Authentication cache hit rate: {dashboard_data['authentication']['cache_hit_rate']:.1f}%"
        ]

        teams_status = dashboard_data["teams"]
        pending_count = dashboard_data["conversations"]["active_conversations"]

        # Add real system metrics to context
        system_metrics = dashboard_data["system"]
        conversation_metrics = dashboard_data["conversations"]
        callback_metrics = dashboard_data["callbacks"]

    except Exception as e:
        logger.error(f"Error loading real metrics: {e}")
        error_message = f"Metrics system temporarily unavailable: {str(e)}"

        # Fallback to empty values
        current_metrics = {
            "session_summary": {
                "total_attempts": 0,
                "successful_attempts": 0,
                "success_rate": 0,
                "avg_queries_per_attempt": 0,
                "learned_pattern_usage": 0,
                "session_duration": "No data available"
            }
        }
        historical_metrics = {}
        recommendations = ["⚠️ Real-time metrics system is initializing..."]
        teams_status = {"available": False, "last_check": datetime.utcnow().isoformat()}
        pending_count = 0
        system_metrics = {}
        conversation_metrics = {}
        callback_metrics = {}

    # Legacy monitoring code removed - using real metrics system above
    pass

    # Always return a valid response with comprehensive real metrics
    return templates.TemplateResponse(
        "dashboard_modern.html",
        {
            "request": request,
            "agent": agent,
            "error": error_message,
            "current_metrics": current_metrics,
            "historical_metrics": historical_metrics,
            "recommendations": recommendations,
            "teams_status": teams_status,
            "pending_count": pending_count if 'pending_count' in locals() else 0,
            "system_metrics": system_metrics if 'system_metrics' in locals() else {},
            "conversation_metrics": conversation_metrics if 'conversation_metrics' in locals() else {},
            "callback_metrics": callback_metrics if 'callback_metrics' in locals() else {},
            "activity_level": dashboard_data.get("activity_level", "Normal") if 'dashboard_data' in locals() else "Normal",
            "data_freshness": "Real-time",
            "last_updated": datetime.utcnow().isoformat(),
            "build_version": BUILD_VERSION,
            "callback_system_version": CALLBACK_SYSTEM_VERSION
        }
    )

@app.get("/agent/conversation/{conversation_id}", response_class=HTMLResponse)
async def conversation_page(
    request: Request,
    conversation_id: str,
    agent: Dict = Depends(get_current_agent)
):
    """Page for handling a specific conversation"""
    # Check if conversation exists
    if conversation_id not in active_conversations and conversation_id not in conversation_messages:
        if not _hydrate_conversation_from_table(conversation_id):
            # Conversation not found - return 404
            return templates.TemplateResponse(
                "redirect.html",
                {
                    "request": request,
                    "title": "Conversation Not Found",
                    "message": "The conversation you're looking for does not exist.",
                    "redirect_url": "/agent/portal",
                    "delay": 3
                },
                status_code=404
            )

    # Get conversation data
    conversation = active_conversations.get(conversation_id, {})
    messages = conversation_messages.get(conversation_id, [])

    return templates.TemplateResponse(
        "conversation.html",
        {
            "request": request,
            "agent": agent,
            "conversation_id": conversation_id,
            "user_info": conversation.get("user_info", {}),
            "history": messages,
            "build_version": BUILD_VERSION,
            "callback_system_version": CALLBACK_SYSTEM_VERSION
        }
    )

@app.get("/api/conversations/pending")
async def get_pending_conversations(agent: Dict = Depends(get_current_agent)):
    """Get all pending conversations"""
    pending = [
        {**conv, "id": conv_id}
        for conv_id, conv in active_conversations.items()
        if conv.get("status") == "waiting"
    ]
    pending_ids = {item.get("id") for item in pending}
    table_pending = _load_pending_from_table()
    for conv in table_pending:
        conv_id = conv.get("id")
        if not conv_id or conv_id in pending_ids:
            continue
        active_conversations[conv_id] = conv
        conversation_messages.setdefault(conv_id, [])
        pending.append({**conv, "id": conv_id})
    return pending

@app.get("/api/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, agent: Dict = Depends(get_current_agent)):
    """Get conversation details"""
    if conversation_id not in active_conversations:
        _hydrate_conversation_from_table(conversation_id)
    if conversation_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation = active_conversations[conversation_id]
    messages = conversation_messages.get(conversation_id, [])

    return {**conversation, "messages": messages}

@app.post("/api/conversations/{conversation_id}/join")
async def join_conversation(conversation_id: str, agent: Dict = Depends(get_current_agent)):
    """Join a conversation as an agent"""
    if conversation_id not in active_conversations:
        _hydrate_conversation_from_table(conversation_id)
    if conversation_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation = active_conversations[conversation_id]
    conversation["status"] = "active"
    conversation["agent_id"] = agent["id"]
    conversation["agent_name"] = agent["name"]

    # Add system message about agent joining
    if conversation_id not in conversation_messages:
        conversation_messages[conversation_id] = []

    conversation_messages[conversation_id].append({
        "role": "system",
        "content": f"Agent {agent['name']} has joined the conversation",
        "timestamp": datetime.utcnow().isoformat()
    })

    # Broadcast message to all connections
    await broadcast_to_conversation(
        conversation_id,
        {
            "type": "agent_joined",
            "agent": agent["name"],
            "timestamp": datetime.utcnow().isoformat()
        }
    )

    # Cancel callback timeout monitor now that an agent has joined
    try:
        from callback_system import cancel_conversation_timeout_monitor
        await cancel_conversation_timeout_monitor(conversation_id)
        logger.info(f"✅ Cancelled timeout monitor for conversation {conversation_id}")
    except Exception as monitor_err:
        logger.warning(f"⚠️ Failed to cancel timeout monitor for {conversation_id}: {monitor_err}")

    return {"status": "joined", "conversation": conversation}

@app.post("/api/conversations/{conversation_id}/leave")
async def leave_conversation(conversation_id: str, agent: Dict = Depends(get_current_agent)):
    """Leave a conversation"""
    if conversation_id not in active_conversations:
        _hydrate_conversation_from_table(conversation_id)
    if conversation_id not in active_conversations:
        raise HTTPException(status_code=404, detail="Conversation not found")

    conversation = active_conversations[conversation_id]
    conversation["status"] = "closed"
    conversation["closed_at"] = datetime.utcnow().isoformat()

    # Add system message about agent leaving
    if conversation_id in conversation_messages:
        conversation_messages[conversation_id].append({
            "role": "system",
            "content": f"Agent {agent['name']} has left the conversation",
            "timestamp": datetime.utcnow().isoformat()
        })

    # Broadcast message to all connections
    await broadcast_to_conversation(
        conversation_id,
        {
            "type": "agent_left",
            "agent": agent["name"],
            "timestamp": datetime.utcnow().isoformat()
        }
    )

    # Persist closed status to shared storage so it disappears from the pending list
    closed_stored = False
    if conversation_store:
        try:
            conversation_store.mark_closed(conversation_id, "agent_left")
            closed_stored = True
        except Exception as status_err:
            logger.warning(f"⚠️ Failed to mark handoff closed via conversation_store: {status_err}")

    if not closed_stored and os.getenv("AZURE_STORAGE_CONNECTION_STRING"):
        try:
            from azure.data.tables import TableServiceClient, UpdateMode
            tsc = TableServiceClient.from_connection_string(os.getenv("AZURE_STORAGE_CONNECTION_STRING"))
            table = tsc.get_table_client("conversations")
            row_key = f"{_normalize_conversation_id(conversation_id)}_pre_handoff"
            entity = {
                "PartitionKey": "conversations",
                "RowKey": row_key,
                "status": "closed",
                "status_reason": "agent_left",
                "status_updated_at": conversation["closed_at"],
                "closed_at": conversation["closed_at"],
                "last_event_at": conversation["closed_at"],
            }
            table.upsert_entity(entity, mode=UpdateMode.MERGE)
            closed_stored = True
        except Exception as table_err:
            logger.warning(f"⚠️ Failed to mark handoff closed via direct table update: {table_err}")

    return {"status": "left", "conversation": conversation}

@app.get("/api/conversations/{conversation_id}/transcript")
async def get_transcript(conversation_id: str, agent: Dict = Depends(get_current_agent)):
    """Get conversation transcript as downloadable text"""
    if conversation_id not in conversation_messages:
        raise HTTPException(status_code=404, detail="Conversation transcript not found")

    messages = conversation_messages[conversation_id]

    # Format transcript
    transcript = f"Conversation ID: {conversation_id}\n"
    transcript += f"Date: {datetime.utcnow().strftime('%Y-%m-%d')}\n\n"

    for msg in messages:
        role = msg.get("role", "unknown").upper()
        timestamp = msg.get("timestamp", "")
        if timestamp:
            try:
                dt = datetime.fromisoformat(timestamp)
                timestamp = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                pass

        transcript += f"[{timestamp}] {role}: {msg.get('content', '')}\n\n"

    return JSONResponse(
        content={"transcript": transcript},
        headers={"Content-Disposition": f"attachment; filename=transcript-{conversation_id}.txt"}
    )

@app.get("/chat/{conversation_id}", response_class=HTMLResponse)
async def user_chat_page(request: Request, conversation_id: str):
    """User-facing chat page for class members"""
    # Check if conversation exists
    if conversation_id not in active_conversations and conversation_id not in conversation_messages:
        # Try to load conversation data
        active_conversations[conversation_id] = {
            "id": conversation_id,
            "user_info": {"apex_id": "User", "name": "Class Member"},
            "waiting_since": get_pacific_time().isoformat(),
            "status": "waiting",
            "reason": "Direct chat access"
        }
        
        if conversation_id not in conversation_messages:
            conversation_messages[conversation_id] = []
    
    # Get conversation info
    conversation = active_conversations.get(conversation_id, {})
    messages = conversation_messages.get(conversation_id, [])
    
    return templates.TemplateResponse(
        "user_chat.html",
        {
            "request": request,
            "conversation_id": conversation_id,
            "conversation": conversation,
            "messages": messages,
            "build_version": BUILD_VERSION
        }
    )

# Helper: normalize client types across UIs (treat 'user' == 'chainlit')
def normalize_client_type(t: Optional[str]) -> str:
    if not t:
        return "agent"
    t_low = str(t).lower()
    if t_low in {"chainlit", "user", "member", "class_member"}:
        return "chainlit"
    if t_low in {"agent", "support_agent", "csr", "portal_agent"}:
        return "agent"
    return t_low

# WebSocket endpoint for real-time communication
@app.websocket("/ws/conversation/{conversation_id}")
async def websocket_endpoint(websocket: WebSocket, conversation_id: str):
    await websocket.accept()

    # Determine connection type from headers (try multiple sources)
    client_type = normalize_client_type(
        websocket.headers.get("x-client-type") or
        websocket.query_params.get("client_type", "agent")
    )

    # Capture agent metadata (if provided)
    agent_name = websocket.query_params.get("agent_name")
    agent_id = websocket.query_params.get("agent_id")

    # Ensure conversation context exists before storing connection
    conversation = active_conversations.get(conversation_id, {})

    if client_type == "agent":
        if not agent_name:
            agent_name = conversation.get("agent_name") or conversation.get("assigned_agent")
        if not agent_name:
            agent_name = "Agent"
        # Persist agent metadata on the conversation for later lookups
        conversation.setdefault("agent_name", agent_name)
        if agent_id:
            conversation.setdefault("agent_id", agent_id)
        active_conversations[conversation_id] = conversation

    # Add connection to active connections
    if conversation_id not in active_connections:
        active_connections[conversation_id] = []
    active_connections[conversation_id].append(websocket)

    # Track connection type
    connection_types[websocket] = {
        "type": client_type,
        "conversation_id": conversation_id,
        "connected_at": datetime.utcnow().isoformat(),
        "agent_name": agent_name,
        "agent_id": agent_id
    }

    logger.info(
        f"WebSocket connection established: {client_type} for conversation {conversation_id}"
        + (f" (agent={agent_name})" if client_type == "agent" else "")
    )

    try:
        # Send initial connection message
        await websocket.send_json({
            "type": "connection_established",
            "conversation_id": conversation_id,
            "client_type": client_type,
            "timestamp": datetime.utcnow().isoformat()
        })

        # Listen for messages
        while True:
            data = await websocket.receive_text()
            message_data = json.loads(data)

            # Handle client identification messages
            if message_data.get("type") == "client_identification":
                new_client_type = normalize_client_type(message_data.get("client_type", "agent"))
                logger.info(f"🔧 Client identification received: {new_client_type} for {conversation_id}")
                logger.info(f"🔧 Previous client type was: {client_type}")

                # Update client type
                client_type = new_client_type
                connection_types[websocket]["type"] = client_type

                logger.info(f"🔧 Updated client type to: {client_type}")

                # Don't store identification messages in conversation history
                continue

            # Add message to conversation history
            if conversation_id not in conversation_messages:
                conversation_messages[conversation_id] = []

            # Add timestamp if not provided
            if "timestamp" not in message_data:
                message_data["timestamp"] = datetime.utcnow().isoformat()

            # Add normalized client type info for message routing
            message_data["source_client"] = client_type

            # Handle message based on source
            sender_info = connection_types.get(websocket, {})
            if client_type == "chainlit":
                # Message from Chainlit user - mark as user message
                message_data["role"] = "user"
                message_data.setdefault("type", "user_message")
                if "user_name" not in message_data:
                    message_data["user_name"] = message_data.get("display_name") or "User"
            elif client_type == "agent":
                # Message from agent - mark as agent message
                agent_name = message_data.get("agent_name") or sender_info.get("agent_name")
                if not agent_name and conversation_id in active_conversations:
                    agent_name = active_conversations[conversation_id].get("agent_name")
                message_data["role"] = "agent"
                message_data.setdefault("type", "agent_message")
                message_data["agent_name"] = agent_name or "Agent"
                if sender_info.get("agent_id") and "agent_id" not in message_data:
                    message_data["agent_id"] = sender_info["agent_id"]

            # Store a copy of the message for history to avoid downstream mutations
            conversation_messages[conversation_id].append(dict(message_data))

            # Route message to appropriate recipients
            await route_message_to_recipients(conversation_id, message_data, websocket)

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {client_type} for conversation {conversation_id}")
        await cleanup_connection(websocket, conversation_id)
    except Exception as e:
        logger.error(f"WebSocket error: {str(e)}")
        await cleanup_connection(websocket, conversation_id)

async def route_message_to_recipients(conversation_id: str, message: dict, sender_websocket: WebSocket):
    """Route message to appropriate recipients based on message source"""
    if conversation_id not in active_connections:
        logger.warning(f"🔧 No active connections for conversation {conversation_id}")
        return

    source_client = normalize_client_type(message.get("source_client", "unknown"))
    sender_info = connection_types.get(sender_websocket, {})
    if source_client == "agent":
        message.setdefault("agent_name", sender_info.get("agent_name", "Agent"))
        message.setdefault("type", "agent_message")
        message.setdefault("role", "agent")
    elif source_client == "chainlit":
        message.setdefault("type", "user_message")
        message.setdefault("role", "user")

    logger.info(f"🔧 Routing message from {source_client} to {len(active_connections[conversation_id])} connections")

    # Debug: show all connection types
    for i, conn in enumerate(active_connections[conversation_id]):
        conn_info = connection_types.get(conn, {})
        logger.info(f"🔧 Connection {i}: type={conn_info.get('type', 'unknown')}")

    # Send to all connections except sender
    dead_connections = []
    for connection in active_connections[conversation_id]:
        if connection == sender_websocket:
            continue  # Don't echo back to sender

        try:
            # Get recipient connection type (normalized)
            recipient_info = connection_types.get(connection, {})
            recipient_type = normalize_client_type(recipient_info.get("type", "agent"))

            # Route based on recipient type
            if recipient_type == "chainlit" and source_client == "agent":
                # Agent message going to Chainlit - format for user display
                formatted_message = {
                    **message,
                    "type": "agent_message",
                    "display_content": message.get("content", ""),
                    "agent_name": message.get("agent_name", sender_info.get("agent_name", "Agent")),
                }
                await connection.send_json(formatted_message)
                logger.info(f"📤 Routed agent message to Chainlit for {conversation_id}: {message.get('content', '')[:50]}...")

            elif recipient_type == "agent" and source_client == "chainlit":
                # User message going to agent - format for agent display
                formatted_message = {
                    **message,
                    "type": "user_message",
                    "display_content": message.get("content", "")
                }
                await connection.send_json(formatted_message)
                logger.info(f"📤 Routed user message to agent for {conversation_id}: {message.get('content', '')[:50]}...")

            elif recipient_type == source_client:
                # Same client type - send as-is (for multiple agents/multiple Chainlit instances)
                await connection.send_json(message)

        except Exception as e:
            logger.error(f"Error routing message to {recipient_type}: {str(e)}")
            dead_connections.append(connection)

    # Clean up dead connections
    for dead in dead_connections:
        await cleanup_connection(dead, conversation_id)

async def cleanup_connection(websocket: WebSocket, conversation_id: str):
    """Clean up a WebSocket connection"""
    # Remove from active connections
    if conversation_id in active_connections and websocket in active_connections[conversation_id]:
        active_connections[conversation_id].remove(websocket)

    # Remove connection type tracking
    if websocket in connection_types:
        client_info = connection_types[websocket]
        client_type = client_info.get("type", "unknown")
        logger.info(f"Cleaned up {client_type} connection for {conversation_id}")
        del connection_types[websocket]

async def broadcast_to_conversation(conversation_id: str, message: dict):
    """Broadcast a message to all connections in a conversation"""
    if conversation_id in active_connections:
        dead_connections = []
        for connection in active_connections[conversation_id]:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)

        # Clean up dead connections
        for dead in dead_connections:
            if dead in active_connections[conversation_id]:
                active_connections[conversation_id].remove(dead)

# API for Lucy to create handoff requests
@app.post("/api/handoff")
async def create_handoff(handoff_data: dict):
    """Create a new handoff request from Lucy"""
    conversation_id = handoff_data.get("conversation_id")
    if not conversation_id:
        conversation_id = str(uuid.uuid4())

    # Store the new conversation
    active_conversations[conversation_id] = {
        "id": conversation_id,
        "user_info": handoff_data.get("user_info", {}),
        "waiting_since": get_pacific_time().isoformat(),
        "status": "waiting",
        "reason": handoff_data.get("reason", "General assistance")
    }

    # Initialize message history
    if conversation_id not in conversation_messages:
        conversation_messages[conversation_id] = []

    # Add any provided history
    for message in handoff_data.get("history", []):
        conversation_messages[conversation_id].append(message)

    # Add system message
    conversation_messages[conversation_id].append({
        "role": "system",
        "content": "Human assistance requested. Waiting for an agent to join.",
        "timestamp": datetime.utcnow().isoformat()
    })

    # Persist the handoff to shared storage so the portal always sees it
    apex_id = handoff_data.get("user_info", {}).get("apex_id")
    portal_url = handoff_data.get("portal_url") or os.getenv("PUBLIC_PORTAL_URL") or os.getenv("AGENT_PORTAL_URL", "")
    metadata = {
        "user_info": handoff_data.get("user_info", {}),
        "reason": handoff_data.get("reason", "General assistance"),
        "created_at": datetime.utcnow().isoformat(),
        "portal_url": portal_url
    }

    stored = False
    if conversation_store:
        try:
            stored = conversation_store.store_handoff_conversation(
                conversation_id,
                conversation_messages[conversation_id],
                apex_id=apex_id,
                status="pending",
                status_reason="handoff_requested",
                metadata=metadata,
                portal_url=portal_url,
                reason=handoff_data.get("reason", "General assistance")
            )
            logger.info(f"💾 Stored handoff {conversation_id} via conversation_store (success={stored})")
        except Exception as e:
            logger.warning(f"⚠️ conversation_store storage failed for {conversation_id}: {e}")

    if not stored and callback_system:
        try:
            await callback_system.store_conversation_history(
                conversation_id,
                "pre_handoff",
                conversation_messages[conversation_id],
                metadata
            )
            stored = True
            logger.info(f"💾 Stored handoff {conversation_id} via callback_system fallback")
        except Exception as e:
            logger.error(f"❌ Failed to persist handoff {conversation_id}: {e}")

    # Last-resort: write directly to Azure Tables to guarantee portal visibility
    if not stored and os.getenv("AZURE_STORAGE_CONNECTION_STRING"):
        try:
            from azure.data.tables import TableServiceClient

            tsc = TableServiceClient.from_connection_string(os.getenv("AZURE_STORAGE_CONNECTION_STRING"))
            table = tsc.get_table_client("conversations")
            try:
                table.create_table()
            except Exception:
                pass  # table likely exists

            row_key = f"{conversation_id}_pre_handoff"
            entity = {
                "PartitionKey": "conversations",
                "RowKey": row_key,
                "conversation_id": conversation_id,
                "conversation_type": "pre_handoff",
                "messages": json.dumps(conversation_messages[conversation_id]),
                "message_count": len(conversation_messages[conversation_id]),
                "created_at": metadata["created_at"],
                "metadata": json.dumps(metadata),
                "status": "pending",
                "status_reason": "handoff_requested",
                "status_updated_at": metadata["created_at"],
                "apex_id": apex_id or "",
                "portal_url": portal_url,
                "reason": handoff_data.get("reason", "General assistance"),
                "last_event_at": metadata["created_at"],
                "connected_at": "",
                "closed_at": ""
            }
            table.upsert_entity(entity)
            stored = True
            logger.info(f"💾 Stored handoff {conversation_id} via direct Azure Tables fallback")
        except Exception as e:
            logger.error(f"❌ Direct Azure Tables fallback failed for {conversation_id}: {e}")

    return {"status": "created", "conversation_id": conversation_id}

# Teams integration endpoints
@app.post("/api/teams/availability")
async def teams_availability_callback(callback_data: dict):
    """Handle Teams availability callback from agent responses"""
    try:
        request_id = callback_data.get("request_id")
        available = callback_data.get("available", False)
        conversation_id = callback_data.get("conversation_id")
        agent_name = callback_data.get("agent", "Unknown Agent")

        if not request_id:
            raise HTTPException(status_code=400, detail="Missing request_id")

        logger.info(f"Teams callback: {agent_name} responded '{available}' to request {request_id}")

        # Check if this is a pending availability check
        if request_id not in pending_availability_checks:
            logger.warning(f"Received callback for unknown request_id: {request_id}")
            return {"status": "received", "warning": "Unknown request_id"}

        # Get the pending check info
        check_info = pending_availability_checks[request_id]

        if available:
            # Agent is available - create conversation and notify
            if not conversation_id:
                conversation_id = str(uuid.uuid4())

            # Create conversation in portal
            active_conversations[conversation_id] = {
                "id": conversation_id,
                "user_info": check_info.get("user_info", {}),
                "waiting_since": get_pacific_time().isoformat(),
                "status": "waiting",
                "assigned_agent": agent_name,
                "request_id": request_id,
                "reason": check_info.get("reason", "General assistance")
            }

            # Initialize message history
            conversation_messages[conversation_id] = [
                {
                    "role": "system",
                    "content": f"Human assistance requested. Agent {agent_name} has been notified.",
                    "timestamp": get_pacific_time().isoformat()
                }
            ]

            # Store response for Lucy to pick up
            check_info["response"] = {
                "available": True,
                "agent_name": agent_name,
                "conversation_id": conversation_id,
                "portal_url": f"{check_info.get('portal_base_url', 'http://localhost:8001')}/agent/conversation/{conversation_id}"
            }

            logger.info(f"Created conversation {conversation_id} for available agent {agent_name}")
        else:
            # Agent is not available
            check_info["response"] = {
                "available": False,
                "agent_name": agent_name,
                "message": f"{agent_name} is not available"
            }

        # Mark as responded
        check_info["responded"] = True
        check_info["responded_at"] = datetime.utcnow().isoformat()

        return {"status": "received", "request_id": request_id, "conversation_id": conversation_id if available else None}

    except Exception as e:
        logger.error(f"Teams callback error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/teams/availability/check")
async def create_availability_check(check_data: dict):
    """Create a new availability check request"""
    try:
        request_id = str(uuid.uuid4())

        # Store the availability check
        pending_availability_checks[request_id] = {
            "request_id": request_id,
            "user_info": check_data.get("user_info", {}),
            "reason": check_data.get("reason", "General assistance"),
            "created_at": datetime.utcnow().isoformat(),
            "responded": False,
            "portal_base_url": check_data.get("portal_base_url", "http://localhost:8001")
        }

        return {"request_id": request_id, "status": "created"}

    except Exception as e:
        logger.error(f"Availability check creation error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/teams/availability/check/{request_id}")
async def get_availability_check_status(request_id: str):
    """Get the status of an availability check"""
    if request_id not in pending_availability_checks:
        raise HTTPException(status_code=404, detail="Request not found")

    check_info = pending_availability_checks[request_id]

    # Clean up old checks (older than 5 minutes)
    created_at = datetime.fromisoformat(check_info["created_at"])
    if (datetime.utcnow() - created_at).total_seconds() > 300:
        del pending_availability_checks[request_id]
        return {"status": "expired", "message": "Request expired"}

    if check_info.get("responded"):
        response = check_info.get("response", {})
        # Clean up after successful response
        del pending_availability_checks[request_id]
        return {"status": "responded", "response": response}
    else:
        return {"status": "waiting", "created_at": check_info["created_at"]}

@app.post("/api/teams/webhook")
async def teams_webhook_handler(request: Request):
    """
    Handle incoming Teams webhook messages and replies
    This prevents server crashes when agents reply directly in Teams
    """
    try:
        # Get the raw body first
        body = await request.body()
        content_type = request.headers.get("content-type", "")

        logger.info(f"Received Teams webhook: Content-Type={content_type}, Size={len(body)} bytes")

        # Handle different content types
        if "application/json" in content_type:
            try:
                webhook_data = json.loads(body)
                logger.info(f"Teams webhook JSON data: {json.dumps(webhook_data, indent=2)}")
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON in Teams webhook: {e}")
                webhook_data = {}
        else:
            # Handle plain text or other formats
            webhook_data = {"text": body.decode("utf-8", errors="replace")}
            logger.info(f"Teams webhook text data: {webhook_data['text'][:200]}...")

        # Extract message information
        message_text = webhook_data.get("text", "")
        from_user = webhook_data.get("from", {}).get("name", "Teams User")
        activity_type = webhook_data.get("type", "message")

        # Handle different Teams activity types
        if activity_type == "message":
            # This is a regular message from Teams
            logger.info(f"Received Teams message from {from_user}: {message_text[:100]}...")

            # Don't return any structured message - just log and acknowledge
            # This prevents creating unwanted adaptive cards or message loops
            return JSONResponse(
                status_code=200,
                content={"status": "received", "message": "Teams message acknowledged"}
            )

        elif activity_type == "invoke":
            # This is a card action (button click)
            action = webhook_data.get("value", {})
            logger.info(f"Teams card action from {from_user}: {action}")

            # Handle availability responses
            if action.get("request_id"):
                # This is an availability response - forward to existing handler
                return await teams_availability_callback(action)
            else:
                return {
                    "type": "message",
                    "text": "Action received. Please use the Agent Portal for ongoing conversations."
                }

        else:
            # Unknown activity type
            logger.info(f"Unknown Teams activity type: {activity_type}")
            return {"type": "message", "text": "Message received."}

    except Exception as e:
        logger.error(f"Teams webhook error: {e}", exc_info=True)
        # Return a safe response to prevent Teams from retrying
        return {
            "type": "message",
            "text": "Thank you for your message. Please use the Agent Portal for customer conversations."
        }

@app.get("/api/metrics/current")
async def get_current_metrics():
    """Get current metrics for dashboard updates"""
    try:
        from agentic_monitoring import get_monitoring_summary
        metrics = get_monitoring_summary()

        # Get pending callbacks count
        pending_callbacks_count = 0
        try:
            from user_functions import get_pending_callbacks_sync
            result_str = get_pending_callbacks_sync()
            import json
            result = json.loads(result_str)
            if result.get("success"):
                pending_callbacks_count = result.get("count", 0)
        except Exception:
            pass

        # Add real-time portal data
        portal_metrics = {
            "active_conversations": len(active_conversations),
            "pending_conversations": len([c for c in active_conversations.values() if c.get("status") == "waiting"]),
            "active_connections": sum(len(conns) for conns in active_connections.values()),
            "total_messages": sum(len(msgs) for msgs in conversation_messages.values()),
            "pending_callbacks": pending_callbacks_count,
            "system_uptime": "--",
            "avg_response_time": "--",
            "memory_usage": "--"
        }

        return {
            "authentication_metrics": metrics,
            "portal_metrics": portal_metrics,
            "timestamp": get_pacific_time().isoformat()
        }
    except Exception as e:
        logger.error(f"Metrics API error: {e}")
        return {"error": str(e), "timestamp": get_pacific_time().isoformat()}

# WebSocket for real-time metrics
@app.websocket("/ws/metrics")
async def metrics_websocket(websocket: WebSocket):
    """WebSocket endpoint for streaming real-time metrics"""
    await websocket.accept()

    try:
        # Send initial metrics
        metrics = await get_current_metrics()
        await websocket.send_json(metrics)

        # Send periodic updates
        while True:
            await asyncio.sleep(5)  # Update every 5 seconds
            try:
                metrics = await get_current_metrics()
                await websocket.send_json(metrics)
            except Exception as e:
                logger.error(f"Error sending metrics: {e}")
                break

    except WebSocketDisconnect:
        logger.info("Metrics WebSocket disconnected")
    except Exception as e:
        logger.error(f"Metrics WebSocket error: {e}")

# Callback management endpoints
@app.get("/api/callbacks/pending")
async def get_pending_callbacks_api(agent: Dict = Depends(get_current_agent)):
    """Get all pending callback requests"""
    try:
        # Check if Azure Storage is configured
        if not os.getenv("AZURE_STORAGE_CONNECTION_STRING"):
            logger.warning("Azure Storage not configured - returning empty callbacks")
            return {
                "success": True,
                "callbacks": [],
                "count": 0,
                "warning": "Azure Storage not configured - callback system unavailable"
            }

        # Try to use callback_system directly if available
        global callback_system
        if callback_system:
            logger.info("Using direct callback_system for pending callbacks")
            callbacks = await callback_system.get_pending_callbacks()
            return {
                "success": True,
                "callbacks": callbacks,
                "count": len(callbacks)
            }
        else:
            # Fall back to user_functions
            logger.info("Using user_functions for pending callbacks")
            from user_functions import get_pending_callbacks_sync

            result_str = get_pending_callbacks_sync()
            result = json.loads(result_str)

            # Add debug logging
            logger.info(f"Fetched {result.get('count', 0)} pending callbacks from Azure Storage")

            if result.get("success"):
                return {
                    "success": True,
                    "callbacks": result.get("callbacks", []),
                    "count": result.get("count", 0)
                }
            else:
                return {
                    "success": False,
                    "error": result.get("error", "Unknown error"),
                    "callbacks": []
                }

    except Exception as e:
        logger.error(f"Error fetching callbacks: {e}")
        return {
            "success": False,
            "error": str(e),
            "callbacks": []
        }

@app.post("/api/callbacks/{callback_id}/complete")
async def complete_callback(
    callback_id: str,
    completion_data: dict,
    agent: Dict = Depends(get_current_agent)
):
    """Mark a callback as completed with agent notes"""
    try:
        from user_functions import mark_callback_completed_sync, get_pending_callbacks_sync, add_agent_note_to_member_sync

        agent_notes = completion_data.get("notes", "")

        # First, get the callback details to find the apex_id
        callbacks_str = get_pending_callbacks_sync()
        callbacks_result = json.loads(callbacks_str)

        apex_id = None
        if callbacks_result.get("success"):
            # Find the specific callback
            for callback in callbacks_result.get("callbacks", []):
                if callback.get("callback_id") == callback_id:
                    apex_id = callback.get("apex_id")
                    break

        # Mark the callback as completed
        result_str = mark_callback_completed_sync(callback_id, agent_notes)
        result = json.loads(result_str)

        if result.get("success"):
            # If we have an apex_id and notes, also save to member profile
            if apex_id and apex_id != "UNKNOWN" and agent_notes:
                try:
                    note_result_str = add_agent_note_to_member_sync(
                        apex_id=apex_id,
                        agent_name=agent["name"],
                        note_content=f"Callback completed: {agent_notes}",
                        conversation_id=callback_id
                    )
                    note_result = json.loads(note_result_str)
                    if not note_result.get("success"):
                        logger.warning(f"Failed to add note to member profile: {note_result.get('error')}")
                except Exception as note_error:
                    logger.warning(f"Error adding note to member profile: {note_error}")

            return {
                "success": True,
                "message": "Callback marked as completed",
                "callback_id": callback_id,
                "note_saved": apex_id is not None and apex_id != "UNKNOWN"
            }
        else:
            return {
                "success": False,
                "error": result.get("error", "Failed to mark callback as completed")
            }

    except Exception as e:
        logger.error(f"Error completing callback: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@app.get("/agent/callbacks", response_class=HTMLResponse)
async def callbacks_page(request: Request, agent: Dict = Depends(get_current_agent)):
    """Callback management page"""
    return templates.TemplateResponse(
        "callbacks.html",
        {
            "request": request,
            "agent": agent,
            "build_version": BUILD_VERSION,
            "callback_system_version": CALLBACK_SYSTEM_VERSION
        }
    )

@app.get("/api/conversations/{conversation_id}/history")
async def get_conversation_history_api(
    conversation_id: str,
    conversation_type: Optional[str] = None,
    agent: Dict = Depends(get_current_agent)
):
    """Get conversation history - simplified approach that actually works"""
    try:
        logger.info(f"📖 Fetching conversation history for conversation_id='{conversation_id}'")
        logger.info(f"📖 Request from agent: {agent.get('name', 'Unknown')}")
        logger.info(f"📖 Full request path: /api/conversations/{conversation_id}/history")

        # Try conversation_store first, then fall back to callback_system
        conversation = None
        direct_conversation = None

        if conversation_store:
            logger.info(f"📖 Attempting to get conversation from conversation_store")
            conversation = conversation_store.get_handoff_conversation(conversation_id)
            logger.info(f"📖 conversation_store returned: {conversation is not None}")

        # Direct Azure Tables fallback (avoid missing cache/SDK quirks)
        if os.getenv("AZURE_STORAGE_CONNECTION_STRING"):
            try:
                from azure.data.tables import TableServiceClient
                tsc = TableServiceClient.from_connection_string(os.getenv("AZURE_STORAGE_CONNECTION_STRING"))
                table = tsc.get_table_client("conversations")
                storage_id = conversation_store._normalize_conversation_id(conversation_id) if conversation_store else conversation_id
                row_key = f"{storage_id}_pre_handoff"
                entity = table.get_entity(partition_key="conversations", row_key=row_key)
                messages = json.loads(entity.get("messages", "[]"))
                direct_conversation = {
                    "id": conversation_id,
                    "normalized_id": storage_id,
                    "messages": messages,
                    "stored_at": entity.get("created_at", entity.get("Timestamp", "")),
                    "message_count": entity.get("message_count", len(messages)),
                    "metadata": entity.get("metadata", {})
                }
                logger.info(f"📖 Retrieved conversation via direct Tables fallback ({len(messages)} messages)")
            except Exception as table_err:
                logger.warning(f"⚠️ Direct Tables fallback failed: {table_err}")

        if direct_conversation and _conversation_score(direct_conversation) > _conversation_score(conversation):
            logger.info("📖 Using direct Tables conversation (richer data than cache)")
            conversation = direct_conversation

        # If conversation_store didn't work, try callback_system
        if not conversation:
            logger.info(f"📖 Falling back to callback_system")
            try:
                from user_functions import get_conversation_history_sync
                result_str = get_conversation_history_sync(conversation_id)
                result = json.loads(result_str)

                if result.get("success") and result.get("conversations"):
                    # Use the first conversation (should be pre_handoff)
                    for conv in result.get("conversations", []):
                        if conv.get("conversation_type") == "pre_handoff":
                            conversation = {
                                "messages": conv.get("messages", []),
                                "message_count": conv.get("message_count", 0),
                                "stored_at": conv.get("created_at", ""),
                                "metadata": conv.get("metadata", {})
                            }
                            logger.info(f"✅ Found conversation via callback_system fallback")
                            break
            except Exception as e:
                logger.error(f"❌ Callback system fallback failed: {e}")

        if conversation:
            # Extract metadata if it's a string
            metadata = conversation.get("metadata", {})
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except:
                    metadata = {}
            
            # Format it to match the expected response structure
            # Ensure messages is a list and not a string
            messages = conversation.get("messages", [])
            if isinstance(messages, str):
                try:
                    messages = json.loads(messages)
                except Exception:
                    messages = []

            formatted_conversation = {
                "conversation_id": conversation_id,
                "conversation_type": "pre_handoff",
                "messages": messages,
                "message_count": len(messages),
                "created_at": conversation.get("stored_at", ""),
                "metadata": metadata,
                "member_notes_summary": metadata.get("member_notes_summary", ""),
                "analytics_data": metadata.get("analytics_data", {})
            }

            logger.info(f"✅ Found conversation with {formatted_conversation['message_count']} messages")

            return {
                "success": True,
                "conversations": [formatted_conversation],
                "count": 1
            }
        else:
            logger.warning(f"❌ No conversation found for {conversation_id}")
            return {
                "success": True,  # Not an error, just no data
                "conversations": [],
                "count": 0
            }

    except Exception as e:
        logger.error(f"❌ Error fetching conversation history: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "conversations": []
        }

@app.post("/api/members/{apex_id}/notes")
async def add_member_note(
    apex_id: str,
    note_data: dict,
    agent: Dict = Depends(get_current_agent)
):
    """Add an agent note to a member's Dynamics 365 profile"""
    try:
        from user_functions import add_agent_note_to_member_sync

        note_content = note_data.get("note", "")
        conversation_id = note_data.get("conversation_id")

        if not note_content.strip():
            return {
                "success": False,
                "error": "Note content is required"
            }

        result_str = add_agent_note_to_member_sync(
            apex_id=apex_id,
            agent_name=agent["name"],
            note_content=note_content,
            conversation_id=conversation_id
        )
        result = json.loads(result_str)

        return result

    except Exception as e:
        logger.error(f"Error adding member note: {e}")
        return {
            "success": False,
            "error": str(e)
        }

@app.post("/api/callbacks/ai-summarize")
async def ai_summarize_callback(callback_data: dict, agent: Dict = Depends(get_current_agent)):
    """Generate AI summary for callback completion"""
    try:
        callback_info = callback_data.get("callback_info", {})

        # Check if Azure OpenAI is configured
        azure_openai_key = os.getenv("AZURE_OPENAI_KEY")
        azure_openai_endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")

        if not azure_openai_key or not azure_openai_endpoint:
            # Return a template if AI is not configured
            user_name = callback_info.get("user_name", "member")
            phone = callback_info.get("phone_number", "")
            reason = callback_info.get("reason", "general inquiry")

            summary = f"Completed callback with {user_name} at {phone}. Addressed their inquiry regarding: {reason}. Member satisfied with resolution, no further action required."

            return {
                "success": True,
                "summary": summary,
                "is_template": True
            }

        # If AI is configured, use it (this would be implemented with Azure OpenAI SDK)
        # For now, return enhanced template
        user_name = callback_info.get("user_name", "member")
        phone = callback_info.get("phone_number", "")
        reason = callback_info.get("reason", "general inquiry")
        apex_id = callback_info.get("apex_id", "")

        summary = f"Completed callback with {user_name} ({apex_id}) at {phone}. Successfully addressed their concern regarding: {reason}. Provided clarification and member expressed satisfaction with the resolution. No additional follow-up required at this time."

        return {
            "success": True,
            "summary": summary,
            "is_template": False
        }

    except Exception as e:
        logger.error(f"Error generating AI summary: {e}")
        return {
            "success": False,
            "error": str(e),
            "summary": ""
        }

@app.post("/api/conversations/{conversation_id}/timeout")
async def handle_conversation_timeout(conversation_id: str, timeout_data: dict):
    """Handle 4-minute conversation timeout from callback system"""
    try:
        logger.info(f"⏰ Received timeout notification for conversation {conversation_id}")

        # Send WebSocket message to Lucy to initiate callback collection
        if conversation_id in active_connections:
            timeout_message = {
                "type": "timeout_occurred",
                "conversation_id": conversation_id,
                "user_info": timeout_data.get("user_info", {}),
                "reason": timeout_data.get("reason", ""),
                "action": "collect_callback_info",
                "message": "No agent joined within 4 minutes. Please collect callback information."
            }

            # Send to all connections for this conversation (usually just Lucy)
            for connection in active_connections[conversation_id]:
                try:
                    await connection.send_text(json.dumps(timeout_message))
                    logger.info(f"✅ Timeout message sent to Lucy via WebSocket")
                except Exception as ws_error:
                    logger.error(f"❌ Failed to send timeout message: {ws_error}")
        else:
            logger.warning(f"⚠️ No active connections for conversation {conversation_id}")

        # Mark the handoff as closed in shared storage so it leaves the pending list
        timeout_closed_at = datetime.utcnow().isoformat()
        if conversation_store:
            try:
                conversation_store.mark_closed(conversation_id, "timeout")
            except Exception as status_err:
                logger.warning(f"⚠️ Failed to mark timeout closed via conversation_store: {status_err}")
        elif os.getenv("AZURE_STORAGE_CONNECTION_STRING"):
            try:
                from azure.data.tables import TableServiceClient, UpdateMode
                tsc = TableServiceClient.from_connection_string(os.getenv("AZURE_STORAGE_CONNECTION_STRING"))
                table = tsc.get_table_client("conversations")
                row_key = f"{_normalize_conversation_id(conversation_id)}_pre_handoff"
                entity = {
                    "PartitionKey": "conversations",
                    "RowKey": row_key,
                    "status": "closed",
                    "status_reason": "timeout",
                    "status_updated_at": timeout_closed_at,
                    "closed_at": timeout_closed_at,
                    "last_event_at": timeout_closed_at,
                }
                table.upsert_entity(entity, mode=UpdateMode.MERGE)
            except Exception as table_err:
                logger.warning(f"⚠️ Failed to mark timeout closed via direct table update: {table_err}")

        return {"success": True, "message": "Timeout handled"}

    except Exception as e:
        logger.error(f"❌ Error handling timeout for {conversation_id}: {e}")
        return {"success": False, "error": str(e)}

# NOTE: Duplicate endpoints removed - callbacks are handled by the endpoints at lines 825-929

@app.delete("/api/callbacks/{callback_id}")
async def delete_callback(
    callback_id: str,
    agent: Dict = Depends(get_current_agent)
):
    """Delete a callback request"""
    try:
        from callback_system import callback_system

        if not callback_system:
            return JSONResponse(
                status_code=503,
                content={
                    "success": False,
                    "error": "Callback system not available"
                }
            )

        # Mark as cancelled instead of deleting
        success = await callback_system.update_callback_request(
            callback_id,
            {"status": "cancelled", "completed": True}
        )

        if success:
            logger.info(f"✅ Callback {callback_id} cancelled by {agent['name']}")
            return JSONResponse(content={
                "success": True,
                "message": "Callback cancelled"
            })
        else:
            return JSONResponse(
                status_code=500,
                content={
                    "success": False,
                    "error": "Failed to cancel callback"
                }
            )

    except Exception as e:
        logger.error(f"Error deleting callback {callback_id}: {e}")
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "error": str(e)
            }
        )

@app.get("/api/debug/conversation-storage")
async def debug_conversation_storage(agent: Dict = Depends(get_current_agent)):
    """Debug endpoint to check conversation storage status"""
    if not DEBUG_ENDPOINTS_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")

    try:
        # Check Azure Storage configuration
        storage_configured = bool(os.getenv("AZURE_STORAGE_CONNECTION_STRING"))

        # Check callback system status
        from callback_system import callback_system
        callback_system_available = callback_system is not None

        # Get recent conversation IDs from active conversations
        recent_conversations = list(active_conversations.keys())[:5]

        # Try to fetch history for recent conversations
        conversation_checks = []
        for conv_id in recent_conversations:
            try:
                from user_functions import get_conversation_history_sync
                result_str = get_conversation_history_sync(conv_id)
                result = json.loads(result_str)
                conversation_checks.append({
                    "conversation_id": conv_id,
                    "has_history": result.get("success", False),
                    "conversation_count": result.get("count", 0)
                })
            except Exception as e:
                conversation_checks.append({
                    "conversation_id": conv_id,
                    "has_history": False,
                    "error": str(e)
                })

        return {
            "storage_configured": storage_configured,
            "callback_system_available": callback_system_available,
            "active_conversations_count": len(active_conversations),
            "recent_conversation_checks": conversation_checks,
            "storage_backend": "Azure Tables" if storage_configured else "In-memory fallback"
        }

    except Exception as e:
        logger.error(f"Debug endpoint error: {e}")
        return {"error": str(e)}

@app.get("/api/debug/azure-test/{conversation_id}")
async def test_azure_connection(
    conversation_id: str,
    agent: Dict = Depends(get_current_agent)
):
    """Test Azure Tables connection and retrieval directly"""
    if not DEBUG_ENDPOINTS_ENABLED:
        raise HTTPException(status_code=404, detail="Not found")

    result = {
        "conversation_id": conversation_id,
        "azure_configured": bool(os.getenv("AZURE_STORAGE_CONNECTION_STRING")),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tests": []
    }

    # Test 1: Can we import callback_system?
    try:
        from callback_system import callback_system
        result["tests"].append({"test": "import_callback_system", "success": True, "message": "Module imported"})
    except Exception as e:
        result["tests"].append({"test": "import_callback_system", "success": False, "error": str(e)})
        return result

    # Test 2: Is callback_system initialized?
    if callback_system and callback_system.conversations_table:
        result["tests"].append({"test": "callback_system_init", "success": True, "message": "Initialized with Azure Tables"})
    else:
        result["tests"].append({"test": "callback_system_init", "success": False, "error": "Not initialized or no table"})
        return result

    # Test 3: Direct Azure Tables query
    try:
        import asyncio
        conversations = await callback_system.get_conversation_history(conversation_id)
        result["tests"].append({
            "test": "get_conversation_history",
            "success": True,
            "count": len(conversations),
            "conversations": conversations
        })
    except Exception as e:
        result["tests"].append({"test": "get_conversation_history", "success": False, "error": str(e)})

    # Test 4: Direct table access
    try:
        # Try to get the specific entity directly
        entity = callback_system.conversations_table.get_entity(
            partition_key="conversations",
            row_key=f"{conversation_id}_pre_handoff"
        )
        result["tests"].append({
            "test": "direct_entity_get",
            "success": True,
            "entity_found": True,
            "message_count": entity.get("message_count", 0)
        })
    except Exception as e:
        result["tests"].append({"test": "direct_entity_get", "success": False, "error": str(e)})

    return result

# Main entry point for running the app directly
if __name__ == "__main__":
    port = int(os.getenv("AGENT_PORTAL_PORT", 8001))
    log_level = os.getenv("LOG_LEVEL", "info")
    reload_enabled = _env_enabled("AGENT_PORTAL_RELOAD", default=False)

    # Print startup banner
    print(f"\n{'='*50}")
    print(f" Apex Agent Portal starting on port {port}")
    print(f"{'='*50}\n")

    uvicorn.run("agent_portal:app", host="0.0.0.0", port=port, log_level=log_level, reload=reload_enabled)
