"""Dependency-free HTTP client for the Memo Cup local API."""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable

from .context import build_memory_context


class MemoCupClient:
    """Client for a running Memo Cup server.

    Example:
        memory = MemoCupClient("http://127.0.0.1:8765", api_key="...")
        matches = memory.recall("preferred deployment platform")
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8765", *, api_key: str, timeout: float = 10):
        if not api_key:
            raise ValueError("api_key is required.")
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout

    def _request(self, path: str, *, method: str = "GET", payload: dict[str, Any] | None = None) -> Any:
        body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Accept": "application/json",
                **({"Content-Type": "application/json; charset=utf-8"} if body is not None else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read(2_000_001)
                if len(raw) > 2_000_000:
                    raise RuntimeError("Memo Cup API response exceeded the 2 MB client limit.")
                return json.loads(raw.decode("utf-8")) if raw else None
        except urllib.error.HTTPError as exc:
            detail = exc.read(4000).decode("utf-8", errors="replace")
            raise RuntimeError(f"Memo Cup API returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ConnectionError(f"Could not connect to Memo Cup at {self.base_url}: {exc.reason}") from exc

    def health(self) -> dict[str, Any]:
        return self._request("/health")

    def remember(self, content: str, **options: Any) -> dict[str, Any]:
        result = self._request("/v1/memories", method="POST", payload={"content": content, **options})
        return result["memory"]

    def recall(
        self,
        query: str,
        *,
        limit: int = 8,
        categories: Iterable[str] | None = None,
        scopes: Iterable[str] | None = None,
    ) -> list[dict[str, Any]]:
        result = self._request(
            "/v1/recall",
            method="POST",
            payload={
                "query": query,
                "limit": limit,
                "categories": list(categories or []),
                "scopes": list(scopes or ["project", "user"]),
            },
        )
        return result["memories"]

    def context(self, query: str, *, limit: int = 8, max_chars: int = 12000) -> str:
        result = self._request(
            "/v1/context", method="POST",
            payload={"query": query, "limit": limit, "max_chars": max_chars},
        )
        return result["context"]

    def prepare_messages(
        self,
        messages: list[dict[str, Any]],
        *,
        query: str | None = None,
        max_chars: int = 12000,
        limit: int = 8,
        system_role: str = "system",
    ) -> list[dict[str, Any]]:
        """Return a new messages list with retrieved memory inserted as a system message.

        The caller remains responsible for saving useful new facts after the model turn.
        This helper never mutates the input list.
        """
        search_query = query or _last_user_text(messages)
        memory_context = self.context(search_query, limit=limit, max_chars=max_chars)
        prepared = [dict(item) for item in messages]
        for index, message in enumerate(prepared):
            if message.get("role") == system_role and isinstance(message.get("content"), str):
                prepared[index]["content"] = message["content"] + "\n\n" + memory_context
                return prepared
        return [{"role": system_role, "content": memory_context}, *prepared]

    def forget(self, memory_id: str) -> bool:
        result = self._request(f"/v1/memories/{urllib.parse.quote(memory_id, safe='')}", method="DELETE")
        return bool(result.get("forgotten"))


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                return " ".join(str(part.get("text", "")) for part in content if isinstance(part, dict))
    return ""
