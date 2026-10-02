---
name: remote-agent-config
description: Sync selected local CC Switch Claude Code or Codex presets to SSH hosts for direct API access, or configure the Claude Code VS Code extension in WSL. Use for remote provider/model changes, key refreshes, removing laptop-tunnel dependencies, and plugin login errors after syncing. Includes API key first-use approval and a real Claude conversation probe. Does not change OpenCode's own configuration.
---

# remote-agent-config

Renders a Claude Code / Codex configuration for a Linux server from a **cc-switch
provider preset**, and pushes it to remote SSH hosts, so `claude` and `codex` on
the server reach the model API directly. This removes the dependency on a reverse
SSH tunnel (`RemoteForward 15721`) pointing back at the laptop.

## When to use

- "把本地 claude/codex 配置同步到服务器"
- "远程用 DeepSeek / 换个渠道 / 换个 provider"
- WSL 里 `claude` CLI 正常但 VS Code 的 Claude Code 插件不生效 / 读不到配置
- remote agent stops working when the laptop sleeps / VS Code disconnects
- need to refresh the model API key on remote hosts
- a new server was added to `~/.ssh/config`

## Resolve the user's choices

Keep progress and questions in Chinese. Run `sync.py --list` and
`sync.py --list-providers` to discover SSH aliases and presets. Use the script
beside this SKILL.md; on Windows invoke it with `python -X utf8`.

Reuse choices already present in the request or conversation. For example,
“34 节点的 Claude Code 使用本地 cc-switch 配置” means the matching 34 host,
Claude only, and the currently active Claude preset. State the resolved alias
and preset before writing; do not repeat questions already answered. Ask only
for unresolved or ambiguous choices:

- 节点：which SSH alias/IP, all enabled hosts, or a WSL distro.
- 同步内容：Claude, Codex, or both. WSL-only always means the Claude extension.
- 预设：current active preset first, then the remaining names in list order.

Inspect the selected target account, run `--dry-run`, and show a concise redacted
preview before syncing. Never print credentials or API key approval suffixes.
A request to use a selected key authorizes recording that key's first-use approval;
a prior explicit rejection is preserved and requires a new user decision.

## How it works

`sync.py` reads the selected preset out of `~/.cc-switch/cc-switch.db` (table
`providers`, column `settings_config`) and renders from that — **not** from the
live `~/.claude/settings.json` / `~/.codex/config.toml`. This distinction is the
whole point: cc-switch's local proxy rewrites the live files to point at
`http://127.0.0.1:15721/v1`, but each preset stores the real upstream `base_url`
and real credentials. Rendering from the preset is what lets a remote node go
direct instead of chasing the laptop's proxy.

Mapping, per agent:

- **claude** preset → remote `~/.claude/settings.json`
  (a preset's `settings_config` is itself a settings.json document)
- **codex** preset → remote `~/.codex/config.toml` (stripped) and
  `~/.codex/auth.json`, plus `~/.codex/cc-switch-model-catalog.json` built from
  the preset's `modelCatalog`

Also optionally merged: remote `~/.vscode-server/data/Machine/settings.json`
(`claudeCode.environmentVariables` and `claudeCode.disableLoginPrompt=true`) so
the VS Code extension uses external authentication. For Claude presets containing
an API key, merge its first-use approval into `~/.claude.json` while preserving
other state. Existing explicit key rejections and malformed JSON stop the sync.
`--force` does not override those checks.

For each host it: creates dirs, backs up existing files to
`<file>.bak-YYYYmmdd-HHMMSS`, uploads via `scp`, `chmod 600`, then verifies.

### WSL targets (`--wsl <发行版>`)

A WSL distro is local: no ssh, no sshd, no `~/.ssh/config` entry. File I/O goes
through the `\\wsl.localhost\<distro>` share and only `chmod` shells out to
`wsl.exe -d <distro>`.

This target exists for the case where the distro runs its **own** cc-switch. That
cc-switch owns `~/.claude/settings.json`, so the `claude` CLI there works fine —
the VS Code Claude Code extension can also have separate environment overrides in
`~/.vscode-server/data/Machine/settings.json` (`claudeCode.environmentVariables`),
which cc-switch does not manage. Sync those overrides and the selected key's
approval so the extension follows the requested provider.

A WSL target writes the extension file and merges the selected API key’s
first-use approval into `~/.claude.json`. It deliberately leaves
`~/.claude/settings.json` alone. Consequence: the extension follows whichever
preset you pick here, while the CLI keeps following the distro's own cc-switch —
pick the same provider if you want them to agree. Reload the VS Code window for
the extension to pick it up.

`--wsl` never fans out to the ssh hosts: a run with `--wsl` and no `--hosts`
targets the distro alone, and such a run syncs **claude only** — `--targets`
defaults to `claude` there, since the extension environment and key approval
come from the Claude preset. Passing `--hosts`
alongside `--wsl` restores the normal `all` default. The distro's Claude CLI
settings and Codex configuration remain managed by its own cc-switch.

### Choosing a preset

`--list-providers` shows every preset per agent with `*` on the current one.
Names match case-insensitively; a unique substring is enough (`--claude-provider deep`
→ `DeepSeek`). Ambiguous or unknown names fail with the list rather than guessing.
With no `--*-provider` flag, the current cc-switch preset is used.

"Official" presets (`Claude Official`, `OpenAI Official`) are login-style and
store no `base_url` / no rendered config. Pushing one would overwrite a working
remote file with an empty shell, so the script refuses them — point the user at a
preset with an explicit upstream instead.

`--from-live` restores the old behaviour of reading the live files. Use it only
if the cc-switch database is missing or out of step with what you actually want
shipped — and expect the loopback guard to fire on Codex, because the live
config is usually proxy-managed.

### Idempotency check

Before touching anything, the script compares the desired config, login-prompt
setting, and selected API key approval against what is already on the remote
(JSON is compared structurally, TOML text is normalised).
If everything matches, that host is skipped with `已是最新，跳过 (up to date)` and
nothing is written or backed up. Pass `--force` to re-write regardless.

The final line reports both counts, e.g.
`done: 1 updated, 5 already up to date (all)`.

### Codex is rewritten, not copied

The config text is Windows-flavoured and **must not be copied raw**. The script
keeps only portable keys (`model_provider`, `model`, `model_reasoning_effort`,
`model_context_window`, `model_auto_compact_token_limit`, `model_catalog_json`,
`[features]`, and the selected `[model_providers.*]` block) and drops `[windows]`,
`[projects.*]`, `[mcp_servers*]`, Windows paths, and proxy-only keys such as
`experimental_bearer_token`.

The preset's `modelCatalog` is compact; it is expanded to Codex's long model
descriptor schema before shipping. If a config references `model_catalog_json`
but no catalog is available, the reference is dropped so the remote does not
fail on a missing file.

### Claude hooks are dropped by default

Local hooks (e.g. `codegraph prompt-hook`) reference tools that may not exist on
the server. Presets normally carry no hooks at all; pass `--include-hooks` to
merge the live `hooks` block back in.

## Usage

```bash
S=~/.claude/skills/remote-agent-config/sync.py

python3 "$S" --list                       # show target hosts
python3 "$S" --list-providers             # show cc-switch presets (* = current)
python3 "$S" --dry-run                    # print generated config, touch nothing
python3 "$S" --hosts 172.16.240.13 --targets claude --claude-provider DeepSeek
python3 "$S" --codex-provider 词易         # pick a codex preset by name
python3 "$S"                              # all enabled Hosts, both agents, current presets
python3 "$S" --force                      # re-write even if up to date
python3 "$S" --exclude 219.145.122.226    # skip the jump box
python3 "$S" --wsl <发行版>                # WSL: extension environment + key approval (Windows only)
python3 "$S" --env ANTHROPIC_MODEL=deepseek-v4-pro   # override one claude env entry (repeatable)
python3 "$S" --no-vscode                  # skip Machine/settings.json
python3 "$S" --from-live                  # legacy: read live files, not presets
python3 "$S" --db /path/to/cc-switch.db   # alternate database
```

On **Windows** use `python` (or `py`) instead of `python3`; everything else is
the same. `--hosts` accepts either the ssh alias or the node IP.

## Windows install locations

To make this skill available to every agent runtime on Windows, keep a copy in:

- `%USERPROFILE%\.config\opencode\skills\remote-agent-config\` (opencode)
- `%USERPROFILE%\.claude\skills\remote-agent-config\` (Claude Code, and
  opencode's external scan)
- `%USERPROFILE%\.codex\skills\remote-agent-config\` (Codex)
- `%USERPROFILE%\.zcode\skills\remote-agent-config\` (zcode)

If you edit one copy, copy all skill sources (including the verifier and tests)
to the other three. Do not copy `__pycache__`, credentials, or generated logs.

## Loopback guard

The script refuses to push a `base_url` of `127.0.0.1` / `localhost`, because
that would point the remote node at itself. With presets this normally never
fires — a preset stores the real upstream. It fires under `--from-live`, where
the live config is often the local cc-switch proxy
(`http://127.0.0.1:15721/v1`). Pick a preset instead, fix the local config to a
reachable upstream, or pass `--allow-loopback` if you really mean it.

## Warnings

- **Secrets on disk.** This writes the real `ANTHROPIC_API_KEY` /
  `OPENAI_API_KEY` into remote config files. On shared accounts other users may
  read them; files are `chmod 600`, but this is still key material leaving the
  laptop. Confirm with the user before running on shared machines.
- Always run `--dry-run` and show the user the generated config first. Dry-run
  output is **redacted** (credential-shaped keys print `***REDACTED***`), so it
  is safe to paste back into chat — but do not run without `--dry-run` just to
  "see the real values".
- The OpenCode preset carries `ANTHROPIC_CUSTOM_HEADERS=x-opencode-session:
  windows-cc-switch`, a laptop-side identity. Nodes that share a network home
  will collide on it; set a per-node value in the remote file if that matters.
  This bites a WSL target too: the Windows preset would label the distro's
  extension `windows-cc-switch` while its CLI carries its own name. Fix it with
  `--env` rather than by editing the file — the next sync rewrites that field:

  ```bash
  python3 "$S" --wsl <发行版> --targets claude \
    --env "ANTHROPIC_CUSTOM_HEADERS=x-opencode-session: wsl-<发行版>"
  ```
- `--wsl` needs Windows (it uses `wsl.exe` and the `\\wsl.localhost` share).
  Running the skill inside WSL itself cannot reach another distro this way.
- After changing `~/.vscode-server/data/Machine/settings.json`, the user must
  reload the VS Code window for the extension to pick it up.
- Existing remote files are backed up. Machine settings and `~/.claude.json`
  are merged to preserve unrelated keys; agent settings are rendered from the preset.
- Avoid concurrent config writers while syncing (active Claude sessions or another
  sync). SSH sync checks for changed auth state before replacing it; this is not
  a cross-process transaction.


## Required verification for Claude

A matching file, HTTP 200 from curl, or `claude auth status` showing
`loggedIn: true` does **not** prove the VS Code client can chat. After syncing,
run the companion probe once for each selected Claude target:

```bash
python verify_claude.py --host <ssh-alias>
python verify_claude.py --wsl <distro>
```

The probe selects the installed extension's native Claude binary, loads the
configured environment, sets `CLAUDE_CODE_ENTRYPOINT=claude-vscode`, and makes
one small real request with tools/hooks disabled and no saved session. It uses
`/tmp` by default to avoid sending project context and has a bounded timeout.
This consumes a small amount of provider usage. It only passes when the CLI
exits successfully and the result is non-error text `OK`. It never prints raw
CLI logs or credentials. Codex-only sync does not run this probe.

This tests the extension's Claude client, not the VS Code UI. Ask the user to
reload the **target remote window** and start a new conversation. If the binary
is missing, the probe times out, or a request fails, report “配置已同步，真实对话验证
未通过” with the actual reason; do not declare the plugin usable.

### `Not logged in · Please run /login` after reload

Observed in Claude Code 2.1.286: the VS Code client only accepts an environment
API key after its first-use approval is recorded in `~/.claude.json` under
`customApiKeyResponses.approved`. The stored identifier is the trimmed key's
last 20 characters; it is sensitive and must never be printed. The CLI's auth
status can still report logged in without this approval. `sync.py` now merges
this state using the selected key and stops on a prior rejection.

`disableLoginPrompt` only hides the login UI; it does not fix missing credentials.
Do not add OAuth login data or mark unrelated onboarding/trust prompts complete.
Do not use `ANTHROPIC_AUTH_TOKEN` as a blind workaround or overwrite all of
`~/.claude.json`. After fixing the selected key approval, repeat the real probe.

If it still fails, inspect the newest
`~/.vscode-server/data/logs/*/exthost*/Anthropic.claude-code/Claude VSCode.log`,
actual Claude process environment (key presence/equality only), working directory,
and project overrides. Filter and redact logs before displaying them. Recheck
the installed client's behavior if its version differs; approval storage is an
observed implementation detail, not a promised stable API.

## Maintainer checks

```bash
python -m unittest discover -s remote-agent-config -p 'test_*.py' -v
```

Run the skill validator when available, review the redacted dry-run, and execute
the real probe on an authorized target. Do not embed target credentials in tests.
