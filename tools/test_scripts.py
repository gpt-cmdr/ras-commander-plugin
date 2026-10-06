"""Unit tests for the plugin's runtime scripts (stdlib unittest; Windows + Linux)."""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "plugins" / "ras-commander" / "scripts"
PLUGIN = SCRIPTS.parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = load("subagent_guard")
launcher = load("launch_text_server")
update = load("update_check")
RAS_TOOL = "mcp__plugin_ras-commander_ras-text__project_units"
HMS_TOOL = "mcp__plugin_ras-commander_hms-text__read_hms_sections"


class GuardTests(unittest.TestCase):
    def test_main_thread_denied(self):
        self.assertIn("ras-commander:ras-text", guard.decide({"tool_name": RAS_TOOL}))
        self.assertIn("ras-commander:hms-text", guard.decide({"tool_name": HMS_TOOL}))

    def test_matching_subagent_allowed(self):
        self.assertIsNone(guard.decide({"tool_name": RAS_TOOL, "agent_id": "a1",
                                        "agent_type": "ras-commander:ras-text"}))
        self.assertIsNone(guard.decide({"tool_name": HMS_TOOL, "agent_id": "a1",
                                        "agent_type": "ras-commander:hms-text"}))

    def test_other_subagent_denied(self):
        self.assertIsNotNone(guard.decide({"tool_name": RAS_TOOL, "agent_id": "a1",
                                           "agent_type": "general-purpose"}))
        self.assertIsNotNone(guard.decide({"tool_name": RAS_TOOL, "agent_id": "a1",
                                           "agent_type": "ras-commander:hms-text"}))

    def test_unrelated_tool_untouched(self):
        self.assertIsNone(guard.decide({"tool_name": "Read"}))

    def test_process_output(self):
        def run(payload: str) -> str:
            return subprocess.run([sys.executable, str(SCRIPTS / "subagent_guard.py")], input=payload,
                                  capture_output=True, text=True, timeout=30).stdout
        denied = json.loads(run(json.dumps({"tool_name": RAS_TOOL})))
        self.assertEqual(denied["hookSpecificOutput"]["permissionDecision"], "deny")
        self.assertEqual(run(json.dumps({"tool_name": RAS_TOOL, "agent_id": "x",
                                         "agent_type": "ras-commander:ras-text"})), "")
        self.assertIn("deny", run("not json"))


class LauncherTests(unittest.TestCase):
    def test_roots(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            missing = os.path.join(first, "missing")
            extra = os.pathsep.join([second, missing, first])
            self.assertEqual(launcher.allowed_roots(first, extra),
                             [os.path.abspath(first), os.path.abspath(second)])
            self.assertEqual(launcher.allowed_roots(first, json.dumps([second])),
                             [os.path.abspath(first), os.path.abspath(second)])
            self.assertEqual(launcher.allowed_roots(first, "${user_config.extra_roots}"),
                             [os.path.abspath(first)])

    def test_extra_root_containing_temp_skipped(self):
        with tempfile.TemporaryDirectory() as project:
            self.assertEqual(launcher.allowed_roots(project, tempfile.gettempdir()), [os.path.abspath(project)])

    def test_unresolved_project_uses_cwd(self):
        self.assertEqual(launcher.allowed_roots("${CLAUDE_PROJECT_DIR}", ""), [os.getcwd()])

    def test_commands(self):
        command, env = launcher.server_command("ras", ["/a", "/b"])
        self.assertEqual(json.loads(env["RAS_MCP_ALLOWED_ROOTS"]), ["/a", "/b"])
        self.assertIn("ras-commander-mcp", command)
        command, env = launcher.server_command("hms", ["/a", "/b"])
        self.assertEqual(command[-4:], ["--root", "/a", "--root", "/b"])
        self.assertNotIn("COMMANDER_EXTRA_ROOTS", env)


class UpdateTests(unittest.TestCase):
    def test_versions(self):
        self.assertTrue(update.newer("0.104.0", "0.99.2"))
        self.assertTrue(update.newer("0.4.1", "0.4.0"))
        self.assertFalse(update.newer("0.4.0", "0.4"))
        self.assertFalse(update.newer("0.5.0rc1", "0.5.0"))
        self.assertFalse(update.newer(None, "0.4.0"))
        self.assertFalse(update.newer("0.4.0", None))

    def test_notice(self):
        cache = {"packages": [
            {"name": "ras-commander-mcp", "server": "ras-commander-mcp", "cached": "0.4.0", "latest": "0.4.0"},
            {"name": "ras-commander", "server": "ras-commander-mcp", "cached": "0.104.0", "latest": "0.105.0"},
            {"name": "hms-commander-mcp", "server": "hms-commander-mcp", "cached": None, "latest": "0.2.0"}],
            "plugin": {"latest": "9.9.9"}}
        message = update.notice(cache, str(PLUGIN))
        self.assertIn("ras-commander 0.104.0 -> 0.105.0", message)
        self.assertIn("uv cache clean ras-commander-mcp ras-commander", message)
        self.assertNotIn("hms-commander", message)
        self.assertIn("claude plugin update ras-commander@ras-commander-plugin", message)
        self.assertIsNone(update.notice({"packages": [], "plugin": {"latest": "0.0.1"}}, str(PLUGIN)))

    def test_hook_is_fast_and_throttled(self):
        with tempfile.TemporaryDirectory() as data:
            update.write_json(os.path.join(data, update.STATE_NAME), {"attempted_at": time.time()})
            update.write_json(os.path.join(data, update.CACHE_NAME), {"packages": [
                {"name": "hms-commander", "server": "hms-commander-mcp", "cached": "0.4.0", "latest": "0.5.0"}]})
            started = time.time()
            result = subprocess.run([sys.executable, str(SCRIPTS / "update_check.py"), data, str(PLUGIN)],
                                    capture_output=True, text=True, timeout=30)
            self.assertLess(time.time() - started, 5)
            self.assertIn("uv cache clean hms-commander-mcp hms-commander",
                          json.loads(result.stdout)["systemMessage"])

    def test_hook_silent_without_cache(self):
        with tempfile.TemporaryDirectory() as data:
            update.write_json(os.path.join(data, update.STATE_NAME), {"attempted_at": time.time()})
            result = subprocess.run([sys.executable, str(SCRIPTS / "update_check.py"), data, str(PLUGIN)],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.returncode, 0)

    @unittest.skipUnless(shutil.which("uv"), "uv not on PATH")
    def test_guard_through_uv(self):
        result = subprocess.run(["uv", "run", "--no-project", "--quiet", str(SCRIPTS / "subagent_guard.py")],
                                input=json.dumps({"tool_name": HMS_TOOL}), capture_output=True, text=True,
                                timeout=60)
        self.assertEqual(json.loads(result.stdout)["hookSpecificOutput"]["permissionDecision"], "deny")


if __name__ == "__main__":
    unittest.main()
