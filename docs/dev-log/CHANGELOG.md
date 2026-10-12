# 变更流水 · CHANGELOG

倒序。每条记录：时间、范围、变更、原因。

---

## 2026-10-11 收尾（版本控制）

- **[新增]** 初始化 Git 仓库，首个提交 `feat: 量子套利系统 + AI 工作站首版`
  （64 个文件 / 9241 行）。
- **[新增]** 根级 `.gitignore`：分层排除密钥（`admin.env`、`tg/config.json`）、
  运行时数据（`*/data/`、`logs/`）、依赖（`node_modules/`）、
  大二进制（`mcp/`、`pgsql/`、`redis/`、`playwright-browsers/`、`downloads/`、`*.exe`）。
- **[新增]** 配置模板：`server/admin.env.example`、`tg/config.json.example`，
  使仓库可复现而不携带任何密钥。
- **[新增]** 根级 `README.md`：功能总览、架构图、快速开始、权限与积分规则、文档索引。
- **[安全]** 提交前扫描发现并清除 9 处硬编码密码：
  测试脚本与文档中写死了管理员口令与数据库口令。
  改为 `process.env.ADMIN_PW` 或占位符 `<ADMIN_PASSWORD>` / `<DB_PASSWORD>`，
  复检确认暂存区零敏感串。
- **[配置]** `points.py` 常量改为从 `admin.env` 读取
  （`POINTS_SIGNUP_BONUS` / `POINTS_VALID_DAYS` / `POINTS_COMMISSION_RATE` / `POINTS_DECAY_HOUR`），
  规则调整不再需要改代码。

---

## 2026-10-11 收尾（Web 功能补全）

- **[修复] 推广返佣算错人（重要）**：闭包表缺少父节点自环行 `(parent,parent,0)`，
  导致 `SELECT ... WHERE descendant=parent` 查不到祖先链，
  注册时上级绑定成功但**积分发给了错误对象**（lisi 拿到 110，admin 拿到 0）。
  修复：`bind_referral()` 先确保父节点自环行存在再拷贝祖先；
  另加 `ensure_self_rows()` 在应用启动时为所有存量账号补齐自环行。
- **[验证]** 三级链路实测通过：admin=11（10+1）、lisi=110（100+10）、wangwu=100，团队 2 人 260 积分。
- **[新增]** `web/public/points.html`：我的积分与团队。
  展示余额、剩余天数、直属下级、团队总人数、团队积分合计、推广码与推广链接（一键复制）、
  团队成员明细（层级/积分/状态）、积分流水。
- **[新增]** `server/app/notices.py` 公告模块 + `/api/notices` 增删改查，
  权限受 `notice:read` / `notice:write` / `notice:manage` 控制，
  支持 普通/警告/紧急 三级与置顶；`web/public/notice.html` 发布与管理界面。
- **[新增]** `web/public/me.html`：我的（账号信息、显示名修改、权限清单、快捷入口）。
- **[新增]** `PUT /api/auth/profile` 自助修改本人显示名（需 `me:write`），
  配套 `rbac.set_display_name()`；修复了原先用管理员接口改自己资料的越权做法。
- **[修复]** `register.html` 读取 URL 的 `?ref=` 参数并提交给注册接口，
  同时调用 `/api/points/ref/{code}` 显示"你的推荐人：xxx"，实现链接推广闭环。
- **[修复]** 积分页对无到期时间的账号不再显示误导性的"剩余天数 0 天"，改为"—"。
- **[测试]** 新增 `web/pages-check.cjs`：真实 Chromium 渲染全部页面并断言数据，
  覆盖 points/notice/me/register 四页 + 积分页 5 项具体数据断言。

---

## 2026-10-11 末（体验修正）

- **[修复]** Telegram 超时提示不再让用户离开 Telegram 去电脑端查看。
  原提示"（opencode 未在超时时间内返回内容，请到电脑窗口查看）"已彻底删除。
- **[新增]** 新增 `followUp()` 后台看门狗：主流程超时后先回一条
  "任务仍在执行，完成后再发结果"，随后在后台持续轮询（最长 6 小时），
  助手一产出就把完整结果推回 Telegram。
- **[新增]** `followingUp` 集合按 session 去重，避免同一任务叠加多个后台观察者。
- **[调整]** `reply_timeout_ms` 300000 → 180000（5 分钟 → 3 分钟），更快给出"仍在执行"反馈。
- **[约束确立]** 用户明确要求：任何情况下**不得**指示用户到电脑窗口操作，
  所有确认与查看动作都必须能在 Telegram 内完成。

---

## 2026-10-11 晚（续）

- **[新增] 积分体系 + 推广关系** `server/app/points.py`：
  - 注册赠送 100 积分，有效期 30 天，8 位小数（全程 Decimal，禁用 float）
  - 每天 02:00 自动线性扣减（剩余积分 ÷ 剩余天数），到期精确归零
  - 下级获得积分时，上级按 10% 分成，**永久逐级、无级差**
  - 推广码 + `?ref=码` 链接注册自动绑定上级，闭包表支持任意深度
  - JSON 兜底模式用父子链 + BFS 实现等价语义
