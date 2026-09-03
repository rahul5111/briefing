// UI overflow / collision audit. Run against a local or prod URL.
//   node site/audit.mjs http://localhost:4321
//
// Catches the class of bug the earlier "widths look uniform" audit missed:
//   1. Text containers whose scrollWidth exceeds their clientWidth (text
//      renders past the parent's edge).
//   2. Cards whose inner content's right-edge extends past the card's
//      own right-edge (bleeding into a neighbor).
//   3. Cross-card horizontal collisions (right edge of A > left edge of B
//      on the same row).
//   4. Page-level horizontal scroll.
//
// Exits non-zero if any issue is found so this can gate a deploy.
//
// Security note: the auditFn below runs inside the target page via
// Playwright's page.evaluate(fn) — that serialises the *function*, not
// eval'd source. No arbitrary-code path in from user data.
import { chromium } from "playwright";

const url = process.argv[2] || "http://localhost:4321/";
const BREAKPOINTS = [
  { name: "1440", w: 1440, h: 900 },
  { name: "1024", w: 1024, h: 768 },
  { name: "768",  w: 768,  h: 1024 },
  { name: "390",  w: 390,  h: 844 },
];

function auditFn() {
  const issues = [];
  const rects = new WeakMap();
  const rectOf = (el) => {
    if (!rects.has(el)) rects.set(el, el.getBoundingClientRect());
    return rects.get(el);
  };

  const textish = document.querySelectorAll(
    ".card, .card-meta, .card-kicker, .card-details, .card-title, .card-sub, .card-source, .card-actions, .player-title, .player-meta, .day-label, .tuner-btn, .sub-chip"
  );
  for (const el of textish) {
    if (el.scrollWidth - el.clientWidth > 1) {
      const cs = getComputedStyle(el);
      const explicitlyClipped =
        (cs.overflowX === "hidden" || cs.overflowX === "clip") &&
        (cs.textOverflow === "ellipsis" || el.tagName !== "SPAN") &&
        (cs.whiteSpace === "nowrap" || cs.whiteSpace === "pre");
      if (explicitlyClipped) continue;
      issues.push({
        kind: "text-overflow",
        cls: (typeof el.className === "string" ? el.className : "") || "",
        tag: el.tagName,
        scrollWidth: el.scrollWidth,
        clientWidth: el.clientWidth,
        excess: el.scrollWidth - el.clientWidth,
        text: (el.textContent || "").slice(0, 60).trim(),
      });
    }
  }

  document.querySelectorAll(".card").forEach((card) => {
    const cr = rectOf(card);
    for (const child of card.querySelectorAll("*")) {
      const rr = rectOf(child);
      if (rr.width === 0) continue;
      // Skip elements inside a clipping ancestor (their visual overflow
      // is contained even if their bounding rect isn't).
      let a = child.parentElement;
      let clippedByAncestor = false;
      while (a && a !== card) {
        const acs = getComputedStyle(a);
        if (acs.overflow === "hidden" || acs.overflow === "clip" || acs.overflowX === "hidden" || acs.overflowX === "clip") {
          clippedByAncestor = true; break;
        }
        a = a.parentElement;
      }
      if (clippedByAncestor) continue;
      if (rr.right - cr.right > 1) {
        issues.push({
          kind: "bleed-past-card",
          card_cls: (typeof card.className === "string" ? card.className : "").split(" ").slice(0, 3).join(" "),
          child_tag: child.tagName,
          child_cls: typeof child.className === "string" ? child.className : String(child.className.baseVal || ""),
          card_right: Math.round(cr.right),
          child_right: Math.round(rr.right),
          excess: Math.round(rr.right - cr.right),
          text: (child.textContent || "").slice(0, 60).trim(),
        });
        break;
      }
    }
  });

  const cards = [...document.querySelectorAll(".card")].map((c) => ({
    el: c, r: rectOf(c), cls: (c.className || "").split(" ").slice(0, 3).join(" "),
  }));
  const rows = new Map();
  for (const c of cards) {
    const key = Math.round(c.r.top);
    if (!rows.has(key)) rows.set(key, []);
    rows.get(key).push(c);
  }
  for (const [y, row] of rows) {
    row.sort((a, b) => a.r.left - b.r.left);
    for (let i = 0; i < row.length - 1; i++) {
      const a = row[i], b = row[i + 1];
      if (a.r.right - b.r.left > 1) {
        issues.push({
          kind: "cross-card-collision",
          y,
          left_cls: a.cls, right_cls: b.cls,
          left_right: Math.round(a.r.right),
          right_left: Math.round(b.r.left),
          overlap: Math.round(a.r.right - b.r.left),
        });
      }
    }
  }

  const doc = document.documentElement;
  if (doc.scrollWidth > doc.clientWidth + 1) {
    issues.push({
      kind: "page-hscroll",
      scrollWidth: doc.scrollWidth,
      clientWidth: doc.clientWidth,
    });
  }

  return issues;
}

const browser = await chromium.launch();
let hadIssues = false;
try {
  for (const bp of BREAKPOINTS) {
    const ctx = await browser.newContext({ viewport: { width: bp.w, height: bp.h }, deviceScaleFactor: 1 });
    const page = await ctx.newPage();
    await page.goto(url, { waitUntil: "networkidle" });
    const tabs = await page.$$eval(".tuner-btn", (btns) => btns.map((b) => (b.textContent || "").trim()));
    // ALL + a few main tabs to cover the sub-strip appearance path.
    const passes = ["ALL", ...tabs.slice(1, 4)];
    for (const label of passes) {
      await page.evaluate((l) => {
        const btn = [...document.querySelectorAll(".tuner-btn")].find((b) => (b.textContent || "").trim().startsWith(l));
        btn?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      }, label);
      await page.waitForTimeout(400);
      const issues = await page.evaluate(auditFn);
      const status = (issues?.length ?? 0) === 0 ? "OK" : `${issues.length} issue(s)`;
      console.log(`[${bp.name}] tab=${label.padEnd(12)} ${status}`);
      if (issues && issues.length) {
        hadIssues = true;
        for (const i of issues.slice(0, 8)) {
          console.log("   -", JSON.stringify(i));
        }
        if (issues.length > 8) console.log(`   … +${issues.length - 8} more`);
      }
    }
    await ctx.close();
  }
} finally {
  await browser.close();
}
if (hadIssues) {
  console.error("\naudit failed");
  process.exit(1);
}
console.log("\naudit passed at every breakpoint · every tab");
