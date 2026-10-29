# RAS Commander plugin for Claude Code and Codex

A plugin marketplace for Claude Code and Codex with one plugin, `ras-commander`. It bundles:

- **Skills** from [RAS Commander](https://github.com/gpt-cmdr/ras-commander) and
  [HMS Commander](https://github.com/gpt-cmdr/hms-commander): the RAS and HMS
  entry points, RAS API discovery, HMS-to-RAS integration, the cloud-native GIS
  skills, and each library's contributing (defect and feature-gap) skill.
- **Two read-only text MCP servers**, launched with `uvx` from PyPI:
  - `ras-text` runs [`ras-commander-mcp`](https://pypi.org/project/ras-commander-mcp/)
    (tools `mcp__plugin_ras-commander_ras-text__*`)
  - `hms-text` runs [`hms-commander-mcp`](https://pypi.org/project/hms-commander-mcp/)
    (tools `mcp__plugin_ras-commander_hms-text__*`)
- **Two read-only subagents**, `ras-commander:ras-text` and
  `ras-commander:hms-text`. Each one can use only its own server's tools.
- **A guard hook.** Calls to either server are allowed only from inside the
  matching subagent. A direct call from the main conversation is denied, with a
  message that says to delegate to the subagent instead. A one-line
  session-start context hint tells the main conversation to delegate from the
  start, so it does not try the tools first.
- **A passive update notice**, described in [Updates](#updates).

## Requirements

- Claude Code with plugin support.
- [uv](https://docs.astral.sh/uv/) on `PATH` (it provides `uvx`). Nothing else
  needs to be installed. The hook and launcher scripts use only the Python
  standard library and run through `uv run --no-project`, on Windows, macOS,
  and Linux.

## Install

```sh
claude plugin marketplace add gpt-cmdr/ras-commander-plugin
claude plugin install ras-commander@ras-commander-plugin
```

The shell install prints `1 userConfig option not yet set — run /plugin
configure … or pass --config KEY=VALUE.` This is expected and can be ignored: it
refers to the optional `extra_roots` setting described in
[Allowed project roots](#allowed-project-roots). Claude Code prints it for every
unset option, including optional ones with a default.

You can also run `/plugin marketplace add gpt-cmdr/ras-commander-plugin` and
then `/plugin install ras-commander@ras-commander-plugin` inside Claude Code.
Restart Claude Code after installing.

Installing does not write to `~/.claude/agents`, your project folders, or any
Python environment. On first use, `uvx` downloads the MCP servers into uv's
cache.

### Codex

The same plugin is published for Codex from the same generated skills. Codex gets the skills
only: subagent-only MCP access has not been demonstrated on Codex, so the RAS and HMS text MCP
servers, subagents and hooks are not wired in. On Codex, project reads go through the
`ras-commander` and `hms-commander` Python APIs.

```sh
codex plugin marketplace add gpt-cmdr/ras-commander-plugin
codex plugin add ras-commander@ras-commander-plugin
```

To update, run `codex plugin marketplace upgrade ras-commander-plugin`, then
`codex plugin add ras-commander@ras-commander-plugin` again, and start a new Codex session.
The Codex marketplace manifest is `.agents/plugins/marketplace.json`; the portable plugin
manifest is `plugins/ras-commander/plugin.json`.

## Allowed project roots

By default, both servers can read only the current Claude Code project
directory (`${CLAUDE_PROJECT_DIR}`). To allow more directories, set the
optional `extra_roots` option. You can set it at install time:

```sh
claude plugin install ras-commander@ras-commander-plugin --config extra_roots=/data/models
```

You can also set it later from the command line:

```sh
echo '{"extra_roots": "/data/models"}' | claude plugin configure ras-commander@ras-commander-plugin --values-stdin
```

Or use `/plugin` → `ras-commander` → *Configure options* inside Claude Code. Separate paths with `;` on Windows or `:` on macOS and Linux, or
enter a JSON array. Paths that do not exist are skipped. A path that contains
the system temporary directory is also skipped, because the servers refuse
such roots.

## Usage

Ask normally, for example "what units does `models/thames.prj` use?". The
main session delegates the lookup to `ras-commander:ras-text` or
`ras-commander:hms-text`. The subagent returns the value, the source file and
its SHA-256 hash, and the package versions. Geometry, HDF/DSS results,
execution, and edits are outside the MCP servers' scope. For those tasks the
skills direct Claude to the `ras-commander` and `hms-commander` Python APIs.

## Updates

### Update notice

When a session starts, a hook reads a cached result from the plugin data
directory (`${CLAUDE_PLUGIN_DATA}`). If an update is available, it shows a
one-line notice that includes the exact update command. The hook never
blocks the session and never installs or upgrades anything.

At most once every 24 hours, the hook also starts a refresh in the
background. The refresh compares two sets of versions:

- the versions `uvx` would launch now (resolved offline from the uv cache)
  against the latest PyPI releases of `ras-commander-mcp`, `ras-commander`,
  `hms-commander-mcp`, and `hms-commander`;
- the installed plugin version against the version published in this
  marketplace.

If the refresh fails, for example because you are offline, nothing is shown.

### Update the MCP servers

The plugin launches the servers with the cached `uvx` form, which has no
version pin. uv caches the PyPI index for 10 minutes (PyPI sends
`Cache-Control: max-age=600`). After that, the next server launch, which
happens when Claude Code restarts, resolves and uses the newest release on
its own. To use a new release immediately, run one of these commands and
then restart Claude Code. Each one was verified to make the next launch use
the newest release.

```sh
# Option A: drop the cached entries. Name both the server and its library;
# naming only the server updates the server but keeps the old library.
uv cache clean ras-commander-mcp ras-commander
uv cache clean hms-commander-mcp hms-commander

# Option B: refresh in place and print the versions the next launch will use
uvx --refresh --from ras-commander-mcp python -c "from importlib.metadata import version as v; print(v('ras-commander-mcp'), v('ras-commander'))"
uvx --refresh --from hms-commander-mcp python -c "from importlib.metadata import version as v; print(v('hms-commander-mcp'), v('hms-commander'))"
```

If you also installed the servers yourself with `uv tool install`, update
those copies separately with `uv tool upgrade ras-commander-mcp
hms-commander-mcp`. The plugin does not use those copies.

### Update the plugin (skills, agents, hooks)

The skills track `main` of ras-commander and hms-commander. A scheduled job
regenerates them every three hours and publishes a new plugin patch version
whenever they change (see [Maintenance](#maintenance)).

**Turn on auto-update (recommended).** Claude Code auto-updates plugins only
from marketplaces with auto-update on, and it is off by default for
third-party marketplaces such as this one. Turn it on once: run `/plugin`, open
the **Marketplaces** tab, select `ras-commander-plugin`, and choose **Enable
auto-update**. After that, each session refreshes the marketplace in the
background, and the next session loads the new version.

To update by hand instead:

```sh
claude plugin marketplace update ras-commander-plugin
claude plugin update ras-commander@ras-commander-plugin
```

Restart Claude Code to apply the update.

## Limitations

- **Tool names appear in the main session.** Claude Code registers a plugin's
  MCP tools for the whole session. Their descriptions are deferred behind
  tool search, but the names are visible and the main model can try to call
  them. The guard hook denies those calls, so the main session cannot use
  the servers. They still count as registered tools.
- **Plugin agents cannot carry their own MCP servers.** Claude Code ignores
  `mcpServers`, `hooks`, and `permissionMode` in a plugin agent's
  frontmatter. Because of that, the servers are defined at the plugin level
  and isolated by the agents' `tools:` allowlist plus the PreToolUse guard.
  The guard relies on the `agent_id` and `agent_type` fields, which Claude
  Code adds to hook input only inside subagents.
- **Skills-only hosts do not get the MCP servers.** claude.ai, Codex, and
  other hosts that import only skills get the instructions without the
  servers, subagents, or hooks. On those hosts the skills fall back to the
  public Python APIs or report that a capability is missing. They never call
  project MCP from the main agent.
- **The skills follow library `main`, not PyPI releases.** They are regenerated
  from each library's `main` branch, as described in [Maintenance](#maintenance),
  and reach you through auto-update or `claude plugin update`. They can
  describe APIs that `main` has but the latest PyPI release does not yet have.
- **uv is required.** If `uv` is not on `PATH`, the servers and hooks do not
  start.

## Repository layout

```
.claude-plugin/marketplace.json     marketplace "ras-commander-plugin"
plugins/ras-commander/
  .claude-plugin/plugin.json        manifest, MCP servers, userConfig
  agents/{ras-text,hms-text}.md     read-only subagents (one per server)
  hooks/hooks.json                  PreToolUse guard, SessionStart delegation hint and update notice
  scripts/                          launcher, guard, update check (stdlib Python)
  skills/                           GENERATED from library main (do not edit)
  provenance/                       refs, commits, generator hashes, file hashes
build/sources.json                  tracked ref, pinned commit, contribution-skill slot
tools/build_content.py              regenerate skills from the pinned library commits
tools/validate.py                   offline manifest, structure, and provenance checks
tools/test_scripts.py               unit tests for the runtime scripts
```

## Maintenance

The skills are never copied by hand. Each library entry in
`build/sources.json` names a tracked `ref` (`main`) and a pinned `commit`.
`tools/build_content.py` fetches that commit and runs its own
`scripts/agent_framework/build_plugin.py`, which selects skills through
`.claude/plugin/package.json`. The script then merges the generated `skills/`
into the plugin. It records the ref, commit, generator SHA-256, selection, and
every source and packaged file hash under `plugins/ras-commander/provenance/`.
`--latest` moves each pin to the current head of its ref. Plain builds and
`--check` use the pinned commit, so CI results are reproducible.

```sh
python tools/build_content.py            # rebuild from the pinned commits
python tools/build_content.py --check    # fail if committed content differs
python tools/build_content.py --latest --bump-on-change   # follow library main
python tools/validate.py
python -m unittest tools/test_scripts.py
claude plugin validate plugins/ras-commander   # local only
```

**Contribution-skill slot.** Each library entry in `build/sources.json` has a
`contribution_skills` list. A name selects a skill from the pinned commit. An
object `{"name": ..., "ref": "<branch>"}` takes the skill from a pre-merge
branch. Either way, the skill goes through the library's generator and its
ref and commit are recorded in provenance. A slot skill that is already in
the library's default selection is skipped, which is now the case for
`ras-commander-contributing` and `hms-commander-contributing` on `main`.

**CI.** `validate.yml` runs the structure and provenance checks, plus a
`--check` rebuild from the pinned sources, and runs the script tests on
Windows, macOS, and Linux. CI cannot run `claude plugin validate`, so run it
locally before you merge changes to the tools, scripts, or manifests.
`regenerate.yml` runs every three hours, on manual dispatch, and on a
`library-release` or `library-main-updated` repository dispatch. It pins each
library to the head of `main` and rebuilds. If no packaged skill or resource
changed, it keeps the current pins and does nothing. Otherwise it runs the
structure, provenance, and `--check` validation, bumps the plugin patch
version, and pushes the commit straight to `main`. If validation fails,
nothing is pushed and the run fails. It never publishes to PyPI.

## License

MIT
