
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import vertexai
from vertexai.generative_models import GenerativeModel, Part
from vertexai.vision_models import MultiModalEmbeddingModel
from config import settings

vertexai.init(project=settings.PROJECT_ID, location=settings.LOCATION)

class VertexAIClient:
    def __init__(self):
        self.gemini_model = GenerativeModel(settings.GEMINI_MODEL)
        self.embedding_model = MultiModalEmbeddingModel.from_pretrained(settings.EMBEDDING_MODEL)

    def get_query_embedding(self, query_text: str) -> list[float] | None:
        """Generate text embedding for search query using the multimodal embedding model."""
        try:
            embedding_response = self.embedding_model.get_embeddings(
                contextual_text=query_text,
                dimension=settings.EMBEDDING_DIMENSION
            )
            return embedding_response.text_embedding
        except Exception as e:
            print(f"⚠️ Warning: Failed to generate query embedding: {e}")
            print("   Falling back to text-only search")
            return None

    async def synthesize_answer_text_only(self, query: str, search_results: list, video_id: str, video_summary: str) -> str:
        """Generate answer using only text metadata (no video clips) - FAST mode"""
        if not search_results:
            prompt = f"""You are an expert security analyst. A user asked a question about a video, but the search system could not find any relevant video segments.
            Your task is to inform the user that no relevant footage was found for their specific query and suggest they try rephrasing their question or asking about a different event.
            The user's original query was: "{query}"
            """
            response = await self.gemini_model.generate_content_async(prompt)
            return response.text

        # Detect temporal queries
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

        # Build text-only context
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
        response = await self.gemini_model.generate_content_async(prompt)
        return response.text

    async def synthesize_answer(self, query: str, search_results: list, video_id: str, video_summary: str) -> str:
        if not search_results:
            # Handle case where no clips are found by sending a specific prompt to the LLM
            prompt = f"""You are an expert security analyst. A user asked a question about a video, but the search system could not find any relevant video clips.
            Your task is to inform the user that no relevant footage was found for their specific query and suggest they try rephrasing their question or asking about a different event.
            The user's original query was: "{query}"
            """
            response = await self.gemini_model.generate_content_async(prompt)
            return response.text

        # Extract pre-clipped URIs from search results
        clipped_video_uris = [
            r['_source'].get('clip_uri')
            for r in search_results
            if r['_source'].get('clip_uri')
        ]

        if not clipped_video_uris:
            return "Could not find pre-clipped video segments for analysis."

        try:
            # 2. Build the multimodal prompt
            # Detect if this is a temporal query
            temporal_keywords = ['when', 'what time', 'time did', 'at what', 'hour', 'minute', 'o\'clock']
            is_temporal = any(kw in query.lower() for kw in temporal_keywords)

            # Build temporal-specific instructions
            temporal_instructions = ""
            if is_temporal:
                temporal_instructions = """
IMPORTANT: This is a TEMPORAL query asking about WHEN something happened.
- Look CAREFULLY for visible timestamps in security camera overlays (common format: MM-DD-YYYY HH:MM:SS AM/PM)
- If you see timestamps displayed in the video frame (usually in corners or overlays), extract the EXACT time
- Include the specific time in your answer (e.g., "at 12:14:27 PM on 09/14/2016")
- If no timestamp is visible, indicate times relative to the clip (e.g., "approximately 0:04 into the clip")
"""

            prompt_parts = [
                f"""You are an expert security analyst analyzing security footage.
{temporal_instructions}
First, here is a high-level summary of the entire video for context:
---
{video_summary}
---

Now, using that summary for context, your main task is to answer the user's specific query. Base all your factual claims *only* on the short video clips provided below.
The user's query is: "{query}"

Analyze the following video clips and provide a concise, factual answer.
For every claim you make, you MUST state which clip it is based on (e.g., "In Clip 1, a person is seen...").
{f'For temporal queries, ALWAYS try to include specific times if they are visible in the footage.' if is_temporal else ''}
If the clips do not contain enough information, state that clearly.
Finally, provide a concluding sentence that connects your clip analysis to the overall video summary.
                """
            ]

            for i, uri in enumerate(clipped_video_uris):
                prompt_parts.append(f"\n--- Clip {i+1} ---")
                prompt_parts.append(Part.from_uri(uri, mime_type="video/mp4"))

            # 3. Call the Gemini model
            response = await self.gemini_model.generate_content_async(prompt_parts)
            return response.text

        except Exception as e:
            print(f"❌ Error during answer synthesis: {e}")
            raise


vertex_ai_client = VertexAIClient()
