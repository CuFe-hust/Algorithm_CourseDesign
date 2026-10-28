// @vitest-environment jsdom
/**
 * Behaviour that review proved untested: bounded polling, teardown, and the
 * terminal-state badge. These mount the real component with fake timers and a
 * stubbed API module.
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

function finished(status: string, timeClass = "O(n)") {
  return {
    submission_id: "11",
    status,
    eligible: true,
    reason: null,
    report: {
      status,
      language: "python3",
      implementation_name: "complexity_probe",
      implementation_version: "1",
      time:
        status === "SUCCEEDED"
          ? {
              class: timeClass,
              confidence: "HIGH",
              source: "DYNAMIC",
              static_class: timeClass,
              measured_class: timeClass,
              agreement: true,
            }
          : {},
      space:
        status === "SUCCEEDED"
          ? {
              class: "O(1)",
              confidence: "HIGH",
              source: "STATIC",
              static_class: "O(1)",
            }
          : {},
      static: { evidence: [] },
      dynamic: { rungs: [], curve: [] },
      limitations: [],
      error: status === "INELIGIBLE" ? "模拟结果不参与复杂度分析" : null,
      requested_at: null,
      finished_at: null,
    },
  };
}

async function advance(ms: number) {
  await vi.advanceTimersByTimeAsync(ms);
  await nextTick();
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

describe("ComplexityPanel terminal states", () => {
  it("labels a failed report as failed rather than complete", async () => {
    api.getComplexity.mockResolvedValue({
      ...finished("FAILED"),
      report: { ...finished("FAILED").report, error: "LEASE_EXPIRED" },
    });
    const host = mount();
    await advance(0);
    expect(host.textContent).toContain("分析失败");
    expect(host.textContent).not.toMatch(/已完成/);
  });

  it("labels an ineligible report as unanalysable", async () => {
    api.getComplexity.mockResolvedValue(finished("INELIGIBLE"));
    const host = mount();
    await advance(0);
    expect(host.textContent).toContain("无法分析");
  });

  it("shows the merged classes when the report succeeded", async () => {
    api.getComplexity.mockResolvedValue(finished("SUCCEEDED", "O(n log n)"));
    const host = mount();
    await advance(0);
    expect(host.textContent).toContain("O(n log n)");
    expect(host.textContent).toContain("已完成");
    expect(host.textContent).not.toContain("undefined");
  });
});
