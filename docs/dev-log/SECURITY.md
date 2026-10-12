# 安全 · Security

最后更新：2026-10-11

## 一、密钥与凭据

| 项 | 位置 | 说明 |
| --- | --- | --- |
| JWT 密钥 | `server/admin.env` → `ADMIN_JWT_SECRET` | 64 位随机 base64url；JWT 签名用 |
| 管理员口令 | `server/admin.env` → `ADMIN_SEED_PASSWORD` | 当前为用户指定值 |
| PostgreSQL | `server/admin.env` → `DATABASE_URL` | 口令含 `@`，已 URL 编码为 `%40` |

**规则**
1. `admin.env` 已在 `server/.gitignore`，**绝不提交**。
2. 改 `ADMIN_SEED_PASSWORD` **不会**更新既有用户口令 —— 见 TROUBLESHOOTING B5。
3. 口令散列：PBKDF2-HMAC-SHA256，20 万轮，随机盐。

## 二、账号体系

- **唯一管理员**：`admin`。该账号的角色与存续受后端保护，
  任何接口都不能把它降级或删除（防止管理员把自己锁在门外）。
- **普通用户**：自助注册（`/register.html`），初始**零权限**、状态 `pending`。
  可登录，但所有受控接口返回 **403**，直到管理员在 `/permissions.html` 授权。
- 授权可精确到 18 个细粒度动作；支持"给"也支持"收回"。

### 新建管理员的正确做法
目前无自助提权通道。如需增加管理员：
1. 直接在 PostgreSQL 插入 `app_users` 行，`role='admin'`；
2. 或临时把某个已有账号的 `role` 改为 `admin`（**绕过接口**，接口会拒绝）。

## 三、网络暴露面

| 服务 | 绑定 | 公网可达 |
| --- | --- | --- |
| Web Client 3000 | 0.0.0.0 | **是**（经 Cloudflare 隧道） |
| Admin Server 8000 | 0.0.0.0 | 否（未做隧道，仅本机/局域网） |
| PostgreSQL 5432 | 127.0.0.1 | 否 |
| Redis 6379 | 127.0.0.1 | 否 |

**⚠ 风险点**
- 8000 目前绑定在 `0.0.0.0`，局域网内可直接访问并绕过 3000 的前端逻辑。
  若不需要局域网直连，建议改为 `--host 127.0.0.1`。
- 隧道暴露的是 3000，而 3000 的 `/api/*` 会代理到 8000，
  因此**公网用户可间接触达全部 API**，认证与权限是唯一防线。
  所有受控接口都强制校验 JWT + 权限，这一点已实现并测试。

**加固建议（尚未实施）**
1. 3000 前加 Cloudflare Access / 或应用层 IP 白名单。
2. 隧道改为 Named Tunnel 并绑定自有域名（见 DECISIONS ADR-006）。
3. Admin 改绑 `127.0.0.1`。

## 四、授权码（Phase 7）

- 形如 `QE-XXXXX-XXXXX-XXXXX-XXXXX`，仅创建时明文返回一次，库里只存 SHA-256。
- 支持有效期、设备数上限、停用与吊销。
- 默认**未强制校验**。需要强制时把 `admin.env` 的 `LICENSE_REQUIRED=true`，
  此后所有受控接口必须携带 `X-License-Key` 头，否则返回 402。

## 五、日志与隐私

- 截图属敏感数据，存于 `server/data/shots/`，已在 `.gitignore`。
- `data/`（含 `db.json`）已排除。
- Telegram 桥接日志会记录消息摘要，避免记录明文敏感内容。

## 六、重置与应急

| 场景 | 处置 |
| --- | --- |
| 口令泄露 | 改 `admin.env` + 重置散列（见 B5） |
| JWT 泄露 | 改 `ADMIN_JWT_SECRET` 并重启，令牌立即全部失效 |
| 怀疑被入侵 | 停 8000/3000 → 轮换 `admin.env` 全部密钥 → 检查 `data/db.json` 与 PG |
| 需要离线 | 停隧道（`cloudflared.exe` 进程），仅保留局域网访问 |

## 七、检查清单（上线前）

- [x] 密钥不进版本库（`admin.env` 已 gitignore）
- [x] 口令加盐散列
- [x] 受控接口强制 JWT
- [x] 权限按 18 项细粒度校验
- [x] 管理员账号防锁死
- [x] 数据库仅绑本机
- [ ] Admin 8000 改绑 127.0.0.1
- [ ] 固定公网域名 + 访问控制
- [ ] 定期备份 PG
