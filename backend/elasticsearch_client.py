import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from elasticsearch import AsyncElasticsearch
from config import settings

class ElasticsearchClient:
    def __init__(self):
        self.client = AsyncElasticsearch(
            settings.ELASTICSEARCH_ENDPOINT,
            api_key=settings.ELASTICSEARCH_API_KEY,
            request_timeout=30,
            max_retries=3
        )
    
    async def hybrid_search(self, query_text: str, query_embedding: list[float], video_id: str | None = None, top_k: int = 5):
        base_query = {
            "bool": {
                "should": [
                    {
                        "multi_match": {
                            "query": query_text,
                            "fields": ["labels^2", "ocr_text"],
                            "type": "best_fields"
                        }
                    },
                    {
                        "nested": {
                            "path": "objects",
                            "query": {
                                "match": {
                                    "objects.description": query_text
                                }
                            }
                        }
                    }
                ]
            }
        }

        if video_id:
            query = {
                "bool": {
                    "must": [base_query],
                    "filter": [{"term": {"video_id": video_id}}]
                }
            }
        else:
            query = base_query

        knn_config = {
            "field": "video_embedding",
            "query_vector": query_embedding,
            "k": top_k,
            "num_candidates": 100
        }

        if video_id:
            knn_config["filter"] = [{"term": {"video_id": video_id}}]

        try:
            response = await self.client.search(
                index=settings.VIDEO_INDEX_NAME,
                knn=knn_config,
                query=query,
                size=top_k,
                _source=["video_id", "start_time_sec", "end_time_sec", "labels", "ocr_text", "objects"]
            )
            hits = response['hits']['hits']
        except Exception:
            hits = []

        # Fallback to text-only search when vector results are empty or error
        if not hits:
            response = await self.client.search(
                index=settings.VIDEO_INDEX_NAME,
                query=query,
                size=top_k,
                _source=["video_id", "start_time_sec", "end_time_sec", "labels", "ocr_text", "objects"]
            )
            hits = response['hits']['hits']

        return hits
    
    async def close(self):
        await self.client.close()

