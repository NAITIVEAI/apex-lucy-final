import os
import sys
import logging
import requests
import json
from typing import Dict, List, Optional, Any
from threading import Lock
from dotenv import load_dotenv

# Ensure teams_integration module can be imported by adding current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

# Also add /app to path for container environments
if '/app' not in sys.path and os.path.exists('/app'):
    sys.path.insert(0, '/app')

# Try to import teams_integration module at module level to catch errors early
try:
    import teams_integration
    TEAMS_INTEGRATION_AVAILABLE = True
    # Note: logger will be defined later, use logging for module-level imports
    logging.info("✅ Full Teams integration module loaded")
except ImportError as e:
    logging.warning(f"Full Teams integration module not available: {e}")
    # Try fallback Teams integration
    try:
        import teams_integration_fallback as teams_integration
        TEAMS_INTEGRATION_AVAILABLE = True
        logging.info("✅ Fallback Teams integration module loaded")
    except ImportError as fallback_error:
        logging.warning(f"Fallback Teams integration also not available: {fallback_error}")
        TEAMS_INTEGRATION_AVAILABLE = False

# Also try to import callback_system early to catch import issues
try:
    import callback_system
    CALLBACK_SYSTEM_AVAILABLE = True
    logging.info("✅ Callback system module loaded at startup")
except ImportError as e:
    CALLBACK_SYSTEM_AVAILABLE = False
    logging.error(f"❌ CRITICAL: callback_system module not available at startup: {e}")
    # Debug: List files in current directory
    try:
        logging.error(f"Files in {current_dir}:")
        for f in os.listdir(current_dir):
            if f.endswith('.py'):
                logging.error(f"  - {f}")
    except Exception:
        pass

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
import asyncio
import aiohttp
import functools
import urllib.parse
import time
import uuid  # Used by analyze_pdf_content_tool and search_notices
import random
from datetime import datetime, timedelta, timezone
from azure.storage.blob import BlobServiceClient, BlobSasPermissions, generate_blob_sas, BlobClient
import chainlit as cl

# Recent handoff registry for bridging between tool execution and Chainlit session
_recent_handoff_cache: List[Dict[str, Any]] = []
_recent_handoff_lock = Lock()
_MAX_HANDOFF_CACHE = 50
_HANDOFF_MAX_AGE_SECONDS = 300

_HANDOFF_MESSAGE_VARIANTS = [
    "An APEX representative will join this chat within 5 minutes. If a representative is not able to join, please just reply back and I will set up a callback.",
    "An APEX representative is on the way and should join within the next five minutes. If no one is able to join, reply here and I'll set up a callback.",
    "An APEX team member will be here within 5 minutes. If a representative can't join, please reply and I'll arrange a callback right away."
]


def _select_handoff_message() -> str:
    try:
        return random.choice(_HANDOFF_MESSAGE_VARIANTS)
    except Exception:
        return _HANDOFF_MESSAGE_VARIANTS[0]

# Import enhanced authentication modules
try:
    from agentic_authentication_enhanced_v2 import authenticate_member_enhanced_v2_sync
    ENHANCED_V2_AUTH_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import enhanced v2 authentication: {e}")
    ENHANCED_V2_AUTH_AVAILABLE = False

try:
    from agentic_authentication import authenticate_member_agentic_sync
    AGENTIC_AUTH_AVAILABLE = True
except ImportError as e:
    print(f"Warning: Could not import agentic_authentication: {e}")
    AGENTIC_AUTH_AVAILABLE = False

# Handoff functions will be implemented in this file

# Load environment variables
load_dotenv()

# Logging setup - moved early to avoid NameError in logger usage throughout file
logger = logging.getLogger("UserFunctions")
logger.setLevel(logging.INFO)
if not any(isinstance(h, logging.FileHandler) and getattr(h, 'baseFilename', '').endswith("app.log") for h in logger.handlers):
    file_handler = logging.FileHandler("app.log")
    file_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(file_handler)
if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(stream_handler)


def record_recent_handoff(apex_id: Optional[str], handoff_id: str, portal_url: str, reason: Optional[str] = None) -> None:
    """Record the most recent handoff so the Chainlit session can reuse the real ID."""
    entry = {
        "apex_id": (apex_id or "").strip(),
        "handoff_id": handoff_id,
        "portal_url": portal_url,
        "reason": reason or "",
        "timestamp": datetime.now(timezone.utc)
    }

    with _recent_handoff_lock:
        _recent_handoff_cache.append(entry)
        # Keep cache bounded
        if len(_recent_handoff_cache) > _MAX_HANDOFF_CACHE:
            del _recent_handoff_cache[0:len(_recent_handoff_cache) - _MAX_HANDOFF_CACHE]


def consume_recent_handoff(apex_id: Optional[str] = None, max_age_seconds: int = _HANDOFF_MAX_AGE_SECONDS) -> Optional[Dict[str, Any]]:
    """Return the most recent handoff entry matching the apex_id (if provided)."""
    now = datetime.now(timezone.utc)

    with _recent_handoff_lock:
        # Drop stale entries first
        fresh_entries: List[Dict[str, Any]] = []
        for entry in _recent_handoff_cache:
            age = (now - entry["timestamp"]).total_seconds()
            if age <= max_age_seconds:
                fresh_entries.append(entry)
        _recent_handoff_cache.clear()
        _recent_handoff_cache.extend(fresh_entries)

        preferred_idx: Optional[int] = None
        fallback_idx: Optional[int] = None

        for idx in range(len(_recent_handoff_cache) - 1, -1, -1):
            entry = _recent_handoff_cache[idx]
            if apex_id and entry.get("apex_id") and entry["apex_id"] == apex_id:
                preferred_idx = idx
                break
            if fallback_idx is None:
                fallback_idx = idx

        target_idx = preferred_idx if preferred_idx is not None else fallback_idx
        if target_idx is not None:
            return _recent_handoff_cache.pop(target_idx)

    return None

# Azure Storage Helper Functions
def generate_sas_url(blob_url: str) -> Optional[str]:
    """Generate a read‑only SAS URL for the given blob using BlobClient."""
    logger = logging.getLogger("UserFunctions")
    logger.info(f"Generating SAS URL for: {blob_url}")

    try:
        connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")

        if connection_string:
            # Connection string approach
            blob_service_client = BlobServiceClient.from_connection_string(
                connection_string
            )

            # Extract account key from connection string or env var
            account_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
            if not account_key:
                try:
                    import re as _re

                    match = _re.search(r"AccountKey=([^;]+)", connection_string, _re.I)
                    if match:
                        account_key = match.group(1)
                except Exception as parse_err:
                    logger.debug(
                        f"Could not parse AccountKey from connection string: "
                        f"{parse_err}"
                    )

            if not account_key and hasattr(blob_service_client, "credential"):
                account_key = getattr(blob_service_client.credential, "key", None)

            if not account_key:
                msg = (
                    "ERROR: storage account key missing - provide via "
                    "AZURE_STORAGE_ACCOUNT_KEY or in connection string"
                )
                logger.error(msg)
                return msg

            # Create a blob client from the URL
            blob_client = BlobClient.from_blob_url(blob_url, credential=None)
            logger.info(
                f"Created blob client for: account={blob_client.account_name}, "
                f"container={blob_client.container_name}, "
                f"blob={blob_client.blob_name}"
            )

            # Generate SAS token using the blob client properties
            start_time = datetime.now(timezone.utc)
            expiry_time = start_time + timedelta(hours=2)

            # Create permission with read access
            permission = BlobSasPermissions(read=True)

            account_name = blob_client.account_name
            if not account_name:
                msg = "ERROR: Could not retrieve storage account name"
                logger.error(msg)
                return msg

            sas_token = generate_blob_sas(
                account_name=account_name,
                container_name=blob_client.container_name,
                blob_name=blob_client.blob_name,
                account_key=account_key,
                permission=permission,
                expiry=expiry_time,
                start=start_time,
                content_disposition=(
                    f'inline; filename="{os.path.basename(blob_client.blob_name)}"'
                ),
                content_type="application/pdf",
            )

            # Construct the SAS URL correctly
            sas_url = f"{blob_client.url}?{sas_token}"
            logger.info(f"Generated SAS URL (first 100 chars): {sas_url[:100]}...")

            # Per SDK update, ensure we return a string
            if not isinstance(sas_url, str):
                sas_url = str(sas_url)

            return sas_url

        else:
            # Managed Identity approach
            try:
                from azure.identity import DefaultAzureCredential
            except ImportError as ie:
                msg = (
                    f"ERROR: azure-identity is required for managed identity "
                    f"SAS generation ({ie})"
                )
                logger.error(msg)
                return msg

            # Create a blob client from the URL
            blob_client = BlobClient.from_blob_url(blob_url, credential=None)
            logger.info(
                f"Created blob client for: account={blob_client.account_name}, "
                f"container={blob_client.container_name}, "
                f"blob={blob_client.blob_name}"
            )

            # Create BlobServiceClient with DefaultAzureCredential
            credential = DefaultAzureCredential(
                exclude_shared_token_cache_credential=False
            )
            blob_service_client = BlobServiceClient(
                f"https://{blob_client.account_name}.blob.core.windows.net",
                credential=credential,
            )

            # Get user delegation key
            user_delegation_key = blob_service_client.get_user_delegation_key(
                key_start_time=datetime.now(timezone.utc) - timedelta(minutes=5),
                key_expiry_time=datetime.now(timezone.utc) + timedelta(hours=2),
            )

            account_name = blob_client.account_name
            if not account_name:
                msg = "ERROR: Could not retrieve storage account name for managed identity"
                logger.error(msg)
                return msg

            sas_token = generate_blob_sas(
                account_name=account_name,
                container_name=blob_client.container_name,
                blob_name=blob_client.blob_name,
                user_delegation_key=user_delegation_key,
                permission=BlobSasPermissions(read=True),
                expiry=datetime.now(timezone.utc) + timedelta(hours=2),
                content_disposition=(
                    f'inline; filename="{os.path.basename(blob_client.blob_name)}"'
                ),
                content_type="application/pdf",
            )

            # Construct the SAS URL correctly
            sas_url = f"{blob_client.url}?{sas_token}"
            logger.info(
                f"Generated SAS URL with managed identity "
                f"(first 100 chars): {sas_url[:100]}..."
            )
            return sas_url

    except Exception as e:
        error_msg = f"SAS generation failed: {str(e)}"
        logger.error(f"❌ {error_msg}", exc_info=True)
        return f"ERROR: {error_msg}"

# PII Protection Functions
def mask_name(name: str) -> str:
    """Mask a name to protect PII. Shows only first character."""
    if not name or len(name) < 2:
        return "***"
    return f"{name[0]}{'*' * (len(name) - 1)}"

def mask_ssn(ssn: str) -> str:
    """Mask SSN to show only last 2 digits."""
    if not ssn or len(ssn) < 2:
        return "****"
    return f"**{ssn[-2:]}"

def sanitize_member_data(member_data: Dict[str, Any]) -> Dict[str, Any]:
    """Remove or mask all PII from member data."""
    if not member_data:
        return {}

    sanitized = {}
    pii_fields = [
        'new_firstname', 'new_lastname', 'new_fullname', 'new_middlename',
        'new_shortsocial', 'new_email', 'new_phone', 'new_address1',
        'new_address2', 'new_city', 'new_state', 'new_zip'
    ]

    for key, value in member_data.items():
        if key in pii_fields:
            # Don't include PII fields in sanitized response
            continue
        else:
            sanitized[key] = value

    # Always include ApexID as it's the safe identifier
    if 'new_apexid' in member_data:
        sanitized['new_apexid'] = member_data['new_apexid']

    return sanitized

# Import monitoring
try:
    from agentic_monitoring import monitoring_report_sync
except ImportError:
    def monitoring_report_sync():
        return json.dumps({"error": "Monitoring not available"})

# Import tracing configuration
try:
    from tracing_config import (
        tracing_config,
        LucyAttributes as TracingLucyAttributes,
        trace_function,
        trace_span as tracing_trace_span,
        trace_dynamics_query as tracing_trace_dynamics_query,
        trace_tool_execution as tracing_trace_tool_execution,
        trace_authentication as tracing_trace_authentication,
        record_metric,
        TRACING_ENABLED
    )
    # Import Status and StatusCode if tracing is available
    from opentelemetry.trace import Status as TracingStatus, StatusCode as TracingStatusCode

    # Assign to local variables to avoid type conflicts
    LucyAttributes = TracingLucyAttributes
    trace_span = tracing_trace_span
    trace_dynamics_query = tracing_trace_dynamics_query
    trace_tool_execution = tracing_trace_tool_execution
    trace_authentication = tracing_trace_authentication
    Status = TracingStatus
    StatusCode = TracingStatusCode

    tracing_logger = logging.getLogger("UserFunctions.Tracing")
    tracing_logger.info(f"✅ Tracing configuration loaded. Tracing enabled: {TRACING_ENABLED}")
except ImportError as e:
    tracing_logger = logging.getLogger("UserFunctions.Tracing")
    tracing_logger.warning(f"⚠️ Tracing configuration not available: {e}")
    # Create dummy implementations
    TRACING_ENABLED = False

    # Dummy Status and StatusCode
    class Status:
        def __init__(self, code, description=None):
            pass

    class StatusCode:
        OK = 0
        ERROR = 1

    # Dummy LucyAttributes
    class LucyAttributes:
        DYNAMICS_ENTITY = "dynamics.entity"
        DYNAMICS_OPERATION = "dynamics.operation"
        DYNAMICS_QUERY = "dynamics.query"
        DYNAMICS_RETRY_COUNT = "dynamics.retry_count"
        DYNAMICS_RECORDS_FOUND = "dynamics.records_found"
        DYNAMICS_AUTO_DISCOVERED = "dynamics.auto_discovered"
        TOOL_NAME = "tool.name"
        TOOL_SUCCESS = "tool.success"
        ERROR_TYPE = "error.type"
        ERROR_MESSAGE = "error.message"
        USER_APEX_ID = "user.apex_id"
        AUTH_STATUS = "auth.status"
        DISBURSEMENT_COUNT = "disbursement.count"
        DISBURSEMENT_TOTAL_AMOUNT = "disbursement.total_amount"

    def trace_function(*args, **kwargs):
        def decorator(func):
            return func
        if len(args) == 1 and callable(args[0]):
            return args[0]
        return decorator

    # Dummy trace_span context manager
    from contextlib import contextmanager
    @contextmanager
    def trace_span(name, **kwargs):
        yield None

    def trace_dynamics_query(*args, **kwargs):
        return trace_span("dynamics", **kwargs)

    def trace_tool_execution(*args, **kwargs):
        return trace_span("tool", **kwargs)

    def trace_authentication(*args, **kwargs):
        return trace_span("auth", **kwargs)

    def record_metric(*args, **kwargs):
        pass

# Define debug logging decorator - moved early for use throughout the file
def debug_log_function(func):
    """Decorator to add detailed logging to Dynamics 365 functions"""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        args_repr = [repr(a) for a in args]
        kwargs_repr = [f"{k}={v!r}" for k, v in kwargs.items()]
        signature = ", ".join(args_repr + kwargs_repr)

        logger.debug(f"Calling {func.__name__}({signature})")

        try:
            result = await func(*args, **kwargs)

            # Log result summary without overwhelming logs
            if isinstance(result, list):
                result_summary = f"{len(result)} items"
                if result and len(result) > 0:
                    sample = result[0]
                    if isinstance(sample, dict):
                        keys = list(sample.keys())
                        result_summary += f", keys: {keys}"
            elif isinstance(result, dict):
                keys = list(result.keys())
                result_summary = f"dict with keys: {keys}"
            else:
                result_summary = str(result)[:100] + "..." if len(str(result)) > 100 else str(result)

            logger.debug(f"{func.__name__} returned: {result_summary}")
            return result

        except Exception as e:
            logger.error(f"Error in {func.__name__}: {str(e)}", exc_info=True)
            raise

    return wrapper

# Logging setup already done earlier in the file

# Dynamics configuration
DYNAMICS_CONFIG = {
    "tenant_id": os.getenv("D365_TENANT_ID"),
    "client_id": os.getenv("D365_CLIENT_ID"),
    "client_secret": os.getenv("D365_CLIENT_SECRET"),
    "resource_url": os.getenv("D365_RESOURCE_URL")
}
DYNAMICS_ENABLED = all(DYNAMICS_CONFIG.values())
if not DYNAMICS_ENABLED:
    logger.warning("⚠️ Dynamics 365 credentials incomplete or missing")

_ENTITY_FIELDS_CACHE: Dict[str, Dict[str, Any]] = {}
_ENTITY_FIELDS_CACHE_TTL = 60 * 30  # 30 minutes
_ADDRESS_UPDATE_FIELDS = {
    "new_address",
    "new_address1",
    "address1_line1",
    "address1_line2",
    "new_city",
    "address1_city",
    "new_state",
    "new_stateorprovince",
    "address1_stateorprovince",
    "new_zip",
    "new_postalcode",
    "address1_postalcode",
}
_COA_REASON_FIELD_CANDIDATES = (
    "new_coareason",
    "new_coa_reason",
    "new_changeofaddressreason",
    "new_changeofaddress_reason",
    "new_addresschangereason",
    "new_address_change_reason",
)
_TEXT_ATTRIBUTE_TYPES = {"string", "memo"}
_CHOICE_ATTRIBUTE_TYPES = {"picklist", "state", "status"}
_COA_REASON_LABEL = "COA via Lucy"
_METADATA_LOGICAL_NAME = {
    "new_classmembers": "new_classmember",
}


def _metadata_logical_name(entity: str) -> str:
    return _METADATA_LOGICAL_NAME.get(entity, entity)


def _get_entity_attributes_cached(entity: str) -> List[Dict[str, Any]]:
    import time
    cache = _ENTITY_FIELDS_CACHE.get(entity)
    now = time.time()
    if cache and (now - cache.get("ts", 0) < _ENTITY_FIELDS_CACHE_TTL) and "attributes" in cache:
        return cache.get("attributes", [])
    try:
        metadata = _safe_async_run(get_entity_metadata(_metadata_logical_name(entity)))
        attributes = metadata.get("value", []) if isinstance(metadata, dict) else []
        fields = {
            attr.get("LogicalName")
            for attr in attributes
            if isinstance(attr, dict) and attr.get("LogicalName")
        }
        _ENTITY_FIELDS_CACHE[entity] = {"ts": now, "fields": fields, "attributes": attributes}
        logger.info(f"✅ Cached {len(fields)} fields for entity {entity}")
        return attributes
    except Exception as exc:
        logger.warning(f"⚠️ Failed to fetch metadata for {entity}: {exc}")
        return []


def _has_address_update(updates: Dict[str, Any]) -> bool:
    return any(field in _ADDRESS_UPDATE_FIELDS for field in updates)


def _normalized_choice_label(label: Any) -> str:
    return " ".join(str(label or "").strip().lower().split())


def _option_label(option: Dict[str, Any]) -> str:
    label = option.get("Label") or {}
    if isinstance(label, dict):
        localized = label.get("UserLocalizedLabel") or {}
        if isinstance(localized, dict) and localized.get("Label"):
            return str(localized["Label"])
        labels = label.get("LocalizedLabels") or []
        for localized_label in labels:
            if isinstance(localized_label, dict) and localized_label.get("Label"):
                return str(localized_label["Label"])
    return ""


def _find_choice_option_value(attribute: Dict[str, Any], label: str) -> Optional[int]:
    expected_label = _normalized_choice_label(label)
    for option_set_key in ("OptionSet", "GlobalOptionSet"):
        option_set = attribute.get(option_set_key) or {}
        if not isinstance(option_set, dict):
            continue
        for option in option_set.get("Options") or []:
            if not isinstance(option, dict):
                continue
            if _normalized_choice_label(_option_label(option)) == expected_label:
                return option.get("Value")
    return None


def _get_choice_attribute_metadata(entity: str, logical_name: str) -> Dict[str, Any]:
    access_token = _safe_async_run(get_access_token())
    entity_logical_name = _metadata_logical_name(entity)
    url = (
        f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/"
        f"EntityDefinitions(LogicalName='{entity_logical_name}')/"
        f"Attributes(LogicalName='{logical_name}')/"
        "Microsoft.Dynamics.CRM.PicklistAttributeMetadata"
        "?$select=LogicalName,AttributeType"
        "&$expand=OptionSet($select=Options),GlobalOptionSet($select=Options)"
    )
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json",
        "OData-MaxVersion": "4.0",
        "OData-Version": "4.0",
    }
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    return response.json()


def _build_coa_reason_update(entity: str) -> tuple[Dict[str, Any], Optional[str]]:
    attributes = _get_entity_attributes_cached(entity)
    if not attributes:
        return {}, "Unable to confirm COA reason schema from Dynamics metadata; address update was not submitted."

    by_logical_name = {
        str(attr.get("LogicalName", "")).lower(): attr
        for attr in attributes
        if isinstance(attr, dict) and attr.get("LogicalName")
    }
    for candidate in _COA_REASON_FIELD_CANDIDATES:
        attribute = by_logical_name.get(candidate)
        if not attribute:
            continue
        logical_name = attribute.get("LogicalName")
        attribute_type = str(attribute.get("AttributeType") or "").lower()
        if attribute_type in _TEXT_ATTRIBUTE_TYPES:
            return {logical_name: _COA_REASON_LABEL}, None
        if attribute_type in _CHOICE_ATTRIBUTE_TYPES or attribute.get("OptionSet") or attribute.get("GlobalOptionSet"):
            option_value = _find_choice_option_value(attribute, _COA_REASON_LABEL)
            if option_value is None:
                try:
                    attribute = _get_choice_attribute_metadata(entity, logical_name)
                    option_value = _find_choice_option_value(attribute, _COA_REASON_LABEL)
                except Exception as exc:
                    return {}, (
                        f"COA reason field {logical_name} is a choice, but option metadata could not be read: {exc}"
                    )
            if option_value is not None:
                return {logical_name: option_value}, None
            return {}, (
                f"COA reason field {logical_name} is a choice, but option "
                f"{_COA_REASON_LABEL!r} was not found; address update was not submitted."
            )
        return {}, f"COA reason field {logical_name} has unsupported type {attribute_type or 'unknown'}."

    return {}, (
        "No confirmed COA reason field found on new_classmembers; "
        "address update was not submitted."
    )

# Entity name and field mapping to handle specific naming conventions
ENTITY_NAME_MAP = {
    "new_classactioncases": "incidents",  # Map to actual entity name
    "new_classactioncase": "incidents",   # Map to actual entity name
    # Add other mapped entities as needed
}

