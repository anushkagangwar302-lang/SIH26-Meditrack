"""Celery application configuration for async background tasks.

Celery handles OCR processing, ABDM/HIS pushes, PDF generation, and scheduled
cleanup tasks. Uses Redis as both broker and result backend with separate DBs
for isolation.

Environment-specific:
- CELERY_BROKER_URL: Redis broker URL (DB 1 for broker)
- CELERY_RESULT_BACKEND: Redis result backend URL (DB 2 for results)
- Worker scaling: Configure worker count based on task queue depth
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Add the app directory to the Python path for worker imports
app_dir = Path(__file__).parent.parent
if str(app_dir) not in sys.path:
    sys.path.insert(0, str(app_dir))

from celery import Celery
from celery.schedules import crontab

# Get environment variables
REDIS_BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/1")
REDIS_RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/2")

# Create Celery app
celery_app = Celery(
    "medikiosk",
    broker=REDIS_BROKER_URL,
    backend=REDIS_RESULT_BACKEND,
    include=["workers.tasks"],
)

# Celery configuration
celery_app.conf.update(
    # Task settings
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes
    task_soft_time_limit=25 * 60,  # 25 minutes
    worker_prefetch_multiplier=1,  # Disable prefetch for fair task distribution
    worker_max_tasks_per_child=1000,  # Restart worker after 1000 tasks (memory safety)
    
    # Result settings
    result_expires=3600,  # Results expire after 1 hour
    result_extended=True,  # Allow result extension
    
    # Retry settings
    task_acks_late=True,  # Ack after task completes (not before)
    task_reject_on_worker_lost=True,  # Re-queue if worker dies
    
    # Rate limiting
    task_default_rate="100/m",  # Default rate limit per task type
    
    # Security
    worker_send_task_events=True,  # Enable task events for monitoring
    task_send_sent_event=True,  # Send task-sent events
    
    # Beat scheduler settings
    beat_schedule={
        # Purge temp files every hour
        "purge-temp-files": {
            "task": "workers.tasks.purge_temp_files",
            "schedule": crontab(minute=0),  # Every hour
        },
        # Retry failed OCR tasks every 15 minutes
        "retry-failed-ocr": {
            "task": "workers.tasks.retry_failed_ocr",
            "schedule": crontab(minute="*/15"),  # Every 15 minutes
        },
        # Health check every 5 minutes
        "worker-health-check": {
            "task": "workers.tasks.worker_health_check",
            "schedule": crontab(minute="*/5"),  # Every 5 minutes
        },
    },
)

# Environment-specific task routing
# In production, you might want different queues for different task types
celery_app.conf.task_routes = {
    "workers.tasks.process_ocr": {"queue": "ocr"},
    "workers.tasks.push_to_abdm": {"queue": "abdm"},
    "workers.tasks.generate_pdf": {"queue": "pdf"},
    "workers.tasks.purge_temp_files": {"queue": "maintenance"},
}

# Task annotations for specific task configurations
celery_app.conf.task_annotations = {
    "workers.tasks.process_ocr": {
        "rate_limit": "20/m",  # OCR is resource-intensive
        "time_limit": 15 * 60,  # 15 minutes for OCR
    },
    "workers.tasks.push_to_abdm": {
        "rate_limit": "50/m",  # ABDM API rate limits
        "retry_backoff": True,  # Exponential backoff
        "retry_kwargs": {"max_retries": 5},
    },
    "workers.tasks.generate_pdf": {
        "rate_limit": "30/m",  # PDF generation is CPU-intensive
        "time_limit": 10 * 60,  # 10 minutes for PDF
    },
}


if __name__ == "__main__":
    celery_app.start()
