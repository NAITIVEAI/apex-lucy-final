import os
import json
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
import uuid

# Try to import Azure dependencies with graceful fallback
try:
    from azure.data.tables import TableServiceClient, TableEntity
    from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
    AZURE_TABLES_AVAILABLE = True
except ImportError as e:
    logging.warning(f"Azure Tables SDK not available: {e}")
    AZURE_TABLES_AVAILABLE = False
    TableServiceClient = None
    TableEntity = None
    ResourceExistsError = Exception
    ResourceNotFoundError = Exception

# Setup logging
logger = logging.getLogger("CallbackSystem")

# Azure Tables configuration
STORAGE_CONNECTION_STRING = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
CALLBACKS_TABLE_NAME = "callbacks"
CONVERSATION_HISTORY_TABLE_NAME = "conversations"

class CallbackSystem:
    """
    Manages callback requests and conversation history using Azure Tables
    """

    def __init__(self):
        # Initialize with defaults
        self.table_service = None
        self.callbacks_table = None
        self.conversations_table = None
        self.timeout_tasks: Dict[str, asyncio.Task] = {}

        # In-memory fallback storage for local development
        self._memory_callbacks: Dict[str, Dict] = {}
        self._memory_conversations: Dict[str, List[Dict]] = {}
        self._use_memory_fallback = False

        if not AZURE_TABLES_AVAILABLE:
            logger.warning("Azure Tables SDK not available - using in-memory fallback")
            self._use_memory_fallback = True
            return

        if not STORAGE_CONNECTION_STRING:
            logger.warning("AZURE_STORAGE_CONNECTION_STRING not configured - using in-memory fallback")
            self._use_memory_fallback = True
            return

        try:
            self.table_service = TableServiceClient.from_connection_string(STORAGE_CONNECTION_STRING)
            self.callbacks_table = self.table_service.get_table_client(CALLBACKS_TABLE_NAME)
            self.conversations_table = self.table_service.get_table_client(CONVERSATION_HISTORY_TABLE_NAME)

            # Initialize tables
            self._init_tables()

            logger.info("✅ Callback system initialized with Azure Tables")
        except Exception as e:
            logger.error(f"Failed to initialize Azure Tables: {e}")
            self.table_service = None
            self.callbacks_table = None
            self.conversations_table = None

    def _init_tables(self):
        """Initialize Azure Tables if they don't exist"""
        if not self.table_service:
            logger.warning("Skipping table initialization - Azure Tables not available")
            return

        try:
            self.callbacks_table.create_table()
            logger.info("✅ Callbacks table created/verified")
        except ResourceExistsError:
            logger.info("✅ Callbacks table already exists")
        except Exception as e:
            logger.error(f"❌ Failed to create callbacks table: {e}")

        try:
            self.conversations_table.create_table()
            logger.info("✅ Conversations table created/verified")
        except ResourceExistsError:
            logger.info("✅ Conversations table already exists")
        except Exception as e:
            logger.error(f"❌ Failed to create conversations table: {e}")

    async def start_timeout_monitor(self, conversation_id: str, user_info: Dict[str, Any], reason: str):
        """
        Start monitoring a conversation for 4-minute timeout

        Args:
            conversation_id: Unique conversation identifier
            user_info: User information including apex_id
            reason: Reason for the handoff request
        """
        logger.info(f"🕐 Starting 4-minute timeout monitor for conversation {conversation_id}")

        # Cancel any existing timeout for this conversation
        if conversation_id in self.timeout_tasks:
            self.timeout_tasks[conversation_id].cancel()

        # Start new timeout task
        task = asyncio.create_task(
            self._monitor_conversation_timeout(conversation_id, user_info, reason)
        )
        self.timeout_tasks[conversation_id] = task

    async def cancel_timeout_monitor(self, conversation_id: str):
        """Cancel timeout monitoring for a conversation (when agent joins)"""
        if conversation_id in self.timeout_tasks:
            self.timeout_tasks[conversation_id].cancel()
            del self.timeout_tasks[conversation_id]
            logger.info(f"✅ Cancelled timeout monitor for conversation {conversation_id}")

    async def _monitor_conversation_timeout(self, conversation_id: str, user_info: Dict[str, Any], reason: str):
        """
        Monitor conversation and trigger callback request after 4 minutes
        """
        try:
            # Wait for 4 minutes (240 seconds)
            await asyncio.sleep(240)

            logger.info(f"⏰ 4-minute timeout reached for conversation {conversation_id}")

            # Check if agent has joined (this should be checked via the portal API)
            # For now, we'll assume timeout was reached if we get here

            # Trigger callback request
            await self._initiate_callback_request(conversation_id, user_info, reason)

        except asyncio.CancelledError:
            logger.info(f"✅ Timeout monitor cancelled for conversation {conversation_id} (agent joined)")
        except Exception as e:
            logger.error(f"❌ Error in timeout monitor for {conversation_id}: {e}")

    async def _initiate_callback_request(self, conversation_id: str, user_info: Dict[str, Any], reason: str):
        """
        Initiate callback request process with Lucy
        """
        logger.info(f"📞 Initiating callback request for conversation {conversation_id}")

        # Store initial callback record
        await self.create_callback_request(
            conversation_id=conversation_id,
            user_info=user_info,
            reason=reason,
            status="pending_user_info"
        )

        # Signal Lucy via agent portal API that timeout occurred
        try:
            import os
            import aiohttp

            agent_portal_url = os.getenv("AGENT_PORTAL_URL", "http://localhost:8001")

            timeout_data = {
                "conversation_id": conversation_id,
                "user_info": user_info,
                "reason": reason,
                "timeout_occurred": True,
                "action": "collect_callback_info"
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{agent_portal_url}/api/conversations/{conversation_id}/timeout",
                    json=timeout_data,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    if response.status == 200:
                        logger.info(f"✅ Timeout signal sent to Lucy for conversation {conversation_id}")
                    else:
                        logger.warning(f"⚠️ Timeout signal failed with status {response.status}")

        except Exception as notify_error:
            logger.warning(f"⚠️ Could not notify Lucy of timeout: {notify_error}")
            # Continue anyway - the callback record is still created

        logger.info(f"📞 Callback request initiated for {conversation_id}")

    async def create_callback_request(self, conversation_id: str, user_info: Dict[str, Any],
                                    reason: str, phone_number: Optional[str] = None,
                                    best_time: Optional[str] = None, status: str = "pending") -> str:
        """
        Create a callback request in Azure Tables

        Args:
            conversation_id: Unique conversation identifier
            user_info: User information
            reason: Reason for callback
            phone_number: User's phone number
            best_time: Best time to call (PST 9am-5pm)
            status: Request status

        Returns:
            Callback request ID
        """
        if not self.callbacks_table:
            logger.warning("Azure Tables not available - creating fallback callback ID")
            callback_id = str(uuid.uuid4())
            logger.info(f"⚠️ Fallback callback created: {callback_id} for {user_info.get('apex_id', 'unknown')}")
            return callback_id

        try:
            callback_id = str(uuid.uuid4())

            entity = {
                'PartitionKey': "callbacks",
                'RowKey': callback_id,
                'conversation_id': conversation_id,
                'apex_id': user_info.get('apex_id', ''),
                'user_name': user_info.get('name', ''),
                'reason': reason,
                'phone_number': phone_number or '',
                'best_time': best_time or '',
                'status': status,
                'created_at': datetime.utcnow().isoformat(),
                'completed': False,
                'agent_notes': ''
            }

            self.callbacks_table.create_entity(entity)
            logger.info(f"✅ Created callback request {callback_id} for conversation {conversation_id}")

            return callback_id

        except Exception as e:
            logger.error(f"❌ Failed to create callback request: {e}")
            raise

    async def update_callback_request(self, callback_id: str, updates: Dict[str, Any]) -> bool:
        """
        Update a callback request

        Args:
            callback_id: Callback request ID
            updates: Fields to update

        Returns:
            Success status
        """
        # Use memory fallback if Azure Tables not available
        if self._use_memory_fallback:
            try:
                if callback_id in self._memory_callbacks:
                    # Update fields in memory
                    for key, value in updates.items():
                        self._memory_callbacks[callback_id][key] = value

                    self._memory_callbacks[callback_id]['updated_at'] = datetime.utcnow().isoformat()
                    logger.info(f"✅ Updated callback request {callback_id} (memory fallback)")
                    return True
                else:
                    logger.error(f"❌ Callback {callback_id} not found in memory")
                    return False
            except Exception as e:
                logger.error(f"❌ Failed to update callback request {callback_id} in memory: {e}")
                return False

        try:
            # Get existing entity
            entity = self.callbacks_table.get_entity(
                partition_key="callbacks",
                row_key=callback_id
            )

            # Update fields
            for key, value in updates.items():
                entity[key] = value

            entity['updated_at'] = datetime.utcnow().isoformat()

            # Update entity
            self.callbacks_table.update_entity(entity)
            logger.info(f"✅ Updated callback request {callback_id}")

            return True

        except Exception as e:
            logger.error(f"❌ Failed to update callback request {callback_id}: {e}")
            return False

    async def get_pending_callbacks(self) -> List[Dict[str, Any]]:
        # Use memory fallback if Azure Tables not available
        if self._use_memory_fallback:
            try:
                # Filter out completed callbacks from memory
                pending_callbacks = []
                for callback_id, callback_data in self._memory_callbacks.items():
                    if not callback_data.get("completed", False):
                        pending_callbacks.append({
                            "callback_id": callback_id,
                            "conversation_id": callback_data.get("conversation_id", ""),
                            "apex_id": callback_data.get("apex_id", ""),
                            "user_name": callback_data.get("user_name", ""),
                            "reason": callback_data.get("reason", ""),
                            "phone_number": callback_data.get("phone_number", ""),
                            "best_time": callback_data.get("best_time", ""),
                            "status": callback_data.get("status", ""),
                            "created_at": callback_data.get("created_at", ""),
                            "agent_notes": callback_data.get("agent_notes", ""),
                            "completed": callback_data.get("completed", False)
                        })
                logger.info(f"✅ Retrieved {len(pending_callbacks)} pending callbacks (memory fallback)")
                return pending_callbacks
            except Exception as e:
                logger.error(f"❌ Failed to get pending callbacks from memory: {e}")
                return []

        if not self.callbacks_table:
            logger.warning(f"Azure Tables not available - cannot retrieve callbacks")
            return []

        """
        Get all pending callback requests

        Returns:
            List of pending callbacks
        """
        try:
            entities = self.callbacks_table.query_entities(
                query_filter="PartitionKey eq 'callbacks' and completed eq false"
            )

            callbacks = []
            for entity in entities:
                callbacks.append({
                    'callback_id': entity['RowKey'],
                    'conversation_id': entity.get('conversation_id', ''),
                    'apex_id': entity.get('apex_id', ''),
                    'user_name': entity.get('user_name', ''),
                    'reason': entity.get('reason', ''),
                    'phone_number': entity.get('phone_number', ''),
                    'best_time': entity.get('best_time', ''),
                    'status': entity.get('status', ''),
                    'created_at': entity.get('created_at', ''),
                    'agent_notes': entity.get('agent_notes', ''),
                    'completed': entity.get('completed', False)
                })

            return callbacks

        except Exception as e:
            logger.error(f"❌ Failed to get pending callbacks: {e}")
            return []

    async def mark_callback_completed(self, callback_id: str, agent_notes: str = "") -> bool:
        """
        Mark a callback as completed

        Args:
            callback_id: Callback request ID
            agent_notes: Notes from the agent

        Returns:
            Success status
        """
        return await self.update_callback_request(callback_id, {
            'completed': True,
            'status': 'completed',
            'agent_notes': agent_notes,
            'completed_at': datetime.utcnow().isoformat()
        })

    async def store_conversation_history(self, conversation_id: str, conversation_type: str,
                                       messages: List[Dict[str, Any]], metadata: Dict[str, Any] = None) -> bool:
        """
        Store conversation history in Azure Tables or memory fallback

        Args:
            conversation_id: Unique conversation identifier
            conversation_type: 'pre_handoff' or 'agent_human'
            messages: List of messages
            metadata: Additional metadata

        Returns:
            Success status
        """
        # Use in-memory fallback if Azure Tables not available
        if self._use_memory_fallback:
            try:
                key = f"{conversation_id}_{conversation_type}"
                conversation_data = {
                    'conversation_id': conversation_id,
                    'conversation_type': conversation_type,
                    'messages': messages,
                    'metadata': metadata or {},
                    'created_at': datetime.utcnow().isoformat(),
                    'message_count': len(messages)
                }

                if conversation_id not in self._memory_conversations:
                    self._memory_conversations[conversation_id] = []

                # Remove existing entry of same type if exists
                self._memory_conversations[conversation_id] = [
                    conv for conv in self._memory_conversations[conversation_id]
                    if conv.get('conversation_type') != conversation_type
                ]

                self._memory_conversations[conversation_id].append(conversation_data)
                logger.info(f"✅ Stored {conversation_type} conversation history for {conversation_id} (memory fallback)")
                return True
            except Exception as e:
                logger.error(f"❌ Failed to store conversation history in memory: {e}")
                return False

        if not self.conversations_table:
            logger.warning(f"Azure Tables not available - cannot store conversation history for {conversation_id}")
            return False

        try:
            row_key = f"{conversation_id}_{conversation_type}"
            entity = {
                'PartitionKey': "conversations",
                'RowKey': row_key,
                'conversation_id': conversation_id,
                'conversation_type': conversation_type,
                'messages': json.dumps(messages),
                'metadata': json.dumps(metadata or {}),
                'created_at': datetime.utcnow().isoformat(),
                'message_count': len(messages)
            }

            logger.info(f"📝 Storing conversation with PartitionKey='conversations', RowKey='{row_key}'")
            self.conversations_table.upsert_entity(entity)
            logger.info(f"✅ Stored {conversation_type} conversation history for {conversation_id}")

            # Verify it was stored
            try:
                verify = self.conversations_table.get_entity(
                    partition_key="conversations",
                    row_key=row_key
                )
                logger.info(f"✅ Verified storage - found entity with {verify.get('message_count')} messages")
            except Exception as ve:
                logger.error(f"❌ Verification failed - could not retrieve what we just stored: {ve}")

            return True

        except Exception as e:
            logger.error(f"❌ Failed to store conversation history: {e}")
            return False

    async def get_conversation_history(self, conversation_id: str, conversation_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Get conversation history from Azure Tables or memory fallback

        Args:
            conversation_id: Unique conversation identifier
            conversation_type: Optional filter by type

        Returns:
            List of conversation records
        """
        # Use memory fallback if Azure Tables not available
        if self._use_memory_fallback:
            try:
                conversations = self._memory_conversations.get(conversation_id, [])

                if conversation_type:
                    # Filter by specific type
                    conversations = [
                        conv for conv in conversations
                        if conv.get('conversation_type') == conversation_type
                    ]

                logger.info(f"✅ Retrieved {len(conversations)} conversations for {conversation_id} (memory fallback)")
                return conversations
            except Exception as e:
                logger.error(f"❌ Failed to get conversation history from memory: {e}")
                return []

        if not self.conversations_table:
            logger.warning(f"Azure Tables not available - cannot retrieve conversation history for {conversation_id}")
            return []

        try:
            if conversation_type:
                # Get specific conversation type
                entity = self.conversations_table.get_entity(
                    partition_key="conversations",
                    row_key=f"{conversation_id}_{conversation_type}"
                )
                return [{
                    'conversation_id': entity['conversation_id'],
                    'conversation_type': entity['conversation_type'],
                    'messages': json.loads(entity['messages']),
                    'metadata': json.loads(entity.get('metadata', '{}')),
                    'created_at': entity['created_at'],
                    'message_count': entity.get('message_count', 0)
                }]
            else:
                # Get all conversations for this ID
                conversations = []

                # Try to get specific conversation types directly
                for conv_type in ['pre_handoff', 'agent_human']:
                    try:
                        row_key = f"{conversation_id}_{conv_type}"
                        logger.info(f"🔍 Looking for PartitionKey='conversations', RowKey='{row_key}'")

                        entity = self.conversations_table.get_entity(
                            partition_key="conversations",
                            row_key=row_key
                        )

                        logger.info(f"✅ Found entity with {entity.get('message_count', 0)} messages")

                        conversations.append({
                            'conversation_id': entity['conversation_id'],
                            'conversation_type': entity['conversation_type'],
                            'messages': json.loads(entity['messages']),
                            'metadata': json.loads(entity.get('metadata', '{}')),
                            'created_at': entity['created_at'],
                            'message_count': entity.get('message_count', 0)
                        })
                        logger.info(f"✅ Successfully loaded {conv_type} conversation for {conversation_id}")
                    except ResourceNotFoundError:
                        logger.info(f"🔍 No {conv_type} conversation found for {conversation_id}")
                        continue
                    except Exception as e:
                        logger.error(f"❌ Error getting {conv_type} conversation: {e}")
                        continue

                if not conversations:
                    # Fallback: Query all entities and filter
                    logger.info(f"Direct fetch failed, trying query approach for {conversation_id}")
                    try:
                        entities = self.conversations_table.query_entities(
                            query_filter="PartitionKey eq 'conversations'"
                        )

                        for entity in entities:
                            # Check if this entity belongs to our conversation
                            row_key = entity.get('RowKey', '')
                            if row_key.startswith(f"{conversation_id}_"):
                                conversations.append({
                                    'conversation_id': entity.get('conversation_id', conversation_id),
                                    'conversation_type': entity.get('conversation_type', 'unknown'),
                                    'messages': json.loads(entity.get('messages', '[]')),
                                    'metadata': json.loads(entity.get('metadata', '{}')),
                                    'created_at': entity.get('created_at', ''),
                                    'message_count': entity.get('message_count', 0)
                                })
                    except Exception as e:
                        logger.error(f"Query fallback failed: {e}")

                logger.info(f"Found {len(conversations)} total conversations for {conversation_id}")
                return conversations

        except ResourceNotFoundError:
            logger.info(f"No conversation history found for {conversation_id}")
            return []
        except Exception as e:
            logger.error(f"❌ Failed to get conversation history: {e}")
            return []

# Global instance - always create it, let it handle fallback internally
try:
    callback_system = CallbackSystem()
except Exception as e:
    logging.warning(f"Failed to initialize callback system: {e}")
    callback_system = None

# Async function wrappers for use in user_functions.py
async def start_conversation_timeout_monitor(conversation_id: str, user_info: Dict[str, Any], reason: str):
    """Start timeout monitoring for a conversation"""
    if callback_system:
        await callback_system.start_timeout_monitor(conversation_id, user_info, reason)

async def cancel_conversation_timeout_monitor(conversation_id: str):
    """Cancel timeout monitoring when agent joins"""
    if callback_system:
        await callback_system.cancel_timeout_monitor(conversation_id)

async def create_callback_request_async(conversation_id: str, user_info: Dict[str, Any],
                                      reason: str, phone_number: str, best_time: str) -> str:
    """Create callback request"""
    if callback_system:
        return await callback_system.create_callback_request(
            conversation_id, user_info, reason, phone_number, best_time, "pending"
        )
    return ""

async def get_pending_callbacks_async() -> List[Dict[str, Any]]:
    """Get pending callbacks"""
    if callback_system:
        return await callback_system.get_pending_callbacks()
    return []

async def mark_callback_completed_async(callback_id: str, agent_notes: str = "") -> bool:
    """Mark callback as completed"""
    if callback_system:
        return await callback_system.mark_callback_completed(callback_id, agent_notes)
    return False

async def store_conversation_history_async(conversation_id: str, conversation_type: str,
                                         messages: List[Dict[str, Any]], metadata: Dict[str, Any] = None) -> bool:
    """Store conversation history"""
    if callback_system:
        return await callback_system.store_conversation_history(conversation_id, conversation_type, messages, metadata)
    else:
        logger.warning("💾 Callback system not available - cannot store conversation history")
        return False

async def get_conversation_history_async(conversation_id: str, conversation_type: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get conversation history"""
    if callback_system:
        return await callback_system.get_conversation_history(conversation_id, conversation_type)
    else:
        logger.warning("💾 Callback system not available - conversation history unavailable")
        return []