# Field name mapping based on entity
FIELD_NAME_MAP = {
    "incidents": {
        "new_classactioncaseid": "incidentid"  # Map field names for incidents entity
    }
    # Add mappings for other entities as needed
}

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(requests.exceptions.RequestException)
)
async def get_access_token() -> str:
    if not DYNAMICS_ENABLED:
        raise Exception("Dynamics 365 credentials not configured.")
    try:
        token_endpoint = f"https://login.microsoftonline.com/{DYNAMICS_CONFIG['tenant_id']}/oauth2/v2.0/token"
        payload = {
            "grant_type": "client_credentials",
            "client_id": DYNAMICS_CONFIG["client_id"],
            "client_secret": DYNAMICS_CONFIG["client_secret"],
            "scope": f"{DYNAMICS_CONFIG['resource_url']}/.default"
        }
        logger.debug(f"Getting access token from: {token_endpoint}")
        response = requests.post(token_endpoint, data=payload, headers={"Content-Type": "application/x-www-form-urlencoded"})
        response.raise_for_status()
        token = response.json()["access_token"]
        logger.debug("✅ Access token fetched successfully")
        return token
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Failed to get Dynamics 365 access token: {str(e)}", exc_info=True)
        raise Exception(f"Unable to authenticate with Dynamics 365: {str(e)}")
    except Exception as e:
        logger.error(f"❌ Unexpected error getting access token: {str(e)}", exc_info=True)
        raise Exception(f"Unexpected error during authentication: {str(e)}")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(requests.exceptions.RequestException)
)
@debug_log_function
async def query_entity(entity: str, filter_str: Optional[str] = None, select: Optional[str] = None) -> List[Dict[str, Any]]:
    access_token = await get_access_token()
    try:
        # Known entity mappings for fallback scenarios
        entity_mappings = {
            "new_cases": "new_classmembers",
            "new_case": "new_classmember",
            "cases": "new_classmembers",
            "case": "new_classmember",
            "classmember": "new_classmember",
            "classmembers": "new_classmembers",
            "memberdisbursement": "new_memberdisbursements", # Corrected
            "memberdisbursements": "new_memberdisbursements",
            "new_disbursement": "new_casedisbursement",
            "new_disbursements": "new_casedisbursements",
            "incidents": "incidents",  # Dynamics 365 case entity
            "incident": "incident",   # Singular form
            "case_records": "incidents",
            "case_record": "incident",
            "casedisbursement": "new_casedisbursement",
            "casedisbursements": "new_casedisbursements",
            "disbursement": "new_casedisbursement",
            "disbursements": "new_casedisbursements",
            "payment": "new_payments",
            "payments": "new_payments",
            "new_payment": "new_payments",
            "settlement": "new_settlements",
            "settlements": "new_settlements",
            "new_settlement": "new_settlements"
        }

        # Build URL
        url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/{entity}"
        params = []
        if filter_str:
            logger.debug(f"Query filter: {filter_str}")
            filter_str = filter_str.strip()
            # URL encode the filter parameter
            encoded_filter = urllib.parse.quote(filter_str, safe='')
            params.append(f"$filter={encoded_filter}")
        if select:
            logger.debug(f"Selecting fields: {select}")
            valid_fields = [f.strip() for f in select.split(",") if f.strip() and not f.strip().startswith("$")]
            if valid_fields:
                clean_select = ",".join(valid_fields)
                # URL encode the select parameter
                encoded_select = urllib.parse.quote(clean_select, safe='')
                params.append(f"$select={encoded_select}")

        # CRITICAL: Always add $top parameter to prevent massive result sets
        # Default to 50 for discovery, 1 for specific lookups
        if filter_str and ("eq" in filter_str or "=" in filter_str):
            # Specific lookup - limit to 1-5 results
            params.append("$top=5")
        else:
            # Discovery query - limit to reasonable number
            params.append("$top=50")

        if params:
            url += "?" + "&".join(params)
        logger.info(f"Executing Dynamics 365 query: {url}")

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0"
        }

        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()
        result = response.json().get("value", [])
        logger.info(f"✅ Query for {entity} returned {len(result)} results")
        return result
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            if entity in entity_mappings:
                mapped_entity = entity_mappings[entity]
                logger.info(f"Entity '{entity}' not found. Trying mapped entity: '{mapped_entity}'")
                return await query_entity(mapped_entity, filter_str, select)
            if not entity.endswith("s"):
                plural_entity = f"{entity}s"
                logger.info(f"Entity not found. Retrying with plural: {plural_entity}")
                return await query_entity(plural_entity, filter_str, select)
            if not entity.startswith("new_"):
                prefixed_entity = f"new_{entity}"
                logger.info(f"Entity not found. Retrying with 'new_' prefix: {prefixed_entity}")
                return await query_entity(prefixed_entity, filter_str, select)
            logger.error(f"❌ Entity '{entity}' not found after trying all fallbacks")
            logger.info(f"🔄 Returning empty result to prevent agent from getting stuck")
            return []
        logger.error(f"❌ Network error querying Dynamics 365: {str(e)}")
        logger.info(f"🔄 Returning empty result to prevent agent from getting stuck")
        return []
    except Exception as e:
        logger.error(f"❌ Unexpected error querying Dynamics 365: {str(e)}")
        logger.info(f"🔄 Returning empty result to prevent agent from getting stuck")
        return []

@debug_log_function
async def update_entity(entity: str, entity_id: str, data: Dict[str, Any]) -> bool:
    access_token = await get_access_token()
    entity_mappings = {
        "new_cases": "new_classmembers",
        "new_case": "new_classmember",
        "cases": "new_classmembers",
        "case": "new_classmember",
        "classmember": "new_classmember",
        "classmembers": "new_classmembers",
        "memberdisbursement": "new_memberdisbursements", # Corrected
        "memberdisbursements": "new_memberdisbursements"
    }
    is_guid = False
    if entity_id and len(entity_id) > 30 and '-' in entity_id:
        is_guid = True
    try:
        if is_guid:
            formatted_id = entity_id
        else:
            logger.info(f"Entity ID '{entity_id}' doesn't appear to be a GUID. Attempting to find record...")
            filter_str = f"new_apexid eq '{entity_id}'"
            results = await query_entity(entity, filter_str=filter_str)
            if not results or len(results) == 0:
                if entity in entity_mappings:
                    mapped_entity = entity_mappings[entity]
                    logger.info(f"Trying to find record with mapped entity: {mapped_entity}")
                    results = await query_entity(mapped_entity, filter_str=filter_str)
            if not results or len(results) == 0:
                raise Exception(f"No record found with Apex ID: {entity_id}")
            if "new_classmemberid" in results[0]:
                formatted_id = results[0]["new_classmemberid"]
            elif entity.endswith("s") and entity[:-1] + "id" in results[0]:
                id_field = entity[:-1] + "id"
                formatted_id = results[0][id_field]
            else:
                id_fields = [k for k in results[0].keys() if k.endswith("id")]
                if id_fields:
                    formatted_id = results[0][id_fields[0]]
                else:
                    raise Exception(f"Could not determine ID field for entity {entity}")
        current_entity = entity
        url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/{current_entity}({formatted_id})"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
            "If-Match": "*"
        }
        logger.info(f"Updating entity at URL: {url} with data: {data}")
        response = requests.patch(url, json=data, headers=headers, timeout=15)
        try:
            response.raise_for_status()
            logger.info(f"✅ Updated entity {current_entity} with ID {formatted_id}")
            return True
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                if current_entity in entity_mappings:
                    mapped_entity = entity_mappings[current_entity]
                    logger.info(f"Entity '{current_entity}' not found. Trying mapped entity: '{mapped_entity}'")
                    url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/{mapped_entity}({formatted_id})"
                    response = requests.patch(url, json=data, headers=headers, timeout=15)
                    response.raise_for_status()
                    logger.info(f"✅ Updated entity {mapped_entity} with ID {formatted_id}")
                    return True
                elif not current_entity.startswith("new_"):
                    prefixed_entity = f"new_{current_entity}"
                    logger.info(f"Entity not found. Retrying with 'new_' prefix: {prefixed_entity}")
                    url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/{prefixed_entity}({formatted_id})"
                    response = requests.patch(url, json=data, headers=headers, timeout=15)
                    response.raise_for_status()
                    logger.info(f"✅ Updated entity {prefixed_entity} with ID {formatted_id}")
                    return True
                else:
                    raise
            else:
                raise
    except Exception as e:
        logger.error(f"❌ Error updating entity {entity}: {str(e)}", exc_info=True)
        raise Exception(f"Failed to update entity: {str(e)}")

@debug_log_function
async def create_entity(entity: str, data: Dict[str, Any]) -> str:
    access_token = await get_access_token()
    entity_mappings = {
        "new_cases": "new_classmembers",
        "new_case": "new_classmember",
        "cases": "new_classmembers",
        "case": "new_classmember",
        "classmember": "new_classmember",
        "classmembers": "new_classmembers",
        "memberdisbursement": "new_memberdisbursements", # Corrected
        "memberdisbursements": "new_memberdisbursements"
    }
    try:
        current_entity = entity
        url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/{current_entity}"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0"
        }
        logger.info(f"Creating entity: {current_entity} with data: {data}")
        response = requests.post(url, json=data, headers=headers, timeout=15)
        try:
            response.raise_for_status()
            entity_id = response.headers.get("OData-EntityId", "").split("(")[-1].rstrip(")")
            logger.info(f"✅ Created entity {current_entity} with ID {entity_id}")
            return entity_id
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                if current_entity in entity_mappings:
                    mapped_entity = entity_mappings[current_entity]
                    logger.info(f"Entity '{current_entity}' not found. Trying mapped entity: '{mapped_entity}'")
                    url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/{mapped_entity}"
                    response = requests.post(url, json=data, headers=headers, timeout=15)
                    response.raise_for_status()
                    entity_id = response.headers.get("OData-EntityId", "").split("(")[-1].rstrip(")")
                    logger.info(f"✅ Created entity {mapped_entity} with ID {entity_id}")
                    return entity_id
                elif not current_entity.startswith("new_"):
                    prefixed_entity = f"new_{current_entity}"
                    logger.info(f"Entity not found. Retrying with 'new_' prefix: {prefixed_entity}")
                    url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/{prefixed_entity}"
                    response = requests.post(url, json=data, headers=headers, timeout=15)
                    response.raise_for_status()
                    entity_id = response.headers.get("OData-EntityId", "").split("(")[-1].rstrip(")")
                    logger.info(f"✅ Created entity {prefixed_entity} with ID {entity_id}")
                    return entity_id
                else:
                    raise
            else:
                raise
    except Exception as e:
        logger.error(f"❌ Error creating entity {entity}: {str(e)}", exc_info=True)
        raise Exception(f"Failed to create entity: {str(e)}")

@debug_log_function
async def delete_entity(entity: str, entity_id: str) -> bool:
    access_token = await get_access_token()
    entity_mappings = {
        "new_cases": "new_classmembers",
        "new_case": "new_classmember",
        "cases": "new_classmembers",
        "case": "new_classmember",
        "classmember": "new_classmember",
        "classmembers": "new_classmembers",
        "memberdisbursement": "new_memberdisbursements", # Corrected
        "memberdisbursements": "new_memberdisbursements"
    }
    is_guid = False
    if entity_id and len(entity_id) > 30 and '-' in entity_id:
        is_guid = True
    try:
        if is_guid:
            formatted_id = entity_id
        else:
            logger.info(f"Entity ID '{entity_id}' doesn't appear to be a GUID. Attempting to find record...")
            filter_str = f"new_apexid eq '{entity_id}'"
            results = await query_entity(entity, filter_str=filter_str)
            if not results or len(results) == 0:
                if entity in entity_mappings:
                    mapped_entity = entity_mappings[entity]
                    logger.info(f"Trying to find record with mapped entity: {mapped_entity}")
                    results = await query_entity(mapped_entity, filter_str=filter_str)
            if not results or len(results) == 0:
                raise Exception(f"No record found with Apex ID: {entity_id}")
            if "new_classmemberid" in results[0]:
                formatted_id = results[0]["new_classmemberid"]
            elif entity.endswith("s") and entity[:-1] + "id" in results[0]:
                id_field = entity[:-1] + "id"
                formatted_id = results[0][id_field]
            else:
                id_fields = [k for k in results[0].keys() if k.endswith("id")]
                if id_fields:
                    formatted_id = results[0][id_fields[0]]
                else:
                    raise Exception(f"Could not determine ID field for entity {entity}")
        current_entity = entity
        url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/{current_entity}({formatted_id})"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0"
        }
        logger.info(f"Deleting entity at URL: {url}")
        response = requests.delete(url, headers=headers, timeout=15)
        try:
            response.raise_for_status()
            logger.info(f"✅ Deleted entity {current_entity} with ID {formatted_id}")
            return True
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                if current_entity in entity_mappings:
                    mapped_entity = entity_mappings[current_entity]
                    logger.info(f"Entity '{current_entity}' not found. Trying mapped entity: '{mapped_entity}'")
                    url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/{mapped_entity}({formatted_id})"
                    response = requests.delete(url, headers=headers, timeout=15)
                    response.raise_for_status()
                    logger.info(f"✅ Deleted entity {mapped_entity} with ID {formatted_id}")
                    return True
                elif not current_entity.startswith("new_"):
                    prefixed_entity = f"new_{current_entity}"
                    logger.info(f"Entity not found. Retrying with 'new_' prefix: {prefixed_entity}")
                    url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/{prefixed_entity}({formatted_id})"
                    response = requests.delete(url, headers=headers, timeout=15)
                    response.raise_for_status()
                    logger.info(f"✅ Deleted entity {prefixed_entity} with ID {formatted_id}")
                    return True
                else:
                    raise
            else:
                raise
    except Exception as e:
        logger.error(f"❌ Error deleting entity {entity}: {str(e)}", exc_info=True)
        raise Exception(f"Failed to delete entity: {str(e)}")

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(requests.exceptions.RequestException)
)
@debug_log_function
async def discover_entities(prefix: str = "") -> List[str]:
    access_token = await get_access_token()
    try:
        url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/EntityDefinitions?$select=LogicalName,DisplayName"
        logger.info(f"Querying entity definitions from: {url}")
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0"
        }
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        entities_data = response.json().get("value", [])
        logger.info(f"Retrieved {len(entities_data)} entity definitions")
        entity_names = []
        for entity in entities_data:
            logical_name = entity.get("LogicalName", "")
            if not prefix or logical_name.startswith(prefix):
                entity_names.append(logical_name)
        logger.info(f"Found {len(entity_names)} entities" +
                   (f" with prefix '{prefix}'" if prefix else ""))
        return entity_names
    except Exception as e:
        logger.error(f"❌ Error discovering entities: {str(e)}", exc_info=True)
        raise Exception(f"Failed to discover entities: {str(e)}")

def get_access_token_sync():
    result = _safe_async_run(get_access_token())
    return str(result)

@trace_function(name="dynamics.query_entity")
def query_entity_sync(entity, filter_str=None, select=None):
    # Determine if new_classmemberid should be stripped based on the 'select' parameter
    strip_new_classmemberid_flag = True
    selected_fields_set_for_stripping = set()
    if select:
        selected_fields_lower = [s.strip().lower() for s in select.split(',')]
        if "new_classmemberid" in selected_fields_lower:
            strip_new_classmemberid_flag = False
        # Also populate the set for the stripping function, using original case from select
        selected_fields_set_for_stripping = set(s.strip() for s in select.split(','))


    # Sanitize the `$select` list for the OData query:
    # never include the GUID field if it wasn't explicitly asked for,
    # as it bloats the response and is rarely useful for the agent.
    # However, if it IS in select, we must keep it for the query.
    # The stripping logic below will handle what the LLM sees.
    effective_select = select
    if select:
        fields = [
            f.strip()
            for f in select.split(',')
            if f.strip() # Keep new_classmemberid if it was in select for the actual query
        ]
        effective_select = ','.join(fields) if fields else None

    try:
        result = _safe_async_run(query_entity(entity, filter_str=filter_str, select=effective_select))
    except RuntimeError as e:
        if "asyncio.run() cannot be called from a running event loop" not in str(e):
            raise
        # Fallback with safe async run
        result = _safe_async_run(query_entity(entity, filter_str=filter_str, select=effective_select))

    def _strip_guid_fields(item):
        if isinstance(item, dict):
            # Only pop new_classmemberid if strip_new_classmemberid_flag is True
            # (i.e., it was NOT explicitly in the original select string)
            if strip_new_classmemberid_flag:
                 item.pop("new_classmemberid", None)
            # Always strip other typical GUIDs not usually needed by LLM unless selected
            # This part can be expanded if other GUIDs are problematic
            # For now, only new_classmemberid is handled based on select
        return item

    if isinstance(result, list):
        result = [_strip_guid_fields(r) for r in result]
        if len(result) > 5: # Limit to 5 records for LLM context
            logger.info(f"Query result for {entity} truncated to 5 records for LLM context.")
            result = result[:5]
    elif isinstance(result, dict):
        result = _strip_guid_fields(result)

    import json as _json
    try:
        return _json.dumps(result)
    except Exception:
        return str(result)

@trace_function(name="dynamics.update_entity")
def update_entity_sync(entity, entity_id, data):
    result = _safe_async_run(update_entity(entity, entity_id, data))
    return str(result)

@trace_function(name="dynamics.update_member_profile")
def update_member_profile_sync(apex_id: str, field_updates: Dict[str, Any]) -> str:
    """
    Safe function to update member profile fields after authentication.

    Args:
        apex_id: The member's APEX ID
        field_updates: Dictionary of fields to update (e.g., {"new_email": "new@email.com", "new_phonenumber": "555-1234"})

    Allowed fields for update:
        - new_email: Email address
        - new_phonenumber: Phone number
        - new_address1: Street address (primary field)
        - new_city: City
        - new_stateorprovince: State/Province
        - new_postalcode: ZIP/Postal code

    Legacy fields (for backward compatibility):
        - new_address: Street address (legacy)
        - new_state: State (legacy)
        - new_zip: ZIP code (legacy)

    Returns:
        JSON string with update results
    """
    try:
        # Whitelist of fields members can update
        allowed_fields = [
            'new_email', 'new_phonenumber', 'new_address1',  # Fixed: Use new_address1
            'new_city', 'new_stateorprovince', 'new_postalcode',  # Fixed: Use correct field names
            # Legacy field names for backward compatibility
            'new_address', 'new_state', 'new_zip'
        ]

        # Filter to only allowed fields
        safe_updates = {k: v for k, v in field_updates.items() if k in allowed_fields}
        if _has_address_update(safe_updates):
            coa_update, coa_error = _build_coa_reason_update("new_classmembers")
            if coa_error:
                logger.error("COA reason writeback blocked address update for %s: %s", apex_id, coa_error)
                return json.dumps({
                    "success": False,
                    "error": coa_error,
                    "attempted_updates": safe_updates
                })
            safe_updates.update(coa_update)

        if not safe_updates:
            return json.dumps({
                "success": False,
                "error": "No valid fields to update. Allowed fields: email, phone, address.",
                "allowed_fields": allowed_fields
            })

        # First, find the member by apex_id
        member_filter = f"new_apexid eq '{apex_id}'"
        member_result_str = query_entity_sync('new_classmembers',
                                            filter_str=member_filter,
                                            select="new_classmemberid,new_apexid")
        member_results = json.loads(member_result_str)

        if not member_results or len(member_results) == 0:
            return json.dumps({
                "success": False,
                "error": f"No member found with ApexID: {apex_id}"
            })

        member_guid = member_results[0].get('new_classmemberid')
        if not member_guid:
            return json.dumps({
                "success": False,
                "error": "Could not retrieve member ID for update"
            })

        # Perform the update
        logger.info(f"Updating member {apex_id} with fields: {list(safe_updates.keys())}")
        update_result = update_entity_sync('new_classmembers', member_guid, safe_updates)

        # Verify the update by reading back
        verify_select = ",".join(safe_updates.keys())
        verify_result_str = query_entity_sync('new_classmembers',
                                            filter_str=member_filter,
                                            select=verify_select)
        verify_results = json.loads(verify_result_str)

        if verify_results and len(verify_results) > 0:
            return json.dumps({
                "success": True,
                "message": "Profile updated successfully",
                "apex_id": apex_id,
                "updated_fields": safe_updates,
                "current_values": verify_results[0]
            })
        else:
            return json.dumps({
                "success": True,
                "message": "Profile update submitted",
                "apex_id": apex_id,
                "updated_fields": safe_updates,
                "note": "Update successful but could not verify new values"
            })

    except Exception as e:
        logger.error(f"Error updating member profile for {apex_id}: {str(e)}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": str(e),
            "message": "Failed to update profile"
        })

def create_entity_sync(entity, data):
    result = _safe_async_run(create_entity(entity, data))
    return str(result)

def delete_entity_sync(entity, entity_id):
    result = _safe_async_run(delete_entity(entity, entity_id))
    return str(result)

def test_azure_search_query():
    import os, requests
    endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
    api_key = os.getenv("AZURE_SEARCH_API_KEY")
    index_name = os.getenv("AZURE_SEARCH_INDEX_NAME")
    headers = {"api-key": api_key}
    r = requests.get(f"{endpoint}/indexes?api-version=2021-04-30-Preview", headers=headers)
    print("Indexes:", r.json())
    r = requests.get(f"{endpoint}/indexes/{index_name}/docs?api-version=2021-04-30-Preview&search=*", headers=headers)
    print("Sample docs:", r.json())

def test_sas_url():
    from azure.storage.blob import BlobServiceClient, BlobSasPermissions, generate_blob_sas
    from datetime import datetime, timedelta
    import os, requests
    connection_string = os.getenv("AZURE_STORAGE_CONNECTION_STRING")
    if not connection_string:
        print("ERROR: AZURE_STORAGE_CONNECTION_STRING not configured")
        return

    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    container_name = (
        os.getenv("AZURE_STORAGE_CONTAINER_NAME")
        or os.getenv("AZURE_STORAGE_CONTAINER")
        or "lucyrag"
    )
    blob_name = "Alight Solutions/Data Files/Alight Solutions Class List.xlsx"
    account_name = blob_service_client.account_name
    if not account_name:
        print("ERROR: Could not get account name")
        return

    account_key = blob_service_client.credential.account_key
    if not account_key:
        print("ERROR: Could not get account key")
        return

    sas_token = generate_blob_sas(
        account_name=account_name,
        container_name=container_name,
        blob_name=blob_name,
        account_key=account_key,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.utcnow() + timedelta(hours=1),
    )
    url = f"https://{account_name}.blob.core.windows.net/{container_name}/{blob_name}?{sas_token}"
    print("SAS URL:", url)
    r = requests.get(url)
    print("Status:", r.status_code)
    print("Content (first 200 bytes):", r.content[:200])

async def get_entity_metadata(entity: str) -> dict:
    access_token = await get_access_token()
    url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/EntityDefinitions(LogicalName='{entity}')/Attributes"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/json"
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as response:
            response.raise_for_status()
            return await response.json()

