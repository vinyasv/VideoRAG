from pydantic import BaseModel

class QueryRequest(BaseModel):
    query: str
    video_id: str | None = None
    use_video_clips: bool = False  # Default to fast text-only RAG

class VideoClip(BaseModel):
    start_time_sec: float
    end_time_sec: float
    score: float
    labels: list[str]
    ocr_text: str

class QueryResponse(BaseModel):
    answer: str
    clips: list[VideoClip]

