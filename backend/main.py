import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
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
                video_summary = summaries.get(request.video_id, "No summary available for this video.")

        answer = await vertex_ai_client.synthesize_answer(
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