def get_entity_metadata_sync(entity):
    return json.dumps(_safe_async_run(get_entity_metadata(entity)))

@trace_function(name="case.get_details")
async def get_case_details(case_id: str) -> Dict[str, Any]:
    """
    Get case (incident) details from Dynamics 365

    Args:
        case_id: Case GUID or case number

    Returns:
        Case information
    """
    try:
        access_token = await get_access_token()

        # Determine if case_id is a GUID or case number
        if len(case_id) > 30 and '-' in case_id:
            # It's a GUID, query by incidentid
            filter_str = f"incidentid eq '{case_id}'"
        else:
            # It's a case number, query by ticketnumber
            filter_str = f"ticketnumber eq '{case_id}'"

        # Define fields to retrieve for case
        select_fields = [
            "incidentid", "ticketnumber", "title", "description",
            "statuscode", "statecode", "prioritycode", "severitycode",
            "createdon", "modifiedon", "caseorigincode",
            "customerid_contact", "customerid_account",
            "ownerid", "casetypecode"
        ]
        select = ",".join(select_fields)

        # Query the incidents entity
        url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/incidents"
        if filter_str:
            url += f"?$filter={filter_str}"
        if select:
            url += f"&$select={select}" if "?" in url else f"?$select={select}"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0"
        }

        logger.info(f"Querying case: {url}")
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        result = response.json().get("value", [])

        if result:
            case = result[0]
            logger.info(f"✅ Found case: {case.get('ticketnumber', case_id)}")
            return case
        else:
            logger.warning(f"❌ Case not found: {case_id}")
            return {}

    except Exception as e:
        logger.error(f"❌ Error retrieving case {case_id}: {e}")
        return {}

def get_case_details_sync(case_id: str) -> str:
    """
    Sync wrapper for getting case details

    Args:
        case_id: Case GUID or case number

    Returns:
        JSON string with case information
    """
    try:
        case_data = _safe_async_run(get_case_details(case_id))

        if case_data:
            return json.dumps({
                "success": True,
                "case": case_data,
                "case_id": case_id
            })
        else:
            return json.dumps({
                "success": False,
                "error": "Case not found",
                "case_id": case_id
            })

    except Exception as e:
        logger.error(f"Error in get_case_details_sync: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "case_id": case_id
        })

@trace_function(name="case.get_notes")
async def get_case_notes(case_id: str) -> List[Dict[str, Any]]:
    """
    Get notes (annotations) for a case from Dynamics 365

    Args:
        case_id: Case GUID

    Returns:
        List of case notes
    """
    try:
        access_token = await get_access_token()

        # Query annotations related to this case
        filter_str = f"objectid eq '{case_id}' and objecttypecode eq 112"  # 112 is incident entity type

        select_fields = [
            "annotationid", "subject", "notetext", "filename",
            "filesize", "isdocument", "createdon", "modifiedon",
            "mimetype", "_createdby_value", "_modifiedby_value"
        ]
        select = ",".join(select_fields)

        url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/annotations"
        url += f"?$filter={filter_str}&$select={select}&$orderby=modifiedon desc"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0"
        }

        logger.info(f"Querying case notes: {url}")
        response = requests.get(url, headers=headers, timeout=15)
        response.raise_for_status()

        result = response.json().get("value", [])
        logger.info(f"✅ Found {len(result)} notes for case {case_id}")

        return result

    except Exception as e:
        logger.error(f"❌ Error retrieving case notes for {case_id}: {e}")
        return []

def get_case_notes_sync(case_id: str) -> str:
    """
    Sync wrapper for getting case notes

    Args:
        case_id: Case GUID

    Returns:
        JSON string with case notes
    """
    try:
        notes_data = _safe_async_run(get_case_notes(case_id))

        return json.dumps({
            "success": True,
            "notes": notes_data,
            "count": len(notes_data),
            "case_id": case_id
        })

    except Exception as e:
        logger.error(f"Error in get_case_notes_sync: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "case_id": case_id,
            "notes": []
        })

@trace_function(name="case.get_member_cases")
async def get_member_cases(apex_id: str) -> List[Dict[str, Any]]:
    """
    Get cases associated with a member

    Args:
        apex_id: Member's APEX ID

    Returns:
        List of cases for the member
    """
    try:
        # First, get the member's contact ID
        member_filter = f"new_apexid eq '{apex_id}'"
        member_result = await query_entity("new_classmembers", filter_str=member_filter, select="new_contactid,new_classmemberid,new_apexid")

        if not member_result:
            logger.warning(f"Member {apex_id} not found")
            return []

        member = member_result[0]
        contact_id = member.get("new_contactid")

        if not contact_id:
            logger.warning(f"No contact ID found for member {apex_id}")
            return []

        # Query cases where this contact is the customer
        case_filter = f"_customerid_contact_value eq {contact_id}"
        cases = await query_entity("incidents", filter_str=case_filter)

        logger.info(f"✅ Found {len(cases)} cases for member {apex_id}")
        return cases

    except Exception as e:
        logger.error(f"❌ Error getting cases for member {apex_id}: {e}")
        return []

def get_member_cases_sync(apex_id: str) -> str:
    """
    Sync wrapper for getting member cases

    Args:
        apex_id: Member's APEX ID

    Returns:
        JSON string with member's cases
    """
    try:
        cases_data = _safe_async_run(get_member_cases(apex_id))

        return json.dumps({
            "success": True,
            "cases": cases_data,
            "count": len(cases_data),
            "apex_id": apex_id
        })

    except Exception as e:
        logger.error(f"Error in get_member_cases_sync: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "apex_id": apex_id,
            "cases": []
        })

@debug_log_function
async def query_related_entity(primary_entity: str, primary_filter: str, related_entity: str,
                              relationship_attr: str, select: Optional[str] = None) -> List[Dict[str, Any]]:
    try:
        logger.info(f"Step 1: Querying primary entity '{primary_entity}' with filter: {primary_filter}")
        primary_results = await query_entity(primary_entity, filter_str=primary_filter)
        if not primary_results:
            logger.warning(f"No primary records found for filter: {primary_filter}")
            return []
        logger.info(f"Found {len(primary_results)} primary records")
        relationship_guids = []
        for record in primary_results:
            logger.debug(f"Primary record fields: {list(record.keys())}")
            if "_new_case_value" in relationship_attr.lower():
                target_field = "_new_case_value"
                if target_field in record and record[target_field]:
                    guid_value = record[target_field]
                    relationship_guids.append(guid_value)
                    logger.info(f"Found case GUID: {guid_value}")
                else:
                    logger.warning(f"No case GUID found in record for relationship {relationship_attr}")
            elif "_new_classmember_value" in relationship_attr.lower():
                possible_fields = ["new_classmemberid", "_new_classmember_value"]
                found_guid = False
                for field in possible_fields:
                    if field in record and record[field]:
                        guid_value = record[field]
                        relationship_guids.append(guid_value)
                        logger.info(f"Found classmember GUID from field '{field}': {guid_value}")
                        found_guid = True
                        break
                if not found_guid:
                    logger.warning(f"No classmember GUID found in record for relationship {relationship_attr}")
            else:
                for key, value in record.items():
                    if (key.endswith('id') and value and
                        isinstance(value, str) and
                        len(value) > 30 and '-' in value):
                        relationship_guids.append(value)
                        logger.info(f"Found generic GUID from field '{key}': {value}")
                        break
        if not relationship_guids:
            logger.error("No valid GUIDs found for relationship query")
            return []
        if len(relationship_guids) == 1:
            guid = relationship_guids[0]
            related_filter = f"{relationship_attr} eq '{guid}'" # GUIDs are typically NOT quoted in $filter if they are actual GUID types
            if not (len(guid) > 30 and '-' in guid): # Heuristic: if not looking like a GUID, quote it
                 related_filter = f"{relationship_attr} eq '{guid}'"
            else: # It looks like a GUID, don't quote
                 related_filter = f"{relationship_attr} eq {guid}"

            logger.info(f"Querying related entity '{related_entity}' with filter: {related_filter}")
        else:
            logger.info(f"Multiple GUIDs found, will query each individually")
            all_related_results = []
            for guid in relationship_guids:
                single_filter = f"{relationship_attr} eq '{guid}'" # Same GUID quoting logic
                if not (len(guid) > 30 and '-' in guid):
                     single_filter = f"{relationship_attr} eq '{guid}'"
                else:
                     single_filter = f"{relationship_attr} eq {guid}"

                logger.info(f"Querying related entity with filter: {single_filter}")
                try:
                    context = f"related to {primary_entity} via {relationship_attr}"
                    single_results = await smart_query_entity(
                        entity_hint=related_entity,
                        filter_str=single_filter,
                        select=select,
                        context=context
                    )
                    all_related_results.extend(single_results)
                except Exception as e:
                    logger.warning(f"Failed to query related entity for GUID {guid}: {e}")
                    continue
            logger.info(f"✅ Found {len(all_related_results)} total related records")
            return all_related_results
        context = f"related to {primary_entity} via {relationship_attr}"
        related_results = await smart_query_entity(
            entity_hint=related_entity,
            filter_str=related_filter,
            select=select,
            context=context
        )
        logger.info(f"✅ Found {len(related_results)} related records in {related_entity}")
        return related_results
    except Exception as e:
        logger.error(f"Error in query_related_entity: {str(e)}", exc_info=True)
        raise Exception(f"Failed to query related entity: {str(e)}")

def query_related_entity_sync(primary_entity, primary_filter, related_entity,
                            relationship_attr, select=None):
    try:
        result = asyncio.run(query_related_entity(
            primary_entity, primary_filter, related_entity, relationship_attr, select
        ))
    except RuntimeError as e:
        if "asyncio.run() cannot be called from a running event loop" not in str(e):
            raise
        import nest_asyncio
        nest_asyncio.apply()
        result = asyncio.run(query_related_entity(
            primary_entity, primary_filter, related_entity, relationship_attr, select
        ))
    import json as _json
    try:
        return _json.dumps(result)
    except Exception:
        return str(result)

async def discover_entity_relationships(entity: str) -> Dict[str, List[str]]:
    try:
        access_token = await get_access_token()
        entity_singular = entity.rstrip('s') if entity.endswith('s') else entity
        url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/EntityDefinitions(LogicalName='{entity_singular}')?$expand=OneToManyRelationships($select=ReferencedEntity,ReferencingEntity,ReferencingAttribute),ManyToOneRelationships($select=ReferencedEntity,ReferencingEntity,ReferencingAttribute),Attributes($select=LogicalName,AttributeType,Targets)"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0"
        }
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        entity_data = response.json()
        relationships = {}
        for rel in entity_data.get("OneToManyRelationships", []):
            referencing_attr = rel.get("ReferencingAttribute")
            referenced_entity = rel.get("ReferencedEntity")
            if referencing_attr and referenced_entity:
                relationships[referencing_attr] = [referenced_entity]
        for rel in entity_data.get("ManyToOneRelationships", []):
            referencing_attr = rel.get("ReferencingAttribute")
            referenced_entity = rel.get("ReferencedEntity")
            if referencing_attr and referenced_entity:
                if referencing_attr not in relationships:
                    relationships[referencing_attr] = []
                if referenced_entity not in relationships[referencing_attr]:
                    relationships[referencing_attr].append(referenced_entity)
        for attr in entity_data.get("Attributes", []):
            if attr.get("AttributeType") == "Lookup":
                attr_name = attr.get("LogicalName")
                targets = attr.get("Targets", [])
                if attr_name and targets:
                    if attr_name not in relationships:
                        relationships[attr_name] = []
                    for target in targets:
                        if target not in relationships[attr_name]:
                            relationships[attr_name].append(target)
        logger.info(f"Discovered {len(relationships)} relationships for entity {entity}")
        return relationships
    except Exception as e:
        logger.error(f"❌ Error discovering relationships for {entity}: {str(e)}", exc_info=True)
        return {}

def discover_entity_relationships_sync(entity):
    try:
        result = asyncio.run(discover_entity_relationships(entity))
    except RuntimeError as e:
        if "asyncio.run() cannot be called from a running event loop" not in str(e):
            raise
        import nest_asyncio
        nest_asyncio.apply()
        result = asyncio.run(discover_entity_relationships(entity))
    import json as _json
    try:
        return _json.dumps(result)
    except Exception:
        return f"Error converting relationships to JSON: {str(result)}"

def setup_dynamics_functions():
    if not DYNAMICS_ENABLED:
        logger.warning("⚠️ Dynamics 365 not enabled. Returning empty function list.")
        return []
    return [
        # Core authentication function (HIGHEST PRIORITY)
        authenticate_member_sync,

        # Primary member information function (SECOND HIGHEST PRIORITY)
        get_class_member_details_sync,

        # Document retrieval (CRITICAL FOR NOTICE REQUESTS)
        find_notice_for_user_sync,

        # Essential disbursement functions
        get_member_disbursements_sync,
        reissue_check_sync,
        get_reissue_status_sync,

        # Profile management
        update_member_profile_sync,  # Safe profile updates for authenticated members
        smart_update_member_sync,  # Agentic updates that can handle any field

        # Field discovery
        discover_entity_fields_sync,  # Discover available fields dynamically

        # Human handoff
        send_handoff_notification_email_sync,  # Initiate human handoff

        # Email failback
        send_lucy_email_sync,  # Lucy's email failback for communication
        send_notification_email_sync,  # General notification email sending

        # Callback system
        collect_callback_information_sync,  # Collect callback info after timeout
        submit_callback_request_sync,  # Submit callback request
        get_pending_callbacks_sync,  # Get pending callbacks for portal
        mark_callback_completed_sync,  # Mark callback as completed

        # Conversation history
        store_conversation_history_sync,  # Store conversation history
        get_conversation_history_sync,  # Get conversation history

        # Agent notes
        add_agent_note_to_member_sync,  # Add agent notes to member profiles

        # Monitoring and analytics
        monitoring_report_sync,  # Get authentication performance metrics

        # Supporting functions (used by above functions)
        query_entity_sync,
        update_entity_sync,  # Only for reissue flag updates
        get_entity_metadata_sync,
        smart_query_entity_sync,  # For entity discovery fallback
        auto_discover_entity_sync,  # For field discovery
        discover_entities_sync,  # For entity listing
    ]

def construct_incident_filter(incident_id: str, case_name: str) -> str:
    filter_str = (
        f"incidentid eq {incident_id} and new_fullname eq '{case_name}'"
    )
    logger.info(f"[OData] Constructed incident filter: {filter_str}")
    return filter_str

def build_odata_query(
    primary_entity: str,
    primary_filter: Optional[str] = None,
    expand_relations: Optional[List[Dict[str, str]]] = None,
    select: Optional[str] = None,
    top: Optional[int] = None
) -> str:
    url = f"/api/data/v9.2/{primary_entity}"
    params = []
    if primary_filter:
        params.append(f"$filter={primary_filter}")
    if select:
        params.append(f"$select={select}")
    if expand_relations:
        expand_parts = []
        for rel in expand_relations:
            relation = rel.get("relation")
            rel_select = rel.get("select")
            if relation:
                if rel_select:
                    expand_parts.append(f"{relation}($select={rel_select})")
                else:
                    expand_parts.append(relation)
        if expand_parts:
            params.append(f"$expand={','.join(expand_parts)}")
    if top is not None and top > 0:
        params.append(f"$top={top}")
    if params:
        url += "?" + "&".join(params)
    return url

@debug_log_function
async def execute_complex_query(odata_query: str) -> List[Dict[str, Any]]:
    access_token = await get_access_token()
    try:
        resource_url = DYNAMICS_CONFIG.get("resource_url")
        if not resource_url:
            raise Exception("Dynamics 365 resource URL not configured")
        base_url = resource_url.rstrip("/")
        odata_path = odata_query.lstrip("/")
        url = f"{base_url}/{odata_path}"
        logger.info(f"Executing complex OData query: {url}")
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0"
        }
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        result = response.json().get("value", [])
        logger.info(f"Complex query returned {len(result)} results")
        return result
    except Exception as e:
        logger.error(f"Error executing complex OData query: {str(e)}", exc_info=True)
        raise

def execute_complex_query_sync(odata_query: str) -> str:
    try:
        result = asyncio.run(execute_complex_query(odata_query))
    except RuntimeError as e:
        if "asyncio.run() cannot be called from a running event loop" not in str(e):
            raise
        import nest_asyncio
        nest_asyncio.apply()
        result = asyncio.run(execute_complex_query(odata_query))
    if isinstance(result, list) and len(result) > 5:
        result = result[:5]
    import json as _json
    try:
        return _json.dumps(result)
    except Exception as e:
        logger.error(f"Error converting complex query results to JSON: {str(e)}")
        return f"Error converting results to JSON: {str(e)}"

async def check_human_availability(timeout=60):
    logger.info("Checking for available human agents")
    try:
        teams_webhook_url = os.getenv("TEAMS_WEBHOOK_URL")
        if teams_webhook_url:
            return await check_teams_availability(teams_webhook_url, timeout)
        else:
            logger.info("Teams webhook URL not configured, skipping Teams notification")
            return False, None
    except Exception as e:
        logger.error(f"Error checking human availability: {str(e)}", exc_info=True)
        return False, None

@debug_log_function
async def check_teams_availability(webhook_url, timeout=60):
    try:
        import aiohttp
        request_id = str(uuid.uuid4())
        message = {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "type": "AdaptiveCard",
                        "body": [
                            {
                                "type": "TextBlock",
                                "size": "Medium",
                                "weight": "Bolder",
                                "text": "AI Agent Lucy Needs Assistance"
                            },
                            {
                                "type": "TextBlock",
                                "text": "Are you available for a live transfer? Class Member is waiting.",
                                "wrap": True
                            }
                        ],
                        "actions": [
                            {
                                "type": "Action.Submit",
                                "title": "Yes",
                                "data": {
                                    "response": "yes",
                                    "requestId": request_id
                                }
                            },
                            {
                                "type": "Action.Submit",
                                "title": "No",
                                "data": {
                                    "response": "no",
                                    "requestId": request_id
                                }
                            }
                        ],
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "version": "1.2"
                    }
                }
            ]
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=message) as response:
                if response.status != 200:
                    logger.error(f"Failed to send Teams notification: {response.status}")
                    return False, None
                response_data = await response.json()
                logger.debug(f"Teams notification sent: {response_data}")
        await asyncio.sleep(1)
        is_available = False
        agent_name = None
        if os.getenv("DEMO_MODE", "false").lower() == "true":
            import random
            is_available = random.random() > 0.5
            agent_name = "Demo Agent" if is_available else None
            if is_available:
                logger.info(f"Agent {agent_name} is available via Teams")
            else:
                logger.info("No agents available via Teams")
        return is_available, agent_name
    except Exception as e:
        logger.error(f"Error checking Teams availability: {str(e)}", exc_info=True)
        return False, None

async def send_handoff_notification_email(conversation_id, user_info, message, is_callback=False):
    try:
        smtp_server = os.getenv("SMTP_SERVER")
        smtp_port_str = os.getenv("SMTP_PORT", "587")
        smtp_port = int(smtp_port_str)
        sender_email = os.getenv("SENDER_EMAIL")
        sender_password = os.getenv("SENDER_PASSWORD")
        recipient_email = "agentsupport@apexclassaction.com"

        if not all([smtp_server, sender_email, sender_password]):
            logger.error("Email configuration incomplete. Cannot send handoff notification.")
            return False

        # Type safety: we know these are not None due to the check above
        assert smtp_server is not None
        assert sender_email is not None
        assert sender_password is not None

        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        msg = MIMEMultipart()
        msg["Subject"] = f"{'Callback' if is_callback else 'Handoff'} Request: {conversation_id}"
        msg["From"] = sender_email
        msg["To"] = recipient_email
        user_info_text = "\n".join([f"{k}: {v}" for k, v in user_info.items() if v])
        agent_portal_url = os.getenv("AGENT_PORTAL_URL", "http://localhost:8000")
        body = f"""
        A class member has requested {'a callback' if is_callback else 'human assistance'}.

        Conversation ID: {conversation_id}

        User Information:
        {user_info_text}

        Message:
        {message}

        {f'Click here to join the conversation: {agent_portal_url}/agent/conversation/{conversation_id}' if not is_callback else 'Please contact the user at your earliest convenience.'}
        """
        msg.attach(MIMEText(body, "plain"))
        import smtplib
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)
        logger.info(f"Handoff notification email sent for conversation {conversation_id}")
        return True
    except Exception as e:
        logger.error(f"Error sending handoff notification email: {str(e)}", exc_info=True)
        return False

async def send_notification_email(
    recipient_email: str,
    subject: str,
    message_content: str,
    conversation_id: Optional[str] = None
) -> bool:
    """
    Send a notification email to specified recipient
    """
    try:
        smtp_server = os.getenv("SMTP_SERVER")
        smtp_port_str = os.getenv("SMTP_PORT", "587")
        smtp_port = int(smtp_port_str)
        sender_email = os.getenv("SENDER_EMAIL")
        sender_password = os.getenv("SENDER_PASSWORD")

        if not all([smtp_server, sender_email, sender_password]):
            logger.error("Email configuration incomplete. Cannot send notification email.")
            return False

        # Type safety: we know these are not None due to the check above
        assert smtp_server is not None
        assert sender_email is not None
        assert sender_password is not None

        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"] = sender_email
        msg["To"] = recipient_email

        # Add conversation link if provided
        if conversation_id:
            agent_portal_url = os.getenv("AGENT_PORTAL_URL", "http://localhost:8001")
            message_content += f"\n\nConversation Link: {agent_portal_url}/agent/conversation/{conversation_id}"

        msg.attach(MIMEText(message_content, "plain"))

        import smtplib
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)

        logger.info(f"Notification email sent to {recipient_email}: {subject}")
        return True

    except Exception as e:
        logger.error(f"Error sending notification email: {str(e)}", exc_info=True)
        return False

