"""PreToolUse guard: RAS/HMS text MCP tools run only inside their dedicated subagent.

Claude Code registers plugin MCP tools in the main session too. This hook denies
any call that does not come from the matching plugin subagent. Hook input has
``agent_id``/``agent_type`` only when the call originates inside a subagent.

With ``--session-context`` (SessionStart hook), print one short context line
that tells the main conversation to delegate, so it does not try the tools
directly and collect guard denials first.

Standard library only; runs through ``uv run --no-project`` on Windows, macOS,
and Linux. Fails closed for this plugin's tools if the input cannot be parsed.
"""
from __future__ import annotations

import json
import re
import sys

PLUGIN = "ras-commander"
TOOL = re.compile(r"^mcp__plugin_ras-commander_(ras-text|hms-text)__")
SESSION_CONTEXT = (
    "ras-commander plugin: the mcp__plugin_ras-commander_ras-text__* and "
    "mcp__plugin_ras-commander_hms-text__* tools are subagent-only, and a guard hook denies "
    "calls from the main conversation. For a HEC-RAS text lookup (units, project metadata, "
    "plan description or configuration), use the Agent tool with "
    "subagent_type 'ras-commander:ras-text'; for HEC-HMS text, 'ras-commander:hms-text'. "
    "Use the ras-commander or hms-commander Python API for results, geometry, execution, and edits.")


def decide(event: dict) -> str | None:
    """Return a denial reason, or None to let the normal permission flow continue."""
    match = TOOL.match(str(event.get("tool_name", "")))
    if not match:
        return None
    server = match.group(1)
    subagent = f"{PLUGIN}:{server}"
    if not event.get("agent_id"):
        return (f"The {server} MCP tools run only inside the {subagent} subagent. "
                f"Delegate one bounded read-only question with the Agent tool "
                f"(subagent_type '{subagent}') instead of calling the tool directly.")
    agent_type = event.get("agent_type")
    if agent_type and agent_type not in (subagent, server):
        return (f"The {server} MCP tools are reserved for the {subagent} subagent; "
                f"this call came from '{agent_type}'. Delegate to {subagent} instead.")
    return None


def session_context() -> str:
    return json.dumps({"hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": SESSION_CONTEXT}})


def main() -> int:
    if sys.argv[1:] == ["--session-context"]:
        print(session_context())
        return 0
    try:
        event = json.loads(sys.stdin.read() or "{}")
        if not isinstance(event, dict):
            raise ValueError("hook input is not an object")
        reason = decide(event)
    except Exception as error:  # fail closed: only this plugin's tools reach this hook
        reason = f"ras-commander guard could not read the hook input ({error}); call denied."
    if reason:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
