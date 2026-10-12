// End-to-end smoke test through the Express proxy (port 3000).
const BASE = process.env.BASE || "http://127.0.0.1:3000";

async function j(path, { method = "GET", body, token } = {}) {
  const headers = {};
  if (body !== undefined) headers["content-type"] = "application/json";
  if (token) headers.authorization = "Bearer " + token;
  const res = await fetch(BASE + path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("json") ? await res.json() : await res.text();
  return { status: res.status, data };
}

(async () => {
  const health = await j("/health");
  console.log("1) web/health        ", health.status, JSON.stringify(health.data));

  const login = await j("/api/auth/login", {
    method: "POST",
    body: { username: "admin", password: process.env.ADMIN_PW || "<ADMIN_PASSWORD>" },
  });
  console.log("2) login             ", login.status,
    login.status === 200 ? "token=OK" : JSON.stringify(login.data));
  if (login.status !== 200) process.exit(1);
  const tok = login.data.access_token;

  const me = await j("/api/auth/me", { token: tok });
  console.log("3) auth/me           ", me.status, JSON.stringify(me.data));

  const st = await j("/api/status", { token: tok });
  console.log("4) api/status        ", st.status, JSON.stringify(st.data));

  const combos = await j("/api/combos", { token: tok });
  console.log("5) api/combos        ", combos.status, "count=" + combos.data.count);
  for (const c of (combos.data.combos || []).slice(0, 5)) {
    console.log("     group=" + c.group + " corr=" + c.correlation +
      " legs=" + c.legs.map((l) => l.symbol).join("/"));
  }

  const h1 = await j("/api/hedge/calculate", {
    method: "POST", token: tok,
    body: { mode: "value", value_a: 100, value_b: 175, equity: 100000, lots: 0.01 },
  });
  console.log("6) hedge value       ", h1.status,
    "ratio=" + h1.data.requested_ratio + " lots=" + h1.data.lots +
    " risk=" + h1.data.risk_triggered);

  const h2 = await j("/api/hedge/calculate", {
    method: "POST", token: tok,
    body: { mode: "value", value_a: 100000, value_b: 100000, equity: 1000, lots: 1 },
  });
  console.log("7) hedge risk cap    ", h2.status,
    "final=" + h2.data.final_ratio + " risk=" + h2.data.risk_triggered +
    " lots=" + h2.data.lots + " floored=" + h2.data.lot_floored);

  const h3 = await j("/api/hedge/calculate", {
    method: "POST", token: tok,
    body: { mode: "volatility", value_a: 1, value_b: 1, vol_a: 2, vol_b: 1, corr: 0.9, equity: 100000, lots: 0.01 },
  });
  console.log("8) hedge volatility  ", h3.status, "ratio=" + h3.data.requested_ratio);

  // screenshot round-trip (1x1 PNG)
  const png = Buffer.from(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==",
    "base64"
  );
  const fd = new FormData();
  fd.append("file", new Blob([png], { type: "image/png" }), "t.png");
  const up = await fetch(BASE + "/api/shots", {
    method: "POST", headers: { authorization: "Bearer " + tok }, body: fd,
  });
  const shot = await up.json();
  console.log("9) shot upload       ", up.status, "id=" + (shot.id || "-"));

  if (shot.id) {
    const rd = await fetch(`${BASE}/api/shots/${shot.id}`, {
      headers: { authorization: "Bearer " + tok },
    });
    console.log("10) shot read        ", rd.status, "bytes=" + (await rd.arrayBuffer()).byteLength);
    const del = await j("/api/shots/" + shot.id, { method: "DELETE", token: tok });
    console.log("11) shot delete      ", del.status, JSON.stringify(del.data));
  }

  const idx = await j("/");
  console.log("12) m.html served    ", idx.status,
    typeof idx.data === "string" && idx.data.includes("量子套利") ? "content=OK" : "content=BAD");

  const noauth = await j("/api/shots");
  console.log("13) shots no token   ", noauth.status, "(expect 401)");
})().catch((e) => {
  console.error("FATAL", e);
  process.exit(1);
});