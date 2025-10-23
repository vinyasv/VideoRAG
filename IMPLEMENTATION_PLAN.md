# Sentinel - Implementation Plan

## Overview
AI-powered CCTV analysis system that transforms video footage into searchable, conversational database using Google Cloud AI and Elasticsearch.

## Technology Stack

### Core Technologies
- **Python**: 3.10+
- **Google Vertex AI**: Multimodal Embeddings (`multimodalembedding@001`, 1408 dimensions)
- **Google Vertex AI**: Video Intelligence API
- **Google Vertex AI**: Gemini 2.0 Flash (chat completion)
- **Elasticsearch**: 8.x with hybrid search (vector + keyword)
- **FastAPI**: Latest stable
- **Frontend**: Vanilla HTML/JS

### Python Dependencies
```
google-cloud-aiplatform
google-cloud-videointelligence
elasticsearch[async]
fastapi
uvicorn[standard]
pydantic
python-multipart
```

## System Architecture

```
┌─────────────────┐
│   Video File    │
│   (GCS/Local)   │
└────────┬────────┘
         │
         v
┌─────────────────────────────────────────┐
│     INGESTION PIPELINE (ingest.py)      │
├─────────────────────────────────────────┤
│ 1. Video Intelligence API               │
│    → labels, OCR, timestamps            │
│ 2. Video Chunking (8s, 4s overlap)      │
│ 3. Multimodal Embeddings per chunk      │
│ 4. Index to Elasticsearch               │
└────────┬────────────────────────────────┘
         │
         v
┌─────────────────────────────────────────┐
│      ELASTICSEARCH INDEX                │
├─────────────────────────────────────────┤
│ Document Schema per segment:            │
│ - video_id                              │
│ - start_time_sec, end_time_sec          │
│ - video_embedding (vector, 1408 dim)    │
│ - labels (array of strings)             │
│ - ocr_text (string)                     │
└────────┬────────────────────────────────┘
         │
         v
┌─────────────────────────────────────────┐
│      BACKEND API (main.py)              │
├─────────────────────────────────────────┤
│ FastAPI Endpoint: POST /ask             │
│ 1. Receive query                        │
│ 2. Generate query embedding             │
│ 3. Hybrid search (vector + keyword)     │
│ 4. Gemini synthesizes answer            │
│ 5. Return JSON response                 │
└────────┬────────────────────────────────┘
         │
         v
┌─────────────────────────────────────────┐
│      FRONTEND (index.html)              │
├─────────────────────────────────────────┤
│ - Chat interface                        │
│ - Video player with timestamp control   │
│ - Clip buttons for results              │
└─────────────────────────────────────────┘
```

## File Structure

```
videorag/
├── prd.md
├── IMPLEMENTATION_PLAN.md
├── requirements.txt
├── .env.example
├── config.py
│
├── ingestion/
│   ├── __init__.py
│   ├── ingest.py
│   └── video_processor.py
│
├── backend/
│   ├── __init__.py
│   ├── main.py
│   ├── models.py
│   ├── elasticsearch_client.py
│   └── vertex_ai_client.py
│
├── frontend/
│   ├── index.html
│   └── styles.css
│
└── data/
    └── demo_video.mp4
```

## Implementation Details

### 1. Configuration (config.py)

```python
import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_ID: str
    LOCATION: str = "us-central1"
    ELASTICSEARCH_ENDPOINT: str
    ELASTICSEARCH_API_KEY: str
    VIDEO_INDEX_NAME: str = "sentinel-video-segments"
    EMBEDDING_MODEL: str = "multimodalembedding@001"
    EMBEDDING_DIMENSION: int = 1408
    CHUNK_DURATION_SEC: int = 8
    CHUNK_OVERLAP_SEC: int = 4
    GEMINI_MODEL: str = "gemini-2.0-flash"
    
    class Config:
        env_file = ".env"

settings = Settings()
```

### 2. Ingestion Pipeline

#### Elasticsearch Index Setup
**Key Pattern**: Dense vector field with `cosine` similarity for semantic search

```python
index_mapping = {
    "mappings": {
        "properties": {
            "video_id": {"type": "keyword"},
            "start_time_sec": {"type": "float"},
            "end_time_sec": {"type": "float"},
            "video_embedding": {
                "type": "dense_vector",
                "dims": 1408,
                "index": True,
                "similarity": "cosine"
            },
            "labels": {"type": "keyword"},
            "ocr_text": {"type": "text"}
        }
    }
}
```

#### Video Intelligence Analysis
**Key Pattern**: Extract labels and OCR with precise timestamps

