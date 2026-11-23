# Security Policy

## Supported versions

Security fixes are intended for the latest released version of Memo Cup.

## Reporting a vulnerability

Please do not publish exploitable security details in a public issue. Contact the repository maintainers privately through the security contact configured on the GitHub repository.

## Current security model

- The HTTP API binds to loopback addresses only.
- All API routes except `/health` require a constant-time-checked bearer token.
- The API does not enable CORS.
- Request bodies are limited to 1 MB.
- SQLite statements use parameters; stored memory text is never executed.
- API credentials and the local database are excluded by the generated `.memocup/.gitignore`.
- MCP runs as a local child process over stdio and writes protocol data only to stdout.

## Known limitations

- Memory records and the local API key are stored unencrypted on disk. Use OS disk encryption and filesystem permissions appropriate to your threat model.
- A process running as the same OS user can generally read the local memory database and configuration.
- Memo Cup is not designed to be exposed directly to the public internet.
- Retrieved memory may be stale, incomplete, wrong, or adversarially crafted. Treat it as untrusted data and verify it against primary sources.
