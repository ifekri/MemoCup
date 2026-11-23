import tempfile
import unittest
from pathlib import Path

from memocup.store import MemoryStore


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = MemoryStore(self.root / "memory.sqlite3", "project-a")

    def tearDown(self):
        self.temp.cleanup()

    def test_remember_and_recall(self):
        saved = self.store.remember(
            "The production database is PostgreSQL.",
            category="decision",
            source="user",
            confidence=1.0,
            importance=5,
            tags=["database", "production"],
        )
        found = self.store.recall("production database PostgreSQL")
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["id"], saved["id"])
        self.assertEqual(found[0]["category"], "decision")

    def test_duplicate_content_is_deduplicated(self):
        first = self.store.remember("User prefers concise answers.", category="preference")
        second = self.store.remember(" user prefers concise answers. ", category="preference", importance=5)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.store.counts()["active"], 1)
        self.assertEqual(second["importance"], 5)

    def test_superseding_marks_previous_record(self):
        old = self.store.remember("The project uses SQLite.", category="decision")
        new = self.store.remember(
            "The project uses PostgreSQL.", category="decision", supersedes_id=old["id"]
        )
        self.assertEqual(self.store.get(old["id"])["status"], "superseded")
        self.assertEqual(self.store.get(old["id"])["superseded_by"], new["id"])
        self.assertEqual([item["id"] for item in self.store.recall("project database")], [new["id"]])

    def test_project_isolation(self):
        other = MemoryStore(self.root / "memory.sqlite3", "project-b")
        self.store.remember("Private project decision about a deployment target.")
        self.assertEqual(other.recall("deployment target"), [])

    def test_forget_is_soft_delete(self):
        saved = self.store.remember("A temporary preference.", category="preference")
        self.assertTrue(self.store.forget(saved["id"]))
        self.assertEqual(self.store.recall("temporary preference"), [])
        self.assertEqual(self.store.get(saved["id"])["status"], "forgotten")

    def test_export_import(self):
        self.store.remember("The API uses bearer authentication.", category="fact")
        payload = self.store.export_data()
        other = MemoryStore(self.root / "other.sqlite3", "project-c")
        result = other.import_data(payload)
        self.assertEqual(result, {"imported": 1, "skipped": 0})
        self.assertEqual(len(other.recall("bearer authentication")), 1)

    def test_import_preserves_ids_status_and_supersession(self):
        previous = self.store.remember("The project uses SQLite.", category="decision")
        current = self.store.remember(
            "The project uses PostgreSQL.", category="decision", supersedes_id=previous["id"]
        )
        forgotten = self.store.remember("Do not retain this temporary item.", category="note")
        self.store.forget(forgotten["id"])

        payload = self.store.export_data()
        restored = MemoryStore(self.root / "restored.sqlite3", "restored-project")
        result = restored.import_data(payload)
        self.assertEqual(result, {"imported": 3, "skipped": 0})
        self.assertEqual(restored.get(previous["id"])["status"], "superseded")
        self.assertEqual(restored.get(previous["id"])["superseded_by"], current["id"])
        self.assertEqual(restored.get(current["id"])["supersedes_id"], previous["id"])
        self.assertEqual(restored.get(forgotten["id"])["status"], "forgotten")
        self.assertEqual(restored.recall("temporary item"), [])
        self.assertEqual(restored.import_data(payload), {"imported": 0, "skipped": 3})

    def test_fts_index_updates_when_duplicate_merges_tags(self):
        saved = self.store.remember("The release uses a stable build pipeline.", category="decision")
        self.store.remember(
            "The release uses a stable build pipeline.",
            category="decision",
            tags=["distinctivebluewidget"],
        )
        found = self.store.recall("distinctivebluewidget")
        self.assertEqual([item["id"] for item in found], [saved["id"]])

    def test_token_scan_fallback_retrieves_content_and_tags(self):
        saved = self.store.remember(
            "The application uses a distinctive runtime.",
            category="fact",
            tags=["fallbackneedle"],
        )
        self.store._fts_available = False
        found = self.store.recall("fallbackneedle")
        self.assertEqual([item["id"] for item in found], [saved["id"]])

    def test_fts_retrieves_matching_records_beyond_recent_record_window(self):
        if not self.store._fts_available:
            self.skipTest("SQLite FTS5 is not available in this Python build.")

        target = self.store.remember(
            "A legacy requirement contains needleoldmemorytoken.",
            category="constraint",
            importance=5,
        )
        now = "2026-01-01T00:00:00Z"
        with self.store._connection() as connection:
            connection.executemany(
                """INSERT INTO memories (
                    id, project_id, scope, category, content, content_hash, tags_json,
                    source, confidence, importance, status, metadata_json, created_at, updated_at
                ) VALUES (?, ?, 'project', 'note', ?, ?, '[]', 'test', 0.5, 1, 'active', '{}', ?, ?)""",
                [
                    (
                        f"mem_filler_{index}",
                        "project-a",
                        f"Unrelated filler record number {index}.",
                        f"filler-hash-{index}",
                        now,
                        now,
                    )
                    for index in range(2005)
                ],
            )

        found = self.store.recall("needleoldmemorytoken")
        self.assertEqual([item["id"] for item in found], [target["id"]])

    def test_validation(self):
        with self.assertRaises(ValueError):
            self.store.remember("")
        with self.assertRaises(ValueError):
            self.store.remember("bad category", category="unknown")
        with self.assertRaises(ValueError):
            self.store.remember("bad confidence", confidence=1.5)


if __name__ == "__main__":
    unittest.main()