```python
from google.cloud import videointelligence_v1 as videointelligence

def analyze_video(video_uri: str):
    client = videointelligence.VideoIntelligenceServiceClient()
    
    features = [
        videointelligence.Feature.LABEL_DETECTION,
        videointelligence.Feature.TEXT_DETECTION,
        videointelligence.Feature.OBJECT_TRACKING
    ]
    
    operation = client.annotate_video(
        request={
            "features": features,
            "input_uri": video_uri
        }
    )
    
    result = operation.result(timeout=600)
    return result
```

#### Video Chunking and Embedding
**Key Pattern**: Generate embeddings with VideoSegmentConfig for precise time windows

```python
from vertexai.vision_models import MultiModalEmbeddingModel, Video, VideoSegmentConfig

def generate_chunk_embeddings(video_path: str, chunks: list):
    model = MultiModalEmbeddingModel.from_pretrained("multimodalembedding@001")
    
    embeddings = []
    for chunk in chunks:
        video = Video.load_from_file(video_path)
        
        config = VideoSegmentConfig(
            start_offset_sec=int(chunk['start']),
            end_offset_sec=int(chunk['end']),
            interval_sec=int(chunk['end'] - chunk['start'])
        )
        
        embedding_response = model.get_embeddings(
            video=video,
            video_segment_config=config,
            dimension=1408
        )
        
        embeddings.append({
            "start": chunk['start'],
            "end": chunk['end'],
            "embedding": embedding_response.video_embeddings[0].embedding
        })
    
    return embeddings
```

#### Indexing to Elasticsearch
**Key Pattern**: Bulk indexing for performance

```python
from elasticsearch import Elasticsearch
from elasticsearch.helpers import bulk

def index_segments(es_client: Elasticsearch, documents: list):
    actions = [
        {
            "_index": "sentinel-video-segments",
            "_source": doc
        }
        for doc in documents
    ]
    
    success, failed = bulk(es_client, actions)
    return success, failed
```

### 3. Backend API

#### Models (models.py)
```python
from pydantic import BaseModel

class QueryRequest(BaseModel):
    query: str

class VideoClip(BaseModel):
    start_time_sec: float
    end_time_sec: float
    score: float

class QueryResponse(BaseModel):
    answer: str
    clips: list[VideoClip]
```

#### Hybrid Search Implementation
**Key Pattern**: Combine kNN vector search with keyword filters

```python
async def hybrid_search(es_client: Elasticsearch, query_text: str, query_embedding: list[float]):
    search_query = {
        "knn": {
            "field": "video_embedding",
            "query_vector": query_embedding,
            "k": 10,
            "num_candidates": 100
        },
        "query": {
            "bool": {
                "should": [
                    {
                        "multi_match": {
                            "query": query_text,
                            "fields": ["labels", "ocr_text"],
                            "type": "best_fields"
                        }
                    }
                ]
            }
        }
    }
    
    response = await es_client.search(
        index="sentinel-video-segments",
        body=search_query,
        size=5
    )
    
    return response['hits']['hits']
```

#### Query Embedding Generation
**Key Pattern**: Use multimodal embeddings with contextual text

```python
from vertexai.vision_models import MultiModalEmbeddingModel

def get_query_embedding(query_text: str) -> list[float]:
    model = MultiModalEmbeddingModel.from_pretrained("multimodalembedding@001")
    
    embedding_response = model.get_embeddings(
        contextual_text=query_text,
        dimension=1408
    )
    
    return embedding_response.text_embedding
```

#### Gemini Chat Completion
**Key Pattern**: Pass search context to Gemini for natural language synthesis

```python
from vertexai.generative_models import GenerativeModel

def synthesize_answer(query: str, search_results: list) -> str:
    model = GenerativeModel("gemini-2.0-flash")
    
    context = "\n".join([
        f"Clip {i+1} ({r['_source']['start_time_sec']}s - {r['_source']['end_time_sec']}s): "
        f"Labels: {', '.join(r['_source']['labels'])}, OCR: {r['_source']['ocr_text']}"
        for i, r in enumerate(search_results)
    ])
    
    prompt = f"""You are a security analyst. Based on the following video segments, answer the user's query.

Query: {query}

Video Segments:
{context}

Provide a concise, natural language answer mentioning specific timestamps."""
    
    response = model.generate_content(prompt)
    return response.text
```

#### FastAPI Endpoint
**Key Pattern**: Single POST endpoint with async processing

