# Memo Cup API Reference

Base URL: `http://127.0.0.1:8765`

Except for `GET /health`, every endpoint requires:

```http
Authorization: Bearer <api_key>
Content-Type: application/json
```

## GET /health

Unauthenticated liveness check.

Response:

```json
{"ok": true, "service": "memocup", "version": "0.1.0"}
```

## POST /v1/memories

Create or deduplicate a memory.

Request:

```json
{
  "content": "The production database is PostgreSQL.",
  "category": "decision",
  "scope": "project",
  "tags": ["database", "production"],
  "source": "user",
  "source_ref": "discussion/42",
  "confidence": 1.0,
  "importance": 5,
  "metadata": {},
  "supersedes_id": null,
  "expires_at": null
}
```

Fields:

| Field | Type | Default | Description |
|---|---|---|---|
| `content` | string | required | Non-empty memory text; maximum 100,000 characters. |
| `category` | string | `note` | One of the documented memory categories. |
| `scope` | string | `project` | `project` or `user`. |
| `tags` | string array | `[]` | Up to 30 tags. |
| `source` | string | `unspecified` | Provenance label. |
| `source_ref` | string/null | `null` | Optional provenance pointer. |
| `confidence` | number | `0.5` | Range 0..1. |
| `importance` | integer | `3` | Range 1..5. |
| `metadata` | object | `{}` | Additional structured metadata. |
| `supersedes_id` | string/null | `null` | Active memory explicitly replaced by this one. |
| `expires_at` | ISO datetime/null | `null` | Optional expiry timestamp. |

Response: `201 Created` with `{ "memory": { ... } }`.

Identical normalized content in the same project and scope is deduplicated. The existing record is reused and its tags/importance/confidence may be increased. A different statement is never silently treated as a replacement: set `supersedes_id` explicitly.

## POST /v1/recall

Request:

```json
{
  "query": "production database choice",
  "limit": 8,
  "categories": ["decision", "fact"],
  "scopes": ["project", "user"]
}
```

- `limit`: 1..50.
- `categories`: optional array of valid categories.
- `scopes`: optional array; defaults to project and user.

Response: `{ "memories": [ ... ] }`. Results include a computed `score`; score is retrieval ranking, not factual confidence.

## POST /v1/context

Request:

```json
{
  "query": "production database choice",
  "limit": 8,
  "max_chars": 12000
}
```

Response:

```json
{
  "context": "MEMO CUP — RETRIEVED MEMORY DATA ...",
  "memory_ids": ["mem_..."]
}
```

The context labels memory as untrusted reference data and tells the model not to follow instructions embedded in records, to disclose conflicts, and not to invent missing history. This is prompt guidance, not a hard security boundary inside the model.

## GET /v1/memories

Optional query parameters:

- `limit`: 1..1000, default 100.
- `status`: `active`, `superseded`, `archived`, or `forgotten`; default `active`.
- `category`: one valid category.
- `scope`: `project` or `user`.

Response: `{ "memories": [ ... ] }`.

## DELETE /v1/memories/{id}

Soft-deletes a memory by setting its status to `forgotten`.

Response: `{ "forgotten": true, "id": "mem_..." }`.

## Status codes

| Status | Meaning |
|---|---|
| 200 | Successful read, recall, context, or delete request. |
| 201 | Memory created or deduplicated. |
| 400 | Invalid JSON or invalid request data. |
| 401 | Missing or invalid bearer token. |
| 404 | Unknown endpoint. |
| 413 | Request body exceeds 1 MB. |
| 415 | Request content type is not application/json. |

## MCP tools

The stdio server exposes the same core operations as tools: `remember_memory`, `recall_memories`, `get_memory_context`, `list_memories`, and `forget_memory`. It uses newline-delimited JSON-RPC messages and the MCP 2025-11-25 initialize handshake. Clients that only support the newer stateless protocol without legacy fallback are not supported by this release; use the HTTP API/SDK with those clients.
