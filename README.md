# Wazz Audio - Worker Service

**Standalone Celery Worker Service for Audio Processing**

This is a dedicated microservice that handles background audio processing tasks. It's completely separated from the API service to enable independent scaling and deployment.

## Features

- **Audio Processing**: Noise reduction using ClearVoice/MossFormer2
- **Scheduled Cleanup**: Automatic removal of expired files
- **Independent Scaling**: Scale workers separately from API
- **Task Queuing**: Uses RabbitMQ for reliable task distribution
- **Database Integration**: Shares database with API via shared-lib
- **Progress Tracking**: Real-time job progress updates

## Architecture

```
┌─────────────┐      ┌──────────────┐      ┌────────────────┐
│   Backend   │─────▶│   RabbitMQ   │─────▶│ Worker Service │
│  (FastAPI)  │      │ (Message     │      │   (Celery)     │
└─────────────┘      │  Broker)     │      └────────────────┘
                     └──────────────┘              │
                                                   │
                     ┌──────────────┐              │
                     │  PostgreSQL  │◀─────────────┘
                     │  (Shared DB) │
                     └──────────────┘
```

## Installation

### 1. Prerequisites

- Python 3.10+
- RabbitMQ running (or Docker)
- PostgreSQL database (same as backend)
- Shared library installed

### 2. Setup

```bash
cd worker-service

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install shared library first
pip install -e ../shared-lib

# Install worker dependencies
pip install -r requirements.txt

# Create .env file
cp .env.example .env
# Edit .env with your configuration
```

### 3. Configure Environment

Update [.env](.env) with your settings:

```env
# Database (same as backend)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/whazz_audio

# RabbitMQ
CELERY_BROKER_URL=amqp://guest:guest@localhost:5672//
CELERY_RESULT_BACKEND=db+postgresql://postgres:postgres@localhost:5432/whazz_audio

# Storage
USE_LOCAL_STORAGE=true
UPLOAD_DIR=./uploads
OUTPUT_DIR=./processed_audio

# Audio Processing
CLEARVOICE_MODEL_NAME=MossFormer2_SE_48K
MAX_FILE_SIZE_MB=100
```

## Running the Workers

### Basic Worker

Process audio files:

```bash
celery -A celery_app worker --loglevel=info -Q audio_processing
```

### Maintenance Worker

Handle cleanup tasks:

```bash
celery -A celery_app worker --loglevel=info -Q maintenance
```

### All Queues

Process all task types:

```bash
celery -A celery_app worker --loglevel=info -Q audio_processing,maintenance
```

### With Concurrency Control

```bash
# 4 concurrent workers
celery -A celery_app worker --loglevel=info --concurrency=4 -Q audio_processing

# Auto-scale between 2-8 workers
celery -A celery_app worker --loglevel=info --autoscale=8,2 -Q audio_processing
```

## Scheduled Tasks (Celery Beat)

Run periodic tasks (cleanup expired files):

```bash
celery -A celery_app beat --loglevel=info
```

For production, run beat in a separate process:

```bash
# Terminal 1: Worker
celery -A celery_app worker --loglevel=info -Q audio_processing,maintenance

# Terminal 2: Beat scheduler
celery -A celery_app beat --loglevel=info
```

## Tasks

### 1. Audio Processing Task

**Task Name**: `tasks.process_audio_task`

**Queue**: `audio_processing`

**Description**: Processes audio files with ClearVoice noise reduction

**Parameters**:
- `job_id` (str): UUID of the AudioProcessingJob

**Flow**:
1. Fetch job from database
2. Update status to "processing"
3. Validate input file exists
4. Initialize ClearVoice model
5. Process audio file
6. Save output file
7. Update job status to "completed" or "failed"
8. Track usage statistics

### 2. Cleanup Task

**Task Name**: `tasks.cleanup_expired_files`

**Queue**: `maintenance`

**Description**: Removes expired files and database records

**Schedule**: Daily at 2:00 AM UTC

**Actions**:
- Deletes expired input files
- Deletes expired output files
- Removes database records for expired jobs

## Monitoring

### Celery Flower

Monitor workers with Flower dashboard:

```bash
pip install flower
celery -A celery_app flower --port=5555
```

Access at: http://localhost:5555

### Check Worker Status

```bash
# List active workers
celery -A celery_app inspect active

# List scheduled tasks
celery -A celery_app inspect scheduled

# Worker statistics
celery -A celery_app inspect stats
```

## Docker Deployment

### Build Image

```bash
docker build -t wazz-audio-worker:latest .
```

### Run Container

```bash
docker run -d \
  --name wazz-worker \
  --env-file .env \
  -v $(pwd)/uploads:/app/uploads \
  -v $(pwd)/processed_audio:/app/processed_audio \
  wazz-audio-worker:latest
```

### Docker Compose

See [docker-compose.yml](docker-compose.yml) for complete setup with RabbitMQ.

## Scaling

### Horizontal Scaling

Run multiple worker instances:

