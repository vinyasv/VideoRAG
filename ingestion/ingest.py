import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
import asyncio
from elasticsearch import AsyncElasticsearch
from elasticsearch.helpers import async_streaming_bulk
from config import settings
import json
from ingestion.video_processor import VideoProcessor
import os
import time

def update_video_summary(video_id, summary):
    """Reads, updates, and writes the video summaries JSON file with file locking."""
    summary_file = Path(__file__).parent.parent / 'video_summaries.json'
    lock_dir = Path(__file__).parent.parent / 'video_summaries.json.lock'
    summaries = {}

    # Acquire lock
    retries = 10
    retry_delay = 1 # second
    for i in range(retries):
        try:
            os.mkdir(lock_dir)
            break
        except FileExistsError:
            if i < retries - 1:
                print(f"Waiting for summary file lock... (attempt {i+1}/{retries})")
                time.sleep(retry_delay)
            else:
                print("Could not acquire lock. Aborting summary update.")
                return

    try:
        # Read existing summaries if the file exists
        if summary_file.exists():
            with open(summary_file, 'r') as f:
                try:
                    summaries = json.load(f)
                except json.JSONDecodeError:
                    print(f"⚠️ Warning: Could not decode {summary_file}. Starting fresh.")

        # Update the summary for the current video
        summaries[video_id] = summary

        # Write the updated summaries back to the file
        with open(summary_file, 'w') as f:
            json.dump(summaries, f, indent=4)
        print(f"✓ Video summary saved to {summary_file}")
    finally:
        # Release lock
        os.rmdir(lock_dir)


async def index_documents_async(es_client, documents):
    """Index documents using async bulk operations with progress tracking"""
    actions = []
    for doc in documents:
        # Create a deterministic, unique ID for each video segment
        doc_id = f"{doc['video_id']}_{doc['start_time_sec']}"
        actions.append({
            "_index": settings.VIDEO_INDEX_NAME,
            "_id": doc_id,
            "_source": doc
        })
    
    print(f"Indexing {len(actions)} documents...")
    success_count = 0
    failed_count = 0
    
    # Use async_streaming_bulk for proper async iteration
    async for ok, result in async_streaming_bulk(es_client, actions, chunk_size=100):
        if ok:
            success_count += 1
            if success_count % 10 == 0:
                print(f"  ✓ Indexed {success_count}/{len(actions)} documents")
        else:
            failed_count += 1
            print(f"  ❌ Failed to index document: {result}")
    
    return success_count, failed_count

async def main_async():
    parser = argparse.ArgumentParser(description='Ingest video into Sentinel')
    parser.add_argument('--video-path', required=True, help='Path to video file (local or GCS URI)')
    parser.add_argument('--video-id', required=True, help='Unique identifier for the video')
    parser.add_argument('--duration', type=int, help='Video duration in seconds (optional, will analyze if not provided)')
    
    args = parser.parse_args()
    
    print(f"Starting ingestion for video: {args.video_id}")
    print(f"Video path: {args.video_path}")
    
    try:
        processor = VideoProcessor()

        print("\n[1/4] Analyzing video with Video Intelligence API...")
        metadata, gcs_uri, summary = await processor.analyze_video(args.video_path)
        print(f"✓ Found {len(metadata['labels_by_time'])} seconds with labels")
        print(f"✓ Found {len(metadata['ocr_by_time'])} seconds with OCR text")

        if args.duration:
            video_duration = args.duration
        else:
            video_duration = max(
                max([int(k) for k in metadata['labels_by_time'].keys()] or [0]),
                max([int(k) for k in metadata['ocr_by_time'].keys()] or [0])
            ) + 1

        print(f"\n[2/5] Creating chunks (duration: {video_duration}s)...")
        chunks = processor.create_chunks(video_duration)
        print(f"✓ Created {len(chunks)} chunks")

        print(f"\n[3/5] Creating and uploading video clips...")
        clip_uris = await processor.create_clip_files(gcs_uri, chunks, args.video_id)
        print(f"✓ Created {len([uri for uri in clip_uris if uri])} clips")

        print(f"\n[4/5] Generating embeddings...")
        embeddings = processor.generate_embeddings(gcs_uri, chunks)
        print(f"✓ Generated {len(embeddings)} embeddings")

        print(f"\n[5/5] Creating documents and indexing...")
        documents = processor.create_documents(args.video_id, chunks, embeddings, metadata, clip_uris)
        
        es = AsyncElasticsearch(
            settings.ELASTICSEARCH_ENDPOINT,
            api_key=settings.ELASTICSEARCH_API_KEY,
            request_timeout=60
        )
        
        success, failed = await index_documents_async(es, documents)
        await es.close()
        
        print(f"✓ Indexed {success} documents")
        
        if failed:
            print(f"⚠ Failed to index {failed} documents")
        
        print(f"\n✅ Ingestion complete for {args.video_id}")
        print(f"Total segments indexed: {len(documents)}")

        # Save the generated summary
        update_video_summary(args.video_id, summary)
        
    except Exception as e:
        print(f"\n❌ Ingestion failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1
    
    return 0

def main():
    return asyncio.run(main_async())

if __name__ == "__main__":
    exit(main())

