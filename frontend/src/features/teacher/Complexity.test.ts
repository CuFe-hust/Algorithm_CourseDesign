// @vitest-environment jsdom
/**
 * Teacher overview of trace-based complexity reports: the published verdict per
 * student, without the raw counts. The API is stubbed, so nothing here depends
 * on the backend.
 */
import { createApp, defineComponent, h, nextTick } from "vue";
import { afterEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({
  request: vi.fn(),
}));
vi.mock("../../shared/session", () => ({
  session: { courseId: "1" },
}));
vi.mock("../../shared/api", async (original) => ({
  ...(await original<typeof import("../../shared/api")>()),
  request: mocks.request,
}));
import Complexity from "./Complexity.vue";

let cleanup: (() => void) | undefined;
afterEach(() => {
  cleanup?.();
  vi.clearAllMocks();
});

interface FixtureItem {
  item_id: string;
  assignment_id: string;
  assignment_title: string;
  problem_code: string;
  title: string;
  profile_family: string | null;
}
interface FixtureReport {
  student_id: string;
  student_no: string;
  name: string;
  assignment_item_id: string;
  title: string;
  submission_id: string;
  status: string;
  time_class: string | null;
  space_class: string | null;
  time_confidence: string | null;
  time_source: string | null;
  requested_at: string | null;
}

const item: FixtureItem = {
  item_id: "1",
  assignment_id: "1",
  assignment_title: "演示作业：编程题",
  problem_code: "CODE-P01",
  title: "活动安排问题",
  profile_family: "INT_ARRAY_ROWS",
};
const report: FixtureReport = {
  student_id: "2",
  student_no: "DEMO2026001",
  name: "演示同学",
  assignment_item_id: "1",
  title: "活动安排问题",
  submission_id: "21",
  status: "SUCCEEDED",
  time_class: "O(n log n)",
  space_class: "O(n)",
  time_confidence: "MEDIUM",
  time_source: "TRACE",
  requested_at: "2026-10-27T22:58:16+08:00",
};
/** A row whose report measured nothing: no class, no confidence, no source. */
const unmeasured: FixtureReport = {
  ...report,
  status: "NOT_MEASURABLE",
  time_class: null,
  space_class: null,
  time_confidence: null,
  time_source: null,
};

type Handler = (path: string) => unknown;

function mount(handler: Handler) {
  mocks.request.mockImplementation((path: string) =>
    Promise.resolve(handler(path)),
  );
  const host = document.createElement("div");
  document.body.append(host);
  const app = createApp(Complexity);
  app.component(
    "RouterLink",
    defineComponent({
      props: { to: { type: String, default: "" } },
      setup:
        (props, { slots }) =>
        () =>
          h("a", { href: props.to }, slots.default?.()),
    }),
  );
  app.mount(host);
  cleanup = () => {
    app.unmount();
    host.remove();
  };
  return host;
}

function itemsResponse(rows: FixtureItem[]) {
  return { items: rows, total: rows.length };
}

function overviewResponse(rows: FixtureReport[]) {
  return { items: rows, total: rows.length };
}

async function settle() {
  // Two rounds: the overview response lands first, then the per-row reasons.
  for (let round = 0; round < 2; round++) {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await nextTick();
  }
}

function body(host: HTMLElement) {
  return host.textContent ?? "";
}

function rowCells(host: HTMLElement, studentNo: string): string[] {
  const row = [...host.querySelectorAll("tbody tr")].find((tr) =>
    tr.textContent?.includes(studentNo),
  );
  return row
    ? [...row.querySelectorAll("td")].map((td) =>
        (td.textContent ?? "").replace(/\s+/g, " ").trim(),
      )
    : [];
}

it("renders a succeeded report with item, status, class, confidence, source and time", async () => {
  const host = mount((path) => {
    if (path.startsWith("/analysis/courses/1/complexity/items"))
      return itemsResponse([item]);
    if (path.startsWith("/analysis/courses/1/complexity?"))
      return overviewResponse([report]);
    return {};
  });
  await settle();

  const cells = rowCells(host, "DEMO2026001");
  expect(cells[0]).toContain("演示同学");
  expect(cells[0]).toContain("DEMO2026001");
  expect(cells[1]).toBe("活动安排问题");
  expect(cells[2]).toBe("已完成");
  expect(cells[3]).toBe("O(n log n)");
  expect(cells[4]).toBe("中");
  expect(cells[5]).toBe("执行轨迹");
  expect(cells[6]).toMatch(/2026/);
  expect(host.querySelector(".badge.amber")).toBeTruthy();
  // The old static/dynamic split must not reappear.
  expect(body(host)).not.toContain("代码结构");
});

