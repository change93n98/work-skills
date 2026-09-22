---
name: cc-switch-claude-401
description: 修复 cc-switch 打开的 Claude CLI 报 401(Invalid/Missing API key)或启动警告 "Both ANTHROPIC_AUTH_TOKEN and ANTHROPIC_API_KEY set"。当用户提到 cc-switch + Claude 401、密钥冲突、Invalid API key、Missing API key、auth may not work as expected 时使用。覆盖检查、定位失效 key、修复 token 字段放错位置、同步 ~/.claude/settings.json。
---

# 修复 cc-switch Claude CLI 401

背景知识(2026-09-21 实测):cc-switch 会把当前激活 provider 的 env 写到
`~/.claude/settings.json` 并生成临时配置 `C:\Users\92757\AppData\Local\Temp\claude_<provider-id>_<cc-switch-pid>.json`。
Claude Code 的认证头由变量名决定:

- token 在 `ANTHROPIC_API_KEY` → 发 `x-api-key: <token>` 头
- token 在 `ANTHROPIC_AUTH_TOKEN` → 发 `Authorization: Bearer <token>` 头

**两个变量并存时 Claude Code 优先用 `ANTHROPIC_API_KEY`**,并打警告
"Both ANTHROPIC_AUTH_TOKEN and ANTHROPIC_API_KEY set"。

cc-switch 的 "OpenCode" provider(端点 `https://opencode.ai/zen/go`)**只认
`x-api-key` 头**,还要求自定义头 `x-opencode-session`(配置里已有
`ANTHROPIC_CUSTOM_HEADERS: x-opencode-session: windows-cc-switch`,别动它)。
所以该 provider 的 token **必须放 `ANTHROPIC_API_KEY` 字段**;放
`ANTHROPIC_AUTH_TOKEN` 会报 401 "Missing API key"(key 有效但认证头不对)。

## 报错 → 病因速查

| 报错/现象 | 病因 | 修法 |
|---|---|---|
| 401 "Invalid API key" + "Both ... set" 警告 | 两个变量都有值,Claude Code 优先用的 `ANTHROPIC_API_KEY` 是失效的旧 key | 删失效 key(见 §2),有效 token 按 §3 归位 |
| 401 "Missing API key",无警告 | 只剩 `AUTH_TOKEN`,但端点只认 `x-api-key` 头 | 把 token 移到 `API_KEY` 字段(见 §3) |
| 其他 401 且端点不是 opencode zen | token 本身失效,或 base_url 错 | 让用户从发 token 的渠道重新拿 key |

## 1. 先收集证据(三处配置 + 实测)

```bash
# ① 临时配置文件(报错标题行里有路径,provider-id 和 cc-switch 进程 PID 都在文件名里)
#    看它 env 里有哪几个 KEY/TOKEN 变量
# ② 全局同步文件 ~/.claude/settings.json 的 env 段(第一轮修复常漏这里!)
# ③ cc-switch 数据库(注意:改之前必须先关 cc-switch 进程,防退出时内存态覆盖)
python -c "
import sqlite3, json
con = sqlite3.connect(r'C:/Users/92757/.cc-switch/cc-switch.db')
# 当前激活 provider 的 id 在 ~/.cc-switch/settings.json 的 currentProviderClaude
cur = con.execute(\"select id, name, settings_config from providers where app_type='claude'\")
for i, n, cfg in cur.fetchall():
    env = json.loads(cfg).get('env', {})
    print(i, n, {k: str(v)[:12] for k, v in env.items() if 'KEY' in k or 'TOKEN' in k})
"
# ④ 用 curl 实测哪把 key 有效、认证头用哪种(x-api-key vs Bearer),别只猜
curl -s -X POST "<base_url>/v1/messages" -H "x-api-key: <token>" \
  -H "x-opencode-session: windows-cc-switch" -H "anthropic-version: 2023-06-01" \
  -H "content-type: application/json" \
  -d '{"model":"<ANTHROPIC_MODEL 不带[1M]后缀>","max_tokens":16,"messages":[{"role":"user","content":"hi"}]}'
```

注意对比历史: `~/.cc-switch/cc-switch.db.bak-<日期>` 备份库可以查这个 provider
以前用的 key,判断哪把是新的、哪把是被换下来的失效 key。

## 2. 删失效 key(密钥冲突时)

1. 关 cc-switch:`powershell -Command "Stop-Process -Name cc-switch"`。
2. 从数据库该 provider 的 `settings_config` JSON `env` 里删除失效的
   `ANTHROPIC_API_KEY`(或 `ANTHROPIC_AUTH_TOKEN`,按 §1 实测结果定删哪个)。
3. **同步删 `~/.claude/settings.json` env 段里的同一个 key**——cc-switch 只在
   切换 provider 时才重写这个文件,改库不会自动同步,漏了它 CLI 照样 401。
4. 可用旧 key 前缀 grep 所有 claude 配置确认清干净:
   `grep -rl "<旧key前8位>" ~/.claude/*.json ~/.claude.json`
5. 重启 cc-switch,让用户**关掉旧 CLI 窗口重新开**。

## 3. token 字段归位(认证头不对时)

按端点要求放字段(OpenCode zen 必须 `ANTHROPIC_API_KEY`;Anthropic 官方端点用
`ANTHROPIC_AUTH_TOKEN` + base_url 时也常见)。数据库和
`~/.claude/settings.json` 两处一起改,保持一致:

```python
env.pop('ANTHROPIC_AUTH_TOKEN', None); env['ANTHROPIC_API_KEY'] = token
# settings.json 同样处理,两处 token 必须相同
```

## 4. 验证与收尾

- 用户重新打开 CLI,确认无警告、对话正常。
- 提醒用户:以后更新 token 走 cc-switch 界面"编辑 provider",整体替换 env,
  且**填到 API Key 栏**(OpenCode provider);不要手动往单个变量塞,避免新旧
  key 各占一字段。
