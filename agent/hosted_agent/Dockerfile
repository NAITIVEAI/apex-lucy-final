FROM python:3.12-slim

ENV TZ=America/Los_Angeles
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

COPY agent/app/requirements.txt /tmp/app-requirements.txt
COPY agent/hosted_agent/requirements.txt /tmp/hosted-requirements.txt
RUN pip install --no-cache-dir --force-reinstall --pre \
    -r /tmp/app-requirements.txt \
    -r /tmp/hosted-requirements.txt

COPY agent/app/ /app/
COPY agent/hosted_agent/ /app/hosted_agent/

ENV PYTHONPATH=/app
ENV PORT=8088
ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV CURL_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt
ENV CHAINLIT_HIDE_BRANDING=true
ENV OTEL_SERVICE_NAME=lucy-hosted-agent
ENV OTEL_RESOURCE_ATTRIBUTES=service.name=lucy-hosted-agent,service.version=1.0.0
ENV AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED=false

EXPOSE 8088

CMD ["python", "-m", "hosted_agent.app"]
