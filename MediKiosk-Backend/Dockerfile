# syntax=docker/dockerfile:1.7
# Multi-stage production Dockerfile for MediKiosk-Backend
# Pinned base image - digest-pin in your registry mirror before going live
# Non-root user, security-hardened, minimal attack surface

FROM python:3.12.8-slim-bookworm AS builder

# Build-time environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /build

# Install build dependencies (minimal set)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy requirements and install Python dependencies
COPY requirements.txt .
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --upgrade pip==24.0 \
    && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt

# Runtime stage - minimal image with only runtime dependencies
FROM python:3.12.8-slim-bookworm AS runtime

# Runtime environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH" \
    HOME=/home/medikiosk \
    # Security: Limit Python's hash seed randomization (consistent across restarts)
    PYTHONHASHSEED=random \
    # Security: Ensure Python doesn't use .pyc files
    PYTHONDONTWRITEBYTECODE=1 \
    # Security: Don't allow arbitrary code execution from .pth files
    PYTHONNOUSERSITE=1

# Install runtime dependencies only (OCR libraries, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    # OCR support (Tesseract)
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-hin \
    tesseract-ocr-ben \
    # Image processing
    libmagic1 \
    # Security and monitoring tools
    curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean \
    && apt-get autoremove -y

# Create non-root user and group with specific UIDs
# UIDs must match volume mount permissions - adjust if using different filesystem
RUN groupadd --gid 10001 medikiosk \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin medikiosk \
    && mkdir -p /app/uploads/temp_scans /app/uploads/encrypted_vault \
    && mkdir -p /var/log/medikiosk \
    && chown -R medikiosk:medikiosk /app \
    && chown -R medikiosk:medikiosk /var/log/medikiosk

# Copy Python environment from builder
COPY --from=builder /opt/venv /opt/venv

# Set working directory
WORKDIR /app

# Copy application code with proper ownership
COPY --chown=medikiosk:medikiosk app ./app
COPY --chown=medikiosk:medikiosk alembic.ini ./
COPY --chown=medikiosk:medikiosk alembic ./alembic
COPY --chown=medikiosk:medikiosk uploads ./uploads

# Ensure proper permissions for application directories
RUN chmod -R 755 /app \
    && chmod -R 750 /app/uploads/encrypted_vault \
    && chmod -R 755 /app/uploads/temp_scans \
    && chmod -R 755 /var/log/medikiosk

# Switch to non-root user (security best practice)
USER medikiosk

# Health check (orchestrator will use this)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://127.0.0.1:8000/healthz || exit 1

# Expose application port (internal only - nginx handles external exposure)
EXPOSE 8000

# Metadata labels for orchestration and monitoring
LABEL maintainer="SIH26 MediTrack Team" \
      version="1.0.0" \
      description="MediKiosk-Backend - Healthcare Intake System" \
      org.opencontainers.image.title="MediKiosk-Backend" \
      org.opencontainers.image.description="FastAPI healthcare intake system with ABDM integration" \
      org.opencontainers.image.version="1.0.0" \
      org.opencontainers.image.vendor="SIH26 MediTrack"

# Production startup command
# Host/port MUST match orchestrator service definition
# --workers for uvicorn will be handled by replica count in docker-compose
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "info"]
