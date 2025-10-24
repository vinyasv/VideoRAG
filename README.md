# Sentinel

AI-powered physical security analyst that transforms CCTV footage into a fully searchable, conversational database.

## What This Does

Converts hours of CCTV footage into a searchable system where you can ask:
- **"Show me suspicious activity near the loading bay"** (semantic search)
- **"Find all clips with a person in a red shirt"** (keyword search)  
- **"When is the EXIT sign visible?"** (OCR search)

Get natural language answers with exact video timestamps in seconds, not hours.

## Architecture

```
Video → Vertex AI Analysis → Chunking → Embeddings → Elasticsearch
                                                            ↓
                                                    FastAPI Backend
                                                            ↓
                                                    HTML/JS Frontend
```

## Tech Stack

- **Google Vertex AI**: Video Intelligence + Multimodal Embeddings (1408D) + Gemini 2.0 Flash
- **Elasticsearch**: Hybrid search (vector + keyword)
- **FastAPI**: Python async API
- **Vanilla HTML/JS**: Simple, fast frontend

## Quick Start

```bash
pip install -r requirements.txt
cp env.example .env

python scripts/create_index.py
python -m ingestion.ingest --video-path data/demo.mp4
uvicorn backend.main:app --reload
```

Then open `frontend/index.html` in browser.

## Documentation

- **[CLAUDE.md](CLAUDE.md)** - Project instructions and guidance for Claude Code
- **[DEPLOYMENT.md](DEPLOYMENT.md)** - Complete deployment guide for Google Cloud Run
- **[tests/README.md](tests/README.md)** - Test suite documentation and usage

## Key Features

- **Semantic Video Search**: Find concepts, not just keywords
- **Hybrid Search**: Combines vector similarity + keyword matching
- **OCR Search**: Search visible text in footage
- **Natural Language Answers**: Gemini synthesizes findings with temporal awareness
- **Precise Timestamps**: Jump to exact moments, with automatic timestamp extraction from security footage
- **Score Normalization**: Consistent 0-1 scoring across all queries for fair comparison
- **Simple UI**: Chat interface + video player

## Project Structure

```
videorag/
├── config.py                 # Configuration management
├── requirements.txt          # Python dependencies
├── ingestion/               # Video processing pipeline
│   ├── ingest.py            # Main ingestion script
│   └── video_processor.py   # Video Intelligence + Embeddings
├── backend/                 # FastAPI server
│   ├── main.py             # API endpoints
│   ├── models.py           # Pydantic schemas
│   ├── elasticsearch_client.py  # Hybrid search with score normalization
│   ├── vertex_ai_client.py      # Gemini API with temporal query detection
│   └── gcs_client.py            # Google Cloud Storage client
├── frontend/               # User interface
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── scripts/               # Utility scripts
│   └── create_index.py   # Elasticsearch setup
├── tests/                # Test scripts and results
│   ├── test_improvements.py      # Tests for temporal accuracy and score normalization
│   ├── test_complex_queries.py   # End-to-end query testing
│   └── analyze_test_results.py  # Test result analysis
└── data/                 # Video files
```

## How It Works

### 1. Ingestion Pipeline
- Analyze video with **Video Intelligence API** (labels, OCR, object tracking)
- Split into 8-second chunks with 4-second overlap
- Generate **1408-dimension embeddings** per chunk
- Index to Elasticsearch with metadata

### 2. Query Processing
- User asks question in natural language
- Generate query embedding
- **Hybrid search**: vector similarity + keyword filters
- Return top 5 matching segments

### 3. Answer Generation
- Pass query + search results to **Gemini 2.0 Flash**
- Gemini synthesizes natural language answer
- Return answer + timestamped clips

### 4. Frontend Display
- Show Gemini's answer
- Display clickable clip buttons
- Click → video seeks to exact timestamp

## Recent Improvements

### Temporal Query Accuracy
The system now automatically detects temporal queries (questions about "when" something happened) and enhances the LLM prompt to:
- Extract precise timestamps from security camera overlays (e.g., "12:14:27 PM on 09/14/2016")
- Provide relative times when no camera timestamp is visible (e.g., "approximately 0:06 into the clip")
- Improvement: 50% to 100% temporal accuracy on test queries

### Score Normalization
Hybrid search combines bounded KNN vector scores (0-1) with unbounded BM25 text scores, which previously caused score variance of 0.5 to 18+. The system now applies min-max normalization to ensure:
- All scores consistently fall between 0-1
- Fair comparison across different queries and videos
- Improvement: Score variance reduced by 93% (range from 13.3 to 1.0)

## Example Workflow

