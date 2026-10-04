from unittest.mock import MagicMock, patch

import httpx
import pytest

from amp_client.async_client import AsyncAMPClient


@pytest.mark.asyncio
async def test_async_url_normalization():
    # Test normalization when /amp/v1 is missing
    client = AsyncAMPClient("http://localhost:8000", "test_agent")
    assert client.server_url == "http://localhost:8000/amp/v1"

    # Test normalization with trailing slash and missing /amp/v1
    client = AsyncAMPClient("http://localhost:8000/", "test_agent")
    assert client.server_url == "http://localhost:8000/amp/v1"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_async_remember_success(mock_post):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 201
    mock_response.json.return_value = {
        "id": "mem_123",
        "type": "semantic",
        "content": {"text": "hello fact", "metadata": {}},
        "identity": {
            "owner_id": "user_abc",
            "owner_type": "user",
            "created_by": "test_agent",
        },
    }
    mock_post.return_value = mock_response

    async with AsyncAMPClient("http://localhost:8000", "test_agent") as client:
        res = await client.remember(content="hello fact", owner_id="user_abc")

    assert res["id"] == "mem_123"
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "http://localhost:8000/amp/v1/memories"
    assert kwargs["headers"]["X-AMP-Agent-ID"] == "test_agent"
    assert kwargs["json"]["content"]["text"] == "hello fact"
    assert kwargs["json"]["identity"]["owner_id"] == "user_abc"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_async_recall_success(mock_post):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [
            {"id": "mem_1", "content": {"text": "result 1"}},
            {"id": "mem_2", "content": {"text": "result 2"}},
        ]
    }
    mock_post.return_value = mock_response

    async with AsyncAMPClient("http://localhost:8000", "test_agent") as client:
        results = await client.recall(query="test query", owner_id="user_abc", limit=2)

    assert len(results) == 2
    assert results[0]["id"] == "mem_1"
    mock_post.assert_called_once()
    args, kwargs = mock_post.call_args
    assert args[0] == "http://localhost:8000/amp/v1/memories/search"
    assert kwargs["json"]["query"] == "test query"
    assert kwargs["json"]["owner_id"] == "user_abc"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_async_get_memory_reads_one_cell(mock_get):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"id": "mem_123", "scoring": {"access_count": 2}}
    mock_get.return_value = mock_response

    async with AsyncAMPClient("http://localhost:8000", "test_agent") as client:
        cell = await client.get_memory("mem_123")

    assert cell["id"] == "mem_123"
    args, kwargs = mock_get.call_args
    assert args[0] == "http://localhost:8000/amp/v1/memories/mem_123"
    assert kwargs["headers"]["X-AMP-Agent-ID"] == "test_agent"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.delete")
@patch("httpx.AsyncClient.patch")
async def test_async_forget_archives_before_deleting(mock_patch, mock_delete):
    """The protocol only permits `archived -> deleted`, in that order.

    This test was rewritten after the method shipped without the PATCH at all: it
    mocked only DELETE, so it passed while a real server answered 409 for every
    cell that was not already archived - which is every cell a caller wants to
    forget. The mock now models the precondition it was hiding.
    """
    order: list[str] = []
    archive = MagicMock(spec=httpx.Response)
    archive.status_code = 200
    mock_patch.side_effect = lambda *a, **k: (order.append("patch"), archive)[1]
    deleted = MagicMock(spec=httpx.Response)
    deleted.status_code = 204
    mock_delete.side_effect = lambda *a, **k: (order.append("delete"), deleted)[1]

    async with AsyncAMPClient("http://localhost:8000", "test_agent") as client:
        res = await client.forget("mem_123")

    assert res is True
    assert order == ["patch", "delete"]
    args, kwargs = mock_patch.call_args
    assert args[0] == "http://localhost:8000/amp/v1/memories/mem_123"
    assert kwargs["json"] == {"lifecycle": {"status": "archived"}}
    assert kwargs["headers"]["X-AMP-Agent-ID"] == "test_agent"
    args, kwargs = mock_delete.call_args
    assert args[0] == "http://localhost:8000/amp/v1/memories/mem_123"


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_async_list_memories_success(mock_get):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [{"id": "mem_1", "content": {"text": "item 1"}}]
    }
    mock_get.return_value = mock_response

    async with AsyncAMPClient("http://localhost:8000", "test_agent") as client:
        res = await client.list_memories(owner_id="user_abc", type="episodic", limit=10)

    assert len(res) == 1
    assert res[0]["id"] == "mem_1"
    mock_get.assert_called_once()
    args, kwargs = mock_get.call_args
    assert args[0] == "http://localhost:8000/amp/v1/memories"
    assert kwargs["params"]["owner_id"] == "user_abc"
    assert kwargs["params"]["type"] == "episodic"
    assert kwargs["params"]["limit"] == 10


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_async_health_ok(mock_get):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok"}
    mock_get.return_value = mock_response

    async with AsyncAMPClient("http://localhost:8000", "test_agent") as client:
        assert await client.health() is True


# ---------------------------------------------------------------------------
# API keys (X-AMP-API-Key)
# ---------------------------------------------------------------------------


def test_async_identity_headers_omit_the_key_unless_one_was_given():
    client = AsyncAMPClient("http://localhost:8000", "agent-1")
    assert client.identity_headers() == {"X-AMP-Agent-ID": "agent-1"}


def test_async_identity_headers_carry_the_key_when_one_was_given():
    """Every async call site uses this builder, so one test covers them all."""
    client = AsyncAMPClient("http://localhost:8000", "agent-1", api_key="agent-one-key")
    assert client.identity_headers() == {
        "X-AMP-Agent-ID": "agent-1",
        "X-AMP-API-Key": "agent-one-key",
    }


# ---------------------------------------------------------------------------
# Paging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_async_recall_sends_the_page_offset(mock_post):
    """The server pages by offset; an SDK that cannot send one cannot page."""
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": [], "returned": 0, "has_more": False}
    mock_post.return_value = mock_response

    async with AsyncAMPClient("http://localhost:8000", "test_agent") as client:
        await client.recall(query="test query", owner_id="user_abc", limit=5, offset=10)

    assert mock_post.call_args.kwargs["json"]["offset"] == 10


@pytest.mark.asyncio
@patch("httpx.AsyncClient.post")
async def test_async_recall_defaults_to_the_first_page(mock_post):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": []}
    mock_post.return_value = mock_response

    async with AsyncAMPClient("http://localhost:8000", "test_agent") as client:
        await client.recall(query="test query", owner_id="user_abc")

    assert mock_post.call_args.kwargs["json"]["offset"] == 0


@pytest.mark.asyncio
@patch("httpx.AsyncClient.get")
async def test_async_list_memories_sends_the_page_offset(mock_get):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {"results": []}
    mock_get.return_value = mock_response

    async with AsyncAMPClient("http://localhost:8000", "test_agent") as client:
        await client.list_memories(owner_id="user_abc", limit=20, offset=20)

    assert mock_get.call_args.kwargs["params"]["offset"] == 20
