// Credentials come from the environment so no secret is ever committed.
//   set ADMIN_PW=...   then:  node rbac_smoke.mjs
const ADMIN_PW = process.env.ADMIN_PW || "<ADMIN_PASSWORD>";

const BASE = "http://127.0.0.1:8000";

async function j(path, { method = "GET", body, token, lic } = {}) {
  const headers = {};
  if (body !== undefined) headers["content-type"] = "application/json";
  if (token) headers.authorization = "Bearer " + token;
  if (lic) headers["x-license-key"] = lic;
  const res = await fetch(BASE + path, {
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("json") ? await res.json() : await res.text();
  return { status: res.status, data };
}

const ok = (c, m) => console.log((c ? "PASS" : "FAIL") + " | " + m);

(async () => {
  // 1. admin login
  const login = await j("/api/auth/login", {
    method: "POST", body: { username: "admin", password: ADMIN_PW },  });
  ok(login.status === 200 && login.data.role === "admin", "admin login, super-admin");
  const T = login.data.access_token;

  // 2. catalog has 5 categories
  const cat = await j("/api/rbac/catalog", { token: T });
  const cats = cat.data.categories || [];
  ok(cats.length === 5, `catalog exposes 5 categories (got ${cats.length}: ${cats.map(c=>c.key).join(",")})`);
  ok(cats.some(c=>c.key==="combo")&&cats.some(c=>c.key==="trade")&&cats.some(c=>c.key==="me")&&cats.some(c=>c.key==="notice")&&cats.some(c=>c.key==="backend"), "all 5 category keys present");

  // 3. create a limited user (viewer preset -> combo:read etc, no trade:order)
  const uname = "trader1";
  const created = await j("/api/rbac/users", {
    method: "POST", token: T,
    body: { username: uname, password: "User@1234", role: "viewer", display_name: "交易员一号", permissions: [] },
  });
  ok([200, 201].includes(created.status), `create user ${uname} (status ${created.status})`);

  // 4. login as that user
  const ulogin = await j("/api/auth/login", {
    method: "POST", body: { username: uname, password: "User@1234" },
  });
  ok(ulogin.status === 200, "limited user login");
  const U = ulogin.data.access_token;
  const uperms = ulogin.data.permissions || [];
  ok(uperms.includes("combo:read"), "viewer has combo:read");
  ok(!uperms.includes("trade:order"), "viewer does NOT have trade:order");

  // 5. limited user can read combos
  const combos = await j("/api/combos", { token: U });
  ok(combos.status === 200, "viewer can read /api/combos");

  // 6. limited user can calculate hedge (trade:read in viewer preset)
  const hedge = await j("/api/hedge/calculate", {
    method: "POST", token: U,
    body: { mode: "value", value_a: 100, value_b: 175, equity: 100000, lots: 0.01 },
  });
  ok(hedge.status === 200, "viewer can calculate hedge (has trade:read)");

  // 7. limited user CANNOT list users (backend:users is admin-only)
  const lu = await j("/api/rbac/users", { token: U });
  ok(lu.status === 403, `viewer blocked from /api/rbac/users (got ${lu.status})`);

  // 8. admin grants trade:order + combo:write to the user
  const grant = await j(`/api/rbac/users/${uname}/permissions`, {
    method: "PUT", token: T,
    body: { permissions: { "combo:read": "allow", "combo:write": "allow", "trade:read": "allow", "trade:order": "allow", "notice:read": "allow" } },
  });
  ok(grant.status === 200, `admin grants perms to ${uname}`);
  ok((grant.data.effective||[]).includes("trade:order"), "trade:order now effective");

  // 9. re-login reflects new perms
  const ulogin2 = await j("/api/auth/login", {
    method: "POST", body: { username: uname, password: "User@1234" },
  });
  ok((ulogin2.data.permissions||[]).includes("trade:order"), "re-login shows trade:order");

  // 10. admin-only create license works, and license activate/validate works
  const lic = await j("/api/licenses", {
    method: "POST", token: T, body: { label: "smoke", plan: "pro", max_machines: 2, days: 30 },
  });
  ok(lic.status === 200 && !!lic.data.key, "admin creates license key");
  const act = await j("/api/licenses/activate", {
    method: "POST", body: { key: lic.data.key, fingerprint: "fp-smoke-1" },
  });
  ok(act.status === 200 && act.data.valid === true, "license activate valid");
  const val = await j("/api/licenses/validate", {
    method: "POST", body: { key: lic.data.key, fingerprint: "fp-smoke-1" },
  });
  ok(val.data.valid === true, "license validate valid");
  const bad = await j("/api/licenses/activate", {
    method: "POST", body: { key: "QE-BOGUS-BOGUS", fingerprint: "x" },
  });
  ok(bad.data.valid === false && bad.data.code === "not_found", "bogus license rejected");

  // 11. admin cannot be edited/deleted via RBAC API
  const editAdmin = await j("/api/rbac/users/admin", {
    method: "PATCH", token: T, body: { role: "viewer" },
  });
  ok(editAdmin.status === 400, "admin role protected from edit");

  // cleanup the smoke user + license
  await j(`/api/rbac/users/${uname}`, { method: "DELETE", token: T });
  await j(`/api/licenses/${lic.data.id}`, { method: "DELETE", token: T });
  console.log("cleanup done");
})().catch((e) => { console.error("FATAL", e); process.exit(1); });
