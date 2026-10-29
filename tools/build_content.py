#!/usr/bin/env python3
"""Regenerate the plugin's skills from the libraries' tracked branch (``main``).

Skills are never hand-copied. For each library in ``build/sources.json`` this
script fetches the pinned ``commit`` of the tracked ``ref`` (``main``), runs that
commit's
``scripts/agent_framework/build_plugin.py`` (the library's canonical skills-only
generator driven by ``.claude/plugin/package.json``), and merges the generated
``skills/`` (and any ``resources/``) into ``plugins/ras-commander/``. Provenance
(tag, commit, generator hash, selection, per-file source/packaged SHA-256) is
written to ``plugins/ras-commander/provenance/``. ``--latest`` moves each pin to
the current head of its ``ref``; plain builds and ``--check`` use the pinned
commit, so CI stays reproducible.

The Codex distribution is derived, not copied: the portable Agent Plugins root
manifest ``plugins/ras-commander/plugin.json`` and the Codex marketplace
``.agents/plugins/marketplace.json`` are generated from the Claude manifests by
``codex_manifests()``. Codex installs the same plugin directory and discovers
the same generated ``skills/``. The Codex manifests declare no MCP servers and
set ``extensions.com.openai.hooks`` to an empty list, so Codex loads neither the
RAS/HMS text servers (subagent-only exposure is unqualified on Codex) nor the
Claude-specific hooks. ``--check`` also fails if these manifests are stale.

Contribution/self-healing skill slot: list skills in a library's
``contribution_skills`` array in ``build/sources.json``, either as a name (taken
from the tracked commit) or as ``{"name": ..., "ref": "<branch-or-tag>"}`` to take
the skill directory from a pre-merge branch of the same repository. They are
added to that library's own ``package.json`` selection inside the disposable
clone, so they go through the same generator, shared-distribution approval,
link containment, and provenance as every other skill; the ref and commit are
recorded. A listed skill that cannot be found fails the build. Once the skill
is on the tracked branch, drop the ``ref``. A slot skill already in the
library's default selection is skipped.

Usage:
  python tools/build_content.py                 # rebuild from pinned commits
  python tools/build_content.py --check         # fail if committed content differs
  python tools/build_content.py --latest --bump-on-change   # follow the tracked branch head
  python tools/build_content.py --codex-only [--check]      # Codex manifests only
"""
from __future__ import annotations

import argparse
import filecmp
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "build" / "sources.json"
GENERATED = ("skills", "resources", "provenance")
CLAUDE_MARKETPLACE = ROOT / ".claude-plugin" / "marketplace.json"
CODEX_MARKETPLACE = ROOT / ".agents" / "plugins" / "marketplace.json"
AGENT_PLUGINS_SCHEMA = "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json"
CODEX_DESCRIPTION = ("HEC-RAS, HEC-HMS, and cloud-native GIS skills from RAS Commander and HMS Commander. "
                     "Skills only on Codex: the read-only RAS/HMS text MCP servers ship in the Claude Code "
                     "plugin, and project reads on Codex go through the public Python APIs.")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(command: list[str], **options) -> str:
    # Match subprocess console output to the explicit UTF-8 capture encoding.
    environment = {**os.environ, "PYTHONUTF8": "1"}
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True,
                                encoding="utf-8", env=environment, **options)
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"Command failed: {' '.join(command)}\n{error.stderr or error.stdout}") from None
    return result.stdout.strip()


def branch_head(library: dict, override: str | None) -> str:
    url = override or library["repository"]
    return run(["git", "ls-remote", "--exit-code", url, f"refs/heads/{library['ref']}"]).split()[0]


def fetch_commit(url: str, commit: str, destination: Path) -> None:
    run(["git", "init", "--quiet", str(destination)])
    # Byte-identical checkouts on every OS; a global autocrlf would change hashes.
    run(["git", "-C", str(destination), "config", "core.autocrlf", "false"])
    run(["git", "-C", str(destination), "fetch", "--quiet", "--depth", "1", "--filter=blob:none", url, commit])
    run(["git", "-C", str(destination), "-c", "advice.detachedHead=false", "checkout", "--quiet", "FETCH_HEAD"])


def clone(library: dict, destination: Path, override: str | None) -> tuple[str, str]:
    fetch_commit(override or library["repository"], library["commit"], destination)
    commit = run(["git", "-C", str(destination), "rev-parse", "HEAD"])
    if commit != library["commit"]:
        raise SystemExit(f"{library['id']}: fetched {commit}, expected {library['commit']}")
    return library["ref"], commit


