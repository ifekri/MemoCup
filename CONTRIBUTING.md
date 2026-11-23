# Contributing

Contributions are welcome. Please keep the runtime dependency-free unless a dependency is essential and its operational/security trade-offs are documented.

## Development setup

```bash
python -m pip install --no-build-isolation --no-deps -e .
python -m unittest discover -s tests -v
node --check sdks/javascript/index.mjs
```

## Engineering expectations

- Keep user application source files untouched by the `init` workflow.
- Never log memory content, API keys, or request bodies.
- Preserve existing user configuration during initialization; never silently replace conflicting settings.
- Treat all stored content as untrusted data.
- Use parameterized SQL and validate all untrusted input.
- Add tests for new storage, API, MCP, or CLI behavior.
- Keep all source code and code comments in English. User-facing documentation may be localized.
