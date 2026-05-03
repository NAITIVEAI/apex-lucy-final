# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set timezone to Pacific
ENV TZ=America/Los_Angeles
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# Set working directory
WORKDIR /app

# Copy requirements.txt and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --force-reinstall --pre -r requirements.txt

# Copy the application code
COPY . .

# Explicitly ensure callback_system.py is present (fix for import issue)
COPY callback_system.py /app/callback_system.py

# Ensure conversation_store.py is present
COPY conversation_store.py /app/conversation_store.py

# Verify callback_system.py and conversation_store.py exist and set Python path
RUN ls -la /app/callback_system.py /app/conversation_store.py && \
    echo "callback_system.py file size:" && \
    wc -c /app/callback_system.py && \
    echo "conversation_store.py file size:" && \
    wc -c /app/conversation_store.py && \
    python -c "import sys; sys.path.insert(0, '/app'); import callback_system; import conversation_store; print('✅ callback_system and conversation_store import successfully in Docker build')"

# Ensure Python can find our modules
ENV PYTHONPATH=/app


# Expose ports for Chainlit, health checks, and the FastAPI HTTP wrapper
# that registers behind the Foundry AI Gateway (lucy_core.http_app).
EXPOSE 8000 8080 8002

# Set environment variables for Chainlit and Azure authentication
ENV CHAINLIT_HOST=0.0.0.0
ENV CHAINLIT_PORT=8000
ENV CHAINLIT_HIDE_BRANDING=true
ENV WEBSITES_PORT=8000
ENV HEALTH_CHECK_PORT=8080
ENV OTEL_SERVICE_NAME=lucy-agent
ENV OTEL_RESOURCE_ATTRIBUTES=service.name=lucy-agent,service.version=1.0.0
ENV OTEL_PYTHON_LOGGING_AUTO_INSTRUMENTATION_ENABLED=true
ENV LUCY_CHAINLIT_ENABLED=true

# Make start script executable
RUN chmod +x start_services.sh health_server.py

# Command to run both services
# For Azure Container Apps, use the start script to run both services
CMD ["./start_services.sh"]
