// @vitest-environment jsdom
import { createApp, nextTick } from "vue";
import { afterEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  select: vi.fn(),
  load: vi.fn(),
  course: {
    id: "9223372036854775806",
    name: "合成课程",
    term: "2026",
    role: "TEACHER",
  },
}));
vi.mock("vue-router", () => ({
  useRouter: () => ({ replace: mocks.replace }),
  useRoute: () => ({ query: { next: "/teacher/assignments/100" } }),
}));
vi.mock("./session", () => ({
  session: { courses: [mocks.course], coursesLoaded: true },
  currentCourse: () => mocks.course,
  selectCourse: mocks.select,
  loadCourses: mocks.load,
  loadSession: vi.fn(),
  logout: vi.fn(),
}));
vi.mock("./activity", () => ({ startActivityTracking: vi.fn() }));
import CourseSelect from "./CourseSelect.vue";
let cleanup: (() => void) | undefined;
afterEach(() => {
  cleanup?.();
  vi.clearAllMocks();
});
it("renders remembered courses immediately and resumes a teacher deep link after explicit selection", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const app = createApp(CourseSelect);
  app.mount(host);
  cleanup = () => {
    app.unmount();
    host.remove();
  };
  await nextTick();
  expect(host.textContent).not.toContain("正在读取课程");
  expect(host.textContent).toContain("合成课程");
  host.querySelector<HTMLButtonElement>(".course-card")!.click();
  await Promise.resolve();
  expect(mocks.select).toHaveBeenCalledWith(mocks.course.id);
  expect(mocks.replace).toHaveBeenCalledWith("/teacher/assignments/100");
});
