// @vitest-environment jsdom
/**
 * Behaviour of the trace-based complexity panel: the finished report (class,
 * method, recurrence, per-rung table, evidence), the states that must not
 * pretend to know a class, and the bounded polling the panel already had.
 *
 * The API module is stubbed, so nothing here depends on the backend.
 */
import { createApp, nextTick } from "vue";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  getComplexity: vi.fn(),
  requestComplexity: vi.fn(),
}));
vi.mock("./api", () => api);
vi.mock("../../../shared/api", () => ({
  errorText: (e: unknown) => String(e),
}));

import ComplexityPanel from "./components/ComplexityPanel.vue";

let cleanup: (() => void) | undefined;
afterEach(() => {
  cleanup?.();
  cleanup = undefined;
  vi.clearAllTimers();
  vi.useRealTimers();
});

beforeEach(() => {
  vi.useFakeTimers();
  api.getComplexity.mockReset();
  api.requestComplexity.mockReset();
});

function mount(
  props: { submissionId: string; autoLoad?: boolean } = { submissionId: "11" },
) {
  const host = document.createElement("div");
  document.body.append(host);
  const app = createApp(ComplexityPanel, props);
  app.mount(host);
  cleanup = () => {
    app.unmount();
    host.remove();
  };
  return host;
}

function pending() {
  return {
    submission_id: "11",
    status: "PENDING",
    eligible: true,
    report: null,
    reason: null,
  };
}

function timePayload(overrides: Record<string, unknown> = {}) {
  return {
    class: "O(n log n)",
    confidence: "HIGH",
    source: "TRACE",
    method: "RECURRENCE",
    closed_form: "Θ(n log n)",
    recurrence: "T(n) = 2·T(n/2) + O(n)",
    fit: {
      class: "O(n log n)",
      confidence: "HIGH",
      margin: 128.4,
      best: {
        class: "O(n log n)",
        r2: 0.9999,
        sse: 0.19,
        coefficient: 1.03,
        offset: 12,
      },
      candidates: [
        { class: "O(n log n)", r2: 0.9999, sse: 0.19 },
        { class: "O(n)", r2: 0.93, sse: 24.3 },
      ],
      notes: [],
    },
    notes: [],
    ...overrides,
  };
}

function spacePayload(overrides: Record<string, unknown> = {}) {
  return {
    class: "O(n)",
    confidence: "MEDIUM",
    source: "TRACE",
    fit: {
      class: "O(n)",
      confidence: "MEDIUM",
      margin: 4.2,
      best: {
        class: "O(n)",
        r2: 0.99,
        sse: 1.5,
        coefficient: 97.2,
        offset: 0,
      },
      candidates: [{ class: "O(n)", r2: 0.99, sse: 1.5 }],
      notes: [],
    },
    depth_fit: null,
    notes: [],
  };
}

function point(
  n: number,
  work: number,
  baseline: number,
  extra: Record<string, unknown> = {},
) {
  return {
    n,
    verdict: "OK",
    detail: null,
    work,
    baseline_work: baseline,
    line_events: work,
    jump_events: 0,
    library_work: 0,
    max_depth: 1,
    peak_bytes: null,
    ...extra,
  };
}

function succeeded(overrides: Record<string, unknown> = {}) {
  return {
    submission_id: "11",
    status: "SUCCEEDED",
    eligible: true,
    reason: null,
    report: {
      status: "SUCCEEDED",
      language: "python3",
      implementation_name: "complexity_probe",
      implementation_version: "2",
      time: timePayload(),
      space: spacePayload(),
      trace: {
        adapter: "python-monitoring-v1",
        work_unit: "行事件 + 跳转事件",
        input_family: "INT_ARRAY_ROWS",
        stop_reason: "OK",
        deterministic: true,
        repeat_delta: 0,
        notes: [],
        points: [
          point(256, 4200, 300),
          point(1024, 20100, 1200),
          point(4096, 96000, 4800),
          point(16384, 452000, 19200, { peak_bytes: 2400000, max_depth: 4 }),
        ],
        time: timePayload(),
        space: spacePayload(),
        evidence: [
          {
            kind: "RECURSION",
            function: "merge_sort",
            branching: 2,
            shrink: "HALVING",
            expression: "T(n) = 2·T(n/2) + O(n)",
            solution: "Θ(n log n)",
            share: 0.98,
          },
          {
            kind: "LINE",
            location: "merge:13",
            class: "O(n log n)",
            counts: [
              { n: 256, count: 2048 },
              { n: 1024, count: 10240 },
            ],
          },
        ],
      },
      limitations: [
        "输入由平台按题目伸缩档合成，报告描述的是在这类输入上的增长",
      ],
      error: null,
      requested_at: "2026-10-27T22:58:16+08:00",
      finished_at: "2026-10-27T22:58:40+08:00",
      ...overrides,
    },
  };
}

