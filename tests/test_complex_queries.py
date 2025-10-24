#!/usr/bin/env python3
"""
Comprehensive query testing script to evaluate VideoRAG system performance.
Tests various query types across both videos.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import asyncio
import json
from datetime import datetime
from backend.elasticsearch_client import ElasticsearchClient
from backend.vertex_ai_client import vertex_ai_client

# Test queries organized by type
TEST_QUERIES = {
    "fire2": {
        "temporal": [
            "When did the fire truck arrive?",
            "What time did emergency responders first appear?",
            "When did people start gathering around?"
        ],
        "object_focused": [
            "Show me all the fire trucks and emergency vehicles",
            "Where are the firefighters?",
            "Show me when people are visible in the scene"
        ],
        "activity": [
            "What are the firefighters doing?",
            "What emergency response activities are happening?",
            "Are there any people evacuating or moving away from the scene?"
        ],
        "semantic": [
            "What is the overall situation in this video?",
            "How serious is the emergency?",
            "What safety equipment can you see being used?"
        ],
        "specific_detail": [
            "Can you see any smoke or flames?",
            "Are there any civilian cars in the scene?",
            "What color are the emergency vehicles?"
        ]
    },
    "burglars_new": {
        "temporal": [
            "When did the person approach the door?",
            "What time did someone knock or ring the doorbell?",
            "When did the homeowner react?"
        ],
        "object_focused": [
            "Show me when people are at the door",
            "Where is the homeowner in the video?",
            "Show me the door or entrance"
        ],
        "activity": [
            "What are the people at the door doing?",
            "What is the homeowner doing?",
            "Is anyone trying to enter the house?"
        ],
        "semantic": [
            "What is happening in this video?",
            "Is this a suspicious situation?",
            "What security concerns are visible?"
        ],
        "specific_detail": [
            "Are the people at the door wearing any uniforms?",
            "Can you see any tools or equipment?",
            "What does the door look like?"
        ]
    }
}

async def run_query(es_client, video_id: str, query: str):
    """Run a single query and return detailed results."""
    print(f"\n{'='*80}")
    print(f"VIDEO: {video_id}")
    print(f"QUERY: {query}")
    print(f"{'='*80}")

    try:
        # Generate query embedding
        print("Generating query embedding...")
        query_embedding = vertex_ai_client.get_query_embedding(query)

        if query_embedding is None:
            print("⚠️  WARNING: Query embedding is None, will use text-only search")
        else:
            print(f"✅ Generated {len(query_embedding)}-dimension embedding")

        # Perform hybrid search
        print(f"\nSearching video '{video_id}'...")
        search_results = await es_client.hybrid_search(
            query_embedding=query_embedding,
            query_text=query,
            video_id=video_id,
            top_k=5
        )

        print(f"\n📊 SEARCH RESULTS: Found {len(search_results)} clips")
        print("-" * 80)

        if not search_results:
            print("❌ No results found")
            return {
                "video_id": video_id,
                "query": query,
                "num_results": 0,
                "clips": [],
                "answer": None,
                "success": False
            }

        # Display clip details
        for i, hit in enumerate(search_results, 1):
            source = hit['_source']
            score = hit['_score']
            start = source['start_time_sec']
            end = source['end_time_sec']
            labels = source.get('labels', [])
            ocr = source.get('ocr_text', '')

            print(f"\nClip {i}: [{start:.1f}s - {end:.1f}s] (score: {score:.3f})")
            print(f"  Labels: {', '.join(labels[:5]) if labels else 'None'}")
            if ocr:
                print(f"  OCR: {ocr[:100]}{'...' if len(ocr) > 100 else ''}")

        # Load video summary
        summary_file = Path(__file__).parent / 'video_summaries.json'
        video_summary = "No summary available."
        if summary_file.exists():
            with open(summary_file, 'r') as f:
                summaries = json.load(f)
                video_summary = summaries.get(video_id, "No summary available for this video.")

        # Generate answer
        print(f"\n💬 GENERATING ANSWER...")
        print("-" * 80)
        answer = await vertex_ai_client.synthesize_answer(
            query, search_results, video_id, video_summary
        )
        print(f"\nANSWER:\n{answer}")

        result = {
            "video_id": video_id,
            "query": query,
            "num_results": len(search_results),
            "clips": [
                {
                    "start": hit['_source']['start_time_sec'],
                    "end": hit['_source']['end_time_sec'],
                    "score": hit['_score'],
                    "labels": hit['_source'].get('labels', [])[:10],
                    "ocr": hit['_source'].get('ocr_text', '')[:200]
                }
                for hit in search_results
            ],
            "answer": answer,
            "success": True
        }

        return result

    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return {
            "video_id": video_id,
            "query": query,
            "error": str(e),
            "success": False
        }

async def run_all_tests():
    """Run all test queries and save results."""
    print("=" * 80)
    print("VIDEORAG SYSTEM - COMPREHENSIVE QUERY TESTING")
    print("=" * 80)
    print(f"Start time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    es_client = ElasticsearchClient()
    all_results = []

    try:
        for video_id, categories in TEST_QUERIES.items():
            print(f"\n\n{'#'*80}")
            print(f"# TESTING VIDEO: {video_id.upper()}")
            print(f"{'#'*80}\n")

            for category, queries in categories.items():
                print(f"\n{'~'*80}")
                print(f"~ CATEGORY: {category.upper().replace('_', ' ')}")
                print(f"{'~'*80}")

                for query in queries:
                    result = await run_query(es_client, video_id, query)
                    result['category'] = category
                    all_results.append(result)

                    # Brief pause between queries
                    await asyncio.sleep(1)

        # Save results to file
        output_file = Path(__file__).parent / 'query_test_results.json'
        with open(output_file, 'w') as f:
            json.dump({
                'timestamp': datetime.now().isoformat(),
                'total_queries': len(all_results),
                'results': all_results
            }, f, indent=2)

        print(f"\n\n{'='*80}")
        print("TEST SUMMARY")
        print(f"{'='*80}")
        print(f"Total queries executed: {len(all_results)}")
        print(f"Successful queries: {sum(1 for r in all_results if r.get('success'))}")
        print(f"Failed queries: {sum(1 for r in all_results if not r.get('success'))}")
        print(f"\nResults saved to: {output_file}")

        # Category breakdown
        print(f"\n{'='*80}")
        print("CATEGORY BREAKDOWN")
        print(f"{'='*80}")
        for video_id in TEST_QUERIES.keys():
            print(f"\n{video_id}:")
            video_results = [r for r in all_results if r.get('video_id') == video_id]
            categories = {}
            for r in video_results:
                cat = r.get('category', 'unknown')
                if cat not in categories:
                    categories[cat] = {'total': 0, 'success': 0}
                categories[cat]['total'] += 1
                if r.get('success'):
                    categories[cat]['success'] += 1

            for cat, stats in categories.items():
                print(f"  {cat}: {stats['success']}/{stats['total']} successful")

    finally:
        await es_client.close()

    print(f"\n{'='*80}")
    print(f"End time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*80}\n")

if __name__ == "__main__":
    asyncio.run(run_all_tests())
