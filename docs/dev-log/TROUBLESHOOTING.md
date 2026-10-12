# 故障案例库 · Troubleshooting

按「症状 → 原因 → 解决」组织。搜症状关键词即可命中。

---

## A. 服务起不来 / 端口不通

### A1. 访问 :3000 显示连接被拒绝

**症状**：`ERR_CONNECTION_REFUSED`，`web.err.log` 无输出

**原因**：Node 进程已退出（多见于调试时被 Ctrl+C 或被清理脚本误杀）

**解决**：
```bat
D:\AI\web\start.cmd
```
确认：
```bat
node D:\AI\web\smoke.mjs
```

---

### A2. :8000 连接被拒绝

**症状**：`http://127.0.0.1:8000/health` 无响应

**原因**：uvicorn 进程退出

**解决**：
```bat
D:\AI\server\start-detached.cmd
```
若启动即崩，看 `D:\AI\server\data\admin.err.log`，常见是 import 报错或端口被占：
```powershell
Get-NetTCPConnection -State Listen | Where-Object {$_.LocalPort -eq 8000}
```

---

### A3. `pg_ctl start` 让命令行卡死不返回

**症状**：执行 `pg_ctl ... start` 后终端一直挂着，工具超时

**原因**：PostgreSQL 会 fork 后台进程并持有父进程管道

**解决**：不要前台调用，用分离方式启动：
```powershell
Start-Process -FilePath "D:\AI\pgsql\pgsql\bin\pg_ctl.exe" `
  -ArgumentList '-D','D:\AI\pgsql\data','-l','D:\AI\pgsql\pg.log','-w','start' -WindowStyle Hidden
```
开机自启走 `D:\AI\pgsql\start-pg.cmd`，不会有这个问题。

---

### A4. `Start-Process` 报「参数为 Null 或空」

**症状**：
```
Start-Process : 无法对参数"ArgumentList"执行参数验证。参数为 Null 或空。
```

**原因**：ArgumentList 里混入了空字符串（如 `'--save',''`）

**解决**：不要传空参数。Redis 改用配置文件 `redis.conf` 启动：
```powershell
Start-Process -FilePath "D:\AI\redis\redis-server.exe" -ArgumentList 'D:\AI\redis\redis.conf'
```

---

## B. 数据库问题

### B1. `/api/status` 里 `postgres: false`

**症状**：`{"postgres": false, "errors": {"postgres": "..."}}`

**排查步骤**：
1. 端口是否在听：
   ```powershell
   Get-NetTCPConnection -State Listen | Where-Object {$_.LocalPort -eq 5432}
   ```
2. 直接用客户端验证：
   ```powershell
   $env:PGPASSWORD="<DB_PASSWORD>"
   & "D:\AI\pgsql\pgsql\bin\psql.exe" -h 127.0.0.1 -U quantum -d quantum -tAc "SELECT 1;"
   ```
3. 看 `errors` 字段里的具体报错。

---

### B2. ⚠️ `postgres: false` 且报错与认证相关（历史坑）

**症状**：`errors.postgres` 类似 `authentication failed ... "Quantum"` 或连不上主机

**原因**：`DATABASE_URL` 里的**密码含有特殊字符 `@`**，未做 URL 编码。
`postgresql://quantum:<DB_PASSWORD>@127.0.0.1:5432/quantum` 会被解析成
密码=`Quantum`、主机=`2026@127.0.0.1`，导致连接失败。

**解决**：把 `@` 编码成 `%40`：
```
DATABASE_URL=postgresql://quantum:Quantum%402026@127.0.0.1:5432/quantum
```
编码方法：
```powershell
python -c "from urllib.parse import quote; print(quote('<DB_PASSWORD>'))"
```

> 这类"静默失败"是本次最耗时的问题，因此 `/api/status` 后来加了 `errors` 字段，
> 让连接失败原因直接可见，而不是只返回一个 false。

---

### B3. ⚠️ `redis: false`，报错 `unknown command 'HELLO'`

**症状**：`errors.redis` = `unknown command \`HELLO\`, with args beginning with: \`3\``

**原因**：redis-py 8.x 客户端默认发 RESP3 `HELLO 3` 握手，
而 Windows 便携版 Redis 5.0.14 只支持 RESP2。

