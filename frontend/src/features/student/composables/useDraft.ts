import { onBeforeUnmount, ref } from "vue";
import { DraftStore, draftStore, type DraftRecord } from "../draft-store";

export const DEBOUNCE_MS = 1000;

export interface DraftContext {
  userId: string;
  itemId: string;
  itemVersion: string;
}

/**
 * One draft slot = (account, item, language). The caller is responsible for
 * loading the right slot when the language changes; this composable never copies
 * content between languages.
 */
export function useDraft(getContext: () => DraftContext) {
  const content = ref("");
  const revision = ref(0);
  const status = ref<
    "idle" | "dirty" | "saving" | "saved" | "error" | "conflict"
  >("idle");
  const message = ref("");
  const conflict = ref<DraftRecord | null>(null);
  const lastSavedAt = ref<number | null>(null);
  let store: DraftStore | null = null;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let pendingValue = "";
  let language = "";
  let disposed = false;

  async function ensureStore() {
    if (!store) store = await draftStore();
    return store;
  }

  function cancelTimer() {
    if (timer !== undefined) {
      clearTimeout(timer);
      timer = undefined;
    }
  }

  async function persist(value = pendingValue): Promise<boolean> {
    if (!language) return false;
    const { userId, itemId, itemVersion } = getContext();
    status.value = "saving";
    try {
      const target = await ensureStore();
      const result = await target.saveDraft({
        userId,
        itemId,
        language,
        content: value,
        revision: revision.value,
        itemVersion,
      });
      if (!result.ok) {
        if (result.conflict) {
          conflict.value = result.conflict;
          status.value = "conflict";
          message.value = "另一标签页写入了更新的草稿，请选择保留哪一份。";
        } else {
          status.value = "error";
          message.value = result.error || "草稿保存失败";
        }
        return false;
      }
      revision.value = result.revision ?? revision.value + 1;
      status.value = "saved";
      lastSavedAt.value = Date.now();
      message.value = "";
      return true;
    } catch (error) {
      status.value = "error";
      message.value = error instanceof Error ? error.message : "草稿保存失败";
      return false;
    }
  }

  async function load(targetLanguage: string) {
    language = targetLanguage;
    status.value = "idle";
    conflict.value = null;
    const { userId, itemId } = getContext();
    const target = await ensureStore();
    const record = await target.loadDraft(userId, itemId, targetLanguage);
    if (record) {
      content.value = record.content;
      pendingValue = record.content;
      revision.value = record.revision;
      lastSavedAt.value = record.updatedAt;
      status.value = "saved";
    } else {
      content.value = "";
      pendingValue = "";
      revision.value = 0;
      lastSavedAt.value = null;
    }
    return record;
  }

  function setValue(value: string) {
    content.value = value;
    pendingValue = value;
    status.value = "dirty";
    cancelTimer();
    timer = setTimeout(() => {
      timer = undefined;
      void persist();
    }, DEBOUNCE_MS);
  }

  /** Apply content that did not come from typing (restored submission, conflict resolution). */
  function apply(value: string) {
    content.value = value;
    pendingValue = value;
  }

  async function flush() {
    cancelTimer();
    if (!language) return false;
    return persist(pendingValue);
  }

  async function clear(targetLanguage = language) {
    if (!targetLanguage) return;
    const { userId, itemId } = getContext();
    const target = await ensureStore();
    await target.removeDraft(userId, itemId, targetLanguage);
    if (targetLanguage === language) {
      revision.value = 0;
      content.value = "";
      status.value = "idle";
    }
  }

  function acceptConflict() {
    if (!conflict.value) return;
    content.value = conflict.value.content;
    revision.value = conflict.value.revision;
    conflict.value = null;
    status.value = "saved";
    message.value = "";
  }

  function dismissConflict() {
    conflict.value = null;
    status.value = "dirty";
    message.value = "";
  }

  async function onHide() {
    if (status.value === "dirty") await flush();
  }
  const visibility = () => {
    if (
      typeof document !== "undefined" &&
      document.visibilityState === "hidden"
    )
      void onHide();
  };
  if (typeof window !== "undefined") {
    window.addEventListener("beforeunload", onHide);
    document.addEventListener("visibilitychange", visibility);
  }
  onBeforeUnmount(() => {
    disposed = true;
    cancelTimer();
    if (typeof window !== "undefined") {
      window.removeEventListener("beforeunload", onHide);
      document.removeEventListener("visibilitychange", visibility);
    }
    void flush();
  });

  return {
    content,
    status,
    message,
    conflict,
    revision,
    lastSavedAt,
    disposed: () => disposed,
    load,
    setValue,
    apply,
    flush,
    clear,
    acceptConflict,
    dismissConflict,
  };
}
