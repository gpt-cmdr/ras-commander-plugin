#!/usr/bin/env python3
"""Offline structural validation for the marketplace and the ras-commander plugin.

Checks manifest JSON and required fields, component wiring (MCP servers, one
read-only subagent per server, the subagent-only guard), runtime scripts
(standard library only, compile on this Python), skill frontmatter, and that
every generated file matches the recorded build provenance. CI cannot run
``claude plugin validate``; maintainers run it locally as well.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MARKETPLACE_NAME = "ras-commander-plugin"
PLUGIN_NAME = "ras-commander"
SERVERS = {"ras-text": "ras", "hms-text": "hms"}
IGNORED_AGENT_KEYS = {"mcpServers", "hooks", "permissionMode"}
errors: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as error:
        errors.append(f"{path.relative_to(ROOT)}: invalid JSON ({error})")
        return None


def frontmatter(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    match = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.DOTALL)
    if not match:
        errors.append(f"{path.relative_to(ROOT)}: missing YAML frontmatter")
        return {}
    fields = {}
    for line in match.group(1).splitlines():
        if line and not line.startswith((" ", "\t", "-")) and ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip()] = value.strip().strip('"').strip("'")
    return fields


def validate_marketplace() -> Path | None:
    marketplace = load_json(ROOT / ".claude-plugin" / "marketplace.json")
    if not marketplace:
        return None
    check(marketplace.get("name") == MARKETPLACE_NAME, "marketplace name must be ras-commander-plugin")
    check(bool((marketplace.get("owner") or {}).get("name")), "marketplace owner.name is required")
    entries = [p for p in marketplace.get("plugins", []) if p.get("name") == PLUGIN_NAME]
    check(len(entries) == 1, "marketplace must list exactly one ras-commander plugin")
    check(len(marketplace.get("plugins", [])) == 1, "marketplace carries a single plugin")
    if not entries:
        return None
    source = entries[0].get("source")
    check(isinstance(source, str) and source.startswith("./"), "plugin source must be a relative ./ path")
    plugin_dir = (ROOT / source).resolve()
    check(plugin_dir.is_dir() and plugin_dir.is_relative_to(ROOT), f"plugin source {source} missing")
    check("version" not in entries[0], "keep the version only in plugin.json")
    return plugin_dir


def validate_manifest(plugin: Path) -> None:
    manifest = load_json(plugin / ".claude-plugin" / "plugin.json")
    if not manifest:
        return
    check(manifest.get("name") == PLUGIN_NAME, "plugin name must be ras-commander")
    check(bool(re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get("version", "")))), "plugin version must be X.Y.Z")
    for key in ("description", "license", "repository"):
        check(bool(manifest.get(key)), f"plugin.json {key} is required")
    for key, option in (manifest.get("userConfig") or {}).items():
        check(option.get("type") in {"string", "number", "boolean", "directory", "file"}, f"userConfig.{key}.type")
        check(bool(option.get("title")) and bool(option.get("description")), f"userConfig.{key} title/description")
        check("default" in option or option.get("required"), f"userConfig.{key} needs a default so the MCP launch resolves")
    servers = manifest.get("mcpServers") or {}
    check(set(servers) == set(SERVERS), f"mcpServers must be exactly {sorted(SERVERS)}")
    for name, kind in SERVERS.items():
        server = servers.get(name) or {}
        check(server.get("command") == "uv", f"{name}: launch through uv")
        args = server.get("args") or []
        check(args[:2] == ["run", "--no-project"], f"{name}: use `uv run --no-project`")
        check(args[-1:] == [kind], f"{name}: launcher kind must be {kind}")
        check("${CLAUDE_PLUGIN_ROOT}/scripts/launch_text_server.py" in args, f"{name}: launcher path")
        env = server.get("env") or {}
        check(env.get("COMMANDER_PROJECT_DIR") == "${CLAUDE_PROJECT_DIR}", f"{name}: project dir root")
        for value in json.dumps(server).split("${user_config.")[1:]:
            option = value.split("}", 1)[0]
            check(option in (manifest.get("userConfig") or {}), f"{name}: undeclared user_config.{option}")


def validate_agents(plugin: Path) -> None:
    for server in SERVERS:
        path = plugin / "agents" / f"{server}.md"
        check(path.is_file(), f"agents/{server}.md missing")
        if not path.is_file():
            continue
        fields = frontmatter(path)
        check(fields.get("name") == server, f"agents/{server}.md name")
        check(bool(fields.get("description")), f"agents/{server}.md description")
        check(fields.get("tools") == f"mcp__plugin_{PLUGIN_NAME}_{server}",
              f"agents/{server}.md tools must be only the {server} server")
        ignored = IGNORED_AGENT_KEYS & set(fields)
        check(not ignored, f"agents/{server}.md: plugin agents ignore {sorted(ignored)}")


def validate_hooks(plugin: Path) -> None:
    hooks = load_json(plugin / "hooks" / "hooks.json")
    if not hooks:
        return
    pre = (hooks.get("hooks") or {}).get("PreToolUse") or []
    matchers = [entry.get("matcher", "") for entry in pre]
    for server in SERVERS:
        tool = f"mcp__plugin_{PLUGIN_NAME}_{server}__server_information"
        check(any(re.fullmatch(m, tool) for m in matchers), f"PreToolUse guard does not match {server} tools")
    check(not any(re.fullmatch(m, "mcp__plugin_other_ras-text__x") for m in matchers), "guard matcher too broad")
    for event, entries in (hooks.get("hooks") or {}).items():
        for entry in entries:
            for hook in entry.get("hooks", []):
                check(hook.get("command") == "uv", f"{event}: hooks run through uv")
                for arg in hook.get("args", []):
                    if arg.startswith("${CLAUDE_PLUGIN_ROOT}/"):
                        target = plugin / arg.split("/", 1)[1]
                        check(target.is_file(), f"{event}: missing {target.relative_to(ROOT)}")
    check(bool((hooks.get("hooks") or {}).get("SessionStart")), "SessionStart update notice missing")


def validate_scripts(plugin: Path) -> None:
    stdlib = set(sys.stdlib_module_names) | {"__future__"}
    for path in sorted((plugin / "scripts").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        compile(tree, str(path), "exec")
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            for name in names:
                check(name.split(".")[0] in stdlib, f"{path.name}: non-stdlib import {name}")
        check(not path.read_text(encoding="utf-8").startswith("# /// script"),
              f"{path.name}: inline script metadata would make uv build an environment")


def validate_generated(plugin: Path) -> None:
    sources = load_json(ROOT / "build" / "sources.json") or {}
    record = load_json(plugin / "provenance" / "generated-files.json") or {}
    listed = {item["path"]: item for item in record.get("files", [])}
    present = {p.relative_to(plugin).as_posix() for d in ("skills", "resources")
               if (plugin / d).is_dir() for p in (plugin / d).rglob("*") if p.is_file()}
    check(present == set(listed), f"generated files differ from provenance: {sorted(present ^ set(listed))}")
    for path, item in listed.items():
        target = plugin / path
        if target.is_file():
            check(hashlib.sha256(target.read_bytes()).hexdigest() == item["sha256"],
                  f"{path} was edited after generation; regenerate with tools/build_content.py")
    expected_skills: set[str] = set()
    for library in sources.get("libraries", []):
        provenance = load_json(plugin / "provenance" / f"{library['id']}.json")
        if not provenance:
            continue
        check(provenance.get("version") == library["version"], f"{library['id']}: provenance version is stale")
        check(provenance.get("tag") == library["tag_template"].format(version=library["version"]),
              f"{library['id']}: provenance tag")
        check(bool(re.fullmatch(r"[0-9a-f]{40}", provenance.get("commit", ""))), f"{library['id']}: commit")
        selection = provenance.get("selection", {})
        wanted = [e if isinstance(e, str) else e["name"] for e in library.get("contribution_skills", [])]
        check(selection.get("contribution_slot") == [s for s in wanted
                                                     if s not in selection.get("library_default", [])],
              f"{library['id']}: contribution slot differs from build/sources.json")
        expected_skills |= set(selection.get("library_default", [])) | set(selection.get("contribution_slot", []))
        for item in provenance.get("source_provenance", {}).get("files", []):
            packaged = item["packaged"]
            check(packaged in listed and listed[packaged]["sha256"] == item["packaged_sha256"],
                  f"{library['id']}: {packaged} does not match the library generator output")
    skills = {p.parent.name for p in (plugin / "skills").glob("*/SKILL.md")}
    check(skills == expected_skills, f"skills {sorted(skills)} differ from selections {sorted(expected_skills)}")
    for skill in sorted(skills):
        fields = frontmatter(plugin / "skills" / skill / "SKILL.md")
        check(fields.get("name") == skill and bool(fields.get("description")), f"skills/{skill} frontmatter")


def main() -> int:
    plugin = validate_marketplace()
    if plugin:
        validate_manifest(plugin)
        validate_agents(plugin)
        validate_hooks(plugin)
        validate_scripts(plugin)
        validate_generated(plugin)
    if errors:
        print("Validation failed:\n  " + "\n  ".join(errors))
        return 1
    print("Marketplace and plugin structure valid.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
