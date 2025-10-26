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

    def _build_text_query(self, query_text: str):
        """Builds the text-based search part of the query."""
        return {
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

    async def hybrid_search(self, query_embedding: list[float] | None, query_text: str, video_id: str | None = None, top_k: int = 5):
        """
        Hybrid search with 80% semantic / 20% text weighting.
        Combines KNN vector search with BM25 text search using weighted score fusion.
        """
        if query_embedding is None:
            # Fallback to text-only if no embedding
            print(f"📝 Using TEXT-ONLY search for query: '{query_text}'")
            text_query = self._build_text_query(query_text)
            query = {
                "bool": {
                    "must": [text_query]
                }
            }
            if video_id:
                query["bool"]["filter"] = [{"term": {"video_id": video_id}}]

            response = await self.client.search(
                index=settings.VIDEO_INDEX_NAME,
                query=query,
                size=top_k,
                _source=["video_id", "start_time_sec", "end_time_sec", "labels", "ocr_text", "objects", "clip_uri", "shot_labels", "ocr_items"]
            )
            print(f"   ✅ Text search successful, found {len(response['hits']['hits'])} results")
            return self._normalize_scores(response['hits']['hits'])

        print(f"🔍 Using WEIGHTED HYBRID search (80% semantic, 20% text) for query: '{query_text}'")

        try:
            # Fetch more candidates for better fusion
            fetch_size = top_k * 4

            # 1. Get semantic (KNN) results
            knn_config = {
                "field": "video_embedding",
                "query_vector": query_embedding,
                "k": fetch_size,
                "num_candidates": 200
            }
            if video_id:
                knn_config["filter"] = {"term": {"video_id": video_id}}

            semantic_response = await self.client.search(
                index=settings.VIDEO_INDEX_NAME,
                knn=knn_config,
                size=fetch_size,
                _source=["video_id", "start_time_sec", "end_time_sec", "labels", "ocr_text", "objects", "clip_uri", "shot_labels", "ocr_items"]
            )

            # 2. Get text (BM25) results
            text_query = self._build_text_query(query_text)
            query = {
                "bool": {
                    "must": [text_query]
                }
            }
            if video_id:
                query["bool"]["filter"] = [{"term": {"video_id": video_id}}]

            text_response = await self.client.search(
                index=settings.VIDEO_INDEX_NAME,
                query=query,
                size=fetch_size,
                _source=["video_id", "start_time_sec", "end_time_sec", "labels", "ocr_text", "objects", "clip_uri", "shot_labels", "ocr_items"]
            )

            # 3. Combine results with 80/20 weighting
            combined_results = self._weighted_fusion(
                semantic_results=semantic_response['hits']['hits'],
                text_results=text_response['hits']['hits'],
                semantic_weight=0.8,
                text_weight=0.2,
                top_k=top_k
            )

            print(f"   ✅ Weighted hybrid search successful, found {len(combined_results)} results")
            return combined_results

        except Exception as e:
            print(f"⚠️ Warning: Weighted hybrid search failed: {e}")
            print("   Falling back to text-only search")

            text_query = self._build_text_query(query_text)
            query = {
                "bool": {
                    "must": [text_query]
                }
            }
            if video_id:
                query["bool"]["filter"] = [{"term": {"video_id": video_id}}]

            response = await self.client.search(
                index=settings.VIDEO_INDEX_NAME,
                query=query,
                size=top_k,
                _source=["video_id", "start_time_sec", "end_time_sec", "labels", "ocr_text", "objects", "clip_uri", "shot_labels", "ocr_items"]
            )
            return self._normalize_scores(response['hits']['hits'])

    def _weighted_fusion(self, semantic_results: list, text_results: list,
                        semantic_weight: float, text_weight: float, top_k: int) -> list:
        """
        Combine semantic and text search results with weighted score fusion.

        Args:
            semantic_results: List of hits from KNN search
            text_results: List of hits from text search
            semantic_weight: Weight for semantic scores (e.g., 0.8)
            text_weight: Weight for text scores (e.g., 0.2)
            top_k: Number of results to return

        Returns:
            Combined and re-ranked results
        """
        # Normalize scores from both result sets
        semantic_normalized = self._normalize_to_unit_range(semantic_results)
        text_normalized = self._normalize_to_unit_range(text_results)

        # Create a map of document ID -> combined document
        doc_map = {}

        # Add semantic results
        for hit in semantic_normalized:
            doc_id = hit['_id']
            doc_map[doc_id] = {
                '_id': doc_id,
                '_source': hit['_source'],
                'semantic_score': hit['_normalized_score'],
                'text_score': 0.0,
                'original_semantic_score': hit['_score']
            }

        # Add/update with text results
        for hit in text_normalized:
            doc_id = hit['_id']
            if doc_id in doc_map:
                doc_map[doc_id]['text_score'] = hit['_normalized_score']
                doc_map[doc_id]['original_text_score'] = hit['_score']
            else:
                doc_map[doc_id] = {
                    '_id': doc_id,
                    '_source': hit['_source'],
                    'semantic_score': 0.0,
                    'text_score': hit['_normalized_score'],
                    'original_text_score': hit['_score']
                }

        # Calculate combined weighted scores
        for doc_id, doc in doc_map.items():
            combined_score = (
                semantic_weight * doc['semantic_score'] +
                text_weight * doc['text_score']
            )
            doc['_score'] = combined_score
            doc['_normalized_score'] = combined_score

        # Sort by combined score (descending) and take top_k
        sorted_docs = sorted(doc_map.values(), key=lambda x: x['_score'], reverse=True)[:top_k]

        # Format results to match expected structure
        formatted_results = []
        for doc in sorted_docs:
            formatted_results.append({
                '_id': doc['_id'],
                '_source': doc['_source'],
                '_score': doc['_score'],
                '_normalized_score': doc['_normalized_score']
            })

        return formatted_results

    def _normalize_to_unit_range(self, search_results: list) -> list:
        """
        Normalize scores to 0-1 range for a single result set.
        Returns a copy with normalized scores added.
        """
        if not search_results:
            return search_results

        # Extract scores
        scores = [hit['_score'] for hit in search_results]
        min_score = min(scores)
        max_score = max(scores)

        score_range = max_score - min_score

        # Create normalized copies
        normalized = []
        for hit in search_results:
            normalized_hit = hit.copy()
            if score_range == 0:
                normalized_hit['_normalized_score'] = 1.0
            else:
                normalized_hit['_normalized_score'] = (hit['_score'] - min_score) / score_range
            normalized.append(normalized_hit)

        return normalized

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

        score_range = max_score - min_score
        if score_range == 0:
            for hit in search_results:
                hit['_normalized_score'] = 1.0
                hit['_original_score'] = hit['_score']
            return search_results

        for hit in search_results:
            original = hit['_score']
            normalized = (original - min_score) / score_range
            hit['_normalized_score'] = normalized
            hit['_original_score'] = original

        return search_results

    async def close(self):
        await self.client.close()