def send_notification_email_sync(
    recipient_email: str,
    subject: str,
    message_content: str,
    conversation_id: Optional[str] = None
) -> str:
    """
    Send notification email synchronously
    Returns JSON with success status
    """
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(
            send_notification_email(recipient_email, subject, message_content, conversation_id)
        )
        loop.close()

        return json.dumps({
            "success": success,
            "message": "Email sent successfully" if success else "Failed to send email"
        })

    except Exception as e:
        logger.error(f"Error in send_notification_email_sync: {str(e)}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })

async def send_lucy_email(
    recipient_email: str,
    subject: str,
    message_content: str,
    conversation_id: Optional[str] = None
) -> bool:
    """
    Send email from Lucy (lucy@apexclassaction.com) as a failback communication method
    """
    try:
        smtp_server = os.getenv("SMTP_SERVER")
        smtp_port_str = os.getenv("SMTP_PORT", "587")
        smtp_port = int(smtp_port_str)
        sender_email = "lucy@apexclassaction.com"  # Lucy's dedicated email
        sender_password = os.getenv("LUCY_EMAIL_PASSWORD", os.getenv("SENDER_PASSWORD"))

        if not all([smtp_server, sender_email, sender_password]):
            logger.error("Lucy email configuration incomplete. Cannot send email.")
            return False

        # Type safety: we know these are not None due to the check above
        assert smtp_server is not None
        assert sender_email is not None
        assert sender_password is not None

        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        msg = MIMEMultipart()
        msg["Subject"] = subject
        msg["From"] = f"Lucy AI Assistant <{sender_email}>"
        msg["To"] = recipient_email

        # Add Lucy's signature to the email
        footer = "\n\n---\nBest regards,\nLucy AI Assistant\nAPEX Class Action\nlucy@apexclassaction.com\n\nThis is an automated message from Lucy, APEX Class Action's AI assistant."

        # Add conversation link if provided
        if conversation_id:
            agent_portal_url = os.getenv("AGENT_PORTAL_URL", "http://localhost:8001")
            message_content += f"\n\nConversation Link: {agent_portal_url}/agent/conversation/{conversation_id}"

        msg.attach(MIMEText(message_content + footer, "plain"))

        import smtplib
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.send_message(msg)

        logger.info(f"Lucy email sent to {recipient_email}: {subject}")
        return True

    except Exception as e:
        logger.error(f"Error sending Lucy email: {str(e)}", exc_info=True)
        return False

def send_lucy_email_sync(
    recipient_email: str,
    subject: str,
    message_content: str,
    conversation_id: Optional[str] = None,
    apex_id: Optional[str] = None
) -> str:
    """
    Send email from Lucy as a failback communication method

    Args:
        recipient_email: Email address to send to
        subject: Email subject line
        message_content: Email body content
        conversation_id: Optional conversation ID for tracking
        apex_id: Optional member APEX ID for context

    Returns:
        JSON string with success status and message
    """
    try:
        # Enhance the subject with Lucy branding
        enhanced_subject = f"[Lucy AI] {subject}"

        # Add context to message if apex_id provided
        if apex_id:
            enhanced_message = f"Regarding member: {apex_id}\n\n{message_content}"
        else:
            enhanced_message = message_content

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        success = loop.run_until_complete(
            send_lucy_email(recipient_email, enhanced_subject, enhanced_message, conversation_id)
        )
        loop.close()

        if success:
            return json.dumps({
                "success": True,
                "message": f"Email sent successfully from Lucy to {recipient_email}",
                "sender": "lucy@apexclassaction.com",
                "recipient": recipient_email,
                "subject": enhanced_subject
            })
        else:
            return json.dumps({
                "success": False,
                "message": "Failed to send email from Lucy",
                "error": "SMTP configuration or connection issue"
            })

    except Exception as e:
        logger.error(f"Error in send_lucy_email_sync: {str(e)}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "message": "Exception occurred while sending Lucy email"
        })

def check_human_availability_sync(timeout=60):
    try:
        is_available, agent_name = asyncio.run(check_human_availability(timeout))
        return json.dumps({
            "is_available": is_available,
            "agent_name": agent_name
        })
    except Exception as e:
        logger.error(f"Error in check_human_availability_sync: {str(e)}", exc_info=True)
        return json.dumps({
            "is_available": False,
            "agent_name": None,
            "error": str(e)
        })

def send_handoff_notification_email_sync(
    apex_id: str,
    conversation_id: str = "",
    phone_number: str = "",
    best_time: str = "",
    reason: Optional[str] = None
) -> str:
    """
    Initiate human handoff for authenticated member.
    First checks Teams availability, then creates handoff.

    Args:
        apex_id: Member's APEX ID
        conversation_id: Conversation ID for the handoff
        phone_number: Member's phone number for callback
        best_time: Best time to contact the member
        reason: Optional reason for handoff

    Returns:
        JSON string with handoff status
    """
    try:
        logger.info(f"🔄 Starting handoff process for member {apex_id}")

        # Import Teams integration functions safely
        teams_functions_available = False
        check_teams_availability_sync = None
        send_teams_handoff_notification_sync = None

        if TEAMS_INTEGRATION_AVAILABLE:
            try:
                from teams_integration import check_teams_availability_sync, send_teams_handoff_notification_sync
                teams_functions_available = True
                logger.info("✅ Teams integration functions imported successfully")
            except ImportError as import_error:
                logger.warning(f"⚠️ Teams integration functions not available: {import_error}")
                teams_functions_available = False
        else:
            logger.warning("⚠️ Teams integration module not available")
            teams_functions_available = False

        # Check if agent portal is enabled
        agent_portal_enabled = os.getenv("AGENT_PORTAL_ENABLED", "false").lower() == "true"
        agent_portal_url = os.getenv("AGENT_PORTAL_URL", "http://localhost:8001")
        teams_webhook_url = os.getenv("TEAMS_WEBHOOK_URL")

        # If neither agent portal nor Teams webhook is configured, and Teams functions unavailable, use email fallback
        if not agent_portal_enabled and not teams_webhook_url and not teams_functions_available:
            logger.warning("No Teams, portal, or webhook available - using email fallback")
            # Fall back to email notification
            try:
                conversation_id = str(uuid.uuid4())
                email_success = asyncio.run(send_handoff_notification_email(
                    conversation_id,
                    {"apex_id": apex_id},
                    reason or "User requested human assistance"
                ))
                if email_success:
                    return json.dumps({
                        "success": True,
                        "message": "I've notified our support team via email. Someone will contact you within 24 hours.",
                        "apex_id": apex_id
                    })
                else:
                    # Try Lucy's email as additional failback
                    logger.warning("Primary email failed, trying Lucy's email failback")
                    try:
                        lucy_email_success = asyncio.run(send_lucy_email(
                            "agentsupport@apexclassaction.com",
                            f"Early Failback Handoff Request: {conversation_id}",
                            f"A class member has requested human assistance.\n\nApex ID: {apex_id}\nReason: {reason or 'User requested human assistance'}\n\nNo Teams or portal configuration available - this is an early failback request.",
                            conversation_id
                        ))
                        if lucy_email_success:
                            return json.dumps({
                                "success": True,
                                "message": "I've notified our support team via Lucy's email. Someone will contact you within 24 hours.",
                                "apex_id": apex_id
                            })
                    except Exception as lucy_error:
                        logger.error(f"Lucy email failback failed: {lucy_error}")

                    return json.dumps({
                        "success": False,
                        "message": "Human handoff is currently unavailable. Please try again later or call our support line."
                    })
            except Exception as email_error:
                logger.error(f"Email fallback failed: {email_error}")
                return json.dumps({
                    "success": False,
                    "message": "Human handoff is currently unavailable. Please try again later or call our support line."
                })

        # Step 1: Check Teams availability with error handling (if Teams functions available)
        agent_email = None
        agent_name = None
        availability_result = {"available": False}

        if teams_functions_available and check_teams_availability_sync:
            logger.info("Checking for available agents via Teams...")
            try:
                availability_result = json.loads(check_teams_availability_sync())
                logger.info(f"Teams availability check result: {availability_result}")
            except Exception as e:
                logger.error(f"Failed to check Teams availability: {e}")
                availability_result = {"available": False, "error": str(e)}
        else:
            logger.info("Teams functions not available, using fallback agent assignment")

        if not availability_result.get("available"):
            # If no agents available or Teams presence check failed, proceed with webhook notification anyway
            if "error" in availability_result and "403" in str(availability_result.get("error", "")):
                logger.warning("Teams presence check failed due to permissions. Proceeding with webhook notification.")
                # Use first configured agent as fallback
                agent_emails = os.getenv("TEAMS_AGENT_EMAILS", "").split(",")
                agent_emails = [email.strip() for email in agent_emails if email.strip()]
                if agent_emails:
                    agent_email = agent_emails[0]
                    agent_name = agent_email.split("@")[0].replace(".", " ").title()
                    logger.info(f"Using fallback agent: {agent_name} ({agent_email})")
                else:
                    return json.dumps({
                        "success": False,
                        "message": "Human handoff is currently unavailable. Please try again later or call our support line."
                    })
            else:
                # No agents showing as available via presence, but still proceed with webhook
                logger.info("No agents showing as available via presence check. Proceeding with webhook notification to all agents.")
                # Use first configured agent as fallback for notification
                agent_emails = os.getenv("TEAMS_AGENT_EMAILS", "").split(",")
                agent_emails = [email.strip() for email in agent_emails if email.strip()]
                if agent_emails:
                    agent_email = agent_emails[0]
                    agent_name = agent_email.split("@")[0].replace(".", " ").title()
                    logger.info(f"Using {agent_name} as primary contact for webhook notification")
                else:
                    return json.dumps({
                        "success": False,
                        "message": "Human handoff is currently unavailable. Please try again later or call our support line."
                    })
        else:
            # We have an available agent from Teams presence check
            agent_email = availability_result.get("agent_email")
            agent_name = availability_result.get("agent_name")

        # Generate unique handoff ID
        handoff_id = str(uuid.uuid4())

        # Step 2: Create handoff in portal (if portal is enabled)

        if agent_portal_enabled:
            handoff_data = {
                "conversation_id": handoff_id,
                "user_info": {
                    "apex_id": apex_id,
                    "name": f"Member {apex_id}",  # Keep PII protected
                    "assigned_agent": agent_email
                },
                "history": [],  # TODO: Get conversation history from Chainlit
                "reason": reason or "User requested human assistance"
            }

            # Send to agent portal API
            try:
                response = requests.post(
                    f"{agent_portal_url}/api/handoff",
                    json=handoff_data,
                    headers={"Content-Type": "application/json"},
                    timeout=10
                )

                if response.status_code == 200:
                    # Success - set proper portal conversation URL
                    portal_url = f"{agent_portal_url}/agent/conversation/{handoff_id}"
                    logger.info(f"✅ Handoff created successfully, portal URL: {portal_url}")
                else:
                    logger.error(f"Agent portal returned {response.status_code}: {response.text}")
                    # Don't fail here - still send Teams notification
                    portal_url = f"{agent_portal_url}/agent/conversation/{handoff_id}"  # Still try the URL

            except requests.exceptions.RequestException as e:
                logger.error(f"Failed to connect to agent portal: {str(e)}")
                # Don't fail here - still send Teams notification
                portal_url = f"{agent_portal_url}/agent/conversation/{handoff_id}"  # Still try the URL
        else:
            logger.info("Agent portal disabled, using Teams-only handoff")
            portal_url = f"Teams handoff (ID: {handoff_id})"

        # Record the real handoff so the Chainlit session can reuse the ID
        try:
            record_recent_handoff(apex_id, handoff_id, portal_url, reason)
        except Exception as cache_error:
            logger.warning(f"Failed to record recent handoff: {cache_error}")

        # Step 3: Send Teams notification to the specific agent with error handling (if Teams functions available)
        notification_result = {"success": False, "message": "Teams notification not available"}

        if teams_functions_available and send_teams_handoff_notification_sync and agent_email and isinstance(agent_email, str):
            logger.info(f"Notifying agent {agent_name} via Teams...")
            try:
                notification_result = json.loads(send_teams_handoff_notification_sync(
                    agent_email=agent_email,
                    apex_id=apex_id,
                    reason=reason or "User requested human assistance",
                    portal_url=portal_url,
                    conversation_id=handoff_id
                ))
                logger.info(f"Teams notification result: {notification_result}")
            except Exception as e:
                logger.error(f"Failed to send Teams notification: {e}")
                notification_result = {"success": False, "error": str(e)}
        else:
            logger.info("Teams notification not available, using email fallback")
            # Send email notification as fallback
            try:
                email_success = asyncio.run(send_handoff_notification_email(
                    handoff_id,
                    {"apex_id": apex_id, "assigned_agent": agent_email or "Support Team"},
                    reason or "User requested human assistance"
                ))
                notification_result = {"success": email_success, "message": "Email notification sent" if email_success else "Email notification failed"}

                # If primary email fails, try Lucy's email as additional failback
                if not email_success:
                    logger.warning("Primary email notification failed, trying Lucy's email failback")
                    try:
                        lucy_email_success = asyncio.run(send_lucy_email(
                            "agentsupport@apexclassaction.com",
                            f"Handoff Request: {handoff_id}",
                            f"A class member has requested human assistance.\n\nApex ID: {apex_id}\nReason: {reason or 'User requested human assistance'}\n\nPlease check the agent portal for more details.",
                            handoff_id
                        ))
                        if lucy_email_success:
                            notification_result = {"success": True, "message": "Lucy email notification sent"}
                            logger.info("✅ Lucy email failback successful")
                        else:
                            logger.error("❌ Lucy email failback also failed")
                    except Exception as lucy_error:
                        logger.error(f"Lucy email failback failed: {lucy_error}")

            except Exception as e:
                logger.error(f"Email notification fallback failed: {e}")
                notification_result = {"success": False, "error": str(e)}

        if notification_result.get("success"):
            # Start timeout monitoring for 4-minute handoff window
            try:
                from callback_system import start_conversation_timeout_monitor
                user_info = {"apex_id": apex_id, "name": f"Member {apex_id}"}
                _safe_async_run(start_conversation_timeout_monitor(
                    handoff_id, user_info, reason or "User requested human assistance"
                ))
                logger.info(f"✅ Started 4-minute timeout monitor for conversation {handoff_id}")
            except ImportError as import_error:
                logger.warning(f"Callback system not available: {import_error}")
            except Exception as timeout_error:
                logger.warning(f"Failed to start timeout monitor: {timeout_error}")

            # Return handoff information for the main handler to store in session
            logger.info(f"✅ Handoff notification successful, returning info for bridge establishment")

            # Generate user-friendly portal URL for the class member (kept for backend WebSocket)
            user_portal_url = portal_url.replace("/agent/", "/chat/") if "/agent/" in portal_url else portal_url

            return json.dumps({
                "success": True,
                "message": _select_handoff_message(),
                "agent_name": agent_name,
                "handoff_id": handoff_id,
                "conversation_id": handoff_id,
                "portal_url": portal_url,
                "user_portal_url": user_portal_url,
                "apex_id": apex_id,
                "establish_bridge": False,  # No WebSocket bridge needed
                "wait_for_agent_join": False
            })
        else:
            # Fallback if Teams notification fails but handoff was created
            logger.info(f"✅ Using fallback handoff, returning info for bridge establishment")

            # Generate user-friendly portal URL for the class member (kept for backend WebSocket)
            user_portal_url = portal_url.replace("/agent/", "/chat/") if "/agent/" in portal_url else portal_url

            return json.dumps({
                "success": True,
                "message": _select_handoff_message(),
                "agent_name": agent_name,
                "handoff_id": handoff_id,
                "conversation_id": handoff_id,
                "portal_url": portal_url,
                "user_portal_url": user_portal_url,
                "apex_id": apex_id,
                "warning": "Teams notification may have failed",
                "establish_bridge": False,  # No WebSocket bridge needed
                "wait_for_agent_join": False
            })

    except Exception as e:
        logger.error(f"Error in handoff function: {str(e)}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "message": "An error occurred while connecting you with an agent."
        })

def request_human_assistance_sync(apex_id: str, reason: Optional[str] = None, timeout: int = 30) -> str:
    """
    Enhanced human handoff using interactive Teams availability check.
    Sends Teams message and waits for agent response.

    Args:
        apex_id: Member's APEX ID
        reason: Optional reason for assistance
        timeout: Wait time in seconds for agent response

    Returns:
        JSON string with handoff status
    """
    try:
        # Check if Teams integration is available
        if not TEAMS_INTEGRATION_AVAILABLE:
            logger.error("Teams integration module not available")
            return json.dumps({
                "success": False,
                "message": "Human handoff system is temporarily unavailable. Please try again later."
            })

        # Import Teams integration function
        from teams_integration import send_teams_availability_check_sync

        # Check if agent portal is enabled
        agent_portal_enabled = os.getenv("AGENT_PORTAL_ENABLED", "false").lower() == "true"

        if not agent_portal_enabled:
            return json.dumps({
                "success": False,
                "message": "Human handoff is currently unavailable. Please try again later or call our support line."
            })

        # Prepare user info for availability check
        user_info = {
            "apex_id": apex_id,
            "name": f"Member {apex_id}"  # Keep PII protected
        }

        # Send interactive Teams availability check
        logger.info(f"Sending interactive Teams availability check for {apex_id}...")
        result_str = send_teams_availability_check_sync(
            user_info=user_info,
            reason=reason or "General assistance",
            timeout=timeout
        )

        result = json.loads(result_str)

        if result.get("available"):
            # Agent is available and conversation is set up
            agent_name = result.get("agent_name", "Agent")
            conversation_id = result.get("conversation_id")
            portal_url = result.get("portal_url")

            return json.dumps({
                "success": True,
                "message": _select_handoff_message(),
                "agent_name": agent_name,
                "conversation_id": conversation_id,
                "portal_url": portal_url,
                "method": "interactive_teams"
            })
        else:
            # No agents responded or available
            message = result.get("message", "No agents are currently available")

            return json.dumps({
                "success": False,
                "message": f"I'm sorry, but {message.lower()}. Would you like me to arrange a callback within the next 24 hours?",
                "offer_callback": True,
                "details": result
            })

    except Exception as e:
        logger.error(f"Error in enhanced handoff function: {str(e)}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "message": "An error occurred while connecting you with an agent. Please try again."
        })

def discover_entities_sync(prefix=None):
    try:
        prefix_param = prefix if prefix is not None else ""
        result = asyncio.run(discover_entities(prefix_param))
    except RuntimeError as e:
        if "asyncio.run() cannot be called from a running event loop" not in str(e):
            raise
        import nest_asyncio
        nest_asyncio.apply()
        result = asyncio.run(discover_entities(prefix_param))
    import json as _json
    try:
        return _json.dumps(result)
    except Exception:
        return f"Error converting entity list to JSON: {str(result)}"

def setup_handoff_functions():
    return [
        check_human_availability_sync,
        send_handoff_notification_email_sync,
        request_human_assistance_sync,  # Enhanced Teams integration
    ]

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(requests.exceptions.RequestException)
)
@debug_log_function
async def auto_discover_entity_and_fields(entity_hint: str, context: str = "") -> Dict[str, Any]:
    try:
        logger.info(f"🔍 Auto-discovering entity schema for hint: '{entity_hint}' with context: '{context}'")
        potential_entities = []
        hint_clean = entity_hint.lower().replace("_", "").replace("new", "")
        try:
            all_entities = await discover_entities("new_")
            logger.info(f"Found {len(all_entities)} total entities with 'new_' prefix")
        except Exception as e:
            logger.warning(f"Failed to get entity list: {e}")
            all_entities = []
        search_variations = [
            entity_hint.lower(),
            f"new_{hint_clean}",
            f"new_{hint_clean}s",
            hint_clean,
            f"{hint_clean}s",
        ]
        if context and "disbursement" in hint_clean:
            search_variations.extend([
                "new_disbursements",
                "new_disbursement",
                "new_paymentdisbursements",
                "new_memberpayments",
                "new_classpayments",
                "new_settlements"
            ])
        for variation in search_variations:
            for entity in all_entities:
                entity_lower = entity.lower()
                if (variation == entity_lower or
                    variation in entity_lower or
                    entity_lower in variation):
                    if entity not in potential_entities:
                        potential_entities.append(entity)
                        logger.info(f"Found potential match: {entity} (via variation: {variation})")
        if not potential_entities:
            logger.info("No direct matches found, trying fuzzy matching...")
            hint_words = hint_clean.split()
            for entity in all_entities:
                entity_clean = entity.lower().replace("_", "").replace("new", "")
                entity_words = entity_clean.split()
                matches = 0
                for hint_word in hint_words:
                    if len(hint_word) > 2:
                        for entity_word in entity_words:
                            if hint_word in entity_word or entity_word in hint_word:
                                matches += 1
                                break
                if matches > 0:
                    potential_entities.append(entity)
                    logger.info(f"Fuzzy match: {entity} (score: {matches})")
        logger.info(f"Found {len(potential_entities)} potential entities: {potential_entities}")
        if not potential_entities:
            logger.warning(f"No matching entities found for hint: {entity_hint}")
            return {"entity_name": None, "fields": [], "id_field": None, "relationships": {}}
        best_match = None
        best_score = 0
        for entity_name in potential_entities:
            try:
                logger.info(f"Testing entity: {entity_name}")
                # CRITICAL FIX: Use minimal test query to check accessibility without massive results
                test_results = await query_entity(entity_name, select="createdon", filter_str=None)
                if test_results is not None:
                    logger.info(f"✅ Entity {entity_name} is accessible")
                    entity_info = await get_entity_field_metadata(entity_name)
                    if entity_info:
                        score = calculate_entity_match_score(entity_name, entity_info, entity_hint, context)
                        if test_results:
                            score += 20
                            logger.info(f"Bonus: Entity {entity_name} contains {len(test_results)} records")
                        logger.info(f"Entity '{entity_name}' scored {score}")
                        if score > best_score:
                            best_score = score
                            best_match = {
                                "entity_name": entity_name,
                                "fields": entity_info.get("fields", []),
                                "id_field": entity_info.get("id_field"),
                                "relationships": entity_info.get("relationships", {}),
                                "sample_data": test_results[:1] if test_results else []
                            }
                    else:
                        logger.warning(f"Could not get metadata for {entity_name}")
            except Exception as e:
                logger.debug(f"Entity {entity_name} failed test query: {e}")
                continue
        if best_match:
            logger.info(f"✅ Best match found: {best_match['entity_name']} with {len(best_match['fields'])} fields (score: {best_score})")
            return best_match
        else:
            logger.warning(f"No accessible entity found for hint: {entity_hint}")
            return {"entity_name": None, "fields": [], "id_field": None, "relationships": {}}
    except Exception as e:
        logger.error(f"❌ Error in auto-discovery: {str(e)}", exc_info=True)
        return {"entity_name": None, "fields": [], "id_field": None, "relationships": {}}

@debug_log_function
async def get_entity_field_metadata(entity_name: str) -> Dict[str, Any]:
    access_token = await get_access_token()
    try:
        url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/EntityDefinitions(LogicalName='{entity_name}')?$expand=Attributes($select=LogicalName,AttributeType,IsPrimaryId),OneToManyRelationships($select=ReferencedEntity,ReferencingEntity,ReferencingAttribute)"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0"
        }
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        entity_data = response.json()
        fields = []
        id_field = None
        relationships = {}
        for attr in entity_data.get("Attributes", []):
            field_name = attr.get("LogicalName")
            if field_name:
                fields.append(field_name)
                if attr.get("IsPrimaryId"):
                    id_field = field_name
        for rel in entity_data.get("OneToManyRelationships", []):
            ref_attr = rel.get("ReferencingAttribute")
            ref_entity = rel.get("ReferencedEntity")
            if ref_attr and ref_entity:
                relationships[ref_attr] = ref_entity
        logger.info(f"Retrieved metadata for {entity_name}: {len(fields)} fields, ID field: {id_field}")
        return {
            "fields": fields,
            "id_field": id_field,
            "relationships": relationships
        }
    except Exception as e:
        logger.error(f"❌ Error getting field metadata for {entity_name}: {str(e)}")
        return {}

