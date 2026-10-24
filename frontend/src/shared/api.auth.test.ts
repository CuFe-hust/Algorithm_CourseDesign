// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  captureAuth,
  clearSession,
  currentGeneration,
  isCurrentAuth,
  request,
  setSession,
  token,
} from "./api";

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStorage.clear();
  clearSession();
});

describe("authentication generation (RV06)", () => {
  it("bumps the generation on login, password change and logout", () => {
    const start = currentGeneration();
    setSession("token-a", { id: "1" });
    expect(currentGeneration()).toBe(start + 1);
    clearSession();
    expect(currentGeneration()).toBe(start + 2);
    expect(token()).toBeNull();
  });

  it("ignores a late 401 that belongs to an older credential", async () => {
    setSession("old-token");
    let resolveFetch: (value: Response) => void = () => {};
    vi.stubGlobal(
      "fetch",
      vi.fn().mockReturnValue(
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
      ),
    );
    const pending = request("/submissions/1");
    // The user re-authenticates while the old request is still in flight.
    setSession("new-token");
    const events: string[] = [];
    const listener = () => events.push("expired");
    window.addEventListener("session-expired", listener);
    resolveFetch(new Response('{"code":"AUTH_EXPIRED"}', { status: 401 }));
    await expect(pending).rejects.toBeInstanceOf(ApiError);
    window.removeEventListener("session-expired", listener);
    expect(token()).toBe("new-token");
    expect(events).toEqual([]);
  });

  it("clears the session for a 401 that belongs to the current credential", async () => {
    setSession("current-token");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(new Response("{}", { status: 401 })),
    );
    await expect(request("/courses")).rejects.toMatchObject({ status: 401 });
    expect(token()).toBeNull();
  });

  it("reports Retry-After so the UI can keep the draft and show a wait", async () => {
    setSession("token");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            code: "RATE_LIMITED",
            message: "太频繁",
            details: { retry_after_at: "2026-10-24T08:01:00Z" },
          }),
          { status: 429, headers: { "Retry-After": "42" } },
        ),
      ),
    );
    const failure = (await request("/assignment-items/1/submissions", {
      method: "POST",
      body: "{}",
    }).catch((error: unknown) => error)) as ApiError;
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure.retryAfterSeconds).toBe(42);
    expect(failure.retryAfterAt).toBe("2026-10-24T08:01:00Z");
    expect(token()).toBe("token");
  });

  it("treats a stale snapshot as no longer current", () => {
    setSession("a");
    const snapshot = captureAuth();
    expect(isCurrentAuth(snapshot)).toBe(true);
    setSession("b");
    expect(isCurrentAuth(snapshot)).toBe(false);
  });

  it("keeps network failures distinct from expired sessions", async () => {
    setSession("token");
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
    const failure = (await request("/courses").catch(
      (error: unknown) => error,
    )) as ApiError;
    expect(failure.network).toBe(true);
    expect(token()).toBe("token");
  });
});
