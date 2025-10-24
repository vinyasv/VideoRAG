#!/bin/bash

# Sentinel Deployment Script for Google Cloud Run
# Usage: ./deploy.sh

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== Sentinel Deployment Script ===${NC}"

# Load environment variables from .env
if [ ! -f .env ]; then
    echo -e "${RED}Error: .env file not found!${NC}"
    echo "Please copy env.example to .env and fill in your configuration."
    exit 1
fi

# Source the .env file
export $(cat .env | grep -v '^#' | xargs)

# Validate required environment variables
if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}Error: PROJECT_ID not set in .env${NC}"
    exit 1
fi

# Configuration
SERVICE_NAME="sentinel-api"
REGION="${LOCATION:-us-central1}"
IMAGE_NAME="${REGION}-docker.pkg.dev/${PROJECT_ID}/${SERVICE_NAME}/${SERVICE_NAME}"

echo -e "${YELLOW}Configuration:${NC}"
echo "  Project ID: $PROJECT_ID"
echo "  Service Name: $SERVICE_NAME"
echo "  Region: $REGION"
echo "  Image: $IMAGE_NAME"
echo ""

# Confirm deployment
read -p "Deploy to Google Cloud Run? (y/n) " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}Deployment cancelled.${NC}"
    exit 0
fi

# Set the active project
echo -e "${GREEN}Setting active GCP project...${NC}"
gcloud config set project $PROJECT_ID

# Enable required APIs
echo -e "${GREEN}Enabling required Google Cloud APIs...${NC}"
gcloud services enable \
    run.googleapis.com \
    containerregistry.googleapis.com \
    cloudbuild.googleapis.com \
    aiplatform.googleapis.com \
    videointelligence.googleapis.com \
    storage-api.googleapis.com

# Build the container image
echo -e "${GREEN}Building container image...${NC}"
gcloud builds submit --tag $IMAGE_NAME

# Deploy to Cloud Run
echo -e "${GREEN}Deploying to Cloud Run...${NC}"
gcloud run deploy $SERVICE_NAME \
    --image $IMAGE_NAME \
    --platform managed \
    --region $REGION \
    --allow-unauthenticated \
    --memory 2Gi \
    --cpu 2 \
    --timeout 300 \
    --max-instances 10 \
    --set-env-vars "PROJECT_ID=${PROJECT_ID},LOCATION=${LOCATION},GCS_BUCKET=${GCS_BUCKET},ELASTICSEARCH_ENDPOINT=${ELASTICSEARCH_ENDPOINT},ELASTICSEARCH_API_KEY=${ELASTICSEARCH_API_KEY},VIDEO_INDEX_NAME=${VIDEO_INDEX_NAME},EMBEDDING_MODEL=${EMBEDDING_MODEL},EMBEDDING_DIMENSION=${EMBEDDING_DIMENSION},CHUNK_DURATION_SEC=${CHUNK_DURATION_SEC},CHUNK_OVERLAP_SEC=${CHUNK_OVERLAP_SEC},GEMINI_MODEL=${GEMINI_MODEL}"

# Get the service URL
SERVICE_URL=$(gcloud run services describe $SERVICE_NAME --region $REGION --format 'value(status.url)')

echo ""
echo -e "${GREEN}=== Deployment Complete! ===${NC}"
echo -e "${GREEN}Service URL: ${SERVICE_URL}${NC}"
echo -e "${GREEN}Frontend: ${SERVICE_URL}/app${NC}"
echo -e "${GREEN}API Docs: ${SERVICE_URL}/docs${NC}"
echo ""
echo -e "${YELLOW}Note: Make sure your Elasticsearch instance is accessible from Cloud Run${NC}"
