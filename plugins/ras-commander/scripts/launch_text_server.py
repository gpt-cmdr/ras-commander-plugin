"""Launch a read-only RAS or HMS text MCP server through uvx with allowed roots.

Usage (from the plugin manifest): ``uv run --no-project launch_text_server.py ras|hms``

Allowed roots are the Claude Code project directory plus the optional
``extra_roots`` plugin option. Paths that do not exist are skipped with a note
on stderr. The server itself is the cached ``uvx`` form
(``uv tool run ras-commander-mcp`` / ``uv tool run hms-commander-mcp``), so
uv's normal caching and refresh rules apply. Standard library only.
"""
from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile

PACKAGES = {"ras": "ras-commander-mcp", "hms": "hms-commander-mcp"}


def _unresolved(value: str) -> bool:
    return not value or "${" in value


def parse_extra_roots(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if _unresolved(raw):
        return []
    if raw.startswith("["):
        try:
            items = json.loads(raw)
        except ValueError:
            items = []
        return [str(item).strip() for item in items if str(item).strip()]
    parts: list[str] = []
    for line in raw.splitlines():
        parts.extend(piece.strip() for piece in line.split(os.pathsep))
    return [piece for piece in parts if piece]


def allowed_roots(project_dir: str, extra: str) -> list[str]:
    project = os.getcwd() if _unresolved(project_dir) else project_dir
    temporary = os.path.normcase(os.path.realpath(tempfile.gettempdir()))
    roots: list[str] = []
    for index, candidate in enumerate([project] + parse_extra_roots(extra)):
        path = os.path.abspath(os.path.expanduser(candidate))
        if not os.path.isdir(path):
            print(f"ras-commander plugin: skipping missing root {path}", file=sys.stderr)
            continue
        real = os.path.normcase(os.path.realpath(path))
        if index and (temporary == real or temporary.startswith(real.rstrip(os.sep) + os.sep)):
            # The servers refuse roots that contain their private temporary storage.
            print(f"ras-commander plugin: skipping extra root {path} (contains the temp directory)",
                  file=sys.stderr)
            continue
        if path not in roots:
            roots.append(path)
    return roots


def server_command(kind: str, roots: list[str]) -> tuple[list[str], dict[str, str]]:
    package = PACKAGES[kind]
    uv = os.environ.get("UV") or shutil.which("uv")
    command = [uv, "tool", "run", package] if uv else [shutil.which("uvx") or "uvx", package]
    env = dict(os.environ)
    for key in ("COMMANDER_PROJECT_DIR", "COMMANDER_EXTRA_ROOTS"):
        env.pop(key, None)
    if kind == "ras":
        env["RAS_MCP_ALLOWED_ROOTS"] = json.dumps(roots)
    else:
        for root in roots:
            command += ["--root", root]
    return command, env


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] not in PACKAGES:
        print("usage: launch_text_server.py ras|hms", file=sys.stderr)
        return 2
    roots = allowed_roots(os.environ.get("COMMANDER_PROJECT_DIR", ""),
                          os.environ.get("COMMANDER_EXTRA_ROOTS", ""))
    if not roots:
        print("ras-commander plugin: no existing project root to serve", file=sys.stderr)
        return 2
    command, env = server_command(argv[1], roots)
    # Keep this process as the MCP client's child (Windows has no exec) and pass
    # stdio straight through; forward termination to the server.
    child = subprocess.Popen(command, env=env)

    def forward(signum, _frame):
        if child.poll() is None:
            child.terminate()

    for name in ("SIGTERM", "SIGINT", "SIGBREAK"):
        if hasattr(signal, name):
            try:
                signal.signal(getattr(signal, name), forward)
            except (ValueError, OSError):
                pass
    return child.wait()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
