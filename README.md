# Sentinel

Sentinel turns recorded security footage into a searchable knowledge base. The system ingests CCTV‑style video, enriches it with multimodal analysis, and exposes a chat UI that answers natural‑language questions with precise timestamps.

## Architecture

```
┌────────────┐     ┌──────────────┐     ┌──────────────┐
│  Frontend  │────▶│  FastAPI API │────▶│ Elasticsearch │
└────────────┘     └──────────────┘     └──────────────┘
        ▲                  │
        │                  ▼
        │            Vertex AI + Ingestion
```

- **Frontend (`frontend/`)**: Vanilla HTML, CSS, and JS chat interface with an embedded video player.
- **Backend (`backend/`)**: FastAPI service that brokers search requests, enriches answers, and serves signed video URLs.
- **Ingestion (`ingestion/`)**: Command-line tools that analyze videos with Vertex AI, generate embeddings, and push chunks to Elasticsearch.
- **Scripts (`scripts/`)**: Operational helpers such as index provisioning.

## Quick Start

Prerequisites: Python 3.10+, Elasticsearch endpoint, Google Cloud credentials with Vertex AI and GCS access.

```bash
pip install -r requirements.txt
cp env.example .env

# Provision the search index (expects ELASTICSEARCH_* vars in .env)
python scripts/create_index.py

# Ingest a sample video (replace with your footage)
python -m ingestion.ingest --video-path data/demo.mp4

# Run the API locally
uvicorn backend.main:app --reload
```

Open `frontend/index.html` in a browser while the API is running to use the chat interface.

## Project Structure

```
backend/         FastAPI app, clients, and models
config.py        Shared configuration helpers
frontend/        Static UI (index.html, app.js, styles.css)
ingestion/       Video chunking and embedding pipeline
scripts/         Utility scripts (e.g., create_index.py)
tests/           Pytest suites for backend and ingestion
```

## Configuration

Copy `env.example` to `.env` and update the following variables to match your environment:

- `PROJECT_ID`, `LOCATION`: Google Cloud project settings.
- `ELASTICSEARCH_ENDPOINT`, `ELASTICSEARCH_API_KEY`: Search backend connection.
- `VIDEO_INDEX_NAME`: Target index for video chunks.
- `EMBEDDING_MODEL`, `EMBEDDING_DIMENSION`: Vertex AI embedding configuration.
- Storage and API keys for GCS or other backing services referenced in `config.py`.

`config.py` centralizes loading of these values so both the backend and ingestion pipeline stay in sync.

## Development Workflow

1. Add or update ingestion logic in `ingestion/` to process new footage.
2. Extend FastAPI routes or clients in `backend/` as needed.
3. Adjust frontend behavior in `frontend/app.js` and styles in `frontend/styles.css`.
4. Capture new tests under `tests/` and run `pytest` before shipping changes.
5. Use `deploy.sh` for the Cloud Run deployment path once you have validated updates locally.

## Additional Resources

- `DEPLOYMENT.md` – Cloud Run deployment checklist.
- `AGENTS.md`, `CLAUDE.md` – Notes for working with AI coding assistants.
- `video_summaries.json` – Sample metadata illustrating expected inputs.

Keep large media assets out of version control and store credentials in `.env` or your secret manager of choice.
