# 2026-10-11 · 从 0 到 1：AI 工作站 + 量子套利系统

一天之内完成两条线：把 opencode 变成可通过 Telegram 远程指挥的 AI 工作站；
并从零搭建出蓝图里描述的套利系统（后端 + Web + 数据库 + 公网 + 权限体系）。

---

## 上午 · 修复 Telegram 远程通道

### 症状
用户在 Telegram 发的指令一直没被执行，插件日志刷
`no target session available, skipping dispatch`。

### 根因
插件用 `worktree="/"` 去查会话，但实际会话的 `directory` 是 `D:\AI`，
过滤条件不匹配 → 查不到会话 → 全部跳过。

### 修复
`resolveSession()` 改为多级尝试：`oc.worktree` → `worktree` → `D:\AI` → `D:/AI`
→ 无条件过滤兜底。用 opencode 的 HTTP API 实测确认全库只有 1 个会话且在 `D:\AI`，
验证修复逻辑正确。

### 附带修复
- `state.json` 曾被写成全 NUL：读取改 `utf-8-sig` + 异常回默认，损坏时从 inbox 重建，写入加 fsync。
- 看门狗陷入 kill 循环：加 `GRACE_SECONDS=150` 宽限期，避免新 worker 未写心跳即被杀。
- `bridge.py` 改为先写心跳再 `getMe`。
- 重复进程清理：两个看门狗、两个 third_hand 各自只留一个。
- 开机自启补齐。

---

## 下午 · 搭建套利系统骨架

用户要求在 `D:\AI` 直接搭出 Admin + Web 完整骨架。

### 遇到的问题：项目不在本机
用户蓝图描述的项目（FastAPI:8000 / Express:3000 / m.html / ADMIN_CLIENT_SPLIT_GUIDE.md）
全盘搜索 C、D 两盘 **零命中**。据此判断这是 AI 工作站而非项目主机，
遂按用户选择"把 D:\AI 当项目根目录"从零搭建。

### 交付
- **Admin Server**（FastAPI:8000）：JWT 认证、Markdown 组合解析、动态对冲计算、
  截图增删查、/health、/api/status。
- **Web Client**（Express:3000）：同源代理 + 响应式暗黑终端 `m.html` + `accounts.html`。
- **测试**：`test_admin_isolation.py` 隔离测试（数据重定向到临时目录）。

### 开发中修掉的 4 个真实 bug
1. **settings.py 变量定义顺序**：`DATA_DIR` 在 `get()` 定义前使用 → NameError。
2. **组合解析漏组**：`flush()` 要求 ≥2 个 pair，导致单 pair 的分组被丢弃。
3. **表格行解析失败**：只按空白切分 token，Markdown 表格 `| XAUUSD | XAGUSD |` 解析不出。
4. **股指品种解析失败**：正则不允许数字，`SPX500/NAS100` 被整体丢弃。

另修正一处**测试本身写错**：`zscore([1,2,3,4,5])` 我断言为 0，
但该函数语义是"最新值相对窗口的 z 值"，应为 1.41。改测试并补了 `latest=均值` 的用例。

### 前端 bug（真实暴露）
- **POST 全部 422**：`express.json()` 消费了请求流，代理再读流时已为空。改为代理自行读流。
- **截图上传 422**：`multipart/form-data` 被当 JSON 处理，boundary 丢失。改为流式透传。

---

## 晚上 · 接入数据库、公网、权限体系

用户回复 5 条需求：新密码、接 PG+Redis、上公网、做授权码、少让人操作电脑。

### 密钥
生成 64 位随机 base64url JWT 密钥；管理员口令改为用户指定的 `<ADMIN_PASSWORD>`。
注意：改 env 不影响已存在用户的散列，需要单独重置——这成了 B5 案例。

### 数据库
- 无 winget/choco/docker，改用**便携版二进制**直接装到 D 盘。
- PostgreSQL 16.4：initdb（scram-sha-256）→ 启动 → 建库 `quantum`。
- Redis 5.0.14：配置文件方式启动。
- venv 缺 pip → `ensurepip` 补齐 → 装 `psycopg[binary]`、`redis`。

### 踩坑
1. `pg_ctl start` 前台调用会把工具挂死（fork 后持有管道）→ 改分离启动。
2. `DATABASE_URL` 密码含 `@` 未编码 → 解析错乱，连不上。编码为 `%40`。
   为避免再次静默失败，给 `/api/status` 加了 `errors` 字段暴露真实原因。
3. `redis: false` 报 `unknown command HELLO 3` → redis-py 8.x 用 RESP3，
   而 Redis 5.0.14 只支持 RESP2 → 客户端锁定 5.0.8。

达成：`postgres: true, redis: true`。

### 公网
装 cloudflared 2026.10.0，跑快速隧道拿到 `*.trycloudflare.com`，
写 `D:\AI\tunnel\watchdog.py` 守护（自动重启、地址落盘）。已用公网地址实测登录成功。

### 权限体系（重点需求）
用户澄清：**"用户自己注册，我们来给他授权"**。
于是把 Phase 7 从纯授权码扩展为完整 RBAC：

- 五大类 18 项权限：组合 / 交易 / 我的 / 公告 / 后台任务；
- 角色预设：只读 / 交易员 / 运维；
- 计算式 `生效 = 预设 ∪ 授权 − 拒绝`；
- 管理员账号受后端保护，不可被改角色或删除（防止把自己锁死）；
- **自助注册** `register.html` → 账号零权限 pending → 可登录但受控操作 403 →
  管理员在 `permissions.html` 勾选授权 → 用户重登即生效；
- 授权码模块保留（形如 `QE-XXXXX-XXXXX-XXXXX-XXXXX`，含有效期/设备数/吊销）。

实测链路：张三自助注册 → pending → 被 403 拦截 → 管理员授权 4 项 →
张三重登获得权限 → 对冲计算成功（1.75）。

---

## 收尾 · 验证与文档

- 单测从 29 项扩到 **37 项**（新增注册/待授权/授权后放行/管理员保护/五类清单等）。
- 端到端 smoke 13 项、RBAC smoke 18 项、公网实测，全部通过。
- 用真实 Chromium 渲染验证移动端 420px 与桌面 1280px 两种尺寸。
- 建立 `docs/dev-log/` 文档体系与一键体检脚本。

---

## 遗留与提醒

| 项 | 说明 |
| --- | --- |
| 隧道地址会变 | 快速隧道重启即换地址，实时读 `D:\AI\tunnel\data\tunnel_url.txt`；要固定域名需 Named Tunnel |
| `ADMIN_SEED_PASSWORD` 改动 | 不会自动更新既有用户口令 |
| `redis` 客户端 | 锁定 5.0.8，不可随意升级 |
| 插件改动 | opencode 插件不热重载，需重启应用 |
| 套利项目本体 | 仍不在本机；此处是按蓝图新建的实现 |
