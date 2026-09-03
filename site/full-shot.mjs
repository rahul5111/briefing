import { chromium } from "playwright";
const url = process.argv[2] || "https://briefing-psi-ten.vercel.app/";
const out = process.argv[3] || "full.png";
const [w, h] = (process.argv[4] || "1440x900").split("x").map(Number);
const browser = await chromium.launch({ args: ["--autoplay-policy=no-user-gesture-required"] });
const page = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2 }).then(c => c.newPage());
await page.goto(url, { waitUntil: "domcontentloaded" });
await page.addStyleTag({ content: "astro-dev-toolbar { display: none !important; }" });
// scroll all the way to trigger any lazy renders + wait for images
await page.evaluate(async () => {
  await new Promise((res) => {
    let y = 0;
    const step = 400;
    const id = setInterval(() => {
      window.scrollTo(0, y);
      y += step;
      if (y >= document.body.scrollHeight) { clearInterval(id); window.scrollTo(0,0); setTimeout(res, 400); }
    }, 60);
  });
});
await page.waitForTimeout(1500);
await page.screenshot({ path: out, fullPage: true });
console.log("saved", out);
await browser.close();
