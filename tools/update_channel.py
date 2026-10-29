#!/usr/bin/env python3
"""Build a channel using main's shared code in a clean, disposable CI checkout."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import build_content as build


def git(*args: str, **options) -> str:
    return build.run(["git", *args], **options)


def manifest_at(commit: str, path: str) -> dict:
    return json.loads(git("show", f"{commit}:{path}"))


def next_version(stable: str, previous: str | None, channel: str) -> str:
    if channel == "release":
        major, minor, patch = map(int, (previous or stable).split("."))
        return f"{major}.{minor}.{patch + 1}"
    prefix = stable + "-latest."
    number = int(previous[len(prefix):]) + 1 if previous and previous.startswith(prefix) else 1
    return prefix + str(number)


def payload(ref: str | None, plugin: str) -> dict:
    """Compare user-facing files, ignoring provenance and the cache version."""
    if ref:
        names = git("ls-tree", "-r", "--name-only", ref, "--", plugin).splitlines()
        read = lambda name: subprocess.check_output(["git", "show", f"{ref}:{name}"])
    else:
        names = [p.relative_to(build.ROOT).as_posix() for p in (build.ROOT / plugin).rglob("*") if p.is_file()]
        read = lambda name: (build.ROOT / name).read_bytes()
    result = {}
    for name in names:
        relative = name[len(plugin) + 1:]
        if relative.startswith("provenance/") or "__pycache__/" in relative:
            continue
        content = read(name)
        if relative in ("plugin.json", ".claude-plugin/plugin.json"):
            value = json.loads(content)
            value.pop("version", None)
            content = json.dumps(value, sort_keys=True).encode()
        result[relative] = content
    return result


def restore_snapshot(ref: str, plugin: str) -> None:
    paths = ["build/sources.json", *(f"{plugin}/{name}" for name in build.GENERATED)]
    # Resources are optional; git restore rejects a path absent from both trees.
    present = git("ls-tree", "--name-only", ref, "--", *paths).splitlines()
    git("restore", "--source", ref, "--", *present)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--channel", choices=("release", "latest"), required=True)
    parser.add_argument("--publish", action="store_true")
    args = parser.parse_args()
    if args.publish and os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("--publish requires a disposable GitHub Actions checkout")
    if git("status", "--porcelain"):
        raise SystemExit("A clean checkout is required")
    baseline = git("rev-parse", "HEAD")
    branch = "main" if args.channel == "release" else "latest"
    probe = subprocess.run(["git", "rev-parse", "--verify", f"refs/remotes/origin/{branch}"],
                           capture_output=True, text=True)
    old = probe.stdout.strip() if probe.returncode == 0 else None
    plugin = json.loads(build.SOURCES.read_text(encoding="utf-8"))["plugin_dir"]
    manifest_path = f"{plugin}/.claude-plugin/plugin.json"
    stable = manifest_at(baseline, manifest_path)["version"]
    previous = manifest_at(old, manifest_path)["version"] if old else None
    build.run([sys.executable, "tools/build_content.py", "--channel", args.channel])
    changed = old is None or payload(None, plugin) != payload(old, plugin)
    path = build.ROOT / manifest_path
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if changed:
        manifest["version"] = next_version(stable, previous, args.channel)
    else:
        # Library code-only pushes keep the previous snapshot and cache version.
        restore_snapshot(old, plugin)
        manifest["version"] = previous
    path.write_text(build.dumps(manifest), encoding="utf-8", newline="\n")
    build.write_codex_manifests(build.ROOT / plugin)
    build.run([sys.executable, "tools/validate.py"])
    build.run([sys.executable, "tools/build_content.py", "--check"])
    print(f"{args.channel}: plugin {manifest['version']}; content changed={changed}")
    if not args.publish:
        return
    git("add", "-A")
    tree = git("write-tree")
    if old and tree == git("rev-parse", f"{old}^{{tree}}"):
        print("Channel is current")
        return
    parents = ["-p", old] if old else []
    if args.channel == "latest" and baseline != old:
        parents += ["-p", baseline]
    commit = git("commit-tree", tree, *parents,
                 input=f"Update {args.channel} channel (plugin {manifest['version']})\n")
    git("push", "origin", f"{commit}:refs/heads/{branch}")
    print(f"Published {branch}: {commit}")


if __name__ == "__main__":
    main()
