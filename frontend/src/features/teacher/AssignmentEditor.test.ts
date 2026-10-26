// @vitest-environment jsdom
import { createApp, defineComponent, h, nextTick } from "vue";
import { afterEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({
  request: vi.fn(),
  post: vi.fn(),
  confirm: vi.fn(),
  replace: vi.fn(),
}));
vi.mock("vue-router", () => ({
  useRoute: () => ({ params: { id: "100" } }),
  useRouter: () => ({ replace: mocks.replace }),
  onBeforeRouteLeave: vi.fn(),
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
import AssignmentEditor from "./AssignmentEditor.vue";
let cleanup: (() => void) | undefined;
afterEach(() => {
  cleanup?.();
  vi.clearAllMocks();
});
const assignment = {
  id: "100",
  course_id: "9223372036854775806",
  title: "合成作业",
  description_md: "",
  submission_status: "DRAFT",
  submission_deadline: "2026-11-01T12:00:00Z",
  review_deadline: null,
  updated_at: "2026-10-25T00:00:00Z",
  published_at: null as string | null,
  items: [],
  student_ids: [],
  participants: [],
};
function mount(value = assignment) {
  mocks.request.mockImplementation((path: string) =>
    Promise.resolve(
      path === "/teacher/assignments/100"
        ? value
        : { items: [], total: 0, limit: 20, offset: 0 },
    ),
  );
  const host = document.createElement("div");
  document.body.append(host);
  const app = createApp(AssignmentEditor);
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
it("opening for submissions is an explicit publish choice and does not dirty saved draft data", async () => {
  const host = mount();
  await settle();
  mocks.confirm.mockResolvedValue(true);
  mocks.post.mockResolvedValue({
    ...assignment,
    submission_status: "OPEN",
    published_at: "2026-10-25T01:00:00Z",
  });
  const select = [...host.querySelectorAll("select")].find((s) =>
    [...s.options].some((o) => o.value === "OPEN"),
  )!;
  select.value = "OPEN";
  select.dispatchEvent(new Event("change", { bubbles: true }));
  await nextTick();
  expect(button(host, "确认发布").disabled).toBe(false);
  button(host, "确认发布").click();
  await settle();
  expect(mocks.post).toHaveBeenCalledWith("/teacher/assignments/100/publish", {
    expected_updated_at: assignment.updated_at,
    submission_status: "OPEN",
  });
  expect(host.textContent).toContain("作业已发布");
});
it("unsaved edits block publication until the draft is saved", async () => {
  const host = mount();
  await settle();
  const input = host.querySelector(
    'input[maxlength="200"]',
  )! as HTMLInputElement;
  input.value = "未保存";
  input.dispatchEvent(new Event("input", { bubbles: true }));
  await nextTick();
  expect(button(host, "确认发布").disabled).toBe(true);
  expect(mocks.post).not.toHaveBeenCalled();
});
it("published content is read-only while schedule writes carry the pinned revision", async () => {
  const host = mount({
    ...assignment,
    submission_status: "CLOSED",
    published_at: "2026-10-25T00:01:00Z",
  });
  await settle();
  expect(
    (host.querySelector('input[maxlength="200"]')! as HTMLInputElement)
      .disabled,
  ).toBe(true);
  expect(button(host, "确认发布")).toBeUndefined();
  mocks.confirm.mockResolvedValue(true);
  mocks.post.mockResolvedValue({
    ...assignment,
    submission_status: "CLOSED",
    published_at: "2026-10-25T00:01:00Z",
  });
  host
    .querySelector("form")!
    .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  await settle();
  expect(mocks.post).toHaveBeenCalledWith(
    "/teacher/assignments/100/schedule",
    expect.objectContaining({
      expected_updated_at: assignment.updated_at,
      submission_status: "CLOSED",
      review_deadline: null,
    }),
  );
});
