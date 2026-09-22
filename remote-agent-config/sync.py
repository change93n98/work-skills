#!/usr/bin/env python3
"""Render local Claude Code / Codex config and push it to remote SSH hosts.

Reads the (working) local config as the source of truth, strips anything
machine-specific (Windows paths, hooks, MCP servers), and writes portable
config over SSH so remote agents talk to the model API directly instead of
depending on a reverse tunnel back to the laptop.
"""

import argparse
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

HOME = Path.home()
CLAUDE_SRC = HOME / ".claude" / "settings.json"
CODEX_DIR = HOME / ".codex"
CODEX_SRC = CODEX_DIR / "config.toml"
AUTH_SRC = CODEX_DIR / "auth.json"
CATALOG_SRC = CODEX_DIR / "cc-switch-model-catalog.json"
SSH_CONFIG = HOME / ".ssh" / "config"

CODEX_TOP_KEYS = [
    "model_provider",
    "model",
    "model_reasoning_effort",
    "model_context_window",
    "model_auto_compact_token_limit",
    "model_catalog_json",
]

# cc-switch keeps its switchable provider presets here. Each preset's
# settings_config is the config it would write for its app, *before* cc-switch's
# local proxy rewrites the live files to point at 127.0.0.1 -- so it is the right
# source for a remote that must reach the upstream directly.
CC_SWITCH_DB = HOME / ".cc-switch" / "cc-switch.db"

# Deliberately does NOT match bare "token": keys like model_auto_compact_token_limit
# are tuning knobs, not credentials.
SECRET_RE = re.compile(
    r"(?i)(api[_-]?key|apikey|auth[_-]?token|access[_-]?token|refresh[_-]?token"
    r"|bearer[_-]?token|client[_-]?secret|password|passwd|credentials?)"
)


def _is_secret_key(key):
    k = str(key)
    return bool(SECRET_RE.search(k) or k.lower() in ("token", "secret", "key", "auth"))


def redact_secrets(obj):
    """Blank secret-looking values so --dry-run output can be shown to the user.

    The presets carry live credentials. Printing them to a terminal that gets
    pasted into chat is how keys leak, so scrub anything whose key looks secret.
    Numbers and booleans are left alone -- a tuning knob named *_token_limit is
    not a credential.
    """
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if _is_secret_key(k) and isinstance(v, (str, list, dict)) and v not in ("", [], {}):
                out[k] = "***REDACTED***"
            else:
                out[k] = redact_secrets(v)
        return out
    if isinstance(obj, list):
        return [redact_secrets(v) for v in obj]
    return obj


_TOML_SECRET_ASSIGN = re.compile(
    r'(?im)^(\s*[A-Za-z0-9_.-]*(?:api[_-]?key|apikey|auth[_-]?token|access[_-]?token'
    r'|refresh[_-]?token|bearer[_-]?token|secret|password|passwd|credential)'
    r'[A-Za-z0-9_.-]*\s*=\s*)'
    r'(".*?"|\'.*?\'|[^\s#]+)'
)
_TOML_NON_SECRET_VALUE = re.compile(r"^(?:[-+]?\d+(?:\.\d+)?|true|false)$", re.I)


def redact_toml(text):
    """Blank secret-looking TOML values (both "..." and '...' string forms).

    Skips bare numbers/booleans so `model_auto_compact_token_limit = 900000`
    survives intact.
    """
    if not text:
        return text

    def _sub(m):
        if _TOML_NON_SECRET_VALUE.match(m.group(2)):
            return m.group(0)
        return m.group(1) + '"***REDACTED***"'

    return _TOML_SECRET_ASSIGN.sub(_sub, text)


def log(msg):
    print(msg, flush=True)


SSH_OPTS = [
    "-o", "BatchMode=yes",
    "-o", "ConnectTimeout=10",
    "-o", "ServerAliveInterval=5",
    "-o", "ServerAliveCountMax=3",
    "-o", "ConnectionAttempts=2",
]

TRANSIENT = (
    "Connection reset", "Connection closed", "Connection refused",
    "kex_exchange", "Broken pipe", "timed out", "Timeout", "closed by remote",
)


