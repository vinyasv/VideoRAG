import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import vertexai
from vertexai.vision_models import MultiModalEmbeddingModel
from vertexai.generative_models import GenerativeModel
from config import settings

vertexai.init(project=settings.PROJECT_ID, location=settings.LOCATION)

class VertexAIClient:
    def __init__(self):
        self.embedding_model = MultiModalEmbeddingModel.from_pretrained(settings.EMBEDDING_MODEL)
        self.gemini_model = GenerativeModel(settings.GEMINI_MODEL)

    def get_query_embedding(self, query_text: str) -> list[float]:
        response = self.embedding_model.get_embeddings(
            contextual_text=query_text,
            dimension=settings.EMBEDDING_DIMENSION
        )
        return response.text_embedding

    def synthesize_answer(self, query: str, search_results: list) -> str:
        if not search_results:
            return "No relevant clips found for your query."

        context_lines = []
        for r in search_results:
            source = r['_source']
            start_time = source['start_time_sec']
            end_time = source['end_time_sec']

            line = f"- From {start_time:.1f}s to {end_time:.1f}s:"
            context_lines.append(line)

            if source.get('labels'):
                context_lines.append(f"  - Scene contains: {', '.join(source['labels'])}")

            if source.get('objects'):
                object_descs = [o['description'] for o in source.get('objects', [])]
                unique_descs = sorted(list(set(object_descs)))
                context_lines.append(f"  - Objects detected: {', '.join(unique_descs)}")

            if source.get('ocr_text', '').strip():
                context_lines.append(f"  - Text seen: '{source['ocr_text'].strip()}'")

        context = "\n".join(context_lines)

        prompt = f"""You are an expert security analyst. Your task is to answer a user's query about a video based *only* on the provided data from relevant video clips. Follow these instructions carefully:

1.  **Analyze the Data**: Review the `Video Clips Data` section, which contains timestamped information about labels, objects, and text detected in the video.
2.  **Synthesize a Timeline**: Based on the data, construct a brief, factual timeline of events relevant to the user's query. Do not infer actions or intentions beyond what is explicitly described in the data.
3.  **Formulate Your Answer**: Based on your timeline, provide a clear and direct answer to the `User Query`.
4.  **Cite Your Evidence**: For every claim you make, you MUST cite the start and end time of the clip(s) that support it (e.g., "At 00:15-00:23, a person is seen...").
5.  **Be Concise**: Keep your answer focused and to the point. If the provided clips do not contain enough information to answer the query, state that clearly.

---

**User Query**: "{query}"

---

**Video Clips Data**:
{context}

---

**Your Analysis**:
(Begin your response here, following the instructions above)
"""

        response = self.gemini_model.generate_content(prompt)
        return response.text

vertex_ai_client = VertexAIClient()
