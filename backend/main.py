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

from backend.models import QueryRequest, QueryResponse, VideoClip
from backend.elasticsearch_client import ElasticsearchClient
from backend.vertex_ai_client import vertex_ai_client
from backend.gcs_client import gcs_client

es_client = None

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
        if summary_file.exists():
            with open(summary_file, 'r') as f:
                summaries = json.load(f)
                # Strip extension for lookup
                summary_key = request.video_id.replace('.mp4', '')
                video_summary = summaries.get(summary_key, "No summary available for this video.")

        # Choose RAG method based on flag
        if request.use_video_clips:
            # Slower but more detailed - uses actual video clips
            answer = await vertex_ai_client.synthesize_answer(
                query_text, search_results, request.video_id, video_summary
            )
        else:
            # Faster - uses only text metadata
            answer = await vertex_ai_client.synthesize_answer_text_only(
                query_text, search_results, request.video_id, video_summary
            )
        
        clips = [
            VideoClip(
                start_time_sec=hit['_source']['start_time_sec'],
                end_time_sec=hit['_source']['end_time_sec'],
                score=hit.get('_normalized_score', hit['_score']),  # Use normalized score if available
                labels=hit['_source'].get('labels', []),
                ocr_text=hit['_source'].get('ocr_text', '')
            )
            for hit in search_results
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


@app.get("/test-prompt")
async def test_prompt():
    """Temporary endpoint to test the new prompt."""
    query_text = "Describe the two suspects at the door."
    video_id = "burglary_video_compressed.mp4"

    query_embedding = vertex_ai_client.get_query_embedding(query_text)

    search_results = await es_client.hybrid_search(
        query_embedding=query_embedding,
        query_text=query_text,
        video_id=video_id,
        top_k=5
    )

    summary_file = Path(__file__).parent.parent / 'video_summaries.json'
    video_summary = "No summary available."
    if summary_file.exists():
        with open(summary_file, 'r') as f:
            summaries = json.load(f)
            summary_key = video_id.replace('.mp4', '')
            video_summary = summaries.get(summary_key, "No summary available for this video.")

    answer = await vertex_ai_client.synthesize_answer(
        query_text, search_results, video_id, video_summary
    )

    return {"question": query_text, "answer": answer}

