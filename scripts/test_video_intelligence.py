import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from google.cloud import videointelligence_v1 as videointelligence
from google.cloud import storage
from google.oauth2 import service_account
from config import settings
import json

def test_video_analysis(video_uri):
    """Test Video Intelligence API with a specific video URI."""
    print(f"Testing Video Intelligence API with: {video_uri}")

    # Initialize Video Intelligence client
    key_path = Path(__file__).parent.parent / 'sentinel-key.json'
    creds = None
    if key_path.exists():
        creds = service_account.Credentials.from_service_account_file(str(key_path))

    client = videointelligence.VideoIntelligenceServiceClient(credentials=creds)

    # Configure features to analyze
    features = [
        videointelligence.Feature.LABEL_DETECTION,
        videointelligence.Feature.TEXT_DETECTION,
        videointelligence.Feature.OBJECT_TRACKING
    ]

    # Set output URI
    output_blob_name = f"results/test_{Path(video_uri).name}.json"
    output_uri = f"gs://{settings.GCS_BUCKET}/{output_blob_name}"

    print(f"Results will be written to: {output_uri}")
    print(f"Starting Video Intelligence API analysis...")

    # Call the API
    operation = client.annotate_video(
        request={
            "features": features,
            "input_uri": video_uri,
            "output_uri": output_uri
        }
    )

    print("⏳ Waiting for analysis to complete (this may take 2-5 minutes)...")
    result = operation.result(timeout=900)
    print("✅ Analysis complete!")

    # Download and display results
    storage_client = storage.Client(credentials=creds)
    bucket = storage_client.bucket(settings.GCS_BUCKET)
    blob = bucket.blob(output_blob_name)

    result_json = json.loads(blob.download_as_string())

    # Extract some key info
    print("\n📊 Analysis Results:")
    print(f"Keys in result: {list(result_json.keys())}")

    if 'annotation_results' in result_json and len(result_json['annotation_results']) > 0:
        annotation = result_json['annotation_results'][0]
        print(f"Keys in annotation: {list(annotation.keys())}")

        # Labels - SHOW ALL
        if 'segment_label_annotations' in annotation:
            labels = [label['entity']['description'] for label in annotation['segment_label_annotations']]
            print(f"\n🏷️  ALL Labels ({len(labels)} total):")
            for i, label in enumerate(labels, 1):
                print(f"   {i}. {label}")

        # OCR Text - SHOW ALL
        if 'text_annotations' in annotation:
            print(f"\n📝 OCR Text ({len(annotation['text_annotations'])} total):")
            for i, text in enumerate(annotation['text_annotations'][:10], 1):
                print(f"   {i}. {text['text'][:100]}")

        # Objects - SHOW ALL UNIQUE
        if 'object_annotations' in annotation:
            objects = list(set([obj['entity']['description'] for obj in annotation['object_annotations']]))
            print(f"\n🎯 Detected Objects ({len(objects)} unique):")
            for i, obj in enumerate(objects, 1):
                print(f"   {i}. {obj}")
    else:
        print("⚠️  No annotation results found!")
        print(f"Raw result: {json.dumps(result_json, indent=2)[:500]}")

    # Clean up
    blob.delete()
    print(f"\n🗑️  Cleaned up results file from GCS")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--video-uri', required=True, help='GCS URI of video to analyze')
    args = parser.parse_args()

    test_video_analysis(args.video_uri)
