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

## Update channels

New installs use **release** by default. Choose one marketplace branch; the plugin
name remains `ras-commander` in both hosts.

| Channel | Marketplace branch | Skill sources | Updates |
| --- | --- | --- | --- |
| `release` (default) | `main` | Latest published, non-prerelease library release tags | Library release notification |
| `latest` | `latest` | RAS Commander and HMS Commander `main` | Library push notification |

The `latest` channel can describe APIs that are not on PyPI yet. Check installed
signatures before using them. Channels select plugin instructions; MCP servers
continue to resolve published PyPI packages, and existing Python environment pins
are preserved. A release bundle omits optional contribution skills that do not
exist in the published source tag.

For a new **latest** installation in Claude Code:

```sh
claude plugin marketplace add gpt-cmdr/ras-commander-plugin@latest
claude plugin marketplace update ras-commander-plugin
claude plugin update ras-commander@ras-commander-plugin
```

For an existing Claude installation, first change this marketplace's source
`ref` to `latest` in `~/.claude/settings.json` (or the active
`CLAUDE_CONFIG_DIR/settings.json`). Keep its other settings:

```json
{
  "extraKnownMarketplaces": {
    "ras-commander-plugin": {
      "source": {"source": "github", "repo": "gpt-cmdr/ras-commander-plugin", "ref": "latest"},
      "autoUpdate": true
    }
  }
}
```

Then run the three Claude commands above. Re-adding refreshes the catalog from
that branch; adding a different branch before changing the declaration is
rejected by Claude Code.

Channel switching was verified with Claude Code 2.1.312. If an older client
rejects a matching declaration or no longer lists the catalog after selecting
a ref, run `claude update`, then repeat the registration and update commands.

For Codex, remove the old marketplace registration before adding a different
branch (skip the remove command for a new installation):

```sh
codex plugin marketplace remove ras-commander-plugin
codex plugin marketplace add gpt-cmdr/ras-commander-plugin --ref latest
codex plugin marketplace upgrade ras-commander-plugin
codex plugin add ras-commander@ras-commander-plugin
```

To return to **release**, use `@main` for Claude Code or `--ref main` for Codex,
then repeat the respective registration and update steps. Restart the host after switching. Organization
managed marketplace declarations must select the same branch. In Claude Code,
enable marketplace auto-update in `/plugin` or set `autoUpdate: true` on its
`extraKnownMarketplaces` entry. Codex users can run the upgrade commands above.
Host update settings determine when a published bundle reaches an installation.

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

