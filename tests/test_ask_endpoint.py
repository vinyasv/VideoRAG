import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

# Stub Google Cloud modules to avoid network calls during imports


class FakeBlob:
    def upload_from_filename(self, *args, **kwargs):
        pass

    def upload_from_string(self, *args, **kwargs):
        pass

    def download_to_filename(self, *args, **kwargs):
        pass

    def download_as_bytes(self, *args, **kwargs):
        return b""

    def generate_signed_url(self, *args, **kwargs):
        return "https://example.com/signed"

    @property
    def public_url(self):
        return "https://example.com/public"

    def delete(self):
        pass


class FakeBucket:
    def __init__(self, name="demo-bucket"):
        self.name = name

    def blob(self, name):
        return FakeBlob()


class FakeStorageClient:
    def __init__(self, *args, **kwargs):
        pass

    def get_bucket(self, name):
        return FakeBucket(name)

    def create_bucket(self, name, location=None):
        return FakeBucket(name)


class FakeCredentials:
    @staticmethod
    def from_service_account_file(path):
        return FakeCredentials()


google_module = types.ModuleType("google")
cloud_module = types.ModuleType("google.cloud")
storage_module = types.ModuleType("google.cloud.storage")
storage_module.Client = FakeStorageClient
cloud_module.storage = storage_module
oauth2_module = types.ModuleType("google.oauth2")
service_account_module = types.ModuleType("google.oauth2.service_account")
service_account_module.Credentials = FakeCredentials
aiplatform_module = types.ModuleType("google.cloud.aiplatform")
aiplatform_version_module = types.ModuleType("google.cloud.aiplatform.version")
aiplatform_version_module.__version__ = "0.0.0"
aiplatform_module.version = aiplatform_version_module
aiplatform_module.init = lambda *args, **kwargs: None

sys.modules.setdefault("google", google_module)
sys.modules["google.cloud"] = cloud_module
sys.modules["google.cloud.storage"] = storage_module
sys.modules["google.oauth2"] = oauth2_module
sys.modules["google.oauth2.service_account"] = service_account_module
sys.modules["google.cloud.aiplatform"] = aiplatform_module
sys.modules["google.cloud.aiplatform.version"] = aiplatform_version_module

# Stub Vertex AI modules to avoid network calls


vertexai_module = types.ModuleType("vertexai")
vertexai_module.init = lambda *args, **kwargs: None


class DummyGenerativeModel:
    def __init__(self, model_name):
        self.model_name = model_name

    async def generate_content_async(self, prompt_parts):
        return SimpleNamespace(text="dummy-answer")


class DummyPart:
    @staticmethod
    def from_uri(uri, mime_type="video/mp4"):
        return {"uri": uri, "mime_type": mime_type}


generative_models_module = types.ModuleType("vertexai.generative_models")
generative_models_module.GenerativeModel = DummyGenerativeModel
generative_models_module.Part = DummyPart


class DummyEmbeddingModel:
    @classmethod
    def from_pretrained(cls, model_name):
        return cls()

    def get_embeddings(self, contextual_text, dimension):
        return SimpleNamespace(text_embedding=[0.1, 0.2, 0.3])


vision_models_module = types.ModuleType("vertexai.vision_models")
vision_models_module.MultiModalEmbeddingModel = DummyEmbeddingModel


sys.modules["vertexai"] = vertexai_module
sys.modules["vertexai.generative_models"] = generative_models_module
sys.modules["vertexai.vision_models"] = vision_models_module


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture
def sample_hits():
    def make_hit(idx, score):
        return {
            "_id": f"clip-{idx}",
            "_score": score,
            "_normalized_score": score,
            "_source": {
                "video_id": "demo",
                "start_time_sec": idx * 10,
                "end_time_sec": idx * 10 + 5,
                "labels": [f"label-{idx}"],
                "ocr_text": f"text-{idx}",
                "clip_uri": f"https://example.com/clip-{idx}.mp4",
            },
        }

    return [
        make_hit(0, 1.0),
        make_hit(1, 0.8),
        make_hit(2, 0.6),
        make_hit(3, 0.3),
        make_hit(4, 0.1),
    ]


class StubElasticsearchClient:
    def __init__(self, hits):
        self.hits = hits

    async def hybrid_search(self, **kwargs):
        return list(self.hits)

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_ask_question_passes_all_hits_to_llm(sample_hits, monkeypatch):
    from backend import main as backend_main
    from backend.models import QueryRequest
    from backend.vertex_ai_client import vertex_ai_client

    captured = {}

    backend_main.es_client = StubElasticsearchClient(sample_hits)

    monkeypatch.setattr(
        vertex_ai_client,
        "get_query_embedding",
        lambda query_text: [0.1, 0.2, 0.3],
    )

    async def fake_synthesize_answer(query, results, video_id, summary):
        captured["results"] = results
        return "stub-answer"

    monkeypatch.setattr(
        vertex_ai_client,
        "synthesize_answer",
        fake_synthesize_answer,
    )

    request = QueryRequest(query="who enters the room", video_id=None, use_video_clips=True)

    response = await backend_main.ask_question(request)

    assert len(response.clips) == 3
    assert [hit["_id"] for hit in captured["results"]] == [hit["_id"] for hit in sample_hits[:3]]
