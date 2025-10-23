
### **Product Requirements Document: "Sentinel"**

| **Document:** | PRD: "Sentinel" - AI Physical Security Analyst |
| :--- | :--- |
| **Status:** | Draft |
| **Author:** | AI Accelerate Hackathon Team |
| **Date:** | October 22, 2025 |

### 1. Overview

**Sentinel** is an AI-powered physical security analyst that transforms high-volume, long-form CCTV footage from a passive "write-only" medium into a fully interactive, searchable, and conversational database. By combining Google Cloud's AI for video analysis and Elastic's hybrid search, Sentinel empowers security operators to find critical events in seconds, not hours, using only natural language.

### 2. The Problem

Security Operations Center (SOC) operators are responsible for monitoring hours of daily footage from dozens or hundreds of cameras. This process is:

* **Manual:** Finding a 5-second event (e.g., "a person in a red shirt entering a restricted area") requires manually "scrubbing" through hours of footage.
* **Reactive:** Investigations *start* after an incident is reported, not as it's happening.
* **Inefficient:** Valuable data (subtle suspicious behaviors, near-misses) is lost because it's impossible to review everything.
* **Not Searchable:** Footage is stored as opaque video files. You can't "Ctrl+F" a video.

### 3. The Solution

Sentinel ingests this long-form footage and runs it through a two-stage AI enrichment pipeline.

1.  **Stage 1: Event Analysis (Google Vertex AI Video Intelligence):** The system first analyzes the entire video to create a manifest of all "ground-truth" events, objects, and text (e.g., `{"label": "person", "start_time": 5.2s, "end_time": 9.8s}`).
2.  **Stage 2: Vectorization (Google Vertex AI Multimodal Embeddings):** The system breaks the video into small, overlapping chunks and generates a "video embedding" (a vector) for each one, capturing the *action and content* of that chunk.

This rich, multi-modal data (vectors, labels, timestamps) is stored in a single **Elasticsearch** index.

A **Gemini-powered agent** then provides a simple chat interface, allowing operators to ask questions. The agent performs a hybrid search (vector + keyword) in Elastic to find the *exact* video segments that answer the query and presents them as timestamped, playable clips.

### 4. Target Persona

* **Alex, the SOC Operator:** Alex is responsible for real-time monitoring and post-incident investigation at a data center. When an alert fires (e.g., "unauthorized door open"), Alex's manager asks, "Show me everyone who was near that door 10 minutes before the alarm." Today, this takes 45 minutes. With Sentinel, it should take 10 seconds.

### 5. Key Features (User Stories)

#### **EPIC 1: The Ingestion & Enrichment Pipeline (System Requirement)**

* **SYS-101:** As the system, I must be able to process a long-form video file (e.g., `.mp4`).
* **SYS-102:** I must use **Vertex AI Video Intelligence** to perform a full analysis, extracting all `labels` (object tracking, action recognition) and `ocr_text` with their precise start/end timestamps.
* **SYS-103:** I must chunk the video into fixed-length (e.g., 8-second) overlapping (e.g., 4-second) segments.
* **SYS-104:** For *each* segment, I must call the **Vertex AI Multimodal Embeddings API** to generate a single `video_embedding` that represents the content *and motion* within that segment.
* **SYS-105:** I must create a single JSON document for each segment and store it in our **Elasticsearch** index. This document *must* contain:
    * `video_id` (e.g., "cctv_feed_01")
    * `start_time_sec` (e.g., 4.0)
    * `end_time_sec` (e.g., 12.0)
    * `video_embedding` (the vector)
    * `labels` (a list of all labels from the Video Intelligence API that fall within this time range, e.g., `["person", "walking", "server_rack"]`)
    * `ocr_text` (a string of all OCR'd text from that time range)

#### **EPIC 2: The Conversational AI Analyst (User-Facing)**

* **USR-201:** As Alex, I want a simple, web-based chat interface where I can type my query.
* **USR-202:** As Alex, I want to ask *conceptual* (semantic) questions, so I can find events without knowing the exact keywords (e.g., "Show me suspicious activity near the loading bay").
* **USR-203:** As Alex, I want to ask *specific* (keyword) questions, so I can find precise artifacts (e.g., "Find all clips with a person in a 'red shirt'" or "when is the 'EXIT' sign visible?").
* **USR-204:** As Alex, I want to receive a natural language summary of the findings (e.g., "I found 2 instances of 'suspicious activity' at 04:15 and 18:32.").
* **USR-205:** As Alex, I want to see a list of playable video clips *cued to the exact start time* of the event so I can immediately verify the finding.

### 6. Technical Architecture & Language

* **Primary Language:** **Python 3.10+**
* **Ingestion Pipeline (`ingest.py`):**
    * A standalone Python script.
    * Uses `google-cloud-video-intelligence` to generate the metadata JSON.
    * Uses `ffmpeg-python` (or similar) to handle video chunking based on timestamps.
    * Uses `google-cloud-aiplatform` to call the Multimodal Embeddings API for each chunk.
    * Uses `elasticsearch-py` to write each document to the Elastic index.
* **Agent Backend (The "Server"):**
    * **FastAPI** (Python framework).
    * Exposes a single API endpoint: `POST /ask`.
    * This endpoint:
        1.  Receives the user's `query` (e.g., "person near server").
        2.  Calls **Vertex AI Multimodal Embeddings** to get a query vector.
        3.  Calls **Elasticsearch** to perform a **hybrid search**:
            * **Vector Search:** `video_embedding` field (for semantic "nearness").
            * **Keyword Filter:** `labels` field (for "person" and "server").
        4.  Receives the list of matching documents (with `start_time_sec`).
        5.  Passes the user's `query` and the `context` (the list of results) to a **Vertex AI Gemini** model.
        6.  Gemini synthesizes the natural language answer (e.g., "I found...").
        7.  Returns a JSON response to the frontend: `{"answer": "...", "clips": [{"start": 255.0}, {"start": 1112.0}]}`.
* **Frontend (The "UI"):**
    * A single `index.html` file.
    * Uses vanilla **JavaScript** (`fetch`) to call the `/ask` backend endpoint.
    * Parses the JSON response to:
        1.  Display the `answer` string in a chat bubble.
        2.  Dynamically create a list of buttons (`<button>Clip 1 (04:15)</button>`).
        3.  When a button is clicked, it sets the `currentTime` of the `<video>` element to the `start` time and plays it.

### 7. Hackathon Scope (Minimum Viable Product)

To be "amazing in a vacuum," we must focus on a perfect, end-to-end demo, not on features.

* **P0 (Must Have):**
    * One (1) 10-15 minute demo video, **pre-processed**. The `ingest.py` script is in the repo to *show how it was done*. The Elastic index is already populated.
    * The FastAPI backend, runnable.
    * The `index.html` frontend, viewable.
    * The demo *must* successfully show a user asking at least two different questions (one conceptual, one keyword) and getting back correct, playable, timestamped clips.
