"""
Azure AI Agent Observability and Tracing Configuration
Implements comprehensive tracing for Lucy with maximum observability
"""
import os
import logging
from typing import Optional, Dict, Any
from functools import wraps
import time
import json
from contextlib import contextmanager

# Configure logging
logger = logging.getLogger("LucyTracing")

# Try to import OpenTelemetry components
TRACING_ENABLED = False
tracer = None
meter = None

try:
    from opentelemetry import trace, metrics
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME, SERVICE_VERSION
    from opentelemetry.trace import Status, StatusCode
    
    # Azure Monitor specific imports
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
        from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter, AzureMonitorMetricExporter
        AZURE_MONITOR_AVAILABLE = True
    except ImportError:
        logger.warning("Azure Monitor OpenTelemetry not available. Install with: pip install azure-monitor-opentelemetry")
        AZURE_MONITOR_AVAILABLE = False
        
    # Console exporter for local development
    from opentelemetry.sdk.trace.export import ConsoleSpanExporter
    from opentelemetry.sdk.metrics.export import ConsoleMetricExporter
    
    TRACING_ENABLED = True
    logger.info("✅ OpenTelemetry loaded successfully")
    
except ImportError as e:
    logger.warning(f"⚠️ OpenTelemetry not available: {e}")
    logger.warning("Install with: pip install opentelemetry-api opentelemetry-sdk azure-monitor-opentelemetry")

# Semantic conventions for Lucy
class LucyAttributes:
    """Semantic conventions for Lucy's tracing attributes"""
    # Agent namespace
    AGENT_ID = "lucy.agent.id"
    AGENT_TYPE = "lucy.agent.type"
    AGENT_VERSION = "lucy.agent.version"
    
    # User/Session namespace
    USER_ID = "lucy.user.id"
    USER_SESSION = "lucy.user.session"
    USER_AUTHENTICATED = "lucy.user.authenticated"
    USER_APEX_ID = "lucy.user.apex_id"
    
    # Authentication namespace
    AUTH_METHOD = "lucy.auth.method"
    AUTH_STATUS = "lucy.auth.status"
    AUTH_ATTEMPTS = "lucy.auth.attempts"
    
    # Dynamics 365 namespace
    DYNAMICS_ENTITY = "lucy.dynamics.entity"
    DYNAMICS_OPERATION = "lucy.dynamics.operation"
    DYNAMICS_QUERY = "lucy.dynamics.query"
    DYNAMICS_RETRY_COUNT = "lucy.dynamics.retry_count"
    DYNAMICS_RECORDS_FOUND = "lucy.dynamics.records_found"
    DYNAMICS_AUTO_DISCOVERED = "lucy.dynamics.auto_discovered"
    
    # Disbursement namespace
    DISBURSEMENT_COUNT = "lucy.disbursement.count"
    DISBURSEMENT_TOTAL_AMOUNT = "lucy.disbursement.total_amount"
    DISBURSEMENT_MEMBER_ID = "lucy.disbursement.member_id"
    
    # Tool namespace
    TOOL_NAME = "lucy.tool.name"
    TOOL_TYPE = "lucy.tool.type"
    TOOL_SUCCESS = "lucy.tool.success"
    TOOL_ERROR = "lucy.tool.error"
    
    # AI/Model namespace
    MODEL_NAME = "lucy.model.name"
    MODEL_TOKENS_PROMPT = "lucy.model.tokens.prompt"
    MODEL_TOKENS_COMPLETION = "lucy.model.tokens.completion"
    MODEL_LATENCY_MS = "lucy.model.latency_ms"
    
    # Handoff namespace
    HANDOFF_REASON = "lucy.handoff.reason"
    HANDOFF_TO = "lucy.handoff.to"
    HANDOFF_SUCCESS = "lucy.handoff.success"
    
    # Error namespace
    ERROR_TYPE = "lucy.error.type"
    ERROR_MESSAGE = "lucy.error.message"
    ERROR_RECOVERY_ATTEMPTED = "lucy.error.recovery_attempted"

