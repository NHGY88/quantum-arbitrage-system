# Admin / Client 分离开发指南 (ADMIN_CLIENT_SPLIT_GUIDE)

> 端口隔离规范：**Admin Server = 8000**（唯一持有数据与密钥），**Web Client = 3000**（只做同源代理与静态页面）。
> 浏览器永远只访问 3000，绝不直连 8000。

---

## 一、为什么彻底抛弃原生 APK

原 Flutter 方案在 Web 端会撞上 `dart:io` 编译陷阱：浏览器无法使用 `dart:io` 的网络层与文件 API，
`flutter build web` 出来的页面在部分环境下直接白屏，且移动端与 Web 端难以共用同一套后端契约。

因此改为：

```
[ 手机 / 电脑浏览器 ]
        │  HTTP  (同源，无 CORS)
        ▼
[ Web Client  Express :3000 ]  ── 静态资源 m.html / accounts.html
        │  /api/*  同源代理（服务端转发，浏览器看不到 8000）
        ▼
[ Admin Server  FastAPI :8000 ]  ── JWT 鉴权 / 量化引擎 / 数据持久化
        ├── JSON 文件库 data/db.json（默认，离线可跑）
        ├── 可选 PostgreSQL + Redis（admin.env 配置后启用）
        └── 截图持久化 data/shots/
```

收益：iOS / Android / PC 浏览器零改动共用同一前端；后端可独立容器化（Phase 5）。

---

## 二、目录结构

```
D:\AI\
├── docs\
│   ├── MASTER_BLUEPRINT.md          # 顶层总纲（交接给任意 AI）
│   └── ADMIN_CLIENT_SPLIT_GUIDE.md  # 本文件：分离开发规范
├── server\                          # Admin Server (FastAPI, :8000)
│   ├── app\
│   │   ├── main.py                  # 路由 / 中间件 / lifespan
│   │   ├── settings.py              # admin.env 读取（环境变量优先）
│   │   ├── auth.py                  # PBKDF2 口令散列 + HS256 JWT
│   │   ├── db.py                    # JSON 存储 + 可选 PG/Redis 探测
│   │   └── engine.py                # Markdown 解析 / 对冲计算 / 风控 / z-score
│   ├── combos\                      # Markdown 组合定义（自动被解析）
│   ├── data\                        # db.json + shots/（运行时生成，已 gitignore）
│   ├── tests\test_admin_isolation.py
│   ├── admin.env                    # 唯一配置来源（务必 .gitignore）
│   ├── requirements.txt
│   └── start.cmd
└── web\                             # Web Client (Express, :3000)
    ├── server.js                    # 同源代理 + 静态托管
    ├── smoke.mjs                    # 端到端冒烟测试
    ├── package.json
    └── public\
        ├── m.html                   # 响应式暗黑终端
        └── accounts.html            # 账号 / 授权（Phase 7 占位）
```

---

## 三、端口隔离规范（硬性）

| 规则 | 说明 |
| --- | --- |
| 浏览器只连 3000 | `m.html` 中所有请求一律 `"/api/..."`，**不得**写 `http://localhost:8000` |
| 8000 只对 3000 可见 | 生产部署时 8000 应绑定内网或仅允许 3000 访问 |
| 代理不改写路径 | `Express /api/x` → `FastAPI /api/x`，路径与参数原样透传 |
| Token 只发往单源 | 前端把 JWT 放 `localStorage.qe_token`，由同源代理附加 `Authorization` |

违反第一条会同时破坏：CORS、安全隔离、localtunnel/Cloudflare 单一对外入口。

---

## 四、启动与验证

```bat
:: 终端 1 —— Admin Server
cd /d D:\AI\server
"D:\hermes_agent\hermes-agent\.venv\Scripts\python.exe" -X utf8 -m uvicorn app.main:app --host 0.0.0.0 --port 8000

:: 终端 2 —— Web Client
cd /d D:\AI\web
node server.js
```

或双击 `D:\AI\server\start.cmd`。

验证：

```bat
node D:\AI\web\smoke.mjs          :: 13 项端到端断言
python -m pytest tests -q         :: 服务端全量单测
```

---

## 五、API 契约

