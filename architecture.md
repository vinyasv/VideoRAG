# Architecture Guide

Sentinel converts raw security footage into a conversational, searchable experience. This document breaks down the architecture that powers ingestion, search, and answering.

## High-Level View

```
┌────────────┐     ┌──────────────┐     ┌──────────────────┐
│  Frontend  │────▶│   FastAPI    │────▶│ Elasticsearch     │
└────────────┘     │    Backend   │     │  (Hybrid Search)  │
        ▲          │              │     └──────────────────┘
        │          │              │              ▲
        │          ▼              ▼              │
        │   Vertex AI Clients  GCS Signed URLs   │
        │          ▲              ▲              │
        └──────────┴──────▶ Ingestion Pipeline ──┘
```

- **Frontend (`frontend/`)**: Chat UI and video player.
- **Backend (`backend/`)**: FastAPI app orchestrating search, retrieval, and answer generation.
- **Ingestion (`ingestion/`)**: Batch process that analyzes video, builds embeddings, and writes to Elasticsearch.
- **Elasticsearch**: Stores chunked video documents for hybrid vector + keyword search.
- **Google Cloud**: Vertex AI for multimodal analysis and embeddings, GCS for video storage.

---

## Ingestion Pipeline

```
┌────────────┐   ┌─────────────┐   ┌───────────────┐   ┌────────────────┐
│ Video File │─▶│ Chunk Builder│─▶│ Feature Enrich │─▶│ Embedding Synth │
└────────────┘   └─────────────┘   └───────────────┘   └────────────────┘
                                                          │
                                                          ▼
                                               ┌────────────────────┐
                                               │ Elasticsearch Index │
                                               └────────────────────┘
```

1. **Chunking** (`ingestion/video_processor.py`)
   - Splits videos into ~8-second windows with 4-second overlap.
   - Captures start/end timestamps and temporal metadata.

2. **Feature Enrichment**
   - Invokes Vertex AI Video Intelligence for labels, objects, and OCR text.
   - Normalizes timestamps and aggregates structured metadata per chunk.

3. **Embedding Generation**
   - Calls Vertex AI `multimodalembedding@001` to produce 1408-dimension vectors.
   - Embedding represents audio + visual context within each chunk.

4. **Indexing** (`scripts/create_index.py`, ingestion writers)
   - Upserts documents into Elasticsearch with:
     - Dense vector field (`embedding`)
     - Keyword fields (labels, objects)
     - Text fields (transcript, OCR)
     - Temporal metadata (start/end seconds, camera timestamp)

Document schema balance vector similarity with filterable metadata for hybrid search.

---

## Backend (FastAPI)

```
┌────────────────────┐
│ backend/main.py    │
│ ─ FastAPI routes   │
│ ─ Request schemas  │
└─────────┬──────────┘
          │
┌─────────▼──────────┐
│ Service Layer      │
│ ├ elasticsearch_client.py│
│ ├ vertex_ai_client.py    │
│ └ gcs_client.py          │
└─────────┬──────────┘
          │
┌─────────▼──────────┐
│ Shared config.py    │
│ Credential loading  │
│ Environment parsing │
└─────────────────────┘
```

### Request Flow (`/ask`)

```
Chat Query ──▶ FastAPI route
                     │
                     ▼
           ┌──────────────────┐
           │ Search Orchestrator│
           └──────────────────┘
                     │
   ┌─────────────────┴──────────────────┐
   ▼                                    ▼
Elasticsearch                Vertex AI (Gemini)
   │                                    │
   └───────────────▶ Answer Synthesis ◀─┘
                     │
                     ▼
                 Response JSON
```

1. Parse incoming query, detect current video ID, and check whether detailed (LLM) mode is enabled.
2. Call Elasticsearch hybrid search:
   - Vector cosine similarity on embeddings.
   - BM25 keyword scoring on OCR/labels.
   - Optional filters (video ID, timestamp ranges).
3. Format top hits with chunk metadata and pre-signed GCS URLs (via `gcs_client.py`).
4. If detailed analysis is on, craft a prompt combining user query and chunk summaries, then ask Gemini to produce a natural language answer referencing precise timestamps.
5. Return answer, clip list, and metadata to the frontend.

### Other Endpoints

- `/video/{video_id}`: Returns signed URLs to stream the selected video from GCS.
- `/healthz` (if present): Health check for deployment targets.

---

## Search Stack (Elasticsearch)

```
┌─────────────────────────────┐
│ Index: VIDEO_INDEX_NAME      │
│ ├ id                         │
│ ├ video_id                   │
│ ├ start_time_sec / end_time_sec│
│ ├ camera_timestamp           │
│ ├ labels[], ocr_text         │
│ ├ transcript / description   │
│ └ embedding (dense_vector)   │
└─────────────────────────────┘
```