function failed() {
  return {
    submission_id: "11",
    status: "FAILED",
    eligible: true,
    reason: "LEASE_EXPIRED",
    report: {
      status: "FAILED",
      language: "python3",
      implementation_name: "complexity_probe",
      implementation_version: "2",
      time: {},
      space: {},
      trace: {},
      limitations: [],
      error: "LEASE_EXPIRED: 分析超时，请重新请求",
      requested_at: null,
      finished_at: null,
    },
  };
}

function notMeasurable() {
  return {
    submission_id: "11",
    status: "NOT_MEASURABLE",
    eligible: true,
    reason: null,
    report: {
      status: "NOT_MEASURABLE",
      language: "python3",
      implementation_name: "complexity_probe",
      implementation_version: "2",
      time: {},
      space: {},
      trace: {},
      limitations: [
        "该题尚未配置规模伸缩档，无法测量增长",
        "复杂度分析不参与评分，也不改变评测结果",
      ],
      error: "该题没有可用的伸缩档：平台无法测量增长",
      requested_at: "2026-10-27T22:58:16+08:00",
      finished_at: "2026-10-27T22:58:20+08:00",
    },
  };
}

function ineligible() {
  return {
    submission_id: "11",
    status: "INELIGIBLE",
    eligible: false,
    reason: "MOCK_RESULT_NOT_ANALYSABLE",
    report: {
      status: "INELIGIBLE",
      language: "python3",
      implementation_name: "complexity_probe",
      implementation_version: "2",
      time: {},
      space: {},
      trace: {},
      limitations: [],
      error: "模拟评测结果不参与复杂度分析，请使用真实执行结果",
      requested_at: null,
      finished_at: null,
    },
  };
}

async function advance(ms: number) {
  await vi.advanceTimersByTimeAsync(ms);
  await nextTick();
}

function rows(host: HTMLElement): string[][] {
  return [...host.querySelectorAll("tbody tr")].map((tr) =>
    [...tr.querySelectorAll("td")].map((td) =>
      (td.textContent ?? "").replace(/\s+/g, " ").trim(),
    ),
  );
}

describe("ComplexityPanel polling", () => {
  it("stops after a bounded number of polls instead of asking forever", async () => {
    api.getComplexity.mockResolvedValue(pending());
    mount();
    await advance(0);
    await advance(200_000);
    const calls = api.getComplexity.mock.calls.length;
    // 45 polls plus the initial load, and no more however long the clock runs.
    expect(calls).toBeLessThanOrEqual(46);
    expect(calls).toBeGreaterThan(1);
    await advance(200_000);
    expect(api.getComplexity.mock.calls.length).toBe(calls);
  });

  it("does not schedule another request after the component is unmounted", async () => {
    api.getComplexity.mockResolvedValue(pending());
    mount();
    await advance(0);
    await advance(1600);
    const before = api.getComplexity.mock.calls.length;
    cleanup?.();
    cleanup = undefined;
    await advance(60_000);
    expect(api.getComplexity.mock.calls.length).toBe(before);
  });
});

