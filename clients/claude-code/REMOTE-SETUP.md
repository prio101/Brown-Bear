# Connecting another machine to Brown Bear

Follow this on the machine you want to connect. Takes about two minutes.

## What you need before you start

| Value | Where to get it |
|---|---|
| Gateway URL | Fixed: **`https://brownbear.frostmangobox.com`**. Nothing to look up |
| Edge token | On the Brown Bear host: `grep BB_EDGE_TOKEN /home/prio/work/Brown-Bear/.env` |
| Model id | Must be **identical** on every machine. Use `claude-opus-5` |

The URL is permanent — a named Cloudflare tunnel, not a `trycloudflare.com`
quick tunnel. It survives host restarts and reboots, so once a machine is set up
you never re-point it.

The machine needs `python3` and `curl`. It does **not** need `jq`, `pip`, Docker,
or network access to anything but the tunnel.

## Option A — one-shot installer (recommended)

Get `install-remote.sh` onto the machine, then run it. It writes both hooks,
merges the Claude Code config without disturbing existing settings, backs up your
current `settings.json`, and verifies the gateway.

```bash
# transfer it however suits you:
scp you@bb-host:~/work/Brown-Bear/clients/claude-code/install-remote.sh .
#   ...or open the file, copy it, and paste into a new file on the target machine

export BB_GATEWAY_URL="https://brownbear.frostmangobox.com"
export BB_EDGE_TOKEN="<the token>"
export BB_MODEL="claude-opus-5"

bash install-remote.sh
```

It prompts for the URL and token if you skip the exports. Safe to re-run — it
updates in place rather than adding duplicates, and it refuses to touch a
`settings.json` that is already malformed rather than clobbering it.

## Option B — by hand

### 1. Create the directory and copy the two hooks

```bash
mkdir -p ~/.claude/bb
# copy bb_context.py and bb_exchange.py from
# Brown-Bear/clients/claude-code/ into ~/.claude/bb/
chmod +x ~/.claude/bb/bb_context.py ~/.claude/bb/bb_exchange.py
```

### 2. Store the configuration

```bash
cat > ~/.claude/bb/env.sh <<'EOF'
export BB_GATEWAY_URL="https://brownbear.frostmangobox.com"
export BB_EDGE_TOKEN="<the token>"
export BB_MODEL="claude-opus-5"
EOF
chmod 600 ~/.claude/bb/env.sh

# load it in every shell
echo '[ -f "$HOME/.claude/bb/env.sh" ] && . "$HOME/.claude/bb/env.sh"' >> ~/.bashrc
. ~/.claude/bb/env.sh
```

Keep the token in `env.sh`, not in `settings.json` — settings files get shared
and committed.

### 3. Add the hooks to `~/.claude/settings.json`

**Merge** this into the existing file; do not replace it. If the file has no
`hooks` key yet, add the whole block.

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/bb/bb_context.py",
            "timeout": 10,
            "statusMessage": "Asking Brown Bear for context..."
          }
        ]
      }
    ],
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 ~/.claude/bb/bb_exchange.py",
            "timeout": 15,
            "async": true
          }
        ]
      }
    ]
  }
}
```

`async: true` keeps storage off the critical path, so you never wait for Brown
Bear after a turn ends.

### 4. Reload Claude Code

Open `/hooks` once, or restart Claude Code. The settings watcher only watches
directories that had a settings file when the session started, so a brand-new
`hooks` block will not be picked up mid-session.

## Verify

```bash
# 1. gateway reachable and ready?
curl -s -H "Authorization: Bearer $BB_EDGE_TOKEN" "$BB_GATEWAY_URL/ext/health"
#    expect: {"ready":true, ... "embedding_model":"nomic-embed-text"}

# 2. does the hook produce hook JSON for something already cached?
echo '{"prompt":"a question you have asked before"}' | python3 ~/.claude/bb/bb_context.py

# 3. dashboard in a browser — user "bb", the token as the password
open "$BB_GATEWAY_URL"
```

Then use Claude Code normally. You will see `Brown Bear cache hit (0.97)` when
one lands, and **nothing at all** otherwise — the hooks are deliberately quiet.

## When nothing seems to happen

Silence is a valid outcome: no cache hit and nothing retrievable means no output.
To see what Claude Code is actually sending:

```bash
export BB_HOOK_DEBUG=1
# use Claude Code once, then:
cat "${TMPDIR:-/tmp}/bb-hook-input.jsonl"
```

If the prompt field is missing from that dump, the hook's field detection needs
adjusting for your Claude Code version — it reads `prompt`, `user_prompt`,
`message`, then `text`.

The hooks **fail open by design**: an unreachable gateway, a wrong token, a
timeout, or malformed JSON all produce no output and let Claude proceed. That
means a misconfiguration is invisible unless you check. Run the verification
above rather than assuming.

## Things to know

**`BB_MODEL` must match everywhere.** Cache hits are scoped by project *and*
model. If this machine says `claude-opus-5` and another leaves it unset
(defaulting to `claude`), the two will never share a single hit — each stores
under its own scope.

**Every prompt and answer leaves the machine.** The context hook sends your
prompt to Brown Bear; the Stop hook sends the prompt and the full response and
stores them. That is the feature, but decide deliberately. `BB_NO_STORE=1` meters
without storing; `BB_STORE_MIN_CHARS` keeps trivial answers out.

**Cache hits do not save tokens in the default mode.** `inject` adds the cached
answer as context and Claude still answers — you gain grounding, not spend.
`BB_CACHE_MODE=block` is the only mode that costs zero tokens, and the only one
where a wrong hit is shown to you as though it were an answer.

**The URL is stable, so `env.sh` is write-once.** `BB_GATEWAY_URL` should never
need changing again. If the gateway goes unreachable, the fault is on the host —
the tunnel, the edge, or the app — not on this machine, so don't start by
editing config here. On the host:

```bash
systemctl status cloudflared          # tunnel up? connections registered?
docker compose ps                     # edge and app running?
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8081/ext/health
#   401 = edge healthy and correctly refusing an unauthenticated request
#   000 = edge is down
```

Because the hooks fail open, a broken gateway looks exactly like a quiet one
from the client side. Run the verification above rather than assuming.

## Uninstall

```bash
rm -rf ~/.claude/bb
# remove the two hook entries from ~/.claude/settings.json
# remove the env.sh line from ~/.bashrc
```
