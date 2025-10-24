import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from google.cloud import storage
from google.oauth2 import service_account
from config import settings
import tempfile
import os
from datetime import timedelta

class GCSClient:
    def __init__(self):
        # Try to use service account key if available
        key_path = Path(__file__).parent.parent / 'sentinel-key.json'
        if key_path.exists():
            credentials = service_account.Credentials.from_service_account_file(str(key_path))
            self.client = storage.Client(project=settings.PROJECT_ID, credentials=credentials)
        else:
            self.client = storage.Client(project=settings.PROJECT_ID)
        
        self.bucket_name = settings.GCS_BUCKET
        self.bucket = self._get_or_create_bucket()
    
    def _get_or_create_bucket(self):
        try:
            bucket = self.client.get_bucket(self.bucket_name)
        except Exception:
            bucket = self.client.create_bucket(
                self.bucket_name,
                location=settings.LOCATION
            )
        return bucket
    
    def upload_video(self, file_data, video_id: str, filename: str = None, is_path: bool = False) -> str:
        if is_path:
            ext = os.path.splitext(file_data.name)[1] or '.mp4'
            blob_name = f"{video_id}{ext}"
            blob = self.bucket.blob(blob_name)
            blob.upload_from_filename(str(file_data))
        else:
            ext = os.path.splitext(filename)[1] or '.mp4'
            blob_name = f"{video_id}{ext}"
            blob = self.bucket.blob(blob_name)
            blob.upload_from_string(file_data, content_type='video/mp4')

        gcs_uri = f"gs://{self.bucket_name}/{blob_name}"
        return gcs_uri

    def download_video(self, gcs_uri: str, destination_path: str):
        """Downloads a video from GCS to a local path."""
        blob_name = gcs_uri.replace(f"gs://{self.bucket_name}/", "")
        blob = self.bucket.blob(blob_name)
        blob.download_to_filename(destination_path)

    
    def get_video_uri(self, video_id: str) -> str:
        if not video_id.endswith('.mp4'):
            video_id = f"{video_id}.mp4"
        return f"gs://{self.bucket_name}/{video_id}"
    
    def get_signed_url(self, video_id: str, expiration_hours: int = 24) -> str:
        blob_name = f"{video_id}.mp4"
        blob = self.bucket.blob(blob_name)

        url = blob.generate_signed_url(
            expiration=timedelta(hours=expiration_hours),
            method='GET'
        )
        return url
    
    def get_public_url(self, video_id: str) -> str:
        blob_name = f"{video_id}.mp4"
        blob = self.bucket.blob(blob_name)
        return blob.public_url

    def delete_video(self, gcs_uri: str):
        """Deletes a video from GCS."""
        try:
            blob_name = gcs_uri.replace(f"gs://{self.bucket_name}/", "")
            blob = self.bucket.blob(blob_name)
            blob.delete()
            print(f"Deleted temporary clip: {gcs_uri}")
        except Exception as e:
            print(f"Could not delete temporary clip {gcs_uri}: {e}")

gcs_client = GCSClient()