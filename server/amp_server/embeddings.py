"""Embedding providers -- who turns text into vectors.

The reference server stores vectors, so something has to produce them. Chroma
ships a small local model and uses it by default, which is fine for a demo and
wrong for anyone with an embedding budget, a language that model does not cover
well, or a rule about where their text is allowed to go.

So the choice is explicit: an operator selects a provider, the storage adapter
embeds through it, and `GET /spec` reports which one is in use. A client that
cares can then tell what it is talking to instead of guessing.

Selecting `openai-compatible` sends memory text to the configured endpoint. That
is the point of choosing it, and it is why the default is local.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any

import httpx

# Names accepted in AMP_EMBEDDING_PROVIDER.
DEFAULT_PROVIDER = "default"
OPENAI_COMPATIBLE_PROVIDER = "openai-compatible"
PROVIDER_CHOICES = (DEFAULT_PROVIDER, OPENAI_COMPATIBLE_PROVIDER)


class EmbeddingProvider(ABC):
    """Turns text into vectors."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Short identifier reported at GET /spec."""

    @property
    @abstractmethod
    def dimensions(self) -> int | None:
        """Vector width, or None when the service decides per request."""

    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed a batch, returning one vector per input, in input order.

        Plain Python floats, not numpy scalars: the storage backend validates
        the type and rejects the batch outright otherwise.
        """


class ChromaDefaultEmbeddingProvider(EmbeddingProvider):
    """Chroma's own default embedding function.

    Chroma embeds locally with a small ONNX model (all-MiniLM-L6-v2), so text
    does not leave the process. This is the default because it needs no
    configuration and no network, and it delegates to Chroma's function rather
    than reimplementing it, so the vectors are exactly what a plain Chroma
    collection would hold.
    """

    name = "chroma-default"
    dimensions = 384

    def __init__(self) -> None:
        # Imported here so the module stays importable without Chroma's
        # embedding extras, which are heavy and only needed when this provider
        # is actually selected.
        from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

        self._function = DefaultEmbeddingFunction()

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        return [
            [float(value) for value in vector] for vector in self._function(list(texts))
        ]


class OpenAICompatibleEmbeddingProvider(EmbeddingProvider):
    """Embeddings from any service that speaks the OpenAI `/embeddings` API.

    Covers OpenAI, Azure OpenAI, and the many local servers that mirror the same
    shape (Ollama, LM Studio, vLLM, text-embeddings-inference). Everything it
    needs is a base URL and a model name, so an operator can point it at whatever
    they already run.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        dimensions: int | None = None,
        timeout: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.model = model
        self._dimensions = dimensions
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._client = httpx.Client(timeout=timeout, transport=transport)

    @property
    def name(self) -> str:
        return OPENAI_COMPATIBLE_PROVIDER

    @property
    def dimensions(self) -> int | None:
        return self._dimensions

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        """Call the service and return its vectors in input order.

        The API returns an `index` per item and is not contractually ordered, so
        the result is sorted by it: a silently reordered batch would attach the
        wrong vector to the wrong memory, which is the kind of bug that looks
        like bad search quality rather than a defect.
        """
        response = self._client.post(
            f"{self._base_url}/embeddings",
            json={"model": self.model, "input": list(texts)},
            headers=self._headers(),
        )
        response.raise_for_status()
        items = response.json()["data"]
        ordered = sorted(items, key=lambda item: item.get("index", 0))
        return [list(item["embedding"]) for item in ordered]

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers


def _require(env_name: str) -> str:
    value = os.environ.get(env_name)
    if not value:
        raise ValueError(
            f"{env_name} is required when AMP_EMBEDDING_PROVIDER="
            f"{OPENAI_COMPATIBLE_PROVIDER}"
        )
    return value


def provider_from_env() -> EmbeddingProvider:
    """Build the configured provider, or fail loudly.

    An unknown name raises rather than falling back to the default: a
    deployment that asked for one embedding model and silently got another would
    produce vectors nobody can search consistently, and the failure would look
    like poor recall rather than a misconfiguration.
    """
    choice = os.environ.get("AMP_EMBEDDING_PROVIDER", DEFAULT_PROVIDER).strip()

    if choice in ("", DEFAULT_PROVIDER):
        return ChromaDefaultEmbeddingProvider()

    if choice == OPENAI_COMPATIBLE_PROVIDER:
        raw_dimensions = os.environ.get("AMP_EMBEDDING_DIMENSIONS")
        dimensions: int | None = None
        if raw_dimensions:
            try:
                dimensions = int(raw_dimensions)
            except ValueError as exc:
                raise ValueError(
                    "AMP_EMBEDDING_DIMENSIONS must be an integer, "
                    f"got {raw_dimensions!r}"
                ) from exc
        return OpenAICompatibleEmbeddingProvider(
            base_url=_require("AMP_EMBEDDING_BASE_URL"),
            model=_require("AMP_EMBEDDING_MODEL"),
            api_key=os.environ.get("AMP_EMBEDDING_API_KEY") or None,
            dimensions=dimensions,
        )

    raise ValueError(
        f"unknown AMP_EMBEDDING_PROVIDER {choice!r}; "
        f"expected one of {', '.join(PROVIDER_CHOICES)}"
    )


def describe(provider: EmbeddingProvider) -> dict[str, Any]:
    """The `embedding` block of `GET /spec`."""
    return {"provider": provider.name, "dimensions": provider.dimensions}
