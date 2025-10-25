import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
from elasticsearch import Elasticsearch
from config import settings

def cleanup_index(force=False):
    """Delete all video records except burglary_video_compressed from Elasticsearch."""
    es = Elasticsearch(
        settings.ELASTICSEARCH_ENDPOINT,
        api_key=settings.ELASTICSEARCH_API_KEY,
        request_timeout=30
    )

    if not es.ping():
        raise Exception("Cannot connect to Elasticsearch")

    index_name = settings.VIDEO_INDEX_NAME

    if not es.indices.exists(index=index_name):
        print(f"Index '{index_name}' does not exist. Nothing to clean up.")
        return

    # Videos to keep (empty means delete all)
    keep_video_ids = ["burglary_video_compressed"] if False else []

    # Videos to delete (if specified, ignores keep list)
    delete_video_ids = ["fire2", "fire_incident"]

    print(f"🔍 Searching for documents to delete in index '{index_name}'...")

    # Query to find documents to delete
    if delete_video_ids:
        # Delete specific video IDs
        query = {
            "query": {
                "terms": {"video_id": delete_video_ids}
            }
        }
    else:
        # Delete all documents NOT in the keep list
        query = {
            "query": {
                "bool": {
                    "must_not": [
                        {"terms": {"video_id": keep_video_ids}}
                    ]
                }
            }
        }

    # First, count how many documents will be deleted
    count_response = es.count(index=index_name, body=query)
    total_to_delete = count_response['count']

    if total_to_delete == 0:
        print("✅ No documents to delete. Index already clean!")
        return

    print(f"📊 Found {total_to_delete} documents to delete")

    # Get unique video IDs that will be deleted (for logging)
    agg_query = {
        "query": query["query"],
        "size": 0,
        "aggs": {
            "video_ids": {
                "terms": {
                    "field": "video_id",
                    "size": 100
                }
            }
        }
    }

    agg_response = es.search(index=index_name, body=agg_query)
    video_ids_to_delete = [bucket['key'] for bucket in agg_response['aggregations']['video_ids']['buckets']]

    print(f"📝 Video IDs to be deleted: {', '.join(video_ids_to_delete)}")

    # Confirm deletion
    if not force:
        response = input(f"\n⚠️  Are you sure you want to delete {total_to_delete} documents? (yes/N): ")
        if response.lower() != 'yes':
            print("❌ Deletion cancelled.")
            return

    # Delete by query
    print(f"\n🗑️  Deleting documents...")
    delete_response = es.delete_by_query(index=index_name, body=query)

    deleted_count = delete_response.get('deleted', 0)
    print(f"✅ Successfully deleted {deleted_count} documents")

    # Verify what's left
    remaining = es.count(index=index_name)
    print(f"📊 Remaining documents in index: {remaining['count']}")

    # Show remaining video IDs
    remaining_query = {
        "size": 0,
        "aggs": {
            "video_ids": {
                "terms": {
                    "field": "video_id",
                    "size": 100
                }
            }
        }
    }
    remaining_response = es.search(index=index_name, body=remaining_query)
    remaining_video_ids = [bucket['key'] for bucket in remaining_response['aggregations']['video_ids']['buckets']]
    print(f"📝 Remaining video IDs: {', '.join(remaining_video_ids)}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Clean up Elasticsearch index by removing unwanted videos.')
    parser.add_argument('--force', action='store_true', help='Skip confirmation prompt')
    args = parser.parse_args()

    try:
        cleanup_index(force=args.force)
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