```python
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Sentinel API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.post("/ask", response_model=QueryResponse)
async def ask_question(request: QueryRequest):
    query_embedding = get_query_embedding(request.query)
    
    search_results = await hybrid_search(
        es_client,
        request.query,
        query_embedding
    )
    
    if not search_results:
        raise HTTPException(status_code=404, detail="No relevant clips found")
    
    answer = synthesize_answer(request.query, search_results)
    
    clips = [
        VideoClip(
            start_time_sec=hit['_source']['start_time_sec'],
            end_time_sec=hit['_source']['end_time_sec'],
            score=hit['_score']
        )
        for hit in search_results
    ]
    
    return QueryResponse(answer=answer, clips=clips)
```

### 4. Frontend

#### HTML Structure
```html
<!DOCTYPE html>
<html>
<head>
    <title>Sentinel - Security Video Search</title>
    <link rel="stylesheet" href="styles.css">
</head>
<body>
    <div class="container">
        <h1>Sentinel</h1>
        
        <div class="video-container">
            <video id="mainVideo" controls>
                <source src="data/demo_video.mp4" type="video/mp4">
            </video>
        </div>
        
        <div class="chat-container">
            <div id="chatHistory"></div>
            
            <div class="input-container">
                <input 
                    type="text" 
                    id="queryInput" 
                    placeholder="Ask about the footage..."
                >
                <button id="sendBtn">Search</button>
            </div>
        </div>
        
        <div id="resultsContainer"></div>
    </div>
    
    <script src="app.js"></script>
</body>
</html>
```

#### JavaScript Logic
**Key Pattern**: Fetch API, video timestamp control

```javascript
const API_URL = 'http://localhost:8000';
const videoPlayer = document.getElementById('mainVideo');
const queryInput = document.getElementById('queryInput');
const sendBtn = document.getElementById('sendBtn');
const chatHistory = document.getElementById('chatHistory');
const resultsContainer = document.getElementById('resultsContainer');

async function askQuestion() {
    const query = queryInput.value.trim();
    if (!query) return;
    
    appendMessage('user', query);
    queryInput.value = '';
    
    try {
        const response = await fetch(`${API_URL}/ask`, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({query})
        });
        
        const data = await response.json();
        
        appendMessage('assistant', data.answer);
        displayClips(data.clips);
        
    } catch (error) {
        appendMessage('error', 'Failed to get response');
    }
}

function displayClips(clips) {
    resultsContainer.innerHTML = '<h3>Found Clips:</h3>';
    
    clips.forEach((clip, index) => {
        const btn = document.createElement('button');
        btn.className = 'clip-button';
        btn.textContent = `Clip ${index + 1} (${formatTime(clip.start_time_sec)})`;
        btn.onclick = () => playClip(clip.start_time_sec);
        resultsContainer.appendChild(btn);
    });
}

function playClip(startTime) {
    videoPlayer.currentTime = startTime;
    videoPlayer.play();
}

function formatTime(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    return `${mins}:${secs.toString().padStart(2, '0')}`;
}

function appendMessage(role, text) {
    const msg = document.createElement('div');
    msg.className = `message ${role}`;
    msg.textContent = text;
    chatHistory.appendChild(msg);
    chatHistory.scrollTop = chatHistory.scrollHeight;
}

sendBtn.addEventListener('click', askQuestion);
queryInput.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') askQuestion();
});
```

## Implementation Steps

### Phase 1: Environment Setup (30 mins)

1. **Google Cloud Setup**
   - Enable Vertex AI API
   - Enable Video Intelligence API
   - Create service account with required permissions
   - Download credentials JSON

2. **Elasticsearch Setup**
   - Create Elasticsearch Cloud deployment (free trial)
   - Get Cloud ID and API key
   - Note endpoint URL

