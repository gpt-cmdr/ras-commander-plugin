"""Passive update notice for the ras-commander plugin (SessionStart hook).

Hook mode (default): read the cached result from the plugin data directory and
print a short ``systemMessage`` only when an update is pending. If the last
refresh attempt is older than 24 hours, start a detached background refresh and
return immediately. Never blocks, never installs or upgrades anything.

Refresh mode (``--refresh``): resolve, offline from the uv cache, the versions
``uvx`` would launch for each text MCP server and its library; fetch the latest
PyPI releases and the plugin version published in the marketplace; write the
cache. Network or resolution failures are silent. Standard library only.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

INTERVAL_SECONDS = 24 * 60 * 60
CACHE_NAME = "update-check.json"
STATE_NAME = "update-check-attempt.json"
MARKETPLACE = "ras-commander-plugin"
PLUGIN = "ras-commander"
MARKETPLACE_URL = ("https://raw.githubusercontent.com/gpt-cmdr/ras-commander-plugin/"
                   "main/.claude-plugin/marketplace.json")
RAW_BASE = "https://raw.githubusercontent.com/gpt-cmdr/ras-commander-plugin/main/"
# Each text MCP server and the library it launches with.
SERVERS = {
    "ras-commander-mcp": "ras-commander",
    "hms-commander-mcp": "hms-commander",
}


def version_key(text: str) -> tuple:
    """Order release versions; pre/dev releases sort below the final release."""
    match = re.match(r"^\s*v?(\d+(?:\.\d+)*)(.*)$", str(text))
    if not match:
        return ((), 0)
    release = tuple(int(part) for part in match.group(1).split("."))
    while release and release[-1] == 0:
        release = release[:-1]
    suffix = match.group(2).strip().lower()
    final = 0 if re.search(r"(a|b|rc|dev|alpha|beta|pre|c)\d*", suffix) else 1
    return (release, final)


def newer(latest: str | None, current: str | None) -> bool:
    return bool(latest and current and version_key(latest) > version_key(current))


def read_json(path: str):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return None


def write_json(path: str, data) -> None:
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".tmp-", dir=directory)
    with os.fdopen(handle, "w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2)
    os.replace(temporary, path)


def local_plugin_version(plugin_root: str) -> str | None:
    manifest = read_json(os.path.join(plugin_root, ".claude-plugin", "plugin.json")) or {}
    return manifest.get("version")


def notice(cache: dict, plugin_root: str) -> str | None:
    parts, clean = [], []
    for item in cache.get("packages", []):
        if newer(item.get("latest"), item.get("cached")):
            parts.append(f"{item['name']} {item['cached']} -> {item['latest']}")
            clean += [item["server"], SERVERS[item["server"]]]
    plugin = cache.get("plugin") or {}
    installed = local_plugin_version(plugin_root)
    plugin_update = newer(plugin.get("latest"), installed)
    if plugin_update:
        parts.append(f"plugin {installed} -> {plugin['latest']}")
    if not parts:
        return None
    steps = []
    if clean:
        unique = list(dict.fromkeys(clean))
        steps.append(f"server: run `uv cache clean {' '.join(unique)}`")
    if plugin_update:
        steps.append(f"plugin: run `claude plugin marketplace update {MARKETPLACE}` then "
                     f"`claude plugin update {PLUGIN}@{MARKETPLACE}`")
    return (f"ras-commander plugin: update available ({'; '.join(parts)}). "
            f"To update, {'; '.join(steps)}; then restart Claude Code.")


def spawn_refresh(data_dir: str, plugin_root: str) -> None:
    arguments = [sys.executable, os.path.abspath(__file__), "--refresh", data_dir, plugin_root]
    options = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, close_fds=True)
    if os.name == "nt":
        detached, group, breakaway = 0x00000008, 0x00000200, 0x01000000
        try:
            subprocess.Popen(arguments, creationflags=detached | group | breakaway, **options)
        except OSError:
            subprocess.Popen(arguments, creationflags=detached | group, **options)
    else:
        subprocess.Popen(arguments, start_new_session=True, **options)


def hook(data_dir: str, plugin_root: str) -> None:
    if not data_dir or "${" in data_dir:
        return
    cache = read_json(os.path.join(data_dir, CACHE_NAME)) or {}
    message = notice(cache, plugin_root)
    state_path = os.path.join(data_dir, STATE_NAME)
    attempted = (read_json(state_path) or {}).get("attempted_at", 0)
    now = time.time()
    if not isinstance(attempted, (int, float)) or not 0 <= now - attempted < INTERVAL_SECONDS:
        try:
            write_json(state_path, {"attempted_at": now})
            spawn_refresh(data_dir, plugin_root)
        except Exception:
            pass
    if message:
        print(json.dumps({"systemMessage": message}))


def fetch_json(url: str, timeout: float = 6.0):
    request = urllib.request.Request(url, headers={"User-Agent": "ras-commander-plugin-update-check"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def cached_versions(server: str) -> dict:
    """Versions uvx would launch right now, resolved offline from the uv cache."""
    uv = os.environ.get("UV") or shutil.which("uv")
    if not uv:
        return {}
    library = SERVERS[server]
    code = ("import importlib.metadata as m, json; "
            f"print(json.dumps({{n: m.version(n) for n in ({server!r}, {library!r})}}))")
    try:
        result = subprocess.run([uv, "tool", "run", "--offline", "--quiet", "--from", server,
                                 "python", "-c", code], capture_output=True, text=True,
                                timeout=60, stdin=subprocess.DEVNULL)
        if result.returncode == 0:
            return json.loads(result.stdout.strip().splitlines()[-1])
    except Exception:
        pass
    return {}


def latest_plugin_version() -> str | None:
    marketplace = fetch_json(MARKETPLACE_URL)
    entry = next(p for p in marketplace["plugins"] if p.get("name") == PLUGIN)
    if entry.get("version"):
        return entry["version"]
    source = str(entry["source"]).lstrip("./").rstrip("/")
    return fetch_json(f"{RAW_BASE}{source}/.claude-plugin/plugin.json").get("version")


def refresh(data_dir: str, plugin_root: str) -> None:
    packages = []
    for server, library in SERVERS.items():
        cached = cached_versions(server)
        for name in (server, library):
            try:
                latest = fetch_json(f"https://pypi.org/pypi/{name}/json")["info"]["version"]
            except Exception:
                latest = None
            # Not yet cached means the next launch resolves the latest release anyway.
            packages.append({"name": name, "server": server,
                             "cached": cached.get(name), "latest": latest})
    try:
        plugin_latest = latest_plugin_version()
    except Exception:
        plugin_latest = None
    write_json(os.path.join(data_dir, CACHE_NAME), {
        "schema": 1,
        "checked_at": time.time(),
        "packages": packages,
        "plugin": {"installed": local_plugin_version(plugin_root), "latest": plugin_latest},
    })


def main(argv: list[str]) -> int:
    try:
        if len(argv) >= 4 and argv[1] == "--refresh":
            refresh(argv[2], argv[3])
        elif len(argv) >= 3:
            hook(argv[1], argv[2])
    except Exception:
        pass  # an update check must never disturb the session
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