describe("ComplexityPanel succeeded report", () => {
  it("shows the class, method, closed form and recurrence", async () => {
    api.getComplexity.mockResolvedValue(succeeded());
    const host = mount();
    await advance(0);
    const text = host.textContent ?? "";
    expect(text).toContain("已完成");
    expect(text).toContain("O(n log n)");
    expect(text).toContain("递推推断");
    expect(text).toContain("Θ(n log n)");
    expect(text).toContain("T(n) = 2·T(n/2) + O(n)");
    expect(text).toContain("执行轨迹");
    // Space source is TRACE here; the space class comes from peak allocation.
    expect(text).toContain("O(n)");
    expect(text).not.toContain("undefined");
    expect(text).not.toContain("[object Object]");
  });

  it("draws the per-rung table with total, baseline-corrected work and memory", async () => {
    api.getComplexity.mockResolvedValue(succeeded());
    const host = mount();
    await advance(0);
    const cells = rows(host);
    expect(cells).toHaveLength(4);
    expect(cells[0]).toEqual(["256", "4,200", "3,900", "—"]);
    expect(cells[1]).toEqual(["1024", "20,100", "18,900", "—"]);
    expect(cells[3]![0]).toBe("16384");
    expect(cells[3]![1]).toBe("452,000");
    expect(cells[3]![2]).toBe("432,800");
    expect(cells[3]![3]).toBe("2.3 MiB");
    // One chart point per finished rung.
    expect(host.querySelectorAll("circle.point")).toHaveLength(4);
    expect(host.textContent).toContain("行事件 + 跳转事件");
  });

  it("lists line and recursion evidence", async () => {
    api.getComplexity.mockResolvedValue(succeeded());
    const host = mount();
    await advance(0);
    const text = (host.textContent ?? "").replace(/\s+/g, " ");
    expect(text).toContain("merge:13");
    expect(text).toContain("执行次数 Θ(n log n)");
    expect(text).toContain("merge_sort");
    expect(text).toContain("每层分 2 支");
    expect(text).toContain("规模每层减半");
    expect(text).toContain("闭式 Θ(n log n)");
  });

  it("renders a report without rungs instead of an empty axis", async () => {
    const fixture = succeeded();
    fixture.report.trace.points = [];
    api.getComplexity.mockResolvedValue(fixture);
    const host = mount();
    await advance(0);
    expect(rows(host)).toHaveLength(0);
    expect(host.querySelectorAll("circle.point")).toHaveLength(0);
    expect(host.textContent).toContain("没有留下可用的测量档位");
    expect(host.textContent).toContain("暂无可用档位");
  });

  it("asks for an analysis when the submission has no report yet", async () => {
    api.getComplexity.mockResolvedValue({
      submission_id: "11",
      status: "NONE",
      eligible: null,
      report: null,
      reason: null,
    });
    api.requestComplexity.mockResolvedValue({
      submission_id: "11",
      status: "PENDING",
    });
    const host = mount();
    await advance(0);
    const button = host.querySelector<HTMLButtonElement>("button.primary");
    expect(button?.textContent).toContain("分析这段代码的复杂度");
    button?.click();
    await advance(0);
    expect(api.requestComplexity).toHaveBeenCalledWith("11");
  });
});

describe("ComplexityPanel states without a class", () => {
  it("explains a not-measurable report with the stored reason and limitations", async () => {
    api.getComplexity.mockResolvedValue(notMeasurable());
    const host = mount();
    await advance(0);
    const text = host.textContent ?? "";
    expect(text).toContain("无法给出结论");
    expect(text).toContain("该题没有可用的伸缩档：平台无法测量增长");
    expect(text).toContain("该题尚未配置规模伸缩档，无法测量增长");
    expect(text).toContain("复杂度分析不参与评分");
    // The old structural conclusion must be gone for good.
    expect(text).not.toContain("仅结构分析");
    expect(text).not.toContain("结构证据");
    expect(host.querySelectorAll("circle.point")).toHaveLength(0);
    expect(
      [...host.querySelectorAll("button")].some((button) =>
        button.textContent?.includes("重新分析"),
      ),
    ).toBe(true);
  });

  it("labels a failed report as failed rather than complete", async () => {
    api.getComplexity.mockResolvedValue(failed());
    const host = mount();
    await advance(0);
    expect(host.textContent).toContain("分析失败");
    expect(host.textContent).toContain("分析超时");
    expect(host.textContent).not.toMatch(/已完成/);
  });

  it("labels an ineligible report as unanalysable", async () => {
    api.getComplexity.mockResolvedValue(ineligible());
    const host = mount();
    await advance(0);
    expect(host.textContent).toContain("无法分析");
    expect(host.textContent).toContain("模拟评测结果不参与复杂度分析");
  });
});
