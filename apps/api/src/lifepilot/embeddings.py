import json
import math
from typing import Final
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ValidationError

from lifepilot.config import settings

EMBEDDING_DIMENSIONS: Final = 768
MAX_EMBEDDING_INPUT_CHARS: Final = 8000


class EmbeddingProviderError(RuntimeError):
    pass


class EmbeddingDatum(BaseModel):
    embedding: list[float]


class EmbeddingResponse(BaseModel):
    data: list[EmbeddingDatum]


def embedding_provider_configured() -> bool:
    return bool(settings.embedding_model and (settings.embedding_base_url or settings.llm_base_url))


def embed_text(text: str) -> list[float]:
    if not embedding_provider_configured():
        raise EmbeddingProviderError("Kein Embedding-Provider konfiguriert")
    if not text.strip():
        raise EmbeddingProviderError("Leerer Text kann nicht eingebettet werden")
    body = {"model": settings.embedding_model, "input": text[:MAX_EMBEDDING_INPUT_CHARS], "dimensions": EMBEDDING_DIMENSIONS}
    base_url = settings.embedding_base_url or settings.llm_base_url
    api_key = settings.embedding_api_key or settings.llm_api_key
    request = Request(
        f"{base_url.rstrip('/')}/embeddings",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=settings.embedding_timeout_seconds) as response:
            parsed = EmbeddingResponse.model_validate_json(response.read())
        if not parsed.data:
            raise EmbeddingProviderError("Der Embedding-Provider hat keine Vektoren geliefert")
        vector = parsed.data[0].embedding
        if len(vector) != EMBEDDING_DIMENSIONS or not all(math.isfinite(value) for value in vector):
            raise EmbeddingProviderError(f"Das Embedding-Modell muss {EMBEDDING_DIMENSIONS} endliche Werte liefern")
        return vector
    except (HTTPError, URLError, TimeoutError, ValidationError, ValueError) as error:
        raise EmbeddingProviderError("Der Embedding-Provider ist fehlgeschlagen; die Textsuche bleibt verfügbar") from error
