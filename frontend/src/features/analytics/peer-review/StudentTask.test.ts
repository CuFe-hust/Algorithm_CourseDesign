// @vitest-environment jsdom
import { createApp, defineComponent, h, nextTick } from "vue";
import { afterEach, it, expect, vi } from "vitest";
const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  post: vi.fn(),
  confirm: vi.fn(),
  leave: undefined as undefined | (() => Promise<boolean>),
}));
vi.mock("vue-router", () => ({
  useRoute: () => ({
    params: { taskId: "9223372036854775804", courseId: "7" },
  }),
  onBeforeRouteLeave: (fn: () => Promise<boolean>) => {
    mocks.leave = fn;
  },
}));
vi.mock("../../../shared/api", async (original) => ({
  ...(await original<typeof import("../../../shared/api")>()),
  request: mocks.request,
  post: mocks.post,
}));
vi.mock("../../../shared/confirm", () => ({ confirmAction: mocks.confirm }));
import StudentTask from "./StudentTask.vue";
let cleanup: (() => void) | undefined;
afterEach(() => {
  cleanup?.();
  vi.resetAllMocks();
});
const fixture = {
  id: "9223372036854775804",
  round_no: 1,
  review_deadline: "2030-01-01T00:00:00Z",
  can_submit: true,
  question: { title: "合成证明题", statement_md: "证明正确性" },
  answer_content: "合成作品",
  rubric: [
    {
      id: "9223372036854775805",
      name: "论证",
      description: "逻辑完整性",
      max_score: "10",
    },
  ],
  rubric_max: "10",
  evaluation: null,
};
async function settle() {
  await new Promise((r) => setTimeout(r, 0));
  await nextTick();
}
async function mount() {
  mocks.request.mockResolvedValue(structuredClone(fixture));
  const host = document.createElement("div");
  document.body.append(host);
  const app = createApp(StudentTask);
  app.component(
    "RouterLink",
    defineComponent({ setup: (_, ctx) => () => h("a", ctx.slots.default?.()) }),
  );
  app.mount(host);
  cleanup = () => {
    app.unmount();
    host.remove();
  };
  await settle();
  return host;
}
function fill(host: HTMLElement) {
  const input = host.querySelector("input")!;
  input.value = "8.25";
  input.dispatchEvent(new Event("input", { bubbles: true }));
  const comment = host.querySelector("textarea")!;
  comment.value = "边界条件和归纳步骤完整";
  comment.dispatchEvent(new Event("input", { bubbles: true }));
}
it("requires every score and sends exact string IDs without client time or author identity", async () => {
  const host = await mount();
  host
    .querySelector("form")!
    .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  await settle();
  expect(mocks.post).not.toHaveBeenCalled();
  fill(host);
  await settle();
  mocks.confirm.mockResolvedValue(true);
  mocks.post.mockResolvedValue({
    ...fixture,
    evaluation: {
      id: "1",
      scores: [{ rubric_item_id: fixture.rubric[0].id, score: "8.25" }],
      comment: "边界条件和归纳步骤完整",
      total_score: "8.25",
      elapsed_seconds: "20",
    },
  });
  host
    .querySelector("form")!
    .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  await settle();
  expect(mocks.post).toHaveBeenCalledWith(
    `/peer-review/tasks/${fixture.id}/evaluation`,
    {
      client_request_id: expect.any(String),
      scores: [{ rubric_item_id: fixture.rubric[0].id, score: "8.25" }],
      comment: "边界条件和归纳步骤完整",
    },
  );
  expect(host.textContent).toContain("原始总分 8.25");
  expect(await mocks.leave!()).toBe(true);
});
it("retains input and the same request ID after a lost response; unsaved navigation requires confirmation", async () => {
  const host = await mount();
  fill(host);
  await settle();
  mocks.confirm.mockResolvedValue(true);
  mocks.post.mockRejectedValue(Error("网络中断"));
  const submit = () =>
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  submit();
  await settle();
  const first = mocks.post.mock.calls[0][1];
  submit();
  await settle();
  expect(mocks.post.mock.calls[1][1]).toEqual(first);
  mocks.confirm.mockResolvedValue(false);
  expect(await mocks.leave!()).toBe(false);
  expect(host.querySelector("textarea")!.value).toContain("归纳步骤");
});

it("accepts a real numeric zero instead of treating it as an empty score", async () => {
  const host = await mount();
  fill(host);
  const input = host.querySelector("input")!;
  input.value = "0";
  input.dispatchEvent(new Event("input", { bubbles: true }));
  await settle();
  mocks.confirm.mockResolvedValue(true);
  mocks.post.mockRejectedValue(Error("synthetic retry"));
  host
    .querySelector("form")!
    .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  await settle();
  expect(mocks.post.mock.calls[0][1].scores[0].score).toBe("0");
});
