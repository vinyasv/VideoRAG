from pydantic import BaseModel

class QueryRequest(BaseModel):
    query: str
    video_id: str | None = None

class VideoClip(BaseModel):
    start_time_sec: float
    end_time_sec: float
    score: float
    labels: list[str]
    ocr_text: str

class QueryResponse(BaseModel):
    answer: str
    clips: list[VideoClip]

