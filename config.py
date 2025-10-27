import os
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    PROJECT_ID: str
    LOCATION: str = "us-central1"
    GCS_BUCKET: str
    
    ELASTICSEARCH_ENDPOINT: str
    ELASTICSEARCH_API_KEY: str
    
    VIDEO_INDEX_NAME: str = "sentinel-video-segments"
    EMBEDDING_MODEL: str = "multimodalembedding@001"
    EMBEDDING_DIMENSION: int = 1408
    CHUNK_DURATION_SEC: int = 16
    CHUNK_OVERLAP_SEC: int = 4
    GEMINI_MODEL: str = "gemini-2.0-flash"
    
    class Config:
        env_file = ".env"
        case_sensitive = True

settings = Settings()

