"""PreToolUse guard: RAS/HMS text MCP tools run only inside their dedicated subagent.

Claude Code registers plugin MCP tools in the main session too. This hook denies
any call that does not come from the matching plugin subagent. Hook input has
``agent_id``/``agent_type`` only when the call originates inside a subagent.

Standard library only; runs through ``uv run --no-project`` on Windows, macOS,
and Linux. Fails closed for this plugin's tools if the input cannot be parsed.
"""
from __future__ import annotations

import json
import re
import sys

PLUGIN = "ras-commander"
TOOL = re.compile(r"^mcp__plugin_ras-commander_(ras-text|hms-text)__")


def decide(event: dict) -> str | None:
    """Return a denial reason, or None to let the normal permission flow continue."""
    match = TOOL.match(str(event.get("tool_name", "")))
    if not match:
        return None
    server = match.group(1)
    subagent = f"{PLUGIN}:{server}"
    if not event.get("agent_id"):
        return (f"The {server} MCP tools run only inside the {subagent} subagent. "
                f"Delegate one bounded read-only question to the {subagent} subagent "
                "with the Agent tool instead of calling the tool directly.")
    agent_type = event.get("agent_type")
    if agent_type and agent_type not in (subagent, server):
        return (f"The {server} MCP tools are reserved for the {subagent} subagent; "
                f"this call came from '{agent_type}'. Delegate to {subagent} instead.")
    return None


def main() -> int:
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
