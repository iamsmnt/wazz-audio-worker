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
COPY shared-lib /app/shared-lib

# Install shared library
RUN pip install --no-cache-dir -e /app/shared-lib

# Copy worker-service files
COPY worker-service/requirements.txt .
COPY worker-service/celery_app.py .
COPY worker-service/tasks.py .
COPY worker-service/celery_config.py .

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
