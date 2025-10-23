import requests
import json

def test_query(query):
    response = requests.post(
        'http://localhost:8000/ask',
        json={'query': query},
        timeout=30
    )
    
    if response.status_code == 200:
        data = response.json()
        print(f"\n{'='*60}")
        print(f"Query: {query}")
        print(f"{'='*60}\n")
        print(f"Answer:\n{data['answer']}\n")
        print(f"Found {len(data['clips'])} clips:")
        for i, clip in enumerate(data['clips'][:3]):
            print(f"\n  Clip {i+1}:")
            print(f"    Time: {clip['start_time_sec']}-{clip['end_time_sec']}s")
            print(f"    Score: {clip['score']:.3f}")
            print(f"    Labels: {', '.join(clip['labels'][:5])}")
            if clip['ocr_text']:
                print(f"    OCR: {clip['ocr_text'][:80]}...")
    else:
        print(f"Error {response.status_code}: {response.text}")

print("Testing Sentinel API...")
print(f"Server: http://localhost:8000\n")

test_query("show me tigers")
test_query("find wildlife animals")
test_query("Los Angeles zoo")

