import { chromium } from "playwright";
const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
const page = await browser.newContext({ viewport: { width: 1440, height: 900 }, deviceScaleFactor: 2 }).then(c => c.newPage());
page.on("pageerror", (e) => console.log("PAGEERR", e.message));
await page.goto(process.argv[2] || "http://localhost:4321/", { waitUntil: "domcontentloaded" });
await page.addStyleTag({ content: "astro-dev-toolbar { display: none !important; }" });
await page.waitForTimeout(800);
// click the first story that has an image
await page.evaluate(() => {
  const cards = document.querySelectorAll(".card");
  for (const c of cards) {
    const t = c.querySelector("h2")?.textContent || "";
    if (t.includes("Gemini")) { c.click(); return; }
  }
  cards[0]?.click();
});
await page.waitForTimeout(3500);
await page.screenshot({ path: process.argv[3] || "player-shot.png", clip: { x: 0, y: 780, width: 1440, height: 120 } });
console.log("saved");
await browser.close();