def calculate_entity_match_score(entity_name: str, entity_info: Dict, hint: str, context: str) -> int:
    score = 0
    if hint.lower() in entity_name.lower():
        score += 50
    if "disbursement" in hint.lower() and "disbursement" in entity_name.lower():
        score += 30
    if "member" in hint.lower() and "member" in entity_name.lower():
        score += 20
    if "classmember" in context.lower():
        relationships = entity_info.get("relationships", {})
        for rel_field, target_entity in relationships.items():
            if "classmember" in target_entity.lower():
                score += 40
                break
    fields = entity_info.get("fields", [])
    disbursement_indicators = ["checkamount", "checkdate", "checknum", "disburs", "payment", "amount"]
    for indicator in disbursement_indicators:
        if any(indicator in field.lower() for field in fields):
            score += 10
    return score

@debug_log_function
async def smart_query_entity(entity_hint: str, filter_str: Optional[str] = None,
                           select: Optional[str] = None, context: str = "") -> List[Dict[str, Any]]:
    try:
        result = await query_entity(entity_hint, filter_str=filter_str, select=select)
        logger.info(f"✅ Direct query succeeded for {entity_hint}")
        return result
    except Exception as e:
        logger.info(f"Direct query failed for {entity_hint}: {e}")
        logger.info(f"🔍 Attempting auto-discovery...")
        discovery_result = await auto_discover_entity_and_fields(entity_hint, context)
        discovered_entity = discovery_result.get("entity_name")
        if not discovered_entity:
            logger.error(f"❌ Auto-discovery failed to find entity for hint: {entity_hint}")
            raise Exception(f"Could not discover entity for hint: {entity_hint}")
        corrected_select = select
        if select and discovery_result.get("fields"):
            corrected_select = correct_field_names(select, discovery_result["fields"])
            logger.info(f"Corrected select clause: {select} -> {corrected_select}")
            available_fields = discovery_result["fields"]
            final_fields = []
            for field in corrected_select.split(","):
                field = field.strip()
                if field in available_fields:
                    final_fields.append(field)
                else:
                    logger.warning(f"Removing invalid field from final select: {field}")
            if final_fields:
                corrected_select = ",".join(final_fields)
                logger.info(f"Final validated select clause: {corrected_select}")
            else:
                corrected_select = None
                logger.warning("No valid fields remain in select clause - using default fields")
        try:
            result = await query_entity(discovered_entity, filter_str=filter_str, select=corrected_select)
            logger.info(f"✅ Auto-discovery query succeeded for {discovered_entity}")
            return result
        except Exception as discovery_e:
            logger.error(f"❌ Even auto-discovery query failed: {discovery_e}")
            raise Exception(f"Query failed even after auto-discovery: {discovery_e}")

def calculate_similarity(str1: str, str2: str) -> int:
    """
    Calculate similarity percentage between two strings.
    Simple implementation based on common characters.
    """
    if not str1 or not str2:
        return 0
    str1_lower = str1.lower()
    str2_lower = str2.lower()
    if str1_lower == str2_lower:
        return 100
    # Check if one is contained in the other
    if str1_lower in str2_lower or str2_lower in str1_lower:
        return 90
    # Count common characters
    common = sum(c in str2_lower for c in str1_lower)
    max_len = max(len(str1), len(str2))
    return int((common / max_len) * 100) if max_len > 0 else 0

def correct_field_names(original_select: str, available_fields: List[str]) -> str:
    if not original_select or not available_fields:
        return original_select
    requested_fields = [f.strip() for f in original_select.split(",")]
    corrected_fields = []
    seen_fields = set()
    for requested_field in requested_fields:
        if not requested_field or requested_field in seen_fields:
            continue
        if requested_field in available_fields:
            corrected_fields.append(requested_field)
            seen_fields.add(requested_field)
            continue
        exact_match = None
        for field in available_fields:
            if field.lower() == requested_field.lower():
                exact_match = field
                break
        if exact_match and exact_match not in seen_fields:
            corrected_fields.append(exact_match)
            seen_fields.add(exact_match)
            continue
        best_match = None
        best_score = 0
        for field in available_fields:
            if field in seen_fields:
                continue
            score = calculate_similarity(requested_field, field)
            if score >= 90 and score > best_score:
                best_score = score
                best_match = field
        if best_match and best_score >= 90:
            logger.info(f"Field name correction: {requested_field} -> {best_match} (score: {best_score})")
            corrected_fields.append(best_match)
            seen_fields.add(best_match)
        else:
            logger.warning(f"No good match found for field '{requested_field}' (best score: {best_score})")
            if requested_field not in seen_fields:
                corrected_fields.append(requested_field)
                seen_fields.add(requested_field)
    result = ",".join(corrected_fields)
    if result != original_select:
        logger.info(f"Corrected select clause: {original_select} -> {result}")
    return result

def smart_query_entity_sync(entity_hint: str, filter_str: Optional[str] = None, select: Optional[str] = None, context: str = ""):
    effective_select = select
    if select:
        fields = [
            f.strip()
            for f in select.split(',')
            if f.strip() and f.strip() != 'new_classmemberid'
        ]
        effective_select = ','.join(fields) if fields else None
    try:
        result = _safe_async_run(smart_query_entity(entity_hint, filter_str=filter_str, select=effective_select, context=context))
    except RuntimeError as e:
        if "asyncio.run() cannot be called from a running event loop" not in str(e):
            raise
        # Fallback with safe async run
        result = _safe_async_run(smart_query_entity(entity_hint, filter_str=filter_str, select=effective_select, context=context))

    strip_new_classmemberid_flag = True # Default to stripping
    if select: # Check original select parameter
        selected_fields_lower = [s.strip().lower() for s in select.split(',')]
        if "new_classmemberid" in selected_fields_lower:
            strip_new_classmemberid_flag = False

    def _strip_guid_fields(item):
        if isinstance(item, dict):
            if strip_new_classmemberid_flag:
                 item.pop("new_classmemberid", None)
        return item

    if isinstance(result, list):
        result = [_strip_guid_fields(r) for r in result]
        if len(result) > 5:
            result = result[:5]
    elif isinstance(result, dict):
        result = _strip_guid_fields(result)
    import json as _json
    try:
        return _json.dumps(result)
    except Exception:
        return str(result)

def auto_discover_entity_sync(entity_hint: str, context: str = ""):
    try:
        result = asyncio.run(auto_discover_entity_and_fields(entity_hint, context=context))
    except RuntimeError as e:
        if "asyncio.run() cannot be called from a running event loop" not in str(e):
            raise
        import nest_asyncio
        nest_asyncio.apply()
        result = asyncio.run(auto_discover_entity_and_fields(entity_hint, context=context))
    import json as _json
    try:
        return _json.dumps(result)
    except Exception:
        return str(result)

@trace_function(name="dynamics.authenticate_member")
# TODO: REMOVE - Old static authentication function replaced by agentic version
# def authenticate_member_sync_static(first_name: str = None, last_name: str = None,
#                             apex_id: str = None, last_four_ssn: str = None,
#                             full_name: str = None) -> str:

def authenticate_member_sync(first_name: Optional[str] = None, last_name: Optional[str] = None,
                            apex_id: Optional[str] = None, last_four_ssn: Optional[str] = None,
                            full_name: Optional[str] = None) -> str:
    """
    Agentic authentication function that adapts to data patterns and learns from successes.

    This function uses dynamic query generation and learning cache to handle:
    - Any naming convention variations in APEX data
    - Adaptive query strategies based on discovered patterns
    - Learning from successful authentications
    - Intelligent fallback strategies

    Args:
        first_name: First name provided by user
        last_name: Last name provided by user (may include middle name)
        apex_id: APEX ID if provided
        last_four_ssn: Last 4 digits of SSN
        full_name: Full name if provided as single string

    Returns:
        JSON string with authentication results and member information
    """
    # Use enhanced v2 authentication if available, otherwise fall back to agentic
    if ENHANCED_V2_AUTH_AVAILABLE:
        return authenticate_member_enhanced_v2_sync(
            first_name or "", last_name or "", apex_id or "",
            last_four_ssn or "", full_name or ""
        )
    elif AGENTIC_AUTH_AVAILABLE:
        return authenticate_member_agentic_sync(
            first_name or "", last_name or "", apex_id or "",
            last_four_ssn or "", full_name or ""
        )
    else:
        logger.error("No authentication module available")
        return json.dumps({
            "success": False,
            "message": "Authentication system temporarily unavailable. Please try again.",
            "error": "Agentic authentication module not available"
        })
def get_class_member_details_sync(apex_id: str, info_type: str = "all") -> str:
    """
    CRITICAL: Get member PROFILE information and STATUS details from Dynamics 365.

    DO NOT USE FOR:
    - Notice documents, legal notices, settlement notices
    - PDF documents, document retrieval
    - Any kind of document or notice requests

    USE ONLY FOR:
    - Member profile details, contact information
    - Settlement amounts and calculations
    - Employment history and earnings data
    - Case status and timeline information

    For documents/notices, use find_notice_for_user_sync() instead.

    Args:
        apex_id: The member's APEX ID
        info_type: Type of information requested:
            - "all": Complete member information
            - "settlement": Settlement amounts and calculations
            - "employment": Employment dates and details
            - "earnings": Wage statements and earnings
            - "disbursements": Payment disbursements
            - "status": Overall case status
            - "timeline": Important dates and timelines

    Returns:
        JSON string with comprehensive member information
    """
    try:
        logger.info(f"🔍 Getting {info_type} information for member: {apex_id}")

        # First, discover what fields are available in the class member entity
        entity_info_str = auto_discover_entity_sync('classmember', context=f"Getting all available fields for member {apex_id}")
        entity_info = json.loads(entity_info_str)

        available_fields = []
        if entity_info.get('success') and entity_info.get('fields'):
            available_fields = entity_info['fields']
            logger.info(f"Discovered {len(available_fields)} fields in class member entity")

        # Query ALL fields or subset based on info_type
        if info_type == "all" or not available_fields:
            # Get everything
            member_result_str = query_entity_sync('new_classmembers',
                                                filter_str=f"new_apexid eq '{apex_id}'",
                                                select=None)  # None means get all fields
        else:
            # Filter fields based on info_type
            field_patterns = {
                "settlement": ["settlement", "amount", "estimate", "calculation"],
                "employment": ["hire", "term", "employ", "date", "rehire"],
                "earnings": ["wage", "earning", "pay", "statement", "gross", "net"],
                "disbursements": ["disbursement", "check", "payment", "void", "reissue"],
                "status": ["status", "state", "active", "included", "eligible"],
                "timeline": ["date", "created", "modified", "deadline", "cutoff"]
            }

            patterns = field_patterns.get(info_type, [])
            relevant_fields = []

            # Always include key identifier fields (but not PII)
            core_fields = ["new_classmemberid", "new_apexid", "_new_case_value"]
            relevant_fields.extend(core_fields)

            # Add fields matching the patterns
            for field in available_fields:
                field_lower = field.lower()
                if any(pattern in field_lower for pattern in patterns):
                    relevant_fields.append(field)

            # Remove duplicates while preserving order
            seen = set()
            unique_fields = []
            for field in relevant_fields:
                if field not in seen:
                    seen.add(field)
                    unique_fields.append(field)

            select_str = ",".join(unique_fields) if unique_fields else None
            member_result_str = query_entity_sync('new_classmembers',
                                                filter_str=f"new_apexid eq '{apex_id}'",
                                                select=select_str)

        member_results = json.loads(member_result_str)

        if not member_results:
            return json.dumps({
                "success": False,
                "error": f"No member found with ApexID: {apex_id}"
            })

        member_data = member_results[0]

        # Process and organize the data
        organized_info = {
            "success": True,
            "apex_id": apex_id,
            "basic_info": {},
            "settlement_info": {},
            "employment_info": {},
            "earnings_info": {},
            "disbursement_info": {},
            "status_info": {},
            "timeline_info": {},
            "additional_info": {}
        }

        # Categorize fields
        for field, value in member_data.items():
            if value is None or field.startswith('@'):
                continue

            field_lower = field.lower()

            # Basic info (exclude PII fields)
            if any(term in field_lower for term in ["name", "apexid", "social", "email", "phone", "address"]):
                # Only include non-PII fields
                if field in ['new_apexid', 'new_classmemberid', '_new_case_value']:
                    organized_info["basic_info"][field] = value
                # Skip PII fields like names, social, email, phone, address
            # Settlement info
            elif any(term in field_lower for term in ["settlement", "amount", "estimate", "calculation"]):
                organized_info["settlement_info"][field] = value
            # Employment info
            elif any(term in field_lower for term in ["hire", "term", "employ", "rehire"]):
                organized_info["employment_info"][field] = value
            # Earnings info
            elif any(term in field_lower for term in ["wage", "earning", "pay", "statement", "gross", "net", "hours", "weeks"]):
                organized_info["earnings_info"][field] = value
            # Status info
            elif any(term in field_lower for term in ["status", "state", "active", "included", "eligible"]):
                organized_info["status_info"][field] = value
            # Timeline info
            elif "date" in field_lower or "created" in field_lower or "modified" in field_lower:
                organized_info["timeline_info"][field] = value
            # Everything else
            else:
                organized_info["additional_info"][field] = value

        # If looking for disbursements specifically, also get them
        if info_type in ["all", "disbursements"]:
            try:
                disbursement_str = get_member_disbursements_sync(apex_id)
                disbursement_data = json.loads(disbursement_str)
                if disbursement_data.get('success'):
                    organized_info["disbursement_info"]["disbursements"] = disbursement_data.get('disbursements', [])
                    organized_info["disbursement_info"]["disbursement_count"] = disbursement_data.get('disbursement_count', 0)
            except Exception as e:
                logger.warning(f"Could not fetch disbursements: {e}")

        # Add helpful analysis
        analysis = []

        # Check for estimated settlement amount
        est_amount_fields = [f for f in organized_info["settlement_info"]
                           if "estimate" in f.lower() and "amount" in f.lower()]
        if est_amount_fields:
            for field in est_amount_fields:
                value = organized_info["settlement_info"][field]
                if value:
                    analysis.append(f"Estimated settlement amount: ${value}")

        # Check employment status
        hire_date = None
        term_date = None
        for field, value in organized_info["employment_info"].items():
            if "hire" in field.lower() and "date" in field.lower() and value:
                hire_date = value
            elif "term" in field.lower() and "date" in field.lower() and value:
                term_date = value

        if hire_date:
            analysis.append(f"Employment start date: {hire_date}")
        if term_date:
            analysis.append(f"Employment end date: {term_date}")

        # Add work statistics
        work_stats = []
        for field, value in organized_info["earnings_info"].items():
            if value and any(term in field.lower() for term in ["weeks", "periods", "shifts"]):
                work_stats.append(f"{field}: {value}")

        if work_stats:
            analysis.extend(work_stats)

        organized_info["analysis"] = analysis

        # Clean up empty sections for specific info_type requests
        if info_type != "all":
            # Keep only relevant sections
            sections_to_keep = ["success", "apex_id", "basic_info", "analysis"]
            if info_type == "settlement":
                sections_to_keep.append("settlement_info")
            elif info_type == "employment":
                sections_to_keep.extend(["employment_info", "timeline_info"])
            elif info_type == "earnings":
                sections_to_keep.extend(["earnings_info", "employment_info"])
            elif info_type == "disbursements":
                sections_to_keep.append("disbursement_info")
            elif info_type == "status":
                sections_to_keep.extend(["status_info", "settlement_info"])
            elif info_type == "timeline":
                sections_to_keep.append("timeline_info")

            # Remove empty or non-requested sections
            organized_info = {k: v for k, v in organized_info.items()
                            if k in sections_to_keep and (not isinstance(v, dict) or v)}

        # Remove empty sections and add member identifier
        final_info = {
            "success": True,
            "apex_id": apex_id,
            "member_identifier": f"Member {apex_id}",
            "info_type": info_type
        }

        # Only include non-empty sections
        for section, data in organized_info.items():
            if section not in ["success", "apex_id"] and data:
                final_info[section] = data

        return json.dumps(final_info, default=str)

    except Exception as e:
        logger.error(f"Error in get_class_member_details_sync: {str(e)}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": str(e),
            "message": "Error retrieving member information"
        })

@trace_function(name="dynamics.get_disbursements")
def get_member_disbursements_sync(apex_id: str, select_fields: Optional[str] = None) -> str:
    """
    CRITICAL: This function is ONLY for PAYMENT CHECK DISBURSEMENTS, NOT document notices.
    Use this ONLY when user asks about:
    - Check payments, check amounts, payment status
    - Disbursement dates, check cashing status
    - Check reissues, voided checks

    DO NOT use this for:
    - Notice documents, legal notices, settlement notices
    - PDF documents, document retrieval
    - Any kind of document or notice requests

    For documents/notices, use find_notice_for_user_sync() instead.
    """
    try:
        logger.info(f"🔍 Getting disbursements for member with ApexID: {apex_id} (Simplified Flow)")
        member_select_fields = "new_classmemberid,new_apexid,_new_case_value"
        member_filter = f"new_apexid eq '{apex_id}'"
        logger.info(f"Querying 'new_classmembers' with filter: {member_filter}")
        member_result_str = query_entity_sync('new_classmembers', filter_str=member_filter, select=member_select_fields)
        member_data_list = json.loads(member_result_str)
        if not member_data_list:
            logger.warning(f"No class member found with ApexID: {apex_id}")
            return json.dumps({
                "success": False,
                "error": f"No class member found with ApexID: {apex_id}",
                "apex_id": apex_id,
                "disbursements": [],
                "disbursement_count": 0
            })
        member_data = member_data_list[0]
        member_guid = member_data.get('new_classmemberid')

        # Heuristic fallback: sometimes the primary key field has a different name or is omitted from $select.
        if not member_guid:
            for k, v in member_data.items():
                if k.lower().endswith('id') and isinstance(v, str) and len(v) > 30 and '-' in v:
                    member_guid = v
                    logger.info(f"Heuristic GUID extraction: using {k} -> {v}")
                    break

        if not member_guid:
            try:
                logger.info("new_classmemberid not present via initial get or heuristic – re-querying for GUID only")
                # Call async query_entity directly to bypass sync wrapper's stripping for this specific fallback
                member_full_records = asyncio.run(
                    query_entity('new_classmembers', filter_str=member_filter, select='new_classmemberid')
                )
                if member_full_records and isinstance(member_full_records, list) and len(member_full_records) > 0:
                    member_guid = member_full_records[0].get('new_classmemberid')
                    logger.info(f"Retrieved GUID via direct async fallback: {member_guid}")
                else:
                    logger.warning(f"Direct async fallback GUID lookup also failed to find new_classmemberid or returned no records.")
            except Exception as guid_err:
                logger.warning(f"Direct async fallback GUID lookup failed with exception: {guid_err}")

        if not member_guid:
            logger.error(f"Could not retrieve 'new_classmemberid' for ApexID: {apex_id} after all fallbacks.")
            return json.dumps({
                "success": False,
                "error": "Could not retrieve member's unique identifier.",
                "apex_id": apex_id,
                "disbursements": [],
                "disbursement_count": 0
            })
        member_info = {
            "name": f"Member {apex_id}".strip() or member_data.get('new_fullname'),
            "apex_id": member_data.get('new_apexid', apex_id),
            "classmember_guid": member_guid,
            "case_guid": member_data.get('_new_case_value')
        }
        logger.info(f"Found member with ApexID: {apex_id} (GUID: {member_guid})")
        disbursement_entity = 'new_memberdisbursements'
        disbursement_filter = f"_new_classmember_value eq {member_guid}"
        default_disbursement_select = 'new_memberdisbursementid,new_checknumbertop,new_checkamount,new_checkdate,new_checkvoiddate,new_checkreissuerequest,new_checkcashed,new_name'
        actual_select_fields = select_fields if select_fields else default_disbursement_select
        logger.info(f"Querying '{disbursement_entity}' with filter: {disbursement_filter} and select: {actual_select_fields}")
        disbursements_result_str = query_entity_sync(disbursement_entity, filter_str=disbursement_filter, select=actual_select_fields)
        disbursements_list = json.loads(disbursements_result_str)
        logger.info(f"✅ Found {len(disbursements_list)} disbursement(s) for member {apex_id}")
        return json.dumps({
            "success": True,
            "member_info": member_info,
            "disbursements": disbursements_list,
            "disbursement_count": len(disbursements_list),
            "note": "Fetched disbursements directly associated with the class member."
        })
    except Exception as e:
        logger.error(f"❌ Error in simplified get_member_disbursements_sync for {apex_id}: {str(e)}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"Failed to get disbursements: {str(e)}",
            "apex_id": apex_id,
            "disbursements": [],
            "disbursement_count": 0
        })

# Removed duplicate function get_member_disbursements - use get_member_disbursements_sync instead

