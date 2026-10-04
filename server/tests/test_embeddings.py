"""Embedding providers: the choice is real, and the claims are honest.

The reference server used to embed with whatever Chroma picked, with no way to
choose. Now a provider is selected explicitly, so these tests guard three things:
that the default is unchanged, that a selected provider is actually the one
producing vectors, and that the provider's own claims (name, dimensions, request
shape) are true.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence

import httpx
import pytest
from conftest import make_cell

from amp_server.embeddings import (
    DEFAULT_PROVIDER,
    OPENAI_COMPATIBLE_PROVIDER,
    ChromaDefaultEmbeddingProvider,
    EmbeddingProvider,
    OpenAICompatibleEmbeddingProvider,
    describe,
    provider_from_env,
)
from amp_server.models import SearchRequest
from amp_server.storage.chroma import ChromaAdapter


class KeywordProvider(EmbeddingProvider):
    """A deterministic stand-in: one dimension per known keyword.

    Keeps every test offline and makes the vectors predictable, so the tests can
    assert on ordering rather than on the quality of a real model.
    """

    name = "stub-keywords"
    dimensions = 3
    KEYWORDS = ("email", "invoice", "python")

    def __init__(self) -> None:
        self.calls: list[list[str]] = []

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        return [
            [float(keyword in text.lower()) for keyword in self.KEYWORDS]
            for text in texts
        ]


def _search(query: str, owner_id: str) -> SearchRequest:
    return SearchRequest(query=query, owner_id=owner_id, limit=10)


# ---------------------------------------------------------------------------
# The default provider
# ---------------------------------------------------------------------------


def test_the_default_provider_reports_its_real_dimensions():
    """384 is a claim; this is the measurement behind it."""
    provider = ChromaDefaultEmbeddingProvider()
    vectors = provider.embed(["a probe"])

    assert len(vectors) == 1
    assert len(vectors[0]) == provider.dimensions


def test_the_default_provider_produces_chromas_own_vectors():
    """The default must not be a behaviour change for an existing deployment."""
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

    ours = ChromaDefaultEmbeddingProvider().embed(["the same sentence"])
    theirs = DefaultEmbeddingFunction()(["the same sentence"])

    assert ours == [[float(value) for value in vector] for vector in theirs]


def test_the_default_provider_returns_plain_floats():
    """Chroma rejects a batch whose elements are numpy scalars."""
    vector = ChromaDefaultEmbeddingProvider().embed(["types matter"])[0]
    assert all(type(value) is float for value in vector)


# ---------------------------------------------------------------------------
# A selected provider is the one that runs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_custom_provider_drives_both_indexing_and_query():
    provider = KeywordProvider()
    storage = ChromaAdapter(
        collection_name=f"test_{uuid.uuid4().hex[:12]}", embedding_provider=provider
    )
    owner = "user-embeddings"
    await storage.save(make_cell(owner_id=owner, text="please email me"))
    await storage.save(make_cell(owner_id=owner, text="send an invoice"))

    results = await storage.search(_search("invoice", owner), agent_id=owner)

    assert [cell.content.text for cell in results][0] == "send an invoice"
    # The exact batches prove the provider produced the document vectors and the
    # query vector, rather than Chroma's default doing either.
    assert provider.calls == [["please email me"], ["send an invoice"], ["invoice"]]


@pytest.mark.asyncio
async def test_an_update_re_embeds_the_new_text():
    provider = KeywordProvider()
    storage = ChromaAdapter(
        collection_name=f"test_{uuid.uuid4().hex[:12]}", embedding_provider=provider
    )
    cell = make_cell(owner_id="user-embeddings", text="nothing relevant")
    await storage.save(cell)
    provider.calls.clear()

    await storage.update(
        cell.id,
        {
            "content": {
                "text": "an invoice arrived",
                "metadata": {},
            }
        },
    )

    assert provider.calls == [["an invoice arrived"]]


@pytest.mark.asyncio
async def test_a_provider_with_a_different_vector_width_works():
    """Switching provider changes the width; nothing may assume 384."""

    class FiveDim(EmbeddingProvider):
        name = "stub-5"
        dimensions = 5

        def embed(self, texts: Sequence[str]) -> list[list[float]]:
            return [[1.0, 0.0, 0.5, 0.25, 0.125] for _ in texts]

    storage = ChromaAdapter(
        collection_name=f"test_{uuid.uuid4().hex[:12]}",
        embedding_provider=FiveDim(),
    )
    cell = make_cell(owner_id="user-width", text="anything at all")
    await storage.save(cell)

    results = await storage.search(
        _search("anything at all", "user-width"), agent_id="user-width"
    )

    assert [found.id for found in results] == [cell.id]


@pytest.mark.asyncio
async def test_the_adapter_reports_the_provider_it_uses():
    provider = KeywordProvider()
    storage = ChromaAdapter(
        collection_name=f"test_{uuid.uuid4().hex[:12]}", embedding_provider=provider
    )

    assert storage.embedding == {
        "provider": "stub-keywords",
        "dimensions": KeywordProvider.dimensions,
    }


@pytest.mark.asyncio
async def test_the_default_adapter_reports_chroma():
    storage = ChromaAdapter(collection_name=f"test_{uuid.uuid4().hex[:12]}")
    assert storage.embedding == {"provider": "chroma-default", "dimensions": 384}


def test_describe_carries_name_and_dimensions():
    assert describe(KeywordProvider()) == {
        "provider": "stub-keywords",
        "dimensions": 3,
    }


# ---------------------------------------------------------------------------
# The openai-compatible provider
# ---------------------------------------------------------------------------


def _mock(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_openai_compatible_sends_the_expected_request():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers.get("authorization")
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200, json={"data": [{"index": 0, "embedding": [0.1, 0.2]}]}
        )

    provider = OpenAICompatibleEmbeddingProvider(
        base_url="http://embed.test/v1/",
        model="text-embedding-3-small",
        api_key="secret",
        transport=_mock(handler),
    )
    vectors = provider.embed(["hello"])

    assert vectors == [[0.1, 0.2]]
    assert seen["url"] == "http://embed.test/v1/embeddings"
    assert seen["auth"] == "Bearer secret"
    assert seen["body"] == {"model": "text-embedding-3-small", "input": ["hello"]}


def test_openai_compatible_omits_the_auth_header_without_a_key():
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [0.0]}]})

    provider = OpenAICompatibleEmbeddingProvider(
        base_url="http://localhost:11434/v1",
        model="nomic-embed-text",
        transport=_mock(handler),
    )
    provider.embed(["hello"])

    assert seen["auth"] is None


def test_openai_compatible_orders_vectors_by_index():
    """A reordered batch would attach the wrong vector to the wrong memory."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": 1, "embedding": [1.0]},
                    {"index": 0, "embedding": [0.0]},
                ]
            },
        )

    provider = OpenAICompatibleEmbeddingProvider(
        base_url="http://embed.test/v1", model="m", transport=_mock(handler)
    )

    assert provider.embed(["first", "second"]) == [[0.0], [1.0]]


