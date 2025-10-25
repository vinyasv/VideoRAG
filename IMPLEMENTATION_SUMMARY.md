# Implementation Summary: Flag-Based RAG System

## Overview
Implemented a user-controlled flag system that allows users to choose between fast text-only RAG and slower but more detailed video clip RAG.

---

## Changes Made

### 1. Backend API (`backend/models.py`)
Added `use_video_clips` flag to QueryRequest:
```python
class QueryRequest(BaseModel):
    query: str
    video_id: str | None = None
    use_video_clips: bool = False  # Default to fast text-only RAG
```

### 2. Vertex AI Client (`backend/vertex_ai_client.py`)
Added new text-only answer generation method:
- `synthesize_answer_text_only()` - Uses only metadata (labels, OCR, objects)
- Existing `synthesize_answer()` - Uses actual video clips

### 3. Main API Handler (`backend/main.py`)
Route to appropriate method based on flag:
```python
if request.use_video_clips:
    # Slower but more detailed - uses actual video clips
    answer = await vertex_ai_client.synthesize_answer(...)
else:
    # Faster - uses only text metadata
    answer = await vertex_ai_client.synthesize_answer_text_only(...)
```

### 4. Frontend UI (`frontend/index.html`, `frontend/app.js`, `frontend/styles.css`)
Added checkbox toggle above chat input:
- Checkbox: "Detailed Analysis (slower, uses video clips)"
- Default: unchecked (fast text-only mode)
- When checked: shows system message "🎬 Using detailed analysis mode"
- Sends `use_video_clips` flag to backend API

---

## Performance Results

### Test Query: "What happened at the door?"

**Text-Only Mode** (unchecked):
- Response time: **3.98s**
- Uses metadata: labels, OCR text, tracked objects
- Quality: Good for text/temporal queries

**Video Clip Mode** (checked):
- Response time: **17.98s**
- Uses actual video clips sent to Gemini
- Quality: Better visual details, actions, appearance

**Speed Improvement**: **77.8% faster** with text-only mode

---

## User Experience Flow

1. **Default behavior**: Fast responses (~4s)
   - User asks question
   - System uses text-only RAG
   - Quick answer based on metadata

2. **When user wants more detail**:
   - User checks "Detailed Analysis" box
   - Ask question
   - System message: "🎬 Using detailed analysis mode"
   - Slower but more detailed response (~18-26s)

---

## Storage & Ingestion

### Pre-clipping Optimization (Already Implemented)
- All videos are pre-clipped during ingestion
- Clips stored in GCS: `gs://bucket/clips/{video_id}_chunk_{i}.mp4`
- Elasticsearch stores `clip_uri` field for each segment

### Videos Ingested
- `demo`: 42 segments ✅
- `fire2`: 62 segments (in progress)
- `burglars_new`: 42 segments (in progress)

---

## Cost Analysis

### Per 1000 Queries (assuming 20% use video clips)

**Text-only queries** (800 queries):
- Time: 800 × 4s = 0.89 hours
- Cost: ~$4-8

**Video clip queries** (200 queries):
- Time: 200 × 18s = 1 hour
- Cost: ~$10-20

**Total**: ~$14-28 per 1000 queries

**vs All Video Clips**: ~$50-100 per 1000 queries

**Savings**: ~60-70% cost reduction

---

## Quality Trade-offs

### When Text-Only Works Best:
- ✅ Text extraction ("What was the door number?") - Same quality, 77% faster
- ✅ Temporal queries ("When did X happen?") - Actually better quality
- ✅ Factual queries based on OCR/labels

### When Video Clips Work Best:
- ✅ Visual details ("Describe clothing/appearance")
- ✅ Action queries ("What happened?", "How did they enter?")
- ✅ Spatial/movement queries

### Recommendation to Users:
- **Default**: Use standard mode (unchecked) for fast responses
- **Check "Detailed Analysis"** when you need:
  - Detailed visual descriptions
  - Action sequences
  - Physical appearance details

---

## Files Modified

1. `backend/models.py` - Added use_video_clips flag
2. `backend/vertex_ai_client.py` - Added synthesize_answer_text_only()
3. `backend/main.py` - Route based on flag
4. `frontend/index.html` - Added checkbox UI
5. `frontend/app.js` - Send flag to API
6. `frontend/styles.css` - Styled toggle and system messages

## New Files Created

1. `scripts/compare_rag_methods.py` - Comparison testing tool
2. `QUALITATIVE_ANALYSIS.md` - Detailed analysis report
3. `IMPLEMENTATION_SUMMARY.md` - This file

---

## Testing

Run comparison test:
```bash
python scripts/compare_rag_methods.py
```

Test frontend:
1. Open browser to `http://localhost:8000/app`
2. Ask question without checking box → Fast response
3. Check "Detailed Analysis" box
4. Ask question → Slower, detailed response

---

## Next Steps (Optional Improvements)

1. **Query classification**: Automatically detect visual vs text queries
2. **Hybrid approach**: Use text-only for first response, offer "detailed analysis" button
3. **Enhanced metadata**: Extract better descriptions during ingestion
4. **Keyframe extraction**: Ultra-fast mode using still images

---

*Implementation completed: October 25, 2025*
*Model: gemini-2.5-flash-lite*
*Performance: 77.8% faster with text-only mode*