```bash
# Instance 1
celery -A celery_app worker --loglevel=info -Q audio_processing -n worker1@%h

# Instance 2
celery -A celery_app worker --loglevel=info -Q audio_processing -n worker2@%h

# Instance 3
celery -A celery_app worker --loglevel=info -Q audio_processing -n worker3@%h
```

### Kubernetes Deployment

Deploy multiple worker pods:

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: wazz-audio-worker
spec:
  replicas: 3  # Scale as needed
  template:
    spec:
      containers:
      - name: worker
        image: wazz-audio-worker:latest
        command: ["celery", "-A", "celery_app", "worker", "-Q", "audio_processing"]
```

## Configuration

### Worker Settings

Edit [celery_config.py](celery_config.py):

```python
# Task execution
task_acks_late = True  # Reliability
worker_prefetch_multiplier = 1  # One task at a time
task_time_limit = 3600  # 1 hour max
task_soft_time_limit = 3300  # 55 minute warning

# Connection reliability
broker_heartbeat = 120  # Heartbeat every 120s
worker_cancel_long_running_tasks_on_connection_loss = False
```

### Queue Routing

Tasks are routed to specific queues:

```python
task_routes = {
    'tasks.process_audio_task': {'queue': 'audio_processing'},
    'tasks.cleanup_expired_files': {'queue': 'maintenance'}
}
```

## Troubleshooting

### Worker Not Connecting to RabbitMQ

```bash
# Check RabbitMQ is running
docker ps | grep rabbitmq

# Test connection
python3 -c "from wazz_shared.config import get_shared_settings; s=get_shared_settings(); print(s.celery_broker_url)"

# Check RabbitMQ logs
docker logs rabbitmq
```

### Database Connection Issues

```bash
# Test database connection
python3 -c "from wazz_shared.database import engine; from sqlalchemy import text; engine.connect().execute(text('SELECT 1'))"
```

### Tasks Not Processing

```bash
# Check queues
celery -A celery_app inspect active_queues

# Purge stuck tasks (careful!)
celery -A celery_app purge

# Check task routes
celery -A celery_app inspect registered
```

### ClearVoice Model Issues

```bash
# Verify model is installed
python3 -c "from clearvoice import ClearVoice; cv = ClearVoice(task='speech_enhancement', model_names=['MossFormer2_SE_48K']); print('Model loaded!')"

# Check model directory
ls ~/.cache/torch/hub/checkpoints/
```

## Production Best Practices

1. **Run Beat Separately**: Only one beat scheduler per deployment
2. **Use Supervisor/Systemd**: Auto-restart workers on failure
3. **Monitor Memory**: Audio processing is memory-intensive
4. **Set Timeouts**: Prevent hung tasks
5. **Log Aggregation**: Centralize logs for debugging
6. **Health Checks**: Monitor worker health
7. **Graceful Shutdown**: Use `--max-tasks-per-child`

### Systemd Service Example

Create `/etc/systemd/system/wazz-worker.service`:

```ini
[Unit]
Description=Wazz Audio Worker Service
After=network.target rabbitmq.service postgresql.service

[Service]
Type=simple
User=wazz
WorkingDirectory=/opt/wazz-audio/worker-service
Environment="PATH=/opt/wazz-audio/worker-service/venv/bin"
ExecStart=/opt/wazz-audio/worker-service/venv/bin/celery -A celery_app worker --loglevel=info -Q audio_processing,maintenance
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable wazz-worker
sudo systemctl start wazz-worker
sudo systemctl status wazz-worker
```

## Development

### Running Tests

```bash
# Unit tests
pytest tests/

# Integration tests
pytest tests/integration/
```

### Adding New Tasks

1. Define task in [tasks.py](tasks.py):

```python
@celery_app.task(name='tasks.my_new_task')
def my_new_task(param1, param2):
    # Your task logic
    return result
```

2. Add route in [celery_config.py](celery_config.py):

```python
task_routes = {
    'tasks.my_new_task': {'queue': 'my_queue'},
}
```

3. Call from backend:

```python
from tasks import my_new_task
result = my_new_task.delay(param1, param2)
```

## Dependencies

- **celery**: Task queue framework
- **clearvoice**: Audio processing library
- **wazz-shared**: Shared models, database, and configuration
- **RabbitMQ**: Message broker (external)
- **PostgreSQL**: Database (external, shared with backend)

## File Structure

```
worker-service/
├── celery_app.py          # Celery initialization
├── tasks.py               # Task definitions
├── celery_config.py       # Celery configuration
├── requirements.txt       # Python dependencies
├── .env.example           # Environment template
├── .env                   # Environment variables (create this)
├── Dockerfile             # Docker image
├── docker-compose.yml     # Docker orchestration
└── README.md             # This file
```

## Related Documentation

- [Backend API Documentation](../backend/README.md)
- [Shared Library Documentation](../shared-lib/README.md)
- [Deployment Guide](../DEPLOYMENT.md)
- [Architecture Overview](../ARCHITECTURE.md)

## Support

For issues or questions:
1. Check this README
2. Review [Celery Documentation](https://docs.celeryproject.org/)
3. Check [ClearVoice Documentation](https://github.com/modelscope/ClearerVoice-Studio)

## License

Same as main project.
