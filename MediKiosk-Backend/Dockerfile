# syntax=docker/dockerfile:1.7
# Pinned base. Digest-pin in your registry mirror before going live.
FROM python:3.12.8-slim-bookworm AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip \
    && /opt/venv/bin/pip install -r requirements.txt

FROM python:3.12.8-slim-bookworm AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    HOME=/home/medikiosk

# Non-root. UID is environment-specific if you bind-mount volumes — keep in sync with compose.
RUN groupadd --gid 10001 medikiosk \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin medikiosk \
    && mkdir -p /app/uploads/temp_scans /app/uploads/encrypted_vault \
    && chown -R medikiosk:medikiosk /app

COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY --chown=medikiosk:medikiosk app ./app
COPY --chown=medikiosk:medikiosk uploads ./uploads

USER medikiosk
EXPOSE 8000
# Host/port MUST match orchestrator service definition.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
