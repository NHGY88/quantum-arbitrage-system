# 系统架构 · Quantum Arbitrage System

最后更新：2026-10-11

## 一、进程与端口全景

```
                    公网
                      │
        ┌─────────────▼──────────────┐
        │  Cloudflare 隧道 (cloudflared) │  ← D:\AI\tunnel\watchdog.py 守护
        │  https://xxx.trycloudflare.com │
        └─────────────┬──────────────┘
                      │ HTTP
        ┌─────────────▼──────────────┐
        │  Web Client  Express :3000   │  ← D:\AI\web\server.js
        │  静态页 + 同源代理 /api/*     │
        └─────────────┬──────────────┘
                      │ fetch (127.0.0.1:8000)
        ┌─────────────▼──────────────┐
        │  Admin Server FastAPI :8000  │  ← D:\AI\server\app\main.py
        │  RBAC / 量化引擎 / 授权码      │
        └──┬───────────┬──────────┬───┘
           │           │          │
   ┌───────▼──────┐ ┌──▼─────┐ ┌──▼────────────┐
   │ PostgreSQL   │ │ Redis  │ │ 文件存储       │
   │ :5432        │ │ :6379  │ │ db.json/shots/ │
   │ 库 quantum   │ │ db 0   │ │                │
   └──────────────┘ └────────┘ └───────────────┘
```

辅助进程（同一台机器，与套利系统解耦）：

| 组件 | 端口/热键 | 位置 |
| --- | --- | --- |
| Telegram 桥接 + 看门狗 | Telegram Bot | `D:\AI\tg\` |
| Third Hand 桌面助手 | Ctrl+Alt+Space | `D:\AI\third-hand\` |
| opencode MCP（playwright / windows-desktop / computer-use） | — | `D:\AI\mcp\` |

## 二、目录结构

```
D:\AI\
├── server\                    Admin Server (FastAPI)
│   ├── app\
│   │   ├── main.py            路由 + 中间件 + lifespan
│   │   ├── settings.py        admin.env 读取（env 优先）
│   │   ├── auth.py            PBKDF2 口令 + HS256 JWT
│   │   ├── rbac.py            角色与权限（五大类 18 项）
│   │   ├── points.py          积分与推广（赠送/衰减/10% 分成/闭包表）
│   │   ├── notices.py         公告模块
│   │   ├── licensing.py       授权码（Phase 7）
│   │   ├── db.py              JSON 存储 + PG/Redis 探测
│   │   └── engine.py          Markdown 解析 / 对冲计算 / 风控
│   ├── combos\                Markdown 组合定义（自动解析）
│   ├── data\                  db.json、shots/、日志
│   ├── tests\                 pytest 隔离测试（37 项）
│   ├── admin.env              ★ 密钥唯一来源（勿提交）
│   └── requirements.txt
├── web\                       Web Client (Express)
│   ├── server.js              同源代理 + 静态托管
│   ├── public\m.html          暗黑终端（计算器/组合/截图）
│   ├── public\points.html     我的积分与团队
│   ├── public\notice.html     公告
│   ├── public\me.html         我的（资料/权限）
│   ├── public\permissions.html 权限控制台
│   ├── public\register.html   自助注册（含 ?ref= 推广码捕获）
│   ├── public\accounts.html   账号与授权
│   └── smoke.mjs / ui-check.cjs / perms-check.cjs / pages-check.cjs
├── pgsql\                     PostgreSQL 16.4 便携版
│   ├── pgsql\bin\
│   └── data\                  数据库文件
├── redis\                     Redis 5.0.14 便携版
├── tunnel\                    公网隧道守护
│   ├── watchdog.py
│   └── data\tunnel_url.txt    ★ 实时公网地址
├── tg\                        Telegram 双向桥接
├── third-hand\                桌面助手
├── docs\                      全部文档
│   ├── MASTER_BLUEPRINT.md
│   ├── ADMIN_CLIENT_SPLIT_GUIDE.md
│   └── dev-log\               ★ 本开发日志目录
└── downloads\                 安装包与二进制
```

## 三、端口隔离规范

| 端口 | 服务 | 谁可以访问 |
| --- | --- | --- |
| 3000 | Web Client | 公网 / 局域网 / 本机 |
| 8000 | Admin Server | **仅** 127.0.0.1（由 3000 代理访问） |
| 5432 | PostgreSQL | 仅本机 |
| 6379 | Redis | 仅本机 |

浏览器永远只连 3000。前端页面里不得出现 `:8000`。

## 四、数据流

**读路径**
```
浏览器 → GET /api/combos (3000) → 代理 → FastAPI → 解析 server/combos/*.md → JSON
```

**写路径**
```
浏览器 → POST /api/hedge/calculate (3000) → 代理 → FastAPI
  → 校验 JWT → 校验权限 trade:read
  → engine.dynamic_hedge_ratio() → engine.apply_risk_caps() → JSON
```

**账号路径**
```
注册 → POST /api/auth/register → rbac.create_user(role=user, 权限={})
     → 状态 pending（可登录，受控操作 403）
管理员 → PUT /api/rbac/users/{u}/permissions → PostgreSQL: user_permissions
用户重新登录 → GET /api/auth/me → 返回生效权限
```

## 五、依赖版本（实测）

| 组件 | 版本 | 说明 |
| --- | --- | --- |
| Python | 3.12 | `D:\hermes_agent\hermes-agent\.venv` |
| FastAPI | 0.133.1 | |
| uvicorn | 0.41.0 | |
| pydantic | 2.12.5 | |
| PyJWT | 2.12.1 | HS256 |
| psycopg | 3.3.6 | PostgreSQL 驱动 |
| redis (py) | **5.0.8** | ⚠ 必须 5.x，见 TROUBLESHOOTING |
| pytest | 9.0.2 | |
| Node.js | 24.14.1 | |
| Express | 4.x | |
| PostgreSQL | 16.4 | 便携版 `D:\AI\pgsql` |
| Redis | 5.0.14 | 便携版 `D:\AI\redis` |
| cloudflared | 2026.10.0 | `D:\AI\downloads\cloudflared.exe` |

## 六、存储策略

| 数据 | 主存储 | 兜底 |
| --- | --- | --- |
| 用户 / 权限 | PostgreSQL `app_users` `user_permissions` | `data/db.json` |
| 授权码 | PostgreSQL `licenses` `license_activations` | `data/db.json` |
| 截图 | 文件 `data/shots/{id}.png` | 元数据落 db.json/db |
| 组合定义 | Markdown `server/combos/*.md` | — |

PG 不可用时服务仍可启动（JSON 兜底），`/api/status` 的 `errors` 字段会写明原因。
