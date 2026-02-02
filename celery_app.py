"""Celery application initialization for Worker Service"""

from celery import Celery
from wazz_shared.config import get_shared_settings

settings = get_shared_settings()

# Initialize Celery app
celery_app = Celery(
    'whazz_audio_worker',
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

# Load configuration from celery_config.py
celery_app.config_from_object('celery_config')

# Import tasks to register them with the Celery app
# This must be after celery_app is created to avoid circular imports
import tasks  # noqa: F401
