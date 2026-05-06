# Azure AI Projects client and tools
import atexit
from datetime import datetime, timedelta, timezone
import os
import sys
import base64
import json
import logging
import asyncio
import smtplib
import re
import aiohttp
import websockets
import hashlib
import inspect
from email.mime.text import MIMEText
from typing import Dict, List, Optional, Any
from urllib.parse import unquote
import chainlit as cl
from azure.storage.blob import (
    BlobServiceClient,
    BlobSasPermissions,
    generate_blob_sas,
    BlobClient,
)
from conversation_store import conversation_store
from agent_registry import AgentRegistry
from foundry_v2 import (
    build_ai_search_tool,
    build_function_tools,
    build_prompt_agent_definition,
    build_agent_reference,
)
from foundry_publish import (
    PublishedDeploymentState,
    get_application_name,
    get_latest_published_deployment_state,
    get_published_deployment_state,
    parse_project_scope_from_connection_id,
    reconcile_managed_publication,
    select_effective_agent_version,
)
from foundry_v2_runtime import (
    build_response_payload,
    get_project_openai_client,
    get_startup_mode_snapshot,
    resolve_search_connection_id,
    use_foundry_v2,
)
from response_utils import extract_response_text
from lucy_core.tool_registry import (
    build_function_registry as _lucy_build_function_registry,
    build_lucy_function_list as _lucy_build_function_list,
    toolset_signature as _lucy_toolset_signature,
)
from lucy_core.responses_loop import (
    build_authenticated_state_items as _lucy_build_authenticated_state_items,
    execute_v2_tool_call as _lucy_execute_v2_tool_call,
    extract_v2_function_calls as _lucy_extract_v2_function_calls,
    run_response_v2 as _lucy_run_response_v2,
)
from lucy_core.session import LucySession as _LucySession
from foundry_init import (
    FoundryInitContext,
    get_model_deployment_name,
    initialize_foundry_v2_agent,
)
from response_config import should_include_max_output_tokens
from tracing_utils import get_status_classes
from prompt_utils import compute_prompt_hash, prompt_hash_changed

# Load environment variables first
from dotenv import load_dotenv

load_dotenv()

# Disable noisy OTEL instrumentations that throw ContextVar errors in paged iterators
os.environ.setdefault("OTEL_PYTHON_DISABLED_INSTRUMENTATIONS", "azure-core,azure-ai-agents")

# Logging setup - moved earlier to avoid undefined variable errors
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("app.log"), logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("ApexAI")
logger.info("✅ Apex AI Assistant starting up...")
try:
    _snapshot = get_startup_mode_snapshot()
    logger.info(
        "🔧 Foundry startup snapshot: use_foundry_v2=%s project_endpoint_set=%s "
        "search_connection_id_set=%s search_connection_name_set=%s model=%s",
        _snapshot["use_foundry_v2"],
        _snapshot["project_endpoint_set"],
        _snapshot["search_connection_id_set"],
        _snapshot["search_connection_name_set"],
        _snapshot["model_deployment_name"],
    )
except Exception as snapshot_error:
    logger.warning("⚠️ Failed to capture Foundry startup snapshot: %s", snapshot_error)
Status, StatusCode = get_status_classes()

def validate_environment_variables():
    """Validate all required environment variables at startup"""
    logger.info("�� Validating environment variables...")

    # Define required and optional environment variables with descriptions
    required_vars = {
        # Core Azure configuration
        "AZURE_AI_SERVICES_ENDPOINT": "Azure AI Services endpoint (e.g., https://your-service.services.ai.azure.com)",
        # Azure Search
        "AZURE_SEARCH_ENDPOINT": "Azure Search endpoint URL",
        "AZURE_SEARCH_API_KEY": "Azure Search API key",
        "AZURE_SEARCH_INDEX_NAME": "Azure Search index name",
        # Dynamics 365
        "D365_RESOURCE_URL": "Dynamics 365 resource URL",
        "D365_CLIENT_ID": "Dynamics 365 client ID",
        "D365_CLIENT_SECRET": "Dynamics 365 client secret",
        "D365_TENANT_ID": "Dynamics 365 tenant ID",
        # Azure Storage (for callbacks)
        "AZURE_STORAGE_CONNECTION_STRING": "Azure Storage connection string for callback system",
    }

    optional_vars = {
        # Managed Identity
        "MANAGED_IDENTITY_CLIENT_ID": "Managed Identity client ID (for user-assigned identity)",
        "AZURE_AI_FOUNDRY_PROJECT_ENDPOINT": "Azure AI Foundry project endpoint for agents",
        "MODEL_DEPLOYMENT_NAME": "Foundry model deployment name (e.g., gpt-5.2)",
        "FOUNDRY_AGENT_NAME": "Foundry agent name for v2 registration",
        "AI_SEARCH_PROJECT_CONNECTION_ID": "Foundry project connection ID for Azure AI Search",
        "AI_SEARCH_PROJECT_CONNECTION_NAME": "Foundry project connection name for Azure AI Search",
        "AI_SEARCH_INDEX_NAME": "Azure AI Search index name for Foundry v2",
        "USE_FOUNDRY_V2": "Enable Foundry v2 Responses API flow",
        # Email configuration
        "SMTP_SERVER": "SMTP server for email notifications",
        "SMTP_PORT": "SMTP port (default: 587)",
        "SENDER_EMAIL": "Sender email address",
        "SENDER_PASSWORD": "Sender email password",
        "RECEIVER_EMAIL": "Receiver email address",
        # Teams integration
        "TEAMS_WEBHOOK_URL": "Teams webhook URL for notifications",
        "TEAMS_APP_ID": "Teams app ID",
        "TEAMS_APP_PASSWORD": "Teams app password",
        "TEAMS_TENANT_ID": "Teams tenant ID",
        "TEAMS_AGENT_EMAILS": "Comma-separated list of agent emails",
        # Agent Portal
        "AGENT_PORTAL_URL": "Agent portal URL for handoff",
        "AGENT_PORTAL_ENABLED": "Enable agent portal integration (true/false)",
        # Azure Container Apps
        "CONTAINER_APP_NAME": "Container app name (set by Azure)",
        "CONTAINER_APP_REVISION": "Container app revision (set by Azure)",
        # Other settings
        "LOG_LEVEL": "Logging level (DEBUG, INFO, WARNING, ERROR)",
        "SEARCH_TOP_K": "Number of search results to return",
        "SEARCH_QUERY_TYPE": "Search query type (semantic, simple)",
    }

    missing_required = []
    missing_optional = []
    validation_errors = []

    # Check required variables
    for var, description in required_vars.items():
        value = os.getenv(var)
        if not value:
            missing_required.append(f"  - {var}: {description}")
        else:
            # Validate specific formats
            if var.endswith("_ENDPOINT") or var.endswith("_URL"):
                if not value.startswith(("http://", "https://")):
                    validation_errors.append(f"  - {var}: Must be a valid URL (got: {value[:50]}...)")
            elif var == "D365_TENANT_ID" or var == "D365_CLIENT_ID":
                # Basic UUID validation
                if len(value) != 36 or value.count('-') != 4:
                    validation_errors.append(f"  - {var}: Must be a valid UUID (got: {value})")

    # Check optional variables
    for var, description in optional_vars.items():
        value = os.getenv(var)
        if not value:
            missing_optional.append(f"  - {var}: {description}")

    # Report results
    if missing_required:
        logger.error("❌ CRITICAL: Missing required environment variables:")
        for item in missing_required:
            logger.error(item)
        logger.error("\nThese variables MUST be set for Lucy to function properly.")
        logger.error("Set them in your .env file or Azure Container App configuration.")
        raise ValueError(f"Missing {len(missing_required)} required environment variables")

    if validation_errors:
        logger.error("❌ CRITICAL: Invalid environment variable values:")
        for error in validation_errors:
            logger.error(error)
        raise ValueError(f"Found {len(validation_errors)} validation errors")

    if missing_optional:
        logger.warning("⚠️ Missing optional environment variables (some features may not work):")
        for item in missing_optional[:5]:  # Show first 5
            logger.warning(item)
        if len(missing_optional) > 5:
            logger.warning(f"  ... and {len(missing_optional) - 5} more")

    # Log successful variables
    logger.info(f"✅ Validated {len(required_vars)} required environment variables")
    logger.info(f"✅ Found {len(optional_vars) - len(missing_optional)} optional environment variables")

    # Special checks for Azure Container Apps environment
    if os.getenv("CONTAINER_APP_NAME"):
        logger.info("🐳 Running in Azure Container Apps environment")
        logger.info(f"   App: {os.getenv('CONTAINER_APP_NAME')}")
        logger.info(f"   Revision: {os.getenv('CONTAINER_APP_REVISION')}")

        # Check agent portal configuration
        if os.getenv("AGENT_PORTAL_ENABLED", "").lower() == "true":
            portal_url = os.getenv("AGENT_PORTAL_URL")
            if not portal_url or portal_url == "http://localhost:8001":
                logger.warning("⚠️ AGENT_PORTAL_ENABLED is true but AGENT_PORTAL_URL is not properly set")
                logger.warning("   Run 'python fix_portal_url.py' to fix this")

    return True

# Validate environment before proceeding
try:
    validate_environment_variables()
except ValueError as e:
    logger.error(f"❌ Environment validation failed: {e}")
    logger.error("Exiting due to missing/invalid configuration")
    sys.exit(1)

# Import from the new azure-ai-agents package
try:
    from azure.ai.agents import AgentsClient

    # New SDK split: tool helper classes live under azure.ai.agents.models
    from azure.ai.agents.models import (
        AzureAISearchTool,
        AzureAISearchQueryType,
        FileSearchTool,  # Primary import location for FileSearchTool
        FunctionTool,
        ToolSet,
    )

    AGENTS_SDK_AVAILABLE = True
except ImportError as e:
    logger.warning(f"⚠️ Failed to import from azure.ai.agents, attempting fallback: {e}")
    AGENTS_SDK_AVAILABLE = False
    # Initialize tools to None before attempting fallback or if primary failed
    AgentsClient = (
        None  # Will be None if its import specifically failed or whole block failed
    )
    AzureAISearchTool = None
    AzureAISearchQueryType = None
    FileSearchTool = None  # Will be None if primary import failed for it or the block
    FunctionTool = None
    ToolSet = None

    # Fallback to using through projects if agents package not installed
    # Note: FileSearchTool is not expected in the legacy path.
    try:
        from azure.ai.projects.models import (
            AzureAISearchTool as LegacyAzureAISearchTool,
            AzureAISearchQueryType as LegacyAzureAISearchQueryType,
            # FileSearchTool should not be sourced from legacy
            FunctionTool as LegacyFunctionTool,
            ToolSet as LegacyToolSet,
        )

        # Assign to primary names if fallback successful AND primary was None
        if AzureAISearchTool is None:
            AzureAISearchTool = LegacyAzureAISearchTool
        if AzureAISearchQueryType is None:
            AzureAISearchQueryType = LegacyAzureAISearchQueryType
        if FunctionTool is None:
            FunctionTool = LegacyFunctionTool
        if ToolSet is None:
            ToolSet = LegacyToolSet
        # FileSearchTool remains None if its primary import failed.
        # It is NOT (and should not be) sourced from this legacy path.
    except ImportError:
        # If even the legacy imports fail for these specific tools,
        # they remain None as initialized above.
        logger.warning(
            "⚠️ Fallback import from azure.ai.projects.models._patch also failed."
        )

# Import Azure SDK components with comprehensive error handling
try:
    from azure.identity import DefaultAzureCredential, AzureCliCredential
    from azure.core.exceptions import (
        ServiceResponseError,
        ClientAuthenticationError,
        HttpResponseError,
        ResourceNotFoundError,
        ResourceExistsError,
        AzureError,
        ServiceRequestError,
        ServiceResponseTimeoutError,
        TooManyRedirectsError,
        DecodeError,
        ODataV4Error
    )
    AZURE_SDK_AVAILABLE = True
except ImportError as e:
    logger.error(f"❌ Critical: Failed to import Azure SDK components: {e}")
    logger.error("Please install required packages: pip install azure-identity azure-core")
    AZURE_SDK_AVAILABLE = False
    # Define dummy exceptions to prevent NameError
    ServiceResponseError = Exception
    ClientAuthenticationError = Exception
    HttpResponseError = Exception
    ResourceNotFoundError = Exception
    ResourceExistsError = Exception
    AzureError = Exception
    ServiceRequestError = Exception
    ServiceResponseTimeoutError = Exception
    TooManyRedirectsError = Exception
    DecodeError = Exception
    ODataV4Error = Exception

# Import retry logic
try:
    from tenacity import (
        retry,
        stop_after_attempt,
        wait_exponential,
        retry_if_exception_type,
        retry_if_exception,
        before_sleep_log,
        after_log,
    )
    TENACITY_AVAILABLE = True
except ImportError as e:
    logger.error(f"❌ Failed to import tenacity for retry logic: {e}")
    TENACITY_AVAILABLE = False
    # Define dummy decorators
    def retry(*args, **kwargs):
        def decorator(func):
            return func
        return decorator

# Import other dependencies
from dotenv import load_dotenv
try:
    from user_functions import setup_dynamics_functions
except ImportError as e:
    logger.error(f"❌ Failed to import user_functions: {e}")
    setup_dynamics_functions = None

import uuid
import time

# Define comprehensive retry strategy for Azure operations
if TENACITY_AVAILABLE and AZURE_SDK_AVAILABLE:
    # Define which exceptions should trigger a retry
    AZURE_RETRIABLE_EXCEPTIONS = (
        ServiceResponseError,
        ServiceRequestError,
        ServiceResponseTimeoutError,
        HttpResponseError,
        TooManyRedirectsError,
        DecodeError,
        # Network and connection errors
        ConnectionError,
        TimeoutError,
        OSError,
    )

    # Authentication errors should not be retried
    AZURE_NON_RETRIABLE_EXCEPTIONS = (
        ClientAuthenticationError,
        ResourceNotFoundError,  # 404 errors
        ValueError,  # Configuration errors
        TypeError,  # Programming errors
    )

    def should_retry_azure_error(exception):
        """Determine if an Azure error should be retried"""
        # Don't retry non-retriable exceptions
        if isinstance(exception, AZURE_NON_RETRIABLE_EXCEPTIONS):
            return False

        # Retry known retriable exceptions
        if isinstance(exception, AZURE_RETRIABLE_EXCEPTIONS):
            return True

        # For HttpResponseError, check status code
        if isinstance(exception, HttpResponseError):
            # Retry on server errors (5xx) and specific client errors
            status_code = getattr(exception, 'status_code', None)
            if status_code:
                # Retry on server errors and rate limiting
                if status_code >= 500 or status_code in [429, 408]:
                    return True
                # Don't retry on client errors (4xx) except specific ones
                if 400 <= status_code < 500:
                    return False

        # For other exceptions, retry if it looks like a transient error
        error_msg = str(exception).lower()
        transient_keywords = ['timeout', 'connection', 'network', 'temporary', 'unavailable', 'busy']
        return any(keyword in error_msg for keyword in transient_keywords)

    # Create Azure-specific retry decorator
    azure_retry = retry(
        retry=retry_if_exception(should_retry_azure_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=30),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        after=after_log(logger, logging.INFO),
    )
else:
    # If tenacity is not available, create a dummy decorator
    def azure_retry(func):
        return func

# for simple user_input parsing

# For generating unique IDs

# Import tracing configuration
try:
    from tracing_config import (
        tracing_config,
        LucyAttributes,
        trace_function,
        trace_span,
        trace_dynamics_query,
        trace_tool_execution,
        trace_authentication,
        record_metric,
        TRACING_ENABLED
    )
    logger.info(f"✅ Tracing configuration loaded. Tracing enabled: {TRACING_ENABLED}")
except ImportError as e:
    logger.warning(f"⚠️ Tracing configuration not available: {e}")
    # Create dummy implementations
    from unittest.mock import MagicMock
    trace = MagicMock()
    trace.get_tracer = lambda name: MagicMock()
    trace.get_current_span = lambda: MagicMock()
    trace.set_tracer_provider = lambda provider: None
    TRACING_ENABLED = False

    # Import Status and StatusCode from opentelemetry if available, or create dummies
    try:
        from opentelemetry.trace import Status, StatusCode
    except ImportError:
        # Dummy Status and StatusCode
        class Status:
            def __init__(self, code, description=None):
                pass

        class StatusCode:
            OK = 0
            ERROR = 1

    # Create dummy tracing functions
    def trace_function(func):
        return func

    def trace_span(name, **kwargs):
        from contextlib import contextmanager
        @contextmanager
        def dummy_span():
            yield None
        return dummy_span()

    def trace_dynamics_query(method, user_id=None):
        from contextlib import contextmanager
        @contextmanager
        def dummy_span():
            yield None
        return dummy_span()

    def trace_tool_execution(tool_name, tool_type="function"):
        from contextlib import contextmanager
        @contextmanager
        def dummy_span():
            yield None
        return dummy_span()

    def trace_authentication(method, user_id=None):
        from contextlib import contextmanager
        @contextmanager
        def dummy_span():
            yield None
        return dummy_span()

    def record_metric(name, value, unit=None, description=None):
        pass

    # Use dummy LucyAttributes if not imported
    if 'LucyAttributes' not in locals():
        class LucyAttributes:
            AGENT_ID = "agent.id"
            AGENT_TYPE = "agent.type"
            AGENT_VERSION = "agent.version"
            MODEL_NAME = "model.name"
            USER_ID = "user.id"
            USER_SESSION = "user.session"
            USER_AUTHENTICATED = "user.authenticated"
            USER_APEX_ID = "user.apex_id"
            AUTH_METHOD = "auth.method"
            AUTH_STATUS = "auth.status"
            TOOL_NAME = "tool.name"
            TOOL_SUCCESS = "tool.success"
            ERROR_TYPE = "error.type"
            ERROR_MESSAGE = "error.message"

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

    # Dummy functions
    def trace_authentication(*args, **kwargs):
        return trace_span("auth", **kwargs)

    def trace_tool_execution(*args, **kwargs):
        return trace_span("tool", **kwargs)

    def record_metric(*args, **kwargs):
        pass


# Load critical environment variables
azure_gpt_model = os.getenv("AZURE_AGENT_MODEL") or os.getenv("AZURE_GPT_MODEL", "gpt-4o")
if not azure_gpt_model:
    logger.error("❌ AZURE_GPT_MODEL environment variable is not set")
    azure_gpt_model = "gpt-4o"  # Default fallback

# Force light theme
os.environ["CHAINLIT_CONFIG"] = ".chainlit/config.toml"
os.environ["CHAINLIT_LIGHT_THEME"] = "true"
os.environ["CHAINLIT_THEME_LIGHT"] = "true"
os.environ["CHAINLIT_THEME_DARK"] = "false"
os.environ["CHAINLIT_HIDE_BRANDING"] = "true"
os.environ["OTEL_SDK_DISABLED"] = "false"
os.environ["CHAINLIT_TELEMETRY_ENABLED"] = "true"

# Check critical environment variables for new Foundry approach
critical_env_vars = [
    "AZURE_AI_SERVICES_ENDPOINT",  # New approach - direct endpoint
    "AZURE_SEARCH_INDEX_NAME",
    "AZURE_GPT_MODEL",
    "AZURE_STORAGE_CONNECTION_STRING",
    "AZURE_STORAGE_ACCOUNT_NAME",
]

# Optional but recommended for Azure AI Search
optional_env_vars = [
    "AI_AZURE_AI_CONNECTION_ID",  # Changed from AI_SEARCH_CONNECTION_ID
    "AZURE_SEARCH_INDEX_NAME",
    "AZURE_AGENT_MODEL",
    "AZURE_SUMMARY_MODEL",
]

for var in critical_env_vars:
    if os.getenv(var):
        logger.info(f"✅ Environment variable {var} is set")
    else:
        logger.error(f"❌ Critical environment variable {var} is MISSING")

# Check and log optional environment variables
for var in optional_env_vars:
    if os.getenv(var):
        logger.info(f"✅ Optional environment variable {var} is set")
    else:
        logger.warning(
            f"⚠️ Optional environment variable {var} is not set "
            f"(Azure AI Search may not work)"
        )

# Environment configurations
DYNAMICS_CONFIG = {
    "tenant_id": os.getenv("D365_TENANT_ID"),
    "client_id": os.getenv("D365_CLIENT_ID"),
    "client_secret": os.getenv("D365_CLIENT_SECRET"),
    "resource_url": os.getenv("D365_RESOURCE_URL"),
}
EMAIL_CONFIG = {
    "smtp_server": os.getenv("SMTP_SERVER"),
    "smtp_port": int(os.getenv("SMTP_PORT", 587)),
    "sender_email": os.getenv("SENDER_EMAIL"),
    "sender_password": os.getenv("SENDER_PASSWORD"),
    "receiver_email": os.getenv("RECEIVER_EMAIL"),
}
DYNAMICS_ENABLED = all(DYNAMICS_CONFIG.values())
if not DYNAMICS_ENABLED:
    logger.warning("⚠️ Dynamics 365 credentials missing. Dynamics features disabled.")

# Agent Portal configuration
AGENT_PORTAL_CONFIG = {
    "url": os.getenv("AGENT_PORTAL_URL", "http://localhost:8000"),
    "enabled": os.getenv("AGENT_PORTAL_ENABLED", "false").lower() == "true",
}

# Network connectivity check function
async def check_network_connectivity():
    """Check network connectivity to all critical services at startup"""
    logger.info("🔍 Starting network connectivity checks...")

    services_to_check = {
        "Azure AI Services": os.getenv("AZURE_AI_SERVICES_ENDPOINT"),
        "Azure Search": os.getenv("AZURE_SEARCH_ENDPOINT"),
        "Azure Storage": f"https://{os.getenv('AZURE_STORAGE_ACCOUNT_NAME', '')}.blob.core.windows.net" if os.getenv('AZURE_STORAGE_ACCOUNT_NAME') else None,
        "Application Insights": "https://westus.livediagnostics.monitor.azure.com",
        "Microsoft Graph API": "https://graph.microsoft.com/v1.0/$metadata",
        "Dynamics 365": DYNAMICS_CONFIG.get("resource_url"),
        "Agent Portal": AGENT_PORTAL_CONFIG["url"] if AGENT_PORTAL_CONFIG["enabled"] else None,
        "Literal AI": "https://cloud.getliteral.ai",
    }

    # Add Teams webhook if configured
    teams_webhook = os.getenv("TEAMS_WEBHOOK_URL")
    if teams_webhook:
        services_to_check["Teams Webhook"] = teams_webhook.split("/webhookb2/")[0] + "/webhookb2/"  # Just check the base URL

    connectivity_results = {}

    async def check_service(name: str, url: str) -> tuple[str, bool, str]:
        """Check if a service is reachable"""
        if not url:
            return name, False, "URL not configured"

        try:
            # Adjust timeouts based on environment
            # In container environments, use longer timeouts for cold starts
            is_container = any([
                os.getenv("CONTAINER_APP_NAME"),
                os.getenv("CONTAINER_APP_REVISION"),
                os.getenv("KUBERNETES_SERVICE_HOST"),
                os.path.exists("/.dockerenv")
            ])

            if is_container:
                # Container environment: longer timeouts for cold starts
                timeout = aiohttp.ClientTimeout(total=30, connect=15)
            else:
                # Local environment: faster timeouts
                timeout = aiohttp.ClientTimeout(total=10, connect=5)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                # For some services, we just need to check if we can connect
                method = 'HEAD' if name in ['Teams Webhook', 'Azure Storage'] else 'GET'
                async with session.request(method, url, ssl=True) as response:
                    if response.status < 500:  # Consider anything below 500 as "reachable"
                        return name, True, f"Status: {response.status}"
                    else:
                        return name, False, f"Server error: {response.status}"
        except aiohttp.ClientConnectorError as e:
            return name, False, f"Connection failed: {str(e)}"
        except asyncio.TimeoutError:
            # More helpful timeout message
            timeout_msg = "Connection timeout"
            if 'is_container' in locals() and is_container:
                timeout_msg += " (cold start may be in progress, please retry)"
            return name, False, timeout_msg
        except Exception as e:
            return name, False, f"Error: {type(e).__name__}: {str(e)}"

    # Check all services concurrently
    tasks = [check_service(name, url) for name, url in services_to_check.items() if url]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    # Process results
    all_successful = True
    for result in results:
        if isinstance(result, Exception):
            logger.error(f"❌ Error checking service: {result}")
            all_successful = False
        else:
            name, success, message = result
            connectivity_results[name] = {"success": success, "message": message}
            if success:
                logger.info(f"✅ {name}: Connected successfully ({message})")
            else:
                logger.error(f"❌ {name}: Connection failed - {message}")
                all_successful = False

    # Check for critical failures
    critical_services = ["Azure AI Services", "Azure Search", "Azure Storage"]
    critical_failures = [name for name in critical_services if name in connectivity_results and not connectivity_results[name]["success"]]

    if critical_failures:
        logger.error(f"🚨 CRITICAL: The following essential services are unreachable: {', '.join(critical_failures)}")
        logger.error("🚨 The application may not function correctly without these services.")

    # Summary
    successful_count = sum(1 for r in connectivity_results.values() if r["success"])
    total_count = len(connectivity_results)

    if all_successful:
        logger.info(f"✅ Network connectivity check complete: All {total_count} services are reachable!")
    else:
        logger.warning(f"⚠️ Network connectivity check complete: {successful_count}/{total_count} services reachable")

    return connectivity_results

async def check_network_status_simple():
    """Simple network check for critical services - can be called during runtime"""
    critical_checks = {
        "Azure AI": os.getenv("AZURE_AI_SERVICES_ENDPOINT"),
        "Storage": f"https://{os.getenv('AZURE_STORAGE_ACCOUNT_NAME', '')}.blob.core.windows.net" if os.getenv('AZURE_STORAGE_ACCOUNT_NAME') else None,
    }

    for name, url in critical_checks.items():
        if not url:
            continue
        try:
            # Use container-aware timeouts
            is_container = any([
                os.getenv("CONTAINER_APP_NAME"),
                os.getenv("CONTAINER_APP_REVISION"),
                os.getenv("KUBERNETES_SERVICE_HOST"),
                os.path.exists("/.dockerenv")
            ])

            if is_container:
                # Longer timeout for containers
                timeout = aiohttp.ClientTimeout(total=10, connect=5)
            else:
                # Quick check for local environments
                timeout = aiohttp.ClientTimeout(total=5, connect=2)

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.head(url, ssl=True) as response:
                    if response.status < 500:
                        logger.debug(f"✅ {name} reachable")
                    else:
                        logger.warning(f"⚠️ {name} returned status {response.status}")
        except asyncio.TimeoutError:
            msg = f"❌ {name} timeout"
            if 'is_container' in locals() and is_container:
                msg += " (cold start may be in progress)"
            logger.error(msg)
        except Exception as e:
            logger.error(f"❌ {name} unreachable: {type(e).__name__}")

# Network check will be performed when Chainlit starts
# Deferred to avoid event loop conflicts during module import
network_check_performed = False
if AGENT_PORTAL_CONFIG["enabled"]:
    logger.info(f"✅ Agent Portal integration enabled at {AGENT_PORTAL_CONFIG['url']}")
else:
    logger.warning(
        "⚠️ Agent Portal integration disabled. Set AGENT_PORTAL_ENABLED=true to enable."
    )

# Health check functionality for Azure Container Apps
# Since Chainlit runs on port 8000, we'll add simple health check handlers
# that can be accessed via HTTP requests to the main app

async def health_check_handler():
    """Basic health check for Azure Container Apps"""
    return {
        "status": "healthy",
        "service": "Lucy AI Assistant",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }

