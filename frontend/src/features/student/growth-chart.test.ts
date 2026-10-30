// @vitest-environment jsdom
/**
 * The growth chart plots counted work on a log-log view: a power law becomes a
 * straight line, so the empirical slope is visible instead of asserted. These
 * tests mount the component directly with a trace payload; no backend involved.
 */
import { createApp, nextTick } from "vue";
import { afterEach, describe, expect, it } from "vitest";
import GrowthChart from "./components/GrowthChart.vue";
import type {
  ComplexitySpace,
  ComplexityTime,
  ComplexityTrace,
  TracePoint,
} from "./types";

function time(overrides: Partial<ComplexityTime> = {}): ComplexityTime {
  return {
    class: "O(n log n)",
    confidence: "HIGH",
    source: "TRACE",
    method: "CLOSED_FORM",
    closed_form: "Θ(n log n)",
    recurrence: null,
    fit: {
      class: "O(n log n)",
      confidence: "HIGH",
      margin: 64.2,
      best: {
        class: "O(n log n)",
        r2: 0.9998,
        sse: 0.21,
        coefficient: 1.03,
        offset: 12,
      },
      candidates: [{ class: "O(n log n)", r2: 0.9998, sse: 0.21 }],
      notes: [],
    },
    notes: [],
    ...overrides,
  };
}

function space(): ComplexitySpace {
  return {
    class: "UNKNOWN",
    confidence: "LOW",
    source: "NONE",
    fit: null,
    depth_fit: null,
    notes: [],
  };
}

function point(
  n: number,
  work: number,
  extra: Partial<TracePoint> = {},
): TracePoint {
  return {
    n,
    verdict: "OK",
    detail: null,
    work,
    baseline_work: 0,
    line_events: work,
    jump_events: 0,
    library_work: 0,
    max_depth: 1,
    peak_bytes: null,
    ...extra,
  };
}

function trace(
  points: TracePoint[],
  overrides: Partial<ComplexityTrace> = {},
): ComplexityTrace {
  return {
    adapter: "python-monitoring-v1",
    work_unit: "line + jump events",
    input_family: "INT_ARRAY_ROWS",
    stop_reason: "OK",
    deterministic: true,
    repeat_delta: 0,
    notes: [],
    points,
    time: time(),
    space: space(),
    evidence: [],
    ...overrides,
  };
}

const rungs: TracePoint[] = [
  point(256, 4200, { baseline_work: 300, peak_bytes: 120000 }),
  point(1024, 20100, { baseline_work: 1200 }),
  point(4096, 96000, { baseline_work: 4800 }),
  point(16384, 452000, { baseline_work: 19200 }),
];

let cleanup: (() => void) | undefined;
afterEach(() => {
  cleanup?.();
  cleanup = undefined;
});

function mount(props: {
  trace: ComplexityTrace | null;
  time?: ComplexityTime | null;
}) {
  const host = document.createElement("div");
  document.body.append(host);
  const app = createApp(GrowthChart, props);
  app.mount(host);
  cleanup = () => {
    app.unmount();
    host.remove();
  };
  return host;
}

describe("GrowthChart", () => {
  it("draws one point per finished rung and a reference curve of the fitted class", async () => {
    const host = mount({ trace: trace(rungs), time: time() });
    await nextTick();
    expect(host.querySelectorAll("circle.point")).toHaveLength(4);
    expect(host.querySelector("path.curve")).not.toBeNull();
    expect(host.textContent).toContain("工作量随 n 增长");
    expect(host.textContent).toContain("参考曲线 O(n log n)");
  });

  it("plots the algorithm's own work, below the reader baseline", async () => {
    const host = mount({ trace: trace(rungs), time: time() });
    await nextTick();
    const points = [...host.querySelectorAll("circle.point")];
    // 4200 total - 300 reader = 3900 for the algorithm itself.
    expect(points[0]?.getAttribute("data-work")).toBe("3900");
    expect(points[3]?.getAttribute("data-work")).toBe("432800");
  });

  it("clamps work that never rises above the reader baseline", async () => {
    const host = mount({
      trace: trace([
        point(128, 400, { baseline_work: 400 }),
        point(512, 700, { baseline_work: 900 }),
      ]),
      time: time(),
    });
    await nextTick();
    const values = [...host.querySelectorAll("circle.point")].map((circle) =>
      circle.getAttribute("data-work"),
    );
    expect(values).toEqual(["1", "1"]);
  });

  it("draws only finished rungs", async () => {
    const host = mount({
      trace: trace([
        point(256, 4200),
        point(512, 0, { verdict: "TIME_LIMIT_EXCEEDED" }),
        point(1024, 20100),
        point(2048, Number.POSITIVE_INFINITY),
      ]),
      time: time(),
    });
    await nextTick();
    const points = [...host.querySelectorAll("circle.point")];
    expect(points).toHaveLength(2);
    for (const circle of points) {
      expect(Number.isFinite(Number(circle.getAttribute("cx")))).toBe(true);
      expect(Number.isFinite(Number(circle.getAttribute("cy")))).toBe(true);
    }
  });

  it("draws no reference curve when the report has no fit", async () => {
    const host = mount({
      trace: trace(rungs, { time: time({ fit: null }) }),
      time: time({ fit: null }),
    });
    await nextTick();
    expect(host.querySelectorAll("circle.point")).toHaveLength(4);
    expect(host.querySelector("path.curve")).toBeNull();
    expect(host.textContent).not.toContain("参考曲线");
  });

  it("says there are no rungs instead of drawing an empty axis", async () => {
    const empty = mount({ trace: trace([]), time: time() });
    await nextTick();
    expect(empty.querySelectorAll("circle.point")).toHaveLength(0);
    expect(empty.querySelector("svg")).toBeNull();
    expect(empty.textContent).toContain("暂无可用档位");
    cleanup?.();
    cleanup = undefined;

    const missing = mount({ trace: null, time: null });
    await nextTick();
    expect(missing.textContent).toContain("暂无可用档位");
  });

  it("never emits a coordinate that is not a number", async () => {
    const host = mount({
      trace: trace([
        point(256, 4200),
        point(Number.NaN, 20000),
        point(1024, 20100),
      ]),
      time: time(),
    });
    await nextTick();
    const markup = host.innerHTML;
    expect(markup).not.toContain("NaN");
    expect(markup).not.toContain("Infinity");
  });

  it("reads the fit class from the trace when no time prop is given", async () => {
    const host = mount({ trace: trace(rungs) });
    await nextTick();
    expect(host.querySelectorAll("circle.point")).toHaveLength(4);
    expect(host.querySelector("path.curve")).not.toBeNull();
    expect(host.textContent).toContain("参考曲线 O(n log n)");
  });
});