class TracingConfig:
    """Configuration for Lucy's tracing system"""
    
    def __init__(self):
        self.enabled = TRACING_ENABLED
        self.service_name = "lucy-ai-agent"
        self.service_version = os.getenv("LUCY_VERSION", "1.0.0")
        self.environment = os.getenv("ENVIRONMENT", "development")
        self.azure_monitor_connection_string = None
        self.export_to_console = os.getenv("TRACE_TO_CONSOLE", "false").lower() == "true"
        self.export_to_azure = os.getenv("TRACE_TO_AZURE", "true").lower() == "true"
        self.content_recording_enabled = os.getenv("AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED", "false").lower() == "true"
        
    def initialize(self, project_client=None):
        """Initialize tracing with Azure Monitor and/or console exporters"""
        global tracer, meter
        
        if not self.enabled:
            logger.warning("⚠️ Tracing is disabled - OpenTelemetry not available")
            return False
            
        try:
            # Create resource with service information
            resource = Resource.create({
                SERVICE_NAME: self.service_name,
                SERVICE_VERSION: self.service_version,
                "environment": self.environment,
                "lucy.instance.id": os.getenv("WEBSITE_INSTANCE_ID", "local"),
            })
            
            # Initialize tracer provider
            tracer_provider = TracerProvider(resource=resource)
            
            # Add exporters based on configuration
            exporters_added = False
            
            # Azure Monitor exporter
            if self.export_to_azure and AZURE_MONITOR_AVAILABLE:
                try:
                    # Try to get connection string from project client
                    if project_client and hasattr(project_client, 'telemetry'):
                        try:
                            self.azure_monitor_connection_string = project_client.telemetry.get_connection_string()
                            logger.info("✅ Retrieved Application Insights connection string from project")
                        except Exception as e:
                            logger.warning(f"Could not get connection string from project: {e}")
                    
                    # Fall back to environment variable
                    if not self.azure_monitor_connection_string:
                        self.azure_monitor_connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
                    
                    if self.azure_monitor_connection_string:
                        # Configure Azure Monitor
                        configure_azure_monitor(
                            connection_string=self.azure_monitor_connection_string,
                            resource=resource,
                            enable_live_metrics=True,
                        )
                        logger.info("✅ Azure Monitor tracing configured")
                        exporters_added = True
                    else:
                        logger.warning("⚠️ No Application Insights connection string found")
                except Exception as e:
                    logger.error(f"❌ Failed to configure Azure Monitor: {e}")
            
            # Console exporter for local development
            if self.export_to_console:
                console_exporter = ConsoleSpanExporter()
                tracer_provider.add_span_processor(BatchSpanProcessor(console_exporter))
                logger.info("✅ Console tracing configured")
                exporters_added = True
            
            if not exporters_added:
                logger.warning("⚠️ No trace exporters configured - traces will not be exported")
            
            # Set the global tracer provider
            trace.set_tracer_provider(tracer_provider)
            tracer = trace.get_tracer(__name__, self.service_version)
            
            # Initialize metrics
            self._initialize_metrics(resource)
            
            logger.info(f"✅ Tracing initialized for {self.service_name} v{self.service_version}")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize tracing: {e}")
            return False
    
    def _initialize_metrics(self, resource):
        """Initialize metrics collection"""
        global meter
        
        try:
            readers = []
            
            # Azure Monitor metrics
            if self.export_to_azure and AZURE_MONITOR_AVAILABLE and self.azure_monitor_connection_string:
                azure_metric_exporter = AzureMonitorMetricExporter(
                    connection_string=self.azure_monitor_connection_string
                )
                readers.append(PeriodicExportingMetricReader(azure_metric_exporter))
            
            # Console metrics for development
            if self.export_to_console:
                console_metric_exporter = ConsoleMetricExporter()
                readers.append(PeriodicExportingMetricReader(console_metric_exporter))
            
            if readers:
                meter_provider = MeterProvider(resource=resource, metric_readers=readers)
                metrics.set_meter_provider(meter_provider)
                meter = metrics.get_meter(__name__, self.service_version)
                logger.info("✅ Metrics collection initialized")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize metrics: {e}")