def run(cmd, timeout=60, retries=3, delay=3, cwd=None, env=None):
    last = None
    for attempt in range(retries):
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                               cwd=cwd, env=env)
        except subprocess.TimeoutExpired:
            last = f"local timeout after {timeout}s"
            time.sleep(delay)
            continue
        if r.returncode == 0:
            return r
        last = r.stderr.strip() or r.stdout.strip()
        if not any(s in last for s in TRANSIENT):
            return r
        time.sleep(delay)
    return subprocess.CompletedProcess(cmd, 1, "", last or "failed")


def ssh(host, remote_cmd, check=True):
    r = run(["ssh", *SSH_OPTS, host, remote_cmd])
    if check and r.returncode != 0:
        raise RuntimeError(f"ssh {host} failed: {r.stderr.strip()}")
    return r


def scp_to(host, local_path, remote_path):
    # Run from the file's directory with a bare name: avoids Windows drive-letter
    # colons being misread by scp as the host separator.
    local_path = Path(local_path)
    r = run(["scp", "-q", *SSH_OPTS, local_path.name, f"{host}:{remote_path}"],
            cwd=str(local_path.parent))
    if r.returncode != 0:
        raise RuntimeError(f"scp -> {host}:{remote_path} failed: {r.stderr.strip()}")


# --- WSL targets ---------------------------------------------------------------
#
# A WSL distro is local: no ssh, no sshd, no ~/.ssh/config entry. File I/O goes
# through the \\wsl.localhost share and only the places that need real Linux
# semantics (chmod) shell out to wsl.exe.
#
# A distro running its own cc-switch keeps owning ~/.claude/settings.json -- that
# is what the `claude` CLI there reads. The VS Code extension, however, takes its
# config from the server's Machine/settings.json, which cc-switch does not manage;
# that is why the extension goes unconfigured while the CLI works. So a WSL target
# writes the extension config only, and leaves the CLI file alone.

def _wsl_env():
    # wsl.exe emits UTF-16 unless this is set.
    return dict(os.environ, WSL_UTF8="1")


def wsl_run(distro, cmd, check=True):
    r = run(["wsl.exe", "-d", distro, "--", "bash", "-c", cmd], env=_wsl_env())
    if check and r.returncode != 0:
        raise RuntimeError(f"wsl {distro}: {r.stderr.strip() or r.stdout.strip()}")
    return r


def wsl_unc(distro, linux_path):
    """Map a WSL-internal absolute path to the Windows share path."""
    return "//wsl.localhost/" + distro + "/" + str(linux_path).lstrip("/").replace("\\", "/")


def wsl_distros():
    """Installed WSL distro names, or [] when WSL is unavailable."""
    try:
        r = run(["wsl.exe", "-l", "-q"], timeout=20, env=_wsl_env())
    except Exception:
        return []
    if r.returncode != 0:
        return []
    # -l still emits UTF-16 on some builds even with WSL_UTF8.
    return [ln.strip() for ln in r.stdout.replace("\x00", "").splitlines() if ln.strip()]


def sync_wsl(distro, env_list, ts, force=False):
    """Merge claudeCode.environmentVariables into the distro's Machine settings.

    Returns "updated" or "skip". Raises on failure.
    """
    home = wsl_run(distro, 'printf %s "$HOME"').stdout.strip()
    if not home.startswith("/"):
        raise RuntimeError(f"could not read $HOME in distro {distro!r}")
    target = f"{home}/.vscode-server/data/Machine/settings.json"
    path = wsl_unc(distro, target)

    cur = {}
    if os.path.exists(path):
        try:
            parsed = json.loads(Path(path).read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                cur = parsed
        except (json.JSONDecodeError, OSError, UnicodeDecodeError):
            cur = {}
    if not force and cur.get("claudeCode.environmentVariables") == env_list:
        return "skip"

    if os.path.exists(path):
        shutil.copy2(path, f"{path}.bak-{ts}")
    cur["claudeCode.environmentVariables"] = env_list
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(cur, indent=4) + "\n", encoding="utf-8")
    # The file carries the API key, so it must not stay world-readable.
    wsl_run(distro, f"chmod 600 {shlex.quote(target)}")

    back = json.loads(dest.read_text(encoding="utf-8"))
    if back.get("claudeCode.environmentVariables") != env_list:
        raise RuntimeError("wrote Machine settings but the value did not stick")
    return "updated"


def redact_env_list(env_list):
    """Redact env entries whose *name* is credential-shaped.

    redact_secrets() keys off the dict key, and here the key is always the literal
    "value", so it would sail straight past a live ANTHROPIC_API_KEY.
    """
    out = []
    for kv in env_list:
        if isinstance(kv, dict) and _is_secret_key(kv.get("name", "")) and kv.get("value"):
            out.append({"name": kv.get("name"), "value": "***REDACTED***"})
        else:
            out.append(kv)
    return out