**解决**：把客户端**锁到 5.x**：
```powershell
python -m pip install "redis==5.0.8"
```
`requirements.txt` 中已固定 `redis==5.0.8`，**不要升级**。

---

### B4. venv 报 `No module named pip`

**症状**：`python -m pip install ...` → No module named pip

**原因**：`D:\hermes_agent\hermes-agent\.venv` 原本没装 pip

**解决**（已执行过，重建环境时需要再做一次）：
```powershell
& "D:\hermes_agent\hermes-agent\.venv\Scripts\python.exe" -m ensurepip --upgrade
```

---

### B5. 改了 admin.env 的密码但登录还是旧密码

**症状**：改了 `ADMIN_SEED_PASSWORD`，用新密码登录返回 401

**原因**：`admin.env` 只在**首次创建**用户时生效。已存在的用户记录里存的是旧口令散列。

**解决**：重置为新口令：
```powershell
python -X utf8 -c @"
import sys; sys.path.insert(0, r'D:\AI\server')
from app import db
from app.auth import hash_password
rec = db.get_user('admin'); rec['password_hash'] = hash_password('新密码')
db.put_user('admin', rec); print('ok')
"@
```
（现在用户体系走 `rbac`，生产用法是直接用管理员账号在控制台改，或删号后由
lifespan 以 `admin.env` 重建。）

---

## C. 前端 / 代理问题

### C1. 登录返回 422 `missing body`

**症状**：`{"detail":[{"type":"missing","loc":["body"]}]}`

**原因**：Express 代理先用了 `express.json()` 消费了请求流，
之后 `for await (chunk of req)` 读到的是空流，转发给 FastAPI 的 body 为空。

**解决**：二选一
- 移除 `express.json()`，在代理里自己读流（当前做法）；
- 或在 `express.json({verify})` 里把原始 body 缓存下来再转发。

---

### C2. 截图上传返回 422

**症状**：`POST /api/shots` 返回 422，但 JSON 接口正常

**原因**：代理把 `multipart/form-data` 当 JSON 处理，boundary 头丢失，FastAPI 解析不到文件。

**解决**：代理中对 `multipart/*` **不读流**，直接 `Readable.toWeb(req)` 透传，
并原样保留 `content-type`（含 boundary）。当前 `web/server.js` 已处理。

---

### C3. 页面能开但列表是空的 / "暂无组合"

**症状**：`/api/combos` 返回 count=0

**原因**：`server/combos/` 目录没有 `*.md` 文件，或解析失败

**解决**：确认 `D:\AI\server\combos\groups.md` 存在且格式正确，参考
`ADMIN_CLIENT_SPLIT_GUIDE.md` 第六节的两种写法。

---

### C4. 组合少了带数字的品种（SPX500 / NAS100 / US30）

**症状**：Markdown 里明明写了股指组合，解析结果没有第 3 组

**原因**：早期品种正则 `[A-Za-z]{3,10}[/=:][A-Za-z]{3,10}` **不允许数字**，
`SPX500/NAS100` 匹配不上。

**解决**：已改为 `[A-Za-z][A-Za-z0-9]{1,11}[/=:][A-Za-z][A-Za-z0-9]{1,11}`，
并加了回归测试 `test_parse_markdown_index_symbols_with_digits`。

---

## D. 进程与自启问题

### D1. 同一服务跑了两份

**症状**：`th.py status` 显示的 pid 和实际进程对不上；重复托盘图标

**原因**：用 `Start-Process` 启动时，Windows 的 venv `pythonw.exe` 是一个**启动器**，
会再拉起基础解释器作为**子进程**，于是出现"两个 python"（其实是 启动器 + 真身）。

另外早期 `third_hand.pyw` 用 pid 文件判重，若 pid 文件是**陈旧的**会误判"已在运行"而自杀。

**解决**：改用命名互斥体做单实例判重：
```python
_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateMutexW.restype = ctypes.c_void_p
_k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
h = _k32.CreateMutexW(None, 0, "Local\\third_hand_v1")
if ctypes.get_last_error() == 183:  # 已存在
    return
```
关键点：`restype` 必须是 `c_void_p`，否则 64 位下句柄被截断。
`D:\AI\tg\watchdog.py`、`D:\AI\third-hand\third_hand.pyw` 都已改用此方案。

