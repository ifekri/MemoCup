import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from memocup.mcp_server import run_stdio
from memocup.store import MemoryStore


class McpTests(unittest.TestCase):
    def test_initialize_list_remember_and_recall(self):
        with tempfile.TemporaryDirectory() as temp:
            store = MemoryStore(Path(temp) / "memory.sqlite3", "mcp-test")
            requests = [
                {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-11-25"}},
                {"jsonrpc": "2.0", "method": "notifications/initialized"},
                {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "remember_memory", "arguments": {"content": "The project uses a modular monolith.", "category": "decision", "source": "user"}}},
                {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "recall_memories", "arguments": {"query": "modular monolith"}}},
            ]
            source = io.StringIO("\n".join(json.dumps(item) for item in requests) + "\n")
            target = io.StringIO()
            with patch("sys.stdin", source), patch("sys.stdout", target):
                run_stdio(store)
            responses = [json.loads(line) for line in target.getvalue().splitlines()]
            self.assertEqual([item["id"] for item in responses], [1, 2, 3, 4])
            self.assertEqual(responses[0]["result"]["protocolVersion"], "2025-11-25")
            self.assertIn("recall_memories", [item["name"] for item in responses[1]["result"]["tools"]])
            self.assertFalse(responses[2]["result"]["isError"])
            recall_text = responses[3]["result"]["content"][0]["text"]
            self.assertIn("modular monolith", recall_text)


if __name__ == "__main__":
    unittest.main()