3. **Local Environment**
   ```bash
   python -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

4. **Environment Variables**
   Create `.env`:
   ```
   PROJECT_ID=your-gcp-project
   LOCATION=us-central1
   GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
   ELASTICSEARCH_CLOUD_ID=your-cloud-id
   ELASTICSEARCH_API_KEY=your-api-key
   ```

### Phase 2: Ingestion Pipeline (2-3 hours)

1. **Create Elasticsearch Index**
   - Run script to create index with proper mappings
   - Verify index creation

2. **Implement Video Processor**
   - Video Intelligence API integration
   - Chunk generation logic
   - Embedding generation

3. **Test Ingestion**
   - Process demo video (10-15 min)
   - Verify documents in Elasticsearch
   - Check embedding dimensions

### Phase 3: Backend API (1-2 hours)

1. **Implement Core Services**
   - Elasticsearch client wrapper
   - Vertex AI client wrapper
   - Hybrid search logic

2. **Build FastAPI Endpoint**
   - `/ask` endpoint
   - Request/response models
   - Error handling

3. **Test API**
   - Test with sample queries
   - Verify Gemini responses
   - Check clip results

### Phase 4: Frontend (1 hour)

1. **Build HTML Interface**
   - Video player
   - Chat interface
   - Results display

2. **Implement JavaScript**
   - API integration
   - Video control
   - UI updates

3. **Styling**
   - Clean, minimal design
   - Responsive layout

### Phase 5: Integration Testing (30 mins)

1. **End-to-End Tests**
   - Conceptual query: "suspicious activity"
   - Keyword query: "person in red shirt"
   - OCR query: "EXIT sign"

2. **Performance Check**
   - Query response time (<2s)
   - Video playback smooth
   - UI responsive

## Key Implementation Patterns

### 1. Parallel Embedding Generation
Use semaphores to control API rate limits:
```python
import threading
from concurrent.futures import ThreadPoolExecutor

def get_embeddings_parallel(chunks, max_workers=5):
    semaphore = threading.Semaphore(max_workers)
    
    def rate_limited_task(chunk):
        with semaphore:
            return get_chunk_embedding(chunk)
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(rate_limited_task, chunks))
    
    return results
```

### 2. Efficient Video Chunking
Overlapping windows for context:
```python
def create_chunks(video_duration_sec, chunk_size=8, overlap=4):
    chunks = []
    step = chunk_size - overlap
    
    for start in range(0, int(video_duration_sec), step):
        end = min(start + chunk_size, video_duration_sec)
        chunks.append({"start": start, "end": end})
    
    return chunks
```

### 3. Elasticsearch Connection Pooling
```python
from elasticsearch import AsyncElasticsearch

async def get_es_client():
    return AsyncElasticsearch(
        cloud_id=settings.ELASTICSEARCH_CLOUD_ID,
        api_key=settings.ELASTICSEARCH_API_KEY,
        request_timeout=30,
        max_retries=3
    )
```

## Expected Behavior

### Demo Scenario 1: Conceptual Query
**Query**: "Show me suspicious activity near the loading bay"
**Expected**:
- Gemini identifies behavioral patterns
- Returns 2-3 clips with unusual movement
- Natural language summary: "I found 2 instances of suspicious activity..."

### Demo Scenario 2: Keyword Query
**Query**: "Find all clips with a person in a red shirt"
**Expected**:
- Keyword filter on `labels: ["person", "red", "clothing"]`
- Vector search for semantic similarity
- Returns timestamped clips

### Demo Scenario 3: OCR Query
**Query**: "When is the EXIT sign visible?"
**Expected**:
- Text search on `ocr_text` field
- Returns specific timestamps
- Clips show EXIT sign

## Performance Targets

- **Ingestion**: 10-15 min video → ~30-60 segments → 5-10 minutes processing
- **Query Response**: <2 seconds end-to-end
- **Search Accuracy**: Top 3 results relevant for both semantic and keyword queries
- **Frontend**: Instant video seek to timestamp

## Gotchas & Solutions

1. **Video Intelligence API Timeout**
   - Solution: Use async operation.result(timeout=900)
   - Split very long videos

2. **Embedding Dimension Mismatch**
   - Video embeddings: Always 1408
   - Text embeddings: Can vary (128, 256, 512, 1408)
   - Solution: Always specify dimension=1408

3. **Elasticsearch Vector Search Performance**
   - Solution: Use `index: true` in mapping
   - Tune `num_candidates` parameter (100-500)

4. **CORS Issues**
   - Solution: Add CORS middleware to FastAPI
   - Or serve frontend from same origin

5. **Video Format Compatibility**
   - Solution: Use MP4 with H.264 codec
   - Test with sample before production

## Next Steps After MVP

1. **Scalability**
   - Batch ingestion for multiple cameras
   - Distributed processing with Celery
   - Elasticsearch cluster scaling

2. **Features**
   - Real-time ingestion pipeline
   - Multi-camera correlation
   - Alert triggers

3. **Production Hardening**
   - Authentication/authorization
   - Rate limiting
   - Monitoring and logging
   - Error recovery

## Success Criteria

✅ Process 10-15 min demo video
✅ Answer 2+ distinct query types (conceptual + keyword)
✅ Return accurate, timestamped clips
✅ Sub-2s query response time
✅ Clean, functional UI
✅ Gemini provides natural language answers
✅ Video player cues to exact timestamp

