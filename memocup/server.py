"""Local HTTP API server with bearer authentication and strict request limits."""

from __future__ import annotations

import hmac
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse, unquote

from .context import build_memory_context
from .store import MemoryStore

LOGGER = logging.getLogger("memocup.server")
MAX_BODY_BYTES = 1_000_000


def create_handler(store: MemoryStore, api_key: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "MemoCup/0.1"
        sys_version = ""

        def log_message(self, fmt: str, *args: Any) -> None:
            LOGGER.info("%s - %s", self.address_string(), fmt % args)

        def _send(self, status: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            supplied = self.headers.get("Authorization", "")
            prefix = "Bearer "
            if not supplied.startswith(prefix):
                self._send(401, {"error": "unauthorized", "message": "A valid Bearer token is required."})
                return False
            token = supplied[len(prefix):]
            if not hmac.compare_digest(token.encode("utf-8"), api_key.encode("utf-8")):
                self._send(401, {"error": "unauthorized", "message": "A valid Bearer token is required."})
                return False
            return True

        def _body(self) -> dict[str, Any] | None:
            raw_length = self.headers.get("Content-Length")
            try:
                length = int(raw_length or "0")
            except ValueError:
                self._send(400, {"error": "invalid_content_length"})
                return None
            if length < 0 or length > MAX_BODY_BYTES:
                self._send(413, {"error": "payload_too_large", "max_bytes": MAX_BODY_BYTES})
                return None
            if self.headers.get_content_type() != "application/json":
                self._send(415, {"error": "content_type_must_be_application_json"})
                return None
            try:
                value = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(value, dict):
                    raise ValueError("JSON body must be an object.")
                return value
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
                self._send(400, {"error": "invalid_json", "message": str(exc)[:300]})
                return None

        def do_GET(self) -> None:  # noqa: N802
            path = urlparse(self.path).path
            if path == "/health":
                self._send(200, {"ok": True, "service": "memocup", "version": "0.1.0"})
                return
            if not self._authorized():
                return
            if path == "/v1/memories":
                from urllib.parse import parse_qs
                params = parse_qs(urlparse(self.path).query)
                try:
                    items = store.list_memories(
                        limit=int(params.get("limit", [100])[0]),
                        status=params.get("status", ["active"])[0],
                        category=params.get("category", [None])[0],
                        scope=params.get("scope", [None])[0],
                    )
                    self._send(200, {"memories": items})
                except ValueError as exc:
                    self._send(400, {"error": "invalid_request", "message": str(exc)})
                return
            self._send(404, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorized():
                return
            payload = self._body()
            if payload is None:
                return
            path = urlparse(self.path).path
            try:
                if path == "/v1/memories":
                    result = store.remember(
                        payload.get("content", ""),
                        category=payload.get("category", "note"),
                        scope=payload.get("scope", "project"),
                        tags=payload.get("tags", []),
                        source=payload.get("source", "unspecified"),
                        source_ref=payload.get("source_ref"),
                        confidence=payload.get("confidence", 0.5),
                        importance=payload.get("importance", 3),
                        metadata=payload.get("metadata", {}),
                        supersedes_id=payload.get("supersedes_id"),
                        expires_at=payload.get("expires_at"),
                    )
                    self._send(201, {"memory": result})
                    return
                if path == "/v1/recall":
                    items = store.recall(
                        payload.get("query", ""),
                        limit=payload.get("limit", 8),
                        categories=payload.get("categories") or None,
                        scopes=payload.get("scopes") or ["project", "user"],
                    )
                    self._send(200, {"memories": items})
                    return
                if path == "/v1/context":
                    items = store.recall(
                        payload.get("query", ""),
                        limit=payload.get("limit", 8),
                        categories=payload.get("categories") or None,
                        scopes=payload.get("scopes") or ["project", "user"],
                    )
                    context = build_memory_context(items, max_chars=int(payload.get("max_chars", 12000)))
                    self._send(200, {"context": context, "memory_ids": [item["id"] for item in items]})
                    return
                self._send(404, {"error": "not_found"})
            except (TypeError, ValueError, KeyError) as exc:
                self._send(400, {"error": "invalid_request", "message": str(exc)[:500]})

        def do_DELETE(self) -> None:  # noqa: N802
            if not self._authorized():
                return
            path = urlparse(self.path).path
            prefix = "/v1/memories/"
            if path.startswith(prefix):
                memory_id = unquote(path[len(prefix):])
                if not memory_id or "/" in memory_id:
                    self._send(400, {"error": "invalid_memory_id"})
                    return
                changed = store.forget(memory_id)
                self._send(200, {"forgotten": changed, "id": memory_id})
                return
            self._send(404, {"error": "not_found"})

    return Handler


def serve(store: MemoryStore, *, host: str, port: int, api_key: str) -> None:
    if host not in {"127.0.0.1", "localhost"}:
        raise ValueError("Memo Cup binds to localhost by default. Remote binding is intentionally disabled in this release.")
    server = ThreadingHTTPServer((host, port), create_handler(store, api_key))
    server.daemon_threads = True
    print(f"Memo Cup API listening on http://{host}:{port}")
    print("Press Ctrl+C to stop. The API key is read from .memocup/config.json.")
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        print("\nShutting down Memo Cup...")
    finally:
        server.server_close()
