import json
import re
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from google.cloud import videointelligence_v1 as videointelligence
from vertexai.generative_models import GenerativeModel
import asyncio
from vertexai.vision_models import MultiModalEmbeddingModel, Video, VideoSegmentConfig
import vertexai
from config import settings
from google.cloud import storage
import tempfile
import os
from datetime import timedelta
from google.oauth2 import service_account

vertexai.init(project=settings.PROJECT_ID, location=settings.LOCATION)

class VideoProcessor:
    def __init__(self):
        key_path = Path(__file__).parent.parent / 'sentinel-key.json'
        creds = None
        if key_path.exists():
            creds = service_account.Credentials.from_service_account_file(str(key_path))

        self.video_intelligence_client = videointelligence.VideoIntelligenceServiceClient(credentials=creds)
        self.embedding_model = MultiModalEmbeddingModel.from_pretrained(settings.EMBEDDING_MODEL)

    def _upload_to_gcs_if_local(self, video_path):
        if str(video_path).startswith("gs://"):
            return video_path

        print(f"  📤 Uploading local video to GCS: {video_path}")
        key_path = Path(__file__).parent.parent / 'sentinel-key.json'
        creds = None
        if key_path.exists():
            creds = service_account.Credentials.from_service_account_file(str(key_path))

        storage_client = storage.Client(credentials=creds)
        bucket = storage_client.bucket(settings.GCS_BUCKET)

        blob_name = os.path.basename(video_path)
        blob = bucket.blob(blob_name)

        blob.upload_from_filename(video_path)

        gcs_uri = f"gs://{settings.GCS_BUCKET}/{blob_name}"
        print(f"  ✓ Uploaded to {gcs_uri}")
        return gcs_uri

    def _format_time_offset(self, offset_val):
        """
        Parses a time offset from the Video Intelligence API into the
        string format expected by the protobuf JSON parser.
        """
        if isinstance(offset_val, str):
            return offset_val
        if isinstance(offset_val, dict):
            seconds = offset_val.get('seconds', 0) or 0
            nanos = offset_val.get('nanos', 0) or 0
            return f"{seconds}.{nanos:09d}s"
        return "0s"

    def _fix_timestamps_recursively(self, data):
        """
        Recursively traverses a dictionary or list and applies the
        _format_time_offset fix to any `start_time_offset`, `end_time_offset`,
        or `time_offset` fields.
        """
        if isinstance(data, dict):
            for key, value in data.items():
                if key in ['start_time_offset', 'end_time_offset', 'time_offset']:
                    data[key] = self._format_time_offset(value)
                else:
                    self._fix_timestamps_recursively(value)
        elif isinstance(data, list):
            for item in data:
                self._fix_timestamps_recursively(item)
        return data

    async def analyze_video(self, video_uri):
        gcs_uri = self._upload_to_gcs_if_local(video_uri)
        features = [
            videointelligence.Feature.LABEL_DETECTION,
            videointelligence.Feature.TEXT_DETECTION,
            videointelligence.Feature.OBJECT_TRACKING
        ]

        # Define the output location in GCS for the results
        blob_name = os.path.basename(gcs_uri)
        output_blob_name = f"results/{blob_name}.json"
        output_uri = f"gs://{settings.GCS_BUCKET}/{output_blob_name}"

        operation = self.video_intelligence_client.annotate_video(
            request={
                "features": features,
                "input_uri": gcs_uri,
                "output_uri": output_uri
            }
        )

        print("Processing video with Video Intelligence API (async)...")
        print(f" -> Waiting for operation to complete. Results will be at {output_uri}")
        operation.result(timeout=900) # Wait for the operation to finish writing to GCS
        print(" <- Operation complete.")

        # Retrieve results from GCS
        key_path = Path(__file__).parent.parent / 'sentinel-key.json'
        creds = None
        if key_path.exists():
            creds = service_account.Credentials.from_service_account_file(str(key_path))
        storage_client = storage.Client(credentials=creds)
        bucket = storage_client.bucket(settings.GCS_BUCKET)

        blob = bucket.blob(output_blob_name)

        print(f"  📥 Downloading results from {output_uri}...")
        try:
            result_json_str = blob.download_as_string()
            print("  ✓ Download complete.")
        except Exception as e:
            print(f"  ❌ Failed to download results: {e}")
            raise

        # HACK: The Video Intelligence API returns inconsistent formats for timestamps
        # (sometimes a string, sometimes a dict, sometimes null/empty). We recursively
        # traverse the entire JSON response and normalize all timestamp fields into
        # the string format that the protobuf parser expects.
        result_data = json.loads(result_json_str)
        fixed_data = self._fix_timestamps_recursively(result_data)
        fixed_json_str = json.dumps(fixed_data)

        # Parse the JSON string into a protobuf message
        try:
            annotation_result = videointelligence.AnnotateVideoResponse.from_json(fixed_json_str)
        except Exception as e:
            print("--- DEBUG: Writing failing JSON to debug_json_output.json ---")
            with open('debug_json_output.json', 'w') as f:
                f.write(fixed_json_str)
            raise e

        # Clean up the results file from GCS
        try:
            print(f"  🗑️ Deleting results file from GCS: {output_blob_name}")
            blob.delete()
            print("  ✓ Deleted results file.")
        except Exception as e:
            print(f"  ⚠️ Could not delete results file: {e}")


        metadata = self._extract_metadata(annotation_result.annotation_results[0])

        # Generate the video summary
        summary = await self._generate_video_summary(metadata)

        return metadata, gcs_uri, summary

    def _extract_metadata(self, annotation_result):
        labels_by_time = {}
        ocr_by_time = {}
        objects_by_time = {}

        for label in annotation_result.segment_label_annotations:
            for segment in label.segments:
                start = int(segment.segment.start_time_offset.seconds)
                end = int(segment.segment.end_time_offset.seconds)

                for t in range(start, end + 1):
                    if t not in labels_by_time:
                        labels_by_time[t] = set()
                    labels_by_time[t].add(label.entity.description)

        for text_annotation in annotation_result.text_annotations:
            for segment in text_annotation.segments:
                start = int(segment.segment.start_time_offset.seconds)
                end = int(segment.segment.end_time_offset.seconds)

                for t in range(start, end + 1):
                    if t not in ocr_by_time:
                        ocr_by_time[t] = set()
                    ocr_by_time[t].add(text_annotation.text)

        for object_annotation in annotation_result.object_annotations:
            description = object_annotation.entity.description
            track_id = object_annotation.track_id

            for frame in object_annotation.frames:
                t = int(frame.time_offset.seconds)
                if t not in objects_by_time:
                    objects_by_time[t] = []

                objects_by_time[t].append({
                    'description': description,
                    'track_id': str(track_id)
                })

        return {
            'labels_by_time': {k: list(v) for k, v in labels_by_time.items()},
            'ocr_by_time': {k: ' '.join(v) for k, v in ocr_by_time.items()},
            'objects_by_time': objects_by_time
        }

    async def _generate_video_summary(self, metadata):
        """Generates a concise summary of the video from its metadata."""
        print("  📝 Generating video summary...")

        # Consolidate all unique labels and object descriptions
        all_labels = set()
        for labels in metadata['labels_by_time'].values():
            all_labels.update(labels)

        all_objects = set()
        for objects_at_time in metadata['objects_by_time'].values():
            for obj in objects_at_time:
                all_objects.add(obj['description'])

        # Combine and deduplicate
        combined_keywords = list(all_labels.union(all_objects))

        if not combined_keywords:
            print("  ⚠️ No keywords found to generate a summary.")
            return "No descriptive summary could be generated for this video."

        # Create the prompt for the LLM
        prompt = f"""Based on the following keywords and objects detected in a video, please generate a concise, 3-4 line narrative summary of what the video is likely about.
        Focus on the most significant or recurring themes.

        Keywords: {', '.join(combined_keywords)}

        Summary:"""

        try:
            gemini_model = GenerativeModel(settings.GEMINI_MODEL)
            response = await gemini_model.generate_content_async(prompt)
            summary = response.text.strip()
            print(f"  ✓ Summary generated successfully.")
            return summary
        except Exception as e:
            print(f"  ❌ Error generating video summary: {e}")
            return "Summary generation failed."
    
    def create_chunks(self, video_duration_sec):
        chunks = []
        step = settings.CHUNK_DURATION_SEC - settings.CHUNK_OVERLAP_SEC
        
        current = 0
        while current < video_duration_sec:
            end = min(current + settings.CHUNK_DURATION_SEC, video_duration_sec)
            chunks.append({
                'start': current,
                'end': end
            })
            current += step
            
            if end >= video_duration_sec:
                break
        
        return chunks
    
    def generate_embeddings(self, gcs_uri, chunks):
        embeddings = []
        video = Video.load_from_file(gcs_uri)

        for i, chunk in enumerate(chunks):
            print(f"  🔄 Generating embedding for chunk {i+1}/{len(chunks)} ({chunk['start']}-{chunk['end']}s)")

            config = VideoSegmentConfig(
                start_offset_sec=int(chunk['start']),
                end_offset_sec=int(chunk['end'])
            )

            try:
                print(f"    -> Calling get_embeddings API...")
                response = self.embedding_model.get_embeddings(
                    video=video,
                    video_segment_config=config,
                    dimension=settings.EMBEDDING_DIMENSION
                )
                print(f"    <- API call complete.")

                if response.video_embeddings:
                    embeddings.append({
                        'start': chunk['start'],
                        'end': chunk['end'],
                        'embedding': response.video_embeddings[0].embedding
                    })
                    print(f"    ✓ Generated embedding (dim: {len(response.video_embeddings[0].embedding)})")
                else:
                    print(f"    ⚠ No embeddings returned for chunk {chunk['start']}-{chunk['end']}s")
            except Exception as e:
                print(f"    ❌ Error generating embedding for chunk {chunk['start']}-{chunk['end']}s: {e}")

        return embeddings
    
    def create_documents(self, video_id, chunks, embeddings, metadata):
        documents = []

        # Map embeddings by chunk bounds for quick lookup
        embed_by_range = {
            (int(e['start']), int(e['end'])): e['embedding']
            for e in embeddings
        }

        for chunk in chunks:
            start = int(chunk['start'])
            end = int(chunk['end'])

            labels = set()
            ocr_texts = []
            objects = {}  # Using a dict to store unique objects by track_id

            for t in range(start, end + 1):
                if t in metadata['labels_by_time']:
                    labels.update(metadata['labels_by_time'][t])
                if t in metadata['ocr_by_time']:
                    ocr_texts.append(metadata['ocr_by_time'][t])
                if t in metadata['objects_by_time']:
                    for obj in metadata['objects_by_time'][t]:
                        if obj['track_id'] not in objects:
                            objects[obj['track_id']] = obj

            doc = {
                'video_id': video_id,
                'start_time_sec': float(chunk['start']),
                'end_time_sec': float(chunk['end']),
                'labels': list(labels),
                'ocr_text': ' '.join(list(dict.fromkeys(ocr_texts))),
                'objects': list(objects.values())
            }

            # Include embedding only if available for this chunk
            emb = embed_by_range.get((start, end))
            if emb is not None:
                doc['video_embedding'] = emb

            documents.append(doc)

        return documents

