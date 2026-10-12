// Verifies the permission console: login, create a user, grant perms via UI.
const { chromium } = require("playwright-core");
const BASE = process.env.BASE || "http://127.0.0.1:3000";

(async () => {
  const exe = process.env.CHROME_PATH;
  const browser = await chromium.launch({ executablePath: exe, headless: true });
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });

  // log in through the terminal first (token lives in localStorage)
  await page.goto(BASE + "/", { waitUntil: "networkidle" });
  await page.fill("#p", process.env.ADMIN_PW || "<ADMIN_PASSWORD>");
  await page.click("#btnLogin");
  await page.waitForTimeout(1200);
  console.log("login:", (await page.textContent("#pillAuth")).trim());

  // go to permission console
  await page.goto(BASE + "/permissions.html", { waitUntil: "networkidle" });
  await page.waitForTimeout(1200);
  console.log("who:", (await page.textContent("#who")).trim());
  const catCount = await page.locator(".permgroup").count();
  console.log("permission groups rendered:", catCount);
  console.log("user rows:", await page.locator("#rows tr").count());

  // create a user
  const uname = "uitest" + Date.now().toString().slice(-4);
  await page.fill("#nu", uname);
  await page.fill("#nd", "界面测试");
  await page.fill("#np", "Test@1234");
  await page.selectOption("#nr", "viewer");
  await page.click("#btnCreate");
  await page.waitForTimeout(1500);
  const rows = await page.locator("#rows tr").allTextContents();
  console.log("created user visible:", rows.some((r) => r.includes(uname)));

  // open the permission drawer for that user
  await page.locator(`#rows button:has-text("授权")`).last().click();
  await page.waitForTimeout(700);
  console.log("drawer open:", await page.locator("#drawer.open").count() > 0);
  const boxes = page.locator('#dBody input[type="checkbox"]');
  console.log("checkbox count:", await boxes.count());

  // grant trade:order and save
  await page.locator('#dBody input[data-key="trade:order"]').check();
  await page.click("#dSave");
  await page.waitForTimeout(1500);
  console.log("toast:", (await page.textContent("#toast")).trim());

  await page.screenshot({ path: "D:\\AI\\web\\data\\permissions.png", fullPage: true });
  console.log("page errors:", errors.filter((e) => !e.includes("favicon")).length ? errors : "none");
  await browser.close();
})().catch((e) => { console.error("FATAL", e.message); process.exit(1); });
