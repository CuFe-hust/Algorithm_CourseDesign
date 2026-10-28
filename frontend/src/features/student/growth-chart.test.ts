// @vitest-environment jsdom
import { createApp, nextTick } from "vue";
import { afterEach, describe, expect, it } from "vitest";
import GrowthChart from "./components/GrowthChart.vue";
import type { DynamicAnalysis } from "./types";

function dynamic(overrides: Partial<DynamicAnalysis> = {}): DynamicAnalysis {
  return {
    measured_class: "O(n log n)",
    io_class: "O(n)",
    informative: true,
    r2: 0.995,
    exponent: 1.12,
    confidence: "HIGH",
    floor_ms: 12,
    fit: null,
    reference_fit: null,
    accounting: [],
    rungs: [
      { n: 256, wall_ms: 14, reference_ms: 12, io_ratio: 1.17, verdict: "OK" },
      { n: 1024, wall_ms: 22, reference_ms: 13, io_ratio: 1.69, verdict: "OK" },
      { n: 4096, wall_ms: 61, reference_ms: 16, io_ratio: 3.8, verdict: "OK" },
      { n: 16384, wall_ms: 240, reference_ms: 24, io_ratio: 10, verdict: "OK" },
    ],
    curve: [
      { n: 256, time_ms: 13 },
      { n: 4096, time_ms: 58 },
      { n: 16384, time_ms: 230 },
    ],
    ...overrides,
  };
}

let cleanup: (() => void) | undefined;
afterEach(() => {
  cleanup?.();
  cleanup = undefined;
});

function mount(props: { dynamic: DynamicAnalysis | null }) {
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
  it("draws one point per completed rung and a fitted curve", async () => {
    const host = mount({ dynamic: dynamic() });
    await nextTick();
    expect(host.querySelectorAll("circle.point")).toHaveLength(4);
    expect(host.querySelector("path.curve")).not.toBeNull();
    expect(host.textContent).toContain("输入规模");
  });

  it("marks rungs that never beat pure input parsing", async () => {
    const host = mount({ dynamic: dynamic() });
    await nextTick();
    // The two small rungs have io_ratio below 2 and must render dimmer.
    expect(host.querySelectorAll("circle.point.mutedPoint")).toHaveLength(2);
    expect(host.textContent).toContain("与纯读取输入同阶");
  });

  it("explains an empty measurement instead of drawing an empty axis", async () => {
    const host = mount({ dynamic: dynamic({ rungs: [], curve: [] }) });
    await nextTick();
    expect(host.querySelectorAll("circle.point")).toHaveLength(0);
    expect(host.textContent).toContain("没有可用的测量点");
  });

  it("only draws completed, finite measurements", async () => {
    const host = mount({
      dynamic: dynamic({
        rungs: [
          { n: 256, wall_ms: 14, verdict: "OK" },
          { n: 512, wall_ms: 0, verdict: "OK" },
          { n: 1024, wall_ms: 22, verdict: "TIME_LIMIT_EXCEEDED" },
          { n: 2048, wall_ms: 30, verdict: "OK" },
        ],
        curve: [],
      } as unknown as Partial<DynamicAnalysis>),
    });
    await nextTick();
    const points = [...host.querySelectorAll("circle.point")];
    expect(points).toHaveLength(2);
    for (const point of points) {
      expect(Number.isFinite(Number(point.getAttribute("cx")))).toBe(true);
      expect(Number.isFinite(Number(point.getAttribute("cy")))).toBe(true);
    }
  });

  it("never emits a coordinate that is not a number", async () => {
    const host = mount({
      dynamic: dynamic({
        rungs: [
          { n: 256, wall_ms: 14, verdict: "OK" },
          { n: Number.NaN, wall_ms: 20, verdict: "OK" },
          { n: 1024, wall_ms: Number.POSITIVE_INFINITY, verdict: "OK" },
        ],
        curve: [
          { n: 256, time_ms: 13 },
          { n: 1024, time_ms: 30 },
        ],
      } as unknown as Partial<DynamicAnalysis>),
    });
    await nextTick();
    const markup = host.innerHTML;
    expect(markup).not.toContain("NaN");
    expect(markup).not.toContain("Infinity");
  });

  it("renders without a report", async () => {
    const host = mount({ dynamic: null });
    await nextTick();
    expect(host.textContent).toContain("没有可用的测量点");
  });
});
