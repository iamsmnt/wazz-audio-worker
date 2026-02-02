"""Celery configuration for Worker Service"""

from celery.schedules import crontab

# Serialization settings
task_serializer = "json"
result_serializer = "json"
accept_content = ["json"]
timezone = "UTC"
enable_utc = True

# Task routing
task_routes = {
    'tasks.process_audio_task': {'queue': 'audio_processing'},
    'tasks.cleanup_expired_files': {'queue': 'maintenance'}
}

# Task execution settings
task_acks_late = True  # Acknowledge task after completion, not before
worker_prefetch_multiplier = 1  # One task at a time per worker
task_track_started = True  # Track when task starts
task_time_limit = 3600  # 1 hour hard limit
task_soft_time_limit = 3300  # 55 minute soft limit

# Connection settings to prevent broker disconnects during long tasks
broker_heartbeat = 120  # Send heartbeat every 120 seconds (default: 60)
broker_connection_timeout = 30  # Connection timeout in seconds
worker_cancel_long_running_tasks_on_connection_loss = False  # Keep tasks running on disconnect

# Celery Beat schedule for periodic tasks
beat_schedule = {
    'cleanup-expired-files': {
        'task': 'tasks.cleanup_expired_files',
        'schedule': crontab(hour=2, minute=0),  # Run daily at 2 AM
    },
}