```
User Query: "person in red near door"
           ↓
Query Embedding Generated
           ↓
Hybrid Search:
  - Vector: semantic similarity to "person in red near door"
  - Keyword: labels contain "person", "door", "red"
           ↓
Top 3 Clips Found:
  - Clip 1: 04:15 - 04:23 (score: 0.89)
  - Clip 2: 18:32 - 18:40 (score: 0.82)
  - Clip 3: 22:10 - 22:18 (score: 0.78)
           ↓
Gemini Synthesizes:
"I found 3 instances of a person in red clothing near the door.
 The first occurrence at 04:15 shows someone entering through
 the main door. At 18:32..."
           ↓
Frontend Displays:
  - Answer text
  - [Clip 1 (04:15)] [Clip 2 (18:32)] [Clip 3 (22:10)]
```

## Performance

- **Ingestion**: ~1 min per video minute
- **Query Response**: <2 seconds
- **Search Accuracy**: Top-3 relevant clips for most queries
- **Embedding Quality**: 1408D multimodal (best available)

## Design Decisions

### Why 8-second chunks?
- Optimal for multimodal embeddings (5-15s range)
- Granular enough for precise results
- Not too many documents to index

### Why 4-second overlap?
- Prevents missing events at chunk boundaries
- 50% redundancy ensures robust coverage
- Minimal storage overhead

### Why 1408 dimensions?
- Highest quality from Vertex AI
- Video embeddings only support 1408
- Better semantic understanding
- Worth the storage cost for accuracy

### Why Elasticsearch?
- Built-in hybrid search (vector + keyword)
- Production-ready, scalable
- No separate vector DB needed
- Excellent query performance

### Why Gemini 2.0 Flash?
- Fast (<2s response)
- Good reasoning quality
- Cost-effective
- Handles context well

## Environment Variables

```env
PROJECT_ID=your-gcp-project
LOCATION=us-central1

ELASTICSEARCH_ENDPOINT=https://your-project.es.region.gcp.elastic-cloud.com
ELASTICSEARCH_API_KEY=your-api-key

VIDEO_INDEX_NAME=sentinel-video-segments
EMBEDDING_MODEL=multimodalembedding@001
EMBEDDING_DIMENSION=1408
CHUNK_DURATION_SEC=8
CHUNK_OVERLAP_SEC=4
GEMINI_MODEL=gemini-2.0-flash
```

## Development Status

This is a **hackathon MVP**. Completed features:
- End-to-end demo with pre-processed video
- Working hybrid search with score normalization
- Natural language answers with temporal awareness
- Precise video timestamps with automatic extraction
- Clean, simple UI
- Comprehensive test suite
- **Cloud Run deployment** - Ready for production deployment

Not included in MVP:
- Real-time ingestion
- Multi-camera support
- Authentication
- Scale testing

## Deployment

Deploy to Google Cloud Run in minutes:

```bash
./deploy.sh
```

See **[DEPLOYMENT.md](DEPLOYMENT.md)** for complete deployment instructions, security configurations, and troubleshooting.

## Testing

The project includes a comprehensive test suite in the `tests/` directory:

### Test Scripts

**test_improvements.py** - Tests temporal accuracy and score normalization
```bash
python tests/test_improvements.py
```
Tests 4 temporal queries and 2 object queries, measuring:
- Temporal accuracy (timestamp extraction)
- Score normalization effectiveness

**test_complex_queries.py** - End-to-end query testing
```bash
python tests/test_complex_queries.py
```
Tests various query types including temporal, object detection, and action queries.

**analyze_test_results.py** - Analyzes test results for patterns
```bash
python tests/analyze_test_results.py
```

Test results are saved as JSON files in the `tests/` directory for analysis.

## Next Steps

1. Set up environment variables in `.env` (copy from `env.example`)
2. Create Elasticsearch index: `python scripts/create_index.py`
3. Process a video: `python -m ingestion.ingest --video-path your-video.mp4`
4. Start the backend: `uvicorn backend.main:app --reload`
5. Open `frontend/index.html` in browser
6. Run tests: `python tests/test_improvements.py`

## Troubleshooting

Common issues:
- **Credentials errors**: Ensure `.env` has valid GCP project ID and Elasticsearch credentials
- **Elasticsearch connection**: Verify ELASTICSEARCH_ENDPOINT and ELASTICSEARCH_API_KEY in `.env`
- **Video format compatibility**: Use MP4 format, compress large files before processing
- **CORS issues**: Serve frontend via HTTP server, not file:// protocol

## License

MIT

## Contributing

This is a hackathon project. For production use:
- Add authentication (see DEPLOYMENT.md for security guidance)
- Implement rate limiting
- Add comprehensive error handling
- Set up monitoring and alerting
- Expand test coverage for edge cases