def loopback_host(url):
    m = re.match(r"^[a-z]+://([^/:]+)", str(url), re.IGNORECASE)
    host = m.group(1).lower() if m else str(url).lower()
    return host in ("127.0.0.1", "localhost", "::1", "0.0.0.0")


def parse_config(config_path):
    """Return ordered entries [{alias, hostname}] from ~/.ssh/config (enabled blocks)."""
    if not config_path.exists():
        raise SystemExit(f"no ssh config at {config_path}")
    entries = []
    current = []
    pat_host = re.compile(r"^\s*Host\s+(.+?)\s*$", re.IGNORECASE)
    pat_hn = re.compile(r"^\s*HostName\s+(\S+)", re.IGNORECASE)
    for line in config_path.read_text().splitlines():
        if line.lstrip().startswith("#"):
            continue
        m = pat_host.match(line)
        if m:
            current = []
            for alias in m.group(1).split():
                if any(c in alias for c in "*?"):
                    continue
                e = {"alias": alias, "hostname": None}
                entries.append(e)
                current.append(e)
            continue
        m = pat_hn.match(line)
        if m and current:
            for e in current:
                e["hostname"] = m.group(1)
    return entries


def enabled_hosts(entries, excludes):
    return [e["alias"] for e in entries if e["alias"] not in excludes]


def resolve_hosts(inputs, entries):
    """Map user input (alias, IP, or HostName) to ssh config aliases."""
    lookup = {}
    for e in entries:
        lookup.setdefault(e["alias"].lower(), e["alias"])
        if e["hostname"]:
            lookup.setdefault(e["hostname"].lower(), e["alias"])
    resolved, unknown = [], []
    for token in inputs:
        alias = lookup.get(token.strip().lower())
        if alias:
            if alias not in resolved:
                resolved.append(alias)
        elif token.strip():
            unknown.append(token.strip())
    if unknown:
        avail = ", ".join(f"{e['alias']} ({e['hostname']})" for e in entries if e["hostname"]) \
            or ", ".join(enabled_hosts(entries, set()))
        raise SystemExit("unknown host(s): " + ", ".join(unknown) + "\navailable: " + avail)
    return resolved


def toml_value(v):
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    return json.dumps(str(v))


def toml_key(k):
    return k if re.match(r"^[A-Za-z0-9_-]+$", k) else json.dumps(k)


def build_claude():
    if not CLAUDE_SRC.exists():
        raise SystemExit(f"missing source {CLAUDE_SRC}")
    data = json.loads(CLAUDE_SRC.read_text())
    return data


def strip_codex_toml(text):
    """Keep only the portable keys from a config.toml.

    The local file is Windows-flavoured and must not be copied raw: [windows],
    [projects.*], [mcp_servers*] and Windows paths only make sense on the laptop.
    Also drops proxy-only keys such as experimental_bearer_token, which would
    point a direct-connect remote back at a managed proxy.
    """
    try:
        data = tomllib.loads(text or "")
    except tomllib.TOMLDecodeError as e:
        raise SystemExit(f"config.toml is not valid TOML: {e}")
    out = []
    for k in CODEX_TOP_KEYS:
        if k in data:
            out.append(f"{toml_key(k)} = {toml_value(data[k])}")
    feats = data.get("features")
    if isinstance(feats, dict):
        out.append("")
        out.append("[features]")
        for k, v in feats.items():
            out.append(f"{toml_key(k)} = {toml_value(v)}")
    provider = data.get("model_provider")
    prov = (data.get("model_providers") or {}).get(provider, {})
    if prov:
        out.append("")
        out.append(f"[model_providers.{toml_key(provider)}]")
        for k in ("name", "wire_api", "requires_openai_auth", "base_url"):
            if k in prov:
                out.append(f"{toml_key(k)} = {toml_value(prov[k])}")
    return "\n".join(out) + "\n"


def build_codex():
    if not CODEX_SRC.exists():
        raise SystemExit(f"missing source {CODEX_SRC}")
    return strip_codex_toml(CODEX_SRC.read_text())


# --- cc-switch provider presets ------------------------------------------------

