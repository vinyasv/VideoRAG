import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import vertexai
from vertexai.vision_models import MultiModalEmbeddingModel
from config import settings

print("Testing Vertex AI connection...")
print(f"Project: {settings.PROJECT_ID}")
print(f"Location: {settings.LOCATION}")

try:
    vertexai.init(project=settings.PROJECT_ID, location=settings.LOCATION)
    print("✓ Vertex AI initialized")
    
    model = MultiModalEmbeddingModel.from_pretrained(settings.EMBEDDING_MODEL)
    print(f"✓ Loaded model: {settings.EMBEDDING_MODEL}")
    
    test_embedding = model.get_embeddings(
        contextual_text="test query",
        dimension=settings.EMBEDDING_DIMENSION
    )
    print(f"✓ Generated test embedding: {len(test_embedding.text_embedding)} dimensions")
    
    print("\n✅ All Vertex AI checks passed!")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    print("\nMake sure you've run: gcloud auth application-default login")
    sys.exit(1)