---

### D2. 看门狗不停杀 worker（日志刷 `heartbeat stale`）

**症状**：`watchdog.log` 反复出现 `worker heartbeat stale (54000s), killing`

**原因**：新 worker 刚启动还没来得及写心跳，旧心跳时间戳太老，被立刻判定为僵死。

**解决**：加宽限期——`GRACE_SECONDS=150`（spawn 后 150 秒内不判死），
`STALE_SECONDS=240`；同时 `bridge.py` 改为**先写心跳再 getMe**。

---

### D3. state.json 变成乱码 / 全是 NUL

**症状**：`state.json` 内容为 `\x00...`，bridge 读取抛异常

**原因**：写入过程中进程被杀，文件被截断为 NUL 字节

**解决**：
1. 读取统一用 `encoding="utf-8-sig"`，并捕获异常回落到默认值；
2. 损坏时从 `inbox.jsonl` 重建 offset；
3. 写入时先写临时文件再替换 + `fsync`。

---

## E. opencode 插件相关

### E1. Telegram 消息不被执行（日志 `no target session available`）

**症状**：`D:\AI\tg\logs\plugin.log` 反复出现
`no target session available, skipping dispatch`

**原因**：插件按 `worktree="/"` 去 `session.list()` 查会话，
而实际会话的 `directory` 是 `D:\AI`，过滤条件不匹配 → 查不到 → 全部跳过。

**解决**：`resolveSession()` 改为多级尝试：
`oc.worktree` → `worktree` → `D:\AI` → `D:/AI` → 无条件过滤兜底。

---

### E2. 改了插件文件没生效

**症状**：插件日志停在旧版本，改了代码也不重载

**原因**：**opencode 插件不热重载**，必须重启 opencode 才加载新代码。

**解决**：重启 opencode 应用。（注意：重启会中断当前会话，但会保留在原会话中继续。）

---

### E3. 清理进程时把自己也杀了

**症状**：`Get-CimInstance Win32_Process | ? {$_.CommandLine -match 'watchdog'} | Stop-Process`
把执行这条命令的 PowerShell 自己也杀了。

**原因**：命令自身的命令行里包含匹配字符串，**自己匹配了自己**。

**解决**：加进程名过滤，排除自身：
```powershell
Get-CimInstance Win32_Process |
  Where-Object { $_.Name -match 'python' -and $_.CommandLine -match 'watchdog\.py' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
```

---

### E4. PowerShell 输出中文乱码

**症状**：接口返回的中文在终端显示成 `æ³¨å†�`

**原因**：控制台代码页不是 UTF-8

**解决**：
```powershell
[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8="1"
```
注意：这**只影响终端显示**，接口本身返回的是正确 UTF-8。

---

### E5. 工具调用没有输出 / 直接静默

**症状**：执行网络请求类的命令后完全没有输出

**原因**：PowerShell 中 `Invoke-WebRequest` 抛异常时管道被吞

**解决**：加 `-UseBasicParsing` 与显式 `-TimeoutSec`；网络探测优先用
`curl.exe -s -o NUL -w "%{http_code}"`，端口探测用 `Test-NetConnection`。

---

## H. Git / GitHub

### H1. ⚠️ `git push` 无限挂死，没有任何输出

**症状**：执行 `git push` 后终端一直不返回，也不打印进度，
网络明明通（`curl https://github.com` 正常）。

**原因**：**Git Credential Manager 的 GUI 选择器**在非交互会话里弹不出窗口，
于是永久阻塞。本机 git 的系统配置里带 `credential.helper = helper-selector`，
指向 `D:\hermes_agent\tools\git\mingw64\bin\git-credential-helper-selector.exe`。

用 `GIT_TRACE=1` 可以看到它卡在这一行：
```
trace: run_command: 'git credential-helper-selector store'
```

**解决**（三处一起做）：
1. 移除系统级助手：`git config --system --unset-all credential.helper`
2. 本地置空：`git config --local credential.helper ""`
3. 设置 `GIT_TERMINAL_PROMPT=0`，杜绝任何终端提示

