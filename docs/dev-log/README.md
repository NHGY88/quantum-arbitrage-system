# 开发日志总纲 · Quantum Arbitrage System

> 本目录是**长期维护记录区**。出现任何问题时，先查这里，再查代码。
> 目录约定：`YYYY-MM-DD-主题.md`，一条工作线一个文件，按日期倒序排列。

## 目录

| 文件 | 内容 |
| --- | --- |
| [CHANGELOG.md](./CHANGELOG.md) | 按时间倒序的变更流水，每次改动追加一行 |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | 系统全景：端口、进程、数据流、目录、依赖版本 |
| [OPERATIONS.md](./OPERATIONS.md) | 运维手册：启动/停止/自启/排查/恢复 |
| [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) | 故障案例库：症状 → 原因 → 解决办法 |
| [DECISIONS.md](./DECISIONS.md) | 关键决策记录（ADR），含被否决的方案与原因 |
| [SECURITY.md](./SECURITY.md) | 账号、权限、密钥、公网暴露面 |
| [2026-10-11-foundation.md](./2026-10-11-foundation.md) | 首个完整工作日：AI 工作站 + 套利系统从 0 到 1 |
| [2026-10-11-points-referral-plan.md](./2026-10-11-points-referral-plan.md) | **积分体系与推广关系方案**（赠送/衰减/10% 分成/8 位小数/闭包表） |

## 快速排障入口

出问题时按这个顺序查：

1. 跑一键体检：`D:\AI\check.cmd`（或 `node D:\AI\doctor.mjs`）
2. 看体检报告里 ❌ 的那一项
3. 在 [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) 搜症状关键词
4. 再看对应服务日志路径（见下表）

| 服务 | 日志 |
| --- | --- |
| Admin Server (8000) | `D:\AI\server\data\admin.err.log` / 标准输出 |
| Web Client (3000) | 前台 `node server.js` 输出 |
| PostgreSQL | `D:\AI\pgsql\pg.log` |
| Redis | `D:\AI\redis\redis.log` |
| 公网隧道 | `D:\AI\tunnel\logs\cloudflared.log`、`tunnel-watchdog.log` |
| Telegram 桥接 | `D:\AI\tg\logs\bridge.log`、`plugin.log`、`watchdog.log` |
| Third Hand | `D:\AI\third-hand\logs\third_hand.log` |

## 当前公网地址

隧道为 Cloudflare 快速隧道，**每次隧道重启地址会变**，实时地址读取：

```
D:\AI\tunnel\data\tunnel_url.txt
D:\AI\tunnel\data\tunnel_status.json
```

如需固定域名，见 [DECISIONS.md](./DECISIONS.md#adr-006-公网入口)。