it("labels a not-measurable report as unable to conclude, with the stored reason", async () => {
  const host = mount((path) => {
    if (path.startsWith("/analysis/courses/1/complexity/items"))
      return itemsResponse([item]);
    if (path.startsWith("/analysis/courses/1/complexity?"))
      return overviewResponse([unmeasured]);
    if (path === "/analysis/submissions/21/complexity")
      return {
        submission_id: "21",
        status: "NOT_MEASURABLE",
        eligible: true,
        report: {
          status: "NOT_MEASURABLE",
          time: {},
          space: {},
          trace: {},
          limitations: ["该题尚未配置规模伸缩档"],
          error: "该题没有可用的伸缩档：平台无法测量增长",
        },
        reason: null,
      };
    return {};
  });
  await settle();

  const cells = rowCells(host, "DEMO2026001");
  expect(cells[2]).toContain("无法给出结论");
  expect(cells[2]).toContain("伸缩档");
  expect(cells[3]).toBe("—");
  expect(cells[4]).toBe("—");
  expect(cells[5]).toBe("—");
  expect(host.querySelector(".badge.gray")).toBeTruthy();
});

it("shows a pending row as analysing without inventing a class", async () => {
  const host = mount((path) => {
    if (path.startsWith("/analysis/courses/1/complexity/items"))
      return itemsResponse([item]);
    if (path.startsWith("/analysis/courses/1/complexity?"))
      return overviewResponse([
        {
          ...report,
          status: "PENDING",
          time_class: null,
          space_class: null,
          time_confidence: null,
          time_source: null,
        },
      ]);
    return {};
  });
  await settle();

  const cells = rowCells(host, "DEMO2026001");
  expect(cells[2]).toBe("分析中");
  expect(cells[3]).toBe("—");
  expect(cells[4]).toBe("—");
  expect(cells[5]).toBe("—");
  expect(body(host)).not.toContain("O(1)");
  expect(body(host)).toContain("仍在分析中");
});

it("shows the stored reason for a failed report instead of an empty class", async () => {
  const host = mount((path) => {
    if (path.startsWith("/analysis/courses/1/complexity/items"))
      return itemsResponse([item]);
    if (path.startsWith("/analysis/courses/1/complexity?"))
      return overviewResponse([
        {
          ...report,
          status: "FAILED",
          time_class: null,
          space_class: null,
          time_confidence: null,
          time_source: null,
        },
      ]);
    if (path === "/analysis/submissions/21/complexity")
      return {
        submission_id: "21",
        status: "FAILED",
        eligible: true,
        report: null,
        reason: "LEASE_EXPIRED: 分析超时，请重新请求",
      };
    return {};
  });
  await settle();

  const cells = rowCells(host, "DEMO2026001");
  expect(cells[2]).toContain("分析失败");
  expect(cells[2]).toContain("分析超时");
  expect(cells[3]).toBe("—");
  expect(body(host)).not.toContain("O(1)");
});

it("warns when the selected item has no scale profile", async () => {
  const host = mount((path) => {
    if (path.startsWith("/analysis/courses/1/complexity/items"))
      return itemsResponse([{ ...item, profile_family: null }]);
    if (path.startsWith("/analysis/courses/1/complexity?"))
      return overviewResponse([]);
    return {};
  });
  await settle();

  expect(body(host)).toContain("该题没有配置规模伸缩档");
  expect(body(host)).toContain("无法给出结论");
  expect(host.querySelector('select[aria-label="选择题目"]')).toBeTruthy();
});

it("explains who can request a report when the table is empty", async () => {
  const host = mount((path) => {
    if (path.startsWith("/analysis/courses/1/complexity/items"))
      return itemsResponse([item]);
    if (path.startsWith("/analysis/courses/1/complexity?"))
      return overviewResponse([]);
    return {};
  });
  await settle();

  expect(body(host)).toContain("还没有这道题的复杂度报告");
  expect(body(host)).toContain("学生端");
  for (const button of host.querySelectorAll("button"))
    expect(button.textContent).not.toMatch(/批量|分析全部/);
});

it("selects the first item with a scale profile by default", async () => {
  const host = mount((path) => {
    if (path.startsWith("/analysis/courses/1/complexity/items"))
      return itemsResponse([
        {
          ...item,
          item_id: "7",
          problem_code: "CODE-P00",
          profile_family: null,
        },
        { ...item, item_id: "8", problem_code: "CODE-P02" },
      ]);
    if (path.startsWith("/analysis/courses/1/complexity?"))
      return overviewResponse([]);
    return {};
  });
  await settle();

  expect(
    host.querySelector<HTMLSelectElement>('select[aria-label="选择题目"]')
      ?.value,
  ).toBe("8");
  expect(mocks.request).toHaveBeenCalledWith(
    expect.stringContaining("assignment_item_id=8"),
  );
});

