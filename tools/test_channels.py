"""Channel boundaries, release resolution, and publication regression tests."""
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_content as build
import update_channel as publish


class ChannelTests(unittest.TestCase):
    def test_release_uses_peeled_tag_not_release_target_branch(self):
        response = io.BytesIO(json.dumps({"tag_name": "v1.2.3", "target_commitish": "main"}).encode())
        refs = "a" * 40 + "\trefs/tags/v1.2.3\n" + "b" * 40 + "\trefs/tags/v1.2.3^{}"
        with patch.object(build.urllib.request, "urlopen", return_value=response), patch.object(build, "run", return_value=refs):
            self.assertEqual(build.release_pin({"repository": "https://github.com/example/library"}),
                             ("v1.2.3", "b" * 40))

    def test_release_uses_lightweight_tag(self):
        response = io.BytesIO(b'{"tag_name":"v1.2.3"}')
        with patch.object(build.urllib.request, "urlopen", return_value=response), patch.object(build, "run", return_value="a" * 40 + "\trefs/tags/v1.2.3"):
            self.assertEqual(build.release_pin({"repository": "https://github.com/example/library"})[1], "a" * 40)

    def test_draft_and_prerelease_rejected(self):
        for flag in ("draft", "prerelease"):
            response = io.BytesIO(json.dumps({"tag_name": "v1.2.3", flag: True}).encode())
            with patch.object(build.urllib.request, "urlopen", return_value=response), self.assertRaises(SystemExit):
                build.release_pin({"repository": "https://github.com/example/library"})

    def test_cache_versions_are_distinct_and_increment(self):
        self.assertEqual(publish.next_version("0.2.0", "0.2.0", "release"), "0.2.1")
        self.assertEqual(publish.next_version("0.2.0", None, "latest"), "0.2.0-latest.1")
        self.assertEqual(publish.next_version("0.2.0", "0.2.0-latest.9", "latest"), "0.2.0-latest.10")
        self.assertEqual(publish.next_version("0.2.1", "0.2.0-latest.9", "latest"), "0.2.1-latest.1")

    def test_payload_ignores_provenance_version_but_sees_runtime_changes(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(build, "ROOT", Path(directory)):
            plugin = Path(directory) / "plugin"
            (plugin / ".claude-plugin").mkdir(parents=True)
            (plugin / "provenance").mkdir()
            manifest = plugin / ".claude-plugin/plugin.json"
            manifest.write_text('{"name":"example","version":"0.2.0"}')
            first = publish.payload(None, "plugin")
            manifest.write_text('{"name":"example","version":"0.2.1"}')
            (plugin / "provenance/build.json").write_text('{}')
            self.assertEqual(first, publish.payload(None, "plugin"))
            (plugin / "runtime.py").write_text('print("changed")')
            self.assertNotEqual(first, publish.payload(None, "plugin"))


if __name__ == "__main__":
    unittest.main()
