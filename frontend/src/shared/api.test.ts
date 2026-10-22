// @vitest-environment jsdom
import { afterEach, describe, it, expect, vi } from "vitest";
import {
  request,
  requestBlob,
  post,
  ApiError,
  query,
  validationMessages,
} from "./api";
afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
});
describe("shared API contract", () => {
  it("applies the same authentication and error handling to downloaded CSV files", async () => {
    sessionStorage.setItem("algoclass.token", "test-download-session");
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response("student_no,full_name,class_name\n", { status: 200 }),
      );
    vi.stubGlobal("fetch", fetch);
    const blob = await requestBlob("/teacher/template");
    const content = await new Promise<string>((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(String(reader.result));
      reader.onerror = reject;
      reader.readAsText(blob);
    });
    expect(content).toContain("student_no");
    expect(
      (fetch.mock.calls[0]![1].headers as Headers).get("Authorization"),
    ).toBe("Bearer test-download-session");
    fetch.mockResolvedValueOnce(
      new Response('{"message":"请重新登录"}', { status: 401 }),
    );
    await expect(requestBlob("/teacher/template")).rejects.toMatchObject({
      status: 401,
    });
    expect(sessionStorage.getItem("algoclass.token")).toBeNull();
  });
  it("shows actionable validation hints without raw database or schema details", () => {
    expect(validationMessages({ requirements: ["至少一个测试用例"] })).toEqual([
      "至少一个测试用例",
    ]);
    expect(
      validationMessages([
        {
          field: "body.version.test_suite.cases.1.weight",
          type: "decimal_max_places",
        },
      ]),
    ).toEqual(["测试配置 · 测试点 · 第 2 项 · 权重：请检查数值范围与小数位数"]);
    expect(validationMessages(null)).toEqual([]);
  });
  it("retains BIGINT strings and injects bearer credentials", async () => {
    sessionStorage.setItem("algoclass.token", "test-session");
    const fetch = vi
      .fn()
      .mockResolvedValue(
        new Response('{"id":"9223372036854775806"}', { status: 200 }),
      );
    vi.stubGlobal("fetch", fetch);
    const result = await post<{ id: string }>("/teacher/test", {
      id: "9223372036854775806",
      weight: "0.125000",
    });
    expect(result.id).toBe("9223372036854775806");
    const headers = fetch.mock.calls[0]![1].headers as Headers;
    expect(headers.get("Authorization")).toBe("Bearer test-session");
    expect(fetch.mock.calls[0]![1].body).toContain('"weight":"0.125000"');
  });
  it("does not override multipart boundaries", async () => {
    const fetch = vi.fn().mockResolvedValue(new Response("{}"));
    vi.stubGlobal("fetch", fetch);
    await request("/upload", { method: "POST", body: new FormData() });
    expect(
      (fetch.mock.calls[0]![1].headers as Headers).has("Content-Type"),
    ).toBe(false);
  });
  it("clears expired sessions and keeps request IDs in errors", async () => {
    sessionStorage.setItem("algoclass.token", "expired");
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(
            '{"code":"UNAUTHORIZED","message":"请登录","request_id":"req-123"}',
            { status: 401 },
          ),
        ),
    );
    await expect(request("/courses")).rejects.toMatchObject({
      status: 401,
      requestId: "req-123",
    });
    expect(sessionStorage.getItem("algoclass.token")).toBeNull();
  });
  it("does not convert 404 or network failures into successful empty data", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 404 })),
    );
    await expect(request("/missing")).rejects.toBeInstanceOf(ApiError);
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    await expect(request("/courses")).rejects.toMatchObject({
      code: "NETWORK_ERROR",
    });
    expect(query({ q: "甲 & 乙", offset: 0, unused: "" })).toBe(
      "q=%E7%94%B2+%26+%E4%B9%99&offset=0",
    );
  });
});