def generate(library: dict, workdir: Path, override: str | None) -> tuple[Path, dict]:
    checkout = workdir / f"src-{library['id']}"
    ref, commit = clone(library, checkout, override)
    package_path = checkout / ".claude" / "plugin" / "package.json"
    original_sha = sha256(package_path)
    package = json.loads(package_path.read_text(encoding="utf-8"))
    default = list(package["skills"])
    slot: list[str] = []
    slot_sources: list[dict] = []
    for entry in library.get("contribution_skills", []):
        entry = {"name": entry} if isinstance(entry, str) else dict(entry)
        name, slot_ref = entry["name"], entry.get("ref")
        if name in default:
            continue
        skill_dir = checkout / ".claude" / "skills" / name
        origin = {"name": name, "ref": ref, "commit": commit}
        if slot_ref:
            # Pre-merge slot: take the skill directory from a named branch/tag
            # of the same repository. Links outside the directory must resolve
            # in the tracked checkout or the library generator fails.
            branch = workdir / f"slot-{library['id']}-{name}"
            url = override or library["repository"]
            if re.fullmatch(r"[0-9a-f]{40}", slot_ref):
                # An exact commit: `clone --branch` accepts only branches and tags.
                fetch_commit(url, slot_ref, branch)
            else:
                run(["git", "-c", "advice.detachedHead=false", "-c", "core.autocrlf=false", "clone",
                     "--config", "core.autocrlf=false", "--quiet", "--depth", "1",
                     "--branch", slot_ref, "--filter=blob:none", url, str(branch)])
            source_dir = branch / ".claude" / "skills" / name
            if not (source_dir / "SKILL.md").is_file():
                raise SystemExit(f"{library['id']} {slot_ref}: contribution skill '{name}' not found")
            if skill_dir.exists():
                shutil.rmtree(skill_dir)
            shutil.copytree(source_dir, skill_dir)
            origin = {"name": name, "ref": slot_ref,
                      "commit": run(["git", "-C", str(branch), "rev-parse", "HEAD"]),
                      "note": entry.get("note", "")}
        if not (skill_dir / "SKILL.md").is_file():
            raise SystemExit(f"{library['id']} {commit}: contribution skill '{name}' is not on {ref}")
        slot.append(name)
        slot_sources.append(origin)
    if slot:
        package["skills"] = default + slot
        package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8", newline="\n")
    generator = checkout / "scripts" / "agent_framework" / "build_plugin.py"
    output = workdir / f"out-{library['id']}"
    run([sys.executable, str(generator),
         "--repo-root", str(checkout), "--output", str(output)])
    record = {
        "library": library["id"],
        "repository": library["repository"],
        "pypi_package": library["pypi_package"],
        "mcp_package": library["mcp_package"],
        "ref": ref,
        "commit": commit,
        "generator": {"path": "scripts/agent_framework/build_plugin.py", "sha256": sha256(generator)},
        "package_json_sha256": original_sha,
        "selection": {"library_default": default, "contribution_slot": slot,
                      "contribution_sources": slot_sources},
        "generated_manifest": json.loads((output / "plugin.json").read_text(encoding="utf-8")),
        "source_provenance": json.loads((output / "source-provenance.json").read_text(encoding="utf-8")),
    }
    return output, record


