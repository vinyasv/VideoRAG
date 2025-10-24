
import asyncio
import time
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from backend.vertex_ai_client import vertex_ai_client
from backend.elasticsearch_client import ElasticsearchClient
from backend.video_clipper import create_clips_from_timestamps
from backend.gcs_client import gcs_client

# --- Configuration ---
TEST_QUERY = "a person walking"
TEST_VIDEO_ID = "demo.mp4"

async def main():
    """
    Debug script to isolate and time each component of the Sentinel query process.
    """
    print("--- Starting Performance Debug Script ---")

    es_client = ElasticsearchClient()

    # --- 1. Time Embedding Generation ---
    print("\n[1/4] Timing Embedding Generation...")
    start_time = time.time()
    query_embedding = vertex_ai_client.get_query_embedding(TEST_QUERY)
    end_time = time.time()
    print(f"    Embedding generated in: {end_time - start_time:.2f} seconds")
    if query_embedding is None:
        print("    Failed to generate embedding. Exiting.")
        return

    # --- 2. Time Elasticsearch Search ---
    print("\n[2/4] Timing Elasticsearch Hybrid Search...")
    start_time = time.time()
    search_results = await es_client.hybrid_search(
        query_embedding=query_embedding,
        query_text=TEST_QUERY,
        video_id=TEST_VIDEO_ID,
        top_k=5
    )
    end_time = time.time()
    print(f"    Elasticsearch search completed in: {end_time - start_time:.2f} seconds")
    if not search_results:
        print("    No search results found. Cannot proceed to clipping and synthesis.")
        await es_client.close()
        return
    print(f"    Found {len(search_results)} results.")


    # --- 3. Time Video Clipping ---
    print("\n[3/4] Timing Video Clipping...")
    timestamps = [
        {"start_time_sec": r['_source']['start_time_sec'], "end_time_sec": r['_source']['end_time_sec']}
        for r in search_results
    ]
    source_video_uri = gcs_client.get_video_uri(TEST_VIDEO_ID)

    start_time = time.time()
    clipped_uris = await create_clips_from_timestamps(source_video_uri, timestamps)
    end_time = time.time()
    print(f"    Video clipping completed in: {end_time - start_time:.2f} seconds")
    print(f"    Created {len(clipped_uris)} clips.")


    # --- 4. Time Answer Synthesis ---
    print("\n[4/4] Timing Answer Synthesis...")
    video_summary = "This is a test summary for debugging purposes."

    start_time = time.time()
    answer = await vertex_ai_client.synthesize_answer(
        TEST_QUERY, search_results, TEST_VIDEO_ID, video_summary
    )
    end_time = time.time()
    print(f"    Answer synthesis (including internal clipping) completed in: {end_time - start_time:.2f} seconds")
    print(f"    Generated answer: {answer[:100]}...")


    await es_client.close()
    print("\n--- Performance Debug Script Finished ---")


if __name__ == "__main__":
    asyncio.run(main())
