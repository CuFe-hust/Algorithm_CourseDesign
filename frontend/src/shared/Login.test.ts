// @vitest-environment jsdom
import { createApp, nextTick } from "vue";
import { afterEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  login: vi.fn(),
  next: "/teacher/assignments/100",
}));
vi.mock("vue-router", () => ({
  useRouter: () => ({ replace: mocks.replace }),
  useRoute: () => ({ query: { next: mocks.next } }),
}));
vi.mock("./session", () => ({ session: {}, login: mocks.login }));
vi.mock("./activity", () => ({ startActivityTracking: vi.fn() }));
import Login from "./Login.vue";
let cleanup: (() => void) | undefined;
afterEach(() => {
  cleanup?.();
  vi.clearAllMocks();
});
it("a remembered teacher deep link still passes through explicit course selection", async () => {
  mocks.login.mockResolvedValue({ must_change_password: false });
  const host = document.createElement("div");
  document.body.append(host);
  const app = createApp(Login);
  app.mount(host);
  cleanup = () => {
    app.unmount();
    host.remove();
  };
  host
    .querySelector("form")!
    .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  await Promise.resolve();
  await nextTick();
  expect(mocks.replace).toHaveBeenCalledWith({
    path: "/courses",
    query: { next: "/teacher/assignments/100" },
  });
});
