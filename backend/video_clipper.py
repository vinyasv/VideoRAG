
import asyncio
import tempfile
import os
from pathlib import Path
from backend.gcs_client import gcs_client
import uuid

async def create_clips_from_timestamps(video_uri: str, timestamps: list[dict]) -> list[str]:
    """
    Extracts clips from a video file based on timestamps using FFmpeg.
    Downloads the source video, creates clips locally, and uploads them back to GCS.
    """
    clipped_video_uris = []

    with tempfile.TemporaryDirectory() as temp_dir:
        base_name = video_uri.split('/')[-1]
        local_video_path = Path(temp_dir) / base_name

        # 1. Download the source video from GCS
        print(f"Downloading source video: {video_uri}")
        await asyncio.to_thread(gcs_client.download_video, video_uri, str(local_video_path))
        print(f"Downloaded to {local_video_path}")

        # 2. Create clips for each timestamp
        tasks = []
        for i, ts in enumerate(timestamps):
            start = ts['start_time_sec']
            end = ts['end_time_sec']
            duration = end - start

            # Use a unique name for each clip
            clip_filename = f"{uuid.uuid4()}.mp4"
            output_path = Path(temp_dir) / clip_filename

            tasks.append(
                _run_ffmpeg_clip_command(local_video_path, output_path, start, duration, i)
            )

        results = await asyncio.gather(*tasks)

        # 3. Upload successful clips to GCS
        upload_tasks = []
        for local_clip_path in results:
            if local_clip_path:
                upload_tasks.append(
                    asyncio.to_thread(
                        gcs_client.upload_video,
                        local_clip_path,
                        f"clips/{local_clip_path.name}",
                        is_path=True
                    )
                )

        clipped_video_uris = await asyncio.gather(*upload_tasks)

    return clipped_video_uris

async def _run_ffmpeg_clip_command(source_path, output_path, start, duration, idx):
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

    print(f"  [{idx+1}] Running ffmpeg: {' '.join(ffmpeg_command)}")

    process = await asyncio.create_subprocess_exec(
        *ffmpeg_command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await process.communicate()

    if process.returncode == 0:
        print(f"  ✓ [{idx+1}] Successfully created clip: {output_path}")
        return output_path
    else:
        print(f"  ❌ [{idx+1}] Failed to create clip.")
        print(f"    STDOUT: {stdout.decode()}")
        print(f"    STDERR: {stderr.decode()}")
        return None
