# Memo Cup

**A local-first, model-agnostic persistent memory layer for AI applications.**

Memo Cup gives AI agents a durable memory store without requiring changes to an application's source code. It provides a SQLite-backed store, an MCP server, a small authenticated HTTP API, and dependency-free Python and JavaScript clients.

> **Important:** Memo Cup cannot make an AI model infallible, guarantee that it remembers every detail, or eliminate hallucinations. It makes durable information available to the model and supplies an explicit retrieval-and-provenance workflow. The model or application must actually call the memory tools or SDK.

## Install in an existing project

Install `uv` first if it is not already available (`python -m pip install --user uv`). Then run this single command from the project root:

```bash
uvx --from git+https://github.com/ifekri/MemoCup memocup init
```

The command is designed to be idempotent and safe to run in the middle of an existing project. It creates `.memocup/`, initializes a local SQLite database, writes `MEMOCUP.md`, and adds a managed Memo Cup section to `AGENTS.md` (plus supported agent instruction files that already exist). It also safely merges a project-level MCP entry into `.mcp.json` and `.cursor/mcp.json`, preserving other configured servers. Existing files with invalid JSON or a conflicting `memocup` entry are left untouched and reported.

It does **not** rewrite application source files, install dependencies into the application environment, or replace existing project configuration. Use `--no-agent-rules` to skip instruction-file changes:

```bash
uvx --from git+https://github.com/ifekri/MemoCup memocup init --no-agent-rules
```

## Connect an AI client

Memo Cup exposes an MCP stdio server. After `init`, Claude Code can load the generated root `.mcp.json`; Cursor uses `.cursor/mcp.json`. VS Code Copilot can use the workspace-root `.mcp.json` when its workspace-root MCP setting is enabled. The command uses `uvx` to run Memo Cup without installing it into the application environment. Reload the host and approve the local server when prompted. For other clients, copy the `mcpServers.memocup` entry from `.memocup/mcp-config.json` into their MCP configuration.

Available MCP tools:

| Tool | Purpose |
|---|---|
| `recall_memories` | Search relevant stored memories. |
| `remember_memory` | Save a durable fact, preference, decision, constraint, correction, or procedure. |
| `get_memory_context` | Return bounded, provenance-aware context for a model prompt. |
| `list_memories` | Review active memories. |
| `forget_memory` | Soft-delete a memory when the user asks. |

MCP support depends on the AI client. A model endpoint by itself does not automatically gain access to MCP; the host application must connect the server and expose its tools to the model. This release implements the MCP `2025-11-25` initialize flow; clients that only support the newer stateless protocol without legacy fallback should use the HTTP/SDK integration until Memo Cup adds that transport version.

## Direct API mode

Run the local HTTP API from the project root:

```bash
uvx --from git+https://github.com/ifekri/MemoCup memocup serve
```

The server binds to `127.0.0.1` by default. All API routes except `/health` require the bearer token stored in `.memocup/config.json`. The generated `.memocup/.gitignore` excludes the private config, absolute-path MCP snippet, and database files.

### Python

Install Memo Cup into the Python environment used by your application:

```bash
python -m pip install git+https://github.com/ifekri/MemoCup
```

Then use the SDK:

```python
import json
from pathlib import Path
from memocup import MemoCupClient

config = json.loads(Path(".memocup/config.json").read_text(encoding="utf-8"))
memory = MemoCupClient(
    f"http://{config['api']['host']}:{config['api']['port']}",
    api_key=config["api"]["api_key"],
)

messages = [
    {"role": "system", "content": "You are a careful assistant."},
    {"role": "user", "content": "Which architecture decision did we make?"},
]
messages = memory.prepare_messages(messages)
# Send `messages` to your provider of choice.

memory.remember(
    "The service uses a modular monolith architecture.",
    category="decision",
    source="user",
    confidence=1.0,
    importance=5,
)
```

### JavaScript / TypeScript

The dependency-free JavaScript client is in `sdks/javascript/index.mjs`:

