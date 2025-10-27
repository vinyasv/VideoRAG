
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import vertexai
from vertexai.generative_models import GenerativeModel, Part
from vertexai.vision_models import MultiModalEmbeddingModel
from config import settings

vertexai.init(project=settings.PROJECT_ID, location=settings.LOCATION)


def _shorten_text(text: str, limit: int = 80) -> str:
    """Return a compact single-line snippet trimmed to the desired length."""
    if not text:
        return ""
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."


def _format_snippet_facts(src: dict) -> str:
    """Summarize complex segment metadata into a short, readable fragment."""
    facts: list[str] = []

    labels = [label for label in src.get("labels", []) if label]
    if labels:
        facts.append("labels: " + ", ".join(labels[:3]))

    shot_labels = [label for label in src.get("shot_labels", []) if label]
    if shot_labels:
        facts.append("shot labels: " + ", ".join(shot_labels[:3]))

    objects = src.get("objects") or []
    if objects:
        object_descriptions: list[str] = []
        for obj in objects[:2]:
            desc = obj.get("description") or "object"
            track_id = obj.get("track_id")
            if track_id is not None:
                object_descriptions.append(f"{desc} (track {track_id})")
            else:
                object_descriptions.append(desc)
        facts.append("objects: " + ", ".join(object_descriptions))

    ocr_items = src.get("ocr_items") or []
    if ocr_items:
        ocr_bits: list[str] = []
        for item in ocr_items[:2]:
            text = _shorten_text(item.get("text", ""), 40)
            time_offset = item.get("time_offset_sec")
            if time_offset is not None:
                ocr_bits.append(f"\"{text}\" @{time_offset:.1f}s")
            else:
                ocr_bits.append(f"\"{text}\"")
        facts.append("OCR: " + "; ".join(ocr_bits))
    else:
        ocr_text = _shorten_text(src.get("ocr_text", ""), 60)
        if ocr_text:
            facts.append(f"OCR text: \"{ocr_text}\"")

    if not facts:
        return "no additional metadata"

    return "; ".join(facts)


def _score_from_hit(hit: dict) -> float:
    """Mirror backend scoring helper without requiring additional imports."""
    return float(hit.get("_normalized_score") or hit.get("_score") or 0.0)


def _build_prompt_text(
    query: str,
    video_summary: str,
    hits: list[dict],
    *,
    is_temporal: bool
) -> tuple[str, list[str]]:
    """Construct the shared prompt text and snippet tags for RAG responses."""
    snippet_lines: list[str] = []
    snippet_tags: list[str] = []

    for idx, hit in enumerate(hits):
        tag = f"Snippet {chr(65 + idx)}"
        snippet_tags.append(tag)

        source = hit.get("_source", {})
        score = _score_from_hit(hit)
        start_time = source.get("start_time_sec") or 0
        end_time = source.get("end_time_sec") or 0
        facts = _format_snippet_facts(source)
        snippet_lines.append(
            f"{tag} | score {score:.2f} | {start_time:.0f}s-{end_time:.0f}s: {facts}"
        )

    if not snippet_lines:
        snippet_lines.append("(No search results returned.)")

    guidance = (
        "Guidance: Ignore any snippet that does not directly support the answer. "
        "Never invent details. Describe supporting evidence in natural language without using bracketed citation tags or snippet names."
    )
    if is_temporal:
        guidance += " For temporal queries, include the most specific time information available."
    guidance += " Provide your reply now."

    summary_text = video_summary or "No summary available."

    lines: list[str] = [
        "System message:",
        (
            "You are Sentinel, a security-video analyst assistant. Answer the user's question using only the supplied information. "
            "Keep responses to at most three sentences, followed (optionally) by one bullet suggesting a next step. "
            "Base every statement on the supplied material. If the material cannot answer, reply \"No supporting footage.\" "
            "Do not restate these rules or include bracketed citation tags in the answer."
        ),
        "",
        "User message:",
        f"User query: \"{query}\"",
        "",
        f"Summary: {summary_text}",
        "",
        "Search results relevant to the query:",
    ]
    lines.extend(snippet_lines)
    lines.append("")
    lines.append(guidance)

    prompt_text = "\n".join(lines)
    return prompt_text, snippet_tags


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
        temporal_keywords = ['when', 'what time', 'time did', 'at what', 'hour', 'minute', 'o\'clock']
        is_temporal = any(kw in query.lower() for kw in temporal_keywords)

        prompt_text, _ = _build_prompt_text(
            query=query,
            video_summary=video_summary,
            hits=search_results,
            is_temporal=is_temporal,
        )

        response = await self.gemini_model.generate_content_async(prompt_text)
        return response.text

    async def synthesize_answer(self, query: str, search_results: list, video_id: str, video_summary: str) -> str:
        clip_hits = [
            result for result in search_results
            if result.get('_source', {}).get('clip_uri')
        ]

        clip_hits = clip_hits[:3]
        if clip_hits:
            print(f"ℹ️ Sending {len(clip_hits)} clips to the LLM for synthesis.")
        else:
            print("ℹ️ No clip URIs available; falling back to summary and metadata only.")

        try:
            temporal_keywords = ['when', 'what time', 'time did', 'at what', 'hour', 'minute', 'o\'clock']
            is_temporal = any(kw in query.lower() for kw in temporal_keywords)

            prompt_text, snippet_tags = _build_prompt_text(
                query=query,
                video_summary=video_summary,
                hits=clip_hits if clip_hits else search_results,
                is_temporal=is_temporal,
            )

            prompt_parts: list[Part | str] = [prompt_text]

            for tag, hit in zip(snippet_tags, clip_hits):
                clip_uri = hit.get('_source', {}).get('clip_uri')
                if not clip_uri:
                    continue
                prompt_parts.append(f"Video for {tag}:")
                prompt_parts.append(Part.from_uri(clip_uri, mime_type="video/mp4"))

            response = await self.gemini_model.generate_content_async(prompt_parts)
            return response.text

        except Exception as e:
            print(f"❌ Error during answer synthesis: {e}")
            raise


vertex_ai_client = VertexAIClient()