| 方法 | 路径 | 鉴权 | 说明 |
| --- | --- | --- | --- |
| GET | `/health` | 否 | 存活探针，Web 端会代理 `/health` |
| GET | `/api/status` | 否 | 返回 pg / redis / json_fallback 状态 |
| POST | `/api/auth/register` | 否 | 自助注册（默认零权限，待授权） |
| POST | `/api/auth/login` | 否 | `{username,password}` → `{access_token,permissions}` |
| GET | `/api/auth/me` | 是 | 当前用户 + 生效权限 |
| GET | `/api/rbac/catalog` | 是 | 五大类权限清单 + 角色预设 |
| GET | `/api/rbac/users` | 仅管理员 | 用户列表（含 pending 标记） |
| POST | `/api/rbac/users` | 仅管理员 | 直接建用户 |
| PUT | `/api/rbac/users/{u}/permissions` | 仅管理员 | 逐项授权 `{perm: "allow"\|"deny"}` |
| PATCH | `/api/rbac/users/{u}` | 仅管理员 | 改角色/显示名/启停 |
| DELETE | `/api/rbac/users/{u}` | 仅管理员 | 删除（管理员账号受保护） |
| GET | `/api/licenses` | 是 | 授权码列表 |
| POST | `/api/licenses` | 仅管理员 | 生成授权码 |
| POST | `/api/licenses/activate` | 否 | 激活（绑定机器指纹） |
| POST | `/api/licenses/validate` | 否 | 校验 |
| GET | `/api/combos?group=N` | 否 | 解析 `server/combos/*.md` |
| POST | `/api/hedge/calculate` | 是 | 动态对冲比 + 风控封顶（需 `trade:read`） |
| POST | `/api/shots` | 是 | multipart 上传截图（需 `combo:read`） |
| GET | `/api/shots` | 是 | 列出截图 |
| GET | `/api/shots/{id}` | 是 | 读取截图二进制 |
| DELETE | `/api/shots/{id}` | 是 | 删除截图（需 `combo:delete`） |

---

## 五之二、账号与权限模型（Phase 7）

### 账号流转

```
任何人 → /register.html 自助注册
        → 账号建立，状态 = 待授权（零权限）
        → 可登录，但所有受控操作返回 403
管理员 → /permissions.html 勾选授权
        → 用户重新登录即获得对应权限
```

**唯一管理员**（`admin.env` 的 `ADMIN_SEED_USERNAME`）拥有全部权限，且其角色/账号
受后端保护，无法通过任何接口被修改或删除，避免把自己锁在门外。

### 五大类权限

| 类别 | key | 权限项 |
| --- | --- | --- |
| 组合 / 组合交易 | `combo` | `combo:read` `combo:write` `combo:delete` `combo:trade` |
| 交易 | `trade` | `trade:read` `trade:order` `trade:risk` `trade:execute` |
| 我的 | `me` | `me:read` `me:write` `me:settings` |
| 公告 | `notice` | `notice:read` `notice:write` `notice:manage` |
| 后台任务 | `backend` | `backend:read` `backend:jobs` `backend:manage` `backend:users` |

共 **18 项**。权限计算规则：

```
生效权限 = 角色预设 ∪ 个人授权 − 个人拒绝
管理员   = 全部 18 项（不可削减）
```

角色预设：`viewer`（只读）/ `trader`（交易员）/ `operator`（运维），
在控制台可一键套用后再微调。

### 授权码（License）

独立于账号体系，用于对外分发。形如 `QE-XXXXX-XXXXX-XXXXX-XXXXX`，
支持有效期、设备数上限与停用/吊销。若要强制校验，把 `admin.env` 的
`LICENSE_REQUIRED` 设为 `true`，此后所有受控接口必须带 `X-License-Key` 头。

---

请求：
```json
{ "mode": "value", "value_a": 100, "value_b": 175, "equity": 100000, "lots": 0.01 }
```
响应（关键字段）：
```json
{ "requested_ratio": 1.75, "final_ratio": 1.75, "lots": 0.0175,
  "risk_triggered": false, "lot_floored": false,
  "implied_value": 175.0, "max_allowed_value": 1000.0 }
```
- `mode` ∈ `value | margin | volatility`
- 硬风控：仓位价值超过 `equity × 1%` 时自动按比例缩仓（`risk_triggered=true`）
- 最小手数：低于 0.01 一律托底到 0.01（`lot_floored=true`）

---

## 六、组合 Markdown 写法

放在 `server\combos\*.md`，自动被 `/api/combos` 解析，支持两种写法：

```markdown
## 1组 贵金属
- XAUUSD/XAGUSD corr 0.97
- XAUUSD/XPTUSD corr 0.91
```

```markdown
| leg_a | leg_b | corr |
|-------|-------|------|
| SPX500 | NAS100 | 0.92 |
```

分组由标题里的 `N组` 决定；缺省按出现顺序自增。品种代码支持字母+数字（`SPX500`/`NAS100`/`US30`）。

---

## 七、安全约定

1. `server/admin.env` 是唯一密钥来源，已在 `server/.gitignore` 中排除；**切勿**把口令写进代码或提交。
2. 生产部署前必须修改：
   - `ADMIN_JWT_SECRET` → 长随机串
   - `ADMIN_SEED_PASSWORD` → 强口令
3. 进程环境变量优先级高于 `admin.env`，便于容器化时用环境注入覆盖（Phase 5）。
4. `data/`（含 `db.json` 与截图）已在 `.gitignore` 中排除；截图属于用户敏感数据。

---

## 八、给后续 AI 的接手约定

- 新增后端能力 → 只动 `server/app/*`，并在 `tests/test_admin_isolation.py` 补一条用例。
- 新增前端能力 → 只动 `web/public/*.html` / `web/server.js`，**禁止**在页面里出现 `:8000`。
- 改动代理 → 必须重跑 `node web/smoke.mjs`，13 项全过才算完成。
- 改完跑 `python -m pytest tests -q`，保持全绿。

相关文档：[MASTER_BLUEPRINT.md](./MASTER_BLUEPRINT.md)
