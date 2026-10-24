// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import {
  activityState,
  configureActivity,
  notifyActivity,
  resetActivityForTests,
  startActivityTracking,
  stopActivityTracking,
  THROTTLE_MS,
} from "./activity";

const renew = vi.fn().mockResolvedValue({});

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-10-24T08:00:00Z"));
  renew.mockClear();
  renew.mockResolvedValue({});
  resetActivityForTests();
  configureActivity({ renew, throttleMs: THROTTLE_MS });
  startActivityTracking();
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    get: () => "visible",
  });
});

afterEach(() => {
  stopActivityTracking();
  resetActivityForTests();
  vi.useRealTimers();
});

const tick = () => vi.advanceTimersByTimeAsync(0);

describe("activity renewal (AC04–AC06)", () => {
  it("sends at most one renewal per minute for continuous typing", async () => {
    notifyActivity();
    await tick();
    expect(renew).toHaveBeenCalledTimes(1);
    for (let index = 0; index < 20; index += 1) {
      await vi.advanceTimersByTimeAsync(1000);
      notifyActivity();
    }
    expect(renew).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(THROTTLE_MS);
    expect(renew).toHaveBeenCalledTimes(2);
  });

  it("never renews without new activity", async () => {
    notifyActivity();
    await tick();
    expect(renew).toHaveBeenCalledTimes(1);
    expect(activityState().pending).toBe(false);
    await vi.advanceTimersByTimeAsync(THROTTLE_MS * 10);
    expect(renew).toHaveBeenCalledTimes(1);
  });

  it("coalesces several clicks into one request", async () => {
    notifyActivity();
    notifyActivity();
    notifyActivity();
    await tick();
    expect(renew).toHaveBeenCalledTimes(1);
  });

  it("ignores activity while the page is hidden", async () => {
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      get: () => "hidden",
    });
    notifyActivity();
    await tick();
    expect(renew).not.toHaveBeenCalled();
  });

  it("stops permanently after a 401 and does not retry in a loop", async () => {
    renew.mockRejectedValueOnce(new ApiError(401, "AUTH_EXPIRED", "过期"));
    notifyActivity();
    await tick();
    expect(renew).toHaveBeenCalledTimes(1);
    expect(activityState().stopped).toBe(true);
    notifyActivity();
    await vi.advanceTimersByTimeAsync(THROTTLE_MS * 3);
    expect(renew).toHaveBeenCalledTimes(1);
  });

  it("keeps the intent after a network failure without hammering the server", async () => {
    renew.mockRejectedValueOnce(new ApiError(0, "NETWORK_ERROR", "断网"));
    notifyActivity();
    await tick();
    expect(renew).toHaveBeenCalledTimes(1);
    expect(activityState().pending).toBe(true);
    await vi.advanceTimersByTimeAsync(THROTTLE_MS);
    expect(renew).toHaveBeenCalledTimes(2);
  });

  it("does not run a keepalive timer after stop", async () => {
    notifyActivity();
    await tick();
    stopActivityTracking();
    await vi.advanceTimersByTimeAsync(THROTTLE_MS * 3);
    expect(renew).toHaveBeenCalledTimes(1);
  });
});
