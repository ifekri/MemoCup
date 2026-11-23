"""SQLite-backed memory storage and deterministic retrieval."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import stat
import uuid
from datetime import datetime, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

VALID_CATEGORIES = {
    "fact", "preference", "decision", "constraint", "task", "entity",
    "procedure", "correction", "conversation", "note",
}
VALID_SCOPES = {"project", "user"}
VALID_STATUSES = {"active", "superseded", "archived", "forgotten"}
TOKEN_RE = re.compile(r"[\w-]{2,}", re.UNICODE)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _normalise(value: str) -> str:
    return " ".join(value.casefold().split())


def _tokens(value: str) -> set[str]:
    return {token for token in TOKEN_RE.findall(value.casefold()) if len(token) > 1}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class MemoryStore:
    """A project-isolated memory store.

    SQLite is used as the source of truth. Retrieved content is data, never trusted
    instructions. The store does not infer facts or silently resolve contradictions.
    """

    def __init__(self, database: str | Path, project_id: str):
        self.database = Path(database).expanduser().resolve()
        self.project_id = project_id
        self._fts_available = False
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._initialise()
        try:
            self.database.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.database), timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialise(self) -> None:
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute("PRAGMA synchronous = NORMAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    scope TEXT NOT NULL CHECK(scope IN ('project', 'user')),
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    source TEXT NOT NULL DEFAULT 'unspecified',
                    source_ref TEXT,
                    confidence REAL NOT NULL DEFAULT 0.5 CHECK(confidence >= 0 AND confidence <= 1),
                    importance INTEGER NOT NULL DEFAULT 3 CHECK(importance >= 1 AND importance <= 5),
                    status TEXT NOT NULL DEFAULT 'active',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    supersedes_id TEXT,
                    superseded_by TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_accessed_at TEXT,
                    expires_at TEXT,
                    FOREIGN KEY(supersedes_id) REFERENCES memories(id),
                    FOREIGN KEY(superseded_by) REFERENCES memories(id)
                );
                CREATE INDEX IF NOT EXISTS idx_memories_project_status
                    ON memories(project_id, status, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_memories_scope
                    ON memories(project_id, scope, status);
                CREATE INDEX IF NOT EXISTS idx_memories_category
                    ON memories(project_id, category, status);
                CREATE INDEX IF NOT EXISTS idx_memories_hash
                    ON memories(project_id, scope, content_hash);
                CREATE TABLE IF NOT EXISTS schema_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT OR REPLACE INTO schema_meta(key, value) VALUES('schema_version', '1');
                """
            )
            try:
                fts_exists = connection.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='memories_fts'"
                ).fetchone() is not None
                connection.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts "
                    "USING fts5(content, tags_json, content='memories', content_rowid='rowid')"
                )
                connection.executescript(
                    """
                    CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                        INSERT INTO memories_fts(rowid, content, tags_json)
                        VALUES (new.rowid, new.content, new.tags_json);
                    END;
                    CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, content, tags_json)
                        VALUES ('delete', old.rowid, old.content, old.tags_json);
                    END;
                    CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE OF content, tags_json ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, content, tags_json)
                        VALUES ('delete', old.rowid, old.content, old.tags_json);
                        INSERT INTO memories_fts(rowid, content, tags_json)
                        VALUES (new.rowid, new.content, new.tags_json);
                    END;
                    """
                )
                if not fts_exists:
                    connection.execute("INSERT INTO memories_fts(memories_fts) VALUES('rebuild')")
                self._fts_available = True
            except sqlite3.OperationalError:
                # Some SQLite builds omit FTS5. Recall falls back to a parameterized local scan.
                self._fts_available = False

    def remember(
        self,
        content: str,
        *,
        category: str = "note",
        scope: str = "project",
        tags: Iterable[str] | None = None,
        source: str = "unspecified",
        source_ref: str | None = None,
        confidence: float = 0.5,
        importance: int = 3,
        metadata: dict[str, Any] | None = None,
        supersedes_id: str | None = None,
        expires_at: str | None = None,
    ) -> dict[str, Any]:
        if not isinstance(content, str) or not content.strip():
            raise ValueError("Memory content must be a non-empty string.")
        content = content.strip()
        if len(content) > 100_000:
            raise ValueError("Memory content exceeds the 100,000 character limit.")
        if not isinstance(category, str) or category not in VALID_CATEGORIES:
            raise ValueError(f"Invalid category. Choose one of: {', '.join(sorted(VALID_CATEGORIES))}.")
        if not isinstance(scope, str) or scope not in VALID_SCOPES:
            raise ValueError(f"Invalid scope. Choose one of: {', '.join(sorted(VALID_SCOPES))}.")
        if isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
            raise ValueError("confidence must be a number between 0 and 1.")
        if isinstance(importance, bool) or not isinstance(importance, int) or not 1 <= importance <= 5:
            raise ValueError("importance must be an integer between 1 and 5.")
        if tags is None:
            tags = []
        if isinstance(tags, (str, bytes)) or not isinstance(tags, Iterable):
            raise ValueError("tags must be an iterable of strings.")
        tags = list(tags)
        if not all(isinstance(tag, str) for tag in tags):
            raise ValueError("Every tag must be a string.")
        clean_tags = sorted({tag.strip()[:64] for tag in tags if tag.strip()})[:30]
        if not isinstance(source, str) or not source.strip():
            raise ValueError("source must be a non-empty string.")
        if source_ref is not None and not isinstance(source_ref, str):
            raise ValueError("source_ref must be a string or null.")
        if supersedes_id is not None and not isinstance(supersedes_id, str):
            raise ValueError("supersedes_id must be a string or null.")
        if metadata is not None and not isinstance(metadata, dict):
            raise ValueError("metadata must be an object.")
        if expires_at is not None:
            if not isinstance(expires_at, str):
                raise ValueError("expires_at must be an ISO datetime string or null.")
            try:
                expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError("expires_at must be a valid ISO datetime.") from exc
            if expiry.tzinfo is None:
                raise ValueError("expires_at must include a timezone offset.")
            expires_at = expiry.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        digest = hashlib.sha256(_normalise(content).encode("utf-8")).hexdigest()
        now = utc_now()
        memory_id = f"mem_{uuid.uuid4().hex}"

        with self._connection() as connection:
            existing = connection.execute(
                """SELECT * FROM memories WHERE project_id=? AND scope=? AND category=? AND content_hash=?
                   AND status='active' ORDER BY created_at DESC LIMIT 1""",
                (self.project_id, scope, category, digest),
            ).fetchone()
            if existing:
                merged_tags = sorted(set(json.loads(existing["tags_json"])) | set(clean_tags))[:30]
                connection.execute(
                    """UPDATE memories SET tags_json=?, importance=MAX(importance, ?),
                       confidence=MAX(confidence, ?), updated_at=? WHERE id=?""",
                    (_json(merged_tags), importance, float(confidence), now, existing["id"]),
                )
                duplicate_id = existing["id"]
            else:
                duplicate_id = None

            if duplicate_id is not None:
                pass
            elif supersedes_id:
                previous = connection.execute(
                    "SELECT id, project_id, status FROM memories WHERE id=?",
                    (supersedes_id,),
                ).fetchone()
                if not previous or previous["project_id"] != self.project_id:
                    raise ValueError("supersedes_id must identify a memory in this project.")
                if previous["status"] != "active":
                    raise ValueError("Only an active memory can be superseded.")

            if duplicate_id is None:
                connection.execute(
                    """INSERT INTO memories (
                        id, project_id, scope, category, content, content_hash, tags_json,
                        source, source_ref, confidence, importance, status, metadata_json,
                        supersedes_id, created_at, updated_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?)""",
                    (
                        memory_id, self.project_id, scope, category, content, digest,
                        _json(clean_tags), str(source)[:128], source_ref, float(confidence),
                        importance, _json(metadata or {}), supersedes_id, now, now, expires_at,
                    ),
                )
                if supersedes_id:
                    connection.execute(
                        "UPDATE memories SET status='superseded', superseded_by=?, updated_at=? WHERE id=?",
                        (memory_id, now, supersedes_id),
                    )
        return self.get(duplicate_id or memory_id) or {}

    def get(self, memory_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM memories WHERE id=? AND project_id=?",
                (memory_id, self.project_id),
            ).fetchone()
        return self._decode(row) if row else None

    @staticmethod
    def _decode(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["tags"] = json.loads(value.pop("tags_json"))
        value["metadata"] = json.loads(value.pop("metadata_json"))
        return value

    def recall(
        self,
        query: str,
        *,
        limit: int = 8,
        categories: Iterable[str] | None = None,
        scopes: Iterable[str] | None = None,
        include_superseded: bool = False,
    ) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            raise ValueError("limit must be an integer between 1 and 50.")
        if query is None:
            query = ""
        if not isinstance(query, str):
            raise ValueError("query must be a string.")
        query = query.strip()
        query_tokens = _tokens(query)
        if categories is not None and (isinstance(categories, (str, bytes)) or not isinstance(categories, Iterable)):
            raise ValueError("categories must be an iterable of category names.")
        if scopes is not None and (isinstance(scopes, (str, bytes)) or not isinstance(scopes, Iterable)):
            raise ValueError("scopes must be an iterable of scope names.")
        categories = list(categories or [])
        scopes = list(scopes or ["project", "user"])
        if not all(isinstance(item, str) for item in categories + scopes):
            raise ValueError("categories and scopes must contain only strings.")
        allowed_categories = set(categories)
        allowed_scopes = set(scopes)
        if allowed_categories - VALID_CATEGORIES:
            raise ValueError("One or more categories are invalid.")
        if allowed_scopes - VALID_SCOPES:
            raise ValueError("One or more scopes are invalid.")

        clauses = ["m.project_id=?", "m.scope IN (" + ",".join("?" for _ in allowed_scopes) + ")"]
        params: list[Any] = [self.project_id, *sorted(allowed_scopes)]
        statuses = ["active", "superseded"] if include_superseded else ["active"]
        clauses.append("m.status IN (" + ",".join("?" for _ in statuses) + ")")
        params.extend(statuses)
        clauses.append("(m.expires_at IS NULL OR m.expires_at > ?)")
        params.append(utc_now())
        if allowed_categories:
            clauses.append("m.category IN (" + ",".join("?" for _ in allowed_categories) + ")")
            params.extend(sorted(allowed_categories))

        join_sql = ""
        if query_tokens:
            if self._fts_available:
                join_sql = " JOIN memories_fts ON memories_fts.rowid=m.rowid"
                fts_query = " OR ".join('"' + token.replace('"', '""') + '"' for token in sorted(query_tokens))
                clauses.append("memories_fts MATCH ?")
                params.append(fts_query)
            else:
                token_conditions = []
                for token in sorted(query_tokens):
                    token_conditions.append("(instr(lower(m.content), lower(?)) > 0 OR instr(lower(m.tags_json), lower(?)) > 0)")
                    params.extend((token, token))
                clauses.append("(" + " OR ".join(token_conditions) + ")")

        sql = "SELECT m.* FROM memories AS m" + join_sql + " WHERE " + " AND ".join(clauses)
        if not query_tokens:
            sql += " ORDER BY m.created_at DESC LIMIT 2000"
        with self._connection() as connection:
            rows = connection.execute(sql, params).fetchall()

        now = datetime.now(timezone.utc)
        ranked: list[tuple[float, dict[str, Any]]] = []
        for row in rows:
            item = self._decode(row)
            content_tokens = _tokens(item["content"] + " " + " ".join(item["tags"]))
            if query_tokens:
                overlap = len(query_tokens & content_tokens) / max(len(query_tokens), 1)
                phrase_bonus = 0.35 if _normalise(query) in _normalise(item["content"]) else 0.0
                if overlap == 0 and phrase_bonus == 0:
                    continue
                relevance = overlap + phrase_bonus
            else:
                relevance = 0.0
            try:
                created = datetime.fromisoformat(item["created_at"].replace("Z", "+00:00"))
                age_days = max((now - created).total_seconds() / 86400, 0)
            except ValueError:
                age_days = 365
            recency = 1 / (1 + age_days / 45)
            importance = item["importance"] / 5
            confidence = item["confidence"]
            score = relevance * 3.0 + importance * 0.55 + recency * 0.25 + confidence * 0.2
            item["score"] = round(score, 4)
            ranked.append((score, item))

        ranked.sort(key=lambda pair: (pair[0], pair[1]["created_at"]), reverse=True)
        results = [item for _, item in ranked[:limit]]
        if results:
            accessed_at = utc_now()
            with self._connection() as connection:
                connection.executemany(
                    "UPDATE memories SET last_accessed_at=? WHERE id=?",
                    [(accessed_at, item["id"]) for item in results],
                )
            for item in results:
                item["last_accessed_at"] = accessed_at
        return results

    def list_memories(
        self,
        *,
        limit: int = 100,
        status: str = "active",
        category: str | None = None,
        scope: str | None = None,
    ) -> list[dict[str, Any]]:
        if status not in VALID_STATUSES:
            raise ValueError("Invalid status.")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError("limit must be an integer between 1 and 1000.")
        clauses = ["project_id=?", "status=?"]
        params: list[Any] = [self.project_id, status]
        if category:
            if category not in VALID_CATEGORIES:
                raise ValueError("Invalid category.")
            clauses.append("category=?")
            params.append(category)
        if scope:
            if scope not in VALID_SCOPES:
                raise ValueError("Invalid scope.")
            clauses.append("scope=?")
            params.append(scope)
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM memories WHERE " + " AND ".join(clauses) +
                " ORDER BY importance DESC, created_at DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [self._decode(row) for row in rows]

    def forget(self, memory_id: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE memories SET status='forgotten', updated_at=? WHERE id=? AND project_id=? AND status!='forgotten'",
                (utc_now(), memory_id, self.project_id),
            )
        return cursor.rowcount > 0

    def archive(self, memory_id: str) -> bool:
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE memories SET status='archived', updated_at=? WHERE id=? AND project_id=? AND status='active'",
                (utc_now(), memory_id, self.project_id),
            )
        return cursor.rowcount > 0

    def counts(self) -> dict[str, int]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS total FROM memories WHERE project_id=? GROUP BY status",
                (self.project_id,),
            ).fetchall()
        result = {status: 0 for status in VALID_STATUSES}
        result.update({row["status"]: row["total"] for row in rows})
        result["total"] = sum(result.values())
        return result

    def export_data(self) -> dict[str, Any]:
        with self._connection() as connection:
            rows = connection.execute(
                "SELECT * FROM memories WHERE project_id=? ORDER BY created_at ASC",
                (self.project_id,),
            ).fetchall()
        return {
            "format": "memocup-export-v1",
            "project_id": self.project_id,
            "exported_at": utc_now(),
            "memories": [self._decode(row) for row in rows],
        }

    def import_data(self, payload: dict[str, Any]) -> dict[str, int]:
        """Import an export while preserving IDs and lifecycle state.

        All imported records are assigned to this store's project ID. Existing IDs
        are skipped, and forgotten/superseded records are never reactivated.
        """
        if not isinstance(payload, dict) or payload.get("format") != "memocup-export-v1" or not isinstance(payload.get("memories"), list):
            raise ValueError("Unsupported import format.")

        candidates: list[dict[str, Any]] = []
        skipped = 0
        seen_ids: set[str] = set()
        for item in payload["memories"]:
            try:
                if not isinstance(item, dict):
                    raise ValueError("A memory record must be an object.")
                memory_id = item["id"]
                content = item["content"]
                category = item["category"]
                scope = item["scope"]
                status = item.get("status", "active")
                if not isinstance(memory_id, str) or not memory_id.startswith("mem_"):
                    raise ValueError("Invalid memory ID.")
                if memory_id in seen_ids:
                    raise ValueError("Duplicate ID in import file.")
                if not isinstance(content, str) or not content.strip() or len(content) > 100_000:
                    raise ValueError("Invalid memory content.")
                if category not in VALID_CATEGORIES or scope not in VALID_SCOPES or status not in VALID_STATUSES:
                    raise ValueError("Invalid category, scope, or status.")
                tags = item.get("tags", [])
                metadata = item.get("metadata", {})
                if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
                    raise ValueError("Invalid tags.")
                if not isinstance(metadata, dict):
                    raise ValueError("Invalid metadata.")
                raw_confidence = item.get("confidence", 0.5)
                if isinstance(raw_confidence, bool):
                    raise ValueError("Invalid confidence.")
                confidence = float(raw_confidence)
                importance = item.get("importance", 3)
                if not 0 <= confidence <= 1 or isinstance(importance, bool) or not isinstance(importance, int) or not 1 <= importance <= 5:
                    raise ValueError("Invalid confidence or importance.")
                source = item.get("source", "unspecified")
                source_ref = item.get("source_ref")
                created_at = item.get("created_at", utc_now())
                updated_at = item.get("updated_at", created_at)
                if not isinstance(source, str) or not isinstance(source.strip(), str) or not source.strip():
                    raise ValueError("Invalid source.")
                if not isinstance(created_at, str) or not isinstance(updated_at, str):
                    raise ValueError("Invalid timestamps.")
                for timestamp in (created_at, updated_at):
                    parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    if parsed.tzinfo is None:
                        raise ValueError("Timestamps must include timezone offsets.")
                if source_ref is not None and not isinstance(source_ref, str):
                    raise ValueError("Invalid source reference.")
                expires_at = item.get("expires_at")
                last_accessed_at = item.get("last_accessed_at")
                if expires_at is not None:
                    if not isinstance(expires_at, str):
                        raise ValueError("Invalid expiry timestamp.")
                    expiry = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                    if expiry.tzinfo is None:
                        raise ValueError("Expiry timestamp must include a timezone offset.")
                    expires_at = expiry.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
                if last_accessed_at is not None:
                    if not isinstance(last_accessed_at, str):
                        raise ValueError("Invalid access timestamp.")
                    accessed = datetime.fromisoformat(last_accessed_at.replace("Z", "+00:00"))
                    if accessed.tzinfo is None:
                        raise ValueError("Access timestamp must include a timezone offset.")
                supersedes_id = item.get("supersedes_id")
                superseded_by = item.get("superseded_by")
                if supersedes_id is not None and not isinstance(supersedes_id, str):
                    raise ValueError("Invalid supersedes ID.")
                if superseded_by is not None and not isinstance(superseded_by, str):
                    raise ValueError("Invalid superseded-by ID.")
                candidates.append({
                    "id": memory_id,
                    "scope": scope,
                    "category": category,
                    "content": content.strip(),
                    "content_hash": hashlib.sha256(_normalise(content).encode("utf-8")).hexdigest(),
                    "tags_json": _json(tags[:30]),
                    "source": source[:128],
                    "source_ref": source_ref,
                    "confidence": confidence,
                    "importance": importance,
                    "status": status,
                    "metadata_json": _json(metadata),
                    "supersedes_id": supersedes_id,
                    "superseded_by": superseded_by,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "last_accessed_at": last_accessed_at,
                    "expires_at": expires_at,
                })
                seen_ids.add(memory_id)
            except (KeyError, TypeError, ValueError, OverflowError):
                skipped += 1

        imported = 0
        with self._connection() as connection:
            existing_rows = connection.execute("SELECT id, project_id FROM memories").fetchall()
            all_existing_ids = {row["id"] for row in existing_rows}
            same_project_ids = {row["id"] for row in existing_rows if row["project_id"] == self.project_id}
            new_records = [item for item in candidates if item["id"] not in all_existing_ids]
            skipped += len(candidates) - len(new_records)
            available_ids = same_project_ids | {item["id"] for item in new_records}
            for item in new_records:
                connection.execute(
                    """INSERT INTO memories (
                        id, project_id, scope, category, content, content_hash, tags_json,
                        source, source_ref, confidence, importance, status, metadata_json,
                        supersedes_id, superseded_by, created_at, updated_at,
                        last_accessed_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?, ?)""",
                    (
                        item["id"], self.project_id, item["scope"], item["category"],
                        item["content"], item["content_hash"], item["tags_json"],
                        item["source"], item["source_ref"], item["confidence"],
                        item["importance"], item["status"], item["metadata_json"],
                        item["created_at"], item["updated_at"],
                        item["last_accessed_at"], item["expires_at"],
                    ),
                )
                imported += 1
            for item in new_records:
                supersedes_id = item["supersedes_id"] if item["supersedes_id"] in available_ids and item["supersedes_id"] != item["id"] else None
                superseded_by = item["superseded_by"] if item["superseded_by"] in available_ids and item["superseded_by"] != item["id"] else None
                if supersedes_id or superseded_by:
                    connection.execute(
                        "UPDATE memories SET supersedes_id=?, superseded_by=? WHERE id=? AND project_id=?",
                        (supersedes_id, superseded_by, item["id"], self.project_id),
                    )
        return {"imported": imported, "skipped": skipped}
