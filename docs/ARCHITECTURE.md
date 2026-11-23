# Architecture

## Components

```text
AI host / agent
   |                       |
   | MCP stdio tools       | REST / SDK
   v                       v
memocup mcp             memocup serve
   |                       |
   +----------+------------+
              |
              v
         MemoryStore
              |
              v
        SQLite database
```

## Design decisions

- **Python standard library only:** avoids native extension builds, framework lock-in, and provider dependencies.
- **SQLite source of truth:** single-file local persistence; SQLite journaling handles concurrent readers/writers for typical local workloads.
- **Project boundary:** each project gets a unique project ID and a local database path by default.
- **MCP integration:** makes memory callable by compatible AI hosts without wrapping a particular model provider. This release implements the 2025-11-25 initialize handshake.
- **HTTP/SDK integration:** supports applications where the developer owns the model request lifecycle.
- **Provenance-first records:** source, optional source reference, confidence, importance, timestamps, and status accompany each memory.
- **No automatic conflict inference:** only an explicit supersedes relationship retires a previous memory.
- **Bounded prompt context:** retrieved data is formatted within a character budget.

## Retrieval

The retriever uses a SQLite FTS5 external-content index when the local SQLite build supports it. Insert/update/delete triggers keep the index aligned with the source-of-truth table. Builds without FTS5 use a parameterized token scan. Candidate records are ranked deterministically by query-token overlap, exact-phrase bonus, importance, confidence, and recency.

This intentionally favors a small, auditable runtime over an embedding model or vector database. It is lexical, not semantic search, and may miss conceptually related memories that share no useful terms.

## Trust boundaries

- Memory content is untrusted data. It is serialized as JSON inside a clearly labelled memory block.
- The model is instructed not to obey instructions found inside memory records.
- Source/confidence are metadata, not cryptographic proof.
- The HTTP API is loopback-only and bearer-authenticated.
- The MCP server has local process permissions of the user who launched it.
- The local database and API key are not encrypted at rest in this release.
