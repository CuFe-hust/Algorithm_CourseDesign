// @vitest-environment jsdom
import { createApp, defineComponent, h, nextTick } from "vue";
import { afterEach, it, expect, vi } from "vitest";
const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  post: vi.fn(),
  confirm: vi.fn(),
  path: "/student/courses/7/learning",
}));
vi.mock("vue-router", () => ({
  useRoute: () => ({ path: mocks.path, params: { courseId: "7" } }),
}));
vi.mock("../../shared/session", () => ({ session: { courseId: "7" } }));
vi.mock("../../shared/confirm", () => ({ confirmAction: mocks.confirm }));
vi.mock("../../shared/api", async (original) => ({
  ...(await original<typeof import("../../shared/api")>()),
  request: mocks.request,
  post: mocks.post,
}));
import Results from "./Results.vue";
let cleanup: (() => void) | undefined;
afterEach(() => {
  cleanup?.();
  vi.resetAllMocks();
  mocks.path = "/student/courses/7/learning";
});
const report = {
  id: "9223372036854775804",
  assignment_id: "9",
  assignment_title: "合成作业",
  results_snapshot_version: "question-results-test",
  created_at: "2026-10-30T00:00:00Z",
  role: "STUDENT",
  known_count: 1,
  missing_count: 1,
  total: 2,
  event_counts: { SUBMITTED: 3 },
  per_item: [
    {
      id: "1",
      title: "合成证明题",
      known: 1,
      missing: 0,
      normalized_mean: "0",
    },
    { id: "2", title: "尚未互评", known: 0, missing: 1, normalized_mean: null },
  ],
  rows: [
    {
      assignment_item_id: "1",
      title: "合成证明题",
      max_score: "20",
      item_score: "0.00",
      normalized_score: "0",
      submission_id: "9223372036854775805",
      source: { kind: "REVIEW_ANALYSIS", version: 2 },
      reason: null,
    },
    {
      assignment_item_id: "2",
      title: "尚未互评",
      max_score: "20",
      item_score: null,
      normalized_score: null,
      submission_id: null,
      source: null,
      reason: "REVIEW_PENDING",
    },
  ],
  model_status: { ability: "NOT_IMPLEMENTED" },
};
async function settle() {
  await new Promise((r) => setTimeout(r, 0));
  await nextTick();
}
async function mount() {
  mocks.request.mockImplementation((path: string) =>
    Promise.resolve(
      path.endsWith("/assignments")
        ? {
            items: [
              { id: "9", title: "合成作业", submission_status: "CLOSED" },
            ],
          }
        : structuredClone(report),
    ),
  );
  const host = document.createElement("div");
  document.body.append(host);
  const app = createApp(Results);
  app.component(
    "RouterLink",
    defineComponent({
      props: ["to"],
      setup: (props, ctx) => () =>
        h("a", { href: props.to }, ctx.slots.default?.()),
    }),
  );
  app.mount(host);
  cleanup = () => {
    app.unmount();
    host.remove();
  };
  await settle();
  return host;
}
it("keeps a real zero distinct from missing and never invents learning-model scores", async () => {
  const host = await mount();
  expect(host.textContent).toContain("0.00");
  expect(host.textContent).toContain("等待互评处理");
  expect(host.textContent).toContain("暂无结果");
  expect(host.textContent).toContain("模型尚未全部接入");
  expect(host.querySelector("a")?.getAttribute("href")).toBe(
    "/student/courses/7/submissions/9223372036854775805",
  );
  expect(
    [...host.querySelectorAll("button")].some((b) =>
      b.textContent?.includes("固定当前"),
    ),
  ).toBe(false);
});
it("reuses its command ID after a lost snapshot response and requires teacher confirmation", async () => {
  mocks.path = "/teacher/results";
  mocks.confirm.mockResolvedValue(true);
  const host = await mount();
  const select = host.querySelector("select")!;
  select.value = "9";
  select.dispatchEvent(new Event("change", { bubbles: true }));
  await settle();
  const reason = host.querySelector("input")!;
  reason.value = "本次合成复核后固定结果";
  reason.dispatchEvent(new Event("input", { bubbles: true }));
  await settle();
  mocks.post.mockRejectedValue(Error("network lost"));
  const button = [...host.querySelectorAll("button")].find((b) =>
    b.textContent?.includes("固定当前逐题结果"),
  )!;
  button.click();
  await settle();
  button.click();
  await settle();
  expect(mocks.confirm).toHaveBeenCalledTimes(2);
  expect(mocks.post.mock.calls[0][1]).toEqual(mocks.post.mock.calls[1][1]);
  expect(mocks.post.mock.calls[0][1]).toMatchObject({
    assignment_id: "9",
    reason: "本次合成复核后固定结果",
    request_id: expect.any(String),
  });
});