def load_providers(app_type=None, db_path=None):
    """Return cc-switch presets as [{id, app_type, name, category, is_current, settings}].

    `settings` is the parsed settings_config and holds live credentials -- never
    log it. Print only name/category/is_current.
    """
    db = Path(db_path) if db_path else CC_SWITCH_DB
    if not db.exists():
        raise SystemExit(
            f"no cc-switch database at {db}\n"
            "Install cc-switch or pass --db; use --from-live to sync the live files instead.")
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    try:
        q = ("SELECT id, app_type, name, category, is_current, sort_index, settings_config "
             "FROM providers")
        args = ()
        if app_type:
            q += " WHERE app_type = ?"
            args = (app_type,)
        q += " ORDER BY app_type, sort_index, name"
        rows = []
        for r in con.execute(q, args):
            try:
                settings = json.loads(r["settings_config"] or "{}")
            except json.JSONDecodeError:
                settings = {}
            rows.append({
                "id": r["id"],
                "app_type": r["app_type"],
                "name": r["name"],
                "category": r["category"],
                "is_current": bool(r["is_current"]),
                "settings": settings if isinstance(settings, dict) else {},
            })
        return rows
    finally:
        con.close()


def resolve_provider(name, providers, app_type):
    """Map a user-typed preset name to one provider (exact, then unique substring)."""
    needle = name.strip().lower()
    exact = [p for p in providers if p["name"].lower() == needle]
    if len(exact) == 1:
        return exact[0]
    partial = [p for p in providers if needle in p["name"].lower()]
    if len(partial) == 1:
        return partial[0]
    if len(partial) > 1:
        raise SystemExit(
            f"ambiguous {app_type} provider {name!r}: "
            + ", ".join(p["name"] for p in partial))
    raise SystemExit(
        f"unknown {app_type} provider {name!r}\navailable: {format_provider_list(providers)}")


def current_provider(providers, app_type):
    for p in providers:
        if p["is_current"]:
            return p
    raise SystemExit(
        f"cc-switch has no current {app_type} provider; pass --{app_type}-provider\n"
        f"available: {format_provider_list(providers)}")


def format_provider_list(providers):
    return ", ".join(("*" if p["is_current"] else "") + p["name"] for p in providers) or "(none)"


def pick_provider(app_type, name, db_path=None):
    providers = load_providers(app_type, db_path)
    if not providers:
        raise SystemExit(f"cc-switch has no {app_type} providers")
    return resolve_provider(name, providers, app_type) if name else current_provider(providers, app_type)


def list_providers(targets, db_path=None):
    """Print selectable cc-switch presets for the chosen targets."""
    apps = []
    if targets in ("all", "claude"):
        apps.append("claude")
    if targets in ("all", "codex"):
        apps.append("codex")
    for app in apps:
        providers = load_providers(app, db_path)
        print(f"[{app}]")
        for p in providers:
            mark = "*" if p["is_current"] else " "
            cat = f"  ({p['category']})" if p["category"] else ""
            print(f"  {mark} {p['name']}{cat}")
        print()
    print("* = 当前激活 (current). Match by name; a unique substring is enough.")


CODEX_MODEL_DEFAULTS = {
    "additional_speed_tiers": [],
    "availability_nux": None,
    "default_reasoning_summary": "none",
    "effective_context_window_percent": 95,
    "experimental_supported_tools": [],
    "service_tiers": [],
    "shell_type": "shell_command",
    "support_verbosity": False,
    "supported_in_api": True,
    "supports_image_detail_original": False,
    "supports_parallel_tool_calls": False,
    "supports_reasoning_summaries": True,
    "supports_search_tool": False,
    "truncation_policy": {"limit": 10000, "mode": "bytes"},
    "upgrade": None,
    "visibility": "list",
}

DEFAULT_CODEX_INSTRUCTIONS = (
    "You are Codex, a coding agent. You and the user share the same workspace "
    "and collaborate to achieve the user's goals."
)


