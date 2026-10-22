// @vitest-environment jsdom
import { createApp, defineComponent, h, nextTick } from "vue";
import { afterEach, expect, it, vi } from "vitest";
const mocks = vi.hoisted(() => ({ request: vi.fn() }));
vi.mock("vue-router", () => ({ onBeforeRouteLeave: vi.fn() }));
vi.mock("../../shared/session", () => ({
  session: { courseId: "9223372036854775806" },
}));
vi.mock("../../shared/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../shared/api")>()),
  request: mocks.request,
}));
import StudentImport from "./StudentImport.vue";

const preview = {
  valid: true,
  preview_token: "signed-test-preview",
  content_sha256: "a".repeat(64),
  expires_in: 900,
  requires_update_confirmation: true,
  summary: { updated_profiles: 1 },
  rows: [
    {
      row_number: 2,
      student_no: "001",
      full_name: "合成甲",
      class_name: "合成班",
      action: "UPDATE",
      errors: [],
      changes: ["姓名"],
    },
  ],
};
let cleanup: (() => void) | undefined;
afterEach(() => {
  cleanup?.();
  mocks.request.mockReset();
});
function mount() {
  const host = document.createElement("div");
  document.body.append(host);
  const app = createApp(StudentImport);
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
function button(host: HTMLElement, text: string) {
  return [...host.querySelectorAll("button")].find(
    (node) => node.textContent?.trim() === text,
  );
}
async function selectFile(host: HTMLElement, name = "synthetic.csv") {
  const input = host.querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(input, "files", {
    configurable: true,
    value: [
      new File(["student_no,full_name,class_name\n001,合成甲,合成班"], name, {
        type: "text/csv",
      }),
    ],
  });
  input.dispatchEvent(new Event("change", { bubbles: true }));
  await nextTick();
}
async function settle() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await nextTick();
}

it("requires explicit approval for profile changes and submits the previewed file and signature", async () => {
  mocks.request.mockResolvedValueOnce(preview).mockResolvedValueOnce({
    summary: { updated_profiles: 1 },
    rows: 1,
    replayed: false,
  });
  const host = mount();
  await selectFile(host);
  button(host, "预览并校验")!.click();
  await settle();
  expect(button(host, "确认导入")!.disabled).toBe(true);
  const approval = host.querySelector<HTMLInputElement>(
    '.import-confirm input[type="checkbox"]',
  )!;
  approval.checked = true;
  approval.dispatchEvent(new Event("change", { bubbles: true }));
  await nextTick();
  expect(button(host, "确认导入")!.disabled).toBe(false);
  button(host, "确认导入")!.click();
  await settle();
  expect(host.textContent).toContain("学生名单导入完成");
  const [path, options] = mocks.request.mock.calls[1]!;
  expect(path).toBe(
    "/teacher/courses/9223372036854775806/students/import/confirm",
  );
  const body = options.body as FormData;
  expect((body.get("file") as File).name).toBe("synthetic.csv");
  expect(body.get("preview_token")).toBe(preview.preview_token);
  expect(body.get("expected_sha256")).toBe(preview.content_sha256);
  expect(body.get("allow_updates")).toBe("true");
});

it("invalidates all previous approval and preview state when a different file is selected", async () => {
  mocks.request.mockResolvedValue(preview);
  const host = mount();
  await selectFile(host);
  button(host, "预览并校验")!.click();
  await settle();
  expect(host.textContent).toContain("校验结果");
  await selectFile(host, "different.csv");
  expect(button(host, "确认导入")).toBeUndefined();
  expect(host.textContent).not.toContain("校验结果");
  expect(host.textContent).toContain("different.csv");
  expect(mocks.request).toHaveBeenCalledTimes(1);
});

it("disables confirmation and displays row errors for an invalid roster", async () => {
  mocks.request.mockResolvedValue({
    ...preview,
    valid: false,
    preview_token: null,
    requires_update_confirmation: false,
    rows: [
      { ...preview.rows[0], action: "ERROR", errors: ["同一文件中学号重复"] },
    ],
  });
  const host = mount();
  await selectFile(host);
  button(host, "预览并校验")!.click();
  await settle();
  expect(host.textContent).toContain("同一文件中学号重复");
  expect(button(host, "确认导入")!.disabled).toBe(true);
  button(host, "确认导入")!.click();
  await settle();
  expect(mocks.request).toHaveBeenCalledTimes(1);
});
