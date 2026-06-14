import pytest
from unittest.mock import MagicMock, patch
import httpx

from amp_client.async_client import AsyncAMPClient
from amp_client.exceptions import AMPError


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
        "identity": {"owner_id": "user_abc", "owner_type": "user", "created_by": "test_agent"},
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
@patch("httpx.AsyncClient.delete")
async def test_async_forget_success(mock_delete):
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 204
    mock_delete.return_value = mock_response

    async with AsyncAMPClient("http://localhost:8000", "test_agent") as client:
        res = await client.forget("mem_123")

    assert res is True
    mock_delete.assert_called_once()
    args, kwargs = mock_delete.call_args
    assert args[0] == "http://localhost:8000/amp/v1/memories/mem_123"
    assert kwargs["headers"]["X-AMP-Agent-ID"] == "test_agent"


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
