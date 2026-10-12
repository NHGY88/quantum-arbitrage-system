# 关键决策记录 (ADR)

格式：背景 → 决策 → 理由 → 被否决的方案 → 后果。
新增决策追加在文末，编号递增。

---

## ADR-001 抛弃原生 APK，改用 Web + 服务端分离

**背景**：原 Flutter 方案在 Web 端撞上 `dart:io` 编译陷阱，且双端难以共用后端契约。

**决策**：Admin Server（FastAPI）+ Web Client（Express + 原生响应式 HTML）彻底解耦，
浏览器只访问 3000，3000 同源代理到 8000。

**理由**：iOS/Android/PC 共用一套前端；后端可独立容器化；无 Flutter 编译链负担。

**否决**：Flutter Web（dart:io 不可用）；原生 APK（双端维护成本高）。

**后果**：移动端零改动；需要自行维护一份响应式前端。

---

## ADR-002 独立配置文件 admin.env

**决策**：所有密钥与连接串放 `server/admin.env`，并加入 `.gitignore`。
进程环境变量优先级高于文件。

**理由**：容器化时用环境注入覆盖，无需改文件；避免密钥进版本库。

**后果**：首次部署必须复制并修改 `admin.env`；
**注意**：改 `ADMIN_SEED_PASSWORD` 不会自动改已存在用户的口令（见 TROUBLESHOOTING B5）。

---

## ADR-003 数据存储：PostgreSQL 为主，JSON 兜底

**决策**：账号/权限/授权码存 PostgreSQL；PG 不可用时自动回落到 `data/db.json`，
服务仍可启动。

**理由**：本机开发与测试零依赖；生产用 PG 保证并发与持久化。

**后果**：`/api/status` 需要能反映真实连接状态，因此增加了 `errors` 字段。

---

## ADR-004 口令散列与令牌方案

**决策**：PBKDF2-HMAC-SHA256（20 万轮，自带随机盐）存口令；HS256 JWT 做无状态令牌。
不引入 passlib。

**理由**：passlib 在新版本 Python 上维护停滞；stdlib 足够且减少依赖。

**后果**：迁移到 bcrypt/argon2 时需要改写 `auth.hash_password` / `verify_password`。

---

## ADR-005 权限模型：五大类 18 项 + 角色预设 + 逐人授权

**背景**：需求是"最高权限管理员创建账号，再按组合/交易/我的/公告/后台任务五类逐人授权"。

**决策**：
- 权限按 5 个 category、18 个细粒度 action 定义；
- 计算式 `生效权限 = 角色预设 ∪ 个人授权 − 个人拒绝`；
- 管理员账号隐含全部权限，且**受后端保护**（不可通过接口改角色或删除）；
- 账号来源改为**用户自助注册 → 管理员事后授权**（注册即零权限的 pending 状态）。

**理由**：自助注册降低管理成本；显式 deny 便于"收回某一项但保留其余"。

**后果**：待授权用户可以登录但所有受控操作 403，需管理员在控制台放行。

---

## ADR-006 公网入口：Cloudflare 快速隧道（暂定）

**决策**：使用 `cloudflared tunnel --url` 快速隧道，由 `D:\AI\tunnel\watchdog.py` 守护，
实时地址写入 `data/tunnel_url.txt`。

**理由**：无需 Cloudflare 账号、无需域名即可立即获得 HTTPS 公网入口，
且**免去 localtunnel 的密码输入步骤**（这正是蓝图 Phase 5 想要的效果）。

**后果（重要）**：快速隧道**每次重启都会换地址**，不适合直接分发给客户。
若需固定地址，需升级为 Named Tunnel：

```powershell
cloudflared tunnel login
cloudflared tunnel create quantum
cloudflared tunnel route dns quantum trade.example.com
# 然后写 config.yml，把 ingress 指向 http://127.0.0.1:3000
cloudflared tunnel run quantum
```

这需要用户在 Cloudflare 控制台登录授权一次（唯一需要人工介入的步骤）。
在该域名解析生效后，隧道应长期常驻或注册为 Windows 服务。

---

## ADR-007 单实例判定使用命名互斥体

**背景**：用 pid 文件判重在进程被强杀后会残留陈旧 pid，导致新实例误判"已在运行"而自杀；
且 venv `pythonw.exe` 是启动器 + 子进程的双进程结构。

**决策**：改用 Win32 命名互斥体（`Local\...`），并显式设置 `restype = c_void_p`。

**理由**：内核对象随进程生命周期自动释放，不会残留；
`c_void_p` 避免 64 位句柄截断。

**后果**：pid 文件仅保留给 `status` 类命令做展示，不再参与判重。

---

## ADR-008 插件不热重载，改动需重启 opencode

**决策**：opencode 插件文件修改后不自动重载，必须重启应用。

**理由**：实测多次等待均未观察到重载。

**后果**：调整插件后要安排一次重启；
Telegram 派发失败时，**先确认插件是否为最新版本**（看日志里的 `alive tick`）。

---

## ADR-009 redis-py 锁定 5.x

**决策**：`requirements.txt` 固定 `redis==5.0.8`。

**理由**：redis-py 8.x 客户端默认发送 RESP3 `HELLO 3`，
Windows 便携版 Redis 5.0.14 仅支持 RESP2，直接连接会失败。

**后果**：不能随手升级 redis 客户端；若未来换用支持 RESP3 的 Redis 服务端（如
较新的官方 Redis 7 容器），才可考虑升级。