def expand_model_catalog(compact):
    """Expand cc-switch's compact modelCatalog into Codex's model_catalog schema.

    cc-switch stores {model, displayName, contextWindow, ...}; Codex wants the long
    descriptor list. The extra fields take the defaults Codex itself uses, so the
    remote agent does not have to guess at truncation or modality policy.
    """
    if not compact:
        return None
    models = compact.get("models") if isinstance(compact, dict) else None
    if not models:
        return None
    out = []
    for i, m in enumerate(models):
        if not isinstance(m, dict):
            continue
        slug = m.get("model") or m.get("slug")
        if not slug:
            continue
        window = int(m.get("contextWindow") or m.get("context_window") or 200000)
        levels = m.get("reasoningLevels") or m.get("supported_reasoning_levels")
        if not isinstance(levels, list) or not levels:
            levels = [{"description": "Enabled Thinking", "effort": "high"}]
        entry = dict(CODEX_MODEL_DEFAULTS)
        entry.update({
            "base_instructions": m.get("baseInstructions") or DEFAULT_CODEX_INSTRUCTIONS,
            "context_window": window,
            "max_context_window": window,
            "default_reasoning_level": m.get("defaultReasoningLevel") or "high",
            "description": m.get("displayName") or slug,
            "display_name": m.get("displayName") or slug,
            "input_modalities": m.get("inputModalities") or ["text", "image"],
            "priority": 1000 + i,
            "slug": slug,
            "supported_reasoning_levels": [
                (x if isinstance(x, dict) and "effort" in x
                 else {"description": "Thinking", "effort": str(x)})
                for x in levels
            ],
        })
        out.append(entry)
    return {"models": out} if out else None


def render_claude(preset, include_hooks=False, live=None):
    """Build the remote ~/.claude/settings.json from a cc-switch claude preset.

    A claude preset's settings_config is itself a settings.json document, so this
    is mostly a passthrough. Hooks are dropped by default because they usually
    reference tools that do not exist on the server.
    """
    settings = dict(preset.get("settings") or {})
    env = settings.get("env") or {}
    if not env.get("ANTHROPIC_BASE_URL"):
        # An "official" preset stores only {"env": {}} -- pushing it would wipe a
        # working remote settings.json with an empty shell and no way to reach an
        # API. Refuse rather than leave the node broken.
        raise SystemExit(
            f"cc-switch claude provider {preset['name']!r} has no ANTHROPIC_BASE_URL "
            "(official-login style), so there is nothing to render for a remote that "
            "must call the API directly. Pick a provider with an explicit base_url.")
    if include_hooks:
        if live and "hooks" in live:
            settings["hooks"] = live["hooks"]
    else:
        settings.pop("hooks", None)
    return settings


def render_codex(preset, live_catalog_text=None):
    """Build (config_toml, auth_json, catalog_json) from a cc-switch codex preset.

    A codex preset stores {auth, config, modelCatalog}: `config` is the config.toml
    text cc-switch would write, `auth` is the auth.json document, and modelCatalog
    is the compact model list that has to be expanded before shipping.
    """
    settings = preset.get("settings") or {}
    raw = (settings.get("config") or "").strip()
    if not raw:
        raise SystemExit(
            f"cc-switch codex provider {preset['name']!r} has an empty config "
            "(official-OAuth style), so there is nothing to render for a remote that "
            "must call the API directly. Pick a provider with an explicit base_url.")

    toml_text = strip_codex_toml(raw)
    catalog = expand_model_catalog(settings.get("modelCatalog"))
    if catalog is None and live_catalog_text:
        # Fall back to the live expanded catalog so a TOML referencing
        # model_catalog_json does not point at a file that was never written.
        try:
            parsed = json.loads(live_catalog_text)
            catalog = parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            catalog = None
    if catalog is None and re.search(r"(?m)^\s*model_catalog_json\s*=", toml_text):
        toml_text = re.sub(r"(?m)^\s*model_catalog_json\s*=\s*.*\n?", "", toml_text).strip() + "\n"
        log("   note: no model catalog to ship, dropped model_catalog_json from config.toml")

    auth = settings.get("auth")
    if isinstance(auth, dict):
        auth_txt = json.dumps(auth, indent=2) + "\n"
    elif isinstance(auth, str) and auth.strip():
        auth_txt = auth if auth.endswith("\n") else auth + "\n"
    else:
        auth_txt = None
    catalog_txt = json.dumps(catalog, indent=2) + "\n" if catalog else None
    return toml_text, auth_txt, catalog_txt


def remote_home(host):
    return ssh(host, 'printf %s "$HOME"').stdout.strip()


def remote_read(host, path):
    r = ssh(host, f'cat {shlex.quote(path)} 2>/dev/null', check=False)
    text = r.stdout
    return text if text.strip() else None