```javascript
import { MemoCupClient } from "./sdks/javascript/index.mjs";

const memory = new MemoCupClient({
  baseUrl: "http://127.0.0.1:8765",
  apiKey: process.env.MEMOCUP_API_KEY,
});

const messages = await memory.prepareMessages([
  { role: "system", content: "You are a careful assistant." },
  { role: "user", content: "What did we decide about the database?" },
]);
// Send `messages` to your provider of choice.

await memory.remember("The production database is PostgreSQL.", {
  category: "decision",
  source: "user",
  confidence: 1,
  importance: 5,
});
```

For API mode, set `MEMOCUP_API_KEY` to the `api.api_key` value in `.memocup/config.json` and start the server. Do not commit that key.

## CLI

```bash
memocup status
memocup doctor
memocup list --limit 50
memocup forget mem_...
memocup export --output ./memocup-backup.json
memocup import --input ./memocup-backup.json
```

When using `uvx` without installing the CLI into the current environment, prefix commands with:

```bash
uvx --from git+https://github.com/ifekri/MemoCup memocup <command>
```

## Memory model

Each record stores:

- A stable memory ID, project ID, scope, category, and plain-text content.
- Tags, provenance (`source` and optional `source_ref`), confidence, and importance.
- Creation/update/access timestamps and optional expiry.
- Lifecycle status (`active`, `superseded`, `archived`, `forgotten`).
- Optional metadata and an explicit link to the memory it supersedes.

Supported categories: `fact`, `preference`, `decision`, `constraint`, `task`, `entity`, `procedure`, `correction`, `conversation`, and `note`.

Supported scopes: `project` and `user`. The default install creates a database per project, so both scopes remain inside that project's database. To share user-scoped memories between projects, configure those projects to use the same trusted database path; do not share a database across untrusted users.

Retrieval uses SQLite FTS5 when the local SQLite build provides it, with a parameterized token-scan fallback when FTS5 is unavailable. Results are deterministically ranked with importance, confidence, and recency weighting. It does not require an embedding provider, vector database, hosted service, or API key for an LLM. This is lexical retrieval, not semantic/vector search, so conceptually related memories with no shared terms may be missed.

## Design and safety guarantees

- **Source-safe initialization:** generated files are added beside the application, not inside its source modules.
- **Local-first storage:** SQLite is the source of truth.
- **No external runtime dependencies:** the Python server, CLI, store, and SDK use the standard library.
- **Local-only HTTP listener:** remote binding is rejected in this release.
- **Bearer authentication:** required for all memory API endpoints.
- **Bounded request/context sizes:** HTTP request body limit is 1 MB; model context has a configurable character budget.
- **Provenance-aware recall:** a retrieved item includes its source, confidence, and memory ID.
- **No silent conflict resolution:** an explicit `supersedes_id` is required to replace an active record.
- **Soft deletion:** `forget` changes the status rather than immediately erasing the row.
- **Untrusted-memory boundary:** retrieved memory is labelled as reference data, never as executable instructions.

## Limitations

Memo Cup is a memory layer, not a new model, inference engine, or truth-verification system.

1. It cannot force every model or host application to use memory. The MCP host must connect and expose the tools, or the application must use the SDK.
2. It cannot guarantee that every conversational detail is saved. Applications should call `remember_memory` / `remember()` after meaningful events or decisions.
3. It cannot guarantee zero hallucinations or eliminate incorrect user-provided information. Provenance and confidence make uncertainty visible; source verification is still required.
4. The first release uses lexical retrieval (SQLite FTS5 where available), not embeddings. Exact names, distinctive terms, and tags improve recall.
5. Data and the API key are stored unencrypted on disk. Use appropriate OS account and disk protections.
6. Memory is project-local by default. It is not a cloud-synchronized cross-device memory service.

## Development

```bash
python -m pip install --no-deps -e .
python -m unittest discover -s tests -v
memocup --help
```

Python 3.10 or later is required. Runtime dependencies: none.

## License

MIT. See [LICENSE](LICENSE).
