// @vitest-environment jsdom
import { createApp, nextTick } from "vue";
import { afterEach, describe, expect, it } from "vitest";
import { formatDateTime, formatTime, remainingLabel } from "./format";
import DraftStatus from "./components/DraftStatus.vue";
import JudgeFeedback from "./components/JudgeFeedback.vue";
import ProblemStatement from "./components/ProblemStatement.vue";
import type { ItemDetail } from "./types";

let cleanup: (() => void) | undefined;
afterEach(() => {
  cleanup?.();
  cleanup = undefined;
});

function mount(
  component: Parameters<typeof createApp>[0],
  props: Record<string, unknown>,
) {
  const host = document.createElement("div");
  document.body.append(host);
  const app = createApp(component, props);
  app.mount(host);
  cleanup = () => {
    app.unmount();
    host.remove();
  };
  return host;
}

describe("format", () => {
  it("renders dates as zero-padded local timestamps, not US locale strings", () => {
    expect(formatDateTime(new Date(2026, 9, 28, 15, 4))).toBe(
      "2026-10-28 15:04",
    );
    expect(formatDateTime(new Date(2026, 0, 2, 3, 5))).toBe("2026-01-02 03:05");
    expect(formatTime(new Date(2026, 9, 28, 8, 3))).toBe("08:03");
    expect(formatDateTime("not a date")).toBe("—");
  });

  it("describes the remaining time until the deadline in student wording", () => {
    const now = new Date(2026, 9, 28, 12, 0).getTime();
    expect(remainingLabel("2026-10-20T00:00:00Z", now)).toBe("已截止");
    expect(remainingLabel(new Date(now + 20 * 60_000).toISOString(), now)).toBe(
      "即将截止",
    );
    expect(
      remainingLabel(new Date(now + 5 * 3_600_000).toISOString(), now),
    ).toBe("5 小时后截止");
    expect(
      remainingLabel(new Date(now + 96 * 3_600_000).toISOString(), now),
    ).toBe("4 天后截止");
  });
});

describe("JudgeFeedback empty state", () => {
  it("shows a waiting badge instead of the cryptic 未标注 when no result exists", async () => {
    const host = mount(JudgeFeedback, { result: null, jobStatus: "PENDING" });
    await nextTick();
    expect(host.textContent).toContain("等待评测");
    expect(host.textContent).not.toContain("未标注");
    const badge = host.querySelector(".badge");
    expect(badge?.className).toContain("amber");
  });
});

describe("DraftStatus wording", () => {
  it("does not claim the student has not started when a draft was restored", async () => {
    const host = mount(DraftStatus, { status: "idle" });
    await nextTick();
    expect(host.textContent).toContain("没有未保存的修改");
    expect(host.textContent).not.toContain("尚未开始作答");
  });

  it("formats the last-saved clock as HH:MM", async () => {
    const host = mount(DraftStatus, {
      status: "saved",
      lastSavedAt: new Date(2026, 9, 28, 9, 5).getTime(),
    });
    await nextTick();
    expect(host.textContent).toContain("草稿已保存于本机 09:05");
  });
});

describe("ProblemStatement metadata", () => {
  it("labels the problem version explicitly to avoid confusion with submission versions", async () => {
    const item = {
      id: "1",
      assignment_id: "1",
      problem_code: "CODE-P01",
      question_type: "PROGRAMMING",
      title: "活动安排问题",
      statement_md: "题面",
      answer_requirements_md: null,
      input_spec_md: null,
      output_spec_md: null,
      data_constraints_md: null,
      public_examples_md: null,
      difficulty_level: 2,
      version_no: 1,
      problem_version_id: "pv-1",
      server_time: "2026-10-28T00:00:00Z",
      max_score: "100.00",
      submission_deadline: "2026-10-31T20:00:00Z",
      review_deadline: null,
      submission_open: true,
      allowed_languages: ["python3"],
      cpu_limit_ms: null,
      execution_budget: null,
      memory_limit_kib: null,
      public_test_cases: [],
      rubric: [],
    } as unknown as ItemDetail;
    const host = mount(ProblemStatement, { item });
    await nextTick();
    expect(host.textContent).toContain("题面版本");
    expect(host.textContent).not.toMatch(/(^|[^面])版本/);
  });
});