**日常使用**：直接跑 `D:\AI\push.cmd`（已封装上述逻辑，token 由 gh 注入且用后即还原）。

---

### H2. 推送时不想把 token 写进 remote URL

**说明**：临时把 token 拼进 remote URL 是绕过 GCM 的常用手法，
但如果忘记还原，token 会留在 `.git/config` 里（本地文件，可能被误提交）。

**解决**：`push.cmd` 会在 push 结束后自动把 remote 还原为干净 URL。
手动处理：
```powershell
git -C D:\AI remote set-url origin https://github.com/<owner>/<repo>.git
```

---

### H3. 中文提交信息在 API 返回里显示为问号

**症状**：`gh api` / GitHub API 返回的 commit message 是 `????`

**原因**：这是 **PowerShell 控制台编码问题**，不是数据损坏 ——
仓库里的中文是完好的，用浏览器打开仓库页即可看到正确文字。

**排查时**：`[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false)`。

---

### H4. 提交前如何确认没有泄露密钥

```powershell
git add -A
git grep --cached -n -I -E "8762810365:|gho_[A-Za-z0-9]+|<你的口令>"
# 输出为空 = 干净
```
本次入库前正是用这条命令查出并清除了 9 处硬编码密码。

---

## G. 积分与推广

### G1. ⚠️ 上级绑定了，但积分发给了别人 / 分成没到账

**症状**：注册时 `referrer` 显示正确，但上级积分为 0，反而是下级拿到了 110

**原因**：闭包表 `user_refs` 里**父节点没有自环行** `(parent,parent,0)`。
`bind_referral()` 复制祖先时执行
`SELECT ancestor FROM user_refs WHERE descendant = parent`，
父节点没有自环行就查不到任何行，于是子节点无法挂到父的祖先链上。

**解决**：
1. `bind_referral()` 内先 `INSERT (parent,parent,0) ON CONFLICT DO NOTHING`；
2. 启动时调用 `points.ensure_self_rows()` 为所有存量账号补齐自环行。

**排查 SQL**：
```sql
SELECT ancestor, descendant, depth FROM user_refs ORDER BY descendant, depth;
-- 每个用户都应该有一行 (自己, 自己, 0)
```

---

### G2. 团队页显示 0 人，但确实有下级

**症状**：`team_total = 0`，数据库里 `referrer` 字段却有值

**原因**：`descendants()` 依赖闭包表；闭包表缺失时团队查询为空（见 G1）。
`referrer` 字段与闭包表是两套数据，前者正确不代表后者完整。

**解决**：修好闭包表后重启 Admin Server，启动钩子会自动补齐。

---

### G3. 显示名变成问号 / 乱码

**症状**：页面昵称显示 `??` 或乱码

**原因**：用 PowerShell `Invoke-RestMethod` 传中文请求体时，
控制台编码不是 UTF-8，中文在发送前就已损坏。

**解决**：涉及中文写操作时改用 Python 脚本调用，不要用 PowerShell：
```powershell
python -X utf8 -c "import sys; sys.path.insert(0, r'D:\AI\server'); from app import rbac; rbac.set_display_name('lisi','李四')"
```

---

### G4. 「剩余天数」显示 0 天但余额不为 0

**症状**：积分有值但剩余天数为 0

**原因**：该账号的积分是**积分系统上线前**产生的，没有 `points_expires_at`。

**解决**：给存量账号补一次有效期，或在前端对无到期时间显示"—"（已做）。

---

## F. 公网隧道

### F1. 公网地址变了

**症状**：昨天的 trycloudflare 链接打不开

**原因**：快速隧道（quick tunnel）**每次重启都会分配新地址**

**解决**：地址实时写在 `D:\AI\tunnel\data\tunnel_url.txt`。
需要固定域名请看 [DECISIONS.md](./DECISIONS.md#adr-006-公网入口)。

---

### F2. 隧道掉线

**症状**：`tunnel_url.txt` 打不开；`tunnel-watchdog.log` 无新记录

**解决**：看门狗会自动重启（间隔 3 秒）。彻底重来：
```bat
D:\AI\tunnel\start.cmd
```
