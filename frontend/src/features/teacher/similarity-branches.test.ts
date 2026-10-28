// @vitest-environment jsdom
/**
 * Branches of the similarity page that review found untested or broken: the
 * business-status warning, the truncation notice, and the accessible header.
 */
import { createApp, defineComponent, h, nextTick } from "vue";
import { afterEach, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ request: vi.fn(), replace: vi.fn() }));
vi.mock("vue-router", () => ({
  useRoute: () => ({ query: { batch: "7" }, path: "/teacher/similarity" }),
  useRouter: () => ({ replace: mocks.replace }),
}));
vi.mock("../../shared/session", () => ({ session: { courseId: "1" } }));
vi.mock("../../shared/api", async (original) => ({
  ...(await original<typeof import("../../shared/api")>()),
  request: mocks.request,
}));
import Similarity from "./Similarity.vue";

let cleanup: (() => void) | undefined;
afterEach(() => {
  cleanup?.();
  vi.clearAllMocks();
});

const person = (id: string, name: string) => ({
  submission_id: id,
  student_id: id,
  student_no: `DEMO202600${id}`,
  name,
  version_no: 1,
});

function item(overrides: Record<string, unknown> = {}) {
  return {
    item_id: "1",
    problem_code: "CODE-P01",
    title: "活动安排问题",
    status: "SUCCEEDED",
    business_status: "OK",
    submission_count: 3,
    implementation_name: "winnowing_token",
    implementation_version: "2",
    method: "winnowing_token_k12_w4",
    parameters: { k: 12, window: 4, threshold: "0.5" },
    pairs: [
      {
        left: person("2", "甲同学"),
        right: person("3", "乙同学"),
        similarity: "0.800000",
        jaccard: "0.6",
        containment_left: "0.8",
        containment_right: "0.9",
        shared_fingerprints: 20,
        matched_tokens: 60,
        longest_run_tokens: 30,
        spans: [
          {
            left_start_line: 2,
            left_end_line: 4,
            right_start_line: 2,
            right_end_line: 4,
            matched_tokens: 60,
            run_tokens: 30,
          },
        ],
      },
    ],
    clusters: [],
    insufficient: [],
    ...overrides,
  };
}

function evidence(overrides: Record<string, unknown> = {}) {
  return {
    batch_id: "7",
    assignment_id: "1",
    status: "COMPLETE",
    threshold: "0.5",
    items: [item(overrides)],
    limitations: ["相似度是证据，不是抄袭判定"],
  };
}

async function mount(batch: string, payload: unknown) {
  mocks.request.mockImplementation((path: string) => {
    if (path.startsWith("/analysis/courses/1/code-similarity/scope"))
      return Promise.resolve({ items: [], total: 0 });
    return Promise.resolve(payload);
  });
  const host = document.createElement("div");
  document.body.append(host);
  const app = createApp(Similarity);
  app.component(
    "RouterLink",
    defineComponent({
      props: { to: { type: String, default: "" } },
      setup:
        (props, { slots }) =>
        () =>
          h("a", { href: props.to }, slots.default?.()),
    }),
  );
  app.mount(host);
  cleanup = () => {
    app.unmount();
    host.remove();
  };
  for (let round = 0; round < 3; round++) {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await nextTick();
  }
  return host;
}

it("shows the pair table when nothing was truncated", async () => {
  const host = await mount("7", evidence());
  expect(host.textContent).toContain("80.0%");
  expect(host.textContent).not.toContain("证据列表已截断");
});

it("keeps the table visible when the evidence list was truncated", async () => {
  const host = await mount("7", evidence({ pairs_truncated: true }));
  // The notice must not replace the very list it is describing.
  expect(host.textContent).toContain("证据列表已截断");
  expect(host.querySelectorAll("tbody tr")).toHaveLength(1);
  expect(host.textContent).toContain("80.0%");
});

it("says a running batch is still computing, not that it has no results", async () => {
  const host = await mount("7", evidence({ status: "RUNNING" }));
  expect(host.textContent).toContain("仍在计算");
  expect(host.textContent).not.toContain("没有可用结果");
});

it("warns when a run succeeded but the business outcome is unusable", async () => {
  const host = await mount(
    "7",
    evidence({ business_status: "NOT_IMPLEMENTED" }),
  );
  expect(host.textContent).toContain("没有可用结果");
  expect(host.textContent).toContain("NOT_IMPLEMENTED");
  expect(host.querySelectorAll("tbody tr")).toHaveLength(0);
});

it("gives the action header an accessible name without an extra element", async () => {
  const host = await mount("7", evidence());
  const header = host.querySelector("th[aria-label='操作']");
  expect(header).not.toBeNull();
  // A position:absolute span inside a table cell escaped to the viewport and
  // widened the document at narrow widths, so no child element may be used.
  expect(header?.children.length).toBe(0);
});
