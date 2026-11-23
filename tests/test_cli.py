import json
import tempfile
import unittest
from pathlib import Path
from argparse import Namespace

from memocup.cli import command_init


class CliInitTests(unittest.TestCase):
    def test_init_is_idempotent_and_does_not_touch_source_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "app.py"
            source.write_text("print('untouched')\n", encoding="utf-8")
            before = source.read_bytes()
            args = Namespace(root=str(root), no_agent_rules=False)
            self.assertEqual(command_init(args), 0)
            config_path = root / ".memocup" / "config.json"
            config_before = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(command_init(args), 0)
            config_after = json.loads(config_path.read_text(encoding="utf-8"))
            self.assertEqual(config_before, config_after)
            self.assertEqual(source.read_bytes(), before)
            agent_rules = (root / "AGENTS.md").read_text(encoding="utf-8")
            self.assertEqual(agent_rules.count("<!-- MEMOCUP:BEGIN -->"), 1)
            root_mcp = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
            cursor_mcp = json.loads((root / ".cursor" / "mcp.json").read_text(encoding="utf-8"))
            self.assertIn("memocup", root_mcp["mcpServers"])
            self.assertIn("${workspaceFolder}", cursor_mcp["mcpServers"]["memocup"]["args"])
            ignore_rules = (root / ".memocup" / ".gitignore").read_text(encoding="utf-8")
            self.assertIn("/config.json", ignore_rules)
            self.assertIn("/mcp-config.json", ignore_rules)

    def test_init_preserves_existing_memocup_ignore_rules(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            memocup_dir = root / ".memocup"
            memocup_dir.mkdir()
            ignore_file = memocup_dir / ".gitignore"
            ignore_file.write_text("/custom-secret\n", encoding="utf-8")
            command_init(Namespace(root=str(root), no_agent_rules=True))
            rules = ignore_file.read_text(encoding="utf-8")
            self.assertIn("/custom-secret", rules)
            self.assertIn("/config.json", rules)
            self.assertIn("/mcp-config.json", rules)

    def test_init_merges_existing_mcp_config_without_overwriting_other_servers(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config = {"mcpServers": {"existing": {"command": "existing-tool", "args": []}}}
            (root / ".mcp.json").write_text(json.dumps(config), encoding="utf-8")
            command_init(Namespace(root=str(root), no_agent_rules=True))
            merged = json.loads((root / ".mcp.json").read_text(encoding="utf-8"))
            self.assertIn("existing", merged["mcpServers"])
            self.assertIn("memocup", merged["mcpServers"])


if __name__ == "__main__":
    unittest.main()
