import { onBeforeUnmount, ref } from "vue";
import { ApiError } from "../../../shared/api";
import { batchStatus } from "../api";
import type { BatchStatusEntry } from "../types";

export const BATCH_SIZE = 100;
export const MAX_PARALLEL_BATCHES = 2;
export const START_DELAY_MS = 2000;
export const MAX_DELAY_MS = 10000;

const TERMINAL = new Set([
  "SUCCEEDED",
  "FAILED",
  "CANCELLED",
  "AWAITING_REVIEW",
]);

function chunk<T>(items: T[], size: number): T[][] {
  const batches: T[][] = [];
  for (let index = 0; index < items.length; index += size)
    batches.push(items.slice(index, index + size));
  return batches;
}

export function useJudgePolling(options: {
  ids: () => string[];
  onChange: (entries: BatchStatusEntry[]) => void;
  onResync?: () => void;
  initialDelay?: number;
}) {
  const running = ref(false);
  const error = ref("");
  const tracked = ref<string[]>([]);
  let delay = options.initialDelay ?? START_DELAY_MS;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let stopped = true;
  let failures = 0;

  function schedule(wait: number) {
    if (timer !== undefined) clearTimeout(timer);
    timer = setTimeout(() => {
      timer = undefined;
      void tick();
    }, wait);
  }

  function visible() {
    return (
      typeof document === "undefined" || document.visibilityState === "visible"
    );
  }

  async function tick() {
    if (stopped) return;
    if (!visible()) return; // hidden pages pause instead of polling in the background
    const ids = options.ids();
    if (ids.length === 0) {
      schedule(MAX_DELAY_MS);
      return;
    }
    const batches = chunk(ids, BATCH_SIZE);
    try {
      const entries: BatchStatusEntry[] = [];
      for (
        let index = 0;
        index < batches.length;
        index += MAX_PARALLEL_BATCHES
      ) {
        const wave = batches.slice(index, index + MAX_PARALLEL_BATCHES);
        const results = await Promise.all(
          wave.map((batch) => batchStatus(batch)),
        );
        for (const result of results) entries.push(...result.items);
      }
      failures = 0;
      error.value = "";
      options.onChange(entries);
      const stillActive = entries.filter(
        (entry) => !TERMINAL.has(entry.job?.status ?? entry.status),
      );
      tracked.value = stillActive.map((entry) => entry.submission_id);
      if (stillActive.length === 0) {
        stopped = true;
        running.value = false;
        return;
      }
      delay = Math.min(MAX_DELAY_MS, Math.round(delay * 1.4));
      schedule(delay);
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 404) {
        // One invisible id makes the whole batch 404: rebuild the visible set instead of probing.
        error.value = "部分任务已不可见，正在重新同步。";
        options.onResync?.();
        stop();
        return;
      }
      failures += 1;
      error.value =
        failure instanceof ApiError ? failure.message : "任务状态查询失败";
      schedule(Math.min(MAX_DELAY_MS, START_DELAY_MS * failures));
    }
  }

  function start() {
    if (!stopped) return;
    stopped = false;
    running.value = true;
    delay = options.initialDelay ?? START_DELAY_MS;
    schedule(0);
  }

  function stop() {
    stopped = true;
    running.value = false;
    tracked.value = [];
    if (timer !== undefined) {
      clearTimeout(timer);
      timer = undefined;
    }
  }

  function refreshNow() {
    if (stopped) start();
    else schedule(0);
  }

  const visibility = () => {
    if (visible() && running.value) schedule(0);
  };
  if (typeof document !== "undefined")
    document.addEventListener("visibilitychange", visibility);

  onBeforeUnmount(() => {
    stop();
    if (typeof document !== "undefined")
      document.removeEventListener("visibilitychange", visibility);
  });

  return { running, error, tracked, start, stop, refreshNow, tick };
}
