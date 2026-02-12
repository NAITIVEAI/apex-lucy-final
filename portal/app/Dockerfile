# Agent Portal Dockerfile - Dedicated file for agent portal
FROM python:3.12-slim

# Set timezone to Pacific
ENV TZ=America/Los_Angeles
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# Copy requirements
COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy all required Python modules
COPY agent_portal.py .
COPY callback_system.py .
COPY conversation_store.py .
COPY teams_integration.py .
COPY agentic_monitoring.py .
COPY user_functions.py .
COPY tracing_config.py .
COPY real_metrics_system.py .

# Copy optional modules (ignore if they don't exist)
# Optional utility module was sometimes present in older images; safe to skip if missing
# COPY azure_storage_utils.p[y] ./

# Copy startup script
COPY start_agent_portal.sh .
RUN chmod +x start_agent_portal.sh

# Copy templates and static directories
COPY templates ./templates
COPY static ./static

# Copy public directory with all assets
COPY public ./public

# Expose port 8001
EXPOSE 8001

# Environment variables
ENV AGENT_PORTAL_PORT=8001
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV DOCKER_CONTAINER=1

# Run the agent portal using the start script
CMD ["./start_agent_portal.sh"]
