"""
Simple, reliable conversation storage system for agent handoffs.
Uses Azure Tables as primary storage with in-memory cache for the same container.
IMPORTANT: This is for cross-container communication between Lucy and Agent Portal.
"""
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any
from collections import defaultdict
import os
try:
    from azure.data.tables import UpdateMode
except Exception:
    UpdateMode = None

logger = logging.getLogger("ConversationStore")

class ConversationStore:
    """
    Simple conversation storage using Azure Tables for cross-container communication.
    Primary: Azure Tables (required for cross-container)
    Cache: In-memory for performance within same container
    """
    
    def __init__(self):
        # In-memory cache for performance (within same container only)
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.azure_available = False
        
        # Try to initialize Azure Tables if available
        try:
            if os.getenv("AZURE_STORAGE_CONNECTION_STRING"):
                from azure.data.tables import TableServiceClient
                self.table_service = TableServiceClient.from_connection_string(
                    os.getenv("AZURE_STORAGE_CONNECTION_STRING")
                )
                self.table_client = self.table_service.get_table_client("conversations")
                
                # Create table if not exists
                try:
                    self.table_client.create_table()
                except:
                    pass  # Table already exists
                    
                self.azure_available = True
                logger.info("✅ Azure Tables backup available")
        except Exception as e:
            logger.warning(f"Azure Tables not available (using memory only): {e}")
    
    @staticmethod
    def _normalize_conversation_id(conversation_id: str) -> str:
        """Normalize IDs so conv- prefixes do not break lookup between services."""
        if not conversation_id:
            return ""
        normalized = conversation_id.strip()
        if normalized.lower().startswith("conv-") and len(normalized) > 5:
            normalized = normalized[5:]
        return normalized or conversation_id
    
    def store_handoff_conversation(
        self,
        conversation_id: str,
        messages: List[Dict[str, Any]],
        apex_id: Optional[str] = None,
        status: str = "pending",
        status_reason: Optional[str] = None,
        portal_url: Optional[str] = None,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """
        Store a conversation for handoff in Azure Tables (required for cross-container access).
        
        Args:
            conversation_id: Unique ID for the conversation
            messages: List of messages with role, content, timestamp
            
        Returns:
            True if stored successfully
        """
        if not self.azure_available:
            logger.error("❌ Azure Tables not available - cannot store conversation for cross-container access")
            return False
            
        try:
            normalized_id = self._normalize_conversation_id(conversation_id)
            storage_id = normalized_id or conversation_id
            now_iso = datetime.utcnow().isoformat()

            # Store in Azure Tables (primary storage for cross-container)
            # Use same key structure as callback_system.py
            row_key = f"{storage_id}_pre_handoff"
            entity = {
                "PartitionKey": "conversations",
                "RowKey": row_key,
                "conversation_id": storage_id,
                "original_conversation_id": conversation_id,
                "conversation_type": "pre_handoff",
                "messages": json.dumps(messages),
                "message_count": len(messages),
                "created_at": now_iso,
                "metadata": json.dumps(metadata or {}),
                "status": status,
                "status_reason": status_reason or "",
                "status_updated_at": now_iso,
                "apex_id": apex_id or "",
                "portal_url": portal_url or "",
                "reason": reason or "",
                "last_event_at": now_iso,
                "connected_at": "",
                "closed_at": ""
            }
            
            self.table_client.upsert_entity(entity)
            logger.info(
                f"✅ Stored {len(messages)} messages for conversation {conversation_id}"
                + (" (normalized)" if storage_id != conversation_id else "")
                + " in Azure Tables"
            )
            
            cached_payload = {
                "id": conversation_id,
                "normalized_id": storage_id,
                "messages": messages,
                "stored_at": entity["created_at"],
                "message_count": len(messages),
                "metadata": metadata or {},
            }
            # Cache locally for performance (within same container)
            self.cache[storage_id] = cached_payload
            if storage_id != conversation_id:
                self.cache[conversation_id] = cached_payload
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to store conversation in Azure Tables: {e}")
            return False

    def update_handoff_status(
        self,
        conversation_id: str,
        status: str,
        reason: Optional[str] = None,
        connected_at: Optional[str] = None,
        closed_at: Optional[str] = None,
    ) -> bool:
        """Update handoff status fields without overwriting messages."""
        if not self.azure_available:
            return False
        try:
            normalized_id = self._normalize_conversation_id(conversation_id)
            storage_id = normalized_id or conversation_id
            row_key = f"{storage_id}_pre_handoff"
            now_iso = datetime.utcnow().isoformat()
            entity = {
                "PartitionKey": "conversations",
                "RowKey": row_key,
                "status": status,
                "status_reason": reason or "",
                "status_updated_at": now_iso,
                "last_event_at": now_iso,
            }
            if connected_at:
                entity["connected_at"] = connected_at
            if closed_at:
                entity["closed_at"] = closed_at

            if UpdateMode:
                self.table_client.upsert_entity(entity, mode=UpdateMode.MERGE)
            else:
                self.table_client.upsert_entity(entity)
            logger.info(f"✅ Updated handoff {conversation_id} status -> {status}")
            return True
        except Exception as e:
            logger.warning(f"⚠️ Failed to update status for {conversation_id}: {e}")
            return False

    def mark_connected(self, conversation_id: str, reason: str = "agent_joined") -> None:
        self.update_handoff_status(
            conversation_id,
            status="connected",
            reason=reason,
            connected_at=datetime.utcnow().isoformat()
        )

    def mark_closed(self, conversation_id: str, reason: str = "closed") -> None:
        self.update_handoff_status(
            conversation_id,
            status="closed",
            reason=reason,
            closed_at=datetime.utcnow().isoformat()
        )
    
    def get_handoff_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a conversation by ID from Azure Tables (required for cross-container access).
        
        Args:
            conversation_id: The conversation ID
            
        Returns:
            Conversation data with messages, or None if not found
        """
        normalized_id = self._normalize_conversation_id(conversation_id)
        lookup_keys = []
        if conversation_id:
            lookup_keys.append(conversation_id)
        if normalized_id and normalized_id != conversation_id:
            lookup_keys.append(normalized_id)

        # Check cache first (fastest, but only works within same container)
        for key in lookup_keys:
            if key in self.cache:
                cached = self.cache[key]
                logger.info(f"✅ Found conversation {conversation_id} in local cache (stored as {key})")
                return cached
        
        # Must use Azure Tables for cross-container access
        if not self.azure_available:
            logger.error("❌ Azure Tables not available - cannot retrieve conversation from other container")
            return None
            
        try:
            storage_id = normalized_id or conversation_id
            # Use same key structure as callback_system.py
            row_key = f"{storage_id}_pre_handoff"
            entity = self.table_client.get_entity(
                partition_key="conversations",
                row_key=row_key
            )
            
            messages = json.loads(entity.get("messages", "[]"))
            metadata_raw = entity.get("metadata", "{}")
            try:
                metadata = json.loads(metadata_raw) if isinstance(metadata_raw, str) else (metadata_raw or {})
            except Exception:
                metadata = {}
            conversation = {
                "id": conversation_id,
                "normalized_id": storage_id,
                "messages": messages,
                "stored_at": entity.get("created_at"),
                "message_count": entity.get("message_count", len(messages)),
                "metadata": metadata,
            }
            
            # Cache for next time (within same container)
            self.cache[storage_id] = conversation
            if storage_id != conversation_id:
                self.cache[conversation_id] = conversation
            logger.info(f"✅ Found conversation {conversation_id} in Azure Tables (stored as {storage_id})")
            
            return conversation
            
        except Exception as e:
            logger.warning(f"Conversation {conversation_id} not found in Azure Tables: {e}")
            return None

    def get_recent_handoff_for_apex(self, apex_id: str, max_age_minutes: int = 10) -> Optional[Dict[str, Any]]:
        """Return most recent non-closed handoff for an apex_id within the window."""
        if not (self.azure_available and apex_id):
            return None
        try:
            query = f"PartitionKey eq 'conversations' and apex_id eq '{apex_id}'"
            entities = list(self.table_client.query_entities(query))
            if not entities:
                return None

            def _parse_dt(val: str) -> datetime:
                try:
                    return datetime.fromisoformat(val)
                except Exception:
                    return datetime.utcnow()

            newest = None
            for ent in entities:
                created_at = _parse_dt(ent.get("created_at", datetime.utcnow().isoformat()))
                if newest is None or created_at > newest[0]:
                    newest = (created_at, ent)

            if not newest:
                return None

            created_at, ent = newest
            age_seconds = (datetime.utcnow() - created_at).total_seconds()
            if age_seconds > max_age_minutes * 60:
                return None

            if ent.get("status", "pending") == "closed":
                return None

            return ent
        except Exception as e:
            logger.warning(f"⚠️ Failed to query recent handoff for apex {apex_id}: {e}")
            return None
    
    def clear_old_conversations(self, hours: int = 24):
        """Clean up old conversations from cache to prevent unbounded growth"""
        try:
            cutoff = datetime.utcnow().timestamp() - (hours * 3600)
            to_remove = []
            
            for conv_id, conv_data in self.cache.items():
                stored_at = datetime.fromisoformat(conv_data.get("stored_at", ""))
                if stored_at.timestamp() < cutoff:
                    to_remove.append(conv_id)
            
            for conv_id in to_remove:
                del self.cache[conv_id]
                
            if to_remove:
                logger.info(f"Cleaned up {len(to_remove)} old conversations from cache")
                
        except Exception as e:
            logger.error(f"Cleanup error: {e}")

# Global singleton instance
conversation_store = ConversationStore()
