# Sentinel - Deployment Guide

This guide walks you through deploying Sentinel to Google Cloud Run.

## Prerequisites

1. **Google Cloud Account** with billing enabled
2. **gcloud CLI** installed and configured ([Install Guide](https://cloud.google.com/sdk/docs/install))
3. **Elasticsearch Instance** (Elastic Cloud recommended)
4. **Environment Variables** configured in `.env`

## Quick Deployment

### 1. Configure Environment

Copy the example environment file and fill in your values:

```bash
cp env.example .env
```

Edit `.env` with your configuration:
- `PROJECT_ID`: Your Google Cloud project ID
- `LOCATION`: GCP region (default: us-central1)
- `GCS_BUCKET`: Google Cloud Storage bucket name for videos
- `ELASTICSEARCH_ENDPOINT`: Your Elasticsearch cluster endpoint
- `ELASTICSEARCH_API_KEY`: Elasticsearch API key

### 2. Authenticate with Google Cloud

```bash
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
```

### 3. Deploy to Cloud Run

Run the deployment script:

```bash
./deploy.sh
```

The script will:
- Enable required Google Cloud APIs
- Build the container image using Cloud Build
- Deploy to Cloud Run with appropriate configuration
- Output the service URL

### 4. Access Your Application

After deployment completes, you'll receive a URL like:
```
https://sentinel-api-xxxxx-uc.a.run.app
```

- **Frontend**: `https://sentinel-api-xxxxx-uc.a.run.app/app`
- **API Docs**: `https://sentinel-api-xxxxx-uc.a.run.app/docs`
- **Health Check**: `https://sentinel-api-xxxxx-uc.a.run.app/`

## Manual Deployment

If you prefer manual deployment:

### 1. Build the container

```bash
export PROJECT_ID=your-project-id
export SERVICE_NAME=sentinel-api
export IMAGE_NAME=gcr.io/${PROJECT_ID}/${SERVICE_NAME}

gcloud builds submit --tag $IMAGE_NAME
```

### 2. Deploy to Cloud Run

```bash
gcloud run deploy $SERVICE_NAME \
    --image $IMAGE_NAME \
    --platform managed \
    --region us-central1 \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 2 \
    --timeout 300 \
    --set-env-vars "PROJECT_ID=${PROJECT_ID},..." \
    # Add all environment variables from .env
```

## Initial Setup

After deployment, you need to set up the Elasticsearch index and ingest videos.

### 1. Create the Elasticsearch Index

Run locally (requires access to your Elasticsearch instance):

```bash
python scripts/create_index.py
```

### 2. Ingest Video Content

Process and index your video files:

```bash
# Upload video to GCS bucket first
gsutil cp your-video.mp4 gs://your-bucket/

# Run ingestion (locally or in Cloud Run)
python -m ingestion.ingest --video-path gs://your-bucket/your-video.mp4
```

## Configuration

### Environment Variables

All configuration is managed through environment variables:

| Variable | Description | Required | Default |
|----------|-------------|----------|---------|
| `PROJECT_ID` | Google Cloud project ID | Yes | - |
| `LOCATION` | GCP region | No | us-central1 |
| `GCS_BUCKET` | GCS bucket for videos | Yes | - |
| `ELASTICSEARCH_ENDPOINT` | Elasticsearch cluster URL | Yes | - |
| `ELASTICSEARCH_API_KEY` | Elasticsearch API key | Yes | - |
| `VIDEO_INDEX_NAME` | Elasticsearch index name | No | sentinel-video-segments |
| `EMBEDDING_MODEL` | Vertex AI embedding model | No | multimodalembedding@001 |
| `GEMINI_MODEL` | Gemini model for responses | No | gemini-2.0-flash |

### Cloud Run Settings

The deployment uses these Cloud Run configurations:

- **Memory**: 2GB (adjust based on video processing needs)
- **CPU**: 2 vCPUs
- **Timeout**: 300 seconds (5 minutes)
- **Max Instances**: 10 (prevents excessive scaling costs)
- **Authentication**: Public (unauthenticated access allowed)

To adjust these, edit `deploy.sh` or use `gcloud run services update`.

## Monitoring & Logs

### View Logs

```bash
gcloud run services logs read sentinel-api --region us-central1 --limit 100
```

### Monitor Performance

Visit the Cloud Run dashboard:
```
https://console.cloud.google.com/run
```

## Security Considerations

### Production Deployment

For production use, consider:

1. **Enable Authentication**: Remove `--allow-unauthenticated` and use IAM or Identity Platform
2. **Restrict CORS**: Update `backend/main.py` to limit allowed origins
3. **API Keys**: Use Secret Manager instead of environment variables
4. **Network Security**: Configure VPC connector for private Elasticsearch access
5. **Rate Limiting**: Implement rate limiting to prevent abuse

### Using Secret Manager

Store sensitive values in Secret Manager:

```bash
# Store Elasticsearch API key
echo -n "your-api-key" | gcloud secrets create elasticsearch-api-key --data-file=-

# Grant Cloud Run access
gcloud secrets add-iam-policy-binding elasticsearch-api-key \
    --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"

# Update deployment to use secret
gcloud run services update sentinel-api \
    --update-secrets ELASTICSEARCH_API_KEY=elasticsearch-api-key:latest
```

## Troubleshooting

### Container Fails to Build

- Check that all dependencies in `requirements.txt` are valid
- Ensure Docker has enough resources allocated
- Review Cloud Build logs: `gcloud builds list`

### Service Fails to Start

- Check environment variables are set correctly
- Review logs: `gcloud run services logs read sentinel-api`
- Verify Elasticsearch is accessible from Cloud Run
- Check that GCS bucket exists and service account has access

### Elasticsearch Connection Issues

If your Elasticsearch instance is not publicly accessible:
1. Set up a VPC connector
2. Configure Cloud Run to use the VPC connector
3. Ensure firewall rules allow traffic

```bash
# Create VPC connector
gcloud compute networks vpc-access connectors create sentinel-connector \
    --region=us-central1 \
    --range=10.8.0.0/28

# Update Cloud Run to use connector
gcloud run services update sentinel-api \
    --vpc-connector=sentinel-connector \
    --vpc-egress=private-ranges-only
```

### Video Processing Timeout

If video processing times out:
- Increase Cloud Run timeout: `--timeout 900` (15 minutes max)
- Process videos in smaller chunks
- Consider using Cloud Functions or Cloud Batch for long-running ingestion

## Cost Optimization

### Estimated Costs

Cloud Run pricing is based on:
- **CPU/Memory**: Only charged when handling requests
- **Request Count**: $0.40 per million requests
- **Networking**: Egress charges apply

Typical costs for moderate usage (~1000 requests/day):
- Cloud Run: ~$10-20/month
- Vertex AI (embeddings): ~$5-15/month (based on video duration)
- Cloud Storage: ~$1-5/month
- Elasticsearch: Varies by plan (Elastic Cloud starts at ~$100/month)

### Cost Reduction Tips

1. **Reduce Max Instances**: Lower `--max-instances` to prevent scaling costs
2. **Optimize Video Chunks**: Larger chunks = fewer embeddings = lower Vertex AI costs
3. **Cache Results**: Implement caching for frequently accessed data
4. **Use Committed Use Discounts**: For predictable workloads

## Updating the Deployment

To update the deployed service:

```bash
# Make your code changes, then redeploy
./deploy.sh
```

Or for a specific update:

```bash
# Just update environment variables
gcloud run services update sentinel-api \
    --update-env-vars KEY=VALUE

# Update image only
gcloud builds submit --tag gcr.io/${PROJECT_ID}/sentinel-api
gcloud run services update sentinel-api --image gcr.io/${PROJECT_ID}/sentinel-api
```

## Rollback

If a deployment causes issues:

```bash
# List revisions
gcloud run revisions list --service sentinel-api

# Rollback to previous revision
gcloud run services update-traffic sentinel-api \
    --to-revisions REVISION_NAME=100
```

## Support

For issues or questions:
- Check logs: `gcloud run services logs read sentinel-api`
- Review [Cloud Run documentation](https://cloud.google.com/run/docs)
- Submit an issue on GitHub