The skills track `main` of ras-commander and hms-commander. Each library sends a
notification on pushes to `main`, triggering a validated rebuild. A weekly check
on Monday at 10:23 UTC recovers missed notifications. Changed packaged content
receives a new plugin patch version (see [Maintenance](#maintenance)).

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

### Update the Python environment for HDF extraction and mapping

The plugin's skills use stable PyPI releases in the agent's Python environment.
Updating the plugin or its text MCP servers does not upgrade that environment.
For a new task environment, use:

```sh
uv venv
uv pip install "ras-commander[full]>=0.110.2"
```

For an existing environment, agree to the upgrade with its owner, activate the
intended environment, and run:

```sh
uv pip install --upgrade "ras-commander[full]>=0.110.2"
```

Preserve project pins unless their owner authorizes a change. Inspect installed
signatures and capabilities when a skill describes an API that is present on
`main` but not yet released to PyPI.

Release 0.110.2 includes the Rust HDF engine, `ras-commander-fast-hdf`, as a
base dependency on supported CPython platforms: Windows x64, Linux x64, and
macOS arm64. The `[full]` extra includes the Rust mapping engine,
`ras-commander-fast-map`, on Windows x64 and Linux x64; no macOS mapping wheel
is available. HDF extraction and mapping use the Python APIs. The text MCP
servers do not perform either operation.

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
- **The `latest` channel follows library `main`.** Its skills can describe APIs
  that are not released to PyPI. The default `release` channel uses published
  library release tags.
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
  skills/                           GENERATED from the selected channel (do not edit)
  provenance/                       refs, commits, generator hashes, file hashes
build/sources.json                  tracked ref, pinned commit, contribution-skill slot
tools/build_content.py              regenerate skills from the pinned library commits
tools/validate.py                   offline manifest, structure, and provenance checks
tools/test_scripts.py               unit tests for the runtime scripts
```

## Maintenance

The skills are generated from the pinned library commits in `build/sources.json`.
That file records `channel`, source `ref`, and exact `commit` for each library.
The canonical library generator enforces shared distribution approval, contained
links, and source/package hashes. Release snapshots that predate the UTF-8/LF
fix use a separately pinned canonical generator commit, recorded in provenance;
all packaged skill and resource text still comes from the release tag.

```sh
python tools/build_content.py --check
python tools/build_content.py --channel release  # refresh published release tags
python tools/build_content.py --channel latest   # refresh library main
python tools/validate.py
python -m unittest tools/test_scripts.py tools/test_channels.py
claude plugin validate plugins/ras-commander
```

`tools/update_channel.py` runs in a clean CI checkout of `main`. It uses shared
runtime code from `main`, rebuilds the selected channel, validates it, and pushes
a normal fast-forward commit. The `latest` branch retains its own generated
content and `X.Y.Z-latest.N` cache version. Source provenance changes alone do not
bump the version. Runtime or packaged skill/resource changes do. Plain builds
and `--check` use exact pins, so validation is reproducible.

`regenerate.yml` updates `latest` after a library main notification or a plugin
`main` push. A `library-release` notification, manual dispatch, or Monday 10:23 UTC
fallback updates both channels. Source notifications trigger builds promptly;
GitHub queue times and host update settings still apply. Builds never publish
Python packages or change project environments.

Each upstream `notify-commander-plugin.yml` sends `library-main-updated` on pushes
to `main` and `library-release` when a release is published. Both use the Actions
secret `PLUGIN_DISPATCH_TOKEN`: a fine-grained token restricted to this plugin
repository with Contents: write. The upstream default `GITHUB_TOKEN` cannot send
cross-repository dispatches. See the [GitHub repository dispatch API](https://docs.github.com/en/rest/repos/repos#create-a-repository-dispatch-event).

### Dispatch token renewal

Configured October 29, 2026: the fine-grained `commander-plugin-dispatch` token
is stored as the Actions secret `PLUGIN_DISPATCH_TOKEN` in both
`gpt-cmdr/ras-commander` and `gpt-cmdr/hms-commander`. Its only selected
repository is `gpt-cmdr/ras-commander-plugin`, with Contents read/write and
required Metadata read access, and no account permissions. It expires
**November 28, 2026**.

Before expiry:

1. Create a replacement fine-grained token with the same repository and
   permissions. Keep its value out of source files, issues, and logs.
2. Replace `PLUGIN_DISPATCH_TOKEN` under **Settings → Secrets and variables →
   Actions** in both library repositories.
3. Run **Notify Commander plugin** (`notify-commander-plugin.yml`) manually
   in each library, or rerun a failed notification job. Confirm that both
   notifications and their resulting **Regenerate from library main** runs
   succeed. Unchanged packaged content should produce no plugin release.
4. Revoke the previous token after both replacement credentials are verified.
   Record the replacement's expiry here.

The weekly Monday recovery job uses this repository's own `GITHUB_TOKEN` and
continues if the upstream token expires. Push-triggered updates resume after
the upstream secrets are replaced and a notification succeeds.

### Verified rollout, October 29, 2026

Plugin 0.1.2 shipped the regenerated skills and setup guidance for
ras-commander 0.110.2 or newer. The upstream generators now handle UTF-8 and LF
directly, so the marketplace's newline monkeypatch has been removed. Structure
and provenance checks, Linux regeneration, and script tests on Windows, macOS,
and Linux passed.

Both upstream push notifications succeeded with the configured secret. The
[RAS-triggered rebuild](https://github.com/gpt-cmdr/ras-commander-plugin/actions/runs/40888556421)
and [HMS-triggered rebuild](https://github.com/gpt-cmdr/ras-commander-plugin/actions/runs/40888557419)
found no changed skills or resources and correctly kept version 0.1.2.

A fresh Windows CPython 3.11 installation of
`ras-commander[full]==0.110.2` included fast-hdf 0.2.4 and fast-map 0.10.1.
Imports of RAS Commander and the HDF extension passed, as did dependency
consistency checks. This check did not run HDF extraction, mapping, or a hydraulic model.
The MCP lock, compatibility snapshot, and setup documentation were also
[refreshed](https://github.com/gpt-cmdr/ras-commander-mcp/pull/16).

## License

MIT
