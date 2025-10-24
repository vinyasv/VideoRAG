
import sys
import asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import vertexai
from vertexai.generative_models import GenerativeModel, Part
from vertexai.vision_models import MultiModalEmbeddingModel
from config import settings
from backend.video_clipper import create_clips_from_timestamps
from backend.gcs_client import gcs_client

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

    async def synthesize_answer(self, query: str, search_results: list, video_id: str, video_summary: str) -> str:
        if not search_results:
            # Handle case where no clips are found by sending a specific prompt to the LLM
            prompt = f"""You are an expert security analyst. A user asked a question about a video, but the search system could not find any relevant video clips.
            Your task is to inform the user that no relevant footage was found for their specific query and suggest they try rephrasing their question or asking about a different event.
            The user's original query was: "{query}"
            """
            response = await self.gemini_model.generate_content_async(prompt)
            return response.text

        timestamps = [
            {"start_time_sec": r['_source']['start_time_sec'], "end_time_sec": r['_source']['end_time_sec']}
            for r in search_results
        ]

        source_video_uri = gcs_client.get_video_uri(video_id)

        # 1. Create temporary clips
        clipped_video_uris = await create_clips_from_timestamps(source_video_uri, timestamps)

        if not clipped_video_uris:
            return "Could not extract relevant video clips for analysis."

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

        finally:
            # 4. Clean up the temporary clips
            print(f"Cleaning up {len(clipped_video_uris)} temporary clips...")
            await asyncio.gather(*[
                asyncio.to_thread(gcs_client.delete_video, uri) for uri in clipped_video_uris
            ])
            print("Cleanup complete.")


vertex_ai_client = VertexAIClient()
