#!/usr/bin/env python3
"""Regenerate the plugin's skills from the libraries' own release tags.

Skills are never hand-copied. For each library in ``build/sources.json`` this
script shallow-clones the release tag, runs that release's
``scripts/agent_framework/build_plugin.py`` (the library's canonical skills-only
generator driven by ``.claude/plugin/package.json``), and merges the generated
``skills/`` (and any ``resources/``) into ``plugins/ras-commander/``. Provenance
(tag, commit, generator hash, selection, per-file source/packaged SHA-256) is
written to ``plugins/ras-commander/provenance/``.

Contribution/self-healing skill slot: list skills in a library's
``contribution_skills`` array in ``build/sources.json``, either as a name (taken
from the release tag) or as ``{"name": ..., "ref": "<branch-or-tag>"}`` to take
the skill directory from a pre-merge branch of the same repository. They are
added to that library's own ``package.json`` selection inside the disposable
clone, so they go through the same generator, shared-distribution approval,
link containment, and provenance as every other skill; the ref and commit are
recorded. A listed skill that cannot be found fails the build. Once the skill
ships in a release, drop the ``ref``. A slot skill already in the library's
default selection is skipped.

Usage:
  python tools/build_content.py                 # rebuild from pinned versions
  python tools/build_content.py --check         # fail if committed content differs
  python tools/build_content.py --latest --bump-on-change   # follow PyPI latest
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
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ROOT / "build" / "sources.json"
GENERATED = ("skills", "resources", "provenance")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pypi_latest(package: str) -> str:
    request = urllib.request.Request(f"https://pypi.org/pypi/{package}/json",
                                     headers={"User-Agent": "ras-commander-plugin-build"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["info"]["version"]


def run(command: list[str], **options) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True, **options)
    return result.stdout.strip()


def clone(library: dict, destination: Path, override: str | None) -> tuple[str, str]:
    tag = library["tag_template"].format(version=library["version"])
    url = override or library["repository"]
    run(["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1",
         "--branch", tag, "--filter=blob:none", url, str(destination)])
    return tag, run(["git", "-C", str(destination), "rev-parse", "HEAD"])


def generate(library: dict, workdir: Path, override: str | None) -> tuple[Path, dict]:
    checkout = workdir / f"src-{library['id']}"
    tag, commit = clone(library, checkout, override)
    package_path = checkout / ".claude" / "plugin" / "package.json"
    original_sha = sha256(package_path)
    package = json.loads(package_path.read_text(encoding="utf-8"))
    default = list(package["skills"])
    slot: list[str] = []
    slot_sources: list[dict] = []
    for entry in library.get("contribution_skills", []):
        entry = {"name": entry} if isinstance(entry, str) else dict(entry)
        name, ref = entry["name"], entry.get("ref")
        if name in default:
            continue
        skill_dir = checkout / ".claude" / "skills" / name
        origin = {"name": name, "ref": tag, "commit": commit}
        if ref:
            # Pre-merge slot: take the skill directory from a named branch/tag
            # of the same repository. Links outside the directory must resolve
            # in the release checkout or the library generator fails.
            branch = workdir / f"slot-{library['id']}-{name}"
            run(["git", "-c", "advice.detachedHead=false", "clone", "--quiet", "--depth", "1",
                 "--branch", ref, "--filter=blob:none", override or library["repository"], str(branch)])
            source_dir = branch / ".claude" / "skills" / name
            if not (source_dir / "SKILL.md").is_file():
                raise SystemExit(f"{library['id']} {ref}: contribution skill '{name}' not found")
            if skill_dir.exists():
                shutil.rmtree(skill_dir)
            shutil.copytree(source_dir, skill_dir)
            origin = {"name": name, "ref": ref,
                      "commit": run(["git", "-C", str(branch), "rev-parse", "HEAD"]),
                      "note": entry.get("note", "")}
        if not (skill_dir / "SKILL.md").is_file():
            raise SystemExit(f"{library['id']} {tag}: contribution skill '{name}' is not in this release")
        slot.append(name)
        slot_sources.append(origin)
    if slot:
        package["skills"] = default + slot
        package_path.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    generator = checkout / "scripts" / "agent_framework" / "build_plugin.py"
    output = workdir / f"out-{library['id']}"
    run([sys.executable, str(generator), "--repo-root", str(checkout), "--output", str(output)])
    record = {
        "library": library["id"],
        "repository": library["repository"],
        "pypi_package": library["pypi_package"],
        "mcp_package": library["mcp_package"],
        "version": library["version"],
        "tag": tag,
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
            json.dumps(record, indent=2) + "\n", encoding="utf-8")
    files.sort(key=lambda item: item["path"])
    (staging / "provenance" / "generated-files.json").write_text(json.dumps({
        "note": "Generated by tools/build_content.py from library release tags. Do not edit by hand.",
        "files": files}, indent=2) + "\n", encoding="utf-8")
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


def bump_patch(manifest_path: Path) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    major, minor, patch = (int(x) for x in re.match(r"^(\d+)\.(\d+)\.(\d+)", manifest["version"]).groups())
    manifest["version"] = f"{major}.{minor}.{patch + 1}"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest["version"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--latest", action="store_true", help="use each library's latest PyPI release")
    parser.add_argument("--check", action="store_true", help="exit 1 if committed content differs")
    parser.add_argument("--bump-on-change", action="store_true", help="bump the plugin patch version on change")
    parser.add_argument("--repo-override", action="append", default=[], metavar="ID=URL",
                        help="clone a library from another URL/path (testing)")
    arguments = parser.parse_args()

    sources = json.loads(SOURCES.read_text(encoding="utf-8"))
    overrides = dict(item.split("=", 1) for item in arguments.repo_override)
    if arguments.latest:
        for library in sources["libraries"]:
            library["version"] = pypi_latest(library["pypi_package"])
    plugin_dir = ROOT / sources["plugin_dir"]
    with tempfile.TemporaryDirectory(prefix="ras-commander-plugin-build-") as temporary:
        staging = assemble(sources["libraries"], Path(temporary), overrides)
        before, after = tree(plugin_dir), tree(staging)
        changed = sorted(set(before) ^ set(after) | {k for k in before.keys() & after.keys() if before[k] != after[k]})
        if arguments.check:
            if changed:
                print("Generated content differs from library sources:\n  " + "\n  ".join(changed))
                return 1
            print("Generated content matches library release sources.")
            return 0
        for name in GENERATED:
            shutil.rmtree(plugin_dir / name, ignore_errors=True)
            if (staging / name).is_dir():
                shutil.copytree(staging / name, plugin_dir / name)
    if arguments.latest:
        SOURCES.write_text(json.dumps(sources, indent=2) + "\n", encoding="utf-8")
    if changed:
        print(f"Updated {len(changed)} generated file(s).")
        if arguments.bump_on_change:
            print("Plugin version:", bump_patch(plugin_dir / ".claude-plugin" / "plugin.json"))
    else:
        print("No generated content changes.")
    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as stream:
            stream.write(f"changed={'true' if changed else 'false'}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
