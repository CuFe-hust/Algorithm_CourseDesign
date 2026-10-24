import { ApiError } from "./api";
import { renewSession } from "./session";

/**
 * Session activity manager.
 *
 * Only real, visible-page interactions create activity. Background timers,
 * polling and draft autosave never call `notifyActivity`, so an idle tab expires
 * after the two-hour idle window. Renewal is throttled and coalesced: at most one
 * request per minute, and only when something new actually happened.
 */
export const THROTTLE_MS = 60_000;

type Renew = () => Promise<unknown>;

let throttleMs = THROTTLE_MS;
let renew: Renew = renewSession;
let lastSentAt = 0;
let pending = false;
let timer: ReturnType<typeof setTimeout> | undefined;
let inflight: Promise<boolean> | null = null;
let stopped = false;
let listeners = 0;
let lastFailure: unknown = null;

const EVENTS = ["pointerdown", "keydown", "click"] as const;

export function configureActivity(
  options: {
    renew?: Renew;
    throttleMs?: number;
  } = {},
) {
  if (options.renew) renew = options.renew;
  if (options.throttleMs) throttleMs = options.throttleMs;
}

export function activityState() {
  return {
    lastSentAt,
    pending,
    inflight: inflight !== null,
    stopped,
    lastFailure,
  };
}

function visible() {
  return (
    typeof document === "undefined" || document.visibilityState === "visible"
  );
}

function schedule(delay: number) {
  if (timer !== undefined) clearTimeout(timer);
  timer = setTimeout(
    () => {
      timer = undefined;
      if (pending && !stopped) void flush();
    },
    Math.max(0, delay),
  );
}

async function flush(): Promise<boolean> {
  if (stopped || !pending) return false;
  if (inflight) return inflight;
  pending = false;
  lastFailure = null;
  inflight = (async () => {
    try {
      await renew();
      lastSentAt = Date.now();
      return true;
    } catch (error) {
      lastFailure = error;
      if (error instanceof ApiError && error.status === 401) {
        stopActivityTracking();
        return false;
      }
      // Network problems keep the intent: the next real interaction may retry.
      if (error instanceof ApiError && error.status === 0) pending = true;
      return false;
    } finally {
      inflight = null;
      if (pending && !stopped) {
        const since = lastSentAt > 0 ? Date.now() - lastSentAt : 0;
        schedule(throttleMs - since);
      }
    }
  })();
  return inflight;
}

export function notifyActivity() {
  if (stopped || !visible()) return;
  pending = true;
  const elapsed = Date.now() - lastSentAt;
  if (elapsed >= throttleMs) void flush();
  else schedule(throttleMs - elapsed);
}

export function startActivityTracking() {
  if (typeof window === "undefined" || listeners > 0) return;
  stopped = false;
  for (const name of EVENTS)
    window.addEventListener(name, notifyActivity, { passive: true });
  window.addEventListener("focus", notifyActivity);
  listeners = EVENTS.length + 1;
}

export function stopActivityTracking() {
  if (typeof window === "undefined") return;
  if (listeners > 0) {
    for (const name of EVENTS) window.removeEventListener(name, notifyActivity);
    window.removeEventListener("focus", notifyActivity);
    listeners = 0;
  }
  stopped = true;
  pending = false;
  if (timer !== undefined) {
    clearTimeout(timer);
    timer = undefined;
  }
}

export function resetActivityForTests() {
  stopActivityTracking();
  lastSentAt = 0;
  pending = false;
  inflight = null;
  lastFailure = null;
  stopped = false;
  throttleMs = THROTTLE_MS;
  renew = renewSession;
}
