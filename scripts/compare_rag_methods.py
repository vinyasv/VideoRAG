#!/usr/bin/env python3
"""
Qualitative comparison of Video Clip RAG vs Text-Only RAG
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import asyncio
import time
import json
from backend.elasticsearch_client import ElasticsearchClient
from backend.vertex_ai_client import vertex_ai_client
from vertexai.generative_models import GenerativeModel
from config import settings

async def get_text_only_answer(query: str, search_results: list, video_id: str, video_summary: str) -> str:
    """Generate answer using only text metadata (no video clips)"""

    if not search_results:
        return "No relevant segments found."

    # Build text-only context
    temporal_keywords = ['when', 'what time', 'time did', 'at what', 'hour', 'minute', 'o\'clock']
    is_temporal = any(kw in query.lower() for kw in temporal_keywords)

    temporal_instructions = ""
    if is_temporal:
        temporal_instructions = """
IMPORTANT: This is a TEMPORAL query asking about WHEN something happened.
- Look for timestamps in the OCR text
- If timestamps are visible, extract the EXACT time
- Include specific times in your answer
"""

    # Build metadata context
    context_parts = []
    context_parts.append(f"""You are an expert security analyst analyzing security footage.
{temporal_instructions}
First, here is a high-level summary of the entire video for context:
---
{video_summary}
---

Now, using that summary for context, your main task is to answer the user's specific query.
The user's query is: "{query}"

You have access to the following video segment metadata. Analyze it carefully and provide a concise, factual answer.
""")

    for i, result in enumerate(search_results):
        src = result['_source']
        context_parts.append(f"""
--- Segment {i+1} ({src['start_time_sec']:.0f}s - {src['end_time_sec']:.0f}s) ---
Labels detected: {', '.join(src.get('labels', []))}
Text visible (OCR): {src.get('ocr_text', 'None')}
Objects tracked: {', '.join([obj['description'] for obj in src.get('objects', [])])}
""")

    context_parts.append(f"""
Based on this metadata, provide a concise answer to the query: "{query}"
For every claim you make, state which segment it is based on.
If the metadata does not contain enough information, state that clearly.
""")

    prompt = '\n'.join(context_parts)

    # Call Gemini with text-only prompt
    gemini_model = GenerativeModel(settings.GEMINI_MODEL)
    response = await gemini_model.generate_content_async(prompt)
    return response.text


async def compare_methods(query: str, video_id: str = 'demo'):
    """Compare video clip RAG vs text-only RAG for a given query"""

    es_client = ElasticsearchClient()

    print('=' * 80)
    print(f'QUERY: "{query}"')
    print('=' * 80)

    # Get search results
    query_embedding = vertex_ai_client.get_query_embedding(query)
    search_results = await es_client.hybrid_search(
        query_embedding=query_embedding,
        query_text=query,
        video_id=video_id,
        top_k=5
    )

    # Load video summary
    summary_file = Path(__file__).parent.parent / 'video_summaries.json'
    video_summary = "No summary available."
    if summary_file.exists():
        with open(summary_file, 'r') as f:
            summaries = json.load(f)
            video_summary = summaries.get(video_id, "No summary available.")

    print(f'\nFound {len(search_results)} relevant segments\n')

    # Method 1: Video Clip RAG (current approach)
    print('─' * 80)
    print('METHOD 1: VIDEO CLIP RAG (Current)')
    print('─' * 80)
    start = time.time()
    video_answer = await vertex_ai_client.synthesize_answer(
        query, search_results, video_id, video_summary
    )
    video_time = time.time() - start
    print(f'Response time: {video_time:.2f}s\n')
    print('ANSWER:')
    print(video_answer)
    print()

    # Method 2: Text-Only RAG
    print('─' * 80)
    print('METHOD 2: TEXT-ONLY RAG (Metadata only, no video clips)')
    print('─' * 80)
    start = time.time()
    text_answer = await get_text_only_answer(query, search_results, video_id, video_summary)
    text_time = time.time() - start
    print(f'Response time: {text_time:.2f}s\n')
    print('ANSWER:')
    print(text_answer)
    print()

    # Summary
    print('=' * 80)
    print('COMPARISON SUMMARY')
    print('=' * 80)
    print(f'Video Clip RAG time:  {video_time:.2f}s')
    print(f'Text-Only RAG time:   {text_time:.2f}s')
    print(f'Speed improvement:    {((video_time - text_time) / video_time * 100):.1f}% faster with text-only')
    print('=' * 80)
    print()

    await es_client.close()

    return {
        'query': query,
        'video_answer': video_answer,
        'video_time': video_time,
        'text_answer': text_answer,
        'text_time': text_time
    }


async def run_full_analysis():
    """Run comprehensive analysis with multiple query types"""

    queries = [
        "What happened at the door?",
        "Describe the suspects at the door",
        "What was the door number?",
        "When did the shooting occur?"
    ]

    print('\n')
    print('╔' + '═' * 78 + '╗')
    print('║' + ' ' * 20 + 'QUALITATIVE RAG ANALYSIS' + ' ' * 34 + '║')
    print('║' + ' ' * 15 + 'Video Clips vs Text-Only Metadata' + ' ' * 30 + '║')
    print('╚' + '═' * 78 + '╝')
    print()

    results = []
    for i, query in enumerate(queries, 1):
        print(f'\n\n{"▓" * 80}')
        print(f'TEST {i}/{len(queries)}')
        print(f'{"▓" * 80}\n')

        result = await compare_methods(query)
        results.append(result)

        # Pause between queries
        if i < len(queries):
            print('\nWaiting 2 seconds before next query...\n')
            await asyncio.sleep(2)

    # Final summary
    print('\n\n')
    print('╔' + '═' * 78 + '╗')
    print('║' + ' ' * 28 + 'FINAL SUMMARY' + ' ' * 37 + '║')
    print('╚' + '═' * 78 + '╝')
    print()

    avg_video_time = sum(r['video_time'] for r in results) / len(results)
    avg_text_time = sum(r['text_time'] for r in results) / len(results)

    print(f'Average Video Clip RAG time:  {avg_video_time:.2f}s')
    print(f'Average Text-Only RAG time:   {avg_text_time:.2f}s')
    print(f'Average speed improvement:    {((avg_video_time - avg_text_time) / avg_video_time * 100):.1f}%')
    print()
    print('Quality Assessment: [Manual review required]')
    print('- Review answers above to determine if video clips provide')
    print('  significantly better detail and accuracy to justify the')
    print(f'  additional {avg_video_time - avg_text_time:.1f}s latency per query.')
    print()


if __name__ == "__main__":
    asyncio.run(run_full_analysis())