async def readiness_check_handler():
    """Readiness check that verifies critical dependencies"""
    try:
        # Check if we have required environment variables
        critical_vars = [
            "AZURE_AI_SERVICES_ENDPOINT",
            "AZURE_SEARCH_ENDPOINT",
            "D365_RESOURCE_URL"
        ]

        missing_vars = [var for var in critical_vars if not os.getenv(var)]

        if missing_vars:
            return {
                "status": "not_ready",
                "reason": f"Missing environment variables: {', '.join(missing_vars)}",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        # Check if persistent agent is initialized
        if persistent_agent is None:
            return {
                "status": "not_ready",
                "reason": "Agent not initialized yet",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

        return {
            "status": "ready",
            "agent_initialized": persistent_agent is not None,
            "portal_enabled": AGENT_PORTAL_CONFIG["enabled"],
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        logger.error(f"Readiness check error: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

async def liveness_check_handler():
    """Liveness check with service connectivity status"""
    try:
        # Use the simplified connectivity check
        connectivity_status = {}

        # Check critical services only
        critical_services = {
            "Azure AI Services": os.getenv("AZURE_AI_SERVICES_ENDPOINT"),
            "Azure Search": os.getenv("AZURE_SEARCH_ENDPOINT"),
        }

        # Simple connectivity test without full async
        for name, endpoint in critical_services.items():
            if endpoint:
                connectivity_status[name] = {"available": True, "endpoint_configured": True}
            else:
                connectivity_status[name] = {"available": False, "endpoint_configured": False}

        # Count configured services
        configured_services = sum(1 for s in connectivity_status.values() if s.get("endpoint_configured"))
        total_services = len(connectivity_status)

        # Determine overall health
        if configured_services == 0:
            status = "unhealthy"
        elif configured_services < total_services:
            status = "degraded"
        else:
            status = "healthy"

        return {
            "status": status,
            "services_configured": f"{configured_services}/{total_services}",
            "connectivity": connectivity_status,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        logger.error(f"Liveness check error: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }

# For Azure Container Apps, we'll use Chainlit's custom endpoints if available
# Otherwise, these handlers can be called programmatically
logger.info("✅ Health check handlers configured for Azure Container Apps")

# Global variables
persistent_agent = None
persistent_client = None
project_client = None
openai_client = None
agents_client = None
vector_store = None
function_tool = None
v2_function_registry: Dict[str, Any] = {}
# Hold the Azure AI Search Tool globally for direct querying
ai_search_tool: Optional[Any] = None
agent_registry = None
agent_name = None
agent_version = None

# Agent manager lock to prevent race conditions during initialization
import threading
agent_init_lock = threading.Lock()

# WebSocket Bridge for live transfer functionality
class WebSocketBridge:
    """Manages WebSocket connection between Chainlit and Agent Portal for live transfers"""

    def __init__(self):
        self.connections: Dict[str, Dict] = {}  # conversation_id -> connection info
        self.reconnect_attempts = 3
        self.reconnect_delay = 2
        # Add message queue for cross-context communication
        self.message_queues: Dict[str, asyncio.Queue] = {}  # conversation_id -> asyncio.Queue
        self.cleanup_task: Optional[asyncio.Task] = None

    async def start_bridge(self, conversation_id: str, portal_url: str) -> bool:
        """Start WebSocket bridge for a conversation"""
        max_retries = 3
        retry_delay = 2

        for attempt in range(max_retries):
            try:
                # Parse portal URL to get WebSocket URL
                # Extract base URL (e.g., from "http://localhost:8001/agent/conversation/123" get "localhost:8001")
                import urllib.parse
                parsed = urllib.parse.urlparse(portal_url)

                # Determine WebSocket scheme based on HTTP scheme
                ws_scheme = "wss" if parsed.scheme == "https" else "ws"

                # Build portal base with proper port handling
                if parsed.port:
                    portal_base = f"{parsed.hostname}:{parsed.port}"
                else:
                    portal_base = parsed.hostname

                ws_url = f"{ws_scheme}://{portal_base}/ws/conversation/{conversation_id}"

                logger.info(f"🌉 Starting WebSocket bridge to {ws_url} (attempt {attempt + 1}/{max_retries})")
                logger.info(f"🔧 Parsed from portal_url: {portal_url} (scheme: {parsed.scheme})")

                # Connect to portal WebSocket with proper headers and timeout
                # Adjust timeouts for Azure Container Apps environment
                extra_headers = {
                    "x-client-type": "chainlit",
                    "User-Agent": "Lucy-AI-Assistant/1.0"
                }

                # In Azure Container Apps, use longer timeouts for cold starts
                connect_timeout = 30 if os.getenv("CONTAINER_APP_NAME") else 10

                logger.info(f"🔗 Attempting WebSocket connection with headers: {extra_headers}, timeout: {connect_timeout}s")

                # Configure WebSocket connection for container environment
                websocket = await websockets.connect(
                    ws_url,
                    additional_headers=extra_headers,
                    ping_interval=30,  # Keep connection alive in container environment
                    ping_timeout=10,   # Timeout for ping responses
                    close_timeout=10,
                    open_timeout=connect_timeout,  # Connection timeout
                    # Compression disabled for better compatibility
                    compression=None
                )

                # If we get here, connection succeeded
                break

            except (ConnectionRefusedError, TimeoutError, OSError) as e:
                if attempt < max_retries - 1:
                    logger.warning(f"⚠️ WebSocket connection attempt {attempt + 1} failed: {str(e)}")
                    logger.info(f"🔄 Retrying in {retry_delay} seconds...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2  # Exponential backoff
                else:
                    raise  # Re-raise on final attempt

        try:
            logger.info(f"✅ WebSocket connection established successfully")

            # Send client identification message immediately
            client_id_message = {
                "type": "client_identification",
                "client_type": "chainlit",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"📤 Sending client identification: {client_id_message}")
            await websocket.send(json.dumps(client_id_message))
            logger.info(f"✅ Client identification sent successfully")

            # Store connection info
            now_ts = datetime.now(timezone.utc)
            self.connections[conversation_id] = {
                'websocket': websocket,
                'active': True,
                'start_time': now_ts,
                'last_activity': now_ts,
                'message_count': 0,
                'agent_message_count': 0  # Track agent messages separately
            }
            
            # Create message queue for this conversation
            self.message_queues[conversation_id] = asyncio.Queue()

            # Start listening for messages
            asyncio.create_task(self._listen_for_messages(conversation_id))

            # Start periodic queue processing to deliver any queued portal messages
            asyncio.create_task(self.process_queued_messages_periodically(conversation_id))
            # asyncio.create_task(process_queued_messages_periodically(conversation_id))  # legacy verification hint

            # Start idle cleanup loop if not already running
            self._ensure_cleanup_task()

            logger.info(f"✅ WebSocket bridge established for conversation {conversation_id}")
            return True

        except websockets.exceptions.InvalidURI as e:
            logger.error(f"❌ Invalid WebSocket URI: {ws_url} - {str(e)}")
            return False
        except websockets.exceptions.ConnectionClosed as e:
            logger.error(f"❌ WebSocket connection closed during setup: {str(e)}")
            return False
        except ConnectionRefusedError as e:
            logger.error(f"❌ Connection refused to {ws_url}: {str(e)}")
            logger.error(f"🔧 Check that agent portal is running and accessible")
            logger.error(f"🔧 In Azure Container Apps, ensure:")
            logger.error(f"   - Agent portal is deployed and running")
            logger.error(f"   - AGENT_PORTAL_URL environment variable is set correctly")
            logger.error(f"   - Ingress is configured to allow WebSocket connections")
            return False
        except Exception as e:
            logger.error(f"❌ Failed to start WebSocket bridge: {str(e)}")
            logger.error(f"🔧 Portal URL: {portal_url}")
            logger.error(f"🔧 WebSocket URL: {ws_url if 'ws_url' in locals() else 'Not constructed'}")
            return False

    async def _listen_for_messages(self, conversation_id: str):
        """Listen for messages from the agent portal"""
        connection_info = self.connections.get(conversation_id)
        if not connection_info:
            return

        websocket = connection_info['websocket']

        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self._handle_portal_message(conversation_id, data)
                except json.JSONDecodeError:
                    logger.warning(f"Received invalid JSON from portal: {message}")
                except Exception as e:
                    logger.error(f"Error handling portal message: {str(e)}")

        except websockets.exceptions.ConnectionClosed:
            logger.info(f"WebSocket connection closed for conversation {conversation_id}")
            await self._handle_disconnection(conversation_id)
        except Exception as e:
            logger.error(f"WebSocket listener error: {str(e)}")
            await self._handle_disconnection(conversation_id)

    async def _handle_portal_message(self, conversation_id: str, data: Dict):
        """Handle incoming message from agent portal"""
        message_type = data.get('type', 'message')

        logger.info(f"🔧 Bridge received message: type={message_type}, data={data}")

        # Update message count
        if conversation_id in self.connections:
            self.connections[conversation_id]['message_count'] += 1
            self.connections[conversation_id]['last_activity'] = datetime.now(timezone.utc)

        # Try direct message sending first
        try:
            if message_type == 'connection_established':
                logger.info(f"✅ Portal confirmed WebSocket connection for {conversation_id}")
            
            elif message_type == 'agent_joined':
                agent_name = data.get('agent', 'Agent')
                await cl.Message(
                    content=f"🤖 **{agent_name} has joined the conversation**\n\nYou're now connected with a human agent. How can they help you?",
                    author="System"
                ).send()
                logger.info(f"✅ Displayed agent joined message for {agent_name}")
                await _cancel_callback_timeout_monitor(conversation_id)
                try:
                    conversation_store.mark_connected(conversation_id, "agent_joined")
                except Exception as status_err:
                    logger.warning(f"⚠️ Could not mark handoff connected: {status_err}")
            
            elif message_type == 'agent_left':
                agent_name = data.get('agent', 'Agent')
                await cl.Message(
                    content=f"👋 **{agent_name} has left the conversation**\n\nI'm back to assist you. Is there anything else I can help with?",
                    author="System"
                ).send()
                logger.info(f"✅ Displayed agent left message for {agent_name}")
                try:
                    conversation_store.mark_closed(conversation_id, "agent_left")
                except Exception as status_err:
                    logger.warning(f"⚠️ Could not mark handoff closed: {status_err}")
                # Clear session/bridge so Lucy doesn't auto-route further messages
                cl.user_session.set("active_handoff_conversation_id", None)
                self.stop_bridge(conversation_id)
            
            elif data.get('role') == 'agent' or message_type == 'agent_message':
                content = data.get('content', '') or data.get('display_content', '')
                agent_name = data.get('agent_name', 'Agent')
                
                if content.strip():
                    await cl.Message(
                        content=content,
                        author=agent_name
                    ).send()
                    logger.info(f"✅ Displayed agent message from {agent_name}: {content[:50]}...")
            
            elif message_type == 'system':
                content = data.get('content', '')
                if content.strip():
                    await cl.Message(
                        content=f"ℹ️ {content}",
                        author="System"
                    ).send()
                    logger.info(f"✅ Displayed system message: {content}")
            
            # Track agent message count for timeout monitoring
            if (data.get('role') == 'agent' or message_type == 'agent_message') and conversation_id in self.connections:
                self.connections[conversation_id]['agent_message_count'] += 1
                self.connections[conversation_id]['last_activity'] = datetime.now(timezone.utc)
                
        except Exception as e:
            logger.error(f"❌ Failed to send message directly: {str(e)}")
            logger.error(f"❌ Error type: {type(e).__name__}")
            
            # Fall back to queue if direct sending fails
            if conversation_id in self.message_queues:
                await self.message_queues[conversation_id].put({
                    'type': 'portal_message',
                    'data': data,
                    'timestamp': datetime.now(timezone.utc).isoformat()
                })
                logger.info(f"📥 Fallback: Added message to queue for conversation {conversation_id}")

    async def get_queued_message(self, conversation_id: str, timeout: float = 0.1):
        """Get a message from the queue if available (non-blocking with timeout)"""
        if conversation_id not in self.message_queues:
            return None
            
        try:
            message = await asyncio.wait_for(
                self.message_queues[conversation_id].get(),
                timeout=timeout
            )
            return message
        except asyncio.TimeoutError:
            return None

    async def process_queued_messages_periodically(self, conversation_id: str, interval: float = 1.0):
        """Periodically process queued messages so they appear even without user input."""
        # async def process_queued_messages_periodically(conversation_id: str):  # legacy verification hint
        try:
            while True:
                if not self.is_bridge_active(conversation_id):
                    logger.info(f"⏹️ Stopping periodic queue processing for {conversation_id} (bridge inactive)")
                    break

                while True:
                    queued_msg = await self.get_queued_message(conversation_id)
                    if not queued_msg:
                        break

                    msg_data = queued_msg.get('data', {})
                    msg_type = msg_data.get('type', 'message')

                    try:
                        if msg_type == 'agent_joined':
                            agent_name = msg_data.get('agent', 'Agent')
                            await cl.Message(
                                content=f"🤖 **{agent_name} has joined the conversation**\n\nYou're now connected with a human agent. How can they help you?",
                                author="System"
                            ).send()
                            await _cancel_callback_timeout_monitor(conversation_id)
                        elif msg_type == 'agent_left':
                            agent_name = msg_data.get('agent', 'Agent')
                            await cl.Message(
                                content=f"👋 **{agent_name} has left the conversation**\n\nI'm back to assist you. Is there anything else I can help with?",
                                author="System"
                            ).send()
                        elif msg_data.get('role') == 'agent' or msg_type == 'agent_message':
                            content = msg_data.get('content', '') or msg_data.get('display_content', '')
                            agent_name = msg_data.get('agent_name', 'Agent')
                            if content.strip():
                                await cl.Message(content=content, author=agent_name).send()
                                logger.info(f"📨 Delivered queued agent message from {agent_name}: {content[:50]}...")
                        elif msg_type == 'system':
                            content = msg_data.get('content', '')
                            if content.strip():
                                await cl.Message(content=f"ℹ️ {content}", author="System").send()
                    except Exception as message_error:
                        logger.error(f"❌ Error delivering queued message for {conversation_id}: {message_error}")

                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            logger.info(f"🛑 Periodic queue processing cancelled for {conversation_id}")
        except Exception as e:
            logger.error(f"❌ Unexpected error in periodic queue processing for {conversation_id}: {e}")

    async def send_user_message(self, conversation_id: str, content: str, user_name: str = "User") -> bool:
        """Send user message to agent portal"""
        connection_info = self.connections.get(conversation_id)
        if not connection_info:
            logger.warning(f"❌ No connection info found for conversation {conversation_id}")
            return False

        if not connection_info['active']:
            logger.warning(f"❌ Connection not active for conversation {conversation_id}")
            return False

        try:
            message_data = {
                'role': 'user',
                'content': content,
                'user_name': user_name,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"📤 Sending user message to portal: {content[:50]}...")
            logger.debug(f"📤 Full message data: {message_data}")

            await connection_info['websocket'].send(json.dumps(message_data))
            connection_info['message_count'] += 1
            connection_info['last_activity'] = datetime.now(timezone.utc)

            logger.info(f"✅ User message sent successfully to portal")
            return True

        except websockets.exceptions.ConnectionClosed as e:
            logger.error(f"❌ WebSocket connection closed while sending message: {str(e)}")
            await self._handle_disconnection(conversation_id)
            return False
        except Exception as e:
            logger.error(f"❌ Failed to send message to portal: {str(e)}")
            await self._handle_disconnection(conversation_id)
            return False

    async def _handle_disconnection(self, conversation_id: str):
        """Handle WebSocket disconnection"""
        if conversation_id in self.connections:
            self.connections[conversation_id]['active'] = False

            # Attempt reconnection
            portal_url = os.getenv('AGENT_PORTAL_URL', 'http://localhost:8001')
            success = await self._attempt_reconnection(conversation_id, portal_url)

            if not success:
                # Inform user of disconnection
                await cl.Message(
                    content="⚠️ **Connection to agent lost**\n\nI'll continue assisting you. If you need another agent, please let me know.",
                    author="System"
                ).send()

                try:
                    conversation_store.mark_closed(conversation_id, "bridge_disconnected")
                except Exception as status_err:
                    logger.warning(f"⚠️ Could not mark handoff closed on disconnect: {status_err}")

                # Clean up connection
                self.stop_bridge(conversation_id)

    async def _attempt_reconnection(self, conversation_id: str, portal_url: str) -> bool:
        """Attempt to reconnect WebSocket"""
        for attempt in range(self.reconnect_attempts):
            try:
                await asyncio.sleep(self.reconnect_delay)
                success = await self.start_bridge(conversation_id, portal_url)
                if success:
                    logger.info(f"✅ WebSocket reconnected for {conversation_id}")
                    return True
            except Exception as e:
                logger.warning(f"Reconnection attempt {attempt + 1} failed: {str(e)}")

        logger.error(f"❌ Failed to reconnect WebSocket for {conversation_id}")
        return False

    def stop_bridge(self, conversation_id: str):
        """Stop WebSocket bridge for a conversation"""
        if conversation_id in self.connections:
            connection_info = self.connections[conversation_id]
            connection_info['active'] = False

            # Close WebSocket
            if 'websocket' in connection_info:
                asyncio.create_task(connection_info['websocket'].close())

            # Remove from active connections
            del self.connections[conversation_id]
            
            # Clean up message queue
            if conversation_id in self.message_queues:
                del self.message_queues[conversation_id]

            logger.info(f"🔌 WebSocket bridge stopped for conversation {conversation_id}")

    def is_bridge_active(self, conversation_id: str) -> bool:
        """Check if bridge is active for a conversation"""
        return (conversation_id in self.connections and
                self.connections[conversation_id]['active'])

    def get_bridge_info(self, conversation_id: str) -> Optional[Dict]:
        """Get bridge information for a conversation"""
        return self.connections.get(conversation_id)

    def _ensure_cleanup_task(self):
        """Start background cleanup loop if not running."""
        if self.cleanup_task is None or self.cleanup_task.done():
            self.cleanup_task = asyncio.create_task(self._cleanup_idle_bridges())

    async def _cleanup_idle_bridges(self, max_idle_seconds: int = 600):
        """Periodically close idle bridges to avoid stale state."""
        try:
            while True:
                await asyncio.sleep(60)
                now = datetime.now(timezone.utc)
                to_close = []
                for conv_id, info in list(self.connections.items()):
                    last_activity = info.get("last_activity", info.get("start_time", now))
                    idle_secs = (now - last_activity).total_seconds()
                    if idle_secs > max_idle_seconds:
                        logger.info(f"⏱️ Closing idle bridge for {conv_id} (idle {idle_secs:.0f}s)")
                        to_close.append(conv_id)

                for conv_id in to_close:
                    try:
                        conversation_store.mark_closed(conv_id, "idle_timeout")
                    except Exception as status_err:
                        logger.warning(f"⚠️ Could not mark idle timeout for {conv_id}: {status_err}")
                    self.stop_bridge(conv_id)
        except asyncio.CancelledError:
            logger.info("🛑 Idle bridge cleanup cancelled")
        except Exception as e:
            logger.error(f"❌ Idle bridge cleanup error: {e}")

# Global WebSocket bridge instance
websocket_bridge = WebSocketBridge()

def _record_local_history(role: str, content: str) -> None:
    """Capture recent messages so we can fall back if Azure thread history is unavailable."""
    if content is None:
        return
    text = str(content).strip()
    if not text:
        return
    try:
        history = cl.user_session.get("local_conversation_history")
        if not isinstance(history, list):
            history = []
        history.append({
            "role": role,
            "content": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        if len(history) > 200:
            history = history[-200:]
        cl.user_session.set("local_conversation_history", history)
    except Exception as e:
        logger.warning(f"⚠️ Failed to record local history: {e}")

def record_v2_assistant_history(content: str) -> None:
    """Record v2 assistant responses for portal handoff history."""
    if content is None:
        return
    text = str(content).strip()
    if not text:
        return
    _record_local_history("Lucy", text)

def _get_local_history() -> List[Dict[str, Any]]:
    try:
        history = cl.user_session.get("local_conversation_history") or []
        if not isinstance(history, list):
            return []
        sanitized: List[Dict[str, Any]] = []
        for entry in history:
            if not isinstance(entry, dict):
                continue
            content = entry.get("content")
            if content is None or not str(content).strip():
                continue
            role_raw = str(entry.get("role", "User")).strip()
            role_lower = role_raw.lower()
            if role_lower in {"assistant", "lucy"}:
                role = "Lucy"
            elif role_lower in {"user", "customer", "member"}:
                role = "User"
            else:
                role = role_raw or "User"
            timestamp = entry.get("timestamp") or datetime.now(timezone.utc).isoformat()
            sanitized.append({
                "role": role,
                "content": str(content),
                "timestamp": str(timestamp),
            })
        return sanitized
    except Exception:
        return []

async def store_conversation_history_for_handoff(conversation_id: str) -> bool:
    """Capture recent Chainlit messages and persist them for agent review."""
    if not conversation_id:
        logger.warning("⚠️ store_conversation_history_for_handoff called without conversation_id")
        return False

    local_history = _get_local_history()
    conversation_messages: List[Dict[str, Any]] = []
    history_source = "none"

    thread_id = cl.user_session.get("thread_id")
    logger.info(
        f"🧾 Preparing to store history for {conversation_id} (thread_id={thread_id})"
    )
    if not thread_id:
        if local_history:
            logger.warning("⚠️ No thread_id available; using local history fallback")
            conversation_messages = local_history
            history_source = "local_session"
        else:
            logger.warning("⚠️ No thread_id available for conversation history capture")
            return False
    elif agents_client is None or not hasattr(agents_client, "messages"):
        if local_history:
            logger.warning("⚠️ Azure Agents client unavailable; using local history fallback")
            conversation_messages = local_history
            history_source = "local_session"
        else:
            logger.warning("⚠️ Azure Agents client unavailable; cannot fetch thread messages")
            return False
    else:
        try:
            try:
                thread_messages = agents_client.messages.list(
                    thread_id=str(thread_id), order="desc", limit=50
                )
                thread_messages_list = list(thread_messages) if thread_messages else []
            except Exception as fetch_error:
                logger.warning(f"⚠️ Thread messages iterator failed: {fetch_error}")
                thread_messages_list = []
            logger.info(
                f"🧾 Retrieved {len(thread_messages_list)} thread messages for {conversation_id}"
            )
        except Exception as fetch_error:
            logger.error(
                f"❌ Failed to retrieve thread messages for {conversation_id}: {fetch_error}"
            )
            thread_messages_list = []

        for msg in reversed(thread_messages_list):  # Oldest first
            # Skip system timestamp prompts
            if getattr(msg, "role", "" ) == "assistant" and "CURRENT TIME:" in str(getattr(msg, "content", "")):
                continue

            content_text = ""
            content_value = getattr(msg, "content", "")
            if isinstance(content_value, list):
                for content_item in content_value:
                    text_value = getattr(getattr(content_item, "text", None), "value", None)
                    if text_value:
                        content_text = text_value
                        break
            elif content_value:
                content_text = str(content_value)

            if not content_text.strip():
                continue

            timestamp = getattr(msg, "created_at", datetime.now(timezone.utc))
            if hasattr(timestamp, "isoformat"):
                timestamp = timestamp.isoformat()

            conversation_messages.append(
                {
                    "role": "Lucy" if getattr(msg, "role", "assistant") == "assistant" else "User",
                    "content": content_text,
                    "timestamp": str(timestamp),
                }
            )

        if conversation_messages:
            history_source = "agents_client"
        elif local_history:
            logger.warning("⚠️ No thread messages returned; using local history fallback")
            conversation_messages = local_history
            history_source = "local_session"

    if not conversation_messages:
        logger.warning("⚠️ No conversation messages available to store for handoff")
        return False

    # Prepare metadata for downstream systems
    apex_id = cl.user_session.get("apex_id", "UNKNOWN")
    handoff_reason = cl.user_session.get("handoff_reason", "User requested human assistance")

    try:
        from conversation_summarizer import conversation_summarizer

        summary_metadata = {"apex_id": apex_id, "handoff_reason": handoff_reason}
        member_notes_summary = conversation_summarizer.generate_summary(
            conversation_messages, summary_metadata
        )
        analytics_data = conversation_summarizer.extract_key_data_points(
            conversation_messages, summary_metadata
        )
    except Exception as summary_error:
        logger.error(f"Failed to generate conversation summary: {summary_error}")
        member_notes_summary = "Conversation summary unavailable."
        analytics_data = {}

    metadata = {
        "apex_id": apex_id,
        "thread_id": str(thread_id),
        "handoff_reason": handoff_reason,
        "handoff_timestamp": datetime.now(timezone.utc).isoformat(),
        "member_notes_summary": member_notes_summary,
        "analytics_data": analytics_data,
        "history_source": history_source,
    }

    try:
        from user_functions import store_conversation_history_sync

        store_result = json.loads(
            store_conversation_history_sync(
                conversation_id=conversation_id,
                conversation_type="pre_handoff",
                messages=conversation_messages,
                metadata=metadata,
            )
        )
    except Exception as store_error:
        logger.error(f"❌ Exception while storing conversation history: {store_error}")
        return False

    if store_result.get("success"):
        logger.info(
            f"✅ Stored {store_result.get('message_count')} pre-handoff messages for {conversation_id}"
        )
        return True

    logger.error(f"❌ Failed to store conversation history: {store_result}")
    return False

async def notify_user_of_pending_messages(conversation_id: str):
    """Monitor for queued messages and notify user to type something to see them"""
    # This function monitors the queue but cannot display messages directly
    # due to Chainlit context limitations in background tasks
    try:
        notified = False
        while websocket_bridge.is_bridge_active(conversation_id):
            # Check if there are queued messages
            if conversation_id in websocket_bridge.message_queues:
                queue_size = websocket_bridge.message_queues[conversation_id].qsize()
                if queue_size > 0 and not notified:
                    logger.info(f"📬 {queue_size} message(s) waiting in queue for conversation {conversation_id}")
                    # We can't send a message here due to context limitations
                    # Messages will be displayed when user types anything
                    notified = True
                elif queue_size == 0:
                    notified = False
            
            # Wait before checking again
            await asyncio.sleep(2.0)
            
    except Exception as e:
        logger.error(f"Error in message monitor: {str(e)}")

async def _cancel_callback_timeout_monitor(conversation_id: str) -> None:
    """Cancel callback timeout monitoring when an agent joins."""
    try:
        from callback_system import cancel_conversation_timeout_monitor
        await cancel_conversation_timeout_monitor(conversation_id)
        logger.info(f"✅ Cancelled callback timeout monitor for {conversation_id}")
    except ImportError as import_err:
        logger.warning(f"Callback system not available: {import_err}")
    except Exception as e:
        logger.warning(f"⚠️ Failed to cancel callback timeout monitor for {conversation_id}: {e}")

async def monitor_agent_response_timeout(conversation_id: str, agent_name: str, timeout_minutes: int = 4):
    """
    Monitor for agent response timeout and escalate if needed
    """
    try:
        # Wait for the timeout period
        await asyncio.sleep(timeout_minutes * 60)

        # Check if bridge is still active (means agent hasn't responded)
        if websocket_bridge.is_bridge_active(conversation_id):
            bridge_info = websocket_bridge.get_bridge_info(conversation_id)

            # Check if there have been any agent messages
            if bridge_info and bridge_info.get('agent_message_count', 0) == 0:
                logger.warning(f"⏱️ Agent {agent_name} hasn't responded within {timeout_minutes} minutes")

                # Send timeout notification to user
                await cl.Message(
                    content=f"⏱️ **Agent Response Timeout**\n\n{agent_name} hasn't responded yet. Let me try to connect you with another available agent or offer alternative assistance.",
                    author="System"
                ).send()

                try:
                    conversation_store.update_handoff_status(
                        conversation_id,
                        status="timeout",
                        reason="agent_no_response",
                        closed_at=datetime.utcnow().isoformat()
                    )
                except Exception as status_err:
                    logger.warning(f"⚠️ Could not mark timeout for {conversation_id}: {status_err}")

                # Try to find another available agent
                from user_functions import check_teams_availability_sync
                try:
                    availability_result = json.loads(check_teams_availability_sync())
                    if availability_result.get("available"):
                        new_agent_email = availability_result.get("agent_email")
                        new_agent_name = availability_result.get("agent_name")

                        if new_agent_email != cl.user_session.get("handoff_agent_email"):
                            # Found different agent, escalate to them
                            await escalate_to_new_agent(conversation_id, new_agent_email, new_agent_name, "Original agent timeout")
                        else:
                            # Same agent, offer callback
                            await offer_callback_fallback(agent_name)
                    else:
                        # No agents available, offer callback
                        await offer_callback_fallback(agent_name)

                except Exception as e:
                    logger.error(f"Error during timeout escalation: {str(e)}")
                    await offer_callback_fallback(agent_name)

    except Exception as e:
        logger.error(f"Error in timeout monitoring: {str(e)}")

async def escalate_to_new_agent(conversation_id: str, agent_email: str, agent_name: str, reason: str):
    """Escalate to a new agent when original agent doesn't respond"""
    try:
        # Send Teams notification to new agent
        try:
            from teams_integration import send_teams_handoff_notification_sync
        except ImportError:
            logger.warning("Teams integration not available for escalation")
            send_teams_handoff_notification_sync = None

        apex_id = str(cl.user_session.get("apex_id", "Unknown"))
        portal_url = f"{os.getenv('AGENT_PORTAL_URL', 'http://localhost:8001')}/agent/conversation/{conversation_id}"

        if send_teams_handoff_notification_sync:
            notification_result = json.loads(send_teams_handoff_notification_sync(
                agent_email=agent_email,
                apex_id=apex_id,
                reason=f"Re-escalation: {reason}",
                portal_url=portal_url,
                conversation_id=conversation_id
            ))
        else:
            notification_result = {"success": False, "message": "Teams integration not available"}

        if notification_result.get("success"):
            await cl.Message(
                content=f"🔄 **Re-escalated to {agent_name}**\n\nI've notified {agent_name} about your conversation. They should join shortly.",
                author="System"
            ).send()

            # Update session with new agent info
            cl.user_session.set("handoff_agent_name", agent_name)
            cl.user_session.set("handoff_agent_email", agent_email)

            # Start new timeout monitoring
            asyncio.create_task(monitor_agent_response_timeout(conversation_id, agent_name))
        else:
            await offer_callback_fallback(agent_name)

    except Exception as e:
        logger.error(f"Error escalating to new agent: {str(e)}")
        await offer_callback_fallback(agent_name)

async def offer_callback_fallback(original_agent_name: str):
    """Automatically schedule callback when no agents respond after 4 minutes"""
    try:
        # Get session information
        apex_id = str(cl.user_session.get("apex_id", "Unknown"))
        conversation_id = str(cl.user_session.get("active_handoff_conversation_id", "Unknown"))
        original_reason = str(cl.user_session.get("handoff_reason", "User requested human assistance"))

        # Import the callback collection function
        from user_functions import collect_callback_information_sync

        # Automatically initiate callback collection process
        logger.info(f"⏱️ 4-minute timeout reached for {original_agent_name}. Automatically scheduling callback for {apex_id}")

        # Send message explaining the timeout and automatic callback scheduling
        await cl.Message(
            content=f"⏱️ **Agent Response Timeout**\n\n{original_agent_name} hasn't responded within 4 minutes. No worries! I'll automatically schedule a callback for you so our support team can reach out within 24 hours.\n\nI just need a few details to set this up:",
            author="System"
        ).send()

        # Call the callback collection function
        callback_result = json.loads(collect_callback_information_sync(apex_id, conversation_id, original_reason))

        if callback_result.get("success"):
            # Set session state to indicate we're collecting callback info
            cl.user_session.set("collecting_callback_info", {
                "conversation_id": conversation_id,
                "apex_id": apex_id,
                "reason": original_reason,
                "step": "phone_number"
            })

            # Send the callback collection message
            await cl.Message(
                content=f"📞 **Callback Setup**\n\n{callback_result.get('message')}\n\n**Step 1 of 3:** Please provide your phone number (including area code)",
                author="System"
            ).send()
        else:
            # Fallback if callback collection fails
            await cl.Message(
                content=f"📞 **Callback Option**\n\nI'm sorry, {original_agent_name} isn't available right now. I'd like to schedule a callback for you, but encountered an issue with the automatic setup.\n\nPlease call our support line directly or try the handoff request again later.",
                author="System"
            ).send()

        # Clear the active handoff to return to callback collection mode
        cl.user_session.set("active_handoff_conversation_id", None)
        cl.user_session.set("pending_handoff", None)
        try:
            conversation_store.mark_closed(conversation_id, "callback_scheduled")
        except Exception as status_err:
            logger.warning(f"⚠️ Could not mark callback closure: {status_err}")

    except Exception as e:
        logger.error(f"Error in automatic callback fallback: {str(e)}")
        # Ultimate fallback - offer manual options
        await cl.Message(
            content=f"📞 **Alternative Options Available**\n\nSince {original_agent_name} isn't available right now, I can:\n\n1. **Schedule a callback** within the next 24 hours\n2. **Continue helping you** with my AI capabilities\n3. **Try again later** when more agents are available\n\nWhat would you prefer?",
            author="System"
        ).send()

        # Clear the active handoff to return to normal AI operation
        cl.user_session.set("active_handoff_conversation_id", None)
        cl.user_session.set("pending_handoff", None)


async def handle_callback_collection(user_input: str, callback_info: dict):
    """Handle the callback information collection process"""
    try:
        step = callback_info.get("step")
        apex_id = str(callback_info.get("apex_id", "Unknown"))
        conversation_id = str(callback_info.get("conversation_id", ""))
        reason = str(callback_info.get("reason", ""))

        logger.info(f"📞 Handling callback collection step '{step}' for {apex_id}")

        if step == "phone_number":
            # Validate phone number format
            phone_number = user_input.strip()
            if not phone_number or len(phone_number) < 10:
                await cl.Message(
                    content="❌ Please provide a valid phone number with area code (e.g., 555-123-4567 or 5551234567)",
                    author="System"
                ).send()
                return

            # Store phone number and move to next step
            callback_info["phone_number"] = phone_number
            callback_info["step"] = "best_time"
            cl.user_session.set("collecting_callback_info", callback_info)

            await cl.Message(
                content=f"✅ **Phone number received:** {phone_number}\n\n**Step 2 of 3:** What's the best time to call you? (PST 9am-5pm weekdays)\n\nExamples:\n- \"Tomorrow morning\"\n- \"Friday afternoon\"\n- \"Any time between 10am-2pm\"",
                author="System"
            ).send()

        elif step == "best_time":
            # Store best time and move to final step
            best_time = user_input.strip()
            if not best_time:
                await cl.Message(
                    content="❌ Please let me know when would be the best time to call you (PST 9am-5pm weekdays)",
                    author="System"
                ).send()
                return

            callback_info["best_time"] = best_time
            callback_info["step"] = "final_reason"
            cl.user_session.set("collecting_callback_info", callback_info)

            await cl.Message(
                content=f"✅ **Best time noted:** {best_time}\n\n**Step 3 of 3:** Please briefly describe what specific assistance you need regarding your case:",
                author="System"
            ).send()

        elif step == "final_reason":
            # Collect final reason and submit callback request
            detailed_reason = user_input.strip()
            if not detailed_reason:
                await cl.Message(
                    content="❌ Please provide a brief description of what assistance you need",
                    author="System"
                ).send()
                return

            # Submit the callback request
            from user_functions import submit_callback_request_sync

            phone_number = str(callback_info.get("phone_number", ""))
            best_time = str(callback_info.get("best_time", ""))

            # Combine original reason with detailed reason
            full_reason = f"{reason}. Additional details: {detailed_reason}"

            result = json.loads(submit_callback_request_sync(
                apex_id=apex_id,
                conversation_id=conversation_id,
                phone_number=phone_number,
                best_time=best_time,
                reason=full_reason
            ))

            if result.get("success"):
                await cl.Message(
                    content=result.get("message"),
                    author="System"
                ).send()

                # Clear callback collection state
                cl.user_session.set("collecting_callback_info", None)

                # Send additional helpful message
                await cl.Message(
                    content="Is there anything else I can help you with while you wait for your callback?",
                    author="Lucy"
                ).send()
            else:
                await cl.Message(
                    content=f"❌ **Error submitting callback request**\n\n{result.get('message', 'Please try again or call our support line directly.')}",
                    author="System"
                ).send()

                # Clear callback collection state on error
                cl.user_session.set("collecting_callback_info", None)

    except Exception as e:
        logger.error(f"Error in callback collection: {str(e)}")
        await cl.Message(
            content="❌ **Error in callback setup**\n\nI'm sorry, there was an error processing your callback request. Please try requesting a handoff again or call our support line directly.",
            author="System"
        ).send()

        # Clear callback collection state on error
        cl.user_session.set("collecting_callback_info", None)


# Retry logic for robustness
@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=8),
)
async def send_handoff_email(user_input: str, apex_id: str = "Unknown"):
    if not all(
        [
            EMAIL_CONFIG["smtp_server"],
            EMAIL_CONFIG["sender_email"],
            EMAIL_CONFIG["sender_password"],
            EMAIL_CONFIG["receiver_email"],
        ]
    ):
        logger.warning("⚠️ Email configuration incomplete. Skipping email handoff.")
        return False
    try:
        msg = MIMEText(
            f"A user requested human assistance.\n"
            f"Apex ID: {apex_id}\nMessage: {user_input}"
        )
        msg["Subject"] = "Human Handoff Request from APEX AI Assistant"
        msg["From"] = EMAIL_CONFIG["sender_email"]
        msg["To"] = EMAIL_CONFIG["receiver_email"]
        with smtplib.SMTP(
            EMAIL_CONFIG["smtp_server"], EMAIL_CONFIG["smtp_port"]
        ) as server:
            server.starttls()
            server.login(EMAIL_CONFIG["sender_email"], EMAIL_CONFIG["sender_password"])
            server.sendmail(
                EMAIL_CONFIG["sender_email"],
                EMAIL_CONFIG["receiver_email"],
                msg.as_string(),
            )
        logger.info("✅ Handoff email sent successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Error sending handoff email: {e}")
        return False


def normalize_apex_id(apex_id: str) -> str:
    return apex_id.upper()


def clean_handoff_json_from_response(response: str) -> str:
    """
    Clean JSON payloads from assistant response that are meant for handoff detection.

    This function removes JSON objects containing 'establish_bridge' key from the
    assistant response so they aren't displayed to users, while preserving the
    human-readable content.

    Args:
        response: The raw assistant response containing both user content and JSON

    Returns:
        Cleaned response with JSON payloads removed
    """
    import re
    import json

    try:
        # Pattern to match JSON objects that might contain establish_bridge
        # Look for JSON-like structures at the end of the response
        json_pattern = r'\n\s*\{[^}]*"establish_bridge"\s*:\s*true[^}]*\}\s*$'

        # Remove JSON payload if found
        cleaned = re.sub(json_pattern, '', response, flags=re.MULTILINE | re.DOTALL)

        # Also try to find and remove any JSON block that contains handoff info
        # This handles cases where the JSON might be formatted differently
        lines = response.split('\n')
        cleaned_lines = []
        in_json_block = False

        for line in lines:
            line_stripped = line.strip()

            # Check if this line starts a JSON block with handoff info
            if line_stripped.startswith('{') and 'establish_bridge' in line:
                in_json_block = True
                continue

            # Check if this line ends a JSON block
            if in_json_block and line_stripped.endswith('}'):
                in_json_block = False
                continue

            # Skip lines that are part of the JSON block
            if in_json_block:
                continue

            # Keep non-JSON lines
            cleaned_lines.append(line)

        # Use the more thorough line-by-line cleaning if it's different
        line_cleaned = '\n'.join(cleaned_lines).strip()

        # Use whichever cleaning method removed more content
        if len(line_cleaned) < len(cleaned):
            result = line_cleaned
        else:
            result = cleaned.strip()

        # If no cleaning occurred, return original with trailing whitespace removed
        if result == response.strip():
            return response.strip()

        logger.debug(f"Cleaned handoff JSON from response. Original length: {len(response)}, Cleaned length: {len(result)}")
        return result

    except Exception as e:
        logger.warning(f"Error cleaning handoff JSON from response: {str(e)}")
        # On error, return original response to be safe
        return response


def generate_sas_url(blob_url: str) -> Optional[str]:
    """Generate a read‑only SAS URL for the given blob using BlobClient."""
    safe_blob_url = blob_url.split("?", 1)[0] if blob_url else blob_url
    logger.info(f"Generating SAS URL for: {safe_blob_url}")

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
            if any(ch in blob_client.blob_name for ch in "[]()"):
                logger.warning(
                    f"⚠️ SAS blob name contains markdown artifacts: {blob_client.blob_name}"
                )

            # Generate SAS token using the blob client properties
            start_time = datetime.now(timezone.utc)
            expiry_time = start_time + timedelta(hours=2)

            # Create permission with read access
            permission = BlobSasPermissions(read=True)

            # Ensure account_name is not None
            account_name = blob_client.account_name
            if not account_name:
                raise ValueError("Blob client account name is None")

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

            # Ensure account_name is not None
            account_name = blob_client.account_name
            if not account_name:
                raise ValueError("Blob client account name is None")

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


def extract_filename_from_sas_url(sas_url: str) -> str:
    """Extract the filename (APEXID) from a SAS URL for PDF naming."""
    try:
        from urllib.parse import urlparse

        parsed_url = urlparse(sas_url)
        path = parsed_url.path.lstrip("/")

        # Extract filename from path (should be container/filename.pdf)
        path_parts = path.split("/")
        if len(path_parts) >= 2:
            filename = path_parts[-1]  # Get the last part (filename.pdf)
            if filename.lower().endswith(".pdf"):
                apex_id = filename[:-4]  # Remove .pdf
                logger.info(f"✅ Extracted APEXID from URL: {apex_id}")
                return apex_id

        # Fallback: try to extract any reasonable filename
        if "/" in path:
            filename = path.split("/")[-1]
            if filename and filename.lower().endswith(".pdf"):
                apex_id = filename[:-4]
                logger.info(f"✅ Extracted APEXID (fallback): {apex_id}")
                return apex_id

        logger.warning(f"⚠️ Could not extract APEXID from URL: {sas_url[:50]}...")
        return "Class Action Notice"  # Fallback to original name

    except Exception as e:
        logger.error(f"❌ Error extracting filename from URL: {e}")
        return "Class Action Notice"  # Fallback to original name


def _normalize_pdf_display_name(name: str) -> str:
    """Ensure the PDF display name includes the .pdf extension."""
    if not name:
        return "Class Action Notice.pdf"
    if name.lower().endswith(".pdf"):
        return name
    return f"{name}.pdf"


def _run_startup_diagnostics():
    storage_cs = os.getenv("AZURE_STORAGE_CONNECTION_STRING", "")
    logger.info(f"Storage connection string detected: length={len(storage_cs)}")

    test_account = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
    if not test_account:
        logger.warning("AZURE_STORAGE_ACCOUNT_NAME not set – skipping SAS self-test")
        return

    container_name = (
        os.getenv("AZURE_STORAGE_CONTAINER_NAME")
        or os.getenv("AZURE_STORAGE_CONTAINER")
        or "lucyrag"
    )
    sample_blob = f"https://{test_account}.blob.core.windows.net/{container_name}/DIAG_PING.pdf"
    try:
        _sas_test = generate_sas_url(sample_blob)
    except Exception as diag_err:
        logger.error(f"SAS self-test raised exception: {diag_err}")
        _sas_test = None

    if _sas_test and not str(_sas_test).startswith("ERROR"):
        logger.info("✅ SAS self-test succeeded – credentials look good")
    else:
        logger.error(f"❌ SAS self-test FAILED: {_sas_test}")


# Run immediately at import time
_run_startup_diagnostics()


@retry(
    retry=retry_if_exception_type(ServiceResponseError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=4, max=10),
)
def extract_pdf_url(search_result: Dict) -> Optional[str]:
    logger.info("🔍 Extracting PDF URL from search result")
    blob_url_candidate: Optional[str] = None

    # New logic: try metadata_storage_path first
    if (
        "metadata_storage_path" in search_result
        and search_result["metadata_storage_path"]
    ):
        storage_path = search_result["metadata_storage_path"]
        storage_account = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")

        # Preserve the full path to the blob (including folder structure)
        storage_path = storage_path.lstrip("/")

        container_name = (
            os.getenv("AZURE_STORAGE_CONTAINER_NAME")
            or os.getenv("AZURE_STORAGE_CONTAINER")
            or "lucyrag"
        )
        parts = storage_path.split("/", 1)
        if parts[0].lower() == container_name.lower():
            blob_url_candidate = (
                f"https://{storage_account}.blob.core.windows.net/{storage_path}"
            )
        else:
            blob_url_candidate = (
                f"https://{storage_account}.blob.core.windows.net/"
                f"{container_name}/{storage_path}"
            )

        # Log the constructed URL for debugging
        logger.info(f"Constructed blob URL: {blob_url_candidate}")

    # Fallback: decode parent_id which is base64‑encoded full blob URL
    elif "parent_id" in search_result and search_result["parent_id"]:
        try:
            padded = search_result["parent_id"] + "=="
            decoded = base64.urlsafe_b64decode(padded).decode("utf-8", "ignore").strip()
            if decoded.lower().startswith("http") and decoded.lower().endswith(".pdf"):
                blob_url_candidate = decoded
        except Exception as decode_err:
            logger.debug(f"parent_id base64 decode failed: {decode_err}")

    if blob_url_candidate:
        sas_url = generate_sas_url(blob_url_candidate)
        if sas_url and not sas_url.startswith("ERROR"):
            logger.info(f"✅ Generated SAS URL: {sas_url[:50]}...")
            return sas_url
        else:
            logger.error(f"❌ Failed to generate SAS token: {sas_url}")
            return sas_url  # still return string so FunctionTool is valid
    # blob_url_candidate was None.
    logger.warning("❌ No valid PDF URL found in search result")
    return None


def get_agent_instructions():
    """Return agent instructions from file."""
    return load_system_prompt()


# Azure AI Search implementation - supports both Foundry connections and direct API
async def execute_search(user_data: Dict, func_tool=None) -> List[Dict]:
    """
    Execute Azure AI Search query using either Foundry connections or direct API.
    Supports both approaches based on available environment variables.
    """
    logger.info(f"🔍 Executing Azure AI Search with data: {user_data}")

    try:
        # Check for direct API credentials first
        search_endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
        search_api_key = os.getenv("AZURE_SEARCH_API_KEY")
        search_index_name = os.getenv("AZURE_SEARCH_INDEX_NAME")

        if search_endpoint and search_api_key and search_index_name:
            # Direct API approach
            return await execute_direct_search(
                user_data, search_endpoint, search_api_key, search_index_name
            )

        # Check for Foundry connection approach
        search_conn_id = os.getenv("AI_AZURE_AI_CONNECTION_ID")
        if search_conn_id and search_index_name:
            logger.info(
                "🔗 Azure AI Search via Foundry connection is handled automatically "
                "by AzureAISearchTool - this function should not be called"
            )
            return []

        logger.warning(
            "⚠️ No Azure AI Search configuration found. "
            "Need either direct API credentials or Foundry connection."
        )
        return []

    except Exception as e:
        logger.error(f"❌ Error in Azure AI Search: {str(e)}", exc_info=True)
        return []


async def execute_direct_search(
    user_data: Dict, endpoint: str, api_key: str, index_name: str
) -> List[Dict]:
    """Execute direct Azure AI Search API calls."""
    try:
        from azure.search.documents import SearchClient
        from azure.core.credentials import AzureKeyCredential
        from azure.core.exceptions import HttpResponseError

        # Build search query
        search_query = construct_search_query(user_data)
        if not search_query:
            logger.warning("⚠️ No search query constructed from user data")
            return []

        logger.info(
            f"🔍 Searching Azure AI Search index '{index_name}' for: {search_query}"
        )

        # Create search client
        credential = AzureKeyCredential(api_key)
        search_client = SearchClient(
            endpoint=endpoint, index_name=index_name, credential=credential
        )

        semantic_config = os.getenv(
            "AZURE_SEARCH_SEMANTIC_CONFIG",
            "rag-1748449715445-semantic-configuration",
        )

        # Execute search with hybrid approach using new index structure
        search_kwargs = {
            "search_text": search_query,
            "top": 10,  # Increased for better coverage
            "include_total_count": True,
            "query_type": "semantic",  # Use semantic search with new configuration
            "semantic_configuration_name": semantic_config,
            "select": [
                "chunk_id",
                "parent_id",
                "chunk",  # Main content field for RAG
                "title",  # Document title
                "metadata_storage_name",  # Filename (APEXID.pdf)
                "metadata_storage_path",  # Full blob path
                "metadata_storage_file_extension",
                "file_extension",
            ],
            "filter": "file_extension eq '.pdf'",
        }

        filter_used = "filter" in search_kwargs
        try:
            results_list = list(search_client.search(**search_kwargs))
        except HttpResponseError:
            logger.warning(
                "⚠️ PDF filter failed; retrying search without filter",
                exc_info=True,
            )
            search_kwargs.pop("filter", None)
            filter_used = False
            results_list = list(search_client.search(**search_kwargs))

        if filter_used and not results_list:
            logger.warning("⚠️ PDF filter returned no results; retrying without filter")
            search_kwargs.pop("filter", None)
            filter_used = False
            results_list = list(search_client.search(**search_kwargs))

        # Defensive PDF-only filter in case the indexer/schema drifted.
        pdf_results = []
        for result in results_list:
            ext = (
                (result.get("file_extension") or "")
                or (result.get("metadata_storage_file_extension") or "")
            ).lower()
            if ext == ".pdf":
                pdf_results.append(result)
        results_list = pdf_results

        # Convert results to expected format
        formatted_results = []
        for result in results_list:
            formatted_result = {
                "chunk_id": result.get("chunk_id", ""),
                "parent_id": result.get("parent_id", ""),
                "chunk": result.get("chunk", ""),  # Main content for RAG
                "title": result.get("title", ""),
                "metadata_storage_name": result.get("metadata_storage_name", ""),
                "metadata_storage_path": result.get("metadata_storage_path", ""),
                "metadata_storage_file_extension": result.get("metadata_storage_file_extension", ""),
                "score": getattr(result, "@search.score", 0.0),
            }
            formatted_results.append(formatted_result)

        logger.info(f"✅ Azure AI Search returned {len(formatted_results)} results")
        return formatted_results

    except ImportError as import_err:
        logger.error(
            f"❌ Azure Search SDK not available: {import_err}. "
            f"Install with: pip install azure-search-documents"
        )
        return []
    except Exception as search_err:
        logger.error(f"❌ Direct Azure AI Search failed: {search_err}", exc_info=True)
        return []


# Missing extract_text_from_pdf function - placeholder for now
async def download_pdf_locally(sas_url: str, pdf_name: str) -> Optional[str]:
    """Download PDF from SAS URL and save locally for Chainlit viewing."""
    try:
        import aiohttp
        import tempfile
        import os

        # Create a temporary directory for PDFs if it doesn't exist
        temp_dir = os.path.join(tempfile.gettempdir(), "chainlit_pdfs")
        os.makedirs(temp_dir, exist_ok=True)

        # Create local file path
        safe_filename = "".join(c for c in pdf_name if c.isalnum() or c in ("-", "_"))
        local_path = os.path.join(temp_dir, f"{safe_filename}.pdf")

        logger.info(f"📄 Downloading PDF locally: {pdf_name} -> {local_path}")

        # Download the PDF content from SAS URL with timeout
        timeout = aiohttp.ClientTimeout(total=30, connect=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(sas_url) as response:
                if response.status != 200:
                    logger.error(f"Failed to download PDF: HTTP {response.status}")
                    return None

                pdf_content = await response.read()
                logger.info(f"Downloaded PDF: {len(pdf_content)} bytes")

        # Save to local file
        with open(local_path, "wb") as f:
            f.write(pdf_content)

        logger.info(f"✅ PDF saved locally: {local_path}")
        return local_path

    except Exception as e:
        logger.error(f"❌ Error downloading PDF locally: {str(e)}", exc_info=True)
        return None


# --- PDF pending state helpers ---
PENDING_PDF_TTL_SECONDS = 300


def _record_pending_pdf(sas_url: str, pdf_name: str, *, display: str = "side") -> None:
    """Record a pending PDF for attachment even if the model drops markers."""
    try:
        if not sas_url:
            return
        payload = {
            "url": sas_url,
            "name": pdf_name or "Class Action Notice",
            "display": display,
            "ts": time.time(),
        }
        cl.user_session.set("pending_pdf", payload)
        logger.info(
            f"📌 Pending PDF stored: name={payload['name']} display={display} url={sas_url[:80]}..."
        )
    except Exception as e:
        logger.warning(f"⚠️ Could not store pending PDF: {e}")


def _pop_pending_pdf() -> Optional[dict]:
    """Return and clear pending PDF if fresh."""
    try:
        pending = cl.user_session.get("pending_pdf")
        if not pending:
            return None
        age = time.time() - float(pending.get("ts", 0))
        if age > PENDING_PDF_TTL_SECONDS:
            logger.info(f"🧹 Clearing stale pending PDF (age={age:.1f}s)")
            cl.user_session.set("pending_pdf", None)
            return None
        cl.user_session.set("pending_pdf", None)
        return pending
    except Exception as e:
        logger.warning(f"⚠️ Could not read pending PDF: {e}")
        return None


def _extract_pdf_info_from_text(text: str) -> Optional[dict]:
    """Extract PDF info from tool output or assistant text."""
    if not text:
        return None
    try:
        import re

        # Try structured PDF_DISPLAY_INFO first
        pdf_url_match = re.search(r"- PDF_URL: (.+)", text)
        pdf_name_match = re.search(r"- PDF_NAME: (.+)", text)
        display_match = re.search(r"- DISPLAY_MODE: (.+)", text)

        if pdf_url_match:
            pdf_url = pdf_url_match.group(1).strip()
            pdf_name = (
                pdf_name_match.group(1).strip()
                if pdf_name_match
                else extract_filename_from_sas_url(pdf_url)
            )
            display_mode = display_match.group(1).strip() if display_match else "side"
            return {"url": pdf_url, "name": pdf_name, "display": display_mode}

        # Try markdown links
        links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
        if links:
            for candidate in links:
                if "blob.core.windows.net" in candidate and "sig=" in candidate:
                    pdf_url = candidate
                    return {
                        "url": pdf_url,
                        "name": extract_filename_from_sas_url(pdf_url),
                        "display": "side",
                    }
                if ".pdf" in candidate.lower():
                    pdf_url = candidate
                    return {
                        "url": pdf_url,
                        "name": extract_filename_from_sas_url(pdf_url),
                        "display": "side",
                    }

        # Fallback: any http(s) URL that looks like SAS
        urls = re.findall(r"https?://[^\s\)\]\"'>]+", text)
        for candidate in urls:
            if "blob.core.windows.net" in candidate and "sig=" in candidate:
                return {
                    "url": candidate,
                    "name": extract_filename_from_sas_url(candidate),
                    "display": "side",
                }
            if ".pdf" in candidate.lower():
                return {
                    "url": candidate,
                    "name": extract_filename_from_sas_url(candidate),
                    "display": "side",
                }

        return None
    except Exception as e:
        logger.warning(f"⚠️ Failed to parse PDF info from text: {e}")
        return None


def _classify_notice_tool_output(output: Any) -> str:
    """Classify notice tool output so a miss does not keep re-triggering lookup."""
    text = str(output or "").strip()
    if not text:
        return "unknown"
    if _extract_pdf_info_from_text(text):
        return "pdf_found"

    lowered = text.lower()
    found_markers = (
        "i've found your notice",
        "i found your notice",
        "found your notice",
        "based on the indexed content",
    )
    if any(marker in lowered for marker in found_markers):
        return "found"

    miss_markers = (
        "couldn't find a notice",
        "could not find a notice",
        "wasn't able to locate",
        "was not able to locate",
        "no notice document",
    )
    if any(marker in lowered for marker in miss_markers):
        return "not_found"

    if lowered.startswith("error"):
        return "unknown"

    # Return None for ambiguous/non-terminal output instead of "answered"
    return None


def _record_notice_lookup_status(status: str, output: Any = None) -> None:
    """Persist terminal notice lookup state for later turns."""
    if status not in {"pdf_found", "found", "not_found", "answered"}:
        return
    try:
        cl.user_session.set("pending_notice_request", None)
        cl.user_session.set("pending_notice_request_text", None)
        cl.user_session.set("notice_lookup_status", status)
        apex_id = cl.user_session.get("apex_id")
        if apex_id:
            cl.user_session.set("notice_lookup_apex_id", str(apex_id))
        if status == "not_found" and output:
            cl.user_session.set("notice_lookup_last_miss", str(output)[:1000])
        elif status in {"pdf_found", "found", "answered"}:
            # Clear miss marker on successful lookup
            cl.user_session.set("notice_lookup_last_miss", "")
        logger.info("📌 Notice lookup terminal status recorded: %s", status)
    except Exception as e:
        logger.warning("⚠️ Could not record notice lookup status: %s", e)


def _hash_url(url: Optional[str]) -> str:
    if not url:
        return "none"
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]


def _extract_links(text: Optional[str]) -> Dict[str, List[str]]:
    if not text:
        return {"urls": [], "markdown": []}
    import re

    urls = re.findall(r"https?://[^\\s\\)\\]\"'>]+", text)
    markdown = re.findall(r"\\[[^\\]]+\\]\\(([^)]+)\\)", text)
    return {"urls": urls, "markdown": markdown}


def _extract_blob_snippets(text: Optional[str], *, context: int = 200) -> List[str]:
    if not text:
        return []
    import re

    snippets: List[str] = []
    needle = "blob.core.windows.net"
    idx = 0
    while True:
        idx = text.find(needle, idx)
        if idx == -1:
            break
        start = max(0, idx - 40)
        end = min(len(text), idx + context)
        snippet = text[start:end]
        snippet = re.sub(r"sig=[^&\\s]+", "sig=<redacted>", snippet)
        snippet = re.sub(r"se=[^&\\s]+", "se=<redacted>", snippet)
        snippet = re.sub(r"st=[^&\\s]+", "st=<redacted>", snippet)
        snippets.append(snippet)
        idx += len(needle)
    return snippets


def _log_link_debug(stage: str, *, content: Optional[str] = None, pdf_url: Optional[str] = None,
                    pdf_name: Optional[str] = None, thread_id: Optional[str] = None,
                    turn_id: Optional[int] = None) -> None:
    links = _extract_links(content)
    logger.info(
        f"🔗[{stage}] thread={thread_id} turn={turn_id} "
        f"pdf_name={pdf_name} pdf_url_hash={_hash_url(pdf_url)} "
        f"urls={len(links['urls'])} markdown={len(links['markdown'])} "
        f"content_len={(len(content) if content else 0)}"
    )
    if links["urls"]:
        preview = ", ".join(u[:120] + ("..." if len(u) > 120 else "") for u in links["urls"][:3])
        logger.info(f"🔗[{stage}] urls_preview={preview}")
    if links["markdown"]:
        preview = ", ".join(u[:120] + ("..." if len(u) > 120 else "") for u in links["markdown"][:3])
        logger.info(f"🔗[{stage}] markdown_preview={preview}")
    blob_snippets = _extract_blob_snippets(content)
    if blob_snippets:
        for idx, snippet in enumerate(blob_snippets[:2]):
            logger.info(f"🧾[{stage}] blob_snippet_{idx}={snippet}")


# COMMENTED OUT: PDF extraction workaround - new index supports native RAG
# async def extract_text_from_pdf(sas_url: str) -> str:
#     """Extract text from PDF using the SAS URL by downloading and parsing it."""
#     logger.info(f"📄 Extracting text from PDF: {sas_url[:50]}...")
#
#     try:
#         import aiohttp
#         import PyPDF2
#         import io
#
#         # Download the PDF content from SAS URL
#         async with aiohttp.ClientSession() as session:
#             async with session.get(sas_url) as response:
#                 if response.status != 200:
#                     logger.error(f"Failed to download PDF: HTTP {response.status}")
#                     return f"ERROR: Failed to download PDF (HTTP {response.status})"
#
#                 pdf_content = await response.read()
#                 logger.info(f"Downloaded PDF: {len(pdf_content)} bytes")
#
#         # Extract text using PyPDF2
#         pdf_file = io.BytesIO(pdf_content)
#         pdf_reader = PyPDF2.PdfReader(pdf_file)
#
#         # Extract text from all pages
#         extracted_text = ""
#         for page_num, page in enumerate(pdf_reader.pages):
#             try:
#                 page_text = page.extract_text()
#                 if page_text.strip():
#                     extracted_text += f"\n--- Page {page_num + 1} ---\n"
#                     extracted_text += page_text.strip()
#                     extracted_text += "\n"
#             except Exception as page_err:
#                 logger.warning(
#                     f"Could not extract text from page {page_num + 1}: {page_err}"
#                 )
#                 continue
#
#         if not extracted_text.strip():
#             logger.warning("No text could be extracted from PDF")
#             return "No readable text found in this PDF document."
#
#         # Clean up the extracted text
#         extracted_text = extracted_text.strip()
#
#         # Limit text size to avoid overwhelming the context
#         MAX_CHARS = 15000  # Increased limit for better summaries
#         if len(extracted_text) > MAX_CHARS:
#             extracted_text = (
#                 extracted_text[:MAX_CHARS] + "\n\n[Content truncated due to length...]"
#             )
#
#         logger.info(f"Successfully extracted {len(extracted_text)} characters from PDF")
#         return extracted_text
#
#     except ImportError as import_err:
#         logger.error(f"Missing required libraries for PDF extraction: {import_err}")
#         return "ERROR: PDF text extraction libraries not available"
#     except Exception as e:
#         logger.error(f"Error extracting text from PDF: {str(e)}", exc_info=True)
#         return f"ERROR: Failed to extract text from PDF: {str(e)}"

async def extract_text_from_pdf(sas_url: str) -> str:
    """DISABLED: Using native RAG from new index instead of PDF extraction workaround."""
    logger.info(f"📄 PDF text extraction disabled - using native RAG from index")
    return "PDF text extraction disabled - using native RAG content from search index."


# Foundry v2 init helpers moved to foundry_init.py (2026-04-25)
# get_model_deployment_name, get_agent_name, get_application_name_for_agent,
# get_search_index_name, get_search_connection_id_env, get_search_connection_name_env,
# fallback_publication_state, _normalize_search_index_name now live there.


def _build_lucy_function_list() -> List[Any]:
    """Thin adapter — delegates to lucy_core.tool_registry.build_lucy_function_list.

    Lazy-imports setup_handoff_functions to preserve prior import-error tolerance.
    """
    try:
        from user_functions import setup_handoff_functions as _setup_handoff
    except Exception as handoff_import_error:
        logger.warning(f"⚠️ Could not import setup_handoff_functions: {handoff_import_error}")
        _setup_handoff = None

    return _lucy_build_function_list(
        setup_dynamics_fn=setup_dynamics_functions,
        core_helpers=[
            generate_sas_url,
            render_pdf,
            get_current_datetime,
            execute_search_tool,
            extract_text_from_pdf_tool,
            analyze_pdf_content_tool,
        ],
        setup_handoff_fn=_setup_handoff,
    )


def _build_function_registry(functions: List[Any]) -> Dict[str, Any]:
    return _lucy_build_function_registry(functions)


def _toolset_signature(functions: List[Any]) -> str:
    return _lucy_toolset_signature(functions)


def _build_authenticated_state_items() -> List[Dict[str, Any]]:
    """Thin adapter — builds a LucySession from cl.user_session and delegates to lucy_core."""
    session = _LucySession(
        session_id="chainlit",
        authenticated=bool(cl.user_session.get("authenticated")),
        apex_id=cl.user_session.get("apex_id"),
        user_name=cl.user_session.get("user_name"),
        metadata={
            "pending_notice_request": bool(cl.user_session.get("pending_notice_request")),
            "pending_notice_request_text": cl.user_session.get("pending_notice_request_text") or "",
            "notice_lookup_status": cl.user_session.get("notice_lookup_status") or "",
            "notice_lookup_apex_id": cl.user_session.get("notice_lookup_apex_id") or "",
        },
    )
    return _lucy_build_authenticated_state_items(session)


async def _initialize_persistent_agent_v2():
    """Thin adapter — delegates Foundry v2 init to foundry_init.initialize_foundry_v2_agent
    and populates apex.py module globals from the returned context."""
    global project_client, openai_client, agent_registry, agent_name, agent_version, v2_function_registry

    if agent_name and agent_version and project_client and openai_client:
        return True

    function_list = _build_lucy_function_list()
    fn_registry = _build_function_registry(function_list)
    sig = _toolset_signature(function_list)

    context = await initialize_foundry_v2_agent(
        instructions=get_agent_instructions(),
        function_list=function_list,
        function_registry=fn_registry,
        toolset_signature=sig,
        prompt_hash=compute_prompt_hash(),
        existing_agent_registry=agent_registry,
    )

    project_client = context.project_client
    openai_client = context.openai_client
    agent_registry = context.agent_registry
    agent_name = context.agent_name
    agent_version = context.agent_version
    v2_function_registry = context.function_registry

    return True


def _extract_v2_function_calls(response) -> List[Dict[str, Any]]:
    return _lucy_extract_v2_function_calls(response)


def _execute_v2_tool_call(name: str, arguments: str) -> str:
    return _lucy_execute_v2_tool_call(name, arguments, v2_function_registry)


async def _run_response_v2(user_text: str) -> Dict[str, Any]:
    """Thin adapter — initializes Foundry v2 globals, builds a LucySession from
    cl.user_session, delegates the Responses loop to lucy_core.responses_loop,
    and writes session state back to cl.user_session.
    """
    global agent_name, agent_version, openai_client

    await _initialize_persistent_agent_v2()
    if not openai_client or not agent_name or not agent_version:
        raise RuntimeError("Foundry v2 client not initialized")

    session = _LucySession(
        session_id="chainlit",
        conversation_id=cl.user_session.get("conversation_id"),
        previous_response_id=cl.user_session.get("previous_response_id"),
        last_eval_final_response_id=cl.user_session.get("last_eval_final_response_id"),
        authenticated=bool(cl.user_session.get("authenticated")),
        apex_id=cl.user_session.get("apex_id"),
        user_name=cl.user_session.get("user_name"),
        metadata={
            "pending_notice_request": bool(cl.user_session.get("pending_notice_request")),
            "pending_notice_request_text": cl.user_session.get("pending_notice_request_text") or "",
            "notice_lookup_status": cl.user_session.get("notice_lookup_status") or "",
            "notice_lookup_apex_id": cl.user_session.get("notice_lookup_apex_id") or "",
        },
    )

    result = await _lucy_run_response_v2(
        user_text=user_text,
        session=session,
        openai_client=openai_client,
        agent_name=agent_name,
        agent_version=agent_version,
        function_registry=v2_function_registry,
    )

    if session.conversation_id is not None:
        cl.user_session.set("conversation_id", session.conversation_id)
    if session.previous_response_id is not None:
        cl.user_session.set("previous_response_id", session.previous_response_id)
    if session.last_eval_final_response_id is not None:
        cl.user_session.set("last_eval_final_response_id", session.last_eval_final_response_id)
    for metadata_key in (
        "pending_notice_request",
        "pending_notice_request_text",
        "notice_lookup_status",
        "notice_lookup_apex_id",
        "notice_lookup_last_miss",
    ):
        if metadata_key in session.metadata:
            cl.user_session.set(metadata_key, session.metadata.get(metadata_key))

    return result

@azure_retry
@trace_function(name="agent.initialization")
async def initialize_persistent_agent():
    global persistent_agent, persistent_client, agents_client, vector_store

    if use_foundry_v2():
        return await _initialize_persistent_agent_v2()

    # Use lock to prevent race conditions during agent initialization
    with agent_init_lock:
        # Always reset persistent_agent to reload tool definitions
        persistent_agent = None
        logger.debug("[DEBUG] Starting initialize_persistent_agent()...")

        # Initialize tracing if not already done
        if TRACING_ENABLED and not tracing_config.azure_monitor_connection_string:
            logger.info("🔍 Attempting to initialize tracing configuration...")

        if persistent_agent is None:
            try:
                with trace_span("agent.initialization.setup") as span:
                    if span:
                        span.set_attribute("agent.initialization.start", True)
                    logger.info("Initializing AI Services client and agent...")

                # Get the AI Services endpoint (new Foundry approach)
                ai_services_endpoint = os.getenv("AZURE_AI_SERVICES_ENDPOINT")
                if not ai_services_endpoint:
                    logger.error("❌ AZURE_AI_SERVICES_ENDPOINT not set")
                    raise ValueError(
                        "AZURE_AI_SERVICES_ENDPOINT not set. Please set it to your"
                        "AI Services endpoint in the format: "
                        "https://your-ai-service-name.services.ai.azure.com"
                    )

                logger.debug("[DEBUG] Checking if running in container...")
                # Azure Container Apps sets CONTAINER_APP_NAME and CONTAINER_APP_REVISION
                # Also check for common container indicators
                is_container = any([
                    os.getenv("CONTAINER_APP_NAME"),
                    os.getenv("CONTAINER_APP_REVISION"),
                    os.getenv("WEBSITE_SITE_NAME"),
                    os.getenv("WEBSITES_PORT"),
                    os.getenv("KUBERNETES_SERVICE_HOST"),  # Common in container environments
                    os.path.exists("/.dockerenv")  # Docker container indicator
                ])

                if is_container:
                    logger.debug("[DEBUG] Setting up managed identity credential...")
                    from azure.identity import (
                        ManagedIdentityCredential,
                        ChainedTokenCredential,
                        EnvironmentCredential,
                    )

                    logger.info("Container environment detected. Using managed identity.")

                    # Get managed identity client ID with better error handling
                    managed_identity_client_id = os.getenv("MANAGED_IDENTITY_CLIENT_ID")
                    if managed_identity_client_id:
                        logger.info(f"Using managed identity with client ID: {managed_identity_client_id[:8]}...")
                        credential = ChainedTokenCredential(
                            ManagedIdentityCredential(client_id=managed_identity_client_id),
                            EnvironmentCredential(),
                        )
                    else:
                        logger.warning("MANAGED_IDENTITY_CLIENT_ID not set, using system-assigned identity")
                        # Try system-assigned identity first, then fall back to other methods
                        credential = ChainedTokenCredential(
                            ManagedIdentityCredential(),  # System-assigned identity
                            EnvironmentCredential(),
                            DefaultAzureCredential(exclude_interactive_browser_credential=True)
                        )
                else:
                    logger.info("Local environment detected. Using Azure CLI credentials.")
                    logger.debug(
                        "[DEBUG] Clearing any conflicting environment variables..."
                    )
                    for var in [
                        "AZURE_CLIENT_ID",
                        "AZURE_CLIENT_SECRET",
                        "AZURE_TENANT_ID",
                    ]:
                        if var in os.environ:
                            logger.debug(f"Clearing {var} to avoid conflicts")
                            del os.environ[var]
                    try:
                        import subprocess

                        logger.debug("[DEBUG] Checking Azure CLI login status...")
                        cli_user = (
                            subprocess.check_output(
                                [
                                    "az",
                                    "ad",
                                    "signed-in-user",
                                    "show",
                                    "--query",
                                    "objectId",
                                    "-o",
                                    "tsv",
                                ]
                            )
                            .decode()
                            .strip()
                        )
                        logger.info(f"Azure CLI user object ID: {cli_user}")
                    except Exception as e:
                        logger.warning(f"Could not retrieve CLI user ID: {str(e)}")

                    logger.debug("[DEBUG] Creating DefaultAzureCredential...")
                    credential = DefaultAzureCredential(
                        exclude_environment_credential=False,
                        exclude_managed_identity_credential=False,
                        exclude_interactive_browser_credential=False,
                        exclude_visual_studio_code_credential=False,
                        exclude_shared_token_cache_credential=False,
                        exclude_cli_credential=False,
                    )

                logger.debug("[DEBUG] Creating AgentsClient with AI Services endpoint...")

                # Check for the direct Foundry project endpoint first (preferred)
                project_endpoint = os.getenv("AZURE_AI_FOUNDRY_PROJECT_ENDPOINT")
                if project_endpoint:
                    logger.info(f"🚀 Using Foundry project endpoint: {project_endpoint}")
                else:
                    # Fallback: construct from AI Services endpoint and project name
                    ai_services_endpoint = os.getenv("AZURE_AI_SERVICES_ENDPOINT")
                    if not ai_services_endpoint:
                        logger.error(
                            "❌ Neither AZURE_AI_FOUNDRY_PROJECT_ENDPOINT nor AZURE_AI_SERVICES_ENDPOINT is set"
                        )
                        raise ValueError(
                            "Missing required endpoint. Please set either:\n"
                            "1. AZURE_AI_FOUNDRY_PROJECT_ENDPOINT (preferred), or\n"
                            "2. AZURE_AI_SERVICES_ENDPOINT + project name"
                        )

                    logger.info(f"🚀 Using AI Services endpoint: {ai_services_endpoint}")

                    # Extract project name from old connection string if available
                    project_name = os.getenv("AZURE_PROJECT_NAME")
                    if not project_name:
                        # Try to extract from old connection string format if it exists
                        old_conn_str = os.getenv("AZURE_PROJECT_CONNSTRING")
                        if old_conn_str and ";" in old_conn_str:
                            parts = old_conn_str.split(";")
                        if len(parts) >= 4:
                            project_name = parts[3]  # Last part is project name
                            logger.info(f"📋 Extracted project name: {project_name}")

                        # Final fallback
                        if not project_name:
                            project_name = "ai-az-agent-project-wus3"  # Updated fallback
                            logger.warning(f"⚠️ Using fallback project name: {project_name}")

                    # Construct the project-specific endpoint for agents
                    project_endpoint = f"{ai_services_endpoint}/api/projects/{project_name}"
                    logger.info(f"🔗 Constructed project endpoint: {project_endpoint}")

                # Create AgentsClient with the project endpoint only if import succeeded
                global agents_client
                if AgentsClient is not None:
                    try:
                        agents_client = AgentsClient(
                            endpoint=project_endpoint,
                            credential=credential,
                        )
                        logger.info(
                            "✅ Azure AI Agents client initialized with project endpoint"
                        )
                    except Exception as client_err:
                        logger.error(f"❌ Failed to initialize AgentsClient: {client_err}")
                        agents_client = None
                        raise RuntimeError(
                            f"Failed to initialize Azure AI Agents client: {client_err}"
                        )
                else:
                    logger.error("❌ AgentsClient is None - SDK import failed")
                    agents_client = None
                    raise RuntimeError(
                        "Azure AI Agents SDK not available - please install azure-ai-agents package"
                    )

                # Initialize tracing after agents client is created
                if TRACING_ENABLED:
                    try:
                        project_client_for_telemetry = None
                        if os.getenv("DISABLE_PROJECT_TELEMETRY", "true").lower() != "true":
                            try:
                                from azure.ai.projects import AIProjectClient
                                project_client_for_telemetry = AIProjectClient(
                                    endpoint=ai_services_endpoint,
                                    credential=credential,
                                    project_name=project_name if 'project_name' in locals() else None
                                )
                                logger.info("✅ Created AIProjectClient for telemetry")
                            except Exception as telemetry_err:
                                logger.warning(f"Could not create AIProjectClient for telemetry: {telemetry_err}")
                        else:
                            logger.info("⏭️ Skipping AIProjectClient telemetry probe (disabled)")

                        # Initialize tracing configuration
                        if tracing_config.initialize(project_client_for_telemetry):
                            logger.info("✅ Tracing initialized successfully")
                            with trace_span("agent.initialization.tracing") as span:
                                if span:
                                    span.set_attribute("tracing.initialized", True)
                                    span.set_attribute("tracing.service_name", tracing_config.service_name)
                                    span.set_attribute("tracing.environment", tracing_config.environment)
                        else:
                            logger.warning("⚠️ Tracing initialization failed")
                    except Exception as trace_err:
                        logger.error(f"❌ Error initializing tracing: {trace_err}")

                # For backward compatibility, create a minimal project client if needed
                # This is primarily for any legacy operations that might still need it
                try:
                    # Try to create a basic project client for compatibility
                    persistent_client = (
                        None  # Set to None since we're using direct AgentsClient
                    )
                    logger.info("✅ Using direct AgentsClient (no project client needed)")
                except Exception as project_err:
                    logger.warning(f"Could not create project client: {project_err}")
                    logger.info("Proceeding with AgentsClient only")

                # Cleanup only truly old agents to avoid stale FunctionTool registrations
                try:
                    logger.debug("[DEBUG] Cleaning up old agents...")
                    listing = agents_client.list_agents()
                    old_agents = getattr(listing, "data", listing)
                    current_time = time.time()

                    for old in old_agents:
                        agent_id = old if isinstance(old, str) else getattr(old, "id", None)
                        if not agent_id:
                            continue

                        # Only delete agents older than 30 minutes to avoid conflicts with active sessions
                        try:
                            agent_created_at = getattr(old, "created_at", None)
                            if agent_created_at:
                                # Convert to timestamp if needed
                                if hasattr(agent_created_at, 'timestamp'):
                                    created_timestamp = agent_created_at.timestamp()
                                else:
                                    created_timestamp = agent_created_at

                                # Only delete if older than 30 minutes (1800 seconds)
                                if current_time - created_timestamp < 1800:
                                    logger.debug(f"Skipping recent agent {agent_id} (created {current_time - created_timestamp:.0f}s ago)")
                                    continue

                            agents_client.delete_agent(agent_id)
                            logger.info(f"🧹 Deleted old agent: {agent_id}")
                        except Exception as ie:
                            # Silently handle 404s (agent already deleted) but log other errors
                            if "No assistant found" not in str(ie) and "404" not in str(ie):
                                logger.warning(f"Could not delete agent {agent_id}: {ie}")
                except Exception as ce:
                    logger.warning(f"Failed to cleanup old agents: {ce}")

                logger.debug("[DEBUG] Creating vector store...")
                vector_store = agents_client.vector_stores.create_and_poll(
                    file_ids=[], name="class_action_notices"
                )
                logger.info(f"✅ Created vector store, ID: {vector_store.id}")

                # --- Azure AI Search Tool Setup ---
                logger.debug("[DEBUG] Setting up Azure AI Search Tool...")
                ai_search_tool = None
                try:
                    # Try Foundry connection approach first
                    search_conn_id = os.getenv("AI_AZURE_AI_CONNECTION_ID")
                    search_index_name = os.getenv("AZURE_SEARCH_INDEX_NAME")

                    if search_conn_id and search_index_name:
                        # Azure AI Foundry connection approach
                        if AzureAISearchTool and AzureAISearchQueryType:
                            ai_search_tool = AzureAISearchTool(
                                index_connection_id=search_conn_id,
                                index_name=search_index_name,
                                query_type=AzureAISearchQueryType.VECTOR_SEMANTIC_HYBRID,
                                top_k=5,
                                filter="",
                            )
                            logger.info(
                                f"✅ Azure AI Search tool configured via Foundry connection: "
                                f"{search_index_name} with connection: {search_conn_id}"
                            )
                        else:
                            logger.warning(
                                "⚠️ AzureAISearchTool or AzureAISearchQueryType not available"
                            )
                    else:
                        # Try direct API approach as fallback
                        search_endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
                        search_api_key = os.getenv("AZURE_SEARCH_API_KEY")
                        search_index_name = os.getenv("AZURE_SEARCH_INDEX_NAME")

                        if search_endpoint and search_api_key and search_index_name:
                            logger.info(
                                f"🔍 Using direct Azure AI Search API approach for index: "
                                f"{search_index_name}"
                            )
                            # Note: For direct API, we'll implement search differently
                            # The AzureAISearchTool is designed for Foundry connections
                            # We'll handle direct API calls in the execute_search function
                            logger.info(
                                "✅ Direct Azure AI Search configuration detected - "
                                "will use custom implementation"
                            )
                        else:
                            logger.warning(
                                "⚠️ Neither Foundry connection nor direct API credentials found. "
                                "Need either AI_AZURE_AI_CONNECTION_ID or "
                                "(AZURE_SEARCH_ENDPOINT + AZURE_SEARCH_API_KEY + AZURE_SEARCH_INDEX_NAME)"
                            )
                except Exception as search_err:
                    logger.warning(f"⚠️ Could not setup Azure AI Search tool: {search_err}")
                    ai_search_tool = None

                # --- File Search Tool ---
                logger.debug("[DEBUG] Creating file_search_tool...")
                if FileSearchTool is None:
                    logger.error("❌ FileSearchTool not available - imports failed")
                    raise ImportError("Cannot import FileSearchTool")

                file_search_tool = FileSearchTool(vector_store_ids=[vector_store.id])

                # --- Function Tool ---
                logger.debug("[DEBUG] Setting up Function Tool...")
                all_functions = setup_dynamics_functions() + [
                    generate_sas_url,
                    render_pdf,
                    get_current_datetime,
                    execute_search_tool,  # Re-added for direct Azure AI Search support
                    extract_text_from_pdf_tool,
                    analyze_pdf_content_tool,  # Add dedicated PDF analysis tool
                ]

                # Add handoff/human-in-the-loop tools so the model can initiate live transfers
                try:
                    from user_functions import setup_handoff_functions
                    all_functions += setup_handoff_functions()
                    logger.info("✅ Added handoff functions to toolset")
                except Exception as handoff_import_error:
                    logger.warning(f"⚠️ Could not add handoff functions: {handoff_import_error}")

                if FunctionTool is None:
                    logger.error("❌ FunctionTool not available - imports failed")
                    raise ImportError("Cannot import FunctionTool")

                function_tool = FunctionTool(functions=set(all_functions))

                # --- ToolSet ---
                logger.debug("[DEBUG] Creating toolset...")
                if ToolSet is None:
                    logger.error("❌ ToolSet not available - imports failed")
                    raise ImportError("Cannot import ToolSet")

                toolset = ToolSet()
                toolset.add(file_search_tool)
                toolset.add(function_tool)

                # Add Azure AI Search tool if available
                if ai_search_tool:
                    toolset.add(ai_search_tool)
                    logger.info("✅ Added Azure AI Search tool to toolset")

                # --- Create Agent (simplified with ToolSet) ---
                logger.debug("[DEBUG] Creating persistent agent...")

                logger.info(f"Creating agent with model: {azure_gpt_model}")

                try:
                    with trace_span("agent.create", **{
                        LucyAttributes.AGENT_TYPE: "persistent",
                        LucyAttributes.MODEL_NAME: azure_gpt_model,
                        "tool.count": len(toolset.definitions) if hasattr(toolset, 'definitions') else 0
                    }) as span:
                        # Preferred: supply the fully-prepared ToolSet directly
                        persistent_agent = agents_client.create_agent(
                            model=azure_gpt_model,  # deployment name
                            name="Lucy Assistant",
                            instructions=get_agent_instructions(),
                            toolset=toolset,
                        )

                        if span and persistent_agent:
                            span.set_attribute(LucyAttributes.AGENT_ID, persistent_agent.id)
                            span.set_attribute(LucyAttributes.AGENT_VERSION, tracing_config.service_version)

                except Exception as agent_error:
                    logger.error(
                        f"❌ Failed to create agent with ToolSet: {agent_error}",
                        exc_info=True,
                    )
                    if span:
                        span.set_status(Status(StatusCode.ERROR, str(agent_error)))
                        span.record_exception(agent_error)
                    raise

                logger.info(f"✅ Persistent agent created with ID: {persistent_agent.id}")

                # Record agent creation metric
                if TRACING_ENABLED:
                    record_metric("agent.created", 1, "count", **{
                        "agent.type": "persistent",
                        "model": azure_gpt_model
                    })

                # Ensure the service will automatically execute function calls defined in our ToolSet
                try:
                    logger.debug("[DEBUG] Enabling auto function calls...")
                    agents_client.enable_auto_function_calls(toolset)
                    logger.info("✅ Auto function call handling enabled for agent runs")
                except Exception as auto_exc:
                    logger.error(f"Could not enable auto function calls: {auto_exc}")

                # Initialization successful – exit the function
                    return True
            except Exception as e:
                logger.error(
                    f"❌ Error initializing persistent agent: {str(e)}", exc_info=True
                )
                raise


def monitor_agent_run(client, thread_id: str, run_id: str) -> Dict[str, int]:
    """Monitor an agent run and track tool usage."""
    tool_usage = {
        "azure_ai_search": 0,
        "file_search": 0,
        "code_interpreter": 0,
        "functions": 0,
    }
    try:
        run = client.agents.retrieve_run(thread_id=thread_id, run_id=run_id)
        if hasattr(run, "tool_calls"):
            for call in run.tool_calls:
                tool_type = call.get("type", "").lower()
                if "search" in tool_type:
                    tool_usage["azure_ai_search"] += 1
                elif "file" in tool_type:
                    tool_usage["file_search"] += 1
                elif "code" in tool_type:
                    tool_usage["code_interpreter"] += 1
                elif "function" in tool_type:
                    tool_usage["functions"] += 1
        logger.debug(f"Tool usage: {tool_usage}")
    except Exception as e:
        logger.error(f"❌ Error monitoring agent run: {str(e)}")
    return tool_usage


# --- PDF SAS URL and Chainlit Inline PDF Preview ---
async def send_pdf_notice(sas_url: str):
    """Send a PDF notice to the user with inline preview."""
    # 1. Send the container message
    msg = cl.Message(
        content=(
            "Here is your **Class Action Notice**. You can view it below "
            "or download it."
        ),
        author="Lucy",
    )
    await msg.send()

    # 2. Attach the PDF element
    pdf_el = cl.Pdf(name="Class Action Notice", url=sas_url, display="side", page=1)  # type: ignore
    await pdf_el.send(for_id=msg.id)
    logger.info("✅ PDF element sent in separate message")


# Register shutdown cleanup
def _cleanup():
    logger.info("Shutting down Azure SDK clients...")
    try:
        if persistent_client:
            persistent_client.close()
            logger.info("AIProjectClient closed successfully")
    except Exception as e:
        logger.error(f"Error closing AIProjectClient: {e}")

    # Clean up telemetry context gracefully to prevent detachment errors
    try:
        import gc
        import asyncio

        # Cancel any pending tasks
        try:
            loop = asyncio.get_event_loop()
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
        except Exception:
            pass

        gc.collect()  # Force garbage collection to cleanup any remaining context objects
    except Exception as gc_error:
        logger.debug(f"Error during garbage collection cleanup: {gc_error}")


atexit.register(_cleanup)


# --- PDF Rendering Tool ---
def render_pdf(sas_url: str, *, display: str = "side") -> str:
    """Return a placeholder string that marks the PDF for in‑app preview."""
    # Check input parameters and handle errors properly
    try:
        if not sas_url or not isinstance(sas_url, str):
            return json.dumps({"error": "Invalid SAS URL provided"})

        if display not in ["side", "inline", "page"]:
            display = "side"  # Default to side if invalid display mode

        logger.info(f"[Lucy] Embedding PDF marker for SAS URL: {sas_url[:80]}...")

        # Extract the ApexID from the SAS URL for proper naming
        apex_id = extract_filename_from_sas_url(sas_url)
        _record_pending_pdf(sas_url, apex_id, display=display)

        # Human‑readable sentence + marker the UI logic will replace
        marker = (
            f"<<PDF_RENDER_MARKER_BEGIN|{sas_url}|{display}|PDF_RENDER_MARKER_END>>"
        )
        result = (
            f"I found your notice! You can view your Notice letter right now:\n\n"
            f"• Click {apex_id} to view it in the sidebar, or\n"
            f"• [Download {apex_id} directly]({sas_url})\n\n{marker}"
        )
        return result
    except Exception as e:
        logger.error(f"Error in render_pdf: {e}")
        return json.dumps({"error": str(e)})


async def send_pdf_directly(thinking_msg: cl.Message, url: str, display: str = "side"):
    """Directly append a PDF element to an existing message."""
    try:
        # Extract the actual filename from the URL
        pdf_name = extract_filename_from_sas_url(url)

        pdf_element = cl.Pdf(name=pdf_name, display=display, url=url, page=1)  # type: ignore
        # Append to message elements
        thinking_msg.elements.append(pdf_element)
        await thinking_msg.update()
        logger.info(f"✅ PDF element directly added to message with name: {pdf_name}")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to directly add PDF: {str(e)}", exc_info=True)
        return False


async def _send_v2_response_with_pdf(
    assistant_response: str,
    animation_task: asyncio.Task,
    *,
    turn_id: str,
    conversation_id: Optional[str] = None,
):
    """Send v2 response with PDF marker handling and pending PDF fallback."""
    clean_response = clean_handoff_json_from_response(assistant_response or "")
    if not clean_response:
        animation_task.cancel()
        try:
            await animation_task
        except asyncio.CancelledError:
            pass
        fallback_msg = cl.Message(
            content="I processed your request, but didn't generate a response. Please try rephrasing your question.",
            author="Lucy",
        )
        await fallback_msg.send()
        record_v2_assistant_history(fallback_msg.content)
        return

    pdf_sent = False
    thread_id = conversation_id or ""

    # Handle structured PDF_DISPLAY_INFO
    if "**PDF_DISPLAY_INFO:**" in clean_response:
        try:
            pdf_url_match = re.search(r"- PDF_URL: (.+)", clean_response)
            pdf_name_match = re.search(r"- PDF_NAME: (.+)", clean_response)
            display_mode_match = re.search(r"- DISPLAY_MODE: (.+)", clean_response)
            if pdf_url_match and pdf_name_match and display_mode_match:
                pdf_url = pdf_url_match.group(1).strip()
                pdf_name = _normalize_pdf_display_name(pdf_name_match.group(1).strip())
                element_name = "Notice PDF"
                display_mode = display_mode_match.group(1).strip()
                clean_response = re.sub(
                    r"\*\*PDF_DISPLAY_INFO:\*\*\n- PDF_URL: .+\n- PDF_NAME: .+\n- DISPLAY_MODE: .+",
                    "",
                    clean_response,
                ).strip()

                animation_task.cancel()
                try:
                    await animation_task
                except asyncio.CancelledError:
                    pass

                response_content = clean_response
                if element_name not in response_content:
                    response_content = (
                        response_content
                        + f"\n\n📄 {element_name}\n"
                        + f"[Download {pdf_name}]({pdf_url})"
                    )
                _log_link_debug(
                    "v2_pdf_display_info_send",
                    content=response_content,
                    pdf_url=pdf_url,
                    pdf_name=pdf_name,
                    thread_id=thread_id,
                    turn_id=turn_id,
                )
                response_msg = cl.Message(content=response_content, author="Lucy")
                await response_msg.send()
                record_v2_assistant_history(response_msg.content)
                pdf_element = cl.Pdf(
                    name=element_name,
                    display=display_mode,  # type: ignore
                    url=pdf_url,
                    page=1,
                )
                await pdf_element.send(for_id=response_msg.id)
                if display_mode == "side":
                    try:
                        await cl.ElementSidebar.set_title(f"📄 {pdf_name}")
                        await cl.ElementSidebar.set_elements([pdf_element])
                    except Exception as sidebar_err:
                        logger.warning("⚠️ Failed to open PDF in sidebar: %s", sidebar_err)
                pdf_sent = True
                cl.user_session.set("pending_pdf", None)
                return
        except Exception as pdf_err:
            logger.error("❌ Error processing v2 PDF_DISPLAY_INFO: %s", pdf_err, exc_info=True)

    # Handle PDF marker payload
    if "<<PDF_RENDER_MARKER_BEGIN|" in clean_response:
        try:
            pattern = r"<<PDF_RENDER_MARKER_BEGIN\\|([^|]+)\\|([^|]+)\\|PDF_RENDER_MARKER_END>>"
            match = re.search(pattern, clean_response)
            if match:
                pdf_url = match.group(1)
                display_mode = match.group(2)
                clean_response = re.sub(pattern, "", clean_response).strip()
                pdf_name = _normalize_pdf_display_name(extract_filename_from_sas_url(pdf_url))
                element_name = "Notice PDF"
                valid_display = display_mode if display_mode in ["side", "inline", "page"] else "side"

                animation_task.cancel()
                try:
                    await animation_task
                except asyncio.CancelledError:
                    pass

                local_pdf_path = await download_pdf_locally(pdf_url, pdf_name)
                if local_pdf_path:
                    pdf_el = cl.Pdf(
                        name=element_name,
                        display=valid_display,  # type: ignore
                        path=local_pdf_path,
                        page=1,
                    )
                else:
                    pdf_el = cl.Pdf(
                        name=element_name,
                        display=valid_display,  # type: ignore
                        url=pdf_url,
                        page=1,
                    )

                response_content = (
                    clean_response
                    + f"\n\n📄 {element_name}\n"
                    + f"[Download {pdf_name}]({pdf_url})"
                )
                _log_link_debug(
                    "v2_pdf_marker_send",
                    content=response_content,
                    pdf_url=pdf_url,
                    pdf_name=pdf_name,
                    thread_id=thread_id,
                    turn_id=turn_id,
                )
                response_msg = cl.Message(content=response_content, author="Lucy")
                await response_msg.send()
                record_v2_assistant_history(response_msg.content)
                await pdf_el.send(for_id=response_msg.id)
                if valid_display == "side":
                    try:
                        await cl.ElementSidebar.set_title(f"📄 {pdf_name}")
                        await cl.ElementSidebar.set_elements([pdf_el])
                    except Exception as sidebar_err:
                        logger.warning("⚠️ Failed to open PDF in sidebar: %s", sidebar_err)
                pdf_sent = True
                cl.user_session.set("pending_pdf", None)
                return
        except Exception as pdf_err:
            logger.error("❌ Error processing v2 PDF marker: %s", pdf_err, exc_info=True)

    # Default response path (no PDF markers)
    animation_task.cancel()
    try:
        await animation_task
    except asyncio.CancelledError:
        pass

    response_msg = cl.Message(content=clean_response, author="Lucy")
    await response_msg.send()
    record_v2_assistant_history(response_msg.content)

    pending_pdf = _pop_pending_pdf()
    if pending_pdf and not pdf_sent:
        try:
            pdf_url = pending_pdf.get("url")
            pdf_name = _normalize_pdf_display_name(pending_pdf.get("name") or "Class Action Notice")
            display_mode = pending_pdf.get("display") or "side"
            element_name = "Notice PDF"
            pdf_el = cl.Pdf(
                name=element_name,
                display=display_mode,  # type: ignore
                url=pdf_url,
                page=1,
            )
            await pdf_el.send(for_id=response_msg.id)
            if display_mode == "side":
                try:
                    await cl.ElementSidebar.set_title(f"📄 {pdf_name}")
                    await cl.ElementSidebar.set_elements([pdf_el])
                except Exception as sidebar_err:
                    logger.warning("⚠️ Failed to open PDF in sidebar: %s", sidebar_err)
        except Exception as pending_err:
            logger.warning("⚠️ Failed to attach pending PDF: %s", pending_err)


async def _process_handoff_after_response(
    assistant_response: Optional[str],
    handoff_tool_payload: Optional[dict],
    message_content: str,
):
    """Parse handoff markers/tool output and establish bridge if needed."""
    if assistant_response:
        try:
            conversation_id: Optional[str] = None
            handoff_agent_name: str = "Agent"
            portal_url: str = os.getenv("AGENT_PORTAL_URL", "http://localhost:8001")
            handoff_allowed = True

            import re

            handoff_data_from_tool = None
            try:
                if handoff_tool_payload:
                    output_str = "".join(handoff_tool_payload.get("outputs", []))
                    if output_str:
                        handoff_data_from_tool = json.loads(output_str)
                        if handoff_data_from_tool.get("establish_bridge"):
                            handoff_allowed = True
            except Exception as e:
                logger.warning(f"⚠️ Error parsing handoff tool output JSON: {e}")

            json_pattern = r'\\{[^{}]*\"establish_bridge\"[^{}]*\\}'
            json_matches = re.findall(json_pattern, assistant_response, re.DOTALL)

            handoff_found = False
            if handoff_data_from_tool and handoff_data_from_tool.get("success") and handoff_allowed:
                logger.info(f"🔍 Using handoff data from tool output: {handoff_data_from_tool}")

                conversation_id = handoff_data_from_tool.get("handoff_id") or handoff_data_from_tool.get("conversation_id")
                handoff_agent_name = handoff_data_from_tool.get("agent_name", "Agent")
                portal_url = handoff_data_from_tool.get("portal_url", os.getenv("AGENT_PORTAL_URL", "http://localhost:8001"))
                tool_apex_id = (handoff_data_from_tool.get("apex_id") or "").strip()
                if tool_apex_id and tool_apex_id.upper() not in {"UNKNOWN", "N/A"}:
                    try:
                        cl.user_session.set("apex_id", normalize_apex_id(tool_apex_id))
                        logger.info(f"✅ Stored apex_id from tool output: {tool_apex_id}")
                    except Exception as apex_store_error:
                        logger.warning(f"⚠️ Unable to store apex_id from tool output: {apex_store_error}")

                if conversation_id:
                    pending_handoff_info = {
                        "conversation_id": conversation_id,
                        "agent_name": handoff_agent_name,
                        "portal_url": portal_url,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "source": "tool_output",
                    }

                    cl.user_session.set("handoff_reason", message_content[:200])
                    cl.user_session.set("pending_handoff", pending_handoff_info)
                    logger.info(f"✅ Stored handoff info in session from tool output: {conversation_id}")
                    handoff_found = True

            for json_match in json_matches:
                try:
                    handoff_data = json.loads(json_match)
                    if handoff_data.get("success") and handoff_allowed:
                        logger.info(f"🔍 Found handoff info in assistant response: {handoff_data}")

                        conversation_id = handoff_data.get("handoff_id") or handoff_data.get("conversation_id")
                        handoff_agent_name = handoff_data.get("agent_name", "Agent")
                        portal_url = handoff_data.get("portal_url", os.getenv("AGENT_PORTAL_URL", "http://localhost:8001"))
                        response_apex_id = (handoff_data.get("apex_id") or "").strip()
                        if response_apex_id and response_apex_id.upper() not in {"UNKNOWN", "N/A"}:
                            try:
                                cl.user_session.set("apex_id", normalize_apex_id(response_apex_id))
                                logger.info(f"✅ Stored apex_id from assistant response: {response_apex_id}")
                            except Exception as apex_store_error:
                                logger.warning(f"⚠️ Unable to store apex_id from assistant response: {apex_store_error}")

                        if conversation_id:
                            pending_handoff_info = {
                                "conversation_id": conversation_id,
                                "agent_name": handoff_agent_name,
                                "portal_url": portal_url,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            }

                            cl.user_session.set("handoff_reason", message_content[:200])
                            cl.user_session.set("pending_handoff", pending_handoff_info)
                            logger.info(f"✅ Stored handoff info in session for bridge establishment: {conversation_id}")
                            handoff_found = True
                            break
                except json.JSONDecodeError:
                    continue

            if not handoff_found:
                cl.user_session.set("pending_handoff", None)
                logger.info("ℹ️ No handoff markers found; cleared pending_handoff")

            if not handoff_found and not cl.user_session.get("pending_handoff"):
                try:
                    from user_functions import consume_recent_handoff
                    apex_id = cl.user_session.get("apex_id")
                    cached = consume_recent_handoff(apex_id=apex_id, max_age_seconds=600)
                    if cached:
                        conversation_id = cached.get("handoff_id") or cached.get("conversation_id")
                        portal_url = cached.get("portal_url") or os.getenv("AGENT_PORTAL_URL", "http://localhost:8001")
                        handoff_agent_name = cached.get("agent_name", "Agent")
                        if conversation_id:
                            pending_handoff_info = {
                                "conversation_id": conversation_id,
                                "agent_name": handoff_agent_name,
                                "portal_url": portal_url,
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                                "source": "recent_cache",
                            }
                            cl.user_session.set("handoff_reason", message_content[:200])
                            cl.user_session.set("pending_handoff", pending_handoff_info)
                            logger.info(f"✅ Restored handoff from recent cache: {conversation_id}")
                except Exception as cache_err:
                    logger.warning(f"⚠️ Unable to consume recent handoff cache: {cache_err}")

        except Exception as handoff_parse_error:
            logger.warning(f"⚠️ Error parsing handoff information from response: {handoff_parse_error}")

    try:
        pending_handoff = cl.user_session.get("pending_handoff")
        if pending_handoff and not cl.user_session.get("active_handoff_conversation_id"):
            conversation_id = pending_handoff.get("conversation_id")
            handoff_agent_name = pending_handoff.get("agent_name", "Agent")
            portal_url = pending_handoff.get("portal_url", os.getenv("AGENT_PORTAL_URL", "http://localhost:8001"))
            logger.info(f"🌉 Establishing WebSocket bridge for handoff {conversation_id}")

            history_stored = await store_conversation_history_for_handoff(conversation_id)
            if not history_stored:
                logger.warning("⚠️ Conversation history persistence failed prior to bridge setup")

            bridge_success = await websocket_bridge.start_bridge(conversation_id, portal_url)

            if bridge_success:
                cl.user_session.set("active_handoff_conversation_id", conversation_id)
                cl.user_session.set("handoff_agent_name", handoff_agent_name)

                cl.user_session.set("pending_handoff", None)
                cl.user_session.set("user_requested_handoff", False)

                asyncio.create_task(notify_user_of_pending_messages(conversation_id))
                logger.info(f"🔄 Started message queue monitor for conversation {conversation_id}")
                logger.info(f"✅ WebSocket bridge established successfully for {conversation_id}")
                asyncio.create_task(monitor_agent_response_timeout(conversation_id, handoff_agent_name))
            else:
                logger.error(f"❌ Failed to establish WebSocket bridge for {conversation_id}")
    except Exception as bridge_error:
        logger.error(f"❌ Error establishing WebSocket bridge: {str(bridge_error)}")

def get_current_datetime() -> str:
    """Return current date/time information as a JSON string."""
    now = datetime.now(timezone.utc)
    eastern = now.astimezone(timezone(timedelta(hours=-4)))
    data = {
        "iso": now.isoformat(),
        "utc": now.strftime("%A, %B %d, %Y at %I:%M %p UTC"),
        "eastern": eastern.strftime("%A, %B %d, %Y at %I:%M %p EST"),
    }
    # Convert the dictionary to a JSON string for tool output
    try:
        return json.dumps(data)
    except Exception as e:
        logger.error(f"Error serializing datetime data: {e}")
        return json.dumps({"error": str(e)})


# Load and enhance system prompt with current time
def load_system_prompt():
    """Load system prompt and enhance it with current datetime information."""
    with open("agent_instructions.txt", "r") as f:
        instructions = f.read()

    # Add current time context
    current_time_json = get_current_datetime()

    # Parse the JSON string back to a dictionary
    try:
        current_time = json.loads(current_time_json)
    except Exception as e:
        logger.error(f"Error parsing datetime JSON: {e}")
        # Fallback if parsing fails
        now = datetime.now(timezone.utc)
        current_time = {
            "utc": now.strftime("%A, %B %d, %Y at %I:%M %p UTC"),
            "eastern": now.astimezone(timezone(timedelta(hours=-4))).strftime(
                "%A, %B %d, %Y at %I:%M %p EST"
            ),
        }

    time_context = (
        f"\nCURRENT TIME: Today is {current_time['utc']} / {current_time['eastern']}.\n"
    )
    time_context += (
        "Always consider this current date in your responses when discussing "
        "deadlines, timelines, or events.\n"
    )

    # Add time context near the beginning of the prompt
    if "\n\n" in instructions:
        parts = instructions.split("\n\n", 1)
        enhanced_instructions = parts[0] + "\n" + time_context + "\n" + parts[1]
    else:
        enhanced_instructions = instructions + "\n" + time_context

    logger.info(f"Added current time to system prompt: {current_time['utc']}")
    return enhanced_instructions


async def refresh_time_awareness(thread_id: str):
    """Refresh Lucy's awareness of the current time during long sessions."""
    try:
        # Check if agents_client is properly initialized
        if agents_client is None or not hasattr(agents_client, "messages"):
            logger.error(
                "❌ agents_client is None or missing 'messages' attribute - cannot refresh time awareness"
            )
            return False

        try:
            messages = agents_client.messages.list(thread_id=thread_id)
            messages_list = list(messages) if messages else []
        except Exception as list_err:
            logger.warning(f"⚠️ Failed to list messages for time refresh: {list_err}")
            return False
        if len(messages_list) < 2:
            return False

        # Find the most recent system message with time information
        latest_time_msg = None
        for msg in messages_list:
            if msg.role == "assistant" and "CURRENT TIME:" in str(msg.content):
                latest_time_msg = msg
                break

        # If no time message found or message is old (30+ minutes), refresh
        current_time = datetime.now(timezone.utc)
        should_refresh = False

        if not latest_time_msg:
            should_refresh = True
        elif hasattr(latest_time_msg, "created_at"):
            # Calculate time difference
            msg_time = latest_time_msg.created_at
            if isinstance(msg_time, str):
                msg_time = datetime.fromisoformat(msg_time.replace("Z", "+00:00"))
            time_diff = current_time - msg_time
            if time_diff.total_seconds() > 1800:  # 30 minutes
                should_refresh = True

        if should_refresh:
            time_info = get_current_datetime()
            # Parse the time_info JSON string
            time_data = json.loads(time_info)
            time_message = (
                f"SYSTEM UPDATE: The current time is now "
                f"{time_data['utc']} / {time_data['eastern']}."
            )

            # Send a new system message with updated time
            if agents_client is None or not hasattr(agents_client, "messages"):
                logger.error(
                    "❌ agents_client is None or missing 'messages' attribute - cannot send time message"
                )
                return False

            agents_client.messages.create(
                thread_id=thread_id, role="assistant", content=time_message
            )
            logger.info(f"Refreshed time awareness: {time_message}")
            return True

        return False
    except Exception as e:
        logger.error(f"Error refreshing time awareness: {str(e)}")
        return False


def _extract_pdf_sas_from_search_results(raw_output):
    """Parse tool output and extract valid PDF SAS URLs."""

    import re as _re
    import json as _json

    pdf_sas_urls: list[str] = []

    # Helper: normalise blob path → SAS url
    def _build_sas_from_path(raw_path: str) -> str | None:
        raw_path = raw_path.lstrip("/")
        if not raw_path.lower().endswith(".pdf"):
            return None
        storage_account = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
        if not storage_account:
            return None
        # Keep the full path structure including folders
        blob_url = f"https://{storage_account}.blob.core.windows.net/{raw_path}"
        logger.debug(f"Building SAS URL from path: {blob_url}")

        # Generate SAS URL with enhanced error handling
        sas_url = generate_sas_url(blob_url)
        if sas_url and not sas_url.startswith("ERROR"):
            logger.info(
                f"Successfully generated SAS URL for path with length: {len(sas_url)}"
            )
            return sas_url
        else:
            logger.error(f"Failed to generate SAS URL for {blob_url}: {sas_url}")
            return None

    # Attempt JSON parse
    try:
        data = _json.loads(raw_output)
        docs: list = []
        if isinstance(data, list):
            docs = data
        elif isinstance(data, dict) and "data" in data:
            docs = data["data"]

        for doc in docs:
            if not isinstance(doc, dict):
                continue

            name = (doc.get("metadata_storage_name") or "").lower()
            path = doc.get("metadata_storage_path") or ""

            # Case A: explicit name + path
            if name.endswith(".pdf") and path.lower().endswith(".pdf"):
                sas = _build_sas_from_path(path)
                if sas and sas not in pdf_sas_urls:
                    pdf_sas_urls.append(sas)
                continue

            # Case B: parent_id base64 containing blob URL
            parent_id = doc.get("parent_id")
            if parent_id and isinstance(parent_id, str):
                try:
                    import base64 as _b64

                    padded = parent_id + "=="  # ensure padding
                    decoded = (
                        _b64.urlsafe_b64decode(padded).decode("utf-8", "ignore").strip()
                    )
                    if decoded.lower().startswith("http") and decoded.lower().endswith(
                        ".pdf"
                    ):
                        # If decoded URL already has SAS token, keep as-is
                        sas_url = (
                            decoded if "?" in decoded else generate_sas_url(decoded)
                        )
                        if sas_url and sas_url not in pdf_sas_urls:
                            pdf_sas_urls.append(sas_url)
                except Exception:
                    pass
    except Exception:
        # Not JSON or malformed – fall through to regex extraction
        pass

    # Regex scan for direct SAS URLs in plain-text output
    if not pdf_sas_urls:
        url_pattern = r"https?://[\w\-.]+/[^\s\)\]\"'>]+\.pdf[^\s\)\]\"'>]*"
        for m in _re.findall(url_pattern, raw_output):
            # Strip trailing markdown characters
            cleaned = m.rstrip("*)]>")  # remove right-hand delimiters
            if cleaned not in pdf_sas_urls:
                pdf_sas_urls.append(cleaned)

    return pdf_sas_urls


# Prevent blank queries
def _is_blank_search_input(data: Any) -> bool:
    if not data:
        return True
    if isinstance(data, dict):
        return not any(data.values())
    return False


# --- Safe thread creation helper ---
async def _safe_create_thread(max_retries: int = 2):
    """Create a new agent thread."""
    global persistent_client, agents_client

    logger.debug(
        f"[DEBUG] _safe_create_thread called with agents_client type: {type(agents_client)}"
    )

    if agents_client is None:
        logger.error("❌ agents_client is None - attempting to reinitialize")
        try:
            await initialize_persistent_agent()
            if agents_client is None:
                raise RuntimeError("Failed to initialize agents_client")
        except Exception as init_err:
            logger.error(f"❌ Re-initialization failed: {init_err}")
            raise RuntimeError(
                "Unable to create thread - agent client initialization failed"
            )

    logger.debug(
        f"[DEBUG] agents_client has threads attribute: {hasattr(agents_client, 'threads')}"
    )
    if hasattr(agents_client, "threads"):
        logger.debug(f"[DEBUG] threads type: {type(agents_client.threads)}")

    for attempt in range(max_retries + 1):
        try:
            # Updated for new azure-ai-agents SDK - use threads.create()
            if not hasattr(agents_client, "threads"):
                raise RuntimeError("agents_client missing 'threads' attribute")
            return agents_client.threads.create()
        except (ServiceResponseError, ClientAuthenticationError) as err:
            logging.warning(
                "Thread creation failed (attempt %s/%s): %s – refreshing client",
                attempt + 1,
                max_retries,
                err,
            )
            try:
                await initialize_persistent_agent()
            except Exception as init_err:
                logging.error("Re-initialisation failed: %s", init_err)
        except Exception as e:  # other unexpected errors propagate
            logger.error(f"❌ Unexpected error creating thread: {e}")
            raise
    raise RuntimeError("Unable to create thread after retries")


# Connectivity quick test
async def test_rag_connectivity():
    """Ping Azure AI Search once to verify connectivity."""
    try:
        sample_query = {"search_query": "class action notice"}
        results = await execute_search(sample_query)
        return bool(results)
    except Exception:
        return False


# Name & Query Helpers
def _pick_best_name(rec: dict) -> str:
    """Return the authoritative name string for a member record."""
    full = (rec.get("new_fullname") or "").strip()
    first = (rec.get("new_firstname") or "").strip()
    last = (rec.get("new_lastname") or "").strip()

    simple = f"{first} {last}".strip()

    if full and simple and full.lower() != simple.lower():
        return full
    return simple or full


def build_member_queries(rec: dict) -> list[str]:
    """Generate ordered RAG search queries as requested."""
    first = (rec.get("new_firstname") or "").strip()
    last = (rec.get("new_lastname") or "").strip()
    full = (rec.get("new_fullname") or "").strip()
    address = (rec.get("new_address") or "").strip()
    apex_id = (rec.get("new_apexid") or "").strip()

    # Full name considered distinct only if not equal to "first last"
    simple_full = f"{first} {last}".strip()
    has_distinct_full = bool(full) and (full.lower() != simple_full.lower())

    def _quoted(s: str) -> str:
        return f'"{s}"'

    queries: list[str] = []

    # ApexID only – highest precision, try this first if available
    if apex_id:
        queries.append(_quoted(apex_id))

    # First + Last + Address
    if first and last and address:
        queries.append(f"{_quoted(first)} AND {_quoted(last)} AND {_quoted(address)}")

    # Full + Address (only if distinct full exists)
    if has_distinct_full and address:
        queries.append(f"{_quoted(full)} AND {_quoted(address)}")

    # First + Last + ApexID
    if first and last and apex_id:
        queries.append(f"{_quoted(first)} AND {_quoted(last)} AND {_quoted(apex_id)}")

    # Full + ApexID
    if has_distinct_full and apex_id:
        queries.append(f"{_quoted(full)} AND {_quoted(apex_id)}")

    # Ensure uniqueness while preserving order
    seen = set()
    ordered_unique: list[str] = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            ordered_unique.append(q)

    return ordered_unique


# FunctionTool wrapper
def execute_search_tool(user_data: Any = None, *, func_tool=None) -> str:
    """Synchronous wrapper around execute_search for FunctionTool."""
    if _is_blank_search_input(user_data):
        # Do not trigger a broad "" search
        return "[]"

    if user_data is None:
        user_data = {}

    try:
        # If a loop is already running we cannot invoke asyncio.run
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    try:
        if running_loop and running_loop.is_running():
            temp_loop = asyncio.new_event_loop()
            try:
                result = temp_loop.run_until_complete(
                    execute_search(user_data, func_tool=func_tool)
                )
            finally:
                temp_loop.close()
        else:
            result = asyncio.run(execute_search(user_data, func_tool=func_tool))

        # Reduce payload size: retain only minimal fields needed downstream
        minimal: List[Dict] = []
        for doc in result:
            if not isinstance(doc, dict):
                continue
            minimal.append(
                {
                    "metadata_storage_name": doc.get("metadata_storage_name"),
                    "metadata_storage_path": doc.get("metadata_storage_path"),
                    "parent_id": doc.get("parent_id"),
                }
            )

        # FunctionTool expects a string payload → return JSON text
        try:
            return json.dumps(minimal, default=str)
        except Exception as json_err:
            logger.error(f"Failed to serialize search results: {json_err}")
            # Fallback to simple string representation if JSON fails
            return str(minimal)
    except Exception as e:
        logger.error(f"Error in execute_search_tool: {e}")
        return json.dumps({"error": str(e)})


async def search_notices(query: str) -> dict:
    """Search for notices using Azure AI Search."""
    logger.info(f"Searching for notices with query: {query}")

    try:
        # Use the existing execute_search function
        search_results = await execute_search({"search_query": query})

        if not search_results:
            logger.warning(f"No search results found for query: {query}")
            return {"results": []}

        # Transform the results into a more usable format
        formatted_results = []
        for result in search_results:
            # Extract key information from search results
            metadata = {
                "blob_url": result.get("metadata_storage_path", ""),
                "file_name": result.get("metadata_storage_name", ""),
                "content_type": (
                    "application/pdf"
                    if result.get("metadata_storage_name", "").lower().endswith(".pdf")
                    else "text/plain"
                ),
            }

            formatted_result = {
                "metadata": metadata,
                "content": result.get("chunk", ""),
                "id": str(uuid.uuid4()),
            }

            formatted_results.append(formatted_result)

        logger.info(f"Transformed {len(formatted_results)} search results")
        return {"results": formatted_results}

    except Exception as e:
        logger.error(f"Error in search_notices: {str(e)}", exc_info=True)
        return {"results": [], "error": str(e)}


def extract_text_from_pdf_tool(sas_url: str, *, func_tool=None) -> str:
    """Synchronous wrapper around extract_text_from_pdf for FunctionTool."""
    if not sas_url or not isinstance(sas_url, str):
        return "ERROR: Invalid SAS URL provided"

    try:
        # If a loop is already running we cannot invoke asyncio.run
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    try:
        if running_loop and running_loop.is_running():
            temp_loop = asyncio.new_event_loop()
            try:
                result = temp_loop.run_until_complete(extract_text_from_pdf(sas_url))
            finally:
                temp_loop.close()
        else:
            result = asyncio.run(extract_text_from_pdf(sas_url))

        # Ensure we're returning a string, not an object
        if result is None:
            return "No text extracted from PDF."
        elif isinstance(result, str):
            return result
        else:
            return str(result)
    except Exception as e:
        logger.error(f"Error in extract_text_from_pdf_tool: {e}")
        return f"ERROR: Failed to extract text from PDF: {str(e)}"


async def check_for_agent_presence(thread_id: str) -> bool:
    """Check if a human agent has joined this conversation thread."""
    if not AGENT_PORTAL_CONFIG["enabled"]:
        return False  # If agent portal integration is disabled

    try:
        # Add timeout to prevent hanging on unreachable network
        timeout = aiohttp.ClientTimeout(total=5, connect=2)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            portal_url = (
                f"{AGENT_PORTAL_CONFIG['url']}/api/conversations/{thread_id}/status"
            )
            async with session.get(portal_url) as response:
                if response.status == 200:
                    data = await response.json()
                    return data.get("agent_joined", False)
                else:
                    logger.warning(
                        f"Failed to check agent status: HTTP {response.status}"
                    )
                    return False
    except aiohttp.ClientConnectorError as e:
        logger.warning(f"Agent portal unreachable at {AGENT_PORTAL_CONFIG['url']}: {str(e)}")
        return False
    except asyncio.TimeoutError:
        logger.warning(f"Timeout connecting to agent portal at {AGENT_PORTAL_CONFIG['url']}")
        return False
    except Exception as e:
        logger.error(f"Error checking for agent presence: {str(e)}", exc_info=True)
        return False


# Add custom dashboard routes to Chainlit app
def setup_dashboard_routes():
    """Add dashboard routes to the main Chainlit FastAPI app"""
    dashboard_enabled = os.getenv(
        "LUCY_DASHBOARD_ROUTES_ENABLED",
        os.getenv("LUCY_CHAINLIT_ENABLED", "true"),
    ).lower() not in {"0", "false", "no", "off"}
    if not dashboard_enabled:
        logger.info("ℹ️ Dashboard routes disabled for this process")
        return

    try:
        from fastapi import Request
        from fastapi.responses import HTMLResponse, JSONResponse
        from fastapi.templating import Jinja2Templates
        import chainlit as cl

        # Get the FastAPI app instance from Chainlit
        app = cl.app

        # Setup templates
        templates = Jinja2Templates(directory="templates")

        @app.get("/dashboard", response_class=HTMLResponse)
        async def dashboard_route(request: Request):
            """Dashboard accessible from main app"""
            try:
                from real_metrics_system import get_live_dashboard_metrics

                # Get real metrics
                dashboard_data = await get_live_dashboard_metrics()

                context = {
                    "request": request,
                    "agent": {"name": "Dashboard User"},
                    "current_metrics": {
                        "session_summary": {
                            "total_attempts": dashboard_data["authentication"]["total_attempts"],
                            "successful_attempts": dashboard_data["authentication"]["successful_attempts"],
                            "success_rate": dashboard_data["authentication"]["success_rate"],
                            "avg_queries_per_attempt": dashboard_data["authentication"]["avg_queries_per_attempt"],
                            "learned_pattern_usage": dashboard_data["authentication"]["cache_hit_rate"]
                        }
                    },
                    "pending_count": dashboard_data["conversations"]["active_conversations"],
                    "teams_status": dashboard_data["teams"],
                    "system_metrics": dashboard_data["system"],
                    "conversation_metrics": dashboard_data["conversations"],
                    "callback_metrics": dashboard_data["callbacks"],
                    "recommendations": [
                        f"🎯 System performance: CPU {dashboard_data['system']['cpu_usage']:.1f}%, Memory {dashboard_data['system']['memory_usage']:.1f}%",
                        f"💬 {dashboard_data['conversations']['active_conversations']} active conversations",
                        f"📞 {dashboard_data['callbacks']['pending_callbacks']} pending callbacks",
                        f"🔗 Teams: {'✅ Connected' if dashboard_data['teams']['available'] else '⚠️ Check config'}"
                    ],
                    "historical_metrics": {
                        "overall_stats": {
                            "total_attempts": dashboard_data["authentication"]["total_attempts"],
                            "success_rate": dashboard_data["authentication"]["success_rate"],
                            "avg_queries_per_attempt": dashboard_data["authentication"]["avg_queries_per_attempt"],
                            "learning_cache_usage": dashboard_data["authentication"]["cache_hit_rate"]
                        }
                    },
                    "build_version": "1.2.0",
                    "callback_system_version": "2.0",
                    "error": None
                }

                return templates.TemplateResponse("dashboard.html", context)

            except Exception as e:
                logger.error(f"Dashboard error: {e}")
                # Return basic dashboard with error
                context = {
                    "request": request,
                    "agent": {"name": "Dashboard User"},
                    "error": f"Dashboard temporarily unavailable: {str(e)}",
                    "current_metrics": {"session_summary": {}},
                    "pending_count": 0,
                    "teams_status": {"available": False},
                    "recommendations": ["⚠️ Dashboard system initializing..."],
                    "historical_metrics": {},
                    "build_version": "1.2.0",
                    "callback_system_version": "2.0"
                }
                return templates.TemplateResponse("dashboard.html", context)

        @app.get("/api/dashboard/metrics")
        async def dashboard_metrics():
            """API endpoint for dashboard metrics"""
            try:
                from real_metrics_system import get_live_dashboard_metrics
                metrics = await get_live_dashboard_metrics()
                return JSONResponse(content={
                    "success": True,
                    "data": metrics,
                    "timestamp": datetime.utcnow().isoformat()
                })
            except Exception as e:
                return JSONResponse(content={
                    "success": False,
                    "error": str(e)
                }, status_code=500)

        logger.info("✅ Dashboard routes added to main Chainlit app")
        logger.info("📊 Dashboard URL: /dashboard")

    except Exception as e:
        logger.error(f"Failed to setup dashboard routes: {e}")

# Setup dashboard routes when module loads
setup_dashboard_routes()

# Start the Chainlit app when run directly
if __name__ == "__main__":
    from chainlit.cli import run_chainlit

    run_chainlit(__file__)


async def find_notice_for_user_DISABLED(user_profile):
    # DISABLED: This function was causing routing conflicts with find_notice_for_user_sync
    return "ERROR: This function has been disabled to prevent routing conflicts"

    # Helper to craft a friendly fallback message
    def _notice_not_found():
        person_name = _pick_best_name(user_profile) or "there"
        return (
            f"{person_name}, thanks for holding while I completed a thorough search. "
            "Unfortunately, I wasn't able to find a copy of your notice. This sometimes "
            "happens because there's a short delay between when a notice is mailed and "
            "when it becomes available in our system.\n\n"
            "**Here are a few ways I can still help:**\n"
            "1. If it isn't urgent, check back in about **two weeks**—the notice is usually online by then.\n"
            "2. Because you're already authenticated, I can still answer questions about your case, update your contact details, verify disbursements, and more.\n"
            "3. I can see if one of my human team-mates is available for a live transfer.\n"
            "4. I can arrange a call-back from one of our customer-service specialists within **24 hours**—just let me know the best number to reach you.\n\n"
            "Let me know which option works best for you, and I'll take it from there!"
        )

    # Build ordered list of queries using new helper
    queries = build_member_queries(user_profile)

    if not queries:
        logger.warning("[Lucy] No usable search criteria derived from user profile")
        return _notice_not_found()

    # Try each query in order
    for idx, query in enumerate(queries):
        logger.info(f"[Lucy] Azure AI Search query attempt {idx + 1}: {query}")
        try:
            # prepare search input with query override
            search_input = dict(user_profile)
            search_input["search_query"] = query
            logger.debug(f"[Lucy] RAG search input: {search_input}")
            # perform search asynchronously
            search_results = await execute_search(search_input)
        except Exception as e:
            logger.error(f"[Lucy] Azure AI Search failed on query '{query}': {e}")
            continue

        logger.info(
            f"[Lucy] Query '{query}' returned {len(search_results) if search_results else 0} results."
        )
        if search_results:
            # Filter to PDF documents only
            pdf_results = []
            for r in search_results:
                name_field = r.get("metadata_storage_name") or r.get("title") or ""
                path_field = r.get("metadata_storage_path") or r.get("parent_id") or ""
                if name_field.lower().endswith(".pdf") and path_field:
                    pdf_results.append(r)

            if not pdf_results:
                logger.info(
                    f"[Lucy] No PDF document found for query '{query}', skipping."
                )
                continue

            doc = pdf_results[0]
            logger.debug(f"[Lucy] RAG result metadata: {doc}")

            # Build the blob URL robustly – ignore metadata_storage_name (it is the file name, not account)
            storage_account = os.getenv("AZURE_STORAGE_ACCOUNT_NAME")
            if not storage_account:
                logger.error(
                    "AZURE_STORAGE_ACCOUNT_NAME not set – cannot generate blob URL"
                )
                return _notice_not_found()

            storage_path = doc.get("metadata_storage_path")
            raw_path = storage_path or ""
            for _ in range(2):
                raw_path = unquote(raw_path)
            if not raw_path:
                logger.error(
                    f"[Lucy] Missing metadata_storage_path in search result: {doc}"
                )

            if raw_path.lower().startswith("http"):
                blob_url = raw_path  # path already a full URL
            else:
                # Ensure container name present
                container_name = (
                    os.getenv("AZURE_STORAGE_CONTAINER_NAME")
                    or os.getenv("AZURE_STORAGE_CONTAINER")
                    or "lucyrag"
                )
                raw_path = raw_path.lstrip("/")
                if not raw_path.lower().startswith(f"{container_name.lower()}/"):
                    raw_path = f"{container_name}/{raw_path}"

                blob_url = f"https://{storage_account}.blob.core.windows.net/{raw_path}"
            logger.info(f"[Lucy] Constructed blob URL: {blob_url}")
            # Generate SAS URL
            sas_url = generate_sas_url(blob_url)
            if not sas_url or sas_url.startswith("ERROR") or "<sas_token>" in sas_url:
                logger.error(
                    "[Lucy] Failed to generate valid SAS URL – falling back to friendly response."
                )
                return _notice_not_found()
            logger.info(f"[Lucy] Generated SAS URL: {sas_url[:80]}...")
            # Check if this is a PDF document (check blob URL, not SAS URL with query params)
            is_pdf = blob_url.lower().endswith(".pdf") or doc.get(
                "metadata_storage_name", ""
            ).lower().endswith(".pdf")

            if is_pdf:
                try:
                    # Call render_pdf function to get the marker text
                    pdf_render_text = render_pdf(sas_url, display="side")

                    # Use native RAG content from new index instead of PDF extraction
                    logger.info("[Lucy] Using native RAG content from new index for summarization...")

                    # Collect ALL chunks related to this document from search results
                    storage_path_norm = storage_path or ""
                    apex_id = extract_filename_from_sas_url(sas_url)
                    related_chunks = []

                    # Strategy 1: Collect chunks with matching storage path
                    for r in search_results:
                        if (r.get("metadata_storage_path") or "") == storage_path_norm:
                            chunk_content = r.get("chunk", "").strip()
                            if chunk_content:
                                related_chunks.append(chunk_content)

                    # Strategy 2: If no path matches, collect by filename/ApexID
                    if not related_chunks and apex_id:
                        for r in search_results:
                            storage_name = r.get("metadata_storage_name", "")
                            if apex_id.replace(".pdf", "") in storage_name or storage_name.startswith(apex_id.replace(".pdf", "")):
                                chunk_content = r.get("chunk", "").strip()
                                if chunk_content:
                                    related_chunks.append(chunk_content)

                    # Strategy 3: If still no chunks, use all available chunks (fallback)
                    if not related_chunks and search_results:
                        for r in search_results:
                            chunk_content = r.get("chunk", "").strip()
                            if chunk_content:
                                related_chunks.append(chunk_content)

                    logger.info(f"[Lucy] Collected {len(related_chunks)} total chunks for document analysis")

                    if related_chunks:
                        # Collect ALL chunks related to this document for comprehensive analysis
                        full_rag_content = "\n\n".join(related_chunks)
                        logger.info(f"[Lucy] Collected {len(related_chunks)} chunks with {len(full_rag_content)} characters of RAG content for comprehensive analysis")

                        # Extract ApexID for proper naming
                        apex_id = extract_filename_from_sas_url(sas_url)

                        # Return comprehensive response with PDF display and instructions for AI-powered analysis
                        return (
                            f"I've found your notice **{apex_id}**! Here's what I can tell you:\n\n"
                            f"{pdf_render_text}\n\n"
                            f"**COMPREHENSIVE NOTICE ANALYSIS:**\n\n"
                            f"Based on the indexed content from your **{apex_id}** notice, I can now provide you with a detailed analysis. Here is the complete content for me to analyze:\n\n"
                            f"<NOTICE_CONTENT>\n{full_rag_content}\n</NOTICE_CONTENT>\n\n"
                            f"Let me now provide you with a comprehensive, intelligent summary of the important information in your notice, including key dates, eligibility requirements, settlement amounts, and any actions you need to take."
                        )
                    else:
                        # No RAG content available, still show PDF
                        logger.warning("[Lucy] No RAG content found, showing PDF only")

                        # Try to use search result chunks as fallback
                        storage_path_norm = storage_path or ""
                        related_chunks = [
                            (r.get("chunk") or "")
                            for r in search_results
                            if (r.get("metadata_storage_path") or "")
                            == storage_path_norm
                        ]

                        if not related_chunks:
                            related_chunks = [doc.get("chunk") or ""]

                        full_text = "\n".join(related_chunks).strip()

                        if full_text:
                            # Extract ApexID for proper naming
                            apex_id = extract_filename_from_sas_url(sas_url)

                            # Provide search chunks for analysis
                            return (
                                f"I've found your notice **{apex_id}**! Here's what I can tell you:\n\n"
                                f"{pdf_render_text}\n\n"
                                f"**AVAILABLE CONTENT FOR ANALYSIS:**\n\n"
                                f"```\n{full_text}\n```\n\n"
                                f"Based on the available content about your **{apex_id}** notice, let me provide you with a summary of the key information."
                            )
                        else:
                            # Extract ApexID for proper naming
                            apex_id = extract_filename_from_sas_url(sas_url)

                            # Just PDF display and download link
                            return (
                                f"I've found your notice **{apex_id}**!\n\n"
                                f"{pdf_render_text}\n\n"
                                f"Click on **{apex_id}** above to view the document in the sidebar. If you have any specific questions about the notice, please let me know and I can help analyze it further."
                            )

                except Exception as extraction_err:
                    logger.error(
                        f"[Lucy] Error during PDF text extraction: {extraction_err}"
                    )

                    # Extract ApexID for proper naming
                    apex_id = extract_filename_from_sas_url(sas_url)

                    # Fallback to PDF display and download link only
                    return (
                        f"I've found your notice **{apex_id}**!\n\n"
                        f"Click on **{apex_id}** above to view the document in the sidebar. If you have any specific questions about the notice, please ask and I'll do my best to help analyze it."
                    )

            # Non-PDF fallback (should not usually happen)
            return f"Here is your document: [Download]({sas_url})"

    logger.info("[Lucy] RAG returned no results – sending friendly not-found message.")
    return _notice_not_found()


# ===== CHAINLIT EVENT HANDLERS =====
# These are REQUIRED for Chainlit to work properly


@cl.set_starters
async def set_starters(user=None):
    return [
        cl.Starter(
            label="Explain My Notice",
            message="Could you explain my class action notice to me?",
            icon="/public/icons/notice.svg",
        ),
        cl.Starter(
            label="Case Status",
            message="What is the current status of my case?",
            icon="/public/icons/update.svg",
        ),
        cl.Starter(
            label="Update Address",
            message="I need to update my address on file.",
            icon="/public/icons/payment.svg",
        ),
        cl.Starter(
            label="Request Check Reissue",
            message="I need to request a reissue of my check.",
            icon="/public/icons/callback.svg",
        ),
        cl.Starter(
            label="Am I Included In A Case",
            message="I want to know if I'm included in a class action case.",
            icon="/public/icons/callback.svg",
        ),
    ]


@cl.on_chat_start
@trace_function(name="chat.start")
async def start_chat():
    """Initialize the chat session when a user starts chatting."""
    try:
        logger.info("🚀 Starting new chat session...")

        # Perform network connectivity check on first session
        global network_check_performed
        if not network_check_performed:
            logger.info("🔍 Performing initial network connectivity check...")
            try:
                await check_network_connectivity()
                network_check_performed = True
            except Exception as e:
                logger.warning(f"Network connectivity check failed: {e}")

        # Generate session ID for tracing. Chainlit may call on_chat_start again
        # after a websocket reconnect; preserve existing turn/thread state when
        # the browser is still in the same logical chat.
        session_id = cl.user_session.get("session_id") or str(uuid.uuid4())
        cl.user_session.set("session_id", session_id)

        use_v2 = use_foundry_v2()

        with trace_span("chat.session.init", **{
            LucyAttributes.USER_SESSION: session_id,
            "session.start_time": datetime.now(timezone.utc).isoformat()
        }):
            # Initialize the persistent agent if not already done
            await initialize_persistent_agent()

        if use_v2:
            if not agent_name or not agent_version:
                logger.error("❌ Foundry v2 agent not initialized")
                await cl.Message(
                    content=(
                        "I'm sorry, there was an error initializing my systems. "
                        "Please refresh the page and try again."
                    )
                ).send()
                return

            cl.user_session.set("agent_name", agent_name)
            cl.user_session.set("agent_version", agent_version)
            logger.info(
                "✅ Foundry v2 chat session initialized: %s:%s "
                "(conversation_id=%s previous_response_id_present=%s)",
                agent_name,
                agent_version,
                cl.user_session.get("conversation_id"),
                bool(cl.user_session.get("previous_response_id")),
            )
            return

        # Ensure we have a valid persistent agent
        if not persistent_agent or not hasattr(persistent_agent, "id"):
            logger.error("❌ No valid persistent agent available")
            await cl.Message(
                content=(
                    "I'm sorry, there was an error initializing my systems. "
                    "Please refresh the page and try again."
                )
            ).send()
            return

        # Create a new thread for this session
        thread = await _safe_create_thread()

        # Store CURRENT agent and thread IDs in this session
        current_agent_id = persistent_agent.id
        cl.user_session.set("thread_id", thread.id)
        cl.user_session.set("agent_id", current_agent_id)

        logger.info(f"✅ Chat session initialized:")
        logger.info(f"   Thread ID: {thread.id}")
        logger.info(f"   Agent ID: {current_agent_id}")

        # No welcome message - just show starter buttons

    except Exception as e:
        logger.error(f"❌ Error starting chat session: {str(e)}", exc_info=True)
        await cl.Message(
            content="I'm sorry, there was an error starting our conversation. "
            "Please try again or contact support if the issue persists."
        ).send()


@cl.on_message
@trace_function(name="chat.message")
async def main(message: cl.Message):
    """Handle incoming user messages."""
    assistant_response = None
    try:
        # Get session data
        session_id = cl.user_session.get("session_id", str(uuid.uuid4()))
        turn_id = int(cl.user_session.get("turn_id", 0)) + 1
        cl.user_session.set("turn_id", turn_id)
        thread_id = cl.user_session.get("thread_id")
        agent_id = cl.user_session.get("agent_id")
        user_authenticated = cl.user_session.get("authenticated", False)
        user_apex_id = cl.user_session.get("apex_id", "")
        use_v2 = use_foundry_v2()
        logger.info(f"🧾 Incoming user message turn={turn_id} thread={thread_id} len={len(message.content)}")

        # Track notice requests across turns so auth follow-ups don't clear intent.
        # Only set when we detect notice intent; otherwise keep existing value.
        if _is_notice_intent(message.content):
            cl.user_session.set("pending_notice_request", True)
            cl.user_session.set("pending_notice_request_text", message.content)
            logger.info("📌 Notice intent detected; will attempt notice retrieval after auth.")

        # Start message processing span
        with trace_span("message.process", **{
            LucyAttributes.USER_SESSION: session_id,
            LucyAttributes.USER_AUTHENTICATED: user_authenticated,
            LucyAttributes.USER_APEX_ID: user_apex_id,
            "message.content_length": len(message.content),
            "thread.id": thread_id or "",
            "agent.id": agent_id or "",
            "message.timestamp": datetime.now(timezone.utc).isoformat()
        }) as span:
            if use_v2:
                if not agent_name or not agent_version:
                    await initialize_persistent_agent()
                if agent_name and agent_version:
                    cl.user_session.set("agent_name", agent_name)
                    cl.user_session.set("agent_version", agent_version)
                    agent_id = f"{agent_name}:{agent_version}"
                conversation_id = cl.user_session.get("conversation_id")
                if conversation_id:
                    thread_id = conversation_id

            # Validate session data
            if not use_v2 and (not thread_id or not agent_id):
                logger.error("❌ No thread or agent ID found in session")
                if span:
                    span.set_attribute(LucyAttributes.ERROR_TYPE, "SessionError")
                    span.set_attribute(LucyAttributes.ERROR_MESSAGE, "Missing thread or agent ID")
                    span.set_status(Status(StatusCode.ERROR, "Session validation failed"))
                await cl.Message(
                    content="Session error. Please refresh the page and try again."
                ).send()
                record_metric("message.error", 1, "count", error_type="session_invalid")
                return

            # Double-check that we have a valid persistent agent
            if not use_v2 and (not persistent_agent or persistent_agent.id != agent_id):
                logger.warning(f"⚠️ Session agent ID {agent_id} doesn't match current agent")

                with trace_span("agent.reinitialize", **{
                    "reason": "agent_id_mismatch",
                    "session_agent_id": agent_id,
                    "current_agent_id": persistent_agent.id if persistent_agent else "none"
                }) as reinit_span:
                    # Re-initialize if needed
                    await initialize_persistent_agent()
                    if persistent_agent:
                        # Update session with current agent ID
                        cl.user_session.set("agent_id", persistent_agent.id)
                        agent_id = persistent_agent.id
                        logger.info(f"✅ Updated session with current agent ID: {agent_id}")
                        if reinit_span:
                            reinit_span.set_attribute("reinitialization.success", True)
                            reinit_span.set_attribute("new_agent_id", agent_id)
                    else:
                        logger.error("❌ Could not re-initialize persistent agent")
                        if reinit_span:
                            reinit_span.set_attribute("reinitialization.success", False)
                            reinit_span.set_status(Status(StatusCode.ERROR, "Agent reinitialization failed"))
                        await cl.Message(
                            content=(
                                "I'm experiencing technical difficulties. "
                                "Please refresh the page."
                            )
                        ).send()
                        record_metric("agent.reinitialize.failed", 1, "count")
                return

            _record_local_history("User", message.content)

            # If no active/pending handoff, check for a recent open handoff for this member and offer to reconnect
            if not cl.user_session.get("active_handoff_conversation_id") and not cl.user_session.get("pending_handoff"):
                if user_apex_id and not cl.user_session.get("handoff_reconnect_offer") and not cl.user_session.get("handoff_reconnect_prompted"):
                    try:
                        recent = conversation_store.get_recent_handoff_for_apex(user_apex_id, max_age_minutes=10)
                    except Exception as query_err:
                        recent = None
                        logger.warning(f"⚠️ Could not query recent handoff: {query_err}")
                    if recent:
                        offer = {
                            "conversation_id": recent.get("conversation_id") or recent.get("original_conversation_id"),
                            "portal_url": recent.get("portal_url") or os.getenv("AGENT_PORTAL_URL", "http://localhost:8001"),
                            "agent_name": recent.get("agent_name", "Agent"),
                            "status": recent.get("status", "pending")
                        }
                        cl.user_session.set("handoff_reconnect_offer", offer)
                        cl.user_session.set("handoff_reconnect_prompted", True)
                        await cl.Message(
                            content="I see you recently asked for a human agent. Would you like me to reconnect you, or keep helping you here? Reply \"yes\" to reconnect or \"no\" to continue with me.",
                            author="Lucy"
                        ).send()
                        return

            # Handle user response to a reconnect offer
            reconnect_offer = cl.user_session.get("handoff_reconnect_offer")
            if reconnect_offer:
                lower = message.content.strip().lower()
                yes_terms = ["yes", "y", "yeah", "sure", "ok", "okay", "please", "reconnect", "connect"]
                no_terms = ["no", "nah", "nope", "not now", "later", "continue", "stay"]
                if any(term in lower for term in yes_terms):
                    conv_id = reconnect_offer.get("conversation_id")
                    portal_url = reconnect_offer.get("portal_url") or os.getenv("AGENT_PORTAL_URL", "http://localhost:8001")
                    cl.user_session.set("handoff_reconnect_offer", None)
                    await cl.Message(
                        content="Reconnecting you with a human agent now. If the agent doesn't appear in a few minutes, let me know and I'll schedule a callback.",
                        author="Lucy"
                    ).send()
                    # Persist latest history and re-establish bridge
                    if conv_id:
                        await store_conversation_history_for_handoff(conv_id)
                        bridge_success = await websocket_bridge.start_bridge(conv_id, portal_url)
                        if bridge_success:
                            cl.user_session.set("active_handoff_conversation_id", conv_id)
                            cl.user_session.set("handoff_agent_name", reconnect_offer.get("agent_name", "Agent"))
                            return
                elif any(term in lower for term in no_terms):
                    cl.user_session.set("handoff_reconnect_offer", None)
                    await cl.Message(
                        content="No problem—I'll continue assisting you here.",
                        author="Lucy"
                    ).send()
                    # proceed with normal AI processing
            # Check for active WebSocket bridge (live transfer mode)
            active_handoff_id = cl.user_session.get("active_handoff_conversation_id")

            logger.debug(f"🔧 Active handoff ID: {active_handoff_id}")
            if active_handoff_id:
                bridge_active = websocket_bridge.is_bridge_active(active_handoff_id)
                logger.debug(f"🔧 Bridge active for {active_handoff_id}: {bridge_active}")

                if bridge_active:
                    logger.info(f"🌉 Routing message through WebSocket bridge for handoff {active_handoff_id}")
                    
                    # First, process any queued messages from the agent portal
                    while True:
                        queued_msg = await websocket_bridge.get_queued_message(active_handoff_id)
                        if not queued_msg:
                            break
                        
                        msg_data = queued_msg.get('data', {})
                        msg_type = msg_data.get('type', 'message')
                        
                        if msg_type == 'agent_joined':
                            handoff_agent_name = msg_data.get('agent', 'Agent')
                            await cl.Message(
                                content=f"🤖 **{handoff_agent_name} has joined the conversation**\n\nYou're now connected with a human agent. How can they help you?",
                                author="System"
                            ).send()
                            await _cancel_callback_timeout_monitor(active_handoff_id)
                        
                        elif msg_type == 'agent_left':
                            handoff_agent_name = msg_data.get('agent', 'Agent')
                            await cl.Message(
                                content=f"👋 **{handoff_agent_name} has left the conversation**\n\nI'm back to assist you. Is there anything else I can help with?",
                                author="System"
                            ).send()
                        
                        elif msg_data.get('role') == 'agent' or msg_type == 'agent_message':
                            content = msg_data.get('content', '') or msg_data.get('display_content', '')
                            handoff_agent_name = msg_data.get('agent_name', 'Agent')
                            
                            if content.strip():
                                await cl.Message(
                                    content=content,
                                    author=handoff_agent_name
                                ).send()
                                logger.info(f"📨 Displayed agent message from {handoff_agent_name}: {content[:50]}...")
                        
                        elif msg_type == 'system':
                            content = msg_data.get('content', '')
                            if content.strip():
                                await cl.Message(
                                    content=f"ℹ️ {content}",
                                    author="System"
                                ).send()

                    # Send user message to agent portal through WebSocket bridge
                    user_name = str(cl.user_session.get("user_name", "User"))
                    success = await websocket_bridge.send_user_message(
                        active_handoff_id,
                        message.content,
                        user_name
                    )

                    if success:
                        logger.info("✅ Message sent to agent through WebSocket bridge - ending AI processing")
                        # Message handled by bridge - don't process with AI agent
                        return
                    else:
                        logger.warning("⚠️ Failed to send message through bridge, falling back to AI agent")
                        # Clear failed handoff state
                        cl.user_session.set("active_handoff_conversation_id", None)
                        await cl.Message(
                            content="⚠️ **Connection to agent lost**\n\nI'll continue assisting you. If you need another agent, please let me know.",
                            author="System"
                        ).send()
                else:
                    logger.debug(f"🔧 Bridge not active for {active_handoff_id}, continuing with AI processing")
            else:
                logger.debug(f"🔧 No active handoff, continuing with AI processing")

            # Check if we're collecting callback information
            callback_info = cl.user_session.get("collecting_callback_info")
            if callback_info:
                logger.info(f"📞 Processing callback collection step: {callback_info.get('step')}")
                await handle_callback_collection(message.content, callback_info)
                return

            logger.info(
                f"📝 Processing message with Agent ID: {agent_id}, Thread ID: {thread_id}"
            )
            logger.info(f"📝 Message content: {message.content[:100]}...")

            if span:
                span.set_attribute("message.preview", message.content[:100])

        # Create a thinking message with animated dots
        thinking_msg = cl.Message(content="Processing your request...", author="Lucy")
        await thinking_msg.send()

        # Start the thinking animation - dots accumulate to form a square
        # Builds up to 8 dots total (2 per side) then resets
        animation_frames = [
            "...",        # Start with 1 dot
            ".. .",       # Bottom side (2 dots)
            "..  .",      # Add right side start
            "..   .",     # Right side complete (4 dots)
            ". .  .",     # Add top start
            ".  . .",     # Top complete (6 dots)
            ".   ..",     # Add left side start
            ". .  ."      # Full square (8 dots)
        ]
        animation_task = asyncio.create_task(
            animate_thinking_message(thinking_msg, animation_frames, interval=0.3)
        )

        pdf_tool_outputs: list[str] = []
        forced_notice_output = None
        pdf_info = None

        if use_v2:
            try:
                with trace_span("agent.run", **{
                    LucyAttributes.AGENT_ID: agent_id or f"{agent_name}:{agent_version}",
                    "thread.id": conversation_id or "",
                    LucyAttributes.MODEL_NAME: get_model_deployment_name(),
                    "run.start_time": datetime.now(timezone.utc).isoformat(),
                }):
                    v2_result = await _run_response_v2(message.content)
                    assistant_response = (v2_result or {}).get("text", "") if isinstance(v2_result, dict) else ""
                    tool_outputs = (v2_result or {}).get("tool_outputs", []) if isinstance(v2_result, dict) else []

                    logger.info(
                        "🧾 V2 assistant_response length=%s tool_outputs=%s",
                        len(assistant_response) if assistant_response else 0,
                        len(tool_outputs),
                    )

                    handoff_tool_payload = None
                    pdf_tool_outputs = []

                    for call in tool_outputs:
                        name = call.get("name")
                        output = call.get("output")
                        arguments = call.get("arguments", "{}")
                        if name == "authenticate_member_sync" and output:
                            try:
                                auth_payload = json.loads(output if isinstance(output, str) else str(output))
                            except Exception:
                                auth_payload = None
                            if isinstance(auth_payload, dict) and auth_payload.get("success"):
                                member = auth_payload.get("member") or {}
                                apex_value = (
                                    member.get("new_apexid")
                                    or member.get("apex_id")
                                    or auth_payload.get("apex_id")
                                )
                                if apex_value:
                                    try:
                                        cl.user_session.set("apex_id", normalize_apex_id(str(apex_value)))
                                        cl.user_session.set("authenticated", True)
                                        logger.info(f"✅ Stored apex_id from auth tool: {apex_value}")
                                    except Exception as apex_store_error:
                                        logger.warning(f"⚠️ Unable to store apex_id from auth tool: {apex_store_error}")
                                full_name = member.get("new_fullname") or member.get("full_name")
                                if full_name:
                                    cl.user_session.set("user_name", full_name)

                        if name == "find_notice_for_user_sync" and output:
                            notice_output = str(output)
                            notice_status = _classify_notice_tool_output(notice_output)
                            if notice_status == "pdf_found":
                                pdf_tool_outputs.append(notice_output)
                            if notice_status in {"pdf_found", "found", "not_found", "answered"}:
                                _record_notice_lookup_status(notice_status, notice_output)

                        if name in {
                            "send_handoff_notification_email_sync",
                            "request_human_assistance_sync",
                            "check_human_availability_sync",
                        }:
                            handoff_tool_payload = {
                                "name": name,
                                "arguments": arguments,
                                "outputs": [output] if output is not None else [],
                            }

                    if pdf_tool_outputs:
                        for raw_output in pdf_tool_outputs:
                            pdf_info = _extract_pdf_info_from_text(raw_output)
                            if pdf_info:
                                _record_pending_pdf(
                                    pdf_info["url"],
                                    pdf_info.get("name") or "Class Action Notice",
                                    display=pdf_info.get("display", "side"),
                                )
                                break

                    if not pdf_tool_outputs and cl.user_session.get("pending_notice_request"):
                        apex_id = cl.user_session.get("apex_id")
                        notice_request_satisfied = False
                        if apex_id:
                            try:
                                from user_functions import find_notice_for_user_sync
                                forced_notice_output = find_notice_for_user_sync(str(apex_id))
                                notice_status = _classify_notice_tool_output(forced_notice_output)
                                if notice_status == "pdf_found":
                                    pdf_tool_outputs.append(str(forced_notice_output))
                                    notice_request_satisfied = True
                                elif notice_status in {"found", "not_found", "answered"}:
                                    notice_request_satisfied = True
                                else:
                                    forced_notice_output = None
                            except Exception as notice_err:
                                logger.warning(f"⚠️ Forced notice retrieval failed: {notice_err}")
                        if notice_request_satisfied:
                            _record_notice_lookup_status(
                                _classify_notice_tool_output(forced_notice_output),
                                forced_notice_output,
                            )
                        else:
                            logger.info("📌 Keeping pending notice request for the next turn.")

                    if pdf_tool_outputs and not cl.user_session.get("pending_pdf"):
                        for raw_output in pdf_tool_outputs:
                            pdf_info = _extract_pdf_info_from_text(raw_output)
                            if pdf_info:
                                _record_pending_pdf(
                                    pdf_info["url"],
                                    pdf_info.get("name") or "Class Action Notice",
                                    display=pdf_info.get("display", "side"),
                                )
                                break

                    if forced_notice_output:
                        assistant_response = str(forced_notice_output)

                    await _send_v2_response_with_pdf(
                        assistant_response,
                        animation_task,
                        turn_id=turn_id,
                        conversation_id=conversation_id,
                    )
                    await _process_handoff_after_response(
                        assistant_response,
                        handoff_tool_payload,
                        message.content,
                    )
                    return
            except Exception as v2_err:
                logger.error(f"❌ Foundry v2 response failed: {v2_err}", exc_info=True)
                animation_task.cancel()
                try:
                    await animation_task
                except asyncio.CancelledError:
                    pass
                await cl.Message(
                    content="I'm experiencing connectivity issues. Please try again."
                ).send()
                return

        if not use_v2:
            # Create a message in the thread with retry logic
            @retry(
                retry=retry_if_exception_type(
                    (ServiceResponseError, ClientAuthenticationError, ConnectionError)
                ),
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=2, max=10),
            )
            async def create_message_with_retry():
                try:
                    if agents_client is None or not hasattr(agents_client, "messages"):
                        logger.error(
                            "❌ agents_client is None or missing 'messages' attribute"
                        )
                        raise RuntimeError(
                            "Azure AI Agents client not properly initialized"
                        )
    
                    return agents_client.messages.create(
                        thread_id=thread_id or "", role="user", content=message.content
                    )
                except Exception as e:
                    logger.warning(f"⚠️ Message creation attempt failed: {str(e)}")
                    # Re-initialize agent if connection issues persist
                    if "Connection" in str(e) or "aborted" in str(e):
                        logger.info("🔄 Reinitializing agent due to connection issues")
                        await initialize_persistent_agent()
                    raise
    
            with trace_span("message.create", **{
                "thread.id": thread_id,
                "message.role": "user",
                "message.content_length": len(message.content)
            }) as msg_span:
                try:
                    await create_message_with_retry()
                    if msg_span:
                        msg_span.set_attribute("message.created", True)
                    record_metric("message.created", 1, "count")
                except Exception as msg_error:
                    logger.error(f"❌ Failed to create message after retries: {msg_error}")
                    if msg_span:
                        msg_span.set_status(Status(StatusCode.ERROR, str(msg_error)))
                        msg_span.record_exception(msg_error)
                        msg_span.set_attribute(LucyAttributes.ERROR_TYPE, type(msg_error).__name__)
                        msg_span.set_attribute(LucyAttributes.ERROR_MESSAGE, str(msg_error))
                    record_metric("message.create.error", 1, "count", error_type=type(msg_error).__name__)
                    await cl.Message(
                        content="I'm experiencing connectivity issues. Please try again."
                    ).send()
                    return
    
            # Process the message with the agent
            try:
                # Start agent run span
                with trace_span("agent.run", **{
                    LucyAttributes.AGENT_ID: agent_id,
                    "thread.id": thread_id,
                    LucyAttributes.MODEL_NAME: azure_gpt_model or "gpt-4",
                    "run.start_time": datetime.now(timezone.utc).isoformat()
                }):
                    # Use create_and_process for automatic handling with retry logic
                    @retry(
                        retry=retry_if_exception_type(
                            (ServiceResponseError, ClientAuthenticationError, ConnectionError)
                        ),
                        stop=stop_after_attempt(3),
                        wait=wait_exponential(multiplier=1, min=2, max=10),
                    )
                    async def create_and_process_run():
                        nonlocal agent_id  # Allow modification of outer scope variable
                        try:
                            if agents_client is None or not hasattr(agents_client, "runs"):
                                logger.error(
                                    "❌ agents_client is None or missing 'runs' attribute"
                                )
                                raise RuntimeError(
                                    "Azure AI Agents client not properly initialized"
                                )
    
                            # Get the event loop for async operations
                            loop = asyncio.get_event_loop()
    
                            # Validate agent exists before attempting to create run
                            current_agent_id = agent_id  # Capture current value to avoid scoping issues
                            try:
                                def validate_agent():
                                    if hasattr(agents_client, 'get_agent'):
                                        return agents_client.get_agent(current_agent_id)
                                    else:
                                        logger.debug("get_agent method not available, skipping validation")
                                        return None
    
                                await loop.run_in_executor(None, validate_agent)
                                logger.debug(f"✅ Agent {current_agent_id} validated before run creation")
                            except Exception as validate_error:
                                if "No assistant found" in str(validate_error):
                                    logger.warning(f"⚠️ Agent {current_agent_id} not found during validation, reinitializing...")
                                    await initialize_persistent_agent()
                                    if persistent_agent:
                                        cl.user_session.set("agent_id", persistent_agent.id)
                                        agent_id = persistent_agent.id
                                        logger.info(f"✅ Updated to new agent ID: {agent_id}")
                                    else:
                                        raise RuntimeError("Failed to reinitialize agent")
                                else:
                                    logger.warning(f"Agent validation failed: {validate_error}")
                                    raise
    
                            start_time = time.time()
                            # Run the blocking call in a thread to allow animation to continue
                            run_result = await loop.run_in_executor(
                                None,  # Use default thread pool
                                lambda: agents_client.runs.create_and_process(
                                    thread_id=str(thread_id),
                                    agent_id=str(agent_id)
                                )
                            )
                            latency_ms = (time.time() - start_time) * 1000
    
                            # Record latency metric only - span attributes across thread boundaries are unreliable
                            record_metric("agent.run.latency", latency_ms, "ms", model=azure_gpt_model or "gpt-4")
    
                            return run_result
                        except Exception as e:
                            logger.warning(f"⚠️ Run creation attempt failed: {str(e)}")
                            if "Connection" in str(e) or "aborted" in str(e) or "Network" in str(e):
                                logger.info("🔄 Connection issue detected - checking network status...")
                                await check_network_status_simple()
                                logger.info("🔄 Reinitializing agent due to connection issues")
                                await initialize_persistent_agent()
                            elif "No assistant found" in str(e):
                                logger.warning(f"⚠️ Agent {agent_id} disappeared during run creation, reinitializing...")
                                await initialize_persistent_agent()
                                if persistent_agent:
                                    cl.user_session.set("agent_id", persistent_agent.id)
                                    agent_id = persistent_agent.id
                            raise
    
                    run = await create_and_process_run()
                    handoff_tool_payload = None
                    pdf_tool_outputs: list[str] = []
                    forced_notice_output = None
                    pdf_info = None
    
                    # Log run completion - span attributes across thread boundaries are unreliable
                    if run:
                        logger.debug(f"Run completed - ID: {run.id if hasattr(run, 'id') else 'unknown'}, Status: {run.status if hasattr(run, 'status') else 'unknown'}")
                        try:
                            tool_calls = getattr(run, "tool_calls", []) or []
                            for call in tool_calls:
                                if getattr(call, "type", "").lower() == "function":
                                    function_call = getattr(call, "function", None)
                                    function_name = getattr(function_call, "name", "") if function_call else ""
                                    if function_name in {"authenticate_member_sync"}:
                                        output = getattr(function_call, "output", None) if function_call else None
                                        if output:
                                            try:
                                                auth_payload = json.loads(output if isinstance(output, str) else str(output))
                                            except Exception:
                                                auth_payload = None
                                            if isinstance(auth_payload, dict) and auth_payload.get("success"):
                                                member = auth_payload.get("member") or {}
                                                apex_value = (
                                                    member.get("new_apexid")
                                                    or member.get("apex_id")
                                                    or auth_payload.get("apex_id")
                                                )
                                                if apex_value:
                                                    try:
                                                        cl.user_session.set("apex_id", normalize_apex_id(str(apex_value)))
                                                        cl.user_session.set("authenticated", True)
                                                        logger.info(f"✅ Stored apex_id from auth tool: {apex_value}")
                                                    except Exception as apex_store_error:
                                                        logger.warning(f"⚠️ Unable to store apex_id from auth tool: {apex_store_error}")
                                                full_name = member.get("new_fullname") or member.get("full_name")
                                                if full_name:
                                                    cl.user_session.set("user_name", full_name)
                                    if function_name in {"find_notice_for_user_sync"}:
                                        output = getattr(function_call, "output", None) if function_call else None
                                        if output:
                                            outputs = output if isinstance(output, (list, tuple)) else [output]
                                            for raw_output in outputs:
                                                notice_output = str(raw_output)
                                                notice_status = _classify_notice_tool_output(notice_output)
                                                if notice_status == "pdf_found":
                                                    pdf_tool_outputs.append(notice_output)
                                                if notice_status in {"pdf_found", "found", "not_found", "answered"}:
                                                    _record_notice_lookup_status(notice_status, notice_output)
                                            logger.info(f"🔍 Captured notice tool output from {function_name}")
                                    if function_name in {
                                        "send_handoff_notification_email_sync",
                                        "request_human_assistance_sync",
                                        "check_human_availability_sync"
                                    }:
                                        arguments = getattr(function_call, "arguments", "{}") if function_call else "{}"
                                        output = getattr(function_call, "output", None) if function_call else None
                                        handoff_tool_payload = {
                                            "name": function_name,
                                            "arguments": arguments,
                                            "outputs": []
                                        }
                                        if output:
                                            if isinstance(output, (list, tuple)):
                                                handoff_tool_payload["outputs"].extend(output)
                                            else:
                                                handoff_tool_payload["outputs"].append(output)
                                        logger.info(f"🔍 Captured handoff tool output from {function_name}")
                                        break
                        except Exception as tool_parse_error:
                            logger.warning(f"⚠️ Unable to extract handoff tool payload: {tool_parse_error}")
    
                    record_metric("agent.run.completed", 1, "count")
    
                    # Parse PDF tool outputs immediately to populate pending cache
                    if pdf_tool_outputs:
                        for raw_output in pdf_tool_outputs:
                            pdf_info = _extract_pdf_info_from_text(raw_output)
                            if pdf_info:
                                _record_pending_pdf(
                                    pdf_info["url"],
                                    pdf_info.get("name") or "Class Action Notice",
                                    display=pdf_info.get("display", "side"),
                                )
                                break
                        if not pdf_info:
                            logger.info("ℹ️ PDF tool output captured but no PDF info found")
    
                    # Fallback: force notice retrieval if user asked for notice and tool didn't run
                    if not pdf_tool_outputs and cl.user_session.get("pending_notice_request"):
                        apex_id = cl.user_session.get("apex_id")
                        notice_request_satisfied = False
                        if apex_id:
                            try:
                                from user_functions import find_notice_for_user_sync
                                forced_notice_output = find_notice_for_user_sync(str(apex_id))
                                notice_status = _classify_notice_tool_output(forced_notice_output)
                                if notice_status == "pdf_found":
                                    pdf_tool_outputs.append(str(forced_notice_output))
                                    notice_request_satisfied = True
                                    logger.info("✅ Forced notice retrieval after missing tool call")
                                elif notice_status in {"found", "not_found", "answered"}:
                                    notice_request_satisfied = True
                                    logger.info("✅ Forced notice retrieval after missing tool call")
                                else:
                                    forced_notice_output = None
                            except Exception as notice_err:
                                logger.warning(f"⚠️ Forced notice retrieval failed: {notice_err}")
                        if notice_request_satisfied:
                            _record_notice_lookup_status(
                                _classify_notice_tool_output(forced_notice_output),
                                forced_notice_output,
                            )
                        else:
                            logger.info("📌 Keeping pending notice request for the next turn.")
    
                # Get the latest messages from the thread with retry logic
                @retry(
                    retry=retry_if_exception_type(
                        (ServiceResponseError, ClientAuthenticationError, ConnectionError)
                    ),
                    stop=stop_after_attempt(3),
                    wait=wait_exponential(multiplier=1, min=2, max=10),
                )
                async def get_messages_with_retry():
                    try:
                        if agents_client is None or not hasattr(agents_client, "messages"):
                            logger.error(
                                "❌ agents_client is None or missing 'messages' attribute"
                            )
                            raise RuntimeError(
                                "Azure AI Agents client not properly initialized"
                            )
    
                        # Run the blocking call in a thread to allow animation to continue
                        loop = asyncio.get_event_loop()
                        return await loop.run_in_executor(
                            None,
                            lambda: agents_client.messages.list(
                                thread_id=str(thread_id), order="desc", limit=5
                            )
                        )
                    except Exception as e:
                        logger.warning(f"⚠️ Message retrieval attempt failed: {str(e)}")
                        if "Connection" in str(e) or "aborted" in str(e):
                            logger.info("🔄 Reinitializing agent due to connection issues")
                            await initialize_persistent_agent()
                        raise
    
                with trace_span("messages.retrieve", **{
                    "thread.id": thread_id,
                    "limit": 5
                }) as retrieve_span:
                    messages = await get_messages_with_retry()
                    message_items = list(messages)
    
                    def _extract_message_text(msg_obj):
                        try:
                            texts = []
                            if hasattr(msg_obj, "text_messages") and msg_obj.text_messages:
                                for tm in msg_obj.text_messages:
                                    if hasattr(tm, "text") and hasattr(tm.text, "value"):
                                        texts.append(tm.text.value)
                                    elif hasattr(tm, "text"):
                                        texts.append(str(tm.text))
                                if texts:
                                    return "\n".join(t for t in texts if t)
                            if getattr(msg_obj, "content", None):
                                for content_item in msg_obj.content:
                                    if hasattr(content_item, "text"):
                                        if hasattr(content_item.text, "value"):
                                            texts.append(content_item.text.value)
                                        else:
                                            texts.append(str(content_item.text))
                                    else:
                                        texts.append(str(content_item))
                            # De-dupe repeated segments while preserving order
                            deduped = []
                            seen = set()
                            for t in texts:
                                if not t:
                                    continue
                                if t in seen:
                                    continue
                                seen.add(t)
                                deduped.append(t)
                            return "\n".join(deduped)
                        except Exception:
                            return ""
    
                    # Find the assistant's response
                    assistant_response = None
                    message_count = 0
                    for msg in message_items:
                        message_count += 1
                        if msg.role == "assistant" and hasattr(msg, "content"):
                            assistant_response = _extract_message_text(msg)
                        if assistant_response:
                            break

                # Scan all messages for PDF info (tool outputs may not be in assistant text)
                pdf_info = None
                for msg in message_items:
                    msg_text = _extract_message_text(msg)
                    if not msg_text:
                        continue
                    pdf_info = _extract_pdf_info_from_text(msg_text)
                    if pdf_info:
                        role = getattr(msg, "role", "unknown")
                        logger.info(f"✅ PDF info extracted from {role} message")
                        _record_pending_pdf(
                            pdf_info["url"],
                            pdf_info.get("name") or "Class Action Notice",
                            display=pdf_info.get("display", "side"),
                        )
                        break

                if forced_notice_output:
                    assistant_response = str(forced_notice_output)
                if retrieve_span:
                    retrieve_span.set_attribute("messages.count", message_count)
                    retrieve_span.set_attribute("response.found", assistant_response is not None)
                    if assistant_response:
                        retrieve_span.set_attribute("response.length", len(assistant_response))

                if assistant_response:
                    _log_link_debug(
                        "assistant_response_raw",
                        content=assistant_response,
                        thread_id=thread_id,
                        turn_id=turn_id,
                    )
                    last_sent_content = None
                    # Cancel the animation and update with response
                    animation_task.cancel()
                    try:
                        await animation_task
                    except asyncio.CancelledError:
                        pass
    
                    logger.info(
                        f"🔍 Assistant response received (length: {len(assistant_response)})"
                    )
                    logger.info(f"🔍 Checking for PDF markers in response...")
    
                    # Check for new PDF_DISPLAY_INFO format and convert to PDF marker
                    if "**PDF_DISPLAY_INFO:**" in assistant_response:
                        logger.info("✅ PDF_DISPLAY_INFO detected in assistant response!")
                        try:
                            import re
    
                            # Extract PDF info from the structured format
                            pdf_url_match = re.search(r"- PDF_URL: (.+)", assistant_response)
                            pdf_name_match = re.search(r"- PDF_NAME: (.+)", assistant_response)
                            display_mode_match = re.search(r"- DISPLAY_MODE: (.+)", assistant_response)
    
                            if pdf_url_match and pdf_name_match and display_mode_match:
                                pdf_url = pdf_url_match.group(1).strip()
                                pdf_name = pdf_name_match.group(1).strip()
                                pdf_name = _normalize_pdf_display_name(pdf_name)
                                # Use a safe element name to avoid Chainlit link replacement inside URLs
                                element_name = "Notice PDF"
                                display_mode = display_mode_match.group(1).strip()
    
                                logger.info(f"✅ Extracted PDF URL: {pdf_url[:50]}...")
                                logger.info(f"✅ PDF Name: {pdf_name}")
                                logger.info(f"✅ Display mode: {display_mode}")
    
                                # Remove the PDF_DISPLAY_INFO section from the response
                                clean_response = re.sub(r"\*\*PDF_DISPLAY_INFO:\*\*\n- PDF_URL: .+\n- PDF_NAME: .+\n- DISPLAY_MODE: .+", "", assistant_response)
                                logger.info("✅ Removed PDF_DISPLAY_INFO from response text")
    
                                # Create PDF element
                                try:
                                    pdf_element = cl.Pdf(
                                        name=element_name,
                                        display=display_mode,  # type: ignore
                                        url=pdf_url,
                                        page=1,
                                    )
    
                                    # Ensure the PDF name appears in the content for side/page display
                                    response_content = clean_response.strip()
                                    if element_name not in response_content:
                                        response_content = (
                                            response_content
                                            + f"\n\n📄 {element_name}\n"
                                            + f"[Download {pdf_name}]({pdf_url})"
                                        )
    
                                    # Cancel the thinking animation first
                                    animation_task.cancel()
                                    try:
                                        await animation_task
                                    except asyncio.CancelledError:
                                        pass
    
                                    # Send the text message first
                                    _log_link_debug(
                                        "pdf_display_info_send",
                                        content=response_content,
                                        pdf_url=pdf_url,
                                        pdf_name=pdf_name,
                                        thread_id=thread_id,
                                        turn_id=turn_id,
                                    )
                                    response_msg = cl.Message(
                                        content=response_content,
                                        author="Lucy",
                                    )
                                    await response_msg.send()
                                    last_sent_content = response_msg.content
    
                                    # Attach the PDF element to the message
                                    await pdf_element.send(for_id=response_msg.id)
    
                                    if display_mode == "side":
                                        try:
                                            sidebar_pdf = cl.Pdf(
                                                name=element_name,
                                                display=display_mode,  # type: ignore
                                                url=pdf_url,
                                                page=1,
                                            )
                                            await cl.ElementSidebar.set_title(f"📄 {pdf_name}")
                                            await cl.ElementSidebar.set_elements([sidebar_pdf])
                                        except Exception as sidebar_err:
                                            logger.warning(
                                                f"⚠️ Failed to open PDF in sidebar: {sidebar_err}"
                                            )
                                    logger.info("✅ PDF element sent successfully!")
                                    try:
                                        cl.user_session.set("pending_pdf", None)
                                    except Exception:
                                        pass
    
                                except Exception as pdf_create_err:
                                    logger.error(f"❌ Error creating PDF element: {pdf_create_err}", exc_info=True)
                                    # Fallback to regular message
                                    animation_task.cancel()
                                    try:
                                        await animation_task
                                    except asyncio.CancelledError:
                                        pass
    
                                    response_msg = cl.Message(content=assistant_response, author="Lucy")
                                    await response_msg.send()
                                    last_sent_content = response_msg.content
                            else:
                                logger.warning("⚠️ PDF_DISPLAY_INFO found but couldn't extract all required fields")
                                # Fall through to normal processing
    
                        except Exception as pdf_info_err:
                            logger.error(f"❌ Error processing PDF_DISPLAY_INFO: {pdf_info_err}", exc_info=True)
                            # Fall through to normal processing
    
                    # Check for PDF render markers and handle them
                    elif "<<PDF_RENDER_MARKER_BEGIN|" in assistant_response:
                        logger.info("✅ PDF marker detected in assistant response!")
                        try:
                            # Extract PDF URL from marker
                            import re
    
                            pattern = r"<<PDF_RENDER_MARKER_BEGIN\|([^|]+)\|([^|]+)\|PDF_RENDER_MARKER_END>>"
                            match = re.search(pattern, assistant_response)
    
                            if match:
                                pdf_url = match.group(1)
                                display_mode = match.group(2)
                                logger.info(f"✅ Extracted PDF URL: {pdf_url[:50]}...")
                                logger.info(f"✅ Display mode: {display_mode}")
    
                                # Remove the marker from the response
                                clean_response = re.sub(pattern, "", assistant_response)
                                logger.info("✅ Removed PDF marker from response text")
    
                                # Create PDF element with button approach
                                try:
                                    # Extract the actual filename from the URL
                                    pdf_name = extract_filename_from_sas_url(pdf_url)
                                    pdf_name = _normalize_pdf_display_name(pdf_name)
                                    element_name = "Notice PDF"
                                    logger.info(f"✅ Using PDF name: {pdf_name}")
    
                                    # Cancel the thinking animation first
                                    animation_task.cancel()
                                    try:
                                        await animation_task
                                    except asyncio.CancelledError:
                                        pass
    
                                    # Download and save PDF locally for Chainlit
                                    local_pdf_path = await download_pdf_locally(
                                        pdf_url, pdf_name
                                    )
    
                                    valid_display = (
                                        display_mode
                                        if display_mode in ["side", "inline", "page"]
                                        else "side"
                                    )
    
                                    pdf_el = None
                                    if local_pdf_path:
                                        # Create PDF element using local file path
                                        pdf_el = cl.Pdf(
                                            name=element_name,
                                            display=valid_display,  # type: ignore
                                            path=local_pdf_path,
                                            page=1,
                                        )
                                    else:
                                        # Fall back to loading directly from the SAS URL
                                        pdf_el = cl.Pdf(
                                            name=element_name,
                                            display=valid_display,  # type: ignore
                                            url=pdf_url,
                                            page=1
                                        )
    
                                    # Create response message attaching the PDF element
                                    response_content = (
                                        clean_response.strip()
                                        + f"\n\n📄 {element_name}\n"
                                        + f"[Download {pdf_name}]({pdf_url})"
                                    )
                                    _log_link_debug(
                                        "pdf_marker_send",
                                        content=response_content,
                                        pdf_url=pdf_url,
                                        pdf_name=pdf_name,
                                        thread_id=thread_id,
                                        turn_id=turn_id,
                                    )
                                    response_msg = cl.Message(
                                        content=response_content,
                                        author="Lucy",
                                    )
                                    await response_msg.send()
                                    last_sent_content = response_msg.content
    
                                    if pdf_el:
                                        # Attach the PDF element to the message for reliable rendering
                                        await pdf_el.send(for_id=response_msg.id)
    
                                    if pdf_el and valid_display == "side":
                                        try:
                                            await cl.ElementSidebar.set_title(f"📄 {pdf_name}")
                                            await cl.ElementSidebar.set_elements([pdf_el])
                                        except Exception as sidebar_err:
                                            logger.warning(
                                                f"⚠️ Failed to open PDF in sidebar: {sidebar_err}"
                                            )
                                    logger.info(
                                        f"✅ Response sent with PDF button for: {pdf_name}"
                                    )
                                    try:
                                        cl.user_session.set("pending_pdf", None)
                                    except Exception:
                                        pass
    
                                except Exception as pdf_create_err:
                                    logger.error(
                                        f"❌ Error creating PDF element: {pdf_create_err}"
                                    )
                                    # Cancel the thinking animation first
                                    animation_task.cancel()
                                    try:
                                        await animation_task
                                    except asyncio.CancelledError:
                                        pass
    
                                    # Fallback: create new message with download link
                                    fallback_content = (
                                        clean_response.strip()
                                        + f"\n\n📄 [**Download your notice here**]({pdf_url})"
                                    )
                                    fallback_msg = cl.Message(
                                        content=fallback_content, author="Lucy"
                                    )
                                    await fallback_msg.send()
                                    last_sent_content = fallback_msg.content
                            else:
                                logger.warning("⚠️ PDF marker found but regex didn't match")
                                # Cancel the thinking animation first
                                animation_task.cancel()
                                try:
                                    await animation_task
                                except asyncio.CancelledError:
                                    pass
    
                                # No valid marker found, clean and send the response
                                clean_response = clean_handoff_json_from_response(assistant_response)
                                response_msg = cl.Message(
                                    content=clean_response, author="Lucy"
                                )
                                await response_msg.send()
                                last_sent_content = response_msg.content
                        except Exception as pdf_err:
                            logger.error(
                                f"❌ Error handling PDF marker: {pdf_err}", exc_info=True
                            )
                            # Cancel the thinking animation first
                            animation_task.cancel()
                            try:
                                await animation_task
                            except asyncio.CancelledError:
                                pass
    
                            # Clean JSON payload from response before sending to user
                            clean_response = clean_handoff_json_from_response(assistant_response)
    
                            # Send the response as a new message (with cleaned content)
                            response_msg = cl.Message(
                                content=clean_response, author="Lucy"
                            )
                            await response_msg.send()
                            last_sent_content = response_msg.content
                    else:
                        logger.info("ℹ️ No PDF markers found in response")
                        # Cancel the thinking animation first
                        animation_task.cancel()
                        try:
                            await animation_task
                        except asyncio.CancelledError:
                            pass
    
                        # Clean JSON payload from response before sending to user
                        clean_response = clean_handoff_json_from_response(assistant_response)
    
                        # Fallback: scan response for PDF URLs and attach element if found
                        pdf_url = None
                        try:
                            import re
    
                            logger.info("🔍 PDF fallback check: scanning response for .pdf URL")
                            urls = re.findall(r"https?://[^\\s\\)\\]\"'>]+", clean_response)
                            if urls:
                                logger.info(f"🔍 Found {len(urls)} URL(s) in response")
                            links = re.findall(r"\\[[^\\]]+\\]\\(([^)]+)\\)", clean_response)
                            if links:
                                preview_links = ", ".join(
                                    l[:80] + ("..." if len(l) > 80 else "") for l in links[:3]
                                )
                                logger.info(
                                    f"🔗 Found {len(links)} markdown link(s): {preview_links}"
                                )
                            for candidate in urls:
                                if ".pdf" in candidate.lower():
                                    pdf_url = candidate
                                    break
                                if "blob.core.windows.net" in candidate and "sig=" in candidate:
                                    pdf_url = candidate
                                    break
                            if pdf_url:
                                logger.info(
                                    f"✅ PDF fallback URL detected: {pdf_url[:80]}..."
                                )
                            else:
                                logger.info("ℹ️ No PDF URL found in response; checking pending PDF")
                        except Exception as pdf_detect_err:
                            logger.warning(
                                f"⚠️ PDF fallback detection failed: {pdf_detect_err}"
                            )
    
                        pending_pdf = None
                        if not pdf_url:
                            pending_pdf = _pop_pending_pdf()
                            if pending_pdf:
                                pdf_url = pending_pdf.get("url")
                                logger.info(
                                    f"✅ Using pending PDF from tool output: {pdf_url[:80]}..."
                                )
                            else:
                                try:
                                    from user_functions import consume_recent_notice_pdf
                                    apex_id = cl.user_session.get("apex_id")
                                    pending_pdf = consume_recent_notice_pdf(
                                        str(apex_id) if apex_id else None
                                    )
                                    if pending_pdf:
                                        pdf_url = pending_pdf.get("url")
                                        logger.info(
                                            f"✅ Using cached notice PDF for {apex_id}: {pdf_url[:80]}..."
                                        )
                                except Exception as notice_err:
                                    logger.warning(
                                        f"⚠️ Notice PDF cache lookup failed: {notice_err}"
                                    )
    
                        if pdf_url:
                            pdf_name = extract_filename_from_sas_url(pdf_url)
                            if pending_pdf and pending_pdf.get("name"):
                                pdf_name = pending_pdf.get("name") or pdf_name
                            pdf_name = _normalize_pdf_display_name(pdf_name)
                            element_name = "Notice PDF"
                            response_content = clean_response
                            if element_name not in response_content:
                                response_content = (
                                    response_content
                                    + f"\n\n📄 {element_name}\n"
                                    + f"[Download {pdf_name}]({pdf_url})"
                                )
                            _log_link_debug(
                                "pdf_fallback_send",
                                content=response_content,
                                pdf_url=pdf_url,
                                pdf_name=pdf_name,
                                thread_id=thread_id,
                                turn_id=turn_id,
                            )
                            response_msg = cl.Message(content=response_content, author="Lucy")
                            await response_msg.send()
                            last_sent_content = response_msg.content
    
                            try:
                                display_mode = (
                                    pending_pdf.get("display")
                                    if pending_pdf and pending_pdf.get("display")
                                    else "side"
                                )
                                pdf_el = cl.Pdf(
                                    name=element_name,
                                    display=display_mode,  # type: ignore
                                    url=pdf_url,
                                    page=1,
                                )
                                await pdf_el.send(for_id=response_msg.id)
                                if display_mode == "side":
                                    try:
                                        await cl.ElementSidebar.set_title(f"📄 {pdf_name}")
                                        await cl.ElementSidebar.set_elements([pdf_el])
                                    except Exception as sidebar_err:
                                        logger.warning(
                                            f"⚠️ Failed to open PDF in sidebar: {sidebar_err}"
                                        )
                            except Exception as pdf_attach_err:
                                logger.error(
                                    f"❌ Failed to attach PDF in fallback: {pdf_attach_err}",
                                    exc_info=True,
                                )
                        else:
                            _log_link_debug(
                                "fallback_text_only",
                                content=clean_response,
                                thread_id=thread_id,
                                turn_id=turn_id,
                            )
                            # Regular text response as new message (with cleaned content)
                            response_msg = cl.Message(
                                content=clean_response, author="Lucy"
                            )
                            await response_msg.send()
                            last_sent_content = response_msg.content
    
                    if last_sent_content:
                        _record_local_history("Lucy", last_sent_content)
                else:
                    # Cancel the animation and show error message
                    animation_task.cancel()
                    try:
                        await animation_task
                    except asyncio.CancelledError:
                        pass
    
                    logger.warning("⚠️ No assistant response received")
                    # Send error message as new message
                    error_msg = cl.Message(
                        content="I processed your request, but didn't generate a response. Please try rephrasing your question.",
                        author="Lucy",
                    )
                    await error_msg.send()
    
            except Exception as run_error:
                # Cancel the animation and show error message
                animation_task.cancel()
                try:
                    await animation_task
                except asyncio.CancelledError:
                    pass
    
                logger.error(f"❌ Error processing agent run: {run_error}", exc_info=True)
    
                # Check if it's an agent not found error
                if "No assistant found" in str(run_error):
                    logger.warning("⚠️ Agent not found - attempting to reinitialize...")
                    try:
                        await initialize_persistent_agent()
                        if persistent_agent:
                            cl.user_session.set("agent_id", persistent_agent.id)
                            error_content = "I had to restart my systems. Please try your message again."
                        else:
                            error_content = "I'm experiencing technical difficulties. Please refresh the page."
                    except Exception as reinit_error:
                        logger.error(f"Reinitializtion failed: {reinit_error}")
                        error_content = "I'm experiencing technical difficulties. Please refresh the page."
                else:
                    error_content = (
                        "I encountered an error while processing your request. "
                        "Please try again or rephrase your question."
                    )
    
                # Send error message as new message
                error_msg = cl.Message(content=error_content, author="Lucy")
                await error_msg.send()
    
        await _process_handoff_after_response(
            assistant_response,
            handoff_tool_payload if "handoff_tool_payload" in locals() else None,
            message.content,
        )

    except Exception as e:
        logger.error(f"❌ Error in message handler: {str(e)}", exc_info=True)
        await cl.Message(
            content=(
                "I'm sorry, there was an error processing your message. "
                "Please try again."
            )
        ).send()


@cl.action_callback("view_pdf")
async def on_view_pdf(action: cl.Action):
    """Handle PDF view button clicks."""
    try:
        data = action.payload or {}
        pdf_name = data.get("pdf_name", "Class Action Notice")
        pdf_path = data.get("pdf_path", "")
        pdf_url = data.get("pdf_url", "")

        logger.info(f"✅ [view_pdf] requested for {pdf_name}")

        # Re-create the PDF element based on available source
        if pdf_path and os.path.exists(pdf_path):
            pdf_element = cl.Pdf(name=pdf_name, display="side", path=pdf_path, page=1)  # type: ignore
        elif pdf_url:
            pdf_element = cl.Pdf(name=pdf_name, display="side", url=pdf_url, page=1)  # type: ignore
        else:
            await cl.Message(content="❌ PDF source not found.").send()
            return

        # Update the sidebar
        await cl.ElementSidebar.set_title(f"📄 {pdf_name}")
        await cl.ElementSidebar.set_elements([pdf_element])

        # Inform the user
        msg_content = (
            f"✅ Your notice **{pdf_name}** is now open in the sidebar."
            f" You can also [download it directly]({pdf_url})."
            if pdf_url
            else ""
        )
        await cl.Message(content=msg_content).send()

    except Exception as e:
        logger.error(f"❌ Error in PDF view callback: {str(e)}", exc_info=True)
        await cl.Message(
            content="❌ There was an error opening the PDF. Please try the download link instead."
        ).send()


@cl.action_callback("check_agent_messages")
async def on_check_messages(action: cl.Action):
    """Handle check for agent messages button click."""
    try:
        conversation_id = action.value
        logger.info(f"🔄 User clicked check messages for conversation {conversation_id}")
        
        # Process any queued messages
        messages_found = False
        while True:
            queued_msg = await websocket_bridge.get_queued_message(conversation_id, timeout=0.1)
            if not queued_msg:
                break
            
            messages_found = True
            msg_data = queued_msg.get('data', {})
            msg_type = msg_data.get('type', 'message')
            
            if msg_type == 'agent_joined':
                agent_name = msg_data.get('agent', 'Agent')
                await cl.Message(
                    content=f"🤖 **{agent_name} has joined the conversation**\n\nYou're now connected with a human agent. How can they help you?",
                    author="System"
                ).send()
                await _cancel_callback_timeout_monitor(conversation_id)
            
            elif msg_type == 'agent_left':
                agent_name = msg_data.get('agent', 'Agent')
                await cl.Message(
                    content=f"👋 **{agent_name} has left the conversation**\n\nI'm back to assist you. Is there anything else I can help with?",
                    author="System"
                ).send()
            
            elif msg_data.get('role') == 'agent' or msg_type == 'agent_message':
                content = msg_data.get('content', '') or msg_data.get('display_content', '')
                agent_name = msg_data.get('agent_name', 'Agent')
                
                if content.strip():
                    await cl.Message(
                        content=content,
                        author=agent_name
                    ).send()
                    logger.info(f"📨 Displayed agent message from {agent_name}: {content[:50]}...")
            
            elif msg_type == 'system':
                content = msg_data.get('content', '')
                if content.strip():
                    await cl.Message(
                        content=f"ℹ️ {content}",
                        author="System"
                    ).send()
        
        if not messages_found:
            await cl.Message(
                content="📁 No new messages from the agent yet. I'll let you know when they respond.",
                author="System"
            ).send()
        
    except Exception as e:
        logger.error(f"Error checking messages: {str(e)}", exc_info=True)
        await cl.Message(
            content="⚠️ There was an error checking for messages. Please try typing a message instead.",
            author="System"
        ).send()


@cl.on_chat_end
async def end_chat():
    """Clean up when a chat session ends."""
    try:
        thread_id = cl.user_session.get("thread_id")
        active_handoff_id = cl.user_session.get("active_handoff_conversation_id")

        if thread_id:
            logger.info(f"💤 Chat session ending - Thread ID: {thread_id}")

        # Clean up WebSocket bridge if active
        if active_handoff_id:
            logger.info(f"🔌 Cleaning up WebSocket bridge for handoff {active_handoff_id}")
            websocket_bridge.stop_bridge(active_handoff_id)
            try:
                conversation_store.mark_closed(active_handoff_id, "chat_end")
            except Exception as status_err:
                logger.warning(f"⚠️ Could not mark handoff closed on chat end: {status_err}")

        # Clear session state
        cl.user_session.set("active_handoff_conversation_id", None)
        cl.user_session.set("pending_handoff", None)
        cl.user_session.set("handoff_agent_name", None)
        cl.user_session.set("local_conversation_history", [])

    except Exception as e:
        logger.error(f"Error ending chat session: {str(e)}")


# Additional helper functions for the updated SDK patterns


def construct_search_query(user_data: Any) -> str:
    """Construct a search query string based on user data for the new index structure."""
    # Handle direct string input (when agent passes search query directly)
    if isinstance(user_data, str):
        logger.info(f"🔍 Using direct search query: '{user_data}'")
        return user_data.strip()

    # Handle dictionary input (for structured user profile data)
    if not isinstance(user_data, dict):
        logger.warning(f"⚠️ Unexpected user_data type: {type(user_data)}")
        return ""

    # If the caller already supplied an explicit search_query string, use it
    override_query = user_data.get("search_query")
    if isinstance(override_query, str) and override_query.strip():
        logger.info(
            f"🔍 Using caller-supplied search_query override: "
            f"'{override_query.strip()}'"
        )
        return override_query.strip()

    # NEW INDEX STRUCTURE: Two-tier search strategy
    # 1. APEX ID exact match (highest priority)
    # 2. Name + address combination (fallback)

    apex_id = user_data.get("apex_id", "").strip().upper()
    first_name = user_data.get("first_name", "").strip()
    last_name = user_data.get("last_name", "").strip()
    full_name = user_data.get("full_name", "").strip()
    address = user_data.get("address", "").strip()

    try:
        # STRATEGY 1: APEX ID exact match using filename
        if apex_id:
            # Clean APEX ID for filename matching
            clean_apex_id = "".join(c for c in apex_id if c.isalnum())
            # Search for exact filename match in metadata_storage_name field (OData syntax)
            query = f"metadata_storage_name eq '{clean_apex_id}.pdf'"
            logger.info(f"🔍 APEX ID exact match query: '{query}'")
            return query

        # STRATEGY 2: Name + address combination search
        query_parts = []

        # Add name components
        if full_name:
            # Use full name if available
            clean_name = " ".join(full_name.split())
            query_parts.append(f'"{clean_name}"')
        elif first_name and last_name:
            # Use first + last name
            query_parts.append(f'"{first_name}"')
            query_parts.append(f'"{last_name}"')
        elif first_name:
            # Use first name only
            query_parts.append(f'"{first_name}"')

        # Add address if available
        if address:
            # Clean address format to improve search matching
            clean_address = address.replace(",", " ").strip()
            clean_address = " ".join(clean_address.split())
            # Limit address length for search query
            if len(clean_address) > 100:
                clean_address = clean_address[:100]
            query_parts.append(f'"{clean_address}"')

        # If we have no specific search terms, return empty string
        if not query_parts:
            logger.info("🔍 No search criteria – skipping search query construction")
            return ""

        # Combine search terms with AND for more precise results
        query = " AND ".join(query_parts)
        logger.info(f"🔍 Name+address combination query: '{query}'")
        return query

    except Exception as e:
        logger.error(f"Error constructing search query: {str(e)}", exc_info=True)
        # On any unexpected error, skip the search
        return ""


def construct_search_filter(_user_data: Dict) -> str:
    """Return an empty string so we skip `$filter` by default."""
    return ""



def analyze_pdf_content_tool(sas_url: str, *, func_tool=None) -> str:
    """Extract and analyze PDF content to provide detailed summaries and explanations."""
    if not sas_url or not isinstance(sas_url, str):
        return "ERROR: Invalid SAS URL provided"

    try:
        # If a loop is already running we cannot invoke asyncio.run
        running_loop = asyncio.get_running_loop()
    except RuntimeError:
        running_loop = None

    try:
        if running_loop and running_loop.is_running():
            temp_loop = asyncio.new_event_loop()
            try:
                result = temp_loop.run_until_complete(extract_text_from_pdf(sas_url))
            finally:
                temp_loop.close()
        else:
            result = asyncio.run(extract_text_from_pdf(sas_url))

        if result and not result.startswith("ERROR:"):
            # Format the extracted text for analysis
            analysis_response = (
                f"**FULL PDF CONTENT EXTRACTED FOR ANALYSIS:**\n\n"
                f"Document URL: {sas_url[:50]}...\n"
                f"Content Length: {len(result)} characters\n\n"
                f"**DOCUMENT TEXT:**\n\n{result}\n\n"
                f"**ANALYSIS INSTRUCTIONS:** Please provide a comprehensive summary "
                f"focusing on:\n"
                f"- What this class action case is about\n"
                f"- Who is eligible to participate\n"
                f"- Important dates and deadlines\n"
                f"- Available settlement amounts or benefits\n"
                f"- Required actions or steps to take\n"
                f"- Contact information for questions\n\n"
                f"Present this information in a clear, easy-to-understand format "
                f"that helps the person understand their options and next steps."
            )
            return analysis_response
        else:
            return f"Unable to extract text from PDF: {result}"

    except Exception as e:
        logger.error(f"Error in analyze_pdf_content_tool: {e}")
        return f"ERROR: Failed to analyze PDF content: {str(e)}"


async def animate_thinking_message(
    msg: cl.Message,
    frames: List[str],
    interval: float = 0.5,
    activity_type: str = "thinking",
) -> None:
    """
    Animate a thinking message with accumulating dots that form a square.
    Dots build up from 1 to 8 (forming a square pattern) then reset.

    Args:
        msg: The Chainlit message to animate
        frames: List of animation frames to cycle through (dots accumulating)
        interval: Time between frame updates in seconds
        activity_type: Type of activity being performed
    """
    frame_index = 0

    try:
        logger.debug(f"Starting {activity_type} animation with {len(frames)} frames")
        status_message = "Processing your request..."

        while True:
            # Get current frame (dots forming square)
            current_frame = frames[frame_index % len(frames)]

            # Simple display - just show the dots and status
            content = f"{status_message} {current_frame}"

            try:
                msg.content = content
                await msg.update()
            except Exception as update_err:
                logger.warning(
                    f"Failed to update {activity_type} message: {update_err}"
                )

            frame_index += 1
            await asyncio.sleep(interval)

    except asyncio.CancelledError:
        logger.debug(f"{activity_type} animation cancelled - stopping gracefully")
        # Clear the animation message
        msg.content = ""
        await msg.update()
    except Exception as e:
        logger.error(f"{activity_type} animation error: {e}")
        # Stop animation on unexpected errors
# Notice request guardrail (fallback when tool calls are skipped)
_NOTICE_INTENT_TERMS = ("notice", "pdf", "document", "class action notice", "notice letter")


def _is_notice_intent(text: str) -> bool:
    if not text:
        return False
    lower = text.lower()
    return any(term in lower for term in _NOTICE_INTENT_TERMS)
