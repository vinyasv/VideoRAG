
import sys
import asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import vertexai
from vertexai.generative_models import GenerativeModel, Part
from config import settings
from backend.video_clipper import create_clips_from_timestamps
from backend.gcs_client import gcs_client

vertexai.init(project=settings.PROJECT_ID, location=settings.LOCATION)

class VertexAIClient:
    def __init__(self):
        self.gemini_model = GenerativeModel(settings.GEMINI_MODEL)

    def get_query_embedding(self, query_text: str) -> list[float]:
        # This function is no longer used in the multimodal flow
        # but kept for potential future use or debugging.
        # In a real application, you might use a dedicated embedding model.
        pass

    async def synthesize_answer(self, query: str, search_results: list, video_id: str) -> str:
        if not search_results:
            return "No relevant clips found for your query."

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
            prompt_parts = [
                f"""You are an expert security analyst. A user is asking a question about a video.
                Your task is to answer their question based *only* on the short video clips provided.
                The user's query is: "{query}"

                Analyze the following video clips and provide a concise, factual answer.
                For every claim you make, you MUST state which clip it is based on (e.g., "In Clip 1, a person is seen...").
                If the clips do not contain enough information, state that clearly.
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
