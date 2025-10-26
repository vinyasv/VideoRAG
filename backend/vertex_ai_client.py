
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
        context_parts.append(f"""You are a helpful security analyst assistant analyzing security footage metadata.
{temporal_instructions}
The user asked: "{query}"

Here is a high-level summary of the entire video:
---
{video_summary}
---

Below are the most relevant video segments found for this query. Use the metadata (labels, OCR text, tracked objects) to answer the user's question.

IMPORTANT GUIDELINES:
- Make reasonable inferences from the available data (e.g., "suspects" in OCR text relates to potential burglars/intruders)
- OCR text often comes from news overlays or chyrons describing the actual video content
- If the segments contain relevant information but use different terminology, still answer the question
- Be helpful and conversational while staying grounded in the actual data
- Only say "no relevant information found" if the segments are truly unrelated to the query

Analyze the following video segment metadata carefully:
""")

        for i, result in enumerate(search_results):
            src = result['_source']

            # Build enhanced object tracking info
            objects_info = []
            for obj in src.get('objects', []):
                frames = obj.get('frames', [])
                if frames:
                    first_frame = frames[0]
                    last_frame = frames[-1]
                    bbox_first = first_frame.get('bounding_box', {})
                    bbox_last = last_frame.get('bounding_box', {})

                    # Calculate movement if we have position data
                    movement_info = ""
                    if bbox_first and bbox_last and len(frames) > 1:
                        # Calculate center positions
                        center_x_first = (bbox_first.get('left', 0) + bbox_first.get('right', 0)) / 2
                        center_y_first = (bbox_first.get('top', 0) + bbox_first.get('bottom', 0)) / 2
                        center_x_last = (bbox_last.get('left', 0) + bbox_last.get('right', 0)) / 2
                        center_y_last = (bbox_last.get('top', 0) + bbox_last.get('bottom', 0)) / 2

                        # Calculate movement distance
                        dx = center_x_last - center_x_first
                        dy = center_y_last - center_y_first
                        distance = (dx**2 + dy**2)**0.5

                        # Determine direction
                        direction = ""
                        if abs(dx) > 0.05 or abs(dy) > 0.05:  # Significant movement
                            h_dir = "right" if dx > 0 else "left"
                            v_dir = "down" if dy > 0 else "up"
                            direction = f"moving {h_dir} and {v_dir}"
                        else:
                            direction = "stationary"

                        movement_info = f", {direction} (distance: {distance:.2f})"

                    obj_desc = (
                        f"  - {obj.get('description', 'unknown')} "
                        f"(track_id: {obj.get('track_id', 'N/A')}, confidence: {obj.get('confidence', 0):.2f})\n"
                        f"    • {len(frames)} frames from {first_frame.get('time_offset_sec', 0):.1f}s "
                        f"to {last_frame.get('time_offset_sec', 0):.1f}s{movement_info}"
                    )
                else:
                    obj_desc = f"  - {obj.get('description', 'unknown')} (track_id: {obj.get('track_id', 'N/A')}, confidence: {obj.get('confidence', 0):.2f})"

                objects_info.append(obj_desc)

            objects_text = '\n'.join(objects_info) if objects_info else '  None'

            # Build OCR items info with timestamps
            ocr_items = src.get('ocr_items', [])
            ocr_info = []
            for ocr in ocr_items[:5]:  # Limit to first 5 for brevity
                time = ocr.get('time_offset_sec', 0)
                conf = ocr.get('confidence', 0)
                text = ocr.get('text', '')
                ocr_info.append(f"  - \"{text}\" at {time:.1f}s (confidence: {conf:.2f})")

            ocr_text = '\n'.join(ocr_info) if ocr_info else f"  {src.get('ocr_text', 'None')}"

            # Add shot labels
            shot_labels = src.get('shot_labels', [])
            shot_labels_text = ', '.join(shot_labels) if shot_labels else 'None'

            context_parts.append(f"""
--- Segment {i+1} ({src['start_time_sec']:.0f}s - {src['end_time_sec']:.0f}s) ---
Labels detected: {', '.join(src.get('labels', []))}
Shot labels: {shot_labels_text}
Text visible (OCR):
{ocr_text}
Objects tracked:
{objects_text}
""")

        context_parts.append(f"""
Now provide a concise, helpful answer to: "{query}"

ANALYSIS CAPABILITIES YOU HAVE:
- MOVEMENT: Use the "moving" direction and distance to detect approaches, departures, or tracking
- COUNTING: Use unique track_ids within a segment to count simultaneous objects (e.g., "2 people" if track_id 0 and 1)
- SPATIAL: Use position data and movement to understand "near", "approaching", "leaving" behaviors
- TEMPORAL: Use frame timestamps to determine when objects appear/disappear
- INFERENCE: Draw reasonable conclusions from OCR text and labels (e.g., news overlay saying "suspects" indicates potential burglars)

IMPORTANT: Always reference timestamps when making claims (e.g., "Between 4-12 seconds, ..." or "At around 8 seconds, ...").
Use the time ranges shown in the metadata above (e.g., "4s - 12s"), NOT segment numbers like "Segment 1".
If you genuinely cannot answer from the available metadata, say so, but be generous in your interpretation.
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

        # Extract pre-clipped URIs and metadata from search results
        clips_with_metadata = [
            {
                'uri': r['_source'].get('clip_uri'),
                'start_time': r['_source'].get('start_time_sec'),
                'end_time': r['_source'].get('end_time_sec')
            }
            for r in search_results
            if r['_source'].get('clip_uri')
        ]

        if not clips_with_metadata:
            return "Could not find pre-clipped video segments for analysis."

        # Limit to top 3 clips to improve performance
        print(f"ℹ️ Sending {len(clips_with_metadata[:3])} clips to the LLM for synthesis.")
        clips_with_metadata = clips_with_metadata[:3]

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
                f"""You are a helpful security analyst assistant analyzing security footage.
{temporal_instructions}
The user asked: "{query}"

Here is a high-level summary of the entire video:
---
{video_summary}
---

Below are the most relevant video clips found for this query. Watch them carefully and answer the user's question based on what you observe.

IMPORTANT GUIDELINES:
- Make reasonable inferences from what you see (e.g., people at a door at night may be suspicious activity)
- Pay attention to OCR text overlays in the video - they often describe the events shown
- Be helpful and conversational while staying grounded in what's actually visible
- Provide specific details from the clips when available
- Reference clips WITH their timestamps (e.g., "In Clip 1 (4-12 seconds), ...")
{f'- For temporal queries, ALWAYS try to include specific times if they are visible in the footage.' if is_temporal else ''}
- Only say "no relevant footage" if the clips are truly unrelated to the query
- Draw on the video summary for broader context when appropriate
                """
            ]

            for i, clip_data in enumerate(clips_with_metadata):
                start = clip_data['start_time']
                end = clip_data['end_time']
                prompt_parts.append(f"\n--- Clip {i+1} ({start:.0f}-{end:.0f} seconds) ---")
                prompt_parts.append(Part.from_uri(clip_data['uri'], mime_type="video/mp4"))

            # 3. Call the Gemini model
            response = await self.gemini_model.generate_content_async(prompt_parts)
            return response.text

        except Exception as e:
            print(f"❌ Error during answer synthesis: {e}")
            raise


vertex_ai_client = VertexAIClient()
