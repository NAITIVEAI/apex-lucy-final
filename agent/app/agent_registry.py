import logging
import os
from typing import Any, Dict, Optional

try:
    from azure.data.tables import TableServiceClient
    from azure.core.exceptions import ResourceExistsError
    AZURE_TABLES_AVAILABLE = True
except Exception as exc:
    logging.warning("Azure Tables SDK not available: %s", exc)
    TableServiceClient = None
    ResourceExistsError = Exception
    AZURE_TABLES_AVAILABLE = False

logger = logging.getLogger("AgentRegistry")

DEFAULT_TABLE = "agentregistry"


def normalize_table_name(name: Optional[str]) -> str:
    if not name:
        return DEFAULT_TABLE
    cleaned = "".join(ch for ch in name if ch.isalnum())
    if not cleaned:
        return DEFAULT_TABLE
    if not cleaned[0].isalpha():
        cleaned = f"t{cleaned}"
    if len(cleaned) < 3:
        return DEFAULT_TABLE
    if len(cleaned) > 63:
        cleaned = cleaned[:63]
    return cleaned.lower()


class AgentRegistry:
    def __init__(self, table_name: Optional[str] = None) -> None:
        raw_name = table_name or os.getenv("AGENT_REGISTRY_TABLE_NAME", DEFAULT_TABLE)
        self.table_name = normalize_table_name(raw_name)
        if raw_name != self.table_name:
            logger.warning(
                "AgentRegistry table name normalized from '%s' to '%s'",
                raw_name,
                self.table_name,
            )
        self._memory_store: Dict[str, Dict[str, Any]] = {}
        self.using_memory_fallback = False

        conn = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
        if not AZURE_TABLES_AVAILABLE or not conn:
            self.using_memory_fallback = True
            self.table_service = None
            self.table_client = None
            return

        self.table_service = TableServiceClient.from_connection_string(conn)
        self.table_client = self.table_service.get_table_client(self.table_name)
        try:
            self.table_client.create_table()
        except ResourceExistsError:
            pass

    def _key(self, partition: str, row: str) -> str:
        return f"{partition}|{row}"

    def get_agent_record(self, partition: str, row: str) -> Optional[Dict[str, Any]]:
        if self.using_memory_fallback:
            return self._memory_store.get(self._key(partition, row))
        try:
            entity = self.table_client.get_entity(partition_key=partition, row_key=row)
            return dict(entity)
        except Exception:
            return None

    def upsert_agent_record(self, partition: str, row: str, data: Dict[str, Any]) -> None:
        entity = {"PartitionKey": partition, "RowKey": row, **data}
        if self.using_memory_fallback:
            self._memory_store[self._key(partition, row)] = entity
            return
        self.table_client.upsert_entity(entity)
