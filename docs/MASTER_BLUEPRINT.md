# 量子套利系统与 Web 终端总体规划方案 (Master Blueprint)

> 本文件由 Telegram 远程通道指令整理落盘，作为后续交给任何 AI 的顶层总纲。
> 落盘位置：`docs/MASTER_BLUEPRINT.md`（当前机器归档处 `D:\AI\docs\MASTER_BLUEPRINT.md`）。
> 注意：正文中引用的量子套利项目本体（FastAPI:8000 / Express:3000、`m.html`、`docs/ADMIN_CLIENT_SPLIT_GUIDE.md`、`docker-compose.admin.yml`）**不在此机器上**，本蓝图仅作内容归档与跨机移交总纲；部署时请以对应项目机器为准。

## 一、项目愿景与核心定位

打造一套轻量、高效、跨平台的统计套利与高正相关对冲交易监控系统。通过多品种纠缠分析、动态价值对冲比计算、暗黑风控终端与多端数据同步，实现 24 小时无人值守的量化交易辅助与看板监控。

## 二、现行技术栈与架构设计（已验证通车）

整个系统已成功解耦为 **服务端（Admin Server）** 与 **Web 前端（Responsive Web）** 两大独立体系，彻底抛弃原生 APK，实现 iOS/Android 跨平台双端零改动。

```
[ 用户端手机/电脑浏览器 ]
       │ (HTTP/WS)
       ▼
[ 前端 Express 同源代理 (Port 3000) ] ──(m.html / 静态看板)
       │
       ▼
[ 后端 FastAPI / Admin 服务 (Port 8000) ]
       ├── 数据库 (PostgreSQL + Redis / db.json 离线兜底)
       ├── 核心量化引擎 (Z-Score / 动态对冲比 / 25组 Markdown 解析)
       └── 外部通道 (Telegram Bot / Webhook 告警)
```

### 后端服务 (Admin Server - Port 8000)

- **技术核心**：Python FastAPI、配置项隔离（`admin.env` 配合 `.gitignore` 防泄密）、种子账号保底 (`admin / ChangeMe123!`)。
- **核心能力**：JWT 认证、Markdown 动态对冲组合解析（25 组）、截图上传写读删持久化、`/health` 与 `/api/status`（PG + Redis 双 true 校验）。
- **独立测试**：配备 pytest 隔离测试（如 `test_admin_isolation.py`），全量 95 项单测全绿。

### 前端网页端 (Web Client - Port 3000)

- **技术核心**：原生响应式 `m.html` + Express 同源代理，彻底避开 Flutter Web 编译 `dart:io` 的网络层陷阱。
- **核心能力**：抽屉式高正相关组合滑动、暗黑 K 线极值点解析、动态对冲计算器、管理看板、localStorage 离线断网缓存兜底。
- **多端访问**：同 WiFi 局域网（最稳）、外网穿透（localtunnel）、本机调试三线并行。

## 三、当前已落盘功能清单（Phase 1 ~ Phase 4 成果）

| 模块 | 功能特性 | 状态 | 技术实现落脚点 |
| --- | --- | --- | --- |
| 数据与解析 | ✅ 自动解析 25 组高正相关品种 Markdown 文档，支持降序与抽屉滑动 | 已上线 | 服务端解析层 + 前端滑动组件 |
| 对冲计算引擎 | ✅ 价值 / 保证金 / 波动率三模式，实现真实价值对冲动态计算（如 1:1.75 替代死板 1:1） | 已上线 | 后端计算引擎 + 前端计算器 |
| 风控与执行 | ✅ 1% 保证金风险上限与 0.01 Lot 截断硬风控逻辑 | 已上线 | 后端风控层 |
| 跨平台 Web 终端 | ✅ `m.html` 响应式暗黑终端，支持截图上传极值点解析与 Token 持久化 | 已上线 | 前端终端 + localStorage |
| 前后端解耦测试 | ✅ 服务端隔离 6/6、全量 95 测过；前端无回归风险，指南落盘 `docs/ADMIN_CLIENT_SPLIT_GUIDE.md` | 已上线 | pytest 隔离测试 |

## 四、后续演进路线图（Future Roadmap）

> 后续如需 AI 进一步扩展功能，可按以下三个阶段分步下达指令。

### Phase 5：云端容器化部署 (Docker 生产化)

- 利用现有的 `docker-compose.admin.yml` 与 `admin.env` 模板，一键部署到海外 VPS 节点。
- 引入 **Cloudflare Tunnel** 替代 localtunnel，消除外网穿透的密码输入步骤，保障 24 小时稳定挂机。

### Phase 6：实盘 API 穿透与自动跟单

- 对接 MT4/MT5 桥接网关（如 `chiyou.exe` Go 核心网关或 WebSocket 实时推送），将计算出的对冲信号直接转换成真实的跟单指令。

### Phase 7：商业化授权与 Keygen 接入

- 在管理后台（`accounts.html`）打通 QE 的 Keygen 授权校验接口，实现多用户 SaaS 化或者独立授权码登录。

## 五、给后续 AI 接手时的提示词模板（可直接复制）

> 接手须知：本项目是基于 Python FastAPI（后端 8000 端口）与 Express 响应式 Web（前端 3000 端口）的量子统计套利系统。两端已彻底解耦，不使用 Flutter APK。开发时请严格遵守端口隔离规范、优先查阅 `docs/ADMIN_CLIENT_SPLIT_GUIDE.md` 与本地 `.env` 配置，确保测试全绿（`pytest` / `flutter analyze`）。