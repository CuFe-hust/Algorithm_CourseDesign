/**
 * Headless Edge capture for the UI review. Requires the synthetic mock API on
 * 127.0.0.1:8000 and one Vite dev server per build:
 *   before: http://127.0.0.1:5174 (clean HEAD worktree)
 *   after:  http://127.0.0.1:5173 (working tree)
 *
 * Usage: node capture.mjs <before|after> <base-url>
 */
import { chromium } from "playwright-core";
import fs from "node:fs";
import path from "node:path";

const label = process.argv[2] || "after";
const base = process.argv[3] || "http://127.0.0.1:5173";
const edge = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const outDir = path.resolve("screenshots", label);
fs.mkdirSync(outDir, { recursive: true });

const studentSession = {
  token: "mock-student-token",
  user: { id: "1", login_name: "demo.student01", full_name: "林晓" },
  course: "1",
};
const teacherSession = {
  token: "mock-teacher-token",
  user: { id: "2", login_name: "demo.teacher", full_name: "周老师" },
  course: "2",
};

const pages = [
  {
    slug: "student-submission",
    path: "/student/courses/1/submissions/1",
    session: studentSession,
    waitFor: "提交状态",
    widths: [1440, 768, 720, 390],
  },
  {
    slug: "student-review-form",
    path: "/student/courses/1/reviews/5",
    session: studentSession,
    waitFor: "待评作品",
    widths: [1440, 768, 720, 390],
  },
  {
    slug: "student-ability",
    path: "/student/courses/1/ability?demo=1&model=d1",
    session: studentSession,
    waitFor: "个人章节表现",
    widths: [1440, 768, 720, 390],
  },
  {
    slug: "teacher-review-preview",
    path: "/teacher/reviews/7",
    session: teacherSession,
    waitFor: "待确认预览",
    widths: [1440, 768, 720, 390],
  },
];

const browser = await chromium.launch({ executablePath: edge, headless: true });
const report = [];

for (const spec of pages) {
  for (const width of spec.widths) {
    const context = await browser.newContext({
      viewport: { width, height: width <= 390 ? 900 : 1000 },
      locale: "zh-CN",
    });
    await context.addInitScript((session) => {
      sessionStorage.setItem("algoclass.token", session.token);
      sessionStorage.setItem("algoclass.user", JSON.stringify(session.user));
      sessionStorage.setItem(
        `algoclass.course.${session.user.id}`,
        session.course,
      );
    }, spec.session);
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(String(error)));
    await page.goto(`${base}${spec.path}`, { waitUntil: "domcontentloaded" });
    await page.waitForFunction(
      (text) => document.body.innerText.includes(text),
      spec.waitFor,
      { timeout: 15000 },
    );
    await page.waitForTimeout(350);
    const metrics = await page.evaluate(() => {
      const style = (selector) => {
        const element = document.querySelector(selector);
        if (!element) return null;
        const computed = getComputedStyle(element);
        return {
          fontSize: computed.fontSize,
          lineHeight: computed.lineHeight,
          color: computed.color,
        };
      };
      const overflowing = [...document.querySelectorAll("*")]
        .filter((element) => {
          const style = getComputedStyle(element);
          return (
            style.overflowX === "visible" &&
            element.scrollWidth > element.clientWidth + 1
          );
        })
        .slice(0, 6)
        .map((element) => ({
          tag: element.tagName.toLowerCase(),
          className: String(element.className).slice(0, 80),
          scrollWidth: element.scrollWidth,
          clientWidth: element.clientWidth,
        }));
      return {
        innerWidth: window.innerWidth,
        htmlScrollWidth: document.documentElement.scrollWidth,
        bodyScrollWidth: document.body.scrollWidth,
        pageOverflow: document.documentElement.scrollWidth > window.innerWidth + 1,
        overflowing,
        body: style("body"),
        eyebrow: style(".eyebrow"),
        navLink: style(".sidebar nav a"),
        tableCell: style("td"),
        hint: style(".hint"),
        badge: style(".badge"),
        button: style("button"),
        skipLink: Boolean(document.querySelector(".skip-link")),
        ariaCurrent: document.querySelectorAll('[aria-current="page"]').length,
      };
    });
    const file = path.join(outDir, `${spec.slug}-${width}.png`);
    await page.screenshot({ path: file, fullPage: true });
    report.push({ page: spec.slug, width, errors, ...metrics });
    console.log(JSON.stringify(report.at(-1)));
    await context.close();
  }
}

// The peer-review form exposes inline field errors after an empty submit.
{
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await context.addInitScript((session) => {
    sessionStorage.setItem("algoclass.token", session.token);
    sessionStorage.setItem("algoclass.user", JSON.stringify(session.user));
    sessionStorage.setItem(`algoclass.course.${session.user.id}`, session.course);
  }, studentSession);
  const page = await context.newPage();
  await page.goto(`${base}/student/courses/1/reviews/5`, {
    waitUntil: "domcontentloaded",
  });
  await page.waitForFunction(() => document.body.innerText.includes("待评作品"));
  await page.locator("form button[type=submit], form button.primary").first().click();
  await page.waitForTimeout(250);
  const formState = await page.evaluate(() => ({
    invalidFields: document.querySelectorAll('[aria-invalid="true"]').length,
    fieldErrors: document.querySelectorAll(".field-error").length,
    errorText: document.querySelector(".alert.error")?.textContent || "",
    formStatus: document.querySelector(".form-status")?.textContent || "",
  }));
  await page.locator(".review-card").nth(2).scrollIntoViewIfNeeded();
  await page.waitForTimeout(150);
  const file = path.join(outDir, "student-review-form-errors-1440.png");
  await page.screenshot({ path: file, fullPage: false });
  report.push({ page: "student-review-form-errors", width: 1440, ...formState });
  console.log(JSON.stringify(report.at(-1)));
  await context.close();
}

fs.writeFileSync(
  path.join(outDir, "metrics.json"),
  JSON.stringify(report, null, 2) + "\n",
  "utf8",
);
await browser.close();
