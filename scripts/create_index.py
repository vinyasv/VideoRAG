import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import argparse
from elasticsearch import Elasticsearch
from config import settings

def create_video_index(force=False):
    es = Elasticsearch(
        settings.ELASTICSEARCH_ENDPOINT,
        api_key=settings.ELASTICSEARCH_API_KEY,
        request_timeout=30
    )

    if not es.ping():
        raise Exception("Cannot connect to Elasticsearch")

    index_name = settings.VIDEO_INDEX_NAME

    if es.indices.exists(index=index_name):
        print(f"Index '{index_name}' already exists.")

        should_delete = False
        if force:
            should_delete = True
        else:
            response = input("Delete and recreate? (y/N): ")
            if response.lower() == 'y':
                should_delete = True

        if should_delete:
            es.indices.delete(index=index_name)
            print(f"Deleted index '{index_name}'")
        else:
            print("Keeping existing index. Exiting.")
            return

    index_mapping = {
        "mappings": {
            "properties": {
                "video_id": { "type": "keyword" },
                "start_time_sec": { "type": "float" },
                "end_time_sec": { "type": "float" },
                "video_embedding": {
                    "type": "dense_vector",
                    "dims": settings.EMBEDDING_DIMENSION,
                    "index": True,
                    "similarity": "cosine"
                },
                "labels": {
                    "type": "text",
                    "fields": { "keyword": { "type": "keyword" } }
                },
                "ocr_text": {
                    "type": "text",
                    "fields": { "keyword": { "type": "keyword", "ignore_above": 256 } }
                },
                "objects": {
                    "type": "nested",
                    "properties": {
                        "description": {
                            "type": "text",
                            "fields": { "keyword": { "type": "keyword" } }
                        },
                        "track_id": { "type": "keyword" }
                    }
                },
                "clip_uri": { "type": "keyword" }
            }
        }
    }

    es.indices.create(index=index_name, body=index_mapping)
    print(f"✅ Created index '{index_name}' with mappings:")
    # ... (rest of the print statements)
    print(f"\nIndex ready for ingestion!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Create or recreate the Elasticsearch index.')
    parser.add_argument('--force', action='store_true', help='Delete and recreate the index without prompting.')
    args = parser.parse_args()

    try:
        create_video_index(force=args.force)
    except Exception as e:
        print(f"❌ Error: {e}")
        exit(1)