def json_equal(remote_text, desired_text):
    if remote_text is None:
        return False
    try:
        return json.loads(remote_text) == json.loads(desired_text)
    except (json.JSONDecodeError, TypeError):
        return False


def norm_text(text):
    if text is None:
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.splitlines() if line.strip())


def text_equal(remote_text, desired_text):
    return remote_text is not None and norm_text(remote_text) == norm_text(desired_text)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hosts", help="comma-separated host aliases/IPs (default: all in ~/.ssh/config)")
    ap.add_argument("--targets", choices=["all", "claude", "codex"],
                    help="which agent config to sync (default: all, or claude when the "
                         "run targets WSL distros only)")
    ap.add_argument("--claude-provider",
                    help="cc-switch claude preset to sync (default: the current one)")
    ap.add_argument("--codex-provider",
                    help="cc-switch codex preset to sync (default: the current one)")
    ap.add_argument("--list-providers", action="store_true",
                    help="list cc-switch provider presets and exit")
    ap.add_argument("--from-live", action="store_true",
                    help="read the live ~/.claude and ~/.codex files instead of cc-switch presets")
    ap.add_argument("--db", help="override path to cc-switch.db")
    ap.add_argument("--exclude", default="", help="comma-separated aliases to skip")
    ap.add_argument("--wsl", help="comma-separated WSL distros to sync the VS Code "
                                  "extension config into (local: UNC + wsl.exe, no ssh)")
    ap.add_argument("--dry-run", action="store_true", help="print generated config, do not touch remotes")
    ap.add_argument("--force", action="store_true", help="re-write even when the remote is already up to date")
    ap.add_argument("--no-vscode", action="store_true", help="do not touch VS Code Machine settings")
    ap.add_argument("--include-hooks", action="store_true", help="keep Claude hooks (may fail remotely)")
    ap.add_argument("--env", action="append", default=[], metavar="KEY=VALUE",
                    help="override a claude env entry (repeatable). Use it for values that "
                         "must differ per target, e.g. ANTHROPIC_CUSTOM_HEADERS's session name")
    ap.add_argument("--allow-loopback", action="store_true",
                    help="permit base_url pointing at 127.0.0.1/localhost (normally refused)")
    ap.add_argument("--list", action="store_true", help="list target hosts and exit")
    args = ap.parse_args()

    # A WSL distro only ever receives the VS Code extension config, and that comes
    # from the claude preset. So a WSL-only run defaults to claude rather than
    # "all": rendering codex would be wasted work, and an official-login codex
    # preset would abort the run over a target that has nothing to do with codex.
    wsl_targets = [x.strip() for x in (args.wsl or "").split(",") if x.strip()]
    if args.targets is None:
        args.targets = "claude" if (wsl_targets and not args.hosts) else "all"

    do_claude = args.targets in ("all", "claude")
    do_codex = args.targets in ("all", "codex")
    do_vscode = do_claude and not args.no_vscode

    if args.list_providers:
        list_providers(args.targets, args.db)
        return

    if wsl_targets and not do_claude:
        raise SystemExit("--wsl 写的是 VS Code 扩展的配置，来自 claude 预设，"
                         "单独指定 --targets codex 时没有可写的内容")

    entries = parse_config(SSH_CONFIG)
    excludes = {x.strip() for x in args.exclude.split(",") if x.strip()}
    if args.hosts:
        hosts = resolve_hosts([x for x in args.hosts.split(",") if x.strip()], entries)
    elif wsl_targets:
        # WSL is local. Without an explicit --hosts, do not fan out to every
        # ssh host just because --wsl was passed.
        hosts = []
    else:
        hosts = enabled_hosts(entries, excludes)

    if args.list:
        for e in entries:
            print(f"{e['alias']}\t{e['hostname'] or ''}")
        for d in wsl_distros():
            print(f"wsl:{d}\t(WSL 发行版，本机；只同步 VS Code 扩展配置)")
        if args.hosts:
            log("selected: " + ", ".join(hosts))
        return
    if not hosts and not wsl_targets:
        raise SystemExit("no target hosts")

    claude, codex_toml, env, env_list = None, None, {}, []
    auth_txt = catalog_txt = None
    if do_claude:
        if args.from_live:
            claude = build_claude()
            if not args.include_hooks:
                claude.pop("hooks", None)
        else:
            prov = pick_provider("claude", args.claude_provider, args.db)
            log(f"claude preset: {prov['name']}"
                + (" (current)" if prov["is_current"] else ""))
            live = build_claude() if args.include_hooks and CLAUDE_SRC.exists() else None
            claude = render_claude(prov, include_hooks=args.include_hooks, live=live)
        # Overrides land on the rendered settings *before* the loopback check and
        # before env_list is derived, so one flag covers both the file and the
        # VS Code Machine settings. In-place: `env` is the dict inside `claude`.
        env = claude.setdefault("env", {})
        for item in args.env:
            if "=" not in item:
                raise SystemExit(f"--env 需要 KEY=VALUE 形式: {item!r}")
            k, v = item.split("=", 1)
            env[k.strip()] = v
            log(f"env override: {k.strip()}")
        env_list = [{"name": k, "value": v} for k, v in env.items()]
    if do_codex:
        if args.from_live:
            codex_toml = build_codex()
            auth_txt = AUTH_SRC.read_text() if AUTH_SRC.exists() else None
            catalog_txt = CATALOG_SRC.read_text() if CATALOG_SRC.exists() else None
        else:
            prov = pick_provider("codex", args.codex_provider, args.db)
            log(f"codex preset: {prov['name']}"
                + (" (current)" if prov["is_current"] else ""))
            live_cat = CATALOG_SRC.read_text() if CATALOG_SRC.exists() else None
            codex_toml, auth_txt, catalog_txt = render_codex(prov, live_catalog_text=live_cat)

    bad = []
    if do_claude and loopback_host(env.get("ANTHROPIC_BASE_URL", "")):
        bad.append(f"claude ANTHROPIC_BASE_URL={env.get('ANTHROPIC_BASE_URL')}")
    if do_codex and codex_toml:
        m = re.search(r'base_url\s*=\s*"([^"]+)"', codex_toml)
        if m and loopback_host(m.group(1)):
            bad.append(f"codex base_url={m.group(1)}")
    if bad and not args.allow_loopback:
        raise SystemExit(
            "refusing to push loopback base_url (would point the remote at itself):\n  "
            + "\n  ".join(bad)
            + "\nFix the local config to a reachable upstream, or pass --allow-loopback.")

    if args.dry_run:
        log(f"targets: {args.targets}")
        if do_claude:
            log("=== claude ~/.claude/settings.json (secrets redacted) ===")
            log(json.dumps(redact_secrets(claude), indent=2))
        if do_codex:
            log("=== codex ~/.codex/config.toml (secrets redacted) ===")
            log(redact_toml(codex_toml))
            log("=== auth.json: %s, catalog: %s ===" % (auth_txt is not None, catalog_txt is not None))
        if wsl_targets:
            log("=== WSL: <home>/.vscode-server/data/Machine/settings.json "
                "claudeCode.environmentVariables (secrets redacted) ===")
            log(json.dumps(redact_env_list(env_list), indent=2, ensure_ascii=False))
        log("hosts: " + ", ".join(hosts + ["wsl:" + d for d in wsl_targets]))
        return

    ts = time.strftime("%Y%m%d-%H%M%S")
    tmp = Path(tempfile.mkdtemp(prefix="agent-sync-"))
    claude_txt = json.dumps(claude, indent=2) + "\n" if do_claude else None
    if do_claude:
        (tmp / "settings.json").write_text(claude_txt)
    if do_codex:
        (tmp / "config.toml").write_text(codex_toml)
        if auth_txt is not None:
            (tmp / "auth.json").write_text(auth_txt)
        if catalog_txt is not None:
            (tmp / "cc-switch-model-catalog.json").write_text(catalog_txt)

    failures = []
    skipped = 0
    for host in hosts:
        log(f"== {host} ==")
        try:
            home = remote_home(host)
            machine = f"{home}/.vscode-server/data/Machine"

            if not args.force:
                same = True
                if do_claude:
                    same = same and json_equal(
                        remote_read(host, f"{home}/.claude/settings.json"), claude_txt)
                if do_codex:
                    same = same and text_equal(
                        remote_read(host, f"{home}/.codex/config.toml"), codex_toml)
                    if auth_txt is not None:
                        same = same and json_equal(
                            remote_read(host, f"{home}/.codex/auth.json"), auth_txt)
                    if catalog_txt is not None:
                        same = same and json_equal(
                            remote_read(host, f"{home}/.codex/cc-switch-model-catalog.json"), catalog_txt)
                if do_vscode:
                    ms_remote = remote_read(host, f"{machine}/settings.json")
                    ms_ok = False
                    if ms_remote:
                        try:
                            ms_ok = json.loads(ms_remote).get("claudeCode.environmentVariables") == env_list
                        except (json.JSONDecodeError, AttributeError):
                            ms_ok = False
                    same = same and ms_ok
                if same:
                    log(f"   home={home}  已是最新，跳过 (up to date)")
                    skipped += 1
                    continue

            dirs = []
            if do_claude:
                dirs.append(f"{home}/.claude")
            if do_codex:
                dirs.append(f"{home}/.codex")
            if do_vscode:
                dirs.append(machine)
            if dirs:
                ssh(host, "mkdir -p " + " ".join(shlex.quote(d) for d in dirs))

            backs = []
            if do_claude:
                backs.append(f"{home}/.claude/settings.json")
            if do_codex:
                backs += [f"{home}/.codex/config.toml", f"{home}/.codex/auth.json",
                          f"{home}/.codex/cc-switch-model-catalog.json"]
            if do_vscode:
                backs.append(f"{machine}/settings.json")
            if backs:
                ssh(host, "for f in " + " ".join(shlex.quote(b) for b in backs)
                    + f'; do [ -e "$f" ] && cp -f "$f" "$f.bak-{ts}"; done; true')

            if do_claude:
                scp_to(host, tmp / "settings.json", f"{home}/.claude/settings.json")
            if do_codex:
                scp_to(host, tmp / "config.toml", f"{home}/.codex/config.toml")
                if auth_txt is not None:
                    scp_to(host, tmp / "auth.json", f"{home}/.codex/auth.json")
                if catalog_txt is not None:
                    scp_to(host, tmp / "cc-switch-model-catalog.json",
                           f"{home}/.codex/cc-switch-model-catalog.json")

            cmds = []
            if do_claude:
                cmds.append(f"chmod 700 {shlex.quote(home + '/.claude')}; "
                            f"chmod 600 {shlex.quote(home + '/.claude/settings.json')}")
            if do_codex:
                cmds.append(f"chmod 700 {shlex.quote(home + '/.codex')}; "
                            f"chmod 600 {shlex.quote(home + '/.codex/config.toml')} "
                            f"{shlex.quote(home + '/.codex/auth.json')}")
            if cmds:
                ssh(host, "; ".join(cmds) + "; true")

            if do_vscode:
                cur = ssh(host, f'cat {shlex.quote(machine + "/settings.json")} 2>/dev/null', check=False).stdout
                try:
                    ms = json.loads(cur) if cur.strip() else {}
                    if not isinstance(ms, dict):
                        ms = {}
                except json.JSONDecodeError:
                    ms = {}
                ms["claudeCode.environmentVariables"] = env_list
                (tmp / "machine-settings.json").write_text(json.dumps(ms, indent=4) + "\n")
                scp_to(host, tmp / "machine-settings.json", f"{machine}/settings.json")
                ssh(host, f"chmod 600 {shlex.quote(machine + '/settings.json')}; true")

            checks = []
            if do_claude:
                checks.append(f'grep -q ANTHROPIC_BASE_URL {shlex.quote(home + "/.claude/settings.json")}')
            if do_codex:
                checks.append(f'grep -q base_url {shlex.quote(home + "/.codex/config.toml")}')
            verify = ssh(host, " && ".join(checks) + " && echo VERIFY_OK || echo VERIFY_FAIL",
                         check=False).stdout.strip() if checks else "VERIFY_OK"
            log(f"   home={home}  {verify}")
            if verify != "VERIFY_OK":
                failures.append(host)
        except Exception as e:
            log(f"   FAILED: {e}")
            failures.append(host)

    for distro in wsl_targets:
        log(f"== wsl:{distro} ==")
        try:
            if sync_wsl(distro, env_list, ts, force=args.force) == "skip":
                log("   已是最新，跳过 (up to date)")
                skipped += 1
            else:
                log("   Machine settings 已更新；VS Code 窗口需重新加载才会生效")
        except Exception as e:
            log(f"   FAILED: {e}")
            failures.append(f"wsl:{distro}")

    log("")
    if failures:
        log("failed hosts: " + ", ".join(failures))
        sys.exit(1)
    updated = len(hosts) + len(wsl_targets) - skipped
    log(f"done: {updated} updated, {skipped} already up to date ({args.targets})")


if __name__ == "__main__":
    main()
