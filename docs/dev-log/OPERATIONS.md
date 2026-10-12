# 运维手册 · Operations

最后更新：2026-10-11

## 一、一键体检（出任何问题先跑这个）

```bat
D:\AI\check.cmd
```

或：
```powershell
node D:\AI\doctor.mjs
```

会逐项检查并打印 ✅ / ❌，包括：进程、端口、数据库、API、隧道、公网可达性。

---

## 二、启动 / 停止

### 全部启动（开机自启已配好，正常无需手动）
```bat
D:\AI\pgsql\start-pg.cmd      :: PostgreSQL :5432
D:\AI\redis\start-redis.cmd   :: Redis :6379
D:\AI\server\start-detached.cmd :: Admin :8000
D:\AI\web\start.cmd           :: Web :3000
D:\AI\tunnel\start.cmd        :: 公网隧道
D:\AI\tg\start.cmd            :: Telegram 桥接
```

### 停止
```powershell
# Admin
Get-CimInstance Win32_Process | ? { $_.Name -match 'python' -and $_.CommandLine -match 'uvicorn' } |
  Stop-Process -Id { $_.ProcessId } -Force

# Web
Get-CimInstance Win32_Process | ? { $_.Name -eq 'node.exe' -and $_.CommandLine -match 'server\.js' } |
  Stop-Process -Id { $_.ProcessId } -Force

# 隧道
Get-CimInstance Win32_Process | ? { $_.Name -eq 'cloudflared.exe' } |
  Stop-Process -Id { $_.ProcessId } -Force
```

> 停止脚本务必带 `Name` 过滤，否则会误杀执行命令的 PowerShell 自身。

---

## 三、开机自启注册项

位于 `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`：

| 名称 | 指向 |
| --- | --- |
| `QuantumPostgres` | `D:\AI\pgsql\start-pg.cmd` |
| `QuantumRedis` | `D:\AI\redis\start-redis.cmd` |
| `QuantumAdmin` | `D:\AI\server\start-detached.cmd` |
| `QuantumWeb` | `D:\AI\web\start.cmd` |
| `QuantumTunnel` | `D:\AI\tunnel\start.cmd` |
| `TgBridge` | `D:\AI\tg\start.cmd` |
| `ThirdHand` | `...\pythonw.exe D:\AI\third-hand\third_hand.pyw` |

查看全部：
```powershell
(Get-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run") | Format-List
```

---

## 四、常用验证

```powershell
# 本机
curl.exe -s http://127.0.0.1:3000/health
curl.exe -s http://127.0.0.1:8000/api/status

# 单测
cd D:\AI\server; python -m pytest tests -q          # 37 项

# 端到端
node D:\AI\web\smoke.mjs                              # 13 项
node D:\AI\server\rbac_smoke.mjs                      # 18 项

# 公网
$u = (Get-Content D:\AI\tunnel\data\tunnel_url.txt).Trim()
curl.exe -s "$u/health"
```

---

## 五、备份

| 对象 | 位置 | 建议 |
| --- | --- | --- |
| 账号与权限 | PostgreSQL `app_users` `user_permissions` | `pg_dump` |
| 授权码 | PostgreSQL `licenses` `license_activations` | `pg_dump` |
| 截图 | `D:\AI\server\data\shots\` | 目录复制 |
| 组合定义 | `D:\AI\server\combos\*.md` | 版本控制 |
| 配置 | `D:\AI\server\admin.env` | 离线加密备份 |

导出数据库：
```powershell
$env:PGPASSWORD="<DB_PASSWORD>"
& "D:\AI\pgsql\pgsql\bin\pg_dump.exe" -h 127.0.0.1 -U quantum -d quantum `
  -Fc -f "D:\AI\backups\quantum-$(Get-Date -f yyyyMMdd-HHmm).dump"
```

---

## 六、升级依赖

```powershell
$py = "D:\hermes_agent\hermes-agent\.venv\Scripts\python.exe"

# 装依赖前先确认 redis 必须保持 5.x
& $py -m pip install -r D:\AI\server\requirements.txt

# 验证
cd D:\AI\server; & $py -m pytest tests -q
node D:\AI\web\smoke.mjs
```
两个验证都通过再重启服务。

---

## 七、访问入口

| 用途 | 地址 |
| --- | --- |
| 局域网 | `http://<本机内网IP>:3000` |
| 公网 | 见 `D:\AI\tunnel\data\tunnel_url.txt` |
| 终端页 | `/` |
| 自助注册 | `/register.html` |
| 权限控制台 | `/permissions.html` |
| 账号与授权 | `/accounts.html` |
| API 文档 | `http://127.0.0.1:8000/docs` |

登录账号：`admin` / 密码见 `D:\AI\server\admin.env` 的 `ADMIN_SEED_PASSWORD`。
