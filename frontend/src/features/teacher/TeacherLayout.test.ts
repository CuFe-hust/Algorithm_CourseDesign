// @vitest-environment jsdom
import { createApp, defineComponent, h, nextTick } from "vue";
import { afterEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  route: { value: { path: "/teacher/problems/new" } },
  push: vi.fn(),
  session: {
    user: { full_name: "合成教师" },
    courseId: "9223372036854775805",
    courses: [
      {
        id: "9223372036854775805",
        name: "课程甲",
        term: "2026",
        role: "TEACHER",
      },
      {
        id: "9223372036854775806",
        name: "课程乙",
        term: "2026",
        role: "TEACHER",
      },
    ],
  },
}));
vi.mock("vue-router", () => ({
  useRouter: () => ({ push: mocks.push, currentRoute: mocks.route }),
}));
vi.mock("../../shared/session", () => ({
  session: mocks.session,
  selectCourse: (id: string) => {
    mocks.session.courseId = id;
  },
  logout: vi.fn(),
}));
import TeacherLayout from "./TeacherLayout.vue";

let cleanup: (() => void) | undefined;
afterEach(() => {
  cleanup?.();
  mocks.push.mockReset();
  mocks.route.value.path = "/teacher/problems/new";
  mocks.session.courseId = "9223372036854775805";
});
function mountLayout() {
  const host = document.createElement("div");
  document.body.append(host);
  const app = createApp(TeacherLayout);
  app.config.globalProperties.$route = {
    path: "/teacher/problems/new",
    fullPath: "/teacher/problems/new",
    name: undefined,
    params: {},
    query: {},
    hash: "",
    matched: [],
    meta: {},
    redirectedFrom: undefined,
  };
  app.component(
    "RouterLink",
    defineComponent({
      setup:
        (_, { slots }) =>
        () =>
          h("a", slots.default?.()),
    }),
  );
  app.component("RouterView", defineComponent({ render: () => null }));
  app.mount(host);
  cleanup = () => {
    app.unmount();
    host.remove();
  };
  return host.querySelector<HTMLSelectElement>(
    'select[aria-label="当前课程"]',
  )!;
}
it("restores the displayed course and retains the original scope when navigation is cancelled", async () => {
  mocks.push.mockResolvedValue(undefined);
  const select = mountLayout();
  select.value = "9223372036854775806";
  select.dispatchEvent(new Event("change", { bubbles: true }));
  await Promise.resolve();
  await nextTick();
  expect(select.value).toBe("9223372036854775805");
  expect(mocks.session.courseId).toBe("9223372036854775805");
});
it("changes scope only after navigation succeeds without losing BIGINT precision", async () => {
  mocks.push.mockImplementation(async () => {
    mocks.route.value.path = "/teacher";
  });
  const select = mountLayout();
  select.value = "9223372036854775806";
  select.dispatchEvent(new Event("change", { bubbles: true }));
  await Promise.resolve();
  await nextTick();
  expect(select.value).toBe("9223372036854775806");
  expect(mocks.session.courseId).toBe("9223372036854775806");
});
