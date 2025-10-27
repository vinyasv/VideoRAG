import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import asyncio
import subprocess
import json
from datetime import datetime
from config import settings

from backend.models import QueryRequest, QueryResponse, VideoClip
from backend.elasticsearch_client import ElasticsearchClient
from backend.vertex_ai_client import vertex_ai_client
from backend.gcs_client import gcs_client

es_client = None


def _score_for(hit: dict) -> float:
    """Return the best available score for a search hit."""
    return float(hit.get('_normalized_score') or hit.get('_score') or 0.0)


def _select_llm_hits(hits: list[dict], *, min_absolute: float = 0.45,
                     relative_ratio: float = 0.6, max_hits: int = 3) -> list[dict]:
    """
    Filter search hits to only high-quality results for LLM ingestion.

    Ensures we keep:
      - hits that meet an absolute quality floor (min_absolute)
      - hits within `relative_ratio` of the best-scoring hit
      - at least one hit (the top result), even if all fall below thresholds
    """
    if not hits:
        return []

    # Sort hits by descending score to ensure consistent ordering
    ordered_hits = sorted(hits, key=_score_for, reverse=True)

    scores = [_score_for(hit) for hit in ordered_hits]
    best_score = scores[0]

    if best_score <= 0:
        return hits[:max_hits]

    absolute_threshold = min_absolute
    relative_threshold = best_score * relative_ratio
    effective_threshold = max(absolute_threshold, relative_threshold)

    filtered = [
        hit for hit, score in zip(ordered_hits, scores)
        if score >= effective_threshold
    ]

    if not filtered:
        filtered = [ordered_hits[0]]

    return filtered[:max_hits]

@asynccontextmanager
async def lifespan(app: FastAPI):
    global es_client
    es_client = ElasticsearchClient()
    yield
    await es_client.close()

app = FastAPI(
    title="Sentinel API",
    description="AI-powered security video search",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.get("/")
async def root():
    return {"status": "operational", "service": "Sentinel API"}

@app.get("/video/{video_id}")
async def get_video_url(video_id: str):
    # First try to serve from local videos directory (for Cloud Run deployment)
    videos_dir = Path(__file__).parent.parent / "frontend" / "videos"

    # Strip .mp4 extension if present
    video_id_base = video_id.replace('.mp4', '')

    # Try exact filename first
    exact_filename = f"{video_id_base}.mp4"
    exact_path = videos_dir / exact_filename

    if exact_path.exists():
        return {"url": f"/videos/{exact_filename}"}

    # Try compressed version (for bundled videos in container)
    compressed_filename = f"{video_id_base}_compressed.mp4"
    compressed_path = videos_dir / compressed_filename

    if compressed_path.exists():
        return {"url": f"/videos/{compressed_filename}"}

    # Fallback to GCS signed URL for local development
    try:
        signed_url = gcs_client.get_signed_url(video_id)
        return {"url": signed_url}
    except Exception as e:
        raise HTTPException(status_code=404, detail=f"Video not found: {str(e)}")


@app.post("/ask", response_model=QueryResponse)
async def ask_question(request: QueryRequest):
    if not request.query or len(request.query.strip()) == 0:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    
    query_text = request.query.strip()
    
    try:
        query_embedding = vertex_ai_client.get_query_embedding(query_text)

        search_results = await es_client.hybrid_search(
            query_embedding=query_embedding,
            query_text=query_text,
            video_id=request.video_id,
            top_k=5
        )
        

        # Load video summary
        summary_file = Path(__file__).parent.parent / 'video_summaries.json'
        video_summary = "No summary available."
        if summary_file.exists() and request.video_id:
            with open(summary_file, 'r') as f:
                summaries = json.load(f)
                # Strip extension for lookup
                summary_key = request.video_id.replace('.mp4', '')
                video_summary = summaries.get(summary_key, "No summary available for this video.")

        llm_hits = _select_llm_hits(search_results)
        print(f"ℹ️ LLM clip filter kept {len(llm_hits)} of {len(search_results)} hits.")

        # Choose RAG method based on flag
        if request.use_video_clips:
            # Slower but more detailed - uses actual video clips
            answer = await vertex_ai_client.synthesize_answer(
                query_text, llm_hits, request.video_id, video_summary
            )
        else:
            # Faster - uses only text metadata
            answer = await vertex_ai_client.synthesize_answer_text_only(
                query_text, llm_hits, request.video_id, video_summary
            )
        clips = [
            VideoClip(
                start_time_sec=hit['_source']['start_time_sec'],
                end_time_sec=hit['_source']['end_time_sec'],
                score=hit.get('_normalized_score', hit['_score']),  # Use normalized score if available
                labels=hit['_source'].get('labels', []),
                ocr_text=hit['_source'].get('ocr_text', '')
            )
            for hit in llm_hits
        ]
        
        return QueryResponse(answer=answer, clips=clips)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Internal error: {str(e)}")

# Mount static files for frontend
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dir / "assets")), name="assets")

    # Mount videos directory for serving video files
    videos_dir = frontend_dir / "videos"
    if videos_dir.exists():
        app.mount("/videos", StaticFiles(directory=str(videos_dir)), name="videos")

    @app.get("/app")
    async def serve_frontend():
        return FileResponse(str(frontend_dir / "index.html"))

    @app.get("/app.js")
    async def serve_js():
        return FileResponse(str(frontend_dir / "app.js"))

    @app.get("/styles.css")
    async def serve_css():
        return FileResponse(str(frontend_dir / "styles.css"))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
