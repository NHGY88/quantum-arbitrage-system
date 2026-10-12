# Telegram ↔ OpenCode 双向通道

所有文件都在 D 盘，C 盘零占用。

## 组成

| 文件 | 作用 |
| --- | --- |
| `bridge.py` | 守护进程：长轮询 Telegram Bot API，收消息写入 `data/inbox.jsonl`，并把 `data/outbox.jsonl` 里的新行发回 Telegram |
| `tg.py` / `tg.cmd` | 命令行入口（`tg.cmd` 是给 CMD/PowerShell 直接用的包装） |
| `config.json` | Bot token、拥有者名字、会话绑定、opencode 派发设置 |
| `data/inbox.jsonl` | 收到的每条 Telegram 消息（一行一条 JSON） |
| `data/outbox.jsonl` | 待发送队列，我方写入即发送 |
| `data/sent.jsonl` | 已发送记录 |
| `data/state.json` | update_id 游标、chat 绑定 |
| `logs/bridge.log` | 运行日志 |
| `D:\AI\.opencode\plugins\telegram-bridge.js` | opencode 插件：把 Telegram 消息注入本窗口会话，并把回复发回 Telegram |
| `D:\AI\.opencode\commands\tg.md` | opencode 斜杠命令 `/tg` |
| `D:\AI\migrate-data.cmd` | 把 opencode 数据目录也搬到 D 盘（需先关闭 OpenCode） |

## 常用命令

```cmd
tg.cmd status              :: 运行状态
tg.cmd me                  :: 校验 token / webhook
tg.cmd poll 20             :: 打印最近 20 条收件箱内容（连通性证据）
tg.cmd wait 60             :: 等待最多 60 秒的新消息
tg.cmd send "回复内容"      :: 发回 Telegram
tg.cmd test                :: 发一条自检消息
tg.cmd stop / start        :: 停止 / 启动守护进程
```

## 两种工作模式

1. **手动（本窗口可见）**：在 opencode 里输入 `/tg`，我读取 `inbox.jsonl`，原文会显示在窗口里，我再把回复发回 Telegram。
2. **自动远程（无需碰电脑）**：插件 `telegram-bridge.js` 监听 `inbox.jsonl`，新消息自动注入本窗口会话，我的回复自动发回 Telegram。
   - 需要重启 OpenCode 让插件加载。
   - `config.json` 里 `opencode.auto_dispatch` 控制开关。
   - `opencode.session_id` 设为 `"auto"` 时自动选最近活跃的会话；也可写死某个 `ses_...` ID。

## 安全

- 首次私聊自动绑定为拥有者会话（`bind_first_contact`），绑定后只有该 chat 的消息会被处理。
- 想固定白名单：把 `allowed_chat_ids` 填成 `[7910598782]`，清空 `bind_first_contact`。
- 内置命令：`/start` `/id` `/ping` `/status` `/help`。

## 开机自启（可选）

`Win+R` → `shell:startup` 放一个 `tg-autostart.cmd`：

```cmd
@echo off
start "" /min "D:\AI\tg\tg.cmd" start
```