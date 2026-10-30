// @vitest-environment jsdom
import { createApp, nextTick } from "vue";
import { afterEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  post: vi.fn(),
  confirm: vi.fn(),
}));
vi.mock("../../shared/api", async (original) => ({
  ...(await original<typeof import("../../shared/api")>()),
  request: mocks.request,
  post: mocks.post,
}));
vi.mock("../../shared/confirm", () => ({ confirmAction: mocks.confirm }));
vi.mock("../../shared/session", () => ({ session: { courseId: "7" } }));
import AbilityGeneration from "./AbilityGeneration.vue";
let cleanup: (() => void) | undefined;
afterEach(() => {
  cleanup?.();
  vi.resetAllMocks();
});
async function settle() {
  await new Promise((r) => setTimeout(r, 0));
  await nextTick();
}
async function mount() {
  mocks.request.mockResolvedValue({
    models: [
      { model: "b0", id: null, status: "NOT_GENERATED" },
      {
        model: "d1",
        id: "19",
        status: "SUCCEEDED",
        business_status: "INSUFFICIENT_DATA",
      },
    ],
  });
  const host = document.createElement("div");
  document.body.append(host);
  const app = createApp(AbilityGeneration);
  app.mount(host);
  cleanup = () => {
    app.unmount();
    host.remove();
  };
  await settle();
  return host;
}
it("creates a course source and both formal models with the same frozen source", async () => {
  const host = await mount();
  expect(host.textContent).toContain("有效证据不足");
  mocks.confirm.mockResolvedValue(true);
  mocks.post.mockResolvedValue({
    id: "9223372036854775804",
    source_count: 2,
    known_count: 12,
    total: 24,
  });
  const button = host.querySelector("button.primary") as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  const input = host.querySelector("input")!;
  input.value = "互评已复核";
  input.dispatchEvent(new Event("input", { bubbles: true }));
  await settle();
  button.click();
  await settle();
  expect(mocks.post.mock.calls.map((args) => args[0])).toEqual([
    "/analysis/courses/7/course-results",
    "/analysis/courses/7/student-ability/b0-batches",
    "/analysis/courses/7/student-ability/difficulty-batches",
  ]);
  for (const call of mocks.post.mock.calls.slice(1))
    expect(call[1]).toMatchObject({
      mode: "REAL_INPUT",
      source_batch_id: "9223372036854775804",
    });
  expect(host.textContent).toContain("12 / 24");
  expect(mocks.confirm).toHaveBeenCalledOnce();
});
it("reuses all command IDs when the D1 response is lost", async () => {
  const host = await mount();
  mocks.confirm.mockResolvedValue(true);
  mocks.post.mockImplementation((path: string) =>
    path.endsWith("difficulty-batches")
      ? Promise.reject(Error("network lost"))
      : Promise.resolve({ id: "23" }),
  );
  const input = host.querySelector("input")!;
  input.value = "完整证据";
  input.dispatchEvent(new Event("input", { bubbles: true }));
  await settle();
  const button = host.querySelector("button.primary") as HTMLButtonElement;
  button.click();
  await settle();
  button.click();
  await settle();
  expect(mocks.post).toHaveBeenCalledTimes(6);
  for (let i = 0; i < 3; i++)
    expect(mocks.post.mock.calls[i]).toEqual(mocks.post.mock.calls[i + 3]);
  expect(input.value).toBe("完整证据");
});
it("does not create snapshots if the teacher cancels confirmation", async () => {
  const host = await mount();
  mocks.confirm.mockResolvedValue(false);
  const input = host.querySelector("input")!;
  input.value = "暂不采用";
  input.dispatchEvent(new Event("input", { bubbles: true }));
  await settle();
  (host.querySelector("button.primary") as HTMLButtonElement).click();
  await settle();
  expect(mocks.post).not.toHaveBeenCalled();
});
