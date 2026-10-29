// @vitest-environment jsdom
import { createApp, nextTick, reactive } from "vue";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { AbilityEstimate, AbilityReport } from "./ability";

const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  replace: vi.fn(),
  route: { params: { courseId: "91" }, query: {} as Record<string, string> },
}));
vi.mock("vue-router", () => ({
  useRoute: () => mocks.route,
  useRouter: () => ({ replace: mocks.replace }),
}));
vi.mock("../../shared/api", async (original) => ({
  ...(await original<typeof import("../../shared/api")>()),
  request: mocks.request,
}));
import Ability from "./Ability.vue";

let cleanup: (() => void) | undefined;
beforeEach(() => {
  mocks.route = reactive({
    params: { courseId: "91" },
    query: {} as Record<string, string>,
  });
  mocks.replace.mockImplementation(
    ({ query }: { query: Record<string, string> }) => {
      mocks.route.query = query;
    },
  );
});
afterEach(() => {
  cleanup?.();
  vi.clearAllMocks();
});
function chapter(
  index: number,
  overrides: Partial<AbilityEstimate> = {},
): AbilityEstimate {
  return {
    object_key: "student:1",
    dimension: `CH0${index}`,
    dimension_label: `章节${index}`,
    dimension_order: index,
    value: "0.6",
    status: "OK",
    n_items: 1,
    assigned_items: 3,
    scored_items: 1,
    W_sum: "1",
    n_eff: "1",
    coverage_items: "0.3333",
    coverage_weight: "0.5",
    missing: { pending: 1, not_submitted: 1, invalid: 0 },
    observed_min: "0.6",
    observed_max: "0.6",
    diagnostic_flags: [],
    by_type: { PROGRAMMING: { value: "0", n_items: 1, W_sum: "1" } },
    ...overrides,
  };
}
function report(estimates: AbilityEstimate[] = []): AbilityReport {
  return {
    status: estimates.length ? "OK" : "NO_REAL_ANALYSIS",
    course_id: "91",
    source_kind: "REAL",
    is_mock: false,
    ...(estimates.length ? { batch_id: "analysis-1" } : {}),
    estimates,
  };
}
function difficultyReport(): AbilityReport {
  return {
    ...report([
      chapter(1, { value: "0.7", baseline_value: "0.5", theta: "0.8473" }),
      chapter(2, {
        value: "0.4",
        baseline_value: "0.6",
        theta: "-0.4055",
        status: "LOW_EVIDENCE",
      }),
      chapter(3, {
        value: null,
        baseline_value: null,
        theta: null,
        status: "NO_EVIDENCE",
      }),
      chapter(4, { status: "NOT_COVERED" }),
    ]),
    method: "DIFFICULTY_FRACTIONAL",
    model_parameters: {
      learner_l2: "0.2",
      item_l2: "2",
      difficulty_scale: "0.5",
      max_iterations: 100,
      tolerance: "0.000001",
    },
    model_diagnostics: {
      loss: "1.234",
      iterations: 12,
      converged: true,
      score_semantics: "REFERENCE_EXPECTED_SCORE",
      difficulty_source: "TEACHER_PRIOR_WITH_COHORT_CALIBRATION",
    },
  };
}
function mount() {
  const host = document.createElement("div");
  document.body.append(host);
  const app = createApp(Ability);
  app.mount(host);
  cleanup = () => {
    app.unmount();
    host.remove();
  };
  return host;
}
async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await nextTick();
}
it("reads formal analysis first and switches to server demo only by explicit action", async () => {
  mocks.request.mockResolvedValue(report());
  const host = mount();
  await settle();
  expect(mocks.request).toHaveBeenCalledWith("/courses/91/my-ability");
  expect(host.textContent).toContain("正式章节分析尚未生成");
  mocks.request.mockResolvedValue({
    ...report([chapter(1)]),
    is_mock: true,
    source_kind: "SYNTHETIC",
  });
  [...host.querySelectorAll("button")]
    .find((button) => button.textContent?.trim() === "切换合成演示")!
    .click();
  await settle();
  expect(mocks.request).toHaveBeenLastCalledWith("/courses/91/my-ability/demo");
  expect(host.textContent).toContain("不代表你的真实学习表现");
  expect(host.querySelector(".ability-bars")).not.toBeNull();
});
it("renders missing evidence and real zero distinctly and hides uncovered rows", async () => {
  mocks.request.mockResolvedValue(
    report([
      chapter(4, { status: "NOT_COVERED" }),
      chapter(3),
      chapter(2, { status: "NO_EVIDENCE", value: null }),
      chapter(1, { value: "0" }),
    ]),
  );
  const host = mount();
  await settle();
  const rows = [...host.querySelectorAll("tbody tr")];
  expect(rows).toHaveLength(3);
  expect(rows[0]?.textContent).toContain("0.0%");
  expect(rows[1]?.querySelector(".ability-value")?.textContent).toBe("—");
  expect(rows[1]?.textContent).toContain("暂无有效证据");
  expect(host.textContent).not.toContain("章节4");
  expect(host.querySelectorAll(".ability-point")).toHaveLength(2);
  expect(host.querySelectorAll(".ability-edge")).toHaveLength(1);
  expect(host.querySelector(".ability-axis-label")?.textContent).toContain(
    "章节1",
  );
  expect(
    host.querySelector(".ability-axis-label title")?.textContent,
  ).toContain("CH01");
  expect(rows[0]?.textContent).toContain("待评分 1");
});
it("honors demo links and explains how an absent persisted demo is created", async () => {
  mocks.route.query.demo = "1";
  mocks.request.mockResolvedValue({
    ...report(),
    status: "NO_DEMO_ANALYSIS",
    is_mock: true,
  });
  const host = mount();
  await settle();
  expect(mocks.request).toHaveBeenCalledWith("/courses/91/my-ability/demo");
  expect(host.textContent).toContain("请由教师或管理员生成");
  expect(host.textContent).toContain("不代表你的真实学习表现");
});
it("discards late formal responses after switching to demo", async () => {
  let resolveFormal!: (value: AbilityReport) => void;
  mocks.request.mockImplementation((path: string) =>
    path.endsWith("/demo")
      ? Promise.resolve({ ...report([chapter(2)]), is_mock: true })
      : new Promise<AbilityReport>((resolve) => {
          resolveFormal = resolve;
        }),
  );
  const host = mount();
  await settle();
  mocks.route.query.demo = "1";
  await settle();
  resolveFormal(report([chapter(1)]));
  await settle();
  expect(host.textContent).toContain("章节2");
  expect(host.textContent).not.toContain("章节1");
});
it.each([
  ["ANALYSIS_PENDING", "章节分析正在处理中"],
  ["ANALYSIS_FAILED", "本次章节分析未完成"],
  ["NOT_IN_SCOPE", "本批次未包含你的分析结果"],
] as const)(
  "shows %s truthfully even when the empty response includes a batch id",
  async (status, title) => {
    mocks.request.mockResolvedValue({
      ...report(),
      batch_id: "analysis-unfinished",
      status,
    });
    const host = mount();
    await settle();
    expect(host.textContent).toContain(title);
    expect(host.querySelector(".ability-overview")).toBeNull();
    expect(host.querySelector(".ability-evidence")).toBeNull();
  },
);
it("shows formal input unavailability and its reason without claiming the batch is pending", async () => {
  mocks.request.mockResolvedValue({
    ...report(),
    batch_id: "analysis-waiting-input",
    reason: "正式评分结果尚未准备好",
  });
  const host = mount();
  await settle();
  expect(host.textContent).toContain("正式章节分析尚未生成");
  expect(host.textContent).toContain("正式评分结果尚未准备好");
  expect(host.textContent).not.toContain("正在处理中");
  expect(host.querySelector(".ability-overview")).toBeNull();
});
it("loads the difficulty demo from its own endpoint and distinguishes model values from observed means", async () => {
  mocks.route.query = { demo: "1", model: "d1" };
  mocks.request.mockResolvedValue({
    ...difficultyReport(),
    is_mock: true,
    source_kind: "SYNTHETIC",
  });
  const host = mount();
  await settle();
  expect(mocks.request).toHaveBeenCalledWith(
    "/courses/91/my-ability/difficulty/demo",
  );
  expect(host.textContent).toContain("不代表你的真实学习表现");
  expect(host.textContent).toContain("模型参考表现");
  expect(host.textContent).toContain("已评分题目均值");
  expect(host.textContent).toContain("编程题原始均值");
  expect(host.textContent).toContain("教师 1–5 级难度");
  expect(host.textContent).toContain("参考难度 0");
  const rows = [...host.querySelectorAll(".ability-evidence tbody tr")];
  expect(rows).toHaveLength(3);
  expect(rows[0]?.querySelector(".ability-value")?.textContent).toBe("70.0%");
  expect(rows[0]?.querySelector(".ability-baseline")?.textContent).toBe(
    "50.0%",
  );
  expect(rows[0]?.querySelector(".ability-difference")?.textContent).toBe(
    "+20.0 个百分点",
  );
  expect(rows[1]?.querySelector(".ability-difference")?.textContent).toBe(
    "−20.0 个百分点",
  );
  expect(rows[1]?.textContent).toContain("证据较少");
  expect(rows[2]?.querySelector(".ability-value")?.textContent).toBe("—");
  expect(rows[2]?.querySelector(".ability-baseline")?.textContent).toBe("—");
  expect(rows[2]?.querySelector(".ability-difference")?.textContent).toBe("—");
  expect(host.textContent).not.toContain("章节4");
  expect(host.querySelectorAll(".ability-baseline-point")).toHaveLength(2);
  expect(host.querySelector(".ability-process")).toBeNull();
});
it("switches the model through the query while preserving formal/demo selection", async () => {
  mocks.route.query = { demo: "1", extra: "preserved" };
  mocks.request.mockResolvedValue(difficultyReport());
  const host = mount();
  await settle();
  [...host.querySelectorAll("button")]
    .find((button) => button.textContent?.trim() === "难度感知模型")!
    .click();
  await settle();
  expect(mocks.route.query).toMatchObject({
    demo: "1",
    model: "d1",
    extra: "preserved",
  });
  expect(mocks.request).toHaveBeenLastCalledWith(
    "/courses/91/my-ability/difficulty/demo",
  );
  [...host.querySelectorAll("button")]
    .find((button) => button.textContent?.trim() === "原始表现 B0")!
    .click();
  await settle();
  expect(mocks.request).toHaveBeenLastCalledWith("/courses/91/my-ability/demo");
  expect(mocks.route.query.demo).toBe("1");
});
it("loads formal D1 and discards its late response after switching back to B0", async () => {
  mocks.route.query.model = "d1";
  let resolveDifficulty!: (value: AbilityReport) => void;
  mocks.request.mockImplementation((path: string) =>
    path.endsWith("/difficulty")
      ? new Promise<AbilityReport>((resolve) => {
          resolveDifficulty = resolve;
        })
      : Promise.resolve(report([chapter(7)])),
  );
  const host = mount();
  await settle();
  expect(mocks.request).toHaveBeenCalledWith(
    "/courses/91/my-ability/difficulty",
  );
  mocks.route.query.model = "b0";
  await settle();
  resolveDifficulty(difficultyReport());
  await settle();
  expect(host.textContent).toContain("章节7");
  expect(host.textContent).not.toContain("章节1");
  expect(host.querySelector(".ability-model-explanation")).toBeNull();
});
it("offers a difficulty demo link without changing the B0 default", async () => {
  mocks.request.mockResolvedValue(report());
  const host = mount();
  await settle();
  [...host.querySelectorAll("button")]
    .find((button) => button.textContent?.trim() === "查看难度模型演示")!
    .click();
  await settle();
  expect(mocks.route.query).toMatchObject({ demo: "1", model: "d1" });
  expect(mocks.request).toHaveBeenLastCalledWith(
    "/courses/91/my-ability/difficulty/demo",
  );
});
it("shows available submission observations without treating attempts as a capability penalty", async () => {
  mocks.route.query.model = "d1";
  mocks.request.mockResolvedValue({
    ...difficultyReport(),
    process_diagnostics: {
      available: true,
      items: [
        {
          item_key: "programming:42",
          submission_count: 4,
          first_score: "0.2",
          latest_score: "0.8",
          best_score: "1",
          first_accepted_attempt: 3,
          repeated_failure_pairs: 1,
        },
        {
          item_key: "programming:43",
          submission_count: 1,
          first_score: "0",
          latest_score: "0",
          best_score: "0",
          first_accepted_attempt: null,
          repeated_failure_pairs: 0,
        },
      ],
    },
  });
  const host = mount();
  await settle();
  const process = host.querySelector(".ability-process");
  expect(process?.textContent).toContain("作答过程观察");
  expect(process?.textContent).toContain("不作为能力扣分");
  const rows = [...process!.querySelectorAll("tbody tr")];
  expect(rows[0]?.textContent).toContain("programming:42");
  expect(rows[0]?.textContent).toContain("20.0%");
  expect(rows[0]?.textContent).toContain("80.0%");
  expect(rows[0]?.textContent).toContain("100.0%");
  expect(rows[0]?.textContent).toContain("第 3 次");
  expect(rows[1]?.textContent).toContain("未观察到");
  expect(rows[1]?.textContent).toContain("0.0%");
});
it("hides process diagnostics when no reliable submission history is available", async () => {
  mocks.route.query.model = "d1";
  mocks.request.mockResolvedValue({
    ...difficultyReport(),
    process_diagnostics: { available: false, items: [] },
  });
  const host = mount();
  await settle();
  expect(host.querySelector(".ability-process")).toBeNull();
});
it("marks an unconverged difficulty result as provisional beside the displayed scores", async () => {
  mocks.route.query.model = "d1";
  const data = difficultyReport();
  data.model_diagnostics!.converged = false;
  mocks.request.mockResolvedValue(data);
  const host = mount();
  await settle();
  expect(host.querySelector(".ability-model-warning")?.textContent).toContain(
    "模型优化尚未收敛",
  );
  expect(host.querySelector(".ability-model-warning")?.textContent).toContain(
    "暂定结果",
  );
});
it("describes fixed teacher priors when item calibration is disabled", async () => {
  mocks.route.query.model = "d1";
  const data = difficultyReport();
  data.model_parameters!.calibrate_items = false;
  data.model_diagnostics!.difficulty_source = "FIXED_TEACHER_PRIOR";
  mocks.request.mockResolvedValue(data);
  const host = mount();
  await settle();
  const explanation = host.querySelector(".ability-model-explanation");
  expect(explanation?.textContent).toContain("题目难度固定在教师先验");
  expect(explanation?.textContent).not.toContain("全体评分证据上校准题目难度");
  expect(explanation?.textContent).toContain("参考难度 0");
});
