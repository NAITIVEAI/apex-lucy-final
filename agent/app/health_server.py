#!/usr/bin/env python3
"""
Health check server for Lucy AI Assistant in Azure Container Apps.

This runs a simple HTTP server on port 8080 to provide health check endpoints
while the main Chainlit app runs on port 8000.
"""

import os
import sys
import json
import asyncio
import logging
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime, timezone
from urllib.parse import urlparse

# Import health check handlers from apex
try:
    from apex import health_check_handler, readiness_check_handler, liveness_check_handler
except ImportError:
    print("Error: Could not import health check handlers from apex.py")
    sys.exit(1)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("HealthServer")

class HealthCheckHandler(BaseHTTPRequestHandler):
    """HTTP request handler for health check endpoints"""
    
    def do_GET(self):
        """Handle GET requests to health check endpoints"""
        path = urlparse(self.path).path
        
        # Route to appropriate handler
        if path == "/health":
            self._handle_health()
        elif path == "/health/ready":
            self._handle_readiness()
        elif path == "/health/live":
            self._handle_liveness()
        else:
            self.send_error(404, "Not Found")
    
    def _handle_health(self):
        """Basic health check"""
        try:
            # Run the async handler in sync context
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(health_check_handler())
            
            self._send_json_response(200, result)
        except Exception as e:
            logger.error(f"Health check error: {e}")
            self._send_json_response(503, {"status": "error", "error": str(e)})
    
    def _handle_readiness(self):
        """Readiness check"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(readiness_check_handler())
            
            # Determine status code based on readiness
            status_code = 200 if result.get("status") == "ready" else 503
            self._send_json_response(status_code, result)
        except Exception as e:
            logger.error(f"Readiness check error: {e}")
            self._send_json_response(503, {"status": "error", "error": str(e)})
    
    def _handle_liveness(self):
        """Liveness check"""
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(liveness_check_handler())
            
            # Determine status code based on health
            status_code = 503 if result.get("status") == "unhealthy" else 200
            self._send_json_response(status_code, result)
        except Exception as e:
            logger.error(f"Liveness check error: {e}")
            self._send_json_response(503, {"status": "error", "error": str(e)})
    
    def _send_json_response(self, status_code, data):
        """Send JSON response"""
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def log_message(self, format, *args):
        """Override to reduce log verbosity"""
        # Only log non-200 responses
        if not (200 <= int(args[1]) < 300):
            logger.info(f"{self.address_string()} - {format % args}")

def run_health_server(port=8080):
    """Run the health check HTTP server"""
    server_address = ('', port)
    httpd = HTTPServer(server_address, HealthCheckHandler)
    
    logger.info(f"🏥 Health check server listening on port {port}")
    logger.info("Health check endpoints:")
    logger.info("  - GET /health        - Basic health check")
    logger.info("  - GET /health/ready  - Readiness check")
    logger.info("  - GET /health/live   - Liveness check")
    
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Health check server shutting down...")
        httpd.shutdown()

if __name__ == "__main__":
    # Get port from environment or use default
    port = int(os.getenv("HEALTH_CHECK_PORT", "8080"))
    run_health_server(port)