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
    
    async def hybrid_search(self, query_embedding: list[float] | None, query_text: str, video_id: str | None = None, top_k: int = 5):
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

        # Only use vector search if embedding is available
        if query_embedding is not None:
            print(f"🔍 Using HYBRID search (vector + text) for query: '{query_text}'")
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
                print(f"   ✅ Hybrid search successful, found {len(response['hits']['hits'])} results")
                normalized_results = self._normalize_scores(response['hits']['hits'])
                return normalized_results
            except Exception as e:
                print(f"⚠️ Warning: Vector search failed: {e}")
                print("   Falling back to text-only search")

        # Text-only search (used when no embedding or vector search fails)
        print(f"📝 Using TEXT-ONLY search for query: '{query_text}'")
        response = await self.client.search(
            index=settings.VIDEO_INDEX_NAME,
            query=query,
            size=top_k,
            _source=["video_id", "start_time_sec", "end_time_sec", "labels", "ocr_text", "objects"]
        )
        print(f"   ✅ Text search successful, found {len(response['hits']['hits'])} results")
        normalized_results = self._normalize_scores(response['hits']['hits'])
        return normalized_results
    
    def _normalize_scores(self, search_results: list) -> list:
        """
        Normalize scores to 0-1 range for consistent comparison across queries.

        This addresses the issue where hybrid search combines bounded KNN scores (0-1)
        with unbounded BM25 text scores, leading to high variance (0.5 to 18+).
        """
        if not search_results:
            return search_results

        scores = [hit['_score'] for hit in search_results]
        min_score = min(scores)
        max_score = max(scores)

        # Avoid division by zero
        score_range = max_score - min_score
        if score_range == 0:
            for hit in search_results:
                hit['_normalized_score'] = 1.0
                hit['_original_score'] = hit['_score']
            return search_results

        # Min-max normalization to 0-1
        for hit in search_results:
            original = hit['_score']
            normalized = (original - min_score) / score_range
            hit['_normalized_score'] = normalized
            hit['_original_score'] = original  # Keep for debugging

        return search_results

    async def close(self):
        await self.client.close()

