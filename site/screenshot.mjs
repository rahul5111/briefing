import { chromium } from "playwright";

const url = process.argv[2] || "http://localhost:4321/";
const out = process.argv[3] || "screenshot.png";
const viewport = process.argv[4] || "1440x900";
const mode = process.argv[5] || "viewport"; // viewport | full
const [w, h] = viewport.split("x").map(Number);

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: w, height: h }, deviceScaleFactor: 2 });
const page = await ctx.newPage();

page.on("console", (msg) => console.log(`[console.${msg.type()}]`, msg.text()));
page.on("pageerror", (e) => console.log(`[pageerror]`, e.message));

await page.goto(url, { waitUntil: "networkidle", timeout: 20000 });

// Hide Astro dev toolbar for clean screenshots
await page.addStyleTag({ content: `astro-dev-toolbar { display: none !important; }` });

await page.waitForTimeout(600);
await page.screenshot({ path: out, fullPage: mode === "full" });
console.log(`saved ${out} (${w}x${h}, ${mode})`);

await browser.close();
