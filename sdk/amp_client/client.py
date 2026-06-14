from __future__ import annotations

from typing import Any
import requests

from amp_client.exceptions import AMPError


class AMPClient:
    """Synchronous client for the Agent Memory Protocol (AMP) server."""

    def __init__(self, server_url: str, agent_id: str) -> None:
        """Initialize the AMP client.

        Args:
            server_url: The base URL of the AMP server.
            agent_id: The ID of the agent using the client.
        """
        # Normalize server_url (strip trailing slash and append /amp/v1 if not present)
        normalized_url = server_url.rstrip("/")
        if not normalized_url.endswith("/amp/v1"):
            normalized_url += "/amp/v1"
        
        self.server_url = normalized_url
        self.agent_id = agent_id
        self.session = requests.Session()

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        """Internal helper to execute HTTP requests with error handling."""
        url = f"{self.server_url}{path}"
        
        # Ensure standard headers are present
        headers = kwargs.pop("headers", {})
        if "X-AMP-Agent-ID" not in headers:
            headers["X-AMP-Agent-ID"] = self.agent_id
        
        try:
            response = self.session.request(method, url, headers=headers, **kwargs)
        except requests.RequestException as e:
            raise AMPError(f"HTTP request failed: {e}") from e

        if not (200 <= response.status_code < 300):
            message = f"HTTP error {response.status_code}: {response.text}"
            details = {}
            try:
                err_json = response.json()
                if isinstance(err_json, dict) and "error" in err_json:
                    err = err_json["error"]
                    if isinstance(err, dict):
                        code = err.get("code")
                        msg = err.get("message")
                        details = err.get("details", {})
                        if code and msg:
                            message = f"{code}: {msg}"
                        elif msg:
                            message = msg
            except Exception:
                pass
            raise AMPError(message, status_code=response.status_code, details=details)

        return response

    def remember(
        self,
        content: str | dict[str, Any],
        owner_id: str,
        type: str = "semantic",
        importance: float = 0.5,
        readable_by: list[str] | None = None,
    ) -> dict[str, Any]:
        """Create a new Memory Cell.

        Args:
            content: The memory content (string text, or dict with text/metadata).
            owner_id: The ID of the owner of this memory.
            type: The memory type (e.g., 'semantic', 'episodic', 'procedural').
            importance: The importance score of this memory cell.
            readable_by: Optional list of agent ID patterns permitted to read this cell.

        Returns:
            The created Memory Cell dictionary returned by the server.
        """
        if isinstance(content, str):
            content_payload = {"text": content, "metadata": {}}
        elif isinstance(content, dict):
            content_payload = content
        else:
            content_payload = {"text": str(content), "metadata": {}}

        identity_payload = {
            "owner_id": owner_id,
            "owner_type": "user",
        }

        body: dict[str, Any] = {
            "type": type,
            "content": content_payload,
            "identity": identity_payload,
            "scoring": {
                "importance": importance,
            },
        }

        if readable_by is not None:
            body["access_policy"] = {
                "readable_by": readable_by,
            }

        response = self._request("POST", "/memories", json=body)
        return response.json()

    def recall(
        self,
        query: str,
        owner_id: str,
        limit: int = 5,
        include_stale: bool = False,
    ) -> list[dict[str, Any]]:
        """Semantic search over Memory Cells.

        Args:
            query: Natural language search query.
            owner_id: Filter to cells owned by this ID.
            limit: Maximum results to return.
            include_stale: If True, includes stale cells in results.

        Returns:
            The list of memory cells in 'results'.
        """
        payload = {
            "query": query,
            "owner_id": owner_id,
            "limit": limit,
            "include_stale": include_stale,
        }

        response = self._request("POST", "/memories/search", json=payload)
        data = response.json()
        return data.get("results", [])

    def forget(self, memory_id: str) -> bool:
        """Archive then delete a Memory Cell.

        Args:
            memory_id: The ID of the memory cell to forget.

        Returns:
            True if the deletion status code is 204.
        """
        # GET the memory cell first to obtain the original created_at timestamp
        # to satisfy server-side validation of MemoryLifecycle in PATCH body.
        cell = self._request("GET", f"/memories/{memory_id}").json()
        created_at = cell["lifecycle"]["created_at"]

        # PATCH to archived status
        patch_body = {
            "lifecycle": {
                "created_at": created_at,
                "status": "archived",
            }
        }
        self._request("PATCH", f"/memories/{memory_id}", json=patch_body)

        # DELETE the memory cell
        response = self._request("DELETE", f"/memories/{memory_id}")
        return response.status_code == 204

    def list_memories(
        self,
        owner_id: str,
        type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """List Memory Cells by owner_id and optionally type.

        Args:
            owner_id: The ID of the owner.
            type: Optional memory type filter.
            limit: Maximum results to return.

        Returns:
            The list of memory cells.
        """
        params: dict[str, Any] = {
            "owner_id": owner_id,
            "limit": limit,
        }
        if type is not None:
            params["type"] = type

        response = self._request("GET", "/memories", params=params)
        data = response.json()
        return data.get("results", [])

    def health(self) -> bool:
        """Check server health.

        Returns:
            True if the server is healthy and status is 'ok', False otherwise.
        """
        try:
            response = self._request("GET", "/health")
            data = response.json()
            return data.get("status") == "ok"
        except Exception:
            return False