it("caps automatic refresh instead of polling forever", async () => {
  vi.useFakeTimers();
  try {
    const host = mount((path) => {
      if (path.startsWith("/analysis/courses/1/complexity/items"))
        return itemsResponse([item]);
      return overviewResponse([{ ...report, status: "PENDING" }]);
    });
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(10 * 60 * 1000);
    const calls = mocks.request.mock.calls.filter((call) =>
      String(call[0]).startsWith("/analysis/courses/1/complexity?"),
    ).length;
    // One initial request plus POLL_LIMIT polls, and then nothing more.
    expect(calls).toBeLessThanOrEqual(46);
    expect(calls).toBeGreaterThan(1);
    expect(body(host)).toContain("已停止自动刷新");
    await vi.advanceTimersByTimeAsync(10 * 60 * 1000);
    expect(
      mocks.request.mock.calls.filter((call) =>
        String(call[0]).startsWith("/analysis/courses/1/complexity?"),
      ).length,
    ).toBe(calls);
  } finally {
    vi.useRealTimers();
  }
});

it("stops polling when the page is left with a request in flight", async () => {
  vi.useFakeTimers();
  try {
    let release: ((value: unknown) => void) | undefined;
    mocks.request.mockImplementation((path: string) => {
      if (path.startsWith("/analysis/courses/1/complexity/items"))
        return Promise.resolve(itemsResponse([item]));
      if (path.startsWith("/analysis/courses/1/complexity?"))
        return new Promise((resolve) => {
          release = resolve;
        });
      return Promise.resolve({});
    });
    const host = document.createElement("div");
    document.body.append(host);
    const app = createApp(Complexity);
    app.component(
      "RouterLink",
      defineComponent({
        props: { to: { type: String, default: "" } },
        setup:
          (props, { slots }) =>
          () =>
            h("a", { href: props.to }, slots.default?.()),
      }),
    );
    app.mount(host);
    await vi.advanceTimersByTimeAsync(0);
    const before = mocks.request.mock.calls.length;
    app.unmount();
    host.remove();
    release?.(overviewResponse([{ ...report, status: "PENDING" }]));
    await vi.advanceTimersByTimeAsync(120_000);
    expect(mocks.request.mock.calls.length).toBe(before);
  } finally {
    vi.useRealTimers();
  }
});

it("links a student to the progress page of that student", async () => {
  const host = mount((path) => {
    if (path.startsWith("/analysis/courses/1/complexity/items"))
      return itemsResponse([item]);
    return overviewResponse([report]);
  });
  await settle();
  const link = [...host.querySelectorAll("a")].find((anchor) =>
    anchor.textContent?.includes("演示同学"),
  );
  expect(link?.getAttribute("href")).toBe("/teacher/students/2/progress");
});

it("queues analysis for the whole item from the teacher page", async () => {
  const host = mount((path) => {
    if (path.startsWith("/analysis/courses/1/complexity/items"))
      return itemsResponse([item]);
    if (path.startsWith("/analysis/courses/1/complexity/batch"))
      return { queued: 3, skipped: 1, ineligible: 2 };
    return overviewResponse([report]);
  });
  await settle();
  const button = [...host.querySelectorAll("button")].find((b) =>
    b.textContent?.includes("排队分析"),
  );
  expect(button).toBeDefined();
  await button!.click();
  await settle();
  const posted = mocks.request.mock.calls.find((call) =>
    String(call[0]).includes("/complexity/batch"),
  );
  expect(posted).toBeDefined();
  expect(host.textContent).toContain("已为 3 份提交排队分析");
});

it("hides the batch button when the item has no scale profile", async () => {
  const host = mount((path) => {
    if (path.startsWith("/analysis/courses/1/complexity/items"))
      return itemsResponse([{ ...item, profile_family: null }]);
    return overviewResponse([]);
  });
  await settle();
  const button = [...host.querySelectorAll("button")].find((b) =>
    b.textContent?.includes("排队分析"),
  );
  expect(button?.disabled).toBe(true);
});

it("renders a report with no request time without crashing", async () => {
  const host = mount((path) => {
    if (path.startsWith("/analysis/courses/1/complexity/items"))
      return itemsResponse([item]);
    return overviewResponse([{ ...report, requested_at: null }]);
  });
  await settle();
  const cells = rowCells(host, "DEMO2026001");
  expect(cells[0]).toContain("演示同学");
  // An em dash, not "1970年1月1日": formatting a null timestamp still yields a
  // date, so asserting only "no undefined" would not catch it.
  expect(cells[6]).toBe("—");
  expect(body(host)).not.toContain("1970");
});
