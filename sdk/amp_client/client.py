from __future__ import annotations

from typing import Any

import requests

from amp_client.exceptions import AMPError


class AMPClient:
    """Synchronous client for the Agent Memory Protocol (AMP) server."""

    def __init__(
        self, server_url: str, agent_id: str, api_key: str | None = None
    ) -> None:
        """Initialize the AMP client.

        Args:
            server_url: The base URL of the AMP server.
            agent_id: The ID of the agent using the client.
            api_key: The key belonging to `agent_id`, sent as `X-AMP-API-Key`.
                Only needed when the server was started with
                `AMP_API_KEYS_FILE`; without that, the server accepts the agent
                id on its own, which is the binding the spec describes.
        """
        # Normalize server_url (strip trailing slash and append /amp/v1 if not present)
        normalized_url = server_url.rstrip("/")
        if not normalized_url.endswith("/amp/v1"):
            normalized_url += "/amp/v1"

        self.server_url = normalized_url
        self.agent_id = agent_id
        self.api_key = api_key
        self.session = requests.Session()

    def identity_headers(self) -> dict[str, str]:
        """The headers that identify this client, built in one place.

        One source, for the same reason the server resolves identity in one
        dependency: a credential added to one call path and forgotten on another
        fails as a confusing 401 rather than as a code error.
        """
        headers = {"X-AMP-Agent-ID": self.agent_id}
        if self.api_key:
            headers["X-AMP-API-Key"] = self.api_key
        return headers

    def _request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        """Internal helper to execute HTTP requests with error handling."""
        url = f"{self.server_url}{path}"

        # Identity first, so a caller-supplied header can still override it.
        headers = {**self.identity_headers(), **kwargs.pop("headers", {})}

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
            except ValueError:
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
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Semantic search over Memory Cells.

        Args:
            query: Natural language search query.
            owner_id: Filter to cells owned by this ID.
            limit: Maximum results in this page.
            include_stale: If True, includes stale cells in results.
            offset: Skip this many results this agent may read, to reach the next
                page. A page shorter than `limit` is the last one - the response
                also carries `has_more`, which this method does not return; use
                `session` / `fetch` directly if you need it.

        Returns:
            The list of memory cells in 'results'.
        """
        payload = {
            "query": query,
            "owner_id": owner_id,
            "limit": limit,
            "include_stale": include_stale,
            "offset": offset,
        }

        response = self._request("POST", "/memories/search", json=payload)
        data = response.json()
        return data.get("results", [])

    def get_memory(self, memory_id: str) -> dict[str, Any]:
        """Retrieve one Memory Cell by ID.

        Reading is what resets a cell's decay clock server-side: the response
        carries the bumped `access_count` and `last_accessed_at`. Neither SDK had
        a way to do this - `forget` reached the route as a side effect of the
        round-trip it no longer needs, which is why the contract test noticed.
        """
        return self._request("GET", f"/memories/{memory_id}").json()

    def forget(self, memory_id: str) -> bool:
        """Archive then delete a Memory Cell.

        Two requests, in this order, because the protocol only permits
        `archived -> deleted`. No read first: a lifecycle update merges into the
        stored cell, so the status alone is enough and `created_at` cannot be
        changed by a client anyway.

        Args:
            memory_id: The ID of the memory cell to forget.

        Returns:
            True if the deletion status code is 204.
        """
        self._request(
            "PATCH",
            f"/memories/{memory_id}",
            json={"lifecycle": {"status": "archived"}},
        )
        response = self._request("DELETE", f"/memories/{memory_id}")
        return response.status_code == 204

    def list_memories(
        self,
        owner_id: str,
        type: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List Memory Cells by owner_id and optionally type.

        Args:
            owner_id: The ID of the owner.
            type: Optional memory type filter.
            limit: Maximum results in this page.
            offset: Skip this many results this agent may read, to reach the next
                page. A page shorter than `limit` is the last one; `has_more` is in
                the response but not returned here.

        Returns:
            The list of memory cells.
        """
        params: dict[str, Any] = {
            "owner_id": owner_id,
            "limit": limit,
            "offset": offset,
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
        except (AMPError, ValueError):
            return False