- **[新增]** 后台定时任务 `_decay_scheduler`：按 `seconds_until_next_decay()` 休眠至次日 02:00 执行，
  单次异常不会终止调度（降级为 5 分钟后重试）。
- **[新增]** 积分与推广接口：`/api/points/{me,team,ledger,ref/{code},grant,decay/run}`。
- **[新增]** 注册接口支持 `ref_code`，注册即绑定上级并发积分。
- **[文档]** 新增 `docs/dev-log/2026-10-11-points-referral-plan.md` 完整规格说明。
- **[测试]** 覆盖注册赠送、10% 分成、三级逐级、团队统计、每日扣减、推广码校验、积分接口鉴权。

## 2026-10-11 晚

- **[安全]** 生成 64 位随机 JWT 密钥替换默认弱密钥；管理员口令改为用户指定值。
- **[修复]** `admin.env` 密码含 `@` 未 URL 编码导致 PostgreSQL 连接失败；
  编码为 `%40`，并为 `/api/status` 新增 `errors` 字段暴露真实连接失败原因。
- **[修复]** redis-py 8.x 客户端发 RESP3 `HELLO 3`，Redis 5.0.14 不支持 → 连接失败。
  客户端锁定 `redis==5.0.8`（requirements.txt 已固定）。
- **[修复]** venv 缺 pip 导致无法安装依赖 → 执行 `ensurepip` 补齐。
- **[基础设施]** 部署便携版 PostgreSQL 16.4（`:5432`，库 `quantum`，scram-sha-256）
  与 Redis 5.0.14（`:6379`），均位于 D 盘并注册开机自启。
- **[新增]** 公网接入：`cloudflared 2026.10.0` 快速隧道 + `tunnel/watchdog.py` 守护，
  实时地址写入 `data/tunnel_url.txt`。
- **[新增] Phase 7 权限体系** `server/app/rbac.py`：
  五大类 18 项权限（组合/交易/我的/公告/后台任务）、角色预设、
  `生效 = 预设 ∪ 授权 − 拒绝` 计算、管理员账号防锁死保护。
- **[新增]** 自助注册 `POST /api/auth/register`：注册即零权限 `pending`，
  可登录但受控操作 403，待管理员授权。
- **[新增]** 授权码模块 `server/app/licensing.py`：Keygen 风格 API
  （机器指纹绑定、设备数上限、有效期、停用/吊销），PG 优先 JSON 兜底。
- **[新增]** 管理接口 `/api/rbac/*`、`/api/licenses/*`（均限管理员）。
- **[前端]** 新增 `web/public/permissions.html` 权限控制台（勾选授权、角色一键套用、
  用户启停/删除、授权码生成，20 秒自动刷新以显示新注册用户）。
- **[前端]** 新增 `web/public/register.html` 自助注册页。
- **[前端]** `accounts.html` 增加授权码入口与状态说明。
- **[测试]** 单测 29 → **37 项**，新增覆盖自助注册、待授权拦截、授权后放行、
  管理员保护、五类权限清单。
- **[测试]** 新增 `server/rbac_smoke.mjs`（18 项 RBAC/授权码端到端）。
- **[修复]** 测试夹具未隔离 RBAC，导致测试打到真实 PostgreSQL → 加 `monkeypatch`
  强制 RBAC 走 JSON 存储。

## 2026-10-11 下午

- **[修复] 代理** `express.json()` 消费请求流导致所有 POST 转发空 body（422）→
  改为代理自行读取请求流。
- **[修复] 代理** `multipart/form-data` 被当 JSON 处理，boundary 丢失导致截图上传 422
  → 对 multipart 改为流式透传并保留原始 content-type。
- **[修复]** 组合解析正则不允许数字，`SPX500/NAS100/US30` 整组丢失
  → 正则放宽为含数字，并加回归测试。
- **[修复]** `flush()` 要求 ≥2 个 pair，导致单 pair 分组被丢弃。
- **[修复]** Markdown 表格行无法解析（仅按空白切分）→ 增加表格分支处理。
- **[修复]** `settings.py` 中 `DATA_DIR` 在 `get()` 定义前使用 → NameError。
- **[修复]** FastAPI `on_event` 弃用警告 → 改用 lifespan。
- **[新增]** Admin Server 全套（认证/组合/对冲计算/截图 CRUD/健康检查）。
- **[新增]** Web Client 全套（同源代理 + 暗黑终端 + 账号页）。
- **[文档]** `docs/MASTER_BLUEPRINT.md`、`docs/ADMIN_CLIENT_SPLIT_GUIDE.md`。

## 2026-10-11 上午

- **[修复]** 插件按 `worktree="/"` 查会话导致全部派发失败 →
  改为多目录尝试 + 无条件兜底。
- **[修复]** 看门狗 kill 循环：加宽限期（`GRACE_SECONDS=150`），worker 先写心跳再 getMe。
- **[修复]** `state.json` 被写成全 NUL：读取用 `utf-8-sig` + 异常回落，
  损坏时从 inbox 重建 offset，写入加 fsync。
- **[修复]** 单实例判定改用命名互斥体，解决陈旧 pid 文件导致新实例自杀、
  以及 venv `pythonw.exe` 启动器/子进程双进程误判。
- **[运维]** 清理重复进程；为 bridge/watchdog/third-hand 补齐开机自启。
