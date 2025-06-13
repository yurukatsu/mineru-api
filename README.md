# MinerU API

MinerU API is a PDF processing API using [MinerU](https://github.com/opendatalab/MinerU). It provides asynchronous processing with Celery and Redis to convert PDF files to Markdown and extract images.

## Features

- **Asynchronous PDF Processing**: Background PDF processing with Celery workers
- **Progress Tracking**: Real-time processing progress and status monitoring
- **Multiple Output Formats**: Markdown, JSON, extracted images, analysis PDFs
- **File Downloads**: Individual or ZIP batch download of processing results
- **Worker Management**: Celery worker monitoring and management

## System Requirements

- Python 3.12+
- Docker & Docker Compose
- 4GB+ RAM (for ML model execution)

## Setup

### 1. Clone Repository

```bash
git clone <repository-url>
cd mineru-api
```

### 2. Environment Configuration

```bash
cp .env.example .env
```

Edit the `.env` file to change ports if needed:

```env
REDIS_PORT=6380
FASTAPI_PORT=8001
```

### 3. Start with Docker Compose

```bash
docker compose up --build
```

Initial startup may take time as MinerU ML models will be downloaded.

## Usage

### API Endpoints

#### Start PDF Processing
```bash
curl -X POST "http://localhost:8000/start" \
  -F "file=@your-document.pdf"
```

Response:
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued",
  "message": "Task started successfully"
}
```

#### Check Processing Status
```bash
curl "http://localhost:8000/status/{task_id}"
```

Response:
```json
{
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "status": "processing",
  "progress": 0.65,
  "stage": "Processing OCR pipeline"
}
```

#### Download Results

Download all results as ZIP:
```bash
curl -O "http://localhost:8000/download/{task_id}"
```

Download specific files individually:
```bash
curl -O "http://localhost:8000/download/{task_id}/markdown"
curl -O "http://localhost:8000/download/{task_id}/content_list"
```

#### Other Endpoints

- `GET /tasks` - List active tasks
- `GET /workers` - Celery worker status
- `DELETE /stop/{task_id}` - Cancel task
- `GET /images/{task_id}` - List extracted images

### Processing Results

PDF processing generates the following files:

- **markdown**: Converted Markdown file
- **content_list**: Structured JSON content
- **middle_json**: Intermediate processing results JSON
- **model_pdf**: AI model analysis result PDF
- **layout_pdf**: Layout analysis result PDF
- **spans_pdf**: Text span analysis result PDF
- **images/**: Extracted image files

### Processing Status

- `queued` - Waiting for processing
- `processing` - Currently processing
- `completed` - Processing completed
- `failed` - Processing failed
- `cancelled` - Processing cancelled

## Architecture

This API consists of the following components:

- **FastAPI App** (`api/app.py`) - REST API server
- **Celery Worker** - Background PDF processing
- **Redis** - Message broker and result storage
- **PDF Processor** (`api/services/pdf_processor.py`) - MinerU wrapper

## Development

### Local Development Environment

```bash
# Install dependencies
uv sync

# Start development server
uv run uvicorn api.app:app --reload

# Start Celery worker (separate terminal)
uv run celery -A api.app.celery_app worker --loglevel=info
```

### Code Quality Check

```bash
uv run ruff check
uv run ruff format
```

## Troubleshooting

### Common Issues

1. **Out of Memory Error**
   - Increase memory allocated to Docker containers (recommended: 6GB+)

2. **Processing doesn't start**
   - Check if Redis is running properly
   ```bash
   docker compose logs redis
   ```

3. **Worker not responding**
   - Check Celery worker logs
   ```bash
   docker compose logs worker
   ```

4. **Model download error**
   - Check internet connection
   - Wait for completion on first startup

### Check Logs

```bash
# All container logs
docker compose logs

# Specific service logs
docker compose logs app
docker compose logs worker
docker compose logs redis
```

## License

This project follows MinerU's license.