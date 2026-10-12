// Renders every page and exercises the real flows.
const { chromium } = require("playwright-core");
const BASE = process.env.BASE || "http://127.0.0.1:3000";
const pages = [
  ["points", "/points.html"],
  ["notice", "/notice.html"],
  ["me", "/me.html"],
  ["register", "/register.html?ref=EDEVSD"],
];

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH, headless: true,
  });
  const ctx = await browser.newContext({ viewport: { width: 420, height: 900 } });
  const page = await ctx.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));
  page.on("console", (m) => { if (m.type() === "error" && !m.text().includes("favicon")) errors.push("console: " + m.text()); });

  // login first so authenticated pages have a token
  await page.goto(BASE + "/", { waitUntil: "networkidle" });
  await page.fill("#p", process.env.ADMIN_PW || "<ADMIN_PASSWORD>");
  await page.click("#btnLogin");
  await page.waitForTimeout(1500);
  console.log("login:", (await page.textContent("#pillAuth")).trim());

  for (const [name, path] of pages) {
    await page.goto(BASE + path, { waitUntil: "networkidle" });
    await page.waitForTimeout(1300);
    const title = await page.title();
    const bodyLen = (await page.innerText("body")).length;
    console.log(`${name.padEnd(9)} title="${title}" text=${bodyLen}ch`);
    await page.screenshot({ path: `D:\\AI\\web\\data\\page-${name}.png` });
  }

  // points page specific assertions
  await page.goto(BASE + "/points.html", { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  console.log("points balance :", (await page.textContent("#pts")).trim());
  console.log("team total    :", (await page.textContent("#total")).trim());
  console.log("ref code      :", (await page.textContent("#refcode")).trim());
  console.log("ref link      :", (await page.inputValue("#reflink")).trim());
  console.log("team rows     :", await page.locator("#teamWrap tbody tr").count());
  console.log("ledger rows   :", await page.locator("#ledgerWrap tbody tr").count());

  console.log("errors:", errors.length ? errors : "none");
  await browser.close();
})().catch((e) => { console.error("FATAL", e.message); process.exit(1); });