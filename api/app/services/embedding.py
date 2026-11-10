import math

from google import genai
from google.genai import types

from app.config import settings

MAX_EMBED_CHARS = 6000


class GeminiEmbedder:
    """embed(text) -> list[float] using Gemini embeddings."""

    def __init__(self, client=None, model: str | None = None):
        self.client = client or genai.Client(api_key=settings.google_api_key)
        self.model = model or settings.embedding_model

    def __call__(self, text: str) -> list[float]:
        result = self.client.models.embed_content(
            model=self.model,
            contents=text[:MAX_EMBED_CHARS],
            config=types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY"),
        )
        return list(result.embeddings[0].values)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0