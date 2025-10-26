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
import uuid

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

        # Initialize GCS client
        key_path = Path(__file__).parent.parent / 'sentinel-key.json'
        creds = None
        if key_path.exists():
            creds = service_account.Credentials.from_service_account_file(str(key_path))
        storage_client = storage.Client(credentials=creds)
        bucket = storage_client.bucket(settings.GCS_BUCKET)

        # --- FIX: Delete stale results from GCS before analysis ---
        print(f"  🧹 Checking for and deleting stale results at {output_uri}...")
        stale_blob = bucket.blob(output_blob_name)
        if stale_blob.exists():
            stale_blob.delete()
            print(f"  ✓ Deleted stale results file.")
        else:
            print(f"  ✓ No stale results found.")
        # --- END FIX ---

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
        shot_labels_by_time = {}
        ocr_by_time = {}
        ocr_items = []
        objects_by_time = {}
        all_objects = []

        # Extract segment labels (video-level)
        for label in annotation_result.segment_label_annotations:
            for segment in label.segments:
                start = int(segment.segment.start_time_offset.seconds)
                end = int(segment.segment.end_time_offset.seconds)

                for t in range(start, end + 1):
                    if t not in labels_by_time:
                        labels_by_time[t] = set()
                    labels_by_time[t].add(label.entity.description)

        # Extract shot labels (scene-level) - NEW
        for label in annotation_result.shot_label_annotations:
            for segment in label.segments:
                start = int(segment.segment.start_time_offset.seconds)
                end = int(segment.segment.end_time_offset.seconds)

                for t in range(start, end + 1):
                    if t not in shot_labels_by_time:
                        shot_labels_by_time[t] = set()
                    shot_labels_by_time[t].add(label.entity.description)

        # Extract OCR text with spatial data - ENHANCED
        for text_annotation in annotation_result.text_annotations:
            for segment in text_annotation.segments:
                start = int(segment.segment.start_time_offset.seconds)
                end = int(segment.segment.end_time_offset.seconds)

                # Store for simple text search (backward compat)
                for t in range(start, end + 1):
                    if t not in ocr_by_time:
                        ocr_by_time[t] = set()
                    ocr_by_time[t].add(text_annotation.text)

                # Store detailed OCR items with bounding boxes - NEW
                for frame in segment.frames:
                    # Handle both timedelta and protobuf Duration
                    time_offset = frame.time_offset
                    if hasattr(time_offset, 'total_seconds'):
                        time_offset_sec = time_offset.total_seconds()
                    elif hasattr(time_offset, 'seconds'):
                        time_offset_sec = time_offset.seconds + (getattr(time_offset, 'nanos', 0) / 1e9)
                    else:
                        time_offset_sec = 0.0

                    # Extract bounding box vertices
                    vertices = []
                    if hasattr(frame, 'rotated_bounding_box') and frame.rotated_bounding_box:
                        for vertex in frame.rotated_bounding_box.vertices:
                            vertices.append({'x': vertex.x, 'y': vertex.y})

                    ocr_items.append({
                        'text': text_annotation.text,
                        'confidence': segment.confidence,
                        'time_offset_sec': time_offset_sec,
                        'bounding_box': {'vertices': vertices} if vertices else None
                    })

        # Extract objects with full frame-level tracking - ENHANCED
        for object_annotation in annotation_result.object_annotations:
            description = object_annotation.entity.description
            confidence = object_annotation.confidence

            # Extract segment timing
            start_offset = object_annotation.segment.start_time_offset
            end_offset = object_annotation.segment.end_time_offset

            if hasattr(start_offset, 'total_seconds'):
                segment_start = start_offset.total_seconds()
            elif hasattr(start_offset, 'seconds'):
                segment_start = start_offset.seconds + (getattr(start_offset, 'nanos', 0) / 1e9)
            else:
                segment_start = 0.0

            if hasattr(end_offset, 'total_seconds'):
                segment_end = end_offset.total_seconds()
            elif hasattr(end_offset, 'seconds'):
                segment_end = end_offset.seconds + (getattr(end_offset, 'nanos', 0) / 1e9)
            else:
                segment_end = 0.0

            # Extract all frame-level bounding boxes
            frames_data = []
            for frame in object_annotation.frames:
                time_offset = frame.time_offset
                if hasattr(time_offset, 'total_seconds'):
                    time_offset_sec = time_offset.total_seconds()
                elif hasattr(time_offset, 'seconds'):
                    time_offset_sec = time_offset.seconds + (getattr(time_offset, 'nanos', 0) / 1e9)
                else:
                    time_offset_sec = 0.0

                bbox = None
                if hasattr(frame, 'normalized_bounding_box') and frame.normalized_bounding_box:
                    bbox = {
                        'left': frame.normalized_bounding_box.left,
                        'top': frame.normalized_bounding_box.top,
                        'right': frame.normalized_bounding_box.right,
                        'bottom': frame.normalized_bounding_box.bottom
                    }

                frames_data.append({
                    'time_offset_sec': time_offset_sec,
                    'bounding_box': bbox
                })

                # Also store in objects_by_time for chunk aggregation
                t = int(time_offset_sec)
                if t not in objects_by_time:
                    objects_by_time[t] = []
                objects_by_time[t].append({
                    'description': description,
                    'track_id': str(getattr(object_annotation, 'track_id', 'unknown')),
                    'confidence': confidence,
                    'frames': frames_data
                })

            # Store complete object with all frames - NEW
            all_objects.append({
                'description': description,
                'track_id': str(getattr(object_annotation, 'track_id', 'unknown')),
                'confidence': confidence,
                'segment_start_sec': segment_start,
                'segment_end_sec': segment_end,
                'frames': frames_data
            })

        return {
            'labels_by_time': {k: list(v) for k, v in labels_by_time.items()},
            'shot_labels_by_time': {k: list(v) for k, v in shot_labels_by_time.items()},
            'ocr_by_time': {k: ' '.join(v) for k, v in ocr_by_time.items()},
            'ocr_items': ocr_items,
            'objects_by_time': objects_by_time,
            'all_objects': all_objects
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

    async def create_clip_files(self, gcs_uri, chunks, video_id):
        """
        Creates physical video clips for each chunk and uploads them to GCS.
        Returns a list of clip URIs in the same order as chunks.
        """
        import subprocess

        clip_uris = []

        with tempfile.TemporaryDirectory() as temp_dir:
            # Download source video
            base_name = gcs_uri.split('/')[-1]
            local_video_path = Path(temp_dir) / base_name

            print(f"  📥 Downloading source video from {gcs_uri}...")
            key_path = Path(__file__).parent.parent / 'sentinel-key.json'
            creds = None
            if key_path.exists():
                creds = service_account.Credentials.from_service_account_file(str(key_path))

            storage_client = storage.Client(credentials=creds)
            bucket = storage_client.bucket(settings.GCS_BUCKET)
            blob_name = gcs_uri.replace(f"gs://{settings.GCS_BUCKET}/", "")
            blob = bucket.blob(blob_name)
            blob.download_to_filename(str(local_video_path))
            print(f"  ✓ Downloaded to {local_video_path}")

            # Create clips for each chunk
            tasks = []
            for i, chunk in enumerate(chunks):
                start = chunk['start']
                end = chunk['end']
                duration = end - start

                # Create clip filename
                clip_filename = f"{video_id}_chunk_{i}.mp4"
                output_path = Path(temp_dir) / clip_filename

                tasks.append(
                    self._create_clip_async(
                        local_video_path, output_path, start, duration, i
                    )
                )

            # Run FFmpeg commands in parallel
            results = await asyncio.gather(*tasks)

            # Upload successful clips to GCS
            print(f"  📤 Uploading {len([r for r in results if r])} clips to GCS...")
            for i, local_clip_path in enumerate(results):
                if local_clip_path:
                    clip_blob_name = f"clips/{local_clip_path.name}"
                    clip_blob = bucket.blob(clip_blob_name)

                    max_retries = 3
                    uploaded = False
                    for attempt in range(max_retries):
                        try:
                            clip_blob.upload_from_filename(str(local_clip_path))
                            clip_uri = f"gs://{settings.GCS_BUCKET}/{clip_blob_name}"
                            clip_uris.append(clip_uri)
                            if (i + 1) % 50 == 0:
                                print(f"    ✓ Uploaded {i + 1}/{len(results)} clips")
                            uploaded = True
                            break  # Success
                        except Exception as e:
                            if attempt < max_retries - 1:
                                print(f"    ⚠️ Connection error on clip {i+1}, retrying in 5s... ({attempt + 1}/{max_retries})")
                                await asyncio.sleep(5)
                            else:
                                print(f"    ❌ Failed to upload clip {i+1} after {max_retries} attempts: {e}")

                    if not uploaded:
                        clip_uris.append(None)

                else:
                    # If clip creation failed, add None
                    clip_uris.append(None)

            print(f"  ✓ Uploaded all clips to GCS")

        return clip_uris

    async def _create_clip_async(self, source_path, output_path, start, duration, idx):
        """Helper to run a single ffmpeg command."""
        ffmpeg_command = [
            'ffmpeg',
            '-ss', str(start),
            '-i', str(source_path),
            '-t', str(duration),
            '-c', 'copy',  # Use stream copy for speed
            '-y',
            str(output_path)
        ]

        if (idx + 1) % 10 == 0:
            print(f"  [{idx+1}] Creating clip {start}s-{start+duration}s...")

        process = await asyncio.create_subprocess_exec(
            *ffmpeg_command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )

        stdout, stderr = await process.communicate()

        if process.returncode == 0:
            return output_path
        else:
            print(f"  ❌ [{idx+1}] Failed to create clip.")
            print(f"    STDERR: {stderr.decode()}")
            return None

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
    
    def create_documents(self, video_id, chunks, embeddings, metadata, clip_uris=None):
        documents = []

        # Map embeddings by chunk bounds for quick lookup
        embed_by_range = {
            (int(e['start']), int(e['end'])): e['embedding']
            for e in embeddings
        }

        for i, chunk in enumerate(chunks):
            start = int(chunk['start'])
            end = int(chunk['end'])

            labels = set()
            shot_labels = set()
            ocr_texts = []
            objects_in_chunk = []
            ocr_items_in_chunk = []

            # Aggregate labels and shot labels
            for t in range(start, end + 1):
                if t in metadata['labels_by_time']:
                    labels.update(metadata['labels_by_time'][t])
                if t in metadata.get('shot_labels_by_time', {}):
                    shot_labels.update(metadata['shot_labels_by_time'][t])
                if t in metadata['ocr_by_time']:
                    ocr_texts.append(metadata['ocr_by_time'][t])

            # Collect ALL objects that appear in this chunk (no deduplication)
            # We'll store complete object data with all frames
            seen_objects = set()  # Track (description, track_id) to avoid exact duplicates
            for obj in metadata.get('all_objects', []):
                # Check if this object's frames overlap with this chunk
                obj_appears_in_chunk = False
                frames_in_chunk = []

                for frame in obj['frames']:
                    frame_time = frame['time_offset_sec']
                    if start <= frame_time <= end:
                        obj_appears_in_chunk = True
                        frames_in_chunk.append(frame)

                if obj_appears_in_chunk:
                    obj_key = (obj['description'], obj['track_id'])
                    if obj_key not in seen_objects:
                        seen_objects.add(obj_key)
                        objects_in_chunk.append({
                            'description': obj['description'],
                            'track_id': obj['track_id'],
                            'confidence': obj['confidence'],
                            'segment_start_sec': obj['segment_start_sec'],
                            'segment_end_sec': obj['segment_end_sec'],
                            'frames': frames_in_chunk  # Only frames within this chunk
                        })

            # Collect OCR items that appear in this chunk
            for ocr_item in metadata.get('ocr_items', []):
                if start <= ocr_item['time_offset_sec'] <= end:
                    ocr_items_in_chunk.append(ocr_item)

            doc = {
                'video_id': video_id,
                'start_time_sec': float(chunk['start']),
                'end_time_sec': float(chunk['end']),
                'labels': list(labels),
                'shot_labels': list(shot_labels),
                'ocr_text': ' '.join(list(dict.fromkeys(ocr_texts))),
                'ocr_items': ocr_items_in_chunk,
                'objects': objects_in_chunk
            }

            # Include embedding only if available for this chunk
            emb = embed_by_range.get((start, end))
            if emb is not None:
                doc['video_embedding'] = emb

            # Include clip URI if available
            if clip_uris and i < len(clip_uris) and clip_uris[i]:
                doc['clip_uri'] = clip_uris[i]

            documents.append(doc)

        return documents