def assemble(libraries: list[dict], workdir: Path, overrides: dict[str, str]) -> Path:
    staging = workdir / "staging"
    (staging / "provenance").mkdir(parents=True)
    owners: dict[str, str] = {}
    files: list[dict] = []
    for library in libraries:
        output, record = generate(library, workdir, overrides.get(library["id"]))
        for kind in ("skills", "resources"):
            base = output / kind
            if not base.is_dir():
                continue
            for source in sorted(p for p in base.rglob("*") if p.is_file()):
                relative = source.relative_to(output).as_posix()
                target = staging / relative
                if target.exists():
                    if relative.startswith("skills/") or not filecmp.cmp(source, target, shallow=False):
                        raise SystemExit(f"Generated path collision: {relative} "
                                         f"({owners[relative]} and {library['id']})")
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
                owners[relative] = library["id"]
                files.append({"path": relative, "sha256": sha256(target), "library": library["id"]})
        (staging / "provenance" / f"{library['id']}.json").write_text(
            json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    files.sort(key=lambda item: item["path"])
    (staging / "provenance" / "generated-files.json").write_text(json.dumps({
        "note": "Generated by tools/build_content.py from the libraries' tracked commits. Do not edit by hand.",
        "files": files}, indent=2) + "\n", encoding="utf-8", newline="\n")
    return staging


def tree(base: Path) -> dict[str, str]:
    result = {}
    for name in GENERATED:
        directory = base / name
        if directory.is_dir():
            for path in directory.rglob("*"):
                if path.is_file():
                    result[path.relative_to(base).as_posix()] = sha256(path)
    return result


def dumps(data: dict) -> str:
    return json.dumps(data, indent=2) + "\n"


def codex_manifests(plugin_dir: Path) -> dict[Path, str]:
    """Derive the Codex manifests from the Claude manifests (single source of truth).

    Returns ``{path: expected file text}``. Identity, version, and metadata come
    from ``.claude-plugin/plugin.json`` and ``.claude-plugin/marketplace.json``.
    MCP servers, userConfig, agents, and hooks are deliberately not carried over.
    """
    claude = json.loads((plugin_dir / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    market = json.loads(CLAUDE_MARKETPLACE.read_text(encoding="utf-8"))
    entry = next(p for p in market["plugins"] if p["name"] == claude["name"])
    manifest = {"$schema": AGENT_PLUGINS_SCHEMA}
    for key in ("name", "version"):
        manifest[key] = claude[key]
    manifest["description"] = CODEX_DESCRIPTION
    for key in ("author", "homepage", "repository", "license"):
        if key in claude:
            manifest[key] = claude[key]
    manifest["keywords"] = [k for k in claude.get("keywords", []) if k != "mcp"]
    manifest["extensions"] = {"com.openai": {
        # An explicit empty list replaces default hooks/hooks.json discovery,
        # which holds the Claude-only subagent guard and update notice.
        "hooks": [],
        "interface": {
            "displayName": "RAS Commander",
            "shortDescription": "HEC-RAS, HEC-HMS, and cloud-native GIS skills",
            "longDescription": CODEX_DESCRIPTION,
            "developerName": claude.get("author", {}).get("name", ""),
            "category": "Engineering",
            "websiteURL": claude.get("homepage", ""),
        },
    }}
    marketplace = {
        "name": market["name"],
        "interface": {"displayName": "RAS Commander"},
        "plugins": [{
            "name": claude["name"],
            "source": {"source": "local", "path": entry["source"]},
            "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
            "category": "Engineering",
        }],
    }
    return {plugin_dir / "plugin.json": dumps(manifest), CODEX_MARKETPLACE: dumps(marketplace)}


def stale_codex_manifests(plugin_dir: Path) -> list[str]:
    return [path.relative_to(ROOT).as_posix() for path, text in codex_manifests(plugin_dir).items()
            if not path.is_file() or path.read_text(encoding="utf-8") != text]


def write_codex_manifests(plugin_dir: Path) -> list[str]:
    stale = stale_codex_manifests(plugin_dir)
    for path, text in codex_manifests(plugin_dir).items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    return stale


def bump_patch(manifest_path: Path) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    major, minor, patch = (int(x) for x in re.match(r"^(\d+)\.(\d+)\.(\d+)", manifest["version"]).groups())
    manifest["version"] = f"{major}.{minor}.{patch + 1}"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n")
    return manifest["version"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--latest", action="store_true", help="pin each library to the head of its tracked ref")
    parser.add_argument("--check", action="store_true", help="exit 1 if committed content differs")
    parser.add_argument("--bump-on-change", action="store_true", help="bump the plugin patch version on change")
    parser.add_argument("--codex-only", action="store_true",
                        help="only (re)write or --check the derived Codex manifests; no library clones")
    parser.add_argument("--repo-override", action="append", default=[], metavar="ID=URL",
                        help="clone a library from another URL/path (testing)")
    arguments = parser.parse_args()

    sources = json.loads(SOURCES.read_text(encoding="utf-8"))
    overrides = dict(item.split("=", 1) for item in arguments.repo_override)
    if arguments.latest:
        for library in sources["libraries"]:
            library["commit"] = branch_head(library, overrides.get(library["id"]))
    plugin_dir = ROOT / sources["plugin_dir"]
    if arguments.codex_only:
        if arguments.check:
            stale = stale_codex_manifests(plugin_dir)
            if stale:
                print("Codex manifests are stale; run tools/build_content.py --codex-only:\n  " + "\n  ".join(stale))
                return 1
            print("Codex manifests match the Claude manifests.")
            return 0
        print("Rewrote Codex manifests:", ", ".join(write_codex_manifests(plugin_dir)) or "already current")
        return 0
    with tempfile.TemporaryDirectory(prefix="ras-commander-plugin-build-") as temporary:
        staging = assemble(sources["libraries"], Path(temporary), overrides)
        before, after = tree(plugin_dir), tree(staging)
        changed = sorted(set(before) ^ set(after) | {k for k in before.keys() & after.keys() if before[k] != after[k]})
        if arguments.check:
            changed += stale_codex_manifests(plugin_dir)
            if changed:
                print("Generated content differs from the pinned library commits:\n  " + "\n  ".join(changed))
                return 1
            print("Generated content matches the pinned library commits; Codex manifests are current.")
            return 0
        if arguments.latest and not any(not path.startswith("provenance/") for path in changed):
            # The branch moved but no packaged file changed: keep the current pins
            # rather than publishing a plugin version that differs only in provenance.
            print("No skill or resource changes at the branch heads; keeping the current pins.")
            if "GITHUB_OUTPUT" in os.environ:
                with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
                    stream.write("changed=false\n")
            return 0
        for name in GENERATED:
            shutil.rmtree(plugin_dir / name, ignore_errors=True)
            if (staging / name).is_dir():
                shutil.copytree(staging / name, plugin_dir / name)
    if arguments.latest:
        SOURCES.write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8", newline="\n")
    if changed:
        print(f"Updated {len(changed)} generated file(s).")
        if arguments.bump_on_change:
            print("Plugin version:", bump_patch(plugin_dir / ".claude-plugin" / "plugin.json"))
    codex_stale = write_codex_manifests(plugin_dir)
    if codex_stale:
        print("Rewrote Codex manifests:", ", ".join(codex_stale))
    elif not changed:
        print("No generated content changes.")
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write(f"changed={'true' if changed else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
