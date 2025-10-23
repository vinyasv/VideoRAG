# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commonly Used Commands

- **Installation:** `pip install -r requirements.txt`
- **Setup:**
    - `cp env.example .env` (and fill in the details for GCP and Elasticsearch)
    - `python scripts/create_index.py` to set up the Elasticsearch index.
- **Ingestion:** `python -m ingestion.ingest --video-path data/demo.mp4` to process a video and add it to the search index.
- **Running the backend:** `uvicorn backend.main:app --reload`
- **Accessing the frontend:** Open `frontend/index.html` in a browser.

## High-level Code Architecture

This project, named "Sentinel," is an AI-powered security video analysis tool. It converts CCTV footage into a searchable, conversational database.

- **Frontend (`frontend/`)**: A vanilla HTML/JS single-page application that provides a chat interface and video player. It sends user queries to the backend and displays the results.

- **Backend (`backend/`)**: A Python-based API built with FastAPI. Its primary role is to handle user queries from the frontend. It performs a hybrid search (semantic vector search + keyword filtering) on an Elasticsearch index. The search results are then passed to Google's Gemini 2.0 Flash model to generate a natural language answer.

- **Ingestion (`ingestion/`)**: This is the data processing pipeline that prepares videos for searching. It uses Google's Video Intelligence API to extract metadata like labels, OCR text, and object tracking. The video is then divided into 8-second chunks (with a 4-second overlap), and a 1408-dimension multimodal embedding is generated for each chunk using Vertex AI. These chunks, along with their metadata, are then indexed in Elasticsearch.

- **Scripts (`scripts/`)**: This directory contains utility scripts, most importantly `create_index.py`, which sets up the Elasticsearch index with the correct schema for storing video segments.

- **Configuration (`config.py` and `.env`)**: The application's configuration, including API keys and service endpoints, is managed through `config.py`, which loads values from a `.env` file.