### Query Strategy

1. Generate query embedding from user text (Vertex AI).
2. Run `knn` search on `embedding` field for semantic similarity.
3. Run BM25 queries on text fields (OCR, labels) for literal matches.
4. Combine results with score normalization to produce a unified ranking.

### Score Normalization

Because Elasticsearch produces bounded vector scores (0…1) and unbounded BM25 scores, a min–max normalization is applied in the backend client so that top results are comparable and stable across queries.

### Temporal Awareness

- Each document stores: `start_time_sec`, `end_time_sec`, `camera_timestamp`.
- Backend uses these fields to surface precise clip ranges and feed timestamps into Gemini prompts.

---

## Answer Generation (Vertex AI Gemini)

```
┌────────────────────────────────────┐
│ Prompt Template                    │
│ ├ User query                       │
│ ├ Top N chunk summaries            │
│ ├ Timestamp metadata               │
│ └ Any OCR/label highlights         │
└────────────────┬───────────────────┘
                 │
                 ▼
        Vertex AI Gemini Flash
                 │
                 ▼
        Structured Answer JSON
```

The backend composes a structured prompt instructing Gemini to:
1. Address the user query directly.
2. Cite specific timestamps when referencing events.
3. Include relevant labels or OCR strings when useful.

Gemini responds with natural language text, which the backend returns alongside raw clip data for the frontend to display.

---

## Frontend Application

```
┌──────────────────────┐
│ index.html           │
│ ├ Video gallery      │
│ ├ Chat panel         │
│ └ Example query UX   │
└──────────┬───────────┘
           │
┌──────────▼───────────┐
│ app.js               │
│ ├ State management   │
│ ├ Fetch helpers      │
│ ├ Clip citation logic│
│ └ Example query preload │
└──────────┬───────────┘
           │
┌──────────▼───────────┐
│ styles.css           │
│ ├ Layout             │
│ ├ Tooltip styling    │
│ └ Chat theming       │
└──────────────────────┘
```

### Chat Flow

1. User selects a video card; `app.js` fetches the signed URL from the backend.
2. Empty-state chat shows example query button; once a question is asked, the button hides.
3. On submit, the UI:
   - Calls `POST /ask`
   - Activates loading indicator
   - Renders user message immediately
4. On response:
   - Displays assistant message with formatted text.
   - Renders citation badges; clicking them seeks the video to the associated chunk start time.
   - Maintains scroll position and focuses the input.

### Accessibility & UX Considerations

- Tooltip content is accessible via focus state and placed above chat messages (CSS `overflow: visible`).
- Buttons use semantic HTML, and icons include `aria-label`.
- Inputs are mirrored in empty state vs active state to keep the layout balanced.

---

## Configuration & Secrets

- `.env` mirrors `env.example`; `config.py` loads and validates values for ingestion and backend usage.
- Sensitive values (API keys, service accounts) should live in Secret Manager for deployment; `.env` is meant for local dev only.
- `sentinel-key.json` is present locally but should not be committed in production setups.

---

## Deployment Snapshot

```
┌──────────────────┐      ┌────────────────────┐
│ Cloud Run (API)  │─────▶│ Elasticsearch (GCP │
│ dockerized FastAPI│     │ or Elastic Cloud)  │
└──────────────────┘      └────────┬───────────┘
                                    │
                       ┌────────────▼────────────┐
                       │ Google Cloud Storage    │
                       │ (video assets)          │
                       └────────────┬────────────┘
                                    │
                       ┌────────────▼────────────┐
                       │ Vertex AI Services      │
                       │ (Video + Embeddings +   │
                       │  Gemini)                │
                       └─────────────────────────┘
```

Key steps (documented in `DEPLOYMENT.md`):
1. Build container with `deploy.sh`.
2. Ensure `.env` values are injected as Cloud Run secrets/config vars.
3. Grant service account permissions for Vertex AI and GCS.
4. Configure outbound networking to reach Elasticsearch endpoint.

---

## Future Extensions

- **Realtime ingestion** via event-driven pipelines (Pub/Sub triggers on new uploads).
- **Additional retrieval modes** (e.g., geospatial filters, advanced OCR queries).
- **User management** in the frontend with authentication layers.
- **Analytics dashboards** using search logs to improve ingestion heuristics.

This architecture is modular: each component (ingestion, search, answer generation, UI) can evolve independently while maintaining clearly defined interfaces. Continuous testing (`pytest`) and configuration (`config.py`) keep the system consistent across environments.