# Global configuration instance
tracing_config = TracingConfig()

# Decorator for tracing functions
def trace_function(name: str = None, **attributes):
    """Decorator to add tracing to functions"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            if not tracer:
                return await func(*args, **kwargs)
                
            span_name = name or f"{func.__module__}.{func.__name__}"
            with tracer.start_as_current_span(span_name) as span:
                # Add custom attributes
                for key, value in attributes.items():
                    span.set_attribute(key, value)
                
                # Add function context
                span.set_attribute("function.module", func.__module__)
                span.set_attribute("function.name", func.__name__)
                
                try:
                    result = await func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    span.set_attribute(LucyAttributes.ERROR_TYPE, type(e).__name__)
                    span.set_attribute(LucyAttributes.ERROR_MESSAGE, str(e))
                    raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            if not tracer:
                return func(*args, **kwargs)
                
            span_name = name or f"{func.__module__}.{func.__name__}"
            with tracer.start_as_current_span(span_name) as span:
                # Add custom attributes
                for key, value in attributes.items():
                    span.set_attribute(key, value)
                
                # Add function context
                span.set_attribute("function.module", func.__module__)
                span.set_attribute("function.name", func.__name__)
                
                try:
                    result = func(*args, **kwargs)
                    span.set_status(Status(StatusCode.OK))
                    return result
                except Exception as e:
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    span.record_exception(e)
                    span.set_attribute(LucyAttributes.ERROR_TYPE, type(e).__name__)
                    span.set_attribute(LucyAttributes.ERROR_MESSAGE, str(e))
                    raise
        
        # Return appropriate wrapper based on function type
        import asyncio
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

@contextmanager
def trace_span(name: str, **attributes):
    """Context manager for creating spans"""
    if not tracer:
        yield None
        return
        
    with tracer.start_as_current_span(name) as span:
        for key, value in attributes.items():
            span.set_attribute(key, value)
        yield span

# Helper functions for common tracing scenarios
def trace_dynamics_query(entity: str, operation: str, query: str = None):
    """Create a span for Dynamics 365 operations"""
    attributes = {
        LucyAttributes.DYNAMICS_ENTITY: entity,
        LucyAttributes.DYNAMICS_OPERATION: operation,
    }
    if query:
        attributes[LucyAttributes.DYNAMICS_QUERY] = query[:500]  # Truncate long queries
    
    return trace_span(f"dynamics.{operation}", **attributes)

def trace_tool_execution(tool_name: str, tool_type: str = "function"):
    """Create a span for tool execution"""
    return trace_span(f"tool.{tool_name}", **{
        LucyAttributes.TOOL_NAME: tool_name,
        LucyAttributes.TOOL_TYPE: tool_type,
    })

def trace_authentication(method: str, user_id: str = None):
    """Create a span for authentication attempts"""
    attributes = {
        LucyAttributes.AUTH_METHOD: method,
    }
    if user_id:
        attributes[LucyAttributes.USER_ID] = user_id
    
    return trace_span("authentication", **attributes)

def record_metric(name: str, value: float, unit: str = "1", **attributes):
    """Record a metric value"""
    if not meter:
        return
        
    try:
        # Create or get counter/histogram based on name pattern
        if "count" in name or "total" in name:
            counter = meter.create_counter(name, unit=unit, description=f"Lucy metric: {name}")
            counter.add(value, attributes)
        else:
            histogram = meter.create_histogram(name, unit=unit, description=f"Lucy metric: {name}")
            histogram.record(value, attributes)
    except Exception as e:
        logger.error(f"Failed to record metric {name}: {e}")

# Export key components
__all__ = [
    'tracing_config',
    'LucyAttributes',
    'trace_function',
    'trace_span',
    'trace_dynamics_query',
    'trace_tool_execution', 
    'trace_authentication',
    'record_metric',
    'TRACING_ENABLED',
]