// @vitest-environment jsdom
import { createApp, defineComponent, h, nextTick } from "vue";
import { afterEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  post: vi.fn(),
  confirm: vi.fn(),
  leave: undefined as undefined | (() => Promise<boolean>),
}));
vi.mock("vue-router", () => ({
  onBeforeRouteLeave: (fn: () => Promise<boolean>) => {
    mocks.leave = fn;
  },
}));
vi.mock("../../shared/session", () => ({
  session: { courseId: "9223372036854775806" },
}));
vi.mock("../../shared/confirm", () => ({ confirmAction: mocks.confirm }));
vi.mock("../../shared/api", async (original) => ({
  ...(await original<typeof import("../../shared/api")>()),
  request: mocks.request,
  post: mocks.post,
}));
import Students from "./Students.vue";
let cleanup: (() => void) | undefined;
afterEach(() => {
  cleanup?.();
  vi.clearAllMocks();
});
const student = {
  id: "9223372036854775804",
  student_no: "00100",
  full_name: "合成学生",
  login_name: "student.00100",
  status: "PENDING",
  class_name: "合成班",
  class_code: "T",
  updated_at: "2026-10-25T00:00:00Z",
  must_change_password: false,
};
function mount() {
  mocks.request.mockImplementation((path: string) =>
    Promise.resolve(
      path.endsWith("/classes")
        ? { items: [] }
        : { items: [student], total: 1, limit: 20, offset: 0 },
    ),
  );
  const host = document.createElement("div");
  document.body.append(host);
  const app = createApp(Students);
  app.component(
    "RouterLink",
    defineComponent({
      setup:
        (_, { slots }) =>
        () =>
          h("a", slots.default?.()),
    }),
  );
  app.mount(host);
  cleanup = () => {
    app.unmount();
    host.remove();
  };
  return host;
}
async function settle() {
  await new Promise((r) => setTimeout(r, 0));
  await nextTick();
}
function button(host: HTMLElement, text: string) {
  return [...host.querySelectorAll("button")].find(
    (b) => b.textContent?.trim() === text,
  )!;
}
it("issues only after confirmation with the exact account revision and clears one-time plaintext", async () => {
  mocks.confirm.mockResolvedValue(true);
  mocks.post.mockResolvedValue({
    credentials: [
      {
        ...student,
        student_id: student.id,
        initial_password: "synthetic-one-time-secret",
      },
    ],
  });
  const host = mount();
  await settle();
  button(host, "开通账号").click();
  await settle();
  expect(mocks.post).toHaveBeenCalledWith(
    "/teacher/courses/9223372036854775806/students/credentials",
    {
      action: "ACTIVATE",
      students: [
        { student_id: student.id, expected_updated_at: student.updated_at },
      ],
    },
  );
  expect(host.textContent).toContain("synthetic-one-time-secret");
  expect(button(host, "开通账号").disabled).toBe(true);
  expect(sessionStorage.length).toBe(0);
  button(host, "已保存，清除本页明文").click();
  await nextTick();
  expect(host.textContent).not.toContain("synthetic-one-time-secret");
});
it("cancelled confirmation never changes credentials", async () => {
  mocks.confirm.mockResolvedValue(false);
  const host = mount();
  await settle();
  button(host, "开通账号").click();
  await settle();
  expect(mocks.post).not.toHaveBeenCalled();
});
it("leaving with undistributed credentials respects cancellation", async () => {
  mocks.confirm.mockResolvedValue(true);
  mocks.post.mockResolvedValue({
    credentials: [
      {
        ...student,
        student_id: student.id,
        initial_password: "synthetic-only",
      },
    ],
  });
  const host = mount();
  await settle();
  button(host, "开通账号").click();
  await settle();
  mocks.confirm.mockResolvedValue(false);
  expect(await mocks.leave!()).toBe(false);
  expect(host.textContent).toContain("synthetic-only");
});
