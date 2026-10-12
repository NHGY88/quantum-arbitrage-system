# 量子纠缠套利交易辅助系统 · Quantum Arbitrage System

> 一套轻量的统计套利与高正相关对冲交易监控系统。
> Web + 服务端彻底解耦，跨平台（手机 / 平板 / 电脑浏览器零改动），
> 内置权限体系、积分推广与公网访问能力。

[![changelog](https://img.shields.io/badge/CHANGELOG-docs/dev-log/CHANGELOG.md-blue)](docs/dev-log/CHANGELOG.md)
[![guide](https://img.shields.io/badge/guide-docs/MASTER_BLUEPRINT.md-green)](docs/MASTER_BLUEPRINT.md)

---

## 功能概览

| 模块 | 说明 |
| --- | --- |
| **动态对冲计算** | 价值 / 保证金 / 波动率三种模式，自动计算真实对冲比（如 1:1.75） |
| **硬风控** | 1% 权益风险上限自动缩仓 + 0.01 最小手数托底 |
| **高相关组合** | 自动解析 Markdown 定义的品种组合与相关系数，支持降序与抽屉浏览 |
| **截图极值解析** | K 线截图上传、持久化、在线查看 |
| **权限体系** | 五大类 18 项权限（组合/交易/我的/公告/后台任务），管理员逐人授权 |
| **积分推广** | 注册送 100 积分，30 天线性衰减，10% 逐级分成，推广链接自动绑定上下级 |
| **公告** | 普通/警告/紧急三级，支持置顶 |
| **授权码** | Keygen 风格授权，支持设备数限制、有效期、停用与吊销 |
| **公网访问** | Cloudflare 隧道自动守护，一键获得 HTTPS 公网地址 |

---

## 架构

```
浏览器（手机/电脑）
    │  同源，无 CORS
    ▼
Web Client  Express :3000 ── 静态页 + /api 同源代理
    │
    ▼
Admin Server  FastAPI :8000 ── JWT + RBAC + 积分 + 量化引擎
    ├── PostgreSQL :5432 ── 账号 / 权限 / 积分 / 公告 / 授权码
    ├── Redis      :6379 ── 缓存
    └── 文件存储    ── 截图、JSON 兜底
```

**端口隔离规范**：浏览器只访问 3000；8000 仅供 3000 代理；
5432 / 6379 仅绑定本机。前端页面中不得出现 `:8000`。

---

## 快速开始

### 1. 配置

```bash
cd server
cp admin.env.example admin.env
```

编辑 `admin.env`，至少修改这三项：

```ini
ADMIN_JWT_SECRET=<用 python -c "import secrets;print(secrets.token_urlsafe(48))" 生成>
ADMIN_SEED_PASSWORD=<你的强口令>
```

数据库可选。留空则自动回落到本地 JSON 文件，服务照常运行。

> ⚠ 若数据库口令含 `@ : /` 等字符，必须 URL 编码：
> `python -c "from urllib.parse import quote;print(quote('你的密码'))"`

### 2. 安装依赖

```bash
# Python
python -m pip install -r server/requirements.txt

# Node
cd web && npm install
```

### 3. 启动

```bash
# Admin Server
cd server && python -m uvicorn app.main:app --port 8000

# Web Client
cd web && node server.js
```

打开 <http://127.0.0.1:3000> 即可。

### 4. 公网访问（可选）

```bash
cloudflared tunnel --url http://127.0.0.1:3000
```

运行 `tunnel/start.cmd` 可由看门狗自动守护，
实时地址写在 `tunnel/data/tunnel_url.txt`。
需要固定域名请改用 Named Tunnel（见 [ADR-006](docs/dev-log/DECISIONS.md)）。

---

## 目录结构

```
├── server/          Admin Server (FastAPI)
│   ├── app/
│   │   ├── main.py      路由与生命周期
│   │   ├── settings.py  配置加载（环境变量优先）
│   │   ├── auth.py      PBKDF2 口令 + JWT
│   │   ├── rbac.py      权限体系（5 类 18 项）
│   │   ├── points.py    积分与推广
│   │   ├── notices.py   公告
│   │   ├── licensing.py 授权码
│   │   ├── engine.py    量化引擎
│   │   └── db.py        存储层
│   ├── combos/      Markdown 组合定义
│   └── tests/       pytest 测试
├── web/             Web Client (Express)
│   └── public/      m / points / notice / me / permissions / register / accounts
├── tunnel/          公网隧道守护
├── tg/              Telegram 远程控制桥接
├── third-hand/      桌面快捷指令助手
└── docs/            全部文档
    ├── MASTER_BLUEPRINT.md        顶层总纲
    ├── ADMIN_CLIENT_SPLIT_GUIDE.md 前后端分离规范
    └── dev-log/                  开发日志与排障手册
```

---

## 权限模型

| 类别 | 权限项 |
| --- | --- |
| 组合 | `combo:read` `combo:write` `combo:delete` `combo:trade` |
| 交易 | `trade:read` `trade:order` `trade:risk` `trade:execute` |
| 我的 | `me:read` `me:write` `me:settings` |
| 公告 | `notice:read` `notice:write` `notice:manage` |
| 后台任务 | `backend:read` `backend:jobs` `backend:manage` `backend:users` |

计算式：`生效权限 = 角色预设 ∪ 个人授权 − 个人拒绝`。
管理员账号隐含全部权限，且受后端保护，无法被降级或删除。

---

## 积分规则

- 注册赠送 **100** 积分，有效期 **30 天**
- 每天 **02:00** 自动扣减：`剩余积分 ÷ 剩余天数`，到期精确归零
- 下级获得积分时，上级按 **10%** 逐级获得（无级差）
  （B 注册 → B+100，A+10；C 通过 B 注册 → C+100，B+10，A+1）
- 全部使用 `Decimal` 量化到 **8 位小数**，不使用浮点数

详见 [积分与推广方案](docs/dev-log/2026-10-11-points-referral-plan.md)。

---

## 测试与体检

```bash
cd server && python -m pytest tests -q     # 单元测试
node web/smoke.mjs                         # 端到端冒烟
node server/rbac_smoke.mjs                 # 权限与授权码
node doctor.mjs                            # 一键体检（Windows）
```

---

## 文档

| 文档 | 内容 |
| --- | --- |
| [MASTER_BLUEPRINT.md](docs/MASTER_BLUEPRINT.md) | 顶层总纲，交接给任意 AI |
| [ADMIN_CLIENT_SPLIT_GUIDE.md](docs/ADMIN_CLIENT_SPLIT_GUIDE.md) | 前后端分离规范与 API 契约 |
| [dev-log/README.md](docs/dev-log/README.md) | 开发日志索引 |
| [dev-log/ARCHITECTURE.md](docs/dev-log/ARCHITECTURE.md) | 系统全景 |
| [dev-log/OPERATIONS.md](docs/dev-log/OPERATIONS.md) | 运维手册 |
| [dev-log/TROUBLESHOOTING.md](docs/dev-log/TROUBLESHOOTING.md) | 故障案例库 |
| [dev-log/DECISIONS.md](docs/dev-log/DECISIONS.md) | 关键决策记录 |
| [dev-log/SECURITY.md](docs/dev-log/SECURITY.md) | 安全与暴露面 |
| [dev-log/CHANGELOG.md](docs/dev-log/CHANGELOG.md) | 变更流水 |

---

## 安全须知

- `server/admin.env` 与 `tg/config.json` 含密钥，**已被 `.gitignore` 排除，切勿提交**
- 克隆本仓库后请先复制 `admin.env.example` 为 `admin.env` 并修改密钥
- 上线前务必更换 `ADMIN_JWT_SECRET` 与管理员口令

---

## 许可

MIT