def test_openai_compatible_raises_on_a_non_success_status():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    provider = OpenAICompatibleEmbeddingProvider(
        base_url="http://embed.test/v1", model="m", transport=_mock(handler)
    )

    with pytest.raises(httpx.HTTPStatusError):
        provider.embed(["hello"])


def test_openai_compatible_reports_configured_dimensions():
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="http://embed.test/v1",
        model="m",
        dimensions=1536,
        transport=_mock(lambda request: httpx.Response(200, json={"data": []})),
    )
    assert describe(provider) == {
        "provider": OPENAI_COMPATIBLE_PROVIDER,
        "dimensions": 1536,
    }


def test_openai_compatible_dimensions_are_unknown_when_not_declared():
    provider = OpenAICompatibleEmbeddingProvider(
        base_url="http://embed.test/v1",
        model="m",
        transport=_mock(lambda request: httpx.Response(200, json={"data": []})),
    )
    assert provider.dimensions is None


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_the_default_is_local(monkeypatch):
    monkeypatch.delenv("AMP_EMBEDDING_PROVIDER", raising=False)
    assert provider_from_env().name == "chroma-default"


def test_an_empty_value_is_treated_as_the_default(monkeypatch):
    monkeypatch.setenv("AMP_EMBEDDING_PROVIDER", "")
    assert provider_from_env().name == "chroma-default"


def test_openai_compatible_is_built_from_the_environment(monkeypatch):
    monkeypatch.setenv("AMP_EMBEDDING_PROVIDER", OPENAI_COMPATIBLE_PROVIDER)
    monkeypatch.setenv("AMP_EMBEDDING_BASE_URL", "http://embed.test/v1")
    monkeypatch.setenv("AMP_EMBEDDING_MODEL", "nomic-embed-text")
    monkeypatch.setenv("AMP_EMBEDDING_API_KEY", "k")
    monkeypatch.setenv("AMP_EMBEDDING_DIMENSIONS", "768")

    provider = provider_from_env()

    assert provider.name == OPENAI_COMPATIBLE_PROVIDER
    assert provider.dimensions == 768


def test_openai_compatible_without_a_base_url_fails_loudly(monkeypatch):
    monkeypatch.setenv("AMP_EMBEDDING_PROVIDER", OPENAI_COMPATIBLE_PROVIDER)
    monkeypatch.delenv("AMP_EMBEDDING_BASE_URL", raising=False)
    monkeypatch.setenv("AMP_EMBEDDING_MODEL", "m")

    with pytest.raises(ValueError, match="AMP_EMBEDDING_BASE_URL is required"):
        provider_from_env()


def test_openai_compatible_without_a_model_fails_loudly(monkeypatch):
    monkeypatch.setenv("AMP_EMBEDDING_PROVIDER", OPENAI_COMPATIBLE_PROVIDER)
    monkeypatch.setenv("AMP_EMBEDDING_BASE_URL", "http://embed.test/v1")
    monkeypatch.delenv("AMP_EMBEDDING_MODEL", raising=False)

    with pytest.raises(ValueError, match="AMP_EMBEDDING_MODEL is required"):
        provider_from_env()


def test_a_non_integer_dimension_fails_loudly(monkeypatch):
    monkeypatch.setenv("AMP_EMBEDDING_PROVIDER", OPENAI_COMPATIBLE_PROVIDER)
    monkeypatch.setenv("AMP_EMBEDDING_BASE_URL", "http://embed.test/v1")
    monkeypatch.setenv("AMP_EMBEDDING_MODEL", "m")
    monkeypatch.setenv("AMP_EMBEDDING_DIMENSIONS", "lots")

    with pytest.raises(ValueError, match="AMP_EMBEDDING_DIMENSIONS must be an integer"):
        provider_from_env()


def test_an_unknown_provider_fails_loudly_and_lists_the_choices(monkeypatch):
    """A silent fallback would produce vectors nobody can search consistently."""
    monkeypatch.setenv("AMP_EMBEDDING_PROVIDER", "openai")

    with pytest.raises(ValueError) as raised:
        provider_from_env()

    message = str(raised.value)
    assert "openai" in message
    assert DEFAULT_PROVIDER in message
    assert OPENAI_COMPATIBLE_PROVIDER in message
