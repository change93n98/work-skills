---
name: remote-agent-config
description: Push a Claude Code / Codex model config to remote SSH hosts in ~/.ssh/config so remote agents call the model API directly instead of a reverse tunnel back to the laptop. Also writes the VS Code extension config into a local WSL distro (`--wsl`), where a distro-local cc-switch covers only the CLI and leaves the extension unconfigured. Renders from a chosen cc-switch provider preset (DeepSeek / OpenCode / Xiaomi MiMo / official / ...), so you pick which of several saved providers each server gets. Use whenever the user wants to sync, deploy, or switch claude/codex config on servers or in WSL, get the VS Code Claude Code extension working on a WSL/remote host, choose between cc-switch providers or "换个模型/换个渠道", remove the 127.0.0.1:15721 / RemoteForward dependency, refresh a remote ANTHROPIC_API_KEY or OPENAI_API_KEY, or fix "remote agent dies when laptop closes".
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

## Required interaction (do this first)

When this skill is invoked, do **not** pick hosts, targets, or cc-switch presets
on your own. Ask the user with the `question` tool, and **ask in Chinese** (the
user is Chinese-speaking). Run `python3 "$S" --list` and
`python3 "$S" --list-providers` first, and show the available nodes and presets,
then ask:

1. **节点选择** — question text: `要同步到哪个节点？`
   - `全部节点` — `~/.ssh/config` 中启用的所有 Host
   - `指定节点` — 输入别名或 IP 均可，支持逗号分隔多个
   - `WSL 发行版` — `--list` 输出里 `wsl:<发行版>` 那几行；本机、不走 ssh，
     且只写 VS Code 扩展的配置（见下方 WSL 一节）
2. **同步内容** — question text: `要同步哪份配置？`
   - `全部（claude + codex）` — 推荐
   - `仅 Claude`
   - `仅 Codex`
3. **cc-switch 预设** — ask once per agent covered by step 2 (so `仅 Claude` asks
   one question, `全部` asks two):
   - Claude: question text: `Claude 用哪个 cc-switch 预设？`
   - Codex: question text: `Codex 用哪个 cc-switch 预设？`
   - The first option is always `当前激活（<name>）`; then one option per remaining
     preset from `--list-providers`. Do not reorder or rename the presets.

Then run sync.py with the answers, e.g.
`--hosts 172.16.240.13 --targets claude --claude-provider DeepSeek`.

Skip the questions only if the user's message already names the host(s), the
target, and the preset. Keep your own progress messages in Chinese too.

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
(`claudeCode.environmentVariables`) so the VS Code extension connects directly
too.

For each host it: creates dirs, backs up existing files to
`<file>.bak-YYYYmmdd-HHMMSS`, uploads via `scp`, `chmod 600`, then verifies.

### WSL targets (`--wsl <发行版>`)

A WSL distro is local: no ssh, no sshd, no `~/.ssh/config` entry. File I/O goes
through the `\\wsl.localhost\<distro>` share and only `chmod` shells out to
`wsl.exe -d <distro>`.

This target exists for the case where the distro runs its **own** cc-switch. That
cc-switch owns `~/.claude/settings.json`, so the `claude` CLI there works fine —
but the VS Code Claude Code extension does not read that file. It takes its config
from the server's `~/.vscode-server/data/Machine/settings.json`
(`claudeCode.environmentVariables`), which cc-switch does not manage. That is the
file left unconfigured.

So a WSL target writes **only** the extension file and deliberately leaves
`~/.claude/settings.json` alone. Consequence: the extension follows whichever
preset you pick here, while the CLI keeps following the distro's own cc-switch —
pick the same provider if you want them to agree. Reload the VS Code window for
the extension to pick it up.

`--wsl` never fans out to the ssh hosts: a run with `--wsl` and no `--hosts`
targets the distro alone.

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

Before touching anything, the script compares the desired config against what is
already on the remote (JSON is compared structurally, TOML text is normalised).
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
python3 "$S" --wsl <发行版>                # WSL: VS Code extension config only (Windows only)
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

If you edit one copy, copy the change to the other three.

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
- Existing remote files are backed up, not merged, except the Machine settings
  JSON which is merged (other keys are preserved).
