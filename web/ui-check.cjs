// Renders m.html in a real browser and exercises the login + calculator flow.
const { chromium } = require("playwright-core");

(async () => {
  const exe =
    process.env.CHROME_PATH ||
    "D:\\AI\\playwright-browsers\\chromium-1181\\chrome-win\\chrome.exe";
  const browser = await chromium.launch({ executablePath: exe, headless: true });
  const page = await browser.newPage({ viewport: { width: 420, height: 860 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });

  await page.goto("http://127.0.0.1:3000/", { waitUntil: "networkidle" });
  console.log("title:", await page.title());
  console.log("api pill:", (await page.textContent("#pillApi")).trim());

  await page.fill("#p", "ChangeMe123!");
  await page.click("#btnLogin");
  await page.waitForTimeout(1500);
  console.log("auth pill after login:", (await page.textContent("#pillAuth")).trim());
  console.log("drawer rows:", await page.locator("#drawer .combo").count());

  await page.click("#btnCalc");
  await page.waitForTimeout(1200);
  const res = (await page.textContent("#result")).replace(/\s+/g, " ").trim();
  console.log("calc result:", res.slice(0, 160));

  await page.screenshot({ path: "D:\\AI\\web\\data\\m-420.png" });
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.waitForTimeout(400);
  await page.screenshot({ path: "D:\\AI\\web\\data\\m-1280.png" });
  console.log("page errors:", errors.length ? errors : "none");

  await browser.close();
})().catch((e) => {
  console.error("FATAL", e.message);
  process.exit(1);
});