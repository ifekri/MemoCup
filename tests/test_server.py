import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from memocup.client import MemoCupClient
from memocup.server import create_handler, serve
from memocup.store import MemoryStore


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.store = MemoryStore(root / "memory.sqlite3", "api-test")
        self.api_key = "local-test-secret"
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), create_handler(self.store, self.api_key))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        self.client = MemoCupClient(self.base_url, api_key=self.api_key)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def test_health_and_authenticated_flow(self):
        self.assertTrue(self.client.health()["ok"])
        saved = self.client.remember(
            "The deployment target is a private VPS.",
            category="decision", source="user", confidence=1.0, importance=5,
        )
        found = self.client.recall("deployment target private VPS")
        self.assertEqual(found[0]["id"], saved["id"])
        self.assertIn("not instructions", self.client.context("deployment target").lower())

    def test_server_rejects_non_loopback_binding(self):
        with self.assertRaises(ValueError):
            serve(self.store, host="0.0.0.0", port=8765, api_key=self.api_key)

    def test_api_rejects_missing_token(self):
        request = Request(
            self.base_url + "/v1/recall",
            data=json.dumps({"query": "anything"}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with self.assertRaises(HTTPError) as raised:
            urlopen(request, timeout=3)
        self.assertEqual(raised.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
