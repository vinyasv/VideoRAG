import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import subprocess
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

@app.post("/upload")
async def upload_video(
    video: UploadFile = File(...),
    video_id: str = Form(...)
):
    try:
        video_data = await video.read()
        
        gcs_uri = gcs_client.upload_video(video_data, video_id, video.filename)
        
        asyncio.create_task(process_video_async(gcs_uri, video_id))
        
        return {"status": "success", "video_id": video_id, "gcs_uri": gcs_uri}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

async def process_video_async(gcs_uri: str, video_id: str):
    try:
        await asyncio.sleep(1)
        
        log_file = Path(__file__).parent.parent / 'ingestion_log.txt'
        start_msg = f"[{datetime.now().isoformat()}] START ingestion for {video_id} ({gcs_uri})\n"
        with log_file.open('a') as lf:
            lf.write(start_msg)
        
        process = await asyncio.create_subprocess_exec(
            'python', 'ingestion/ingest.py',
            '--video-path', gcs_uri,
            '--video-id', video_id,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        
        stdout, stderr = await process.communicate()
        
        log_lines = []
        if stdout:
            log_lines.append(stdout.decode())
        if stderr:
            log_lines.append(stderr.decode())
        status = 'SUCCEEDED' if process.returncode == 0 else 'FAILED'
        end_msg = f"[{datetime.now().isoformat()}] END ingestion for {video_id} - {status} (rc={process.returncode})\n\n"
        
        with log_file.open('a') as lf:
            for line in log_lines:
                lf.write(line)
            lf.write(end_msg)
        
        if process.returncode != 0:
            print(f"Ingestion failed for {video_id}: {stderr.decode()}")
        else:
            print(f"Successfully ingested {video_id}")
            
    except Exception as e:
        print(f"Error processing video {video_id}: {str(e)}")
        try:
            log_file = Path(__file__).parent.parent / 'ingestion_log.txt'
            with log_file.open('a') as lf:
                lf.write(f"[{datetime.now().isoformat()}] ERROR ingestion for {video_id}: {str(e)}\n\n")
        except Exception:
            pass

@app.post("/ask", response_model=QueryResponse)
async def ask_question(request: QueryRequest):
    if not request.query or len(request.query.strip()) == 0:
        raise HTTPException(status_code=400, detail="Query cannot be empty")
    
    query_text = request.query.strip()
    
    try:
        query_embedding = vertex_ai_client.get_query_embedding(query_text)
        
        search_results = await es_client.hybrid_search(
            query_text=query_text,
            query_embedding=query_embedding,
            video_id=request.video_id,
            top_k=5
        )
        
        if not search_results:
            raise HTTPException(
                status_code=404,
                detail="No relevant video clips found for your query"
            )
        
        answer = vertex_ai_client.synthesize_answer(query_text, search_results)
        
        clips = [
            VideoClip(
                start_time_sec=hit['_source']['start_time_sec'],
                end_time_sec=hit['_source']['end_time_sec'],
                score=hit['_score'],
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

