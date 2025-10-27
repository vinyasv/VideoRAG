# Repository Guidelines

## Project Structure & Module Organization
The repo centers on `backend/` (FastAPI app, Elasticsearch and Vertex clients), `ingestion/` (chunking and ingestion pipeline), and `frontend/` (vanilla HTML/JS UI). Supporting utilities live in `scripts/` (e.g., `create_index.py` for Elasticsearch provisioning) and deployment automation in `deploy.sh` and `Dockerfile`. Shared configuration is handled in `config.py`, while credentials and run-time knobs should be mirrored from `env.example` into a local `.env`. Keep large media assets outside version control; check `video_summaries.json` for sample metadata.

## Build, Test, and Development Commands
Install dependencies with `pip install -r requirements.txt`, then copy environment defaults via `cp env.example .env`. Bootstrap search infrastructure using `python scripts/create_index.py`, ingest footage with `python -m ingestion.ingest --video-path data/demo.mp4`, and start the API locally through `uvicorn backend.main:app --reload`. The frontend can be opened directly from `frontend/index.html` once the backend is running. Run Python tests (when present) with `pytest`. Use `./deploy.sh` for the Cloud Run path; it expects authenticated `gcloud` and a populated `.env`.

## Coding Style & Naming Conventions
Python modules follow PEP 8: four-space indentation, `snake_case` functions, and `PascalCase` for Pydantic models. Favor type hints and async-friendly patterns when touching FastAPI endpoints. Keep ingestion helpers pure and composable; co-locate private helpers beside their public entrypoints. Frontend scripts in `frontend/app.js` use ES modules and descriptive camelCase. Before submitting, run `python -m compileall backend ingestion` to catch syntax errors if formatting tools are unavailable in the environment.

## Testing Guidelines
Add unit or integration suites under `tests/`, mirroring the ingestion/backend division (e.g., `tests/test_ingestion_pipeline.py`). Prefer `pytest` fixtures for Elasticsearch and Vertex mocks, and capture representative chunks of CCTV metadata in lightweight JSON fixtures. Tests should assert both semantic relevance scores and timestamp normalization. Document non-trivial scenarios in docstrings and include sample commands (`pytest -k temporal`) in PR descriptions when new coverage is introduced.

## Commit & Pull Request Guidelines
Follow the existing Git history: concise, capitalized, present-tense subjects (`Prepare for production deployment`). Group related changes into single commits and reference scripts or modules touched. Pull requests should summarize user-facing effects, list validation steps (commands run, test output), and link to tracking issues or deployment notes. Include screenshots or terminal snippets when frontend behavior or ingest outputs change, and call out any manual GCP or Elasticsearch steps reviewers must perform.

## Security & Configuration Tips
Never commit service keys (`sentinel-key.json`) or raw footage; rely on `.env` and GCP Secret Manager for production values. When rotating credentials, update `config.py` defaults sparingly and document required variables in the PR. Cloud Run deployments inherit environment variables from `.env`, so double-check `ELASTICSEARCH_API_KEY` and `GCS_BUCKET` before promoting changes.
