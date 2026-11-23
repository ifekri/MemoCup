"""Project configuration and safe filesystem helpers."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from pathlib import Path
from typing import Any

CONFIG_DIR = ".memocup"
CONFIG_FILE = "config.json"
CONFIG_VERSION = 1


def project_root(start: str | Path | None = None) -> Path:
    """Find the nearest Memo Cup project root, otherwise use the given directory."""
    candidate = Path(start or Path.cwd()).expanduser().resolve()
    if candidate.is_file():
        candidate = candidate.parent
    for parent in (candidate, *candidate.parents):
        if (parent / CONFIG_DIR / CONFIG_FILE).is_file():
            return parent
    return candidate


def make_project_id(root: Path) -> str:
    """Create a stable, non-secret identifier for this project location."""
    digest = hashlib.sha256(str(root.resolve()).encode("utf-8")).hexdigest()[:20]
    return f"proj_{digest}"


def default_config(root: Path) -> dict[str, Any]:
    return {
        "config_version": CONFIG_VERSION,
        "project_id": make_project_id(root),
        "project_name": root.name or "project",
        "storage": {"database": ".memocup/data/memories.sqlite3"},
        "api": {"host": "127.0.0.1", "port": 8765, "api_key": secrets.token_urlsafe(32)},
        "retrieval": {"default_limit": 8, "max_context_chars": 12000},
        "privacy": {"store_assistant_turns": False, "allow_remote_api": False},
    }


def config_path(root: Path) -> Path:
    return root / CONFIG_DIR / CONFIG_FILE


def load_config(root: str | Path | None = None) -> tuple[Path, dict[str, Any]]:
    resolved = project_root(root)
    path = config_path(resolved)
    if not path.is_file():
        raise FileNotFoundError(
            f"Memo Cup is not initialized in {resolved}. Run `memocup init` first."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("config_version") != CONFIG_VERSION:
        raise ValueError(
            f"Unsupported Memo Cup config version: {data.get('config_version')!r}. "
            "Back up .memocup and run the upgrade command when available."
        )
    return resolved, data


def database_path(root: Path, config: dict[str, Any]) -> Path:
    configured = Path(config["storage"]["database"])
    return configured if configured.is_absolute() else (root / configured).resolve()


def write_private_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        os.chmod(temporary, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    temporary.replace(path)
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def redact_config(config: dict[str, Any]) -> dict[str, Any]:
    safe = json.loads(json.dumps(config))
    if safe.get("api", {}).get("api_key"):
        safe["api"]["api_key"] = "[REDACTED]"
    return safe
