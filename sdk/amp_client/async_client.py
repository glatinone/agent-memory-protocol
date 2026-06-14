from __future__ import annotations
import httpx
from contextlib import asynccontextmanager
from typing import Any
from amp_client.exceptions import AMPError

class AsyncAMPClient:
    """Asynchronous AMP Client using httpx."""

    def __init__(self, server_url: str, agent_id: str):
        self.server_url = server_url.rstrip("/")
        if not self.server_url.endswith("/amp/v1"):
            self.server_url += "/amp/v1"
        self.agent_id = agent_id
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> AsyncAMPClient:
        self._client = httpx.AsyncClient()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    @asynccontextmanager
    async def _get_client(self):
        if self._client is not None:
            yield self._client
        else:
            async with httpx.AsyncClient() as client:
                yield client

    def _raise_amp_error(self, response: httpx.Response) -> None:
        try:
            err_data = response.json()
            if isinstance(err_data, dict) and "error" in err_data:
                error_detail = err_data["error"]
                code = error_detail.get("code", "UNKNOWN_ERROR")
                message = error_detail.get("message", response.text)
                raise AMPError(f"{code}: {message}")
        except AMPError:
            raise
        except Exception:
            pass
        raise AMPError(f"HTTP {response.status_code}: {response.text}")

    async def remember(
        self,
        content: str | dict[str, Any],
        owner_id: str,
        type: str = "semantic",
        importance: float = 0.5,
        readable_by: list[str] | None = None,
    ) -> dict[str, Any]:
        if isinstance(content, str):
            content_payload = {"text": content}
        else:
            content_payload = content

        body = {
            "type": type,
            "content": content_payload,
            "identity": {
                "owner_id": owner_id,
                "owner_type": "user",
            },
            "scoring": {
                "importance": importance,
            }
        }
        if readable_by is not None:
            body["access_policy"] = {
                "readable_by": readable_by
            }

        async with self._get_client() as client:
            try:
                resp = await client.post(
                    f"{self.server_url}/memories",
                    json=body,
                    headers={"X-AMP-Agent-ID": self.agent_id}
                )
            except httpx.HTTPError as exc:
                raise AMPError(f"HTTP request failed: {exc}") from exc

        if not (200 <= resp.status_code < 300):
            self._raise_amp_error(resp)
        return resp.json()

    async def recall(
        self,
        query: str,
        owner_id: str,
        limit: int = 5,
        include_stale: bool = False,
    ) -> list[dict[str, Any]]:
        body = {
            "query": query,
            "owner_id": owner_id,
            "limit": limit,
            "include_stale": include_stale,
        }
        async with self._get_client() as client:
            try:
                resp = await client.post(
                    f"{self.server_url}/memories/search",
                    json=body,
                    headers={"X-AMP-Agent-ID": self.agent_id}
                )
            except httpx.HTTPError as exc:
                raise AMPError(f"HTTP request failed: {exc}") from exc

        if not (200 <= resp.status_code < 300):
            self._raise_amp_error(resp)
        return resp.json().get("results", [])

    async def forget(self, memory_id: str) -> bool:
        async with self._get_client() as client:
            try:
                resp = await client.delete(
                    f"{self.server_url}/memories/{memory_id}",
                    headers={"X-AMP-Agent-ID": self.agent_id}
                )
            except httpx.HTTPError as exc:
                raise AMPError(f"HTTP request failed: {exc}") from exc

        if not (200 <= resp.status_code < 300):
            self._raise_amp_error(resp)
        return True

    async def list_memories(
        self,
        owner_id: str,
        type: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        params = {
            "owner_id": owner_id,
            "limit": limit,
        }
        if type is not None:
            params["type"] = type

        async with self._get_client() as client:
            try:
                resp = await client.get(
                    f"{self.server_url}/memories",
                    params=params,
                    headers={"X-AMP-Agent-ID": self.agent_id}
                )
            except httpx.HTTPError as exc:
                raise AMPError(f"HTTP request failed: {exc}") from exc

        if not (200 <= resp.status_code < 300):
            self._raise_amp_error(resp)
        return resp.json().get("results", [])

    async def health(self) -> bool:
        try:
            async with self._get_client() as client:
                resp = await client.get(f"{self.server_url}/health")
                if resp.status_code == 200:
                    data = resp.json()
                    return data.get("status") == "ok"
        except Exception:
            pass
        return False
