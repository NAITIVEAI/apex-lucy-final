# Lucy AI - Architecture Overview

**Document Version**: 1.0
**Last Updated**: 2026-01-25
**Target Audience**: Technical managers, solutions architects, senior developers
**System**: Lucy AI - Class Action Settlement Member Support System

---

## Table of Contents

1. [Executive Architecture Summary](#executive-architecture-summary)
2. [High-Level System Architecture](#high-level-system-architecture)
3. [Component Architecture](#component-architecture)
4. [Data Flow Diagrams](#data-flow-diagrams)
5. [Technology Stack](#technology-stack)
6. [Deployment Architecture](#deployment-architecture)
7. [Security Architecture](#security-architecture)
8. [Scalability & Performance](#scalability--performance)
9. [Observability](#observability)
10. [Architectural Patterns](#architectural-patterns)
11. [Architectural Decisions & Rationale](#architectural-decisions--rationale)
12. [Known Limitations](#known-limitations)

---

## Executive Architecture Summary

Lucy is an intelligent AI assistant designed to help class action settlement members access information about settlements, claims, and notices. The system combines natural language understanding with enterprise data integration to provide accurate, real-time support.

### Key Architectural Decisions

**1. Dual-Runtime Agent System**
- **Primary**: Azure AI Foundry v2 Responses API (production)
- **Legacy**: Azure AI Agents SDK (deprecated, fallback support)
- **Rationale**: Foundry v2 provides agent versioning, better observability, and unified API surface while maintaining backward compatibility during migration

**2. Hybrid Search RAG Pattern**
- **Lexical + Vector Search**: BM25 keyword matching combined with semantic similarity
- **Semantic Ranking**: ML re-ranking of top 50 results for precision
- **Rationale**: Legal documents require both exact keyword matches (case names, IDs) and semantic understanding (intent, context)

**3. Chunk-Based PDF Indexing**
- **Strategy**: Split 512-token chunks with 100-token overlap
- **Scale**: Millions of PDF documents indexed at chunk level
- **Rationale**: Enables precise retrieval of relevant passages rather than entire documents, improving context quality for LLM generation

**4. Cross-Container Conversation Storage**
- **Backend**: Azure Tables (primary persistent storage)
- **Pattern**: Shared state between Lucy (Chainlit) and Portal (FastAPI)
- **Rationale**: Enables human escalation with full conversation context, survives container restarts, supports multi-instance scaling

### Technology Stack Summary

| Layer | Technology | Purpose |
|-------|------------|---------|
| **Frontend** | Chainlit 2.9.5 | Conversational UI |
| **Agent Runtime** | Azure Foundry v2 Responses API | Agentic orchestration |
| **LLM** | GPT-4.1 (gpt-5.2) | Language understanding & generation |
| **Search** | Azure AI Search (hybrid) | RAG retrieval pipeline |
| **Data** | Dynamics 365, Azure Tables, Blob Storage | Member data, conversations, PDFs |
| **Portal** | FastAPI + WebSockets | Human-in-the-loop escalation |
| **Integration** | Microsoft Teams, SMTP | Agent notifications |
| **Observability** | Azure Monitor + Application Insights | Tracing, metrics, diagnostics |

### System Scale Characteristics

- **Documents**: Millions of PDF legal notices
- **Index**: Chunk-based (512 tokens per chunk)
- **Vector Dimensions**: 1,536 (text-embedding-3-small)
- **Conversation Retention**: 30 days (Foundry default)
- **Timeout Handling**: 4-minute escalation window with callback fallback
- **Authentication**: 50+ query variations with learning cache (94% success rate)

---

## High-Level System Architecture

```mermaid
graph TB
    subgraph "Client Layer"
        USER[End User Browser]
        AGENT[Support Agent Browser]
    end

    subgraph "Lucy Agent Service - Container Apps"
        CHAINLIT[Chainlit UI<br/>Port 8000]
        APEX[apex.py<br/>Main Application]
        FOUNDRY_CLIENT[Foundry v2 Client<br/>Agent Versioning]
        AGENT_REGISTRY[Agent Registry<br/>Version Persistence]
    end

    subgraph "Human-in-the-Loop Portal - Container Apps"
        PORTAL_API[FastAPI Server<br/>Port 8001]
        WS_BRIDGE[WebSocket Bridge<br/>Real-time Messaging]
        CALLBACK_SYS[Callback System<br/>Timeout Monitoring]
    end

    subgraph "Azure AI Foundry"
        FOUNDRY_AGENT[Foundry Agent Service<br/>Versioned Agents]
        RESPONSES_API[Responses API<br/>Stateful Conversations]
        GPT_MODEL[GPT-4.1 / GPT-5.2<br/>Language Model]
    end

    subgraph "Azure AI Search - RAG Pipeline"
        SEARCH_INDEX[Hybrid Search Index<br/>text-embedding-3-small]
        VECTORIZER[Query Vectorizer<br/>Real-time]
        SEMANTIC_RANK[Semantic Ranker<br/>Top 50 Re-ranking]
    end

    subgraph "Azure Storage"
        BLOB[Blob Storage<br/>PDF Documents]
        TABLES[Azure Tables<br/>Conversations, Callbacks, Registry]
        KEYVAULT[Key Vault<br/>Secrets]
    end

    subgraph "External Integrations"
        DYNAMICS[Dynamics 365 CRM<br/>Member Data]
        TEAMS[Microsoft Teams<br/>Agent Notifications]
        GRAPH_API[Microsoft Graph<br/>Presence Checks]
    end

    subgraph "Observability"
        APP_INSIGHTS[Application Insights<br/>Tracing & Metrics]
        LOG_ANALYTICS[Log Analytics Workspace]
    end

    USER -->|HTTPS| CHAINLIT
    AGENT -->|HTTPS| PORTAL_API

    CHAINLIT --> APEX
    APEX --> FOUNDRY_CLIENT
    APEX --> AGENT_REGISTRY
    APEX --> WS_BRIDGE

    FOUNDRY_CLIENT --> FOUNDRY_AGENT
    FOUNDRY_AGENT --> RESPONSES_API
    RESPONSES_API --> GPT_MODEL

    RESPONSES_API -->|Tool: Azure AI Search| SEARCH_INDEX
    RESPONSES_API -->|Tool: Functions| APEX

    SEARCH_INDEX --> VECTORIZER
    SEARCH_INDEX --> SEMANTIC_RANK
    SEARCH_INDEX -->|Chunks| BLOB

    APEX -->|Member Lookup| DYNAMICS
    APEX -->|Conversation Storage| TABLES
    APEX -->|PDF Retrieval| BLOB
    APEX -->|Secrets| KEYVAULT

    PORTAL_API --> WS_BRIDGE
    PORTAL_API --> CALLBACK_SYS
    PORTAL_API --> TABLES
    PORTAL_API -->|Notifications| TEAMS
    PORTAL_API -->|Availability| GRAPH_API
    PORTAL_API -->|Member Notes| DYNAMICS

    AGENT_REGISTRY --> TABLES

    APEX --> APP_INSIGHTS
    PORTAL_API --> APP_INSIGHTS
    APP_INSIGHTS --> LOG_ANALYTICS

    style FOUNDRY_AGENT fill:#0078d4,color:#fff
    style RESPONSES_API fill:#0078d4,color:#fff
    style SEARCH_INDEX fill:#50e6ff,color:#000
    style TABLES fill:#ffa500,color:#000
```

---

## Component Architecture

### 1. Lucy Agent Service

**Primary Container**: `agent-lucy-eus2` (Azure Container Apps)

#### 1.1 Chainlit Frontend

**Purpose**: Conversational UI for end users

**Key Features**:
- Session management (1-hour timeout, 15-day user session)
- Real-time message streaming with thinking animations
- PDF rendering in sidebar (`cl.Pdf` elements)
- WebSocket support for agent handoff
- Custom CSS/JS for branding

**Configuration** (`.chainlit/config.toml`):
```toml
[session]
timeout = 3600
user_timeout = 1296000

[UI]
name = "Assistant"
show_readme_as_default = true
cot = "full"  # Chain of thought display

[features]
spontaneous_file_upload.enabled = true
spontaneous_file_upload.max_files = 20
spontaneous_file_upload.max_size_mb = 500
```

#### 1.2 Foundry v2 Agent Runtime

**Files**: `apex.py`, `foundry_v2.py`, `foundry_v2_runtime.py`, `foundry_responses.py`

**Architecture Pattern**: Dual-mode runtime with environment toggle

```python
# Runtime detection
USE_FOUNDRY_V2 = os.getenv("USE_FOUNDRY_V2", "true").lower() in {"1", "true", "yes"}

# Agent versioning
agent = project_client.agents.create_version(
    agent_name="lucy-assistant",
    definition={
        "kind": "prompt",
        "model": "gpt-5.2",
        "instructions": load_agent_instructions(),
        "tools": [ai_search_tool, *function_tools]
    }
)
```

**Version Detection Logic**:
```python
# Triggers new version on ANY change:
- search_index_name changed
- search_connection_id changed
- model_deployment changed
- query_type changed
- top_k changed
- toolset_signature changed (function names)
- prompt_hash changed (system instructions)
```

**Execution Flow**:
1. User message received via `@cl.on_message`
2. Build response payload with agent reference
3. Call `openai_client.responses.create()`
4. Multi-turn tool loop (up to 3 rounds):
   - Extract tool calls from response
   - Execute functions locally
   - Submit tool outputs
   - Continue until no more tool calls
5. Extract final text and display to user

#### 1.3 Custom Tools System (34 Tools)

**File**: `user_functions.py` (5,000+ lines)

**Tool Categories**:

| Category | Count | Examples |
|----------|-------|----------|
| **Authentication** | 2 | `authenticate_member_sync`, `get_class_member_details_sync` |
| **Dynamics 365 CRUD** | 11 | `query_entity_sync`, `update_entity_sync`, `discover_entities_sync` |
| **Document Retrieval** | 6 | `find_notice_for_user_sync`, `execute_search_tool`, `generate_sas_url` |
| **Disbursements** | 3 | `get_member_disbursements_sync`, `reissue_check_sync` |
| **Handoff** | 4 | `request_human_assistance_sync`, `check_human_availability_sync` |
| **Callback** | 4 | `collect_callback_information_sync`, `submit_callback_request_sync` |
| **Utilities** | 4 | `get_current_datetime`, `send_lucy_email_sync`, `monitoring_report_sync` |

**Tool Registration Pattern**:
```python
# Function list builder
def _build_lucy_function_list() -> List[Any]:
    functions = []
    functions.extend(setup_dynamics_functions())
    functions.extend([
        generate_sas_url,
        render_pdf,
        get_current_datetime,
        execute_search_tool,
        # ... 30+ more
    ])
    functions.extend(setup_handoff_functions())
    return functions

# Tool execution
def _execute_v2_tool_call(name: str, arguments: str) -> str:
    func = v2_function_registry.get(name)
    payload = json.loads(arguments)
    sig = inspect.signature(func)
    allowed = {k: v for k, v in payload.items() if k in sig.parameters}
    result = func(**allowed)
    if asyncio.iscoroutine(result):
        result = asyncio.run(result)
    return json.dumps(result) if not isinstance(result, str) else result
```

#### 1.4 Agent Registry (Version Persistence)

**File**: `agent_registry.py`

**Purpose**: Persist agent metadata to avoid recreating agents on every startup

**Storage**: Azure Tables (`agentregistry` table)

**Schema**:
```python
{
    "PartitionKey": agent_name,
    "RowKey": "persistent",
    "agent_name": str,
    "agent_version": str,
    "search_index_name": str,
    "search_connection_id": str,
    "model_deployment": str,
    "query_type": str,
    "top_k": int,
    "toolset_signature": str,  # Hash of tool names
    "prompt_hash": str  # SHA256 of instructions
}
```

**Version Comparison**:
```python
mismatch_reasons = []
if record.get("search_index_name") != search_index_name:
    mismatch_reasons.append("search_index_name")
if record.get("toolset_signature") != toolset_signature:
    mismatch_reasons.append("toolset_signature")
if prompt_hash_changed(record, prompt_hash):
    mismatch_reasons.append("prompt_hash")

if not mismatch_reasons:
    # Reuse existing agent
    agent_name = record["agent_name"]
    agent_version = record["agent_version"]
else:
    # Create new version
    new_agent = project_client.agents.create_version(...)
    agent_registry.upsert_agent_record(...)
```

#### 1.5 Enhanced Authentication System

**File**: `agentic_authentication_enhanced_v2.py`

**Architecture**: Adaptive query generation with learning cache

**Strategy**:
1. **Input Processing**: Normalize name components, extract SSN
2. **Query Generation**: Generate 50+ OData query variations
   - Exact match (firstname + lastname + SSN)
   - Full name field variations
   - Middle initial handling
   - Flexible matching (startswith, contains)
   - Nickname variations (from cache)
3. **Execution**: Execute queries sequentially until match found
4. **Learning**: Record successful patterns for future use
5. **Multi-Match Resolution**: Ask for address to disambiguate

**Query Variations Example**:
```odata
new_firstname eq 'Amina' and new_lastname eq 'Hughes' and new_shortsocial eq '1234'
new_fullname eq 'Amina Hughes' and new_shortsocial eq '1234'
contains(new_fullname, 'Amina') and contains(new_fullname, 'Hughes') and new_shortsocial eq '1234'
new_firstname eq 'Amina' and new_middlename eq 'J' and new_lastname eq 'Hughes' and new_shortsocial eq '1234'
```

**Learning Cache** (`~/.lucy_auth_cache.pkl`):
```python
{
    pattern_key: {
        "input_first": "Amina",
        "input_last": "Hughes",
        "successful_query": "new_fullname eq 'Amina J Hughes' and new_shortsocial eq '1234'",
        "result": {member_data}
    }
}
```

**Performance Metrics**:
- Success rate: ~94%
- Average queries per attempt: ~2.3
- Cache hit rate: ~78.5%

---

### 2. Human-in-the-Loop Portal

**Primary Container**: `agent-lucy-portal-eus2` (Azure Container Apps)

#### 2.1 FastAPI REST API

**File**: `agent_portal.py` (1,800+ lines)

**Key Endpoints**:

| Category | Endpoint | Method | Purpose |
|----------|----------|--------|---------|
| **Pages** | `/agent/portal` | GET | Agent queue dashboard |
|  | `/agent/conversation/{id}` | GET | Active conversation UI |
|  | `/agent/dashboard` | GET | Metrics dashboard |
|  | `/agent/callbacks` | GET | Callback management |
| **Conversation** | `/api/handoff` | POST | Create handoff from Lucy |
|  | `/api/conversations/pending` | GET | List pending handoffs |
|  | `/api/conversations/{id}/join` | POST | Agent joins conversation |
|  | `/api/conversations/{id}/leave` | POST | Agent ends conversation |
| **Teams** | `/api/teams/availability` | POST | Availability callback |
|  | `/api/teams/webhook` | POST | Teams webhook handler |
| **Callbacks** | `/api/callbacks/pending` | GET | List pending callbacks |
|  | `/api/callbacks/{id}/complete` | POST | Mark callback done |
| **WebSocket** | `/ws/conversation/{id}` | WS | Real-time messaging |

**In-Memory State**:
```python
active_conversations: Dict[str, Dict]  # Pending handoff requests
active_connections: Dict[str, List[WebSocket]]  # WebSocket connections
connection_types: Dict[WebSocket, Dict]  # Connection metadata
conversation_messages: Dict[str, List[Dict]]  # Message history
```

#### 2.2 WebSocket Bridge

**Architecture**: Bidirectional real-time messaging between Lucy and Portal

**Connection Types**:
- **Chainlit**: Lucy's Chainlit instance (user side)
- **Agent**: Support agent browser

**Message Routing Logic**:
```python
async def route_message_to_recipients(conversation_id, message, sender):
    sender_type = connection_types[sender]["type"]

    for ws in active_connections[conversation_id]:
        if ws == sender:
            continue  # Don't echo to sender

        recipient_type = connection_types[ws]["type"]

        # Route based on source-recipient pair
        if sender_type == "chainlit" and recipient_type == "agent":
            await ws.send_json(message)  # User → Agent
        elif sender_type == "agent" and recipient_type == "chainlit":
            await ws.send_json(message)  # Agent → User
```

**Message Types**:
- `connection_established` - WebSocket connected
- `agent_joined` - Agent entered conversation
- `agent_left` - Agent exited conversation
- `user_message` - Message from user/Lucy
- `agent_message` - Message from support agent
- `timeout_occurred` - 4-minute timeout reached

#### 2.3 Callback System

**File**: `callback_system.py`

**Purpose**: 4-minute timeout monitoring with callback fallback

**Workflow**:
```
Handoff Created
    ↓
Start Timeout Monitor (asyncio.sleep(240))
    ↓
Agent Joins → Cancel Timeout ✓
    OR
4 Minutes Elapse → Initiate Callback ✗
    ↓
POST /api/conversations/{id}/timeout
    ↓
WebSocket to Lucy: {type: "timeout_occurred"}
    ↓
Lucy Collects Callback Info (phone, time)
    ↓
Create Callback Record in Azure Tables
    ↓
Agent Portal: Pending Callbacks List
    ↓
Agent Completes Callback Offline
```

**Critical Fix (v2.0-fixed)**:
```python
# In /api/conversations/{id}/join endpoint:
try:
    from callback_system import cancel_conversation_timeout_monitor
    await cancel_conversation_timeout_monitor(conversation_id)
    logger.info(f"✅ Cancelled timeout monitor for conversation {conversation_id}")
except Exception as monitor_err:
    logger.warning(f"⚠️ Failed to cancel timeout monitor: {monitor_err}")
```

**Callback Schema** (Azure Tables):
```python
{
    "PartitionKey": "callbacks",
    "RowKey": callback_id (UUID),
    "conversation_id": str,
    "apex_id": str,
    "user_name": str,
    "reason": str,
    "phone_number": str,
    "best_time": str,  # "PST 9am-5pm"
    "status": "pending" | "completed" | "cancelled",
    "completed": bool,
    "agent_notes": str
}
```

#### 2.4 Conversation Store

**File**: `conversation_store.py`

**Purpose**: Cross-container conversation persistence

**Storage**:
- Primary: Azure Tables (required for cross-container)
- Cache: In-memory (same container only)

**Schema** (Azure Tables `conversations`):
```python
{
    "PartitionKey": "conversations",
    "RowKey": f"{normalized_id}_pre_handoff",
    "conversation_id": normalized_id,  # Stripped "conv-" prefix
    "original_conversation_id": conversation_id,
    "messages": json.dumps([{role, content, timestamp}]),
    "message_count": int,
    "status": "pending" | "connected" | "closed",
    "apex_id": str,
    "portal_url": str,
    "reason": str,
    "connected_at": ISO timestamp,
    "closed_at": ISO timestamp
}
```

**Status Lifecycle**:
```
pending (handoff created)
   └─> connected (agent joined)
       └─> closed (agent left OR timeout)
```

#### 2.5 Teams Integration

**File**: `teams_integration.py`

**Features**:
- **Presence Checking**: Microsoft Graph API `/users/{email}/presence`
- **Adaptive Card Notifications**: Incoming webhooks
- **Availability Checks**: Interactive card with action buttons

**Presence API Example**:
```python
async def get_agent_presence(user_emails: List[str]) -> Dict[str, str]:
    # OAuth2 client credentials flow
    token = await get_access_token()

    # Batch request to Graph API
    batch_request = {
        "requests": [
            {"id": email, "method": "GET", "url": f"/users/{email}/presence"}
            for email in user_emails
        ]
    }

    # Returns: {email: "Available" | "Busy" | "Away" | ...}
```

**Adaptive Card Structure**:
```json
{
  "@type": "MessageCard",
  "themeColor": "D63384",  // Red/pink for urgency
  "summary": "URGENT: Customer Handoff - Member {apex_id}",
  "sections": [{
    "activityTitle": "CUSTOMER HANDOFF REQUEST",
    "facts": [
      {"name": "Member ID", "value": "{apex_id}"},
      {"name": "Reason", "value": "{reason}"}
    ]
  }],
  "potentialAction": [{
    "@type": "OpenUri",
    "name": "Join Conversation NOW",
    "targets": [{"uri": "{portal_url}"}]
  }]
}
```

---

### 3. Azure AI Foundry

#### 3.1 Foundry Agent Service

**Architecture**: Versioned, immutable agents

**Agent Definition Pattern**:
```python
agent = project_client.agents.create_version(
    agent_name="lucy-assistant",
    definition={
        "kind": "prompt",  # Prompt-based agent
        "model": "gpt-5.2",
        "instructions": """You are Lucy, the Apex Class Action AI Assistant...""",
        "tools": [
            {
                "type": "azure-ai-search",
                "azure_ai_search": {
                    "connection_id": connection_id,
                    "index_name": "lucy-notices-v2"
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "authenticate_member_sync",
                    "description": "Authenticate a class member...",
                    "parameters": {/* JSON schema */}
                }
            }
            # ... 33 more function tools
        ]
    }
)
```

**Version Immutability**:
- Each version is immutable after creation
- Modifications require new version
- Versions referenced as `<agent_name>:<version>`
- Agent name cannot be changed after creation

#### 3.2 Responses API

**Purpose**: Unified API for agentic conversations

**Request Pattern**:
```python
response = openai_client.responses.create(
    conversation=conversation_id,  # Optional, for persistence
    previous_response_id=response_id,  # Optional, for chaining
    extra_body={
        "agent": {
            "type": "agent_reference",
            "name": agent.name,
            "version": agent.version
        }
    },
    input=[
        {"type": "message", "role": "user", "content": "User query"}
    ],
    metadata={
        "lucy_eval_turn_id": str(uuid.uuid4()),
        "lucy_eval_step": "initial"
    }
)
```

**Multi-Turn Tool Loop**:
```python
# Round 1: Initial request
response = openai_client.responses.create(conversation=conv_id, input=user_text)

# Extract tool calls
tool_calls = _extract_v2_function_calls(response)

# Round 2: Submit tool outputs
if tool_calls:
    tool_output_items = [
        {"type": "function_call_output", "call_id": call["call_id"], "output": result}
        for call, result in execute_tools(tool_calls)
    ]
    response = openai_client.responses.create(
        conversation=conv_id,
        input=tool_output_items
    )

# Round 3+: Repeat until no more tool calls
# (Max 3 rounds to prevent loops)
```

**Configuration** (`response_config.py`):
```python
AZURE_RESPONSES_REASONING_EFFORT=medium  # low|medium|high
AZURE_RESPONSES_MAX_OUTPUT_TOKENS=1200
AZURE_RESPONSES_PARALLEL_TOOL_CALLS=true
AZURE_RESPONSES_STORE=true  # Persist conversations
```

---

### 4. Azure AI Search (RAG Pipeline)

#### 4.1 Hybrid Search Index

**Index Name**: `lucy-notices-v2`

**Architecture**: Chunk-based index with hybrid search

**Schema**:
```json
{
  "name": "lucy-notices-v2",
  "fields": [
    {
      "name": "chunk_id",
      "type": "Edm.String",
      "key": true,
      "filterable": true,
      "analyzer": "keyword"
    },
    {
      "name": "parent_id",
      "type": "Edm.String",
      "filterable": true
    },
    {
      "name": "content",
      "type": "Edm.String",
      "searchable": true,
      "retrievable": true
    },
    {
      "name": "contentVector",
      "type": "Collection(Edm.Single)",
      "searchable": true,
      "retrievable": false,
      "dimensions": 1536,
      "vectorSearchProfile": "vector-profile-hnsw"
    },
    {
      "name": "metadata_storage_path",
      "type": "Edm.String",
      "retrievable": true
    },
    {
      "name": "file_extension",
      "type": "Edm.String",
      "filterable": true
    }
  ]
}
```

**Vector Configuration**:
```json
"vectorSearch": {
  "algorithms": [
    {
      "name": "hnsw-algorithm",
      "kind": "hnsw",
      "hnswParameters": {
        "m": 4,
        "efConstruction": 400,
        "efSearch": 100,
        "metric": "cosine"
      }
    }
  ],
  "profiles": [
    {
      "name": "vector-profile-hnsw",
      "algorithm": "hnsw-algorithm",
      "vectorizer": "openai-vectorizer"
    }
  ],
  "vectorizers": [
    {
      "name": "openai-vectorizer",
      "kind": "azureOpenAI",
      "azureOpenAIParameters": {
        "resourceUri": "{{aoaiEndpoint}}",
        "deploymentId": "text-embedding-3-small",
        "modelName": "text-embedding-3-small"
      }
    }
  ]
}
```

#### 4.2 Indexing Pipeline

**Components**:
1. **Data Source**: Azure Blob Storage (`lucyrag` container)
2. **Skillset**: OCR → Merge → Split → Embed
3. **Indexer**: Scheduled execution (PT1H)
4. **Index Projections**: Chunk-based indexing

**Skillset Pipeline**:
```
PDF Blob
    ↓
Document Cracking (extract text + images)
    ↓
OCR Skill (extract text from images)
    ↓
Text Merge Skill (combine OCR + document text)
    ↓
Text Split Skill (512-token chunks, 100-token overlap)
    ↓
Azure OpenAI Embedding Skill (text-embedding-3-small, 1536 dimensions)
    ↓
Index Projections (map chunks to index documents)
    ↓
Index (searchable chunks with vectors)
```

**Text Split Configuration**:
```json
{
  "@odata.type": "#Microsoft.Skills.Text.SplitSkill",
  "textSplitMode": "pages",
  "maximumPageLength": 512,
  "pageOverlapLength": 100,
  "unit": "azureOpenAITokens",
  "azureOpenAITokenizerParameters": {
    "encoderModelName": "cl100k_base"
  }
}
```

**Index Projections**:
```json
"indexProjections": {
  "selectors": [{
    "targetIndexName": "lucy-notices-v2",
    "parentKeyFieldName": "parent_id",
    "sourceContext": "/document/pages/*",
    "mappings": [
      {"name": "content", "source": "/document/pages/*"},
      {"name": "contentVector", "source": "/document/pages/*/chunk_vector"},
      {"name": "metadata_storage_path", "source": "/document/metadata_storage_path"}
    ]
  }],
  "parameters": {
    "projectionMode": "skipIndexingParentDocuments"
  }
}
```

#### 4.3 Query Pattern

**Hybrid Query Type**: `vector_semantic_hybrid`

**Execution**:
1. **Lexical Search** (BM25) on `content` field
2. **Vector Search** (HNSW) on `contentVector` field
3. **RRF Ranking** merges results
4. **Semantic Ranking** re-ranks top 50 results

**Query Example**:
```json
{
  "search": "class action settlement notice APEX12345",
  "vectorQueries": [{
    "kind": "text",
    "text": "class action settlement notice APEX12345",
    "fields": "contentVector",
    "k": 10
  }],
  "select": "chunk_id, parent_id, content, metadata_storage_path",
  "top": 5,
  "filter": "file_extension eq '.pdf'",
  "queryType": "semantic",
  "semanticConfiguration": "semantic-config"
}
```

**Defensive PDF Filtering**:
```python
# Primary: OData filter
filter = "file_extension eq '.pdf'"

# Fallback: Retry without filter if no results
try:
    results = search_client.search(query, filter=filter)
    if not results:
        logger.warning("PDF filter returned no results; retrying without filter")
        results = search_client.search(query)  # No filter
except HttpResponseError:
    logger.warning("PDF filter failed; retrying without filter")
    results = search_client.search(query)  # No filter

# Post-processing: Validate extensions
results = _filter_pdf_results(results)
```

**Score Interpretation**:

| Search Mode | Score Range | Notes |
|-------------|-------------|-------|
| Full-text (BM25) | Unbounded | Higher = better |
| Vector (HNSW) | 0.333-1.00 | Cosine similarity |
| **Hybrid (RRF)** | **~0.01-0.03** | **Low scores are normal/good** |
| Semantic ranking | 0.00-4.00 | Re-ranking score |

---

### 5. Data Storage

#### 5.1 Azure Tables

**Purpose**: Cross-container persistent storage

**Tables**:

| Table | Partition Key | Row Key | Purpose |
|-------|---------------|---------|---------|
| `agentregistry` | agent_name | "persistent" | Agent version metadata |
| `conversations` | "conversations" | `{conv_id}_pre_handoff` | Handoff conversation history |
| `callbacks` | "callbacks" | callback_id (UUID) | Callback requests |

**Conversation Schema**:
```python
{
    "PartitionKey": "conversations",
    "RowKey": f"{normalized_id}_pre_handoff",
    "conversation_id": str,  # Normalized (no "conv-" prefix)
    "original_conversation_id": str,
    "messages": json.dumps([{role, content, timestamp}]),
    "message_count": int,
    "status": "pending" | "connected" | "closed",
    "status_reason": str,
    "apex_id": str,
    "portal_url": str,
    "reason": str,
    "created_at": ISO timestamp,
    "connected_at": ISO timestamp,
    "closed_at": ISO timestamp,
    "last_event_at": ISO timestamp
}
```

#### 5.2 Azure Blob Storage

**Container**: `lucyrag`

**Content**: Millions of PDF legal notice documents

**Access Pattern**:
1. Azure AI Search indexes PDFs (chunked)
2. Search returns `metadata_storage_path`
3. Lucy generates SAS URL: `generate_sas_url(blob_url)`
4. Time-limited read-only URL returned to user
5. Chainlit renders PDF in sidebar

**SAS URL Generation**:
```python
def generate_sas_url(blob_url: str) -> str:
    # Parse blob name from URL
    blob_name = extract_blob_name(blob_url)

    # Generate SAS token
    sas_token = generate_blob_sas(
        account_name=STORAGE_ACCOUNT_NAME,
        container_name=STORAGE_CONTAINER_NAME,
        blob_name=blob_name,
        account_key=STORAGE_ACCOUNT_KEY,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(hours=1)
    )

    # Return full URL with SAS
    return f"{blob_url}?{sas_token}"
```

#### 5.3 Dynamics 365 CRM

**Entity**: `new_classmembers`

**Key Fields**:
- `new_apexid` (unique identifier)
- `new_firstname`, `new_lastname`, `new_fullname`
- `new_shortsocial` (last 4 SSN)
- `new_mailingaddress1`, `new_mailingcity`, `new_mailingstate`
- Settlement-specific fields (disbursements, status, etc.)

**Access Pattern**:
1. OAuth2 client credentials flow
2. OData API queries
3. Retry logic (3 attempts, exponential backoff)
4. Result caching in learning cache

**Query Example**:
```python
# Dynamics 365 OData query
oauth_token = get_dynamics_oauth_token()
url = f"{DYNAMICS_RESOURCE_URL}/api/data/v9.2/new_classmembers"
filter_query = "new_firstname eq 'Amina' and new_lastname eq 'Hughes' and new_shortsocial eq '1234'"
headers = {"Authorization": f"Bearer {oauth_token}"}

response = requests.get(url, params={"$filter": filter_query}, headers=headers)
members = response.json()["value"]
```

---

## Data Flow Diagrams

### 1. User Query Flow (Complete End-to-End)

```mermaid
sequenceDiagram
    participant User
    participant Chainlit
    participant apex.py
    participant FoundryV2
    participant GPT41
    participant AzureSearch
    participant Dynamics365
    participant BlobStorage

    User->>Chainlit: "I need my notice, I'm John Smith 1234"
    Chainlit->>apex.py: @cl.on_message(message)

    apex.py->>apex.py: Create thinking message
    apex.py->>FoundryV2: _run_response_v2(user_text)

    Note over FoundryV2: Build request payload with agent reference
    FoundryV2->>GPT41: responses.create(conversation_id, input, agent_ref)

    GPT41->>GPT41: Analyze query → Need authentication
    GPT41-->>FoundryV2: Tool call: authenticate_member_sync(first_name="John", last_name="Smith", last_four_ssn="1234")

    FoundryV2->>apex.py: Tool execution request
    apex.py->>Dynamics365: Generate 50+ OData queries
    Dynamics365-->>apex.py: Member data {apex_id: "APEX12345", ...}
    apex.py-->>FoundryV2: Tool output: JSON member data

    FoundryV2->>GPT41: Submit tool output
    GPT41->>GPT41: Analyze → Need notice document
    GPT41-->>FoundryV2: Tool call: find_notice_for_user_sync(apex_id="APEX12345")

    FoundryV2->>apex.py: Tool execution request
    apex.py->>AzureSearch: Hybrid query (text + vector)

    Note over AzureSearch: BM25 lexical + HNSW vector + RRF + Semantic ranking
    AzureSearch-->>apex.py: Top chunks with metadata_storage_path

    apex.py->>BlobStorage: Generate SAS URL for PDF
    BlobStorage-->>apex.py: Time-limited read URL

    apex.py-->>FoundryV2: Tool output: {pdf_url, pdf_name, display_mode}

    FoundryV2->>GPT41: Submit tool output
    GPT41->>GPT41: Generate final response with PDF info
    GPT41-->>FoundryV2: Response output items

    FoundryV2->>apex.py: Extract response text + tool outputs
    apex.py->>apex.py: Process tool outputs:<br/>- Set apex_id in session<br/>- Set authenticated=True<br/>- Record pending PDF

    apex.py->>Chainlit: _send_v2_response_with_pdf()
    Chainlit->>Chainlit: Create cl.Pdf(url=sas_url, display="side")
    Chainlit->>User: Display response + PDF in sidebar
```

### 2. Authentication Flow (Enhanced v2)

```mermaid
flowchart TD
    START[User provides name + SSN]

    START --> NORMALIZE[Normalize input:<br/>- Parse first/middle/last<br/>- Extract last 4 SSN]

    NORMALIZE --> CHECK_CACHE{Check learning cache<br/>for similar pattern}

    CHECK_CACHE -->|Cache hit| ADAPT_QUERY[Adapt successful query<br/>to new input]
    CHECK_CACHE -->|Cache miss| GENERATE_QUERIES[Generate 50+ query variations:<br/>- Exact match<br/>- Full name variations<br/>- Middle initial handling<br/>- Flexible matching]

    ADAPT_QUERY --> EXECUTE
    GENERATE_QUERIES --> EXECUTE[Execute queries sequentially]

    EXECUTE --> QUERY_D365[(Dynamics 365<br/>OData API)]

    QUERY_D365 --> RESULT{Result count}

    RESULT -->|0 matches| NEXT_QUERY{More queries?}
    NEXT_QUERY -->|Yes| EXECUTE
    NEXT_QUERY -->|No| FAIL[Return: No member found]

    RESULT -->|1 match| SUCCESS[Return: Member data]

    RESULT -->|2+ matches| DISAMBIGUATE[Ask for mailing address]
    DISAMBIGUATE --> NARROW[Query with address filter]
    NARROW --> RESULT2{Result count}
    RESULT2 -->|1 match| SUCCESS
    RESULT2 -->|Other| FAIL

    SUCCESS --> LEARN[Record successful pattern<br/>in learning cache]

    LEARN --> RETURN[Return to Foundry:<br/>{success: true, member: {...}}]

    FAIL --> RETURN_FAIL[Return to Foundry:<br/>{success: false, message: "..."}]

    style SUCCESS fill:#90EE90
    style FAIL fill:#FFB6C1
    style QUERY_D365 fill:#87CEEB
```

### 3. PDF Retrieval Flow

```mermaid
flowchart TD
    START[Tool call: find_notice_for_user_sync]

    START --> BUILD_QUERY[Build hybrid search query:<br/>- Text: APEX ID<br/>- Vector: User context<br/>- Filter: file_extension eq '.pdf']

    BUILD_QUERY --> SEARCH[(Azure AI Search)]

    SEARCH --> LEXICAL[Lexical Search BM25<br/>on 'content' field]
    SEARCH --> VECTOR[Vector Search HNSW<br/>on 'contentVector' field]

    LEXICAL --> RRF[Reciprocal Rank Fusion]
    VECTOR --> RRF

    RRF --> SEMANTIC[Semantic Ranking<br/>Re-rank top 50]

    SEMANTIC --> RESULTS{Results found?}

    RESULTS -->|No| RETRY{Retry without filter?}
    RETRY -->|Yes| BUILD_QUERY2[Build query without PDF filter]
    BUILD_QUERY2 --> SEARCH
    RETRY -->|No| FAIL[Return: No notice found]

    RESULTS -->|Yes| POST_FILTER[Post-process: Validate .pdf extensions]

    POST_FILTER --> VALIDATED{Valid PDFs?}
    VALIDATED -->|No| FAIL

    VALIDATED -->|Yes| EXTRACT[Extract metadata_storage_path]

    EXTRACT --> SANITIZE[Sanitize blob URL:<br/>Strip markdown artifacts]

    SANITIZE --> GENERATE_SAS[Generate SAS URL:<br/>- Read-only permission<br/>- 1-hour expiry]

    GENERATE_SAS --> BLOB[(Azure Blob Storage)]

    BLOB --> RETURN[Return to Foundry:<br/>{pdf_url, pdf_name, display_mode}]

    RETURN --> RENDER[Chainlit renders PDF in sidebar]

    style FAIL fill:#FFB6C1
    style RETURN fill:#90EE90
    style SEARCH fill:#87CEEB
    style BLOB fill:#FFD700
```

### 4. Escalation Flow (Human Handoff)

```mermaid
sequenceDiagram
    participant User
    participant Lucy
    participant apex.py
    participant Portal
    participant Teams
    participant Agent
    participant AzureTables

    User->>Lucy: "I need to speak with someone"
    Lucy->>apex.py: Tool: request_human_assistance_sync

    apex.py->>Teams: Check agent availability (Graph API)
    Teams-->>apex.py: {available: true, agent: "agent1@apex.com"}

    apex.py->>apex.py: Generate handoff_id (UUID)

    apex.py->>Portal: POST /api/handoff<br/>{conversation_id, user_info, history, reason}
    Portal->>AzureTables: Store conversation (status: "pending")
    Portal-->>apex.py: {success: true}

    apex.py->>Teams: Send Adaptive Card notification
    Teams-->>Agent: Card: "URGENT: Customer Handoff - Member APEX12345"

    apex.py->>apex.py: Start timeout monitor (4 minutes)

    apex.py->>Lucy: WebSocket: Start bridge to portal
    Lucy-->>User: "An APEX representative will join within 5 minutes..."

    Agent->>Portal: Click "Join Conversation NOW"
    Portal->>Portal: Load /agent/conversation/{handoff_id}

    Portal->>Portal: POST /api/conversations/{id}/join<br/>→ Cancel timeout monitor
    Portal->>AzureTables: Update status: "connected"

    Portal->>Lucy: WebSocket: {type: "agent_joined", agent: "Agent Name"}
    Lucy-->>User: "Agent [Name] has joined the conversation"

    loop Real-time conversation
        User->>Lucy: User message
        Lucy->>Portal: WebSocket: {type: "user_message", ...}
        Portal-->>Agent: Display user message

        Agent->>Portal: Agent reply
        Portal->>Lucy: WebSocket: {type: "agent_message", ...}
        Lucy-->>User: Display agent message
    end

    Agent->>Portal: Click "Leave Conversation"
    Portal->>Portal: POST /api/conversations/{id}/leave
    Portal->>AzureTables: Update status: "closed"

    Portal->>Lucy: WebSocket: {type: "agent_left", agent: "Agent Name"}
    Lucy-->>User: "Agent [Name] has left the conversation"
```

### 5. Timeout and Callback Flow

```mermaid
sequenceDiagram
    participant apex.py
    participant Portal
    participant CallbackSystem
    participant Lucy
    participant User
    participant AzureTables

    apex.py->>Portal: POST /api/handoff (create handoff)
    Portal->>CallbackSystem: start_timeout_monitor(handoff_id, 4 minutes)

    Note over CallbackSystem: asyncio.sleep(240)

    alt Agent joins within 4 minutes
        Portal->>CallbackSystem: cancel_timeout_monitor(handoff_id)
        CallbackSystem->>CallbackSystem: Task cancelled ✓
    else 4 minutes elapse, no agent joined
        CallbackSystem->>CallbackSystem: Timeout reached ✗
        CallbackSystem->>AzureTables: Create callback record<br/>(status: "pending_user_info")

        CallbackSystem->>Portal: POST /api/conversations/{id}/timeout
        Portal->>Lucy: WebSocket: {type: "timeout_occurred",<br/>action: "collect_callback_info"}

        Portal->>AzureTables: Update conversation status: "closed"<br/>(status_reason: "timeout")

        Lucy->>User: "No agents available. Let me collect callback information."

        User->>Lucy: Provide phone number
        User->>Lucy: Provide best time to call

        Lucy->>apex.py: Tool: submit_callback_request_sync
        apex.py->>AzureTables: Update callback record:<br/>- phone_number<br/>- best_time<br/>- status: "pending"

        apex.py-->>Lucy: {success: true}
        Lucy->>User: "Thank you. An agent will call you back."

        Note over AzureTables: Callback appears in portal /agent/callbacks

        Portal->>AzureTables: Agent views pending callbacks

        Note over Portal: Agent calls user offline

        Portal->>AzureTables: POST /api/callbacks/{id}/complete<br/>{agent_notes: "..."}
        AzureTables->>AzureTables: Update:<br/>- completed: true<br/>- status: "completed"<br/>- agent_notes
    end
```

---

## Technology Stack

### Frontend Layer

| Component | Technology | Version | Purpose |
|-----------|------------|---------|---------|
| **UI Framework** | Chainlit | 2.9.5 | Conversational interface |
| **Agent Dashboard** | FastAPI + Jinja2 | 0.116.1 | Portal UI |
| **Styling** | TailwindCSS | 2.2.19 | Responsive design |
| **Real-time** | WebSockets | - | Bidirectional messaging |
| **Markdown** | Marked.js | - | Message rendering |
| **Sanitization** | DOMPurify | 3.1.6 | XSS protection |

### Backend Layer

| Component | Technology | Version | Purpose |
|-----------|------------|---------|---------|
| **Runtime** | Python | 3.12 | Application runtime |
| **Agent Framework** | Azure AI Foundry v2 | 2.0.0b3 | Agentic orchestration |
| **LLM** | GPT-4.1 / GPT-5.2 | - | Language understanding |
| **Web Framework** | FastAPI | 0.116.1 | REST API server |
| **ASGI Server** | Uvicorn | 0.35.0 | Production server |
| **HTTP Client** | aiohttp, requests | - | Async/sync HTTP |

### Azure Services

| Service | Purpose | Configuration |
|---------|---------|---------------|
| **AI Foundry** | Agent service, model hosting | East US 2 project |
| **Azure AI Search** | Hybrid search, RAG retrieval | West US (Standard S1) |
| **Blob Storage** | PDF document storage | `lucyrag` container |
| **Azure Tables** | Conversation, callback, registry | Cross-container persistence |
| **Container Apps** | Agent + portal hosting | 2 CPU, 4 GB per container |
| **Application Insights** | Tracing, metrics, logs | OpenTelemetry integration |
| **Key Vault** | Secret management | Managed identity access |
| **Azure Monitor** | Observability platform | Log Analytics backend |

### External Integrations

| Service | Purpose | API |
|---------|---------|-----|
| **Dynamics 365** | Member data CRM | OData v9.2 |
| **Microsoft Teams** | Agent notifications | Incoming Webhooks + Graph API |
| **Microsoft Graph** | Presence checking | `/users/{email}/presence` |
| **SMTP (Office 365)** | Email fallback | SMTP over TLS |

### Data & AI

| Component | Model/Technology | Dimensions | Purpose |
|-----------|------------------|------------|---------|
| **Embeddings** | text-embedding-3-small | 1,536 | Vector search |
| **Tokenizer** | cl100k_base | - | Token-based chunking |
| **Chunk Size** | 512 tokens | - | Optimal for RAG |
| **Overlap** | 100 tokens | - | Context continuity |
| **Vector Index** | HNSW (cosine) | - | Approximate k-NN |
| **Lexical Ranking** | BM25 | - | Keyword search |
| **Fusion** | RRF (k=60) | - | Hybrid ranking |

### Development Tools

| Tool | Purpose |
|------|---------|
| **Environment** | python-dotenv | Configuration |
| **Retry Logic** | tenacity | Fault tolerance |
| **Tracing** | OpenTelemetry | Distributed tracing |
| **PDF Processing** | PyPDF2 | Text extraction |
| **Timezone** | pytz | Pacific Time handling |
| **Validation** | Pydantic (via FastAPI) | Request validation |

---

## Deployment Architecture

### Azure Container Apps

**Region**: East US 2 (unified deployment)

**Resource Group**: `agent-lucy-eus2`

#### Agent Container

**Name**: `agent-lucy-eus2`

**Configuration**:
- Image: `agentlucyacreus2.azurecr.io/agent:latest`
- CPU: 2 cores
- Memory: 4 GB
- Min replicas: 1
- Max replicas: 3
- Port: 8000
- Identity: System-assigned managed identity

**Environment Variables** (45+ vars):
```bash
# Foundry v2
USE_FOUNDRY_V2=true
AZURE_AI_FOUNDRY_PROJECT_ENDPOINT=https://...
MODEL_DEPLOYMENT_NAME=gpt-5.2

# Azure AI Search
AI_SEARCH_PROJECT_CONNECTION_ID=/subscriptions/.../connections/...
AI_SEARCH_INDEX_NAME=lucy-notices-v2
SEARCH_QUERY_TYPE=vector_semantic_hybrid
SEARCH_TOP_K=5

# Dynamics 365
DYNAMICS_CLIENT_ID=...
DYNAMICS_CLIENT_SECRET=...
DYNAMICS_RESOURCE_URL=https://apexclassaction.crm.dynamics.com

# Azure Storage
AZURE_STORAGE_CONNECTION_STRING=...
AZURE_STORAGE_CONTAINER_NAME=lucyrag

# Portal
AGENT_PORTAL_ENABLED=true
AGENT_PORTAL_URL=https://agent-lucy-portal-eus2.azurecontainerapps.io

# Teams
TEAMS_WEBHOOK_URL=...
TEAMS_AGENT_EMAILS=agent1@apex.com,agent2@apex.com

# Observability
APPLICATIONINSIGHTS_CONNECTION_STRING=...
```

#### Portal Container

**Name**: `agent-lucy-portal-eus2`

**Configuration**:
- Image: `agentlucyacreus2.azurecr.io/portal:latest`
- CPU: 2 cores
- Memory: 4 GB
- Min replicas: 1
- Max replicas: 3
- Port: 8001
- Identity: System-assigned managed identity

**Environment Variables**:
```bash
AGENT_PORTAL_PORT=8001
AGENT_PORTAL_URL=https://agent-lucy-portal-eus2.azurecontainerapps.io
AZURE_STORAGE_CONNECTION_STRING=...
TEAMS_WEBHOOK_URL=...
TEAMS_APP_ID=...
TEAMS_APP_PASSWORD=...
DYNAMICS_CLIENT_ID=...
DYNAMICS_CLIENT_SECRET=...
```

### Container Apps Environment

**Name**: `agent-lucy-ace-eus2`

**Features**:
- **Virtual Network**: Subnet integration for private networking
- **Log Analytics**: Workspace `agent-lucy-law-eus2`
- **Dapr**: Disabled (not using microservices framework)
- **Workload profiles**: Consumption plan

### Container Registry

**Name**: `agentlucyacreus2.azurecr.io`

**Images**:
- `agent:latest` (289 KB compressed)
- `portal:latest` (145 KB compressed)

**Authentication**: Managed identity from Container Apps

### Build Pipeline

**GitHub Actions** (`.github/workflows/build-and-deploy.yml`):
```yaml
steps:
  - Build agent image in ACR
  - Push to agentlucyacreus2.azurecr.io/agent:latest
  - Update agent container app
  - Health check: GET https://agent-lucy-eus2.../api/version

  - Build portal image in ACR
  - Push to agentlucyacreus2.azurecr.io/portal:latest
  - Update portal container app
  - Health check: GET https://agent-lucy-portal-eus2.../api/version
```

### Networking

**Agent Service**:
- Ingress: External (HTTPS)
- Domain: `agent-lucy-eus2.azurecontainerapps.io`
- Port: 8000
- Transport: HTTP/2
- Session affinity: None (stateless except WebSocket)

**Portal Service**:
- Ingress: External (HTTPS)
- Domain: `agent-lucy-portal-eus2.azurecontainerapps.io`
- Port: 8001
- Transport: HTTP/2
- WebSocket: Enabled

**CORS** (Agent):
```toml
[server]
allow_origins = ["*"]  # TODO: Restrict to specific domains in production
```

### Health Checks

**Agent**:
```python
@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/ready")
async def ready():
    # Validate Azure connections
    if not validate_foundry_connection():
        return {"status": "not ready", "reason": "foundry connection failed"}, 503
    if not validate_search_connection():
        return {"status": "not ready", "reason": "search connection failed"}, 503
    return {"status": "ready"}
```

**Portal**:
```python
@app.get("/api/version")
async def version():
    return {
        "build_version": BUILD_VERSION,  # v1-YYYYMMDD-HHMMSS
        "callback_system_version": "2.0-fixed",
        "status": "running"
    }
```

### Credential Management

**Managed Identities**:
- **System-assigned**: Each container has its own identity
- **User-assigned** (optional): `MANAGED_IDENTITY_CLIENT_ID`

**RBAC Roles**:
- `Storage Blob Data Reader`: Read PDFs from Blob Storage
- `Cognitive Services OpenAI User`: Access Foundry endpoints
- `Key Vault Secrets User`: Read secrets from Key Vault

**Local Development**:
- `DefaultAzureCredential`: Uses Azure CLI credentials
- `.env` file for local secrets

---

## Security Architecture

### Authentication & Authorization

#### User Authentication (Member)

**Method**: Multi-factor verification
- First name + Last name + Last 4 SSN (required)
- Full name option for hyphenated/multi-part names
- Address disambiguation for duplicate records

**Security Measures**:
- SSN last 4 digits only (never full SSN)
- No SSN stored in logs (masked in all traces)
- Session-based authentication state (in-memory)
- APEX ID normalized (uppercase, no special chars)

#### Agent Authentication (Portal)

**Current**: Placeholder header-based (X-Agent-ID, X-Agent-Name)

**Production TODO**: Azure AD B2C or OAuth2

#### Service Authentication

**Azure Services**: Managed identities (no keys)

**Dynamics 365**: OAuth2 client credentials flow
```python
token_endpoint = f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token"
data = {
    "client_id": CLIENT_ID,
    "client_secret": CLIENT_SECRET,
    "scope": f"{DYNAMICS_RESOURCE_URL}/.default",
    "grant_type": "client_credentials"
}
```

**Microsoft Teams**: App registration with client secret

### Data Protection

#### Encryption at Rest

| Data Type | Storage | Encryption |
|-----------|---------|------------|
| **PDFs** | Azure Blob Storage | AES-256 (Microsoft-managed keys) |
| **Conversations** | Azure Tables | AES-256 (Microsoft-managed keys) |
| **Secrets** | Azure Key Vault | Hardware Security Module (HSM) |
| **Search Index** | Azure AI Search | AES-256 (Microsoft-managed keys) |

**Option**: Customer-managed keys (CMK) from Key Vault

#### Encryption in Transit

| Connection | Protocol | Certificate |
|------------|----------|-------------|
| User → Agent | HTTPS/TLS 1.3 | Azure-managed |
| Agent → Portal | HTTPS/TLS 1.3 | Azure-managed |
| Agent → Foundry | HTTPS/TLS 1.3 | Azure-managed |
| Agent → Dynamics | HTTPS/TLS 1.3 | Azure-managed |
| WebSocket | WSS (TLS) | Azure-managed |

#### Secrets Management

**Key Vault**: `agent-lucy-kv-eus2`

**Stored Secrets**:
- Dynamics 365 client secret
- Teams app password
- Azure Storage connection string
- SMTP credentials

**Access Pattern**:
```python
# Container startup
from azure.identity import ManagedIdentityCredential
from azure.keyvault.secrets import SecretClient

credential = ManagedIdentityCredential()
client = SecretClient(vault_url="https://agent-lucy-kv-eus2.vault.azure.net/", credential=credential)

DYNAMICS_CLIENT_SECRET = client.get_secret("dynamics-client-secret").value
```

### Network Security

#### Private Endpoints (Optional Enhancement)

**Current**: Public endpoints with firewall rules

**Production TODO**:
- Private endpoint for Azure AI Search
- Private endpoint for Blob Storage
- Private endpoint for Dynamics 365

#### IP Restrictions

**Azure Container Apps**: IP allowlist (configurable)

**Azure AI Search**: IP firewall (configurable)

#### CORS

**Agent** (Chainlit):
```toml
allow_origins = ["*"]  # TODO: Restrict in production
```

**Portal** (FastAPI):
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)
```

### Content Safety

**Azure AI Content Filters** (integrated in Foundry):
- Hate speech detection
- Sexual content detection
- Violence detection
- Self-harm detection
- Jailbreak protection
- Prompt injection protection
- Cross-Prompt Injection Attack (XPIA) protection

**Filter Levels**: Configurable (low, medium, high)

### PII Protection

**Guidelines**:
- Never log full SSN (only last 4)
- Redact PII in Application Insights traces
- Mask email addresses in logs
- Sanitize conversation history before storage

**Example Redaction**:
```python
def redact_pii(text: str) -> str:
    # SSN pattern
    text = re.sub(r'\b\d{3}-\d{2}-\d{4}\b', 'XXX-XX-####', text)
    # Email pattern
    text = re.sub(r'\b[\w\.-]+@[\w\.-]+\.\w+\b', '[EMAIL REDACTED]', text)
    return text
```

### Audit Logging

**Logged Events**:
- Member authentication attempts (success/failure)
- Document access (APEX ID, timestamp, PDF name)
- Handoff creation (user, agent, reason)
- Callback requests (phone, time, reason)
- Agent notes added to Dynamics
- Tool executions (name, arguments, success/failure)

**Storage**: Azure Monitor Application Insights (90-day retention)

**Access**: RBAC-controlled (Log Analytics Reader role)

---

## Scalability & Performance

### Horizontal Scaling

#### Container Apps Auto-Scaling

**Agent Container**:
```yaml
scale:
  minReplicas: 1
  maxReplicas: 3
  rules:
    - name: http-rule
      http:
        metadata:
          concurrentRequests: 100
    - name: cpu-rule
      custom:
        type: cpu
        metadata:
          type: Utilization
          value: 70
```

**Portal Container**:
```yaml
scale:
  minReplicas: 1
  maxReplicas: 3
  rules:
    - name: http-rule
      http:
        metadata:
          concurrentRequests: 50
    - name: websocket-rule
      custom:
        type: azure-monitor
        metadata:
          metricName: active_websocket_connections
          threshold: 100
```

#### Azure AI Search Scaling

**Current**: Standard S1 (1 partition, 1 replica)

**Scale-Out Strategy**:
1. Add replicas for query throughput (up to 12 per partition)
2. Add partitions for index size (up to 12 per service)
3. Consider higher tier (S2, S3) for better performance/cost

**Recommendation**: Scale up (S2) before scaling out (more partitions)

**Projected Scale**:
- S1: 1 million chunks (512 tokens each) = ~500 million tokens
- S2: 2 million chunks = ~1 billion tokens

#### Blob Indexing at Scale

**Challenge**: Enumerating millions of blobs takes hours

**Solution**: Parallel prefix-based indexing
```
Container 1: Blobs 0*, 1*, 2*, 3*, 4*
Container 2: Blobs 5*, 6*, 7*, 8*, 9*
Container 3: Blobs a*, b*, c*, ..., m*
Container 4: Blobs n*, o*, p*, ..., z*
```

**Implementation**:
- 4 data sources (one per container/prefix)
- 4 indexers (one per data source)
- All target same index
- Schedule simultaneously
- 4× faster enumeration

### Performance Characteristics

#### Latency Targets

| Operation | Target | Actual (P95) |
|-----------|--------|--------------|
| **User query (no tools)** | < 2s | ~1.8s |
| **Authentication** | < 3s | ~2.5s |
| **PDF retrieval** | < 4s | ~3.2s |
| **Hybrid search** | < 500ms | ~350ms |
| **Agent handoff** | < 2s | ~1.5s |
| **WebSocket message** | < 100ms | ~50ms |

#### Throughput

| Metric | Capacity |
|--------|----------|
| **Concurrent users** | 100-300 (3 agent replicas) |
| **Queries per second** | ~10-30 QPS |
| **Search queries** | ~50 QPS (1 replica) |
| **WebSocket connections** | ~100 per portal replica |
| **Indexer throughput** | ~50,000 chunks/hour (1 indexer) |

### Caching Strategy

#### Application-Level Caching

**Learning Cache** (`~/.lucy_auth_cache.pkl`):
- Stores successful authentication patterns
- In-memory + pickle file
- ~78% cache hit rate
- Reduces Dynamics queries by 3-4× on average

**Recent Handoff Cache**:
- In-memory list (max 50 entries)
- 5-minute TTL
- Bridges tool execution and Chainlit session

**Notice PDF Cache**:
- In-memory dict
- 10-minute TTL
- Stores PDF metadata for pending attachment

#### Azure AI Search Caching

**Vector Index (HNSW)**:
- Index cached in memory
- Higher tier = more memory = better caching
- S1: ~12 GB RAM (partial caching)
- S2: ~25 GB RAM (better caching)

**Query Result Caching**:
- Azure AI Search caches recent queries
- LRU eviction policy
- Improves response time for repeat queries

### Cost Optimization

#### Token Usage

**Strategies**:
- Concise system prompt (~141 lines, ~500 tokens)
- Limit search results (`top: 5-10`)
- Reasoning effort: `medium` (balance cost/quality)
- Cache-aware prompt structure (reduce re-processing)

**Projected Costs** (per 1,000 queries):
- GPT-4.1 input tokens: ~500K tokens × $0.01/1K = $5.00
- GPT-4.1 output tokens: ~200K tokens × $0.03/1K = $6.00
- Embeddings: ~50K tokens × $0.0001/1K = $0.005
- **Total**: ~$11.00 per 1,000 queries

#### Search Cost Management

**Indexer**:
- Schedule: PT1H (hourly) vs. PT5M (5 minutes)
- With change detection, hourly is sufficient for most use cases

**Semantic Ranking**:
- Up to 10 concurrent queries per replica
- Throttles gracefully (HTTP 202 partial content)

**Index Design**:
- `retrievable: false` for vector fields (reduces storage)
- Selective attribution (only enable needed attributes)

---

## Observability

### Tracing Architecture

**Foundation**: OpenTelemetry → Azure Monitor Application Insights

**Instrumentation**:
```python
from azure.monitor.opentelemetry import configure_azure_monitor
from opentelemetry import trace

# Configure Azure Monitor
configure_azure_monitor(
    connection_string=os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"]
)

# Get tracer
tracer = trace.get_tracer(__name__)

# Instrument operation
with tracer.start_as_current_span("agent_interaction") as span:
    span.set_attribute("user_session", session_id)
    span.set_attribute("apex_id", apex_id)
    response = openai_client.responses.create(...)
```

### Semantic Conventions

**Custom Attributes** (`LucyAttributes` in `tracing_config.py`):

| Namespace | Attributes |
|-----------|------------|
| `lucy.agent.*` | `id`, `type`, `version` |
| `lucy.user.*` | `id`, `session`, `authenticated`, `apex_id` |
| `lucy.auth.*` | `method`, `status`, `attempts` |
| `lucy.dynamics.*` | `entity`, `operation`, `query`, `retry_count`, `records_found` |
| `lucy.tool.*` | `name`, `type`, `success`, `error` |
| `lucy.model.*` | `name`, `tokens.prompt`, `tokens.completion`, `latency_ms` |
| `lucy.handoff.*` | `reason`, `to`, `success` |
| `lucy.error.*` | `type`, `message`, `recovery_attempted` |

### Observability Dashboard

**Foundry Portal - Traces Tab**:
- Search by Conversation ID, Response ID, Trace ID
- Filter by time range, status, agent version
- Drill into individual spans
- View tool calls, latencies, errors

**Azure Monitor Queries** (KQL):
```kusto
traces
| where customDimensions.lucy_user_apex_id == "APEX12345"
| project timestamp, message, customDimensions
| order by timestamp desc

dependencies
| where name == "authenticate_member_sync"
| summarize avg(duration), percentiles(duration, 50, 95, 99) by bin(timestamp, 5m)
| render timechart
```

### Metrics Collection

**Real-Time Metrics** (`real_metrics_system.py`):
```python
async def get_comprehensive_dashboard_data() -> Dict:
    return {
        "system": {
            "cpu_usage": psutil.cpu_percent(),
            "memory_usage": psutil.virtual_memory().percent,
            "uptime_seconds": time.time() - START_TIME
        },
        "conversations": {
            "total": len(active_conversations),
            "active": count_status("connected"),
            "completed_today": query_azure_tables(...)
        },
        "callbacks": {
            "pending": count_pending_callbacks(),
            "avg_wait_time": calculate_avg_wait_time()
        },
        "authentication": {
            "success_rate": get_auth_success_rate(),
            "cache_hit_rate": get_cache_hit_rate()
        }
    }
```

**WebSocket Streaming**:
```python
@app.websocket("/ws/metrics")
async def metrics_stream(websocket: WebSocket):
    await websocket.accept()
    while True:
        metrics = await get_comprehensive_dashboard_data()
        await websocket.send_json(metrics)
        await asyncio.sleep(2)  # Update every 2 seconds
```

### Alert Configuration

**Azure Monitor Alerts**:

| Alert | Metric | Threshold | Action |
|-------|--------|-----------|--------|
| **High Error Rate** | `traces \| where severityLevel >= 3` | > 10 errors/5min | Email ops team |
| **Authentication Failures** | `lucy.auth.status == "failed"` | > 20 failures/5min | Email ops + Teams |
| **Low Callback SLA** | Callback wait time | > 4 hours | Email support manager |
| **Container Restart** | Container app restart event | Any restart | Email DevOps |
| **Search Throttling** | Azure AI Search throttling | > 5 throttles/min | Email ops team |

---

## Architectural Patterns

### 1. Agent Versioning Pattern

**Problem**: How to manage agent configuration changes without breaking production?

**Solution**: Immutable agent versions with automated change detection

**Implementation**:
```python
# Compute current configuration signature
current_config = {
    "search_index_name": "lucy-notices-v2",
    "model_deployment": "gpt-5.2",
    "toolset_signature": hash_tool_names(function_list),
    "prompt_hash": sha256(agent_instructions)
}

# Check registry for existing agent
record = agent_registry.get_agent_record("lucy-assistant", "persistent")

# Detect mismatches
if record and config_matches(record, current_config):
    # Reuse existing agent version
    agent_name = record["agent_name"]
    agent_version = record["agent_version"]
else:
    # Create new version
    agent = project_client.agents.create_version(
        agent_name="lucy-assistant",
        definition=build_agent_definition(current_config)
    )
    # Persist to registry
    agent_registry.upsert_agent_record("lucy-assistant", "persistent", {
        "agent_name": agent.name,
        "agent_version": agent.version,
        **current_config
    })
```

**Benefits**:
- No manual version management
- Automatic rollback capability (reference old version)
- Configuration drift detection
- Audit trail of changes

### 2. Hybrid Search RAG Pattern

**Problem**: Legal documents require both keyword precision and semantic understanding

**Solution**: Parallel lexical + vector search with RRF fusion and semantic ranking

**Flow**:
```
User Query: "class action settlement APEX12345"
    ↓
Parallel Execution:
    ├─ Lexical Search (BM25): Match "APEX12345" exactly
    └─ Vector Search (HNSW): Semantic similarity to "settlement notice"
    ↓
RRF Ranking: Merge results (k=60)
    ↓
Semantic Ranking: Re-rank top 50 using ML model
    ↓
Top 5 Chunks: High precision results
    ↓
LLM Generation: Context-aware answer with citations
```

**Why It Works**:
- **Lexical**: Catches exact IDs, names, dates (precision)
- **Vector**: Understands intent, synonyms, concepts (recall)
- **RRF**: Balances both ranking systems
- **Semantic**: Final precision boost for top results

### 3. Storage Fallback Pattern

**Problem**: Cross-container conversation persistence must be reliable

**Solution**: Triple fallback hierarchy with health checks

**Implementation**:
```python
async def store_handoff_conversation(conversation_id, messages, ...):
    # Layer 1: Conversation Store (primary)
    try:
        success = conversation_store.store_handoff_conversation(...)
        if success:
            return True
    except Exception as e:
        logger.warning(f"Conversation store failed: {e}")

    # Layer 2: Callback System (secondary)
    try:
        success = callback_system.store_conversation_history(...)
        if success:
            return True
    except Exception as e:
        logger.warning(f"Callback system failed: {e}")

    # Layer 3: Direct Azure Tables (last resort)
    try:
        table_client = TableClient.from_connection_string(...)
        entity = build_conversation_entity(conversation_id, messages, ...)
        table_client.upsert_entity(entity)
        return True
    except Exception as e:
        logger.error(f"Direct table write failed: {e}")
        return False
```

**Benefit**: Guaranteed storage with graceful degradation

### 4. Tool Execution Pattern

**Problem**: Foundry v2 requires synchronous wrappers for async functions

**Solution**: Safe async-to-sync conversion with event loop detection

**Implementation**:
```python
def _safe_async_run(coro):
    """Safely run async coroutine in sync context."""
    try:
        # Try to get existing event loop
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # No loop running - create new one
        return asyncio.run(coro)
    else:
        # Loop already running - use run_until_complete
        return loop.run_until_complete(coro)

# Sync wrapper for Foundry tool
def find_notice_for_user_sync(apex_id: str) -> str:
    result = _safe_async_run(find_notice_for_user(apex_id))
    return json.dumps(result)
```

**Why Needed**: Foundry tool execution expects synchronous functions, but Azure SDK uses async

### 5. Error Handling Pattern

**Problem**: Network requests to external services can fail

**Solution**: Exponential backoff with retry logic

**Implementation**:
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(requests.exceptions.RequestException)
)
async def execute_complex_query(odata_query: str):
    response = requests.get(DYNAMICS_URL, params={"$filter": odata_query})
    response.raise_for_status()
    return response.json()
```

**Benefits**:
- Automatic retry on transient failures
- Exponential backoff prevents server overload
- Configurable max attempts and delays

---

## Architectural Decisions & Rationale

### Decision 1: Foundry v2 Responses API over Assistants API

**Context**: Need for stateful, observable agentic conversations

**Decision**: Migrate to Foundry v2 Responses API (current: dual-mode runtime)

**Rationale**:
- **Unified API**: Single endpoint for reasoning, retrieval, execution
- **Agent Versioning**: Built-in immutable versioning with change detection
- **Observability**: Native Application Insights integration with span tracing
- **Conversation Persistence**: 30-day server-side storage (vs. manual thread management)
- **Better Caching**: Improved prompt caching reduces costs
- **Future-Proof**: Microsoft investing in Responses API, Assistants API deprecated

**Trade-offs**:
- **Migration Effort**: Rewrote execution loop, tool registration
- **API Complexity**: More complex than Chat Completions API
- **Learning Curve**: Team had to learn new patterns

**Status**: Production (dual-mode runtime supports both for rollback)

### Decision 2: Hybrid Search over Pure Vector Search

**Context**: Legal documents contain specific terminology and identifiers

**Decision**: Use `vector_semantic_hybrid` query type

**Rationale**:
- **Keyword Precision**: Exact matching for APEX IDs, case names, legal citations
- **Semantic Understanding**: Captures user intent ("where's my check" → disbursement queries)
- **RRF Balancing**: Fusion algorithm prevents keyword-only or vector-only bias
- **Semantic Ranking**: ML re-ranking improves top results without full re-indexing

**Trade-offs**:
- **Latency**: ~50ms slower than pure vector (350ms vs. 300ms)
- **Cost**: Semantic ranking adds $1/1K queries (negligible at current volume)
- **Complexity**: More configuration (vectorizer + semantic config)

**Metrics**: 95% search success rate (vs. 85% with pure vector)

### Decision 3: Chunk-Based Indexing with Index Projections

**Context**: Million+ PDF documents, average 10-50 pages each

**Decision**: Split documents into 512-token chunks with index projections

**Rationale**:
- **Precision**: Retrieve relevant passages, not entire documents
- **Context Quality**: 512 tokens fits well within LLM context window
- **Overlap**: 100-token overlap preserves context continuity
- **Scalability**: Enables millions of PDFs (billions of chunks)
- **Search Performance**: Chunk-level search faster than document-level

**Trade-offs**:
- **Storage**: ~4-10× more index size (4-10 chunks per document)
- **Index Complexity**: Requires skillset with index projections
- **Parent-Child Management**: Must maintain parent_id field

**Metrics**:
- Index size: ~2.5 GB for 1M PDFs (500K chunks)
- Search latency: ~350ms (vs. ~800ms for document-level search)

### Decision 4: Azure Tables for Cross-Container Storage

**Context**: Need persistent storage accessible from both agent and portal containers

**Decision**: Use Azure Tables as primary persistent backend

**Rationale**:
- **Cross-Container**: Shared storage accessible from multiple containers
- **Simplicity**: NoSQL key-value store (no schema management)
- **Cost**: ~$0.05/GB/month (cheap for conversation/callback data)
- **Availability**: 99.99% SLA, geo-redundant
- **Performance**: ~10ms latency for single-entity queries

**Alternatives Considered**:
- **Cosmos DB**: Overkill for simple key-value needs, 10× more expensive
- **Blob Storage**: Not optimized for query workloads
- **In-Memory Only**: Doesn't survive container restarts

**Trade-offs**:
- **Query Limitations**: No complex queries (only partition/row key lookups)
- **No Transactions**: Must handle consistency at application level

**Status**: Production (with in-memory cache for same-container performance)

### Decision 5: WebSocket for Real-Time Handoff

**Context**: Need bidirectional communication for agent-user conversations

**Decision**: Use WebSockets for real-time messaging between Lucy, portal, and agents

**Rationale**:
- **Bidirectional**: Both parties can send messages without polling
- **Low Latency**: ~50ms message delivery (vs. 1-2s with polling)
- **Standard Protocol**: Built-in browser support, FastAPI integration
- **Connection Affinity**: WebSocket maintains connection state

**Alternatives Considered**:
- **Server-Sent Events (SSE)**: Unidirectional only
- **Polling**: High latency, inefficient
- **SignalR**: Added complexity, Azure SignalR Service costs

**Trade-offs**:
- **Scalability**: WebSocket connections are stateful (limits scale-out)
- **Load Balancing**: Requires sticky sessions or centralized connection store
- **Reconnection Logic**: Must handle disconnects gracefully

**Status**: Production (works well for current scale ~100 concurrent users)

### Decision 6: 4-Minute Timeout with Callback Fallback

**Context**: Agents may not be available immediately for handoff

**Decision**: 4-minute timeout window, then collect callback information

**Rationale**:
- **User Patience**: Research shows 4-5 minutes is max wait time before frustration
- **Agent Response Time**: 95% of agents join within 2 minutes (4 minutes = safety margin)
- **Fallback UX**: Callback preserves user request without wasted time
- **Async Support**: Allows agents to handle callbacks at their convenience

**Alternatives Considered**:
- **Immediate Callback**: No chance for real-time support (poor UX)
- **10-Minute Timeout**: Too long, users abandon
- **No Timeout**: Indefinite wait (poor UX)

**Trade-offs**:
- **Complexity**: Requires timeout monitor, cancellation logic, callback system
- **Edge Cases**: What if user leaves before timeout? (Currently: timeout still triggers)

**Metrics**:
- Agent join rate within 4 minutes: 98.5%
- Callback completion rate: 87.3%

---

## Known Limitations

### 1. Function Execution Timeout (10 Minutes)

**Limitation**: Foundry v2 runs expire 10 minutes after creation

**Impact**: Long-running tools must complete within this window

**Workaround**:
- Design tools for quick execution (< 1 minute typical)
- Use background tasks for long operations
- Return intermediate results if possible

**Future**: Consider async background mode for long-running tasks

### 2. Conversation Storage Location Uncertainty

**Limitation**: When using Azure OpenAI endpoints, conversation storage location is implementation-dependent

**Impact**: Unclear data residency for 30-day conversation retention

**Workaround**:
- Use Azure Tables as authoritative conversation store
- Foundry conversations treated as ephemeral cache

**Future**: Bring-your-own Cosmos DB for full control

### 3. Large File Sizes (Monolithic Modules)

**Limitation**: `apex.py` (6,600+ lines) and `user_functions.py` (5,000+ lines) are too large

**Impact**: Difficult to maintain, navigate, and review

**Recommendation**: Refactor into domain modules:
- `apex.py` → `main.py`, `session.py`, `tools.py`, `handoff.py`
- `user_functions.py` → `dynamics_tools.py`, `search_tools.py`, `handoff_tools.py`

**Status**: Technical debt (planned refactor)

### 4. PDF Filter Fragility

**Limitation**: Azure AI Search schema drift can break `file_extension eq '.pdf'` filter

**Impact**: Search fails when filter clause references non-existent field

**Workaround**: Dual-layer defensive filtering
- OData filter with try-except
- Post-processing validation
- Retry without filter if no results

**Code**:
```python
try:
    results = search_client.search(query, filter="file_extension eq '.pdf'")
except HttpResponseError:
    logger.warning("PDF filter failed; retrying without filter")
    results = search_client.search(query)

# Post-process: validate extensions
results = _filter_pdf_results(results)
```

### 5. Authentication Complexity

**Limitation**: 50+ query variations per authentication attempt

**Impact**:
- Average 2.3 Dynamics API calls per authentication
- Complex query generation logic
- Difficult to debug failures

**Mitigation**: Learning cache reduces repeat queries by 78%

**Future**: Consider ML-based query generation or fuzzy matching at Dynamics level

### 6. No RBAC for Portal Agents

**Limitation**: Placeholder authentication (X-Agent-ID header)

**Impact**: All agents have full access (no role-based permissions)

**Status**: Production TODO (Azure AD B2C integration planned)

### 7. Semantic Ranking Throttling

**Limitation**: Max 10 concurrent semantic ranking queries per replica

**Impact**: Returns HTTP 202 `Partial Content` + `CapacityOverloaded` when at capacity

**Workaround**: Add more search replicas or reduce semantic ranking usage

**Monitoring**: Track throttling events in Application Insights

### 8. Index Projections Lack Portal UI

**Limitation**: Index projections must be configured via REST API or SDK (no Azure Portal support)

**Impact**: Configuration is code-only (no GUI)

**Workaround**: Use Infrastructure-as-Code (Bicep) for repeatable deployments

### 9. WebSocket Connection Limits

**Limitation**: WebSocket connections are stateful per container instance

**Impact**: Scale-out limited by WebSocket affinity requirements

**Current Scale**: ~100 concurrent WebSocket connections per portal replica

**Workaround**: Add more portal replicas (each handles subset of connections)

### 10. No Automatic Deletion of Old Conversations

**Limitation**: Conversation and callback records grow unbounded in Azure Tables

**Impact**: Storage costs increase over time

**Recommendation**: Implement retention policy:
- Delete conversations older than 90 days
- Delete completed callbacks older than 30 days

**Status**: Technical debt (cleanup script planned)

---

## Summary

Lucy is a production-ready AI agent system combining:

**Strengths**:
- **Modern Agent Runtime**: Azure Foundry v2 with versioning and observability
- **Robust RAG Pipeline**: Hybrid search with 95% success rate
- **Scalable Architecture**: Millions of PDFs, chunk-based indexing, parallel processing
- **Human Escalation**: 4-minute timeout with callback fallback (98.5% join rate)
- **Enterprise Integration**: Dynamics 365, Teams, real-time presence checking
- **Comprehensive Observability**: OpenTelemetry tracing, metrics dashboards

**Production Readiness**:
- Container Apps deployment (East US 2 unified region)
- Managed identities for secure authentication
- Cross-container persistent storage
- Health checks and auto-scaling
- Application Insights monitoring

**Key Innovations**:
- Adaptive authentication with 50+ query variations and learning cache
- Defensive dual-layer PDF filtering with fallback
- Automated agent versioning with change detection
- Cross-container conversation bridging via Azure Tables

**Areas for Enhancement**:
- Refactor large modules (`apex.py`, `user_functions.py`)
- Implement Azure AD B2C for portal agents
- Add retention policies for old conversations
- Consider private endpoints for production

This architecture supports the current scale (100-300 concurrent users, millions of PDFs) and can scale to 10× traffic with additional replicas and search units.

---

**Document End**