def search_disbursement_amounts_sync(apex_id: str, disbursement_id: Optional[str] = None) -> str:
    try:
        logger.info(f"🔍 Searching for disbursement amounts for member: {apex_id}")
        basic_disbursements_str = get_member_disbursements_sync(apex_id)
        disbursement_data = json.loads(basic_disbursements_str)
        if not disbursement_data.get("success") or disbursement_data.get("disbursement_count", 0) == 0:
            error_msg = disbursement_data.get("error", "No disbursements found for this member")
            return json.dumps({
                "error": error_msg,
                "amount_info": []
            })
        member_info = disbursement_data.get("member_info", {})
        case_guid = member_info.get("case_guid")
        disbursements = disbursement_data.get("disbursements", [])
        logger.info(f"🎯 Found {len(disbursements)} member-specific disbursements. Analyzing for amounts or related amount entities.")
        amount_results = []
        if case_guid:
            amount_search_entities = [
                "settlement", "payment", "fund", "amount"
            ]
            for search_term in amount_search_entities:
                try:
                    logger.info(f"🔍 Searching for entities related to '{search_term}' for case {case_guid}")
                    discovery_result = auto_discover_entity_sync(
                        search_term,
                        f"related to case {case_guid}"
                    )
                    discovery_data = json.loads(discovery_result)
                    if discovery_data.get("entity_name"):
                        entity_name = discovery_data["entity_name"]
                        available_fields = discovery_data.get("fields", [])
                        logger.info(f"🎯 Found potential amount entity via case: {entity_name}")
                        amount_fields = [f for f in available_fields
                                       if any(indicator in f.lower()
                                             for indicator in ["amount", "payment", "dollar", "settlement"])]
                        if amount_fields:
                            logger.info(f"💰 Found amount fields in {entity_name}: {amount_fields}")
                            try:
                                rel_filter = f"_new_case_value eq '{case_guid}'"
                                select_str = ",".join(amount_fields[:3] + [f for f in available_fields if "date" in f.lower() or "id" in f.lower()][:2])
                                amount_entity_data_str = query_entity_sync(entity_name, rel_filter, select_str)
                                amount_entity_data = json.loads(amount_entity_data_str)
                                if amount_entity_data:
                                    logger.info(f"✅ Found amount data in {entity_name} related to case!")
                                    amount_results.append({
                                        "source_entity": entity_name,
                                        "relationship_type": "case_related_amount",
                                        "case_guid": case_guid,
                                        "amount_fields_queried": amount_fields,
                                        "data": amount_entity_data
                                    })
                            except Exception as e:
                                logger.debug(f"Failed to query amount entity {entity_name} for case: {e}")
                except Exception as e:
                    logger.debug(f"Discovery failed for '{search_term}' (case related): {e}")
                    continue
        else:
            logger.info("No case_guid available from member_info, skipping case-related amount search.")
        if amount_results:
            logger.info(f"✅ Found additional amount information in {len(amount_results)} entities!")
            return json.dumps({
                "member_info": member_info,
                "direct_disbursements": disbursements,
                "additional_amount_info": amount_results,
                "summary": f"Found additional amount information across {len(amount_results)} related entities."
            })
        else:
            logger.info("ℹ️ No additional amount information found in related entities beyond direct disbursements.")
            return json.dumps({
                "member_info": member_info,
                "direct_disbursements": disbursements,
                "additional_amount_info": [],
                "summary": "Direct disbursement records found. No further amount information discovered in other related entities."
            })
    except Exception as e:
        logger.error(f"❌ Error searching for disbursement amounts: {str(e)}", exc_info=True)
        return json.dumps({
            "error": f"Failed to search for amount information: {str(e)}",
            "amount_info": []
        })

def get_comprehensive_member_info_sync(apex_id: str) -> str:
    try:
        logger.info(f"🤖 Getting comprehensive information for member: {apex_id}")
        disbursement_info_str = get_member_disbursements_sync(apex_id)
        disbursement_data = json.loads(disbursement_info_str)
        if not disbursement_data.get("success"):
            return json.dumps({
                "error": disbursement_data.get("error", f"No member found or error fetching basic info for ApexID: {apex_id}"),
                "comprehensive_info": {}
            })
        member_info = disbursement_data.get("member_info", {})
        case_guid = member_info.get("case_guid")
        comprehensive_info = {
            "member_basic": member_info,
            "disbursements_summary": {
                "count": disbursement_data.get("disbursement_count"),
                "data": disbursement_data.get("disbursements")
            },
            "case_info": {},
            "related_entities_discovered": [],
            "discovery_log": ["Retrieved direct member and disbursement information."]
        }
        logger.info("💰 Searching for additional amount information...")
        amount_info_str = search_disbursement_amounts_sync(apex_id)
        comprehensive_info["amount_search_details"] = json.loads(amount_info_str)
        comprehensive_info["discovery_log"].append("Searched for additional amount information across related entities.")
        if case_guid:
            logger.info("📁 Gathering case information...")
            try:
                case_result_str = query_entity_sync(
                    'incidents',
                    f"incidentid eq {case_guid}",
                    'title,ticketnumber,createdon,statuscode,description'
                )
                case_data_list = json.loads(case_result_str)
                if case_data_list:
                    comprehensive_info["case_info"] = case_data_list[0]
                    comprehensive_info["discovery_log"].append("Retrieved case information.")
                else:
                    comprehensive_info["discovery_log"].append(f"No case information found for GUID: {case_guid}")
            except Exception as e:
                logger.warning(f"Could not retrieve case info for GUID {case_guid}: {e}")
                comprehensive_info["discovery_log"].append(f"Case information not accessible for GUID: {case_guid}")
        else:
            comprehensive_info["discovery_log"].append("No case GUID linked to member, skipping case information retrieval.")
        logger.info("🔍 Auto-discovering other related entities (example)...")
        discovery_terms = ["settlementdetail", "noticepreference", "communicationlog"]
        for term in discovery_terms:
            try:
                discovery_result_str = auto_discover_entity_sync(
                    term,
                    f"related to class member {apex_id} or case {case_guid if case_guid else 'N/A'}"
                )
                discovery_data = json.loads(discovery_result_str)
                if discovery_data.get("entity_name"):
                    entity_name = discovery_data["entity_name"]
                    if entity_name not in ['new_classmembers', 'new_memberdisbursements', 'incidents']:
                        if entity_name not in [info.get("entity") for info in comprehensive_info["related_entities_discovered"]]:
                            comprehensive_info["related_entities_discovered"].append({
                                "entity": entity_name,
                                "discovery_term": term,
                                "fields_available": len(discovery_data.get("fields", [])),
                                "has_sample_data": bool(discovery_data.get("sample_data"))
                            })
            except Exception as e:
                logger.debug(f"Discovery failed for term '{term}': {e}")
        comprehensive_info["discovery_log"].append(f"Discovered {len(comprehensive_info['related_entities_discovered'])} other potentially related entities.")
        summary = {
            "member_found": True,
            "has_disbursements": comprehensive_info["disbursements_summary"].get("count", 0) > 0,
            "has_additional_amount_info": len(comprehensive_info["amount_search_details"].get("additional_amount_info", [])) > 0,
            "has_case_info": bool(comprehensive_info["case_info"]),
            "other_related_entities_count": len(comprehensive_info["related_entities_discovered"]),
            "discovery_steps_logged": len(comprehensive_info["discovery_log"])
        }
        comprehensive_info["final_summary"] = summary
        logger.info(f"✅ Comprehensive information gathered for {apex_id}")
        return json.dumps(comprehensive_info)
    except Exception as e:
        logger.error(f"❌ Error getting comprehensive member info: {str(e)}", exc_info=True)
        return json.dumps({
            "error": f"Failed to get comprehensive information: {str(e)}",
            "comprehensive_info": {}
        })

@trace_function(name="dynamics.navigate_relationships")
def navigate_entity_relationships_sync(start_entity: str, start_filter: str, target_data_type: str, max_depth: int = 3) -> str:
    try:
        logger.info(f"🧭 Starting agentic navigation from {start_entity} looking for {target_data_type}")
        with trace_dynamics_query(start_entity, "navigate", start_filter) as nav_span:
            if nav_span:
                nav_span.set_attribute("target_data_type", target_data_type)
                nav_span.set_attribute("max_depth", max_depth)
                nav_span.set_attribute(LucyAttributes.DYNAMICS_AUTO_DISCOVERED, True)
            navigation_results = {
                "start_entity": start_entity,
                "start_filter": start_filter,
                "target_data_type": target_data_type,
                "navigation_paths": [],
                "discovered_data": {},
                "relationship_map": {},
                "summary": {}
            }
            logger.info(f"📍 Step 1: Getting starting entity data...")
            start_result = query_entity_sync(start_entity, start_filter)
            start_data = json.loads(start_result)
            if nav_span:
                nav_span.set_attribute("start_records_found", len(start_data) if start_data else 0)
        if not start_data:
            return json.dumps({
                "error": f"No starting data found in {start_entity} with filter: {start_filter}",
                "navigation_results": navigation_results
            })
        navigation_results["start_data"] = start_data
        logger.info(f"✅ Found {len(start_data)} starting records")
        logger.info(f"🔍 Step 2: Discovering relationship paths...")
        relationship_paths = discover_relationship_paths_sync(start_entity, target_data_type, max_depth)
        path_data = json.loads(relationship_paths)
        navigation_results["relationship_map"] = path_data.get("relationship_map", {})
        potential_paths = path_data.get("potential_paths", [])
        logger.info(f"🗺️ Found {len(potential_paths)} potential navigation paths")
        all_discovered_data = {}
        successful_paths = []
        for path_info in potential_paths:
            try:
                path_name = path_info.get("path_name", "unknown")
                entities_in_path = path_info.get("entities", [])
                relationships = path_info.get("relationships", [])
                logger.info(f"🛤️ Navigating path: {path_name}")
                path_result = navigate_single_path_sync(
                    start_data,
                    entities_in_path,
                    relationships,
                    target_data_type
                )
                path_result_data = json.loads(path_result)
                if path_result_data.get("success") and path_result_data.get("target_data") is not None:
                    successful_paths.append({
                        "path_name": path_name,
                        "entities": entities_in_path,
                        "data_found": len(path_result_data.get("target_data", [])),
                        "path_result": path_result_data
                    })
                    target_data = path_result_data.get("target_data", [])
                    if target_data:
                        if path_name not in all_discovered_data:
                            all_discovered_data[path_name] = []
                        all_discovered_data[path_name].extend(target_data)
                        logger.info(f"✅ Path '{path_name}' found {len(target_data)} {target_data_type} records")
                    else:
                        logger.info(f"✅ Path '{path_name}' navigated successfully but found no {target_data_type} data")
            except Exception as e:
                logger.warning(f"❌ Path navigation failed for {path_name}: {e}")
                continue
        navigation_results["navigation_paths"] = successful_paths
        navigation_results["discovered_data"] = all_discovered_data
        total_records = sum(len(data) for data in all_discovered_data.values())
        navigation_results["summary"] = {
            "total_paths_explored": len(potential_paths),
            "successful_paths": len(successful_paths),
            "total_records_found": total_records,
            "data_sources": list(all_discovered_data.keys()),
            "navigation_success": total_records > 0
        }
        if total_records > 0:
            logger.info(f"🎯 Navigation SUCCESS: Found {total_records} {target_data_type} records across {len(successful_paths)} paths")
        else:
            logger.info(f"🔍 Navigation completed but no {target_data_type} data found")
        return json.dumps(navigation_results)
    except Exception as e:
        logger.error(f"❌ Error in agentic navigation: {str(e)}", exc_info=True)
        return json.dumps({
            "error": f"Navigation failed: {str(e)}",
            "navigation_results": navigation_results if 'navigation_results' in locals() else {}
        })

def discover_relationship_paths_sync(start_entity: str, target_data_type: str, max_depth: int = 3) -> str:
    try:
        logger.info(f"🗺️ Discovering relationship paths from {start_entity} to {target_data_type}")
        target_entities = discover_target_entities_sync(target_data_type)
        target_entity_list = json.loads(target_entities)
        logger.info(f"🎯 Found {len(target_entity_list)} potential target entities: {target_entity_list}")
        potential_paths = []
        relationship_map = {}
        if start_entity == "new_classmember" and target_data_type.lower() == "disbursement":
            if "new_memberdisbursements" in target_entity_list:
                 potential_paths.append({
                    "path_name": f"direct_{start_entity}_to_new_memberdisbursements",
                    "entities": [start_entity, "new_memberdisbursements"],
                    "relationships": ["_new_classmember_value"],
                    "depth": 1,
                    "is_preferred_path": True
                })
            if "new_casedisbursements" in target_entity_list:
                potential_paths.append({
                    "path_name": f"indirect_{start_entity}_via_case_to_new_casedisbursements",
                    "entities": [start_entity, "incidents", "new_casedisbursements"],
                    "relationships": ["_new_case_value", "_new_case_value"],
                    "depth": 2,
                    "is_preferred_path": False
                })
        else:
            try:
                start_relationships_str = discover_entity_relationships_sync(start_entity)
                start_rel_data = json.loads(start_relationships_str)
                relationship_map[start_entity] = start_rel_data
                for rel_attr, target_entities_list_from_rel in start_rel_data.items():
                    for target_entity_discovered in target_entity_list:
                        if target_entity_discovered in target_entities_list_from_rel:
                            potential_paths.append({
                                "path_name": f"direct_{start_entity}_to_{target_entity_discovered}_via_{rel_attr}",
                                "entities": [start_entity, target_entity_discovered],
                                "relationships": [rel_attr],
                                "depth": 1
                            })
                if max_depth > 1:
                    for rel_attr, intermediate_entities in start_rel_data.items():
                        for intermediate_entity in intermediate_entities:
                            try:
                                intermediate_relationships_str = discover_entity_relationships_sync(intermediate_entity)
                                intermediate_rel_data = json.loads(intermediate_relationships_str)
                                relationship_map[intermediate_entity] = intermediate_rel_data
                                for int_rel_attr, int_target_entities in intermediate_rel_data.items():
                                    for target_entity_discovered in target_entity_list:
                                        if target_entity_discovered in int_target_entities:
                                            potential_paths.append({
                                                "path_name": f"indirect_{start_entity}_via_{intermediate_entity}_to_{target_entity_discovered}",
                                                "entities": [start_entity, intermediate_entity, target_entity_discovered],
                                                "relationships": [rel_attr, int_rel_attr],
                                                "depth": 2
                                            })
                            except Exception as e:
                                logger.debug(f"Failed to get relationships for {intermediate_entity}: {e}")
                                continue
            except Exception as e:
                logger.warning(f"Failed to discover relationships for {start_entity}: {e}")
        logger.info(f"🛤️ Discovered {len(potential_paths)} potential navigation paths")
        return json.dumps({
            "potential_paths": potential_paths,
            "relationship_map": relationship_map,
            "target_entities": target_entity_list
        })
    except Exception as e:
        logger.error(f"❌ Error discovering relationship paths: {str(e)}", exc_info=True)
        return json.dumps({
            "potential_paths": [],
            "relationship_map": {},
            "target_entities": [],
            "error": str(e)
        })

def discover_target_entities_sync(target_data_type: str) -> str:
    try:
        logger.info(f"🎯 Discovering entities that might contain {target_data_type} data")
        all_entities_result = discover_entities_sync("new_")
        all_custom_entities = json.loads(all_entities_result)
        standard_entities_to_check = ['incidents']
        all_entities = all_custom_entities + [se for se in standard_entities_to_check if se not in all_custom_entities]
        search_patterns = {
            "disbursement": ["disburs", "payment", "check", "payout", "memberdisbursement", "casedisbursement"],
            "payment": ["payment", "pay", "disburs", "check", "settlement"],
            "amount": ["amount", "check", "payment", "settlement", "fund", "value"],
            "settlement": ["settlement", "amount", "fund", "agreement"],
            "notice": ["notice", "document", "title", "content", "letter"],
            "case": ["case", "incident", "title", "status", "matter"],
            "member": ["member", "class", "participant", "claimant", "contact"]
        }
        patterns = search_patterns.get(target_data_type.lower(), [target_data_type.lower()])
        target_entities = []
        for entity in all_entities:
            entity_lower = entity.lower()
            for pattern in patterns:
                if pattern in entity_lower:
                    if entity not in target_entities:
                        target_entities.append(entity)
                        logger.info(f"🎯 Found target entity: {entity} (matches pattern: {pattern})")
                    break
        if target_data_type.lower() == "disbursement":
            if "new_memberdisbursements" not in target_entities: target_entities.append("new_memberdisbursements")
            if "new_casedisbursements" not in target_entities: target_entities.append("new_casedisbursements")
        if target_data_type.lower() == "case" and "incidents" not in target_entities:
            target_entities.append("incidents")
        logger.info(f"✅ Discovered {len(target_entities)} target entities for {target_data_type}: {target_entities}")
        return json.dumps(target_entities)
    except Exception as e:
        logger.error(f"❌ Error discovering target entities: {str(e)}", exc_info=True)
        return json.dumps([])

def navigate_single_path_sync(start_data: List[Dict[str, Any]], entities_in_path: List[str], relationships: List[str], target_data_type: str) -> str:
    try:
        logger.info(f"🛤️ Navigating path: {' -> '.join(entities_in_path)}")
        current_data = start_data
        path_results = []
        for i in range(1, len(entities_in_path)):
            current_entity_name = entities_in_path[i-1]
            next_entity_name = entities_in_path[i]
            relationship_attr_for_next_filter = relationships[i-1] if i-1 < len(relationships) else f"_new_{current_entity_name.replace('new_', '')}_value"
            logger.info(f"🔗 Step {i}: {current_entity_name} -> {next_entity_name} using linking attribute: {relationship_attr_for_next_filter}")
            link_values_from_current_data = []
            primary_key_of_current_entity = None
            if current_entity_name == "new_classmembers": primary_key_of_current_entity = "new_classmemberid"
            elif current_entity_name == "incidents": primary_key_of_current_entity = "incidentid"
            if not primary_key_of_current_entity:
                 id_fields = [k for k in (current_data[0] if current_data else {}) if k.endswith("id")]
                 if id_fields: primary_key_of_current_entity = id_fields[0]
            if primary_key_of_current_entity:
                for record in current_data:
                    if primary_key_of_current_entity in record and record[primary_key_of_current_entity]:
                        link_values_from_current_data.append(record[primary_key_of_current_entity])
                        logger.info(f"Found link value from {primary_key_of_current_entity}: {record[primary_key_of_current_entity]}")
            else:
                 for record in current_data:
                    if relationship_attr_for_next_filter in record and record[relationship_attr_for_next_filter]:
                        link_values_from_current_data.append(record[relationship_attr_for_next_filter])
                        logger.info(f"Found link value from {relationship_attr_for_next_filter}: {record[relationship_attr_for_next_filter]}")
            if not link_values_from_current_data:
                logger.warning(f"No link values found in '{current_entity_name}' records to link to '{next_entity_name}' using '{primary_key_of_current_entity or relationship_attr_for_next_filter}'.")
                return json.dumps({"success": False, "error": f"No link values found for {primary_key_of_current_entity or relationship_attr_for_next_filter}", "path_results": path_results})
            next_data_accumulator = []
            for link_value in set(link_values_from_current_data):
                try:
                    filter_value_formatted = f"'{link_value}'" if not (len(link_value) > 30 and '-' in link_value) else link_value
                    next_entity_filter = f"{relationship_attr_for_next_filter} eq {filter_value_formatted}"
                    logger.info(f"Querying {next_entity_name} with filter: {next_entity_filter}")
                    next_result_str = smart_query_entity_sync(
                        entity_hint=next_entity_name,
                        filter_str=next_entity_filter,
                        select=None,
                        context=f"related to {current_entity_name} via {relationship_attr_for_next_filter}"
                    )
                    next_records = json.loads(next_result_str)
                    if next_records:
                        next_data_accumulator.extend(next_records)
                        logger.info(f"✅ Found {len(next_records)} records in {next_entity_name} for link value {link_value}")
                    else:
                        logger.debug(f"No records found in {next_entity_name} for link value {link_value} with filter {next_entity_filter}")
                except Exception as e:
                    logger.debug(f"Failed to query {next_entity_name} with filter {next_entity_filter}: {e}")
                    continue
            if not next_data_accumulator:
                logger.warning(f"No data found in {next_entity_name} for any link values.")
                return json.dumps({"success": False, "error": f"No data found in {next_entity_name}", "path_results": path_results})
            current_data = next_data_accumulator
            path_results.append({
                "entity": next_entity_name,
                "records_found": len(current_data),
                "sample_record": current_data[0] if current_data else None
            })
        final_entity_name = entities_in_path[-1]
        target_data_extracted = analyze_target_data(current_data, target_data_type, final_entity_name)
        return json.dumps({
            "success": True,
            "target_data": target_data_extracted,
            "path_results": path_results,
            "final_entity": final_entity_name
        })
    except Exception as e:
        logger.error(f"❌ Error navigating single path: {str(e)}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": str(e),
            "path_results": []
        })

def analyze_target_data(data: List[Dict[str, Any]], target_data_type: str, entity_name: str) -> List[Dict[str, Any]]:
    if not data:
        return []
    logger.info(f"🔍 Analyzing {len(data)} records from {entity_name} for {target_data_type} information")
    field_patterns = {
        "disbursement": ["disburs", "payment", "check", "amount", "date", "new_memberdisbursementid", "new_checkreissuerequest", "new_checkcashed", "new_checkvoiddate", "new_checknumbertop"],
        "payment": ["payment", "amount", "check", "disburs"],
        "amount": ["amount", "check", "payment", "settlement", "fund", "value"],
        "settlement": ["settlement", "amount", "fund", "agreement"],
        "notice": ["notice", "document", "title", "content", "letter"],
        "case": ["case", "incident", "title", "status", "matter"],
        "member": ["member", "name", "contact", "address", "apexid", "firstname", "lastname"]
    }
    patterns = field_patterns.get(target_data_type.lower(), [target_data_type.lower()])
    relevant_data = []
    for record in data:
        relevant_record = {}
        for key, value in record.items():
            if key.endswith('id') and value:
                relevant_record[key] = value
        for key, value in record.items():
            if key in relevant_record: continue
            key_lower = key.lower()
            for pattern in patterns:
                if pattern in key_lower and value is not None:
                    relevant_record[key] = value
                    break
        for key, value in record.items():
            if key in relevant_record: continue
            if 'date' in key.lower() and value:
                relevant_record[key] = value
        if target_data_type.lower() == "disbursement" and entity_name == "new_memberdisbursements":
            core_disbursement_fields = ['new_memberdisbursementid', 'new_checkamount', 'new_checknumbertop', 'new_checkdate', 'new_checkcashed', 'new_checkreissuerequest', 'new_checkvoiddate']
            for core_field in core_disbursement_fields:
                if core_field not in relevant_record and core_field in record:
                    relevant_record[core_field] = record[core_field]
        if relevant_record:
            relevant_data.append(relevant_record)
    logger.info(f"✅ Extracted {len(relevant_data)} relevant records for {target_data_type} from {entity_name}")
    return relevant_data

