#!/usr/bin/env python3
"""
Test improvements after fixes:
1. Temporal query accuracy
2. Score normalization
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

import asyncio
import json
import statistics
from backend.elasticsearch_client import ElasticsearchClient
from backend.vertex_ai_client import vertex_ai_client

# Subset of queries focusing on temporal and score variance
TEST_QUERIES = [
    # Temporal queries (where we expect improvement)
    {"video_id": "fire2", "query": "When did the firefighters arrive?", "type": "temporal"},
    {"video_id": "fire2", "query": "What time did emergency responders first appear?", "type": "temporal"},
    {"video_id": "burglars_new", "query": "When did the person approach the door?", "type": "temporal"},
    {"video_id": "burglars_new", "query": "What time did someone knock or ring the doorbell?", "type": "temporal"},

    # Regular queries (to test score normalization)
    {"video_id": "fire2", "query": "Show me the firefighters", "type": "object"},
    {"video_id": "burglars_new", "query": "Show me people at the door", "type": "object"},
]

async def test_query(es_client, query_info):
    """Test a single query and analyze results"""
    video_id = query_info["video_id"]
    query = query_info["query"]
    query_type = query_info["type"]

    print(f"\n{'='*80}")
    print(f"VIDEO: {video_id}")
    print(f"QUERY: {query}")
    print(f"TYPE: {query_type}")
    print(f"{'='*80}")

    # Generate embedding and search
    query_embedding = vertex_ai_client.get_query_embedding(query)
    search_results = await es_client.hybrid_search(
        query_embedding=query_embedding,
        query_text=query,
        video_id=video_id,
        top_k=5
    )

    # Analyze scores
    scores = [hit.get('_normalized_score', hit.get('_score', 0)) for hit in search_results]
    original_scores = [hit.get('_original_score', hit.get('_score', 0)) for hit in search_results]

    print(f"\n📊 SCORE ANALYSIS:")
    print(f"  Normalized scores: {[f'{s:.3f}' for s in scores]}")
    print(f"  Original scores: {[f'{s:.3f}' for s in original_scores]}")
    print(f"  Normalized range: {min(scores):.3f} - {max(scores):.3f}")
    print(f"  Original range: {min(original_scores):.3f} - {max(original_scores):.3f}")

    # Generate answer
    video_summaries = {
        "fire2": "Security footage showing emergency response to a fire incident.",
        "burglars_new": "Security footage showing a burglary attempt at a residence."
    }

    answer = await vertex_ai_client.synthesize_answer(
        query, search_results, video_id, video_summaries.get(video_id, "")
    )

    # Check for temporal information
    if query_type == "temporal":
        # Check for specific times (HH:MM format or "0:XX" for relative)
        has_specific_time = any(pattern in answer for pattern in [
            '12:', '1:', '2:', '3:', 'PM', 'AM', '0:0', '0:1', '0:2', '0:3', '0:4', '0:5'
        ])

        print(f"\n⏰ TEMPORAL ANALYSIS:")
        print(f"  Contains time info: {'✅ YES' if has_specific_time else '❌ NO'}")

        # Extract time mentions
        import re
        time_patterns = [
            r'\d{1,2}:\d{2}:\d{2}\s*(?:AM|PM)',  # 12:14:27 PM
            r'\d{1,2}:\d{2}\s*(?:AM|PM)',        # 12:14 PM
            r'approximately\s+\d+:\d+',           # approximately 0:04
            r'at\s+\d+:\d+',                      # at 0:02
        ]

        times_found = []
        for pattern in time_patterns:
            matches = re.findall(pattern, answer, re.IGNORECASE)
            times_found.extend(matches)

        if times_found:
            print(f"  Times mentioned: {times_found}")

    print(f"\n💬 ANSWER PREVIEW:")
    print(f"  {answer[:250]}...")

    return {
        "video_id": video_id,
        "query": query,
        "type": query_type,
        "normalized_scores": scores,
        "original_scores": original_scores,
        "has_temporal_info": has_specific_time if query_type == "temporal" else None,
        "times_found": times_found if query_type == "temporal" else None,
        "answer_length": len(answer)
    }

async def main():
    print("="*80)
    print("TESTING IMPROVEMENTS: TEMPORAL ACCURACY & SCORE NORMALIZATION")
    print("="*80)

    es_client = ElasticsearchClient()
    results = []

    try:
        for query_info in TEST_QUERIES:
            result = await test_query(es_client, query_info)
            results.append(result)
            await asyncio.sleep(1)

        # Summary
        print(f"\n\n{'='*80}")
        print("IMPROVEMENT SUMMARY")
        print(f"{'='*80}")

        # Temporal accuracy
        temporal_results = [r for r in results if r['type'] == 'temporal']
        temporal_with_time = sum(1 for r in temporal_results if r['has_temporal_info'])

        print(f"\n⏰ TEMPORAL QUERY ACCURACY:")
        print(f"  Queries with time info: {temporal_with_time}/{len(temporal_results)} ({temporal_with_time/len(temporal_results)*100:.0f}%)")
        print(f"  IMPROVEMENT: Was 50% (3/6), now {temporal_with_time/len(temporal_results)*100:.0f}%")

        # Score normalization
        all_normalized = [s for r in results for s in r['normalized_scores']]
        all_original = [s for r in results for s in r['original_scores']]

        print(f"\n📊 SCORE NORMALIZATION:")
        print(f"  BEFORE (original scores):")
        print(f"    Range: {min(all_original):.3f} - {max(all_original):.3f}")
        print(f"    Std Dev: {statistics.stdev(all_original):.3f}")
        print(f"  AFTER (normalized scores):")
        print(f"    Range: {min(all_normalized):.3f} - {max(all_normalized):.3f}")
        print(f"    Std Dev: {statistics.stdev(all_normalized):.3f}")
        print(f"  IMPROVEMENT: Range reduced from {max(all_original)-min(all_original):.1f} to {max(all_normalized)-min(all_normalized):.1f}")

        # Save results
        output_file = Path(__file__).parent / 'improvement_test_results.json'
        with open(output_file, 'w') as f:
            json.dump({
                'summary': {
                    'temporal_accuracy': f'{temporal_with_time}/{len(temporal_results)}',
                    'temporal_percentage': temporal_with_time/len(temporal_results)*100,
                    'score_range_before': max(all_original) - min(all_original),
                    'score_range_after': max(all_normalized) - min(all_normalized),
                    'score_std_before': statistics.stdev(all_original),
                    'score_std_after': statistics.stdev(all_normalized)
                },
                'detailed_results': results
            }, f, indent=2, default=str)

        print(f"\n✅ Results saved to: {output_file}")

    finally:
        await es_client.close()

if __name__ == "__main__":
    asyncio.run(main())
