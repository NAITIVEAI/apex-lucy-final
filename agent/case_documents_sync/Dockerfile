FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY app/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY case_documents_sync /app/case_documents_sync

RUN useradd --create-home --shell /usr/sbin/nologin syncworker
USER syncworker

CMD ["python", "-m", "case_documents_sync.sync"]