@trace_function(name="dynamics.reissue_check")
def reissue_check_sync(apex_id: str, disbursement_id: Optional[str] = None) -> str:
    try:
        logger.info(f"🔄 Processing check reissue request for ApexID: {apex_id} (Specific Disbursement ID: {disbursement_id if disbursement_id else 'None'})")
        disbursements_str = get_member_disbursements_sync(apex_id)
        disbursement_data = json.loads(disbursements_str)
        if not disbursement_data.get("success"):
            error_msg = disbursement_data.get("error", "Failed to retrieve disbursements for member.")
            logger.warning(f"Failed to get disbursements for {apex_id}: {error_msg}")
            return json.dumps({"success": False, "error": error_msg, "apex_id": apex_id})
        member_disbursements = disbursement_data.get("disbursements", [])
        logger.info(f"Found {len(member_disbursements)} member-specific disbursement records.")
        if not member_disbursements:
            return json.dumps({"success": False, "error": "No check disbursements found for this member.", "apex_id": apex_id})
        target_disbursement = None
        reissue_field = 'new_checkreissuerequest'
        if disbursement_id:
            logger.info(f"Processing specific disbursement ID: {disbursement_id}")
            specific_disbursement = next((d for d in member_disbursements if d.get('new_memberdisbursementid') == disbursement_id), None)
            if not specific_disbursement:
                logger.warning(f"Specified disbursement ID {disbursement_id} not found among member's checks.")
                return json.dumps({"success": False, "error": f"Disbursement with ID {disbursement_id} not found for this member.", "apex_id": apex_id})
            if specific_disbursement.get('new_checkcashed') == True:
                logger.info(f"Disbursement {disbursement_id} is cashed. Cannot reissue.")
                return json.dumps({"success": False, "error": "This check has already been cashed and cannot be reissued.", "apex_id": apex_id,
                                   "disbursement_info": {"disbursement_id": disbursement_id, "check_number": specific_disbursement.get('new_checknumbertop')}})
            if specific_disbursement.get(reissue_field) == True:
                logger.info(f"Disbursement {disbursement_id} already has {reissue_field}=true.")
                return json.dumps({
                    "success": True,
                    "message": "This check is already marked for reissue and is being processed.",
                    "disbursement_info": {
                        "disbursement_id": specific_disbursement.get('new_memberdisbursementid'),
                        "check_number": specific_disbursement.get('new_checknumbertop'),
                        "check_amount": specific_disbursement.get('new_checkamount'),
                        "check_date": specific_disbursement.get('new_checkdate'),
                        "void_date": specific_disbursement.get('new_checkvoiddate'),
                        "already_requested": True
                    },
                    "next_steps": "No further action is needed. Your reissue is in progress."
                })
            target_disbursement = specific_disbursement
            logger.info(f"Targeting specific uncashed, un-reissued check ID: {target_disbursement.get('new_memberdisbursementid')}")
        else:
            logger.info("No specific disbursement_id provided. Identifying eligible checks...")
            eligible_checks = [
                d for d in member_disbursements
                if not d.get('new_checkcashed') and not d.get(reissue_field)
            ]
            logger.info(f"Found {len(eligible_checks)} eligible (uncashed, not reissued) checks.")
            if len(eligible_checks) == 0:
                logger.info("No eligible (uncashed, not reissued) checks found.")
                all_uncashed_checks = [d for d in member_disbursements if not d.get('new_checkcashed')]
                if not all_uncashed_checks:
                    logger.info("No uncashed checks available at all.")
                    return json.dumps({"success": False, "error": "No uncashed checks are available for reissue.", "apex_id": apex_id})
                logger.info("All uncashed checks appear to be already requested for reissue or are cashed.")
                requested_uncashed_checks = [d for d in all_uncashed_checks if d.get(reissue_field)]
                if requested_uncashed_checks:
                    most_recent_requested_uncashed = sorted(requested_uncashed_checks, key=lambda x: x.get('new_checkdate', ''), reverse=True)[0]
                    return json.dumps({
                        "success": True,
                        "message": "The most recent uncashed check is already marked for reissue and is being processed.",
                        "disbursement_info": {
                            "disbursement_id": most_recent_requested_uncashed.get('new_memberdisbursementid'),
                            "check_number": most_recent_requested_uncashed.get('new_checknumbertop'),
                            "check_amount": most_recent_requested_uncashed.get('new_checkamount'),
                            "check_date": most_recent_requested_uncashed.get('new_checkdate'),
                            "void_date": most_recent_requested_uncashed.get('new_checkvoiddate'),
                            "already_requested": True
                        },
                        "next_steps": "No further action is needed. Your reissue is in progress."
                    })
                else:
                     return json.dumps({"success": False, "error": "All checks are either cashed or not eligible for reissue.", "apex_id": apex_id})
            elif len(eligible_checks) == 1:
                target_disbursement = eligible_checks[0]
                logger.info(f"One eligible check found. Targeting ID: {target_disbursement.get('new_memberdisbursementid')}")
            else:
                logger.info(f"Found {len(eligible_checks)} eligible checks. Returning candidates for user confirmation.")
                candidates_summary = []
                sorted_eligible_checks = sorted(eligible_checks, key=lambda x: x.get('new_checkdate', ''), reverse=True)
                for check in sorted_eligible_checks:
                    candidates_summary.append({
                        "disbursement_id": check.get('new_memberdisbursementid'),
                        "check_number": check.get('new_checknumbertop'),
                        "check_amount": check.get('new_checkamount'),
                        "check_date": check.get('new_checkdate'),
                        "void_date": check.get('new_checkvoiddate')
                    })
                return json.dumps({
                    "success": False,
                    "multiple_candidates": True,
                    "message": "I found multiple checks that can be reissued. Please confirm which one you'd like by providing its Disbursement ID or Check Number:",
                    "candidates": candidates_summary,
                    "apex_id": apex_id
                })
        if not target_disbursement:
             logger.error("Logic error: target_disbursement is None when it shouldn't be (e.g. specific ID not found or no eligible checks).")
             return json.dumps({"success": False, "error": "Could not identify a suitable check for reissue based on the criteria.", "apex_id": apex_id})
        disbursement_guid = target_disbursement.get('new_memberdisbursementid')
        if not disbursement_guid:
             logger.error(f"Target disbursement is missing 'new_memberdisbursementid'. Data: {target_disbursement}")
             return json.dumps({"success": False, "error": "Target disbursement missing critical ID.", "apex_id": apex_id})
        logger.info(f"Attempting to update entity 'new_memberdisbursements' with GUID: {disbursement_guid} to set {reissue_field}=true")
        update_payload = {reissue_field: True}
        update_result_str = update_entity_sync(
            'new_memberdisbursements',
            disbursement_guid,
            update_payload
        )
        if update_result_str == 'True':
            logger.info(f"✅ Successfully marked check for reissue: {disbursement_guid} using field {reissue_field}.")
            return json.dumps({
                "success": True,
                "message": "Check reissue request submitted successfully!",
                "disbursement_info": {
                    "disbursement_id": disbursement_guid,
                    "check_number": target_disbursement.get('new_checknumbertop'),
                    "check_amount": target_disbursement.get('new_checkamount'),
                    "check_date": target_disbursement.get('new_checkdate'),
                    "void_date": target_disbursement.get('new_checkvoiddate'),
                    "already_requested": False
                },
                "next_steps": "The check reissue will be processed by our accounting team within 5-7 business days."
            })
        else:
            logger.error(f"Update failed for reissue. update_entity_sync returned: {update_result_str} for GUID {disbursement_guid}")
            return json.dumps({
                "success": False,
                "error": "Failed to update reissue request in the system.",
                "apex_id": apex_id,
                "details": f"Update operation for {disbursement_guid} returned: {update_result_str}"
            })
    except Exception as e:
        logger.error(f"❌ Error processing check reissue for {apex_id}: {str(e)}", exc_info=True)
        return json.dumps({
            "success": False,
            "error": f"A technical error occurred while processing your reissue request: {str(e)}",
            "apex_id": apex_id
        })

def get_current_datetime_sync() -> str:
    from datetime import datetime
    import pytz
    utc_now = datetime.now(pytz.UTC)
    eastern = pytz.timezone('US/Eastern')
    pacific = pytz.timezone('US/Pacific')
    central = pytz.timezone('US/Central')
    eastern_now = utc_now.astimezone(eastern)
    pacific_now = utc_now.astimezone(pacific)
    central_now = utc_now.astimezone(central)
    return json.dumps({
        "current_datetime_utc": utc_now.isoformat(),
        "current_datetime_eastern": eastern_now.isoformat(),
        "current_datetime_pacific": pacific_now.isoformat(),
        "current_datetime_central": central_now.isoformat(),
        "date_only": eastern_now.strftime("%Y-%m-%d"),
        "formatted_date": eastern_now.strftime("%B %d, %Y"),
        "formatted_datetime": eastern_now.strftime("%B %d, %Y at %I:%M %p %Z"),
        "day_of_week": eastern_now.strftime("%A"),
        "timestamp": int(utc_now.timestamp()),
        "note": "All times shown for US timezones"
    })

def get_reissue_status_sync(apex_id: str) -> str:
    try:
        logger.info(f"Checking reissue status for ApexID: {apex_id} (Simplified Flow)")
        disbursements_str = get_member_disbursements_sync(apex_id)
        disbursement_data = json.loads(disbursements_str)
        if not disbursement_data.get("success"):
            error_msg = disbursement_data.get("error", "Failed to retrieve disbursements for status check.")
            logger.warning(f"Failed to get disbursements for status check for {apex_id}: {error_msg}")
            return json.dumps({"apex_id": apex_id, "reissue_requests": [], "message": error_msg})
        all_disbursements = disbursement_data.get("disbursements", [])
        if not all_disbursements:
            return json.dumps({
                "apex_id": apex_id,
                "reissue_requests": [],
                "message": "No disbursements found for this member."
            })
        reissue_info = []
        reissue_field_name = 'new_checkreissuerequest'
        completion_field_name = 'new_checkreissuecompleted'
        for d in all_disbursements:
            if d.get('new_memberdisbursementid') and 'new_checkamount' in d:
                reissue_info.append({
                    "disbursement_id": d.get('new_memberdisbursementid'),
                    "check_number": d.get('new_checknumbertop'),
                    "check_amount": d.get('new_checkamount'),
                    "check_date": d.get('new_checkdate'),
                    "reissue_requested": d.get(reissue_field_name, False),
                    "reissue_completed": d.get(completion_field_name, False),
                    "check_cashed": d.get('new_checkcashed'),
                    "void_date": d.get('new_checkvoiddate')
                })
        reissue_info.sort(key=lambda x: x.get('check_date', ''), reverse=True)
        return json.dumps({
            "apex_id": apex_id,
            "reissue_requests": reissue_info,
            "summary": {
                "total_checks": len(reissue_info),
                "pending_reissues": sum(1 for r in reissue_info if r.get('reissue_requested') and not r.get('reissue_completed')),
                "completed_reissues": sum(1 for r in reissue_info if r.get('reissue_completed'))
            }
        })
    except Exception as e:
        logger.error(f"❌ Error checking reissue status for {apex_id}: {str(e)}", exc_info=True)
        return json.dumps({
            "apex_id": apex_id,
            "error": f"Unable to check reissue status: {str(e)}"
        })

# ===== AGENTIC MEMBER UPDATE FUNCTIONS =====
# These functions provide intelligent, dynamic field discovery and updates

def discover_entity_fields_sync(entity_name: str) -> str:
    """
    Discover all available fields for a given entity using Dynamics 365 metadata.

    Args:
        entity_name: The entity name (e.g., "new_classmembers")

    Returns:
        JSON string with field metadata including names, types, and descriptions
    """
    try:
        result = asyncio.run(discover_entity_fields(entity_name))
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error discovering fields: {str(e)}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })

async def discover_entity_fields(entity_name: str) -> Dict[str, Any]:
    """
    Async implementation to discover entity fields from metadata.
    """
    access_token = await get_access_token()

    # Clean entity name
    if not entity_name.startswith("new_"):
        entity_name = f"new_{entity_name}"
    if entity_name.endswith("s") and not entity_name.endswith("ss"):
        entity_set = entity_name
    else:
        entity_set = entity_name + "s"

    try:
        # Query metadata endpoint
        metadata_url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/{entity_set}?$top=1"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json;odata.metadata=full",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0"
        }

        logger.info(f"Discovering fields for entity: {entity_set}")
        response = requests.get(metadata_url, headers=headers, timeout=15)

        if response.status_code == 200:
            # Parse the response to extract field information
            data = response.json()

            # Get field names from the first record if available
            if data.get("value") and len(data["value"]) > 0:
                record = data["value"][0]
                fields = []

                for field_name, field_value in record.items():
                    if not field_name.startswith("@") and not field_name.startswith("_"):
                        field_type = "string"
                        if isinstance(field_value, bool):
                            field_type = "boolean"
                        elif isinstance(field_value, (int, float)):
                            field_type = "number"
                        elif field_value and "Date" in str(field_value):
                            field_type = "datetime"

                        fields.append({
                            "name": field_name,
                            "type": field_type,
                            "sample_value": str(field_value) if field_value else None
                        })

                # Group fields by category for better understanding
                categorized_fields = categorize_agentic_fields(fields)

                return {
                    "success": True,
                    "entity": entity_set,
                    "total_fields": len(fields),
                    "categories": categorized_fields,
                    "all_fields": fields,
                    "updateable_fields": get_agentic_updateable_fields(fields)
                }
            else:
                # No records found, try to get metadata from $metadata endpoint
                return await get_agentic_entity_metadata(entity_set, access_token)

        else:
            return {
                "success": False,
                "error": f"Failed to discover fields: HTTP {response.status_code}",
                "details": response.text
            }

    except Exception as e:
        logger.error(f"Error discovering fields: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

def categorize_agentic_fields(fields: List[Dict]) -> Dict[str, List[str]]:
    """
    Categorize fields by their likely purpose based on naming patterns.
    """
    categories = {
        "personal_info": [],
        "address_info": [],
        "contact_info": [],
        "case_info": [],
        "financial_info": [],
        "dates": [],
        "status_flags": [],
        "other": []
    }

    for field in fields:
        name = field["name"].lower()

        if any(x in name for x in ["name", "firstname", "lastname", "middlename", "fullname"]):
            categories["personal_info"].append(field["name"])
        elif any(x in name for x in ["address", "city", "state", "zip"]):
            categories["address_info"].append(field["name"])
        elif any(x in name for x in ["email", "phone", "phonenumber"]):
            categories["contact_info"].append(field["name"])
        elif any(x in name for x in ["case", "claim", "apex", "member"]):
            categories["case_info"].append(field["name"])
        elif any(x in name for x in ["amount", "earnings", "payment", "disbursement", "settlement"]):
            categories["financial_info"].append(field["name"])
        elif "date" in name or field["type"] == "datetime":
            categories["dates"].append(field["name"])
        elif field["type"] == "boolean":
            categories["status_flags"].append(field["name"])
        else:
            categories["other"].append(field["name"])

    # Remove empty categories
    return {k: v for k, v in categories.items() if v}

def get_agentic_updateable_fields(fields: List[Dict]) -> List[str]:
    """
    Determine which fields are likely safe for member updates.
    """
    updateable = []

    # Patterns for updateable fields
    updateable_patterns = [
        "address", "city", "state", "zip",
        "email", "phone", "phonenumber",
        "new_address", "new_city", "new_state", "new_zip",
        "new_email", "new_phonenumber"
    ]

    # Patterns for non-updateable fields
    readonly_patterns = [
        "id", "created", "modified", "amount", "earnings",
        "settlement", "claim", "case", "status", "date"
    ]

    for field in fields:
        name = field["name"].lower()

        # Check if it matches updateable patterns
        if any(pattern in name for pattern in updateable_patterns):
            # Make sure it's not also in readonly patterns
            if not any(pattern in name for pattern in readonly_patterns):
                updateable.append(field["name"])

    return updateable

async def get_agentic_entity_metadata(entity_set: str, access_token: str) -> Dict[str, Any]:
    """
    Get entity metadata from the $metadata endpoint.
    """
    try:
        metadata_url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/$metadata"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/xml"
        }

        response = requests.get(metadata_url, headers=headers, timeout=15)

        if response.status_code == 200:
            # For now, just return that we found the entity
            return {
                "success": True,
                "entity": entity_set,
                "message": "Entity exists but no sample data available. Use smart_update_member_sync to update fields.",
                "hint": "Common updateable fields: new_address, new_city, new_state, new_zip, new_email, new_phonenumber"
            }
        else:
            return {
                "success": False,
                "error": f"Failed to get metadata: HTTP {response.status_code}"
            }
    except Exception as e:
        return {
            "success": False,
            "error": f"Metadata error: {str(e)}"
        }

def smart_update_member_sync(apex_id: str, update_request: str) -> str:
    """
    Intelligently update member information based on natural language request.
    This function can handle any field update by discovering and mapping fields.

    Args:
        apex_id: The member's APEX ID
        update_request: Natural language update request (e.g., "change address to 123 Main St, City, CA 12345")

    Returns:
        JSON string with update results
    """
    try:
        result = asyncio.run(smart_update_member(apex_id, update_request))
        return json.dumps(result, indent=2)
    except Exception as e:
        logger.error(f"Error in smart update: {str(e)}")
        return json.dumps({
            "success": False,
            "error": str(e)
        })

async def smart_update_member(apex_id: str, update_request: str) -> Dict[str, Any]:
    """
    Async implementation of smart member update.
    """
    try:
        # Parse the update request to extract field updates
        field_updates = parse_agentic_update_request(update_request)
        if _has_address_update(field_updates):
            coa_update, coa_error = _build_coa_reason_update("new_classmembers")
            if coa_error:
                logger.error("COA reason writeback blocked smart address update for %s: %s", apex_id, coa_error)
                return {
                    "success": False,
                    "error": coa_error,
                    "attempted_updates": field_updates
                }
            field_updates.update(coa_update)

        if not field_updates:
            return {
                "success": False,
                "error": "Could not parse update request. Please be more specific.",
                "hint": "Example: 'Update address to 123 Main St, Los Angeles, CA 90001'"
            }

        # Get member GUID first
        access_token = await get_access_token()
        member_filter = f"new_apexid eq '{apex_id}'"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0"
        }

        # Find member
        query_url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/new_classmembers?$filter={member_filter}&$select=new_classmemberid"
        response = requests.get(query_url, headers=headers, timeout=15)

        if response.status_code != 200 or not response.json().get("value"):
            return {
                "success": False,
                "error": f"Member with ApexID {apex_id} not found"
            }

        member_guid = response.json()["value"][0]["new_classmemberid"]

        # Perform the update
        update_url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/new_classmembers({member_guid})"
        update_headers = headers.copy()
        update_headers["Content-Type"] = "application/json"
        update_headers["If-Match"] = "*"

        logger.info(f"Updating member {apex_id} with: {field_updates}")

        response = requests.patch(update_url, json=field_updates, headers=update_headers, timeout=15)

        if response.status_code in [204, 200]:
            # Verify the update
            verify_url = f"{DYNAMICS_CONFIG['resource_url']}/api/data/v9.2/new_classmembers({member_guid})?$select={','.join(field_updates.keys())}"
            verify_response = requests.get(verify_url, headers=headers, timeout=15)

            if verify_response.status_code == 200:
                updated_values = verify_response.json()
                return {
                    "success": True,
                    "message": "Member profile updated successfully",
                    "apex_id": apex_id,
                    "updates_applied": field_updates,
                    "current_values": updated_values
                }
            else:
                return {
                    "success": True,
                    "message": "Member profile updated successfully (verification failed)",
                    "apex_id": apex_id,
                    "updates_applied": field_updates,
                    "note": "Update succeeded but could not verify new values"
                }
        else:
            error_detail = response.text
            return {
                "success": False,
                "error": f"Update failed: {error_detail}",
                "attempted_updates": field_updates
            }

    except Exception as e:
        logger.error(f"Error updating member: {str(e)}")
        return {
            "success": False,
            "error": str(e)
        }

def parse_agentic_update_request(request: str) -> Dict[str, Any]:
    """
    Parse natural language update request into field updates.
    """
    updates = {}
    request_lower = request.lower()

    # Address parsing
    if "address" in request_lower:
        import re
        # Try to extract address components
        # Pattern: number street, city, state zip
        address_pattern = r'(\d+\s+[^,]+),\s*([^,]+),\s*([A-Z]{2})\s+(\d{5}(?:-\d{4})?)'
        match = re.search(address_pattern, request, re.IGNORECASE)

        if match:
            updates["new_address1"] = match.group(1).strip()  # Fixed: Use new_address1 instead of new_address
            updates["new_city"] = match.group(2).strip()
            updates["new_stateorprovince"] = match.group(3).upper()  # Fixed: Use correct field name
            updates["new_postalcode"] = match.group(4).strip()  # Fixed: Use new_postalcode instead of new_zip
        else:
            # Try simpler pattern
            if " to " in request_lower:
                address_part = request.split(" to ", 1)[1].strip()
                # At minimum, try to extract the street address
                parts = address_part.split(",")
                if parts:
                    updates["new_address1"] = parts[0].strip()  # Fixed: Use new_address1
                    if len(parts) > 1:
                        updates["new_city"] = parts[1].strip()
                    if len(parts) > 2:
                        state_zip = parts[2].strip().split()
                        if state_zip:
                            updates["new_stateorprovince"] = state_zip[0].strip()  # Fixed: Use correct field name
                        if len(state_zip) > 1:
                            updates["new_postalcode"] = state_zip[1].strip()  # Fixed: Use correct field name

    # Phone parsing
    if "phone" in request_lower:
        import re
        phone_pattern = r'[\d\s\-\(\)]+\d'
        phones = re.findall(phone_pattern, request)
        if phones:
            # Take the last phone number found
            phone = phones[-1].strip()
            # Clean it up a bit
            phone = re.sub(r'[^\d\-]', '', phone)
            updates["new_phonenumber"] = phone

    # Email parsing
    if "email" in request_lower:
        import re
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        emails = re.findall(email_pattern, request)
        if emails:
            updates["new_email"] = emails[0]

    return updates

