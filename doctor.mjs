/**
 * 一键体检 / doctor
 *
 * 检查：进程 -> 端口 -> 数据库 -> 本机 API -> 公网隧道。
 * 任何一项失败都会在结尾汇总，便于直接对照 TROUBLESHOOTING.md。
 *
 *   node D:\AI\doctor.mjs
 */

import { execSync } from "node:child_process";
import fs from "node:fs";

const results = [];
const ok = (m, extra = "") => results.push({ pass: true, m, extra });
const bad = (m, extra = "") => results.push({ pass: false, m, extra });

function portListening(port) {
  try {
    const out = execSync(
      `powershell -NoProfile -Command "(Get-NetTCPConnection -State Listen -LocalPort ${port} -ErrorAction SilentlyContinue) | Select-Object -First 1 -ExpandProperty OwningProcess"`,
      { encoding: "utf8", timeout: 20000 }
    );
    return out.trim() !== "";
  } catch {
    return false;
  }
}

function procExists(pattern) {
  try {
    const out = execSync(
      `powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match '${pattern}' } | Measure-Object | Select-Object -ExpandProperty Count"`,
      { encoding: "utf8", timeout: 20000 }
    );
    return parseInt(out.trim(), 10) || 0;
  } catch {
    return 0;
  }
}

async function getJson(url, opts = {}) {
  const res = await fetch(url, { ...opts, signal: AbortSignal.timeout(20000) });
  const ct = res.headers.get("content-type") || "";
  return { status: res.status, body: ct.includes("json") ? await res.json() : await res.text() };
}

(async () => {
  console.log("=== Quantum Arbitrage 系统体检 ===");
  console.log(new Date().toLocaleString("zh-CN"));
  console.log("");

  // --- processes ---
  const nPg = procExists("postgres");
  const nRd = procExists("redis-server");
  const nAdmin = procExists("uvicorn");
  const nWeb = procExists("server\\.js");
  const nTunnel = procExists("cloudflared");

  nPg ? ok("PostgreSQL 进程", `count=${nPg}`) : bad("PostgreSQL 进程", "未运行 -> D:\\AI\\pgsql\\start-pg.cmd");
  nRd ? ok("Redis 进程", `count=${nRd}`) : bad("Redis 进程", "未运行 -> D:\\AI\\redis\\start-redis.cmd");
  nAdmin ? ok("Admin Server 进程 (uvicorn)", `count=${nAdmin}`) : bad("Admin Server 进程", "未运行 -> D:\\AI\\server\\start-detached.cmd");
  nWeb ? ok("Web Client 进程 (node)", `count=${nWeb}`) : bad("Web Client 进程", "未运行 -> D:\\AI\\web\\start.cmd");
  nTunnel ? ok("公网隧道 (cloudflared)", `count=${nTunnel}`) : bad("公网隧道", "未运行 -> D:\\AI\\tunnel\\start.cmd");

  // --- ports ---
  for (const [port, name] of [[5432, "PostgreSQL"], [6379, "Redis"], [8000, "Admin"], [3000, "Web"]]) {
    portListening(port) ? ok(`端口 ${port} (${name})`) : bad(`端口 ${port} (${name})`, "未监听");
  }

  // --- admin api ---
  try {
    const h = await getJson("http://127.0.0.1:8000/health");
    h.status === 200 ? ok("Admin /health") : bad("Admin /health", `status=${h.status}`);
  } catch (e) { bad("Admin /health", e.message); }

  try {
    const s = await getJson("http://127.0.0.1:8000/api/status");
    const b = s.body;
    b.postgres ? ok("PostgreSQL 已连接") : bad("PostgreSQL 已连接", b.errors?.postgres || "见 TROUBLESHOOTING B1/B2");
    b.redis ? ok("Redis 已连接") : bad("Redis 已连接", b.errors?.redis || "见 TROUBLESHOOTING B3");
  } catch (e) { bad("Admin /api/status", e.message); }

  // --- web proxy ---
  try {
    const h = await getJson("http://127.0.0.1:3000/health");
    h.status === 200 ? ok("Web /health (3000 代理)") : bad("Web /health", `status=${h.status}`);
  } catch (e) { bad("Web /health", e.message); }

  // --- tunnel url ---
  let url = "";
  try { url = fs.readFileSync("D:/AI/tunnel/data/tunnel_url.txt", "utf8").trim(); } catch {}
  if (!url) {
    bad("隧道地址文件", "D:\\AI\\tunnel\\data\\tunnel_url.txt 不存在或为空");
  } else {
    ok("隧道地址文件", url);
    try {
      const h = await getJson(url + "/health");
      h.status === 200 ? ok("公网可达", url) : bad("公网可达", `status=${h.status}`);
    } catch (e) { bad("公网可达", `${url} -> ${e.message}`); }
  }

  // --- report ---
  console.log("");
  for (const r of results) {
    console.log(`${r.pass ? "PASS" : "FAIL"} | ${r.m}${r.extra ? "  [" + r.extra + "]" : ""}`);
  }
  const failed = results.filter((r) => !r.pass);
  console.log("");
  console.log(failed.length === 0
    ? "==> 全部正常"
    : `==> ${failed.length} 项异常，请对照 D:\\AI\\docs\\dev-log\\TROUBLESHOOTING.md`);
  process.exit(failed.length === 0 ? 0 : 1);
})().catch((e) => {
  console.error("体检脚本异常:", e);
  process.exit(2);
});
