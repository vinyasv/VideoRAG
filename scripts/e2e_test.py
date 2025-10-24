import requests
import json
import time

# --- Configuration ---
BASE_URL = "http://localhost:8000"
ASK_ENDPOINT = f"{BASE_URL}/ask"
VIDEO_ID = "burglary_video_compressed"

QUERIES = [
    {
        "scenario": "Initial Approach",
        "query": "Show me the first moment someone approaches the glass door."
    },
    {
        "scenario": "Forced Entry",
        "query": "At what point does the intruder use an object to break the glass on the door?"
    },
    {
        "scenario": "Subject Analysis",
        "query": "Provide a description of the person who enters the building. What are they wearing and what do they do once inside?"
    }
]

def check_server_status():
    """Checks if the backend server is running."""
    try:
        response = requests.get(BASE_URL)
        if response.status_code == 200 and response.json().get("status") == "operational":
            print("✅ Backend server is operational.")
            return True
        else:
            print(f"❌ Backend server returned status {response.status_code}.")
            return False
    except requests.ConnectionError:
        print("❌ Backend server is not running. Please start it with 'uvicorn backend.main:app --reload'")
        return False

def run_test_query(scenario: str, query: str, video_id: str):
    """Sends a single query to the backend and prints the result."""
    print(f"--- Testing Scenario: {scenario} ---")
    print(f"❓ Query: {query}")

    payload = {
        "query": query,
        "video_id": video_id
    }

    try:
        start_time = time.time()
        response = requests.post(ASK_ENDPOINT, json=payload, timeout=300) # 5 minute timeout
        end_time = time.time()

        duration = end_time - start_time
        print(f"⏱️ Request took {duration:.2f} seconds.")

        if response.status_code == 200:
            result = response.json()
            print("\n🤖 AI Answer:")
            print(result.get("answer", "No answer found in response."))
            print("\n🔍 Retrieved Clips:")
            if result.get("clips"):
                for i, clip in enumerate(result["clips"]):
                    print(f"  - Clip {i+1}: Start: {clip['start_time_sec']:.2f}s, End: {clip['end_time_sec']:.2f}s, Score: {clip['score']:.4f}")
            else:
                print("  No clips were returned.")
        else:
            print(f"❌ Error: Received status code {response.status_code}")
            try:
                print("📝 Response Body:")
                print(response.json())
            except json.JSONDecodeError:
                print(response.text)

    except requests.exceptions.RequestException as e:
        print(f"❌ An error occurred during the request: {e}")
    finally:
        print("-" * (len(scenario) + 24))
        print("\n")


if __name__ == "__main__":
    if check_server_status():
        print(f"🚀 Starting end-to-end test for video_id: '{VIDEO_ID}'...")
        for q in QUERIES:
            run_test_query(q["scenario"], q["query"], VIDEO_ID)
        print("✅ End-to-end test complete.")
