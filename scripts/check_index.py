import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from elasticsearch import Elasticsearch
from config import settings
import json

es = Elasticsearch(
    settings.ELASTICSEARCH_ENDPOINT,
    api_key=settings.ELASTICSEARCH_API_KEY
)

response = es.search(index=settings.VIDEO_INDEX_NAME, size=2)

print(f"Total documents: {response['hits']['total']['value']}\n")

for i, hit in enumerate(response['hits']['hits']):
    print(f"Document {i+1}:")
    print(f"  Time: {hit['_source']['start_time_sec']}-{hit['_source']['end_time_sec']}s")
    print(f"  Labels: {hit['_source']['labels']}")
    print(f"  OCR: {hit['_source']['ocr_text'][:100] if hit['_source']['ocr_text'] else 'none'}")
    print(f"  Video ID: {hit['_source']['video_id']}")
    print(f"  Score: {hit['_score']}")
    print()