def find_notice_for_user_sync(apex_id: str) -> str:
    """
    CRITICAL: Find and retrieve CLASS ACTION NOTICES (legal documents) for a member using Azure AI Search.
    This is for DOCUMENT RETRIEVAL, NOT disbursement checks or payments.
    Uses the new Azure AI Search index with native RAG capabilities.

    TODO: Create Azure Container Job for SharePoint to Blob Storage sync
    Current state: PDFs are stored in Azure Blob Storage (lucycmnotices container)
    Needed: Automated container job to sync PDFs from SharePoint to Blob Storage
    - Run on schedule (daily/hourly based on update frequency)
    - Copy only PDF files from SharePoint document library
    - Maintain folder structure or flatten to lucycmnotices/ container
    - Trigger Azure AI Search indexer after sync completes
    - Add error handling and logging for failed sync operations

    Args:
        apex_id: The member's APEX ID for document search

    Returns:
        String containing PDF display, download link, and comprehensive AI-powered analysis
    """
    try:
        logger = logging.getLogger("UserFunctions.NoticeSearch")
        logger.info(f"🔍 Starting NOTICE DOCUMENT search for APEX ID: {apex_id}")

        if not apex_id:
            return "ERROR: APEX ID is required for notice search"

        # Use direct Azure AI Search instead of importing from apex
        try:
            from azure.search.documents import SearchClient
            from azure.core.credentials import AzureKeyCredential
            from azure.core.exceptions import HttpResponseError
            from azure.identity import DefaultAzureCredential
            import json

            # Get search configuration from environment
            search_endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
            search_api_key = os.getenv("AZURE_SEARCH_API_KEY")
            search_index_name = os.getenv("AZURE_SEARCH_INDEX_NAME")

            if not search_endpoint:
                logger.error("AZURE_SEARCH_ENDPOINT not configured")
                return "ERROR: Search service not configured"

            if not search_index_name:
                logger.error("AZURE_SEARCH_INDEX_NAME not configured")
                return "ERROR: Search index not configured"

            # Create search client
            if search_api_key:
                credential = AzureKeyCredential(search_api_key)
            else:
                credential = DefaultAzureCredential()

            search_client = SearchClient(
                endpoint=search_endpoint,
                index_name=search_index_name,
                credential=credential
            )

            # Strategy 1: APEX ID exact match using text search (not filter)
            clean_apex_id = "".join(c for c in apex_id if c.isalnum())
            search_query = f"{clean_apex_id}.pdf"

            logger.info(f"🔍 DOCUMENT search query: '{search_query}'")

            # Execute search using text search instead of filter
            search_kwargs = {
                "search_text": search_query,
                "top": 5,
                "include_total_count": True,
                "filter": "file_extension eq '.pdf'",
                "select": [
                    "chunk",
                    "metadata_storage_name",
                    "metadata_storage_path",
                    "metadata_storage_file_extension",
                    "file_extension",
                ],
            }

            filter_used = "filter" in search_kwargs
            try:
                search_results = search_client.search(**search_kwargs)
            except HttpResponseError:
                logger.warning("⚠️ PDF filter failed; retrying search without filter", exc_info=True)
                search_kwargs.pop("filter", None)
                filter_used = False
                search_results = search_client.search(**search_kwargs)

            results_list = list(search_results)
            if filter_used and not results_list:
                logger.warning("⚠️ PDF filter returned no results; retrying search without filter")
                search_kwargs.pop("filter", None)
                results_list = list(search_client.search(**search_kwargs))
            logger.info(f"[Lucy] Document search returned {len(results_list)} results before filtering")

            # Filter to ensure only PDF files are returned (defensive filter for indexer misconfiguration)
            pdf_results = []
            for result in results_list:
                storage_path = result.get("metadata_storage_path", "")
                storage_name = result.get("metadata_storage_name", "")

                # Check if file is a PDF by extension
                is_pdf = storage_path.lower().endswith(".pdf") or storage_name.lower().endswith(".pdf")

                if is_pdf:
                    pdf_results.append(result)
                else:
                    # Log filtered non-PDF files for debugging
                    filtered_name = storage_name or storage_path
                    logger.info(f"[Lucy] Filtered out non-PDF file: {filtered_name}")

            results_list = pdf_results
            logger.info(f"[Lucy] After PDF filtering: {len(results_list)} PDF results")

            if not results_list:
                return f"I couldn't find a notice document for APEX ID {apex_id}. This sometimes happens when there's a delay between when a notice is mailed and when it becomes available in our system. You can check back in about two weeks, or I can help you with other questions about your case."

            # Get the first document result
            doc = results_list[0]

            # Build blob URL for PDF access
            storage_account = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
            if not storage_account:
                logger.error("AZURE_STORAGE_ACCOUNT_NAME not set")
                return "ERROR: Storage account not configured"
            container_name = (
                os.getenv("AZURE_STORAGE_CONTAINER_NAME")
                or os.getenv("AZURE_STORAGE_CONTAINER")
                or "lucyrag"
            )

            storage_path = doc.get("metadata_storage_path")
            if not storage_path:
                logger.error("No storage path found in search result")
                return "ERROR: Document path not found"

            # Check if storage_path is already a full URL
            if storage_path.lower().startswith("http"):
                blob_url = storage_path  # Already a full URL
            else:
                # Ensure proper blob URL format from path
                raw_path = storage_path.lstrip("/")
                if not raw_path.lower().startswith(f"{container_name.lower()}/"):
                    raw_path = f"{container_name}/{raw_path}"
                blob_url = f"https://{storage_account}.blob.core.windows.net/{raw_path}"

            # Generate SAS URL for secure access
            # Using local generate_sas_url function instead of apex import
            sas_url = generate_sas_url(blob_url)
            if not sas_url or sas_url.startswith("ERROR"):
                logger.error("Failed to generate SAS URL for PDF access")
                return f"ERROR: Cannot generate secure access link for document"

            # Use SAS URL for download link
            download_url = sas_url

            # Collect RAG chunks for AI analysis
            all_chunks = []
            for result in results_list:
                chunk_content = result.get("chunk", "").strip()
                if chunk_content:
                    all_chunks.append(chunk_content)

            if all_chunks:
                full_rag_content = "\n\n".join(all_chunks)
                logger.info(f"[Lucy] Collected {len(all_chunks)} chunks with {len(full_rag_content)} characters for analysis")

                # Return structured response with PDF URL for agent to handle
                return f"""I've found your notice **{clean_apex_id}**! Here's what I can tell you:

📄 **[{clean_apex_id} - Click to Download]({download_url})**

**COMPREHENSIVE NOTICE ANALYSIS:**

Based on the indexed content from your **{clean_apex_id}** notice, I can now provide you with a detailed analysis. Here is the complete content for me to analyze:

<NOTICE_CONTENT>
{full_rag_content}
</NOTICE_CONTENT>

Let me now provide you with a comprehensive, intelligent summary of the important information in your notice, including key dates, eligibility requirements, settlement amounts, and any actions you need to take.

**PDF_DISPLAY_INFO:**
- PDF_URL: {sas_url}
- PDF_NAME: notice_{clean_apex_id}
- DISPLAY_MODE: inline"""
            else:
                # Return structured response with PDF URL for agent to handle
                return f"""I've found your notice **{clean_apex_id}**!

📄 **[{clean_apex_id} - Click to Download]({download_url})**

If you have any specific questions about the notice content, please let me know and I can help analyze it further.

**PDF_DISPLAY_INFO:**
- PDF_URL: {sas_url}
- PDF_NAME: notice_{clean_apex_id}
- DISPLAY_MODE: inline"""

        except Exception as search_error:
            logger.error(f"Azure AI Search error: {search_error}")
            return f"ERROR: Document search failed: {str(search_error)}"

    except Exception as e:
        logger.error(f"Error in notice search for {apex_id}: {e}")
        return f"ERROR: Notice search failed: {str(e)}"

@trace_function(name="callback.collect_info")
def collect_callback_information_sync(apex_id: str, conversation_id: str, reason: str) -> str:
    """
    Collect callback information from the user after 4-minute timeout

    Args:
        apex_id: Member's APEX ID
        conversation_id: Conversation ID that timed out
        reason: Original reason for assistance

    Returns:
        JSON string with callback collection status
    """
    try:
        logger.info(f"📞 Collecting callback information for {apex_id} (conversation: {conversation_id})")

        return json.dumps({
            "success": True,
            "message": "I understand no agent was available immediately. I'd be happy to arrange a callback for you.",
            "collect_phone": True,
            "collect_best_time": True,
            "conversation_id": conversation_id,
            "apex_id": apex_id,
            "reason": reason,
            "instructions": [
                "Please provide your phone number (including area code)",
                "Let me know the best time to call you (PST 9am-5pm weekdays)",
                "What specific assistance do you need regarding your case?"
            ]
        })

    except Exception as e:
        logger.error(f"❌ Error collecting callback info for {apex_id}: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "message": "I'm sorry, there was an error setting up your callback. Please try again or call our support line."
        })

@trace_function(name="callback.submit_request")
def submit_callback_request_sync(apex_id: str, conversation_id: str, phone_number: str,
                                best_time: str, reason: str) -> str:
    """
    Submit a callback request with user information

    Args:
        apex_id: Member's APEX ID
        conversation_id: Original conversation ID
        phone_number: User's phone number
        best_time: Best time to call (PST 9am-5pm)
        reason: Assistance needed

    Returns:
        JSON string with submission status
    """
    try:
        import asyncio
        logger.info(f"📞 Submitting callback request for {apex_id}")
        logger.info(f"📞 Details - Phone: {phone_number}, Time: {best_time}, Reason: {reason}")

        # Check if Azure Storage is configured
        if not os.getenv("AZURE_STORAGE_CONNECTION_STRING"):
            logger.warning("❌ AZURE_STORAGE_CONNECTION_STRING not configured!")
            return json.dumps({
                "success": False,
                "message": "⚠️ Callback system is temporarily unavailable. Please try again later or call our support line directly.",
                "error": "Azure Storage not configured"
            })

        # Check if callback_system was loaded at startup
        if not CALLBACK_SYSTEM_AVAILABLE:
            logger.error("❌ CALLBACK SYSTEM NOT AVAILABLE - Module failed to load at startup")
            return json.dumps({
                "success": False,
                "message": "❌ **ERROR: CALLBACK SYSTEM NOT AVAILABLE**\n\nThe callback system module could not be loaded. This is a deployment issue.\n\nPlease:\n• Call our support line directly\n• Try again later\n• Contact support via email",
                "error": "callback_system module not available at startup",
                "apex_id": apex_id
            })

        try:
            from callback_system import create_callback_request_async

            # Try to get the member's actual name from CRM
            try:
                member_details = get_class_member_details_sync(apex_id, "all")
                details_data = json.loads(member_details)
                if details_data.get("success") and details_data.get("data"):
                    member_data = details_data["data"]
                    member_name = f"{member_data.get('firstname', '')} {member_data.get('lastname', '')}".strip()
                    if not member_name:
                        member_name = f"Member {apex_id}"
                else:
                    member_name = f"Member {apex_id}"
            except:
                member_name = f"Member {apex_id}"

            user_info = {
                "apex_id": apex_id,
                "name": member_name
            }

            logger.info(f"📞 Creating callback for: {member_name} ({apex_id})")

            # Create callback request
            callback_id = _safe_async_run(create_callback_request_async(
                conversation_id=conversation_id,
                user_info=user_info,
                reason=reason,
                phone_number=phone_number,
                best_time=best_time
            ))

            logger.info(f"✅ Callback created with ID: {callback_id}")

        except ImportError as import_error:
            logger.error(f"❌ CALLBACK SYSTEM FAILED: {import_error}")
            return json.dumps({
                "success": False,
                "message": "❌ **ERROR: CALLBACK SYSTEM NOT WORKING**\n\nI cannot submit callback requests right now due to a system issue. Please:\n\n• Call our support line directly\n• Try again later\n• Contact support via email\n\nI apologize for the inconvenience.",
                "error": f"Callback system module not available: {import_error}",
                "apex_id": apex_id
            })
        except Exception as callback_error:
            logger.error(f"❌ Error creating callback request: {callback_error}")
            return json.dumps({
                "success": False,
                "message": "❌ **ERROR: CALLBACK SYSTEM NOT WORKING**\n\nThere was a technical error submitting your callback request. Please:\n\n• Call our support line directly\n• Try again later\n• Contact support via email\n\nI apologize for the inconvenience.",
                "error": str(callback_error),
                "apex_id": apex_id
            })

        if callback_id:
            return json.dumps({
                "success": True,
                "message": f"✅ **Callback request submitted successfully!**\n\n**Phone:** {phone_number}\n**Best time:** {best_time}\n**Request:** {reason}\n\nOur support team will call you during your preferred time window. You should receive a call within 24 hours.",
                "callback_id": callback_id,
                "phone_number": phone_number,
                "best_time": best_time,
                "reason": reason
            })
        else:
            return json.dumps({
                "success": False,
                "message": "❌ **ERROR: CALLBACK SYSTEM NOT WORKING**\n\nI cannot submit callback requests right now. Please:\n\n• Call our support line directly\n• Try again later\n• Contact support via email\n\nI apologize for the inconvenience.",
                "error": "Failed to create callback request",
                "apex_id": apex_id
            })

    except Exception as e:
        logger.error(f"❌ Error submitting callback request for {apex_id}: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "message": "I'm sorry, there was an error submitting your callback request. Please try again or call our support line."
        })

def _safe_async_run(coro):
    """
    Safely run an async coroutine, handling the case where we're already in an event loop.
    Enhanced with better error handling for event loop issues.
    """
    try:
        # Try to get the current event loop
        loop = asyncio.get_running_loop()

        # Check if the loop is closed
        if loop.is_closed():
            logger.warning("Current event loop is closed, creating new one")
            return asyncio.run(coro)

        # We're in an async context, need to handle this differently
        import concurrent.futures
        import threading

        def run_in_executor():
            try:
                # Create a new event loop for this thread
                new_loop = asyncio.new_event_loop()
                asyncio.set_event_loop(new_loop)
                try:
                    result = new_loop.run_until_complete(coro)
                    return result
                finally:
                    # Properly close the loop
                    try:
                        new_loop.close()
                    except Exception as close_error:
                        logger.warning(f"Error closing event loop: {close_error}")
            except Exception as executor_error:
                logger.error(f"Error in executor thread: {executor_error}")
                raise

        # Run in a thread pool to avoid event loop conflict
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(run_in_executor)
                return future.result(timeout=30)  # Increased timeout
        except concurrent.futures.TimeoutError:
            logger.error("Async operation timed out after 30 seconds")
            raise TimeoutError("Async operation timed out")

    except RuntimeError as re:
        # No running event loop, safe to use asyncio.run()
        try:
            return asyncio.run(coro)
        except RuntimeError as run_error:
            if "Event loop is closed" in str(run_error):
                logger.warning("Event loop is closed, trying with new loop")
                # Create a fresh event loop
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                try:
                    return loop.run_until_complete(coro)
                finally:
                    loop.close()
            else:
                raise run_error
    except Exception as e:
        logger.error(f"Unexpected error in _safe_async_run: {e}")
        raise

@trace_function(name="callback.get_pending")
def get_pending_callbacks_sync() -> str:
    """
    Get all pending callback requests for the agent portal

    Returns:
        JSON string with pending callbacks
    """
    try:
        import asyncio
        from callback_system import get_pending_callbacks_async

        logger.info("📞 Fetching pending callback requests")

        callbacks = _safe_async_run(get_pending_callbacks_async())

        return json.dumps({
            "success": True,
            "callbacks": callbacks,
            "count": len(callbacks)
        })

    except Exception as e:
        logger.error(f"❌ Error fetching pending callbacks: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "callbacks": []
        })

@trace_function(name="callback.mark_completed")
def mark_callback_completed_sync(callback_id: str, agent_notes: str = "") -> str:
    """
    Mark a callback as completed with agent notes

    Args:
        callback_id: Callback request ID
        agent_notes: Notes from the agent about the call

    Returns:
        JSON string with completion status
    """
    try:
        import asyncio
        from callback_system import mark_callback_completed_async

        logger.info(f"📞 Marking callback {callback_id} as completed")

        success = _safe_async_run(mark_callback_completed_async(callback_id, agent_notes))

        if success:
            return json.dumps({
                "success": True,
                "message": "Callback marked as completed successfully",
                "callback_id": callback_id
            })
        else:
            return json.dumps({
                "success": False,
                "message": "Failed to mark callback as completed",
                "callback_id": callback_id
            })

    except Exception as e:
        logger.error(f"❌ Error marking callback completed: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "message": "Error marking callback as completed"
        })

@trace_function(name="conversation.store_history")
def store_conversation_history_sync(conversation_id: str, conversation_type: str,
                                  messages: List[Dict[str, Any]], metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Store conversation history using the simple conversation store

    Args:
        conversation_id: Conversation ID
        conversation_type: 'pre_handoff' or 'agent_human'
        messages: List of messages
        metadata: Additional metadata

    Returns:
        JSON string with storage status
    """
    try:
        # Try to use the simple store first
        success = False
        try:
            from conversation_store import conversation_store
            logger.info(f"💬 Storing {conversation_type} conversation history for {conversation_id} using simple store")
            apex_id = None
            if metadata and isinstance(metadata, dict):
                apex_id = metadata.get("apex_id")
            success = conversation_store.store_handoff_conversation(
                conversation_id,
                messages,
                apex_id=apex_id,
                status="pending",
                status_reason=f"{conversation_type}_history",
                metadata=metadata,
            )
        except Exception as store_error:
            logger.warning(f"Simple store failed: {store_error}, falling back to callback_system")

        # If simple store failed, try the old method
        if not success:
            try:
                from callback_system import store_conversation_history_async
                success = _safe_async_run(store_conversation_history_async(
                    conversation_id, conversation_type, messages, metadata or {}
                ))
                if success:
                    logger.info("✅ Stored using callback_system fallback")
            except Exception as e:
                logger.error(f"Both storage methods failed: {e}")
                success = False

        if success:
            return json.dumps({
                "success": True,
                "message": "Conversation history stored successfully",
                "conversation_id": conversation_id,
                "type": conversation_type,
                "message_count": len(messages)
            })
        else:
            return json.dumps({
                "success": False,
                "message": "Failed to store conversation history",
                "conversation_id": conversation_id
            })

    except Exception as e:
        logger.error(f"❌ Error storing conversation history: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "message": "Error storing conversation history"
        })

@trace_function(name="conversation.get_history")
def get_conversation_history_sync(conversation_id: str, conversation_type: Optional[str] = None) -> str:
    """
    Get conversation history using the simple conversation store

    Args:
        conversation_id: Conversation ID
        conversation_type: Optional filter by type

    Returns:
        JSON string with conversation history
    """
    try:
        # Import the simple store
        try:
            from conversation_store import conversation_store
        except ImportError:
            logger.error("❌ conversation_store module not available")
            # Fallback to old method
            from callback_system import get_conversation_history_async
            conversations = _safe_async_run(get_conversation_history_async(conversation_id, conversation_type))
        else:
            # Use the simple store
            logger.info(f"💬 Fetching conversation history for {conversation_id} using simple store")
            conversation = conversation_store.get_handoff_conversation(conversation_id)

            if conversation:
                # Format to match expected structure
                conversations = [{
                    "conversation_id": conversation_id,
                    "conversation_type": "pre_handoff",
                    "messages": conversation.get("messages", []),
                    "message_count": conversation.get("message_count", 0),
                    "created_at": conversation.get("stored_at", "")
                }]
            else:
                # Simple store didn't find anything, fall back to callback_system (like storage does)
                logger.warning(f"Simple store didn't find conversation {conversation_id}, trying callback_system fallback")
                try:
                    from callback_system import get_conversation_history_async
                    conversations = _safe_async_run(get_conversation_history_async(conversation_id, conversation_type))
                    logger.info(f"✅ Callback_system fallback found {len(conversations)} conversations")
                except Exception as fallback_error:
                    logger.error(f"❌ Callback_system fallback also failed: {fallback_error}")
                    conversations = []

        return json.dumps({
            "success": True,
            "conversations": conversations,
            "count": len(conversations),
            "conversation_id": conversation_id
        })

    except Exception as e:
        logger.error(f"❌ Error fetching conversation history: {e}")
        error_msg = str(e)
        if "not configured" in error_msg.lower():
            error_msg = "Azure Storage not configured for conversation history. Please set AZURE_STORAGE_CONNECTION_STRING environment variable."

        return json.dumps({
            "success": False,
            "error": error_msg,
            "conversations": [],
            "conversation_id": conversation_id
        })

@trace_function(name="dynamics.add_agent_note")
def add_agent_note_to_member_sync(apex_id: str, agent_name: str, note_content: str,
                                 conversation_id: Optional[str] = None) -> str:
    """
    Add an agent note to a member's Dynamics 365 profile

    Args:
        apex_id: Member's APEX ID
        agent_name: Name of the agent adding the note
        note_content: Content of the note
        conversation_id: Optional conversation ID

    Returns:
        JSON string with note addition status
    """
    try:
        logger.info(f"📝 Adding agent note to member {apex_id} profile")

        # Look up member record using apex_id directly
        try:
            # Query for the member using apex_id (always uppercase in Dynamics)
            # Escape single quotes in OData filter (single quote becomes two single quotes)
            escaped_apex_id = apex_id.upper().replace("'", "''")
            filter_str = f"new_apexid eq '{escaped_apex_id}'"
            result_str = query_entity_sync("new_classmembers", filter_str=filter_str, select="new_classmemberid,new_apexid,new_firstname,new_lastname")
            result = json.loads(result_str)

            if not result or len(result) == 0:
                return json.dumps({
                    "success": False,
                    "error": "Member not found with APEX ID",
                    "apex_id": apex_id
                })

            member = result[0]
            member_guid = member.get("new_classmemberid")
        except Exception as lookup_error:
            logger.error(f"Error looking up member {apex_id}: {lookup_error}")
            return json.dumps({
                "success": False,
                "error": f"Database lookup failed: {str(lookup_error)}",
                "apex_id": apex_id
            })

        if not member_guid:
            return json.dumps({
                "success": False,
                "error": "Member GUID not found",
                "apex_id": apex_id
            })

        # Prepare the note data
        from datetime import datetime
        import pytz
        pacific = pytz.timezone('America/Los_Angeles')
        current_time = datetime.now(pacific)

        # Format the note with timestamp and agent info
        formatted_note = f"[{current_time.strftime('%Y-%m-%d %H:%M:%S')} PST] Agent: {agent_name}\n"
        if conversation_id:
            formatted_note += f"Conversation ID: {conversation_id}\n"
        formatted_note += f"Note: {note_content}"

        # Since new_agentnotes field doesn't exist in the schema,
        # create a note as an annotation entity linked to the class member
        try:
            note_data = {
                "subject": f"Agent Note - {agent_name}",
                "notetext": formatted_note,
                "objectid_new_classmember@odata.bind": f"/new_classmembers({member_guid})",
                "isdocument": False
            }

            # Create annotation (note) entity
            create_result = create_entity_sync("annotations", note_data)

            if create_result and create_result != "False":
                return json.dumps({
                    "success": True,
                    "message": "Agent note created as separate record",
                    "apex_id": apex_id,
                    "agent_name": agent_name,
                    "method": "annotation",
                    "note_preview": note_content[:100] + "..." if len(note_content) > 100 else note_content
                })
            else:
                return json.dumps({
                    "success": False,
                    "error": "Failed to create agent note",
                    "apex_id": apex_id
                })

        except Exception as annotation_error:
            logger.error(f"Error creating annotation: {annotation_error}")
            return json.dumps({
                "success": False,
                "error": "Failed to add agent note to member profile",
                "apex_id": apex_id,
                "details": str(annotation_error)
            })

    except Exception as e:
        logger.error(f"❌ Error adding agent note for {apex_id}: {e}")
        return json.dumps({
            "success": False,
            "error": str(e),
            "apex_id": apex_id,
            "message": "Error adding agent note to member profile"
        })


def check_teams_availability_sync(agent_emails: Optional[List[str]] = None) -> str:
    """
    Check Teams availability for agents - wrapper function for Teams integration

    Args:
        agent_emails: Optional list of agent emails to check

    Returns:
        JSON string with availability status
    """
    try:
        if not TEAMS_INTEGRATION_AVAILABLE:
            logger.warning("⚠️ Teams integration not available")
            return json.dumps({
                "success": False,
                "available": False,
                "error": "Teams integration not available",
                "agent_email": None,
                "agent_name": None
            })

        # Import and call the Teams integration function
        from teams_integration import check_teams_availability_sync as teams_check
        result = teams_check(agent_emails or [])
        logger.info(f"✅ Teams availability check completed")
        return result

    except Exception as e:
        logger.error(f"❌ Error checking Teams availability: {e}")
        return json.dumps({
            "success": False,
            "available": False,
            "error": str(e),
            "agent_email": None,
            "agent_name": None
        })
