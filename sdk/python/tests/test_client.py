import pytest
from unittest.mock import MagicMock, patch
import requests

from amp_client.client import AMPClient
from amp_client.exceptions import AMPError


def test_url_normalization():
    # Test normalization when /amp/v1 is missing
    client = AMPClient("http://localhost:8000", "test_agent")
    assert client.server_url == "http://localhost:8000/amp/v1"

    # Test normalization with trailing slash and missing /amp/v1
    client = AMPClient("http://localhost:8000/", "test_agent")
    assert client.server_url == "http://localhost:8000/amp/v1"

    # Test normalization when /amp/v1 is present
    client = AMPClient("http://localhost:8000/amp/v1", "test_agent")
    assert client.server_url == "http://localhost:8000/amp/v1"

    # Test normalization with trailing slash and /amp/v1 present
    client = AMPClient("http://localhost:8000/amp/v1/", "test_agent")
    assert client.server_url == "http://localhost:8000/amp/v1"


@patch("requests.Session.request")
def test_remember_success(mock_request):
    mock_response = MagicMock()
    mock_response.status_code = 201
    mock_response.json.return_value = {
        "id": "mem_123",
        "type": "semantic",
        "content": {"text": "hello fact", "metadata": {}},
        "identity": {"owner_id": "user_abc", "owner_type": "user", "created_by": "test_agent"},
    }
    mock_request.return_value = mock_response

    client = AMPClient("http://localhost:8000", "test_agent")
    res = client.remember(content="hello fact", owner_id="user_abc")

    assert res["id"] == "mem_123"
    mock_request.assert_called_once()
    args, kwargs = mock_request.call_args
    assert args[0] == "POST"
    assert args[1] == "http://localhost:8000/amp/v1/memories"
    assert kwargs["headers"]["X-AMP-Agent-ID"] == "test_agent"
    assert kwargs["json"]["content"]["text"] == "hello fact"
    assert kwargs["json"]["identity"]["owner_id"] == "user_abc"


@patch("requests.Session.request")
def test_remember_error_raises_amp_error(mock_request):
    mock_response = MagicMock()
    mock_response.status_code = 422
    mock_response.text = "Unprocessable Entity"
    mock_response.json.return_value = {
        "error": {
            "code": "INVALID_SCHEMA",
            "message": "Memory Cell is missing MUST fields",
            "details": {"missing": ["content.text"]},
        }
    }
    mock_request.return_value = mock_response

    client = AMPClient("http://localhost:8000", "test_agent")
    with pytest.raises(AMPError) as exc_info:
        client.remember(content="", owner_id="user_abc")

    assert "INVALID_SCHEMA" in str(exc_info.value)
    assert exc_info.value.status_code == 422
    assert exc_info.value.details == {"missing": ["content.text"]}


@patch("requests.Session.request")
def test_recall_success(mock_request):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [
            {"id": "mem_1", "content": {"text": "result 1"}},
            {"id": "mem_2", "content": {"text": "result 2"}},
        ]
    }
    mock_request.return_value = mock_response

    client = AMPClient("http://localhost:8000", "test_agent")
    results = client.recall(query="test query", owner_id="user_abc", limit=2)

    assert len(results) == 2
    assert results[0]["id"] == "mem_1"
    mock_request.assert_called_once()
    args, kwargs = mock_request.call_args
    assert args[0] == "POST"
    assert args[1] == "http://localhost:8000/amp/v1/memories/search"
    assert kwargs["json"]["query"] == "test query"
    assert kwargs["json"]["owner_id"] == "user_abc"
    assert kwargs["json"]["limit"] == 2


@patch("requests.Session.request")
def test_forget_success(mock_request):
    # Mock sequence: GET, PATCH, DELETE
    mock_get = MagicMock()
    mock_get.status_code = 200
    mock_get.json.return_value = {
        "id": "mem_123",
        "lifecycle": {
            "created_at": "2026-06-12T10:00:00Z",
            "status": "active"
        }
    }

    mock_patch = MagicMock()
    mock_patch.status_code = 200
    mock_patch.json.return_value = {}

    mock_delete = MagicMock()
    mock_delete.status_code = 204

    mock_request.side_effect = [mock_get, mock_patch, mock_delete]

    client = AMPClient("http://localhost:8000", "test_agent")
    res = client.forget("mem_123")

    assert res is True
    assert mock_request.call_count == 3
    
    # Check GET call
    args_get, _ = mock_request.call_args_list[0]
    assert args_get[0] == "GET"
    assert args_get[1] == "http://localhost:8000/amp/v1/memories/mem_123"

    # Check PATCH call
    args_patch, kwargs_patch = mock_request.call_args_list[1]
    assert args_patch[0] == "PATCH"
    assert args_patch[1] == "http://localhost:8000/amp/v1/memories/mem_123"
    assert kwargs_patch["json"]["lifecycle"]["status"] == "archived"
    assert kwargs_patch["json"]["lifecycle"]["created_at"] == "2026-06-12T10:00:00Z"

    # Check DELETE call
    args_del, _ = mock_request.call_args_list[2]
    assert args_del[0] == "DELETE"
    assert args_del[1] == "http://localhost:8000/amp/v1/memories/mem_123"


@patch("requests.Session.request")
def test_list_memories_success(mock_request):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "results": [{"id": "mem_1", "content": {"text": "item 1"}}]
    }
    mock_request.return_value = mock_response

    client = AMPClient("http://localhost:8000", "test_agent")
    res = client.list_memories(owner_id="user_abc", type="episodic", limit=10)

    assert len(res) == 1
    assert res[0]["id"] == "mem_1"
    mock_request.assert_called_once()
    args, kwargs = mock_request.call_args
    assert args[0] == "GET"
    assert args[1] == "http://localhost:8000/amp/v1/memories"
    assert kwargs["params"]["owner_id"] == "user_abc"
    assert kwargs["params"]["type"] == "episodic"
    assert kwargs["params"]["limit"] == 10


@patch("requests.Session.request")
def test_health_ok(mock_request):
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"status": "ok"}
    mock_request.return_value = mock_response

    client = AMPClient("http://localhost:8000", "test_agent")
    assert client.health() is True


@patch("requests.Session.request")
def test_health_error(mock_request):
    mock_request.side_effect = requests.RequestException("conn error")

    client = AMPClient("http://localhost:8000", "test_agent")
    assert client.health() is False
