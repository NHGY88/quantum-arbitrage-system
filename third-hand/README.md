# Windows Third Hand

A tray + global-hotkey desktop assistant that mirrors [shhivv/third-hand](https://github.com/shhivv/third-hand)
(which is macOS-only) on Windows. Press the hotkey anywhere, describe a task, and
opencode drives the real desktop through the `windows-desktop` and `playwright`
MCP tools, then shows the reply back in the hotkey window.

```
Ctrl+Alt+Space
     │
     ▼
[ capture focused app + screenshot ]  ──►  data/tasks.jsonl
     │                                          │
     ▼                                    (opencode plugin)
[ small prompt window ]                         │
     │  your instruction                   promptAsync into the session
     └──────────────────────────────────►       │
                                          opencode agent
                                          + windows-desktop MCP (22 tools)
                                          + playwright MCP (25 tools)
                                                │
     ┌──────────────────────────────────────────┘
     ▼
 data/results.jsonl  ──►  reply shown in the prompt window / tray
```

## Files

| file | role |
| --- | --- |
| `third_hand.pyw` | tray + global hotkey + prompt window (stdlib + tkinter only) |
| `core.py` | config, foreground-window inspection, GDI screenshot (PNG), task ledger |
| `th.py` | CLI: `status` `run` `stop` `hotkey` `capture` `send` `tasks` `results` |
| `start.cmd` | launches the app in the background |
| `config.json` | settings |
| `data/tasks.jsonl` | task queue (written by the app) |
| `data/results.jsonl` | replies (written by the plugin) |
| `data/shots/` | screenshots of the focused window |
| `logs/third_hand.log`, `logs/plugin.log` | logs |
| `..\.opencode\plugins\third-hand.js` | opencode plugin that dispatches tasks to the agent |

## Usage

```powershell
python D:\AI\third-hand\th.py run        # start (or double-click start.cmd)
python D:\AI\third-hand\th.py status
python D:\AI\third-hand\th.py stop
```

- **Hotkey**: `Ctrl+Alt+Space` (configurable) — opens a small window tagged with the
  app you were in. Type an instruction, `Enter` to run, `Esc` to cancel.
- **Tray icon**: left-click = new task, right-click = menu (new task / screenshots /
  logs / quit).
- **CLI test**: `python th.py send "打开记事本写hello"` queues a task and prints the reply.

## How a task reaches the agent

The app only writes to `data\tasks.jsonl`. The opencode plugin `third-hand.js`
watches that file and, for each task, calls `session.promptAsync` in the active
session with a prompt that includes the focused app, the screenshot path and your
instruction, then writes the agent's reply to `data\results.jsonl`.

> **The plugin only loads when opencode starts.** Restart OpenCode once after
> installing; until then `th.py send` will report a timeout.

## Config (`config.json`)

```jsonc
{
  "hotkey": "ctrl+alt+space",     // e.g. "ctrl+shift+space", "ctrl+alt+t", "f9"
  "tray": true,
  "capture": { "enabled": true, "mode": "active_window", "max_files": 200 },
  "opencode": {
    "session_id": "auto",         // "auto" = most recently updated session in worktree
    "worktree": "D:\\AI",
    "auto_dispatch": true,
    "poll_interval_ms": 1500,
    "reply_timeout_ms": 300000
  }
}
```

Everything lives under `D:\AI`. Nothing is written to `C:`.

## Notes vs. the macOS original

- No ChatGPT / TypeSafe key: planning is done by opencode's own model, and the
  desktop actions use the local MCP servers already installed.
- `@app` mentions are passed through to the agent as plain text; the agent picks
  the target from the focused-app context.
- Works only while OpenCode is running (it is the brain).
