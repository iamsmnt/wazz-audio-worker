# Dockerfile for Wazz Audio Worker Service
# This creates a containerized Celery worker for audio processing

FROM python:3.10-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    postgresql-client \
    libsndfile1 \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy shared library first
COPY wazz-audio-shared /app/wazz-audio-shared

# Install shared library
RUN pip install --no-cache-dir /app/wazz-audio-shared

# Copy worker-service files
COPY wazz-audio-worker/requirements.txt .
COPY wazz-audio-worker/celery_app.py .
COPY wazz-audio-worker/tasks.py .
COPY wazz-audio-worker/celery_config.py .

# Install worker dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Create directories for file storage
RUN mkdir -p /app/uploads /app/processed_audio

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV CELERY_BROKER_URL=amqp://guest:guest@rabbitmq:5672//
ENV DATABASE_URL=postgresql://postgres:postgres@postgres:5432/whazz_audio

# Run Celery worker
CMD ["celery", "-A", "celery_app", "worker", "--loglevel=info", "-Q", "audio_processing,maintenance"]
