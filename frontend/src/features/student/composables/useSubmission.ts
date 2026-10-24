import { computed, ref } from "vue";
import { ApiError, errorText } from "../../../shared/api";
import { draftStore, type UnconfirmedRequest } from "../draft-store";
import { submitAnswer } from "../api";
import type { Receipt } from "../types";

export function newRequestKey() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto)
    return crypto.randomUUID().replace(/-/g, "");
  return `${Date.now()}${Math.random().toString(16).slice(2)}`.slice(0, 32);
}

export interface SubmissionSnapshot {
  content: string;
  language: string | null;
  revision: number;
  clientRequestId: string;
  itemId: string;
  userId: string;
}

/** Local revision is stable for a request key: retrying must never mint a version. */
export function useSubmission(itemId: () => string) {
  const busy = ref(false);
  const receipt = ref<Receipt | null>(null);
  const receiptContent = ref("");
  const error = ref("");
  const unknownResult = ref(false);
  const pending = ref<UnconfirmedRequest[]>([]);
  const lastSnapshot = ref<SubmissionSnapshot | null>(null);

  const accepted = computed(() => receipt.value !== null);
  const needsNewKey = computed(
    () => unknownResult.value && pending.value.length === 0,
  );

  async function loadPending(userId: string) {
    const store = await draftStore();
    pending.value = await store.listUnconfirmed(userId);
    return pending.value;
  }

  async function send(snapshot: SubmissionSnapshot): Promise<Receipt | null> {
    busy.value = true;
    error.value = "";
    unknownResult.value = false;
    try {
      const result = await submitAnswer(itemId(), {
        content: snapshot.content,
        language: snapshot.language,
        client_request_id: snapshot.clientRequestId,
      });
      receipt.value = result;
      receiptContent.value = snapshot.content;
      lastSnapshot.value = snapshot;
      const store = await draftStore();
      await store.removeUnconfirmed(snapshot.userId, snapshot.clientRequestId);
      await loadPending(snapshot.userId);
      return result;
    } catch (failure) {
      if (failure instanceof ApiError && failure.status === 0) {
        unknownResult.value = true;
        error.value =
          "网络中断，无法确认是否已接收。可用同一请求重试，不会重复生成版本。";
        await loadPending(snapshot.userId);
        return null;
      }
      error.value = errorText(failure);
      if (
        failure instanceof ApiError &&
        (failure.code === "IDEMPOTENCY_CONFLICT" ||
          failure.status === 409 ||
          failure.status === 413 ||
          failure.status === 429)
      ) {
        unknownResult.value = true;
      }
      await loadPending(snapshot.userId);
      return null;
    } finally {
      busy.value = false;
    }
  }

  async function submit(input: {
    userId: string;
    content: string;
    language: string | null;
    revision: number;
    clientRequestId?: string;
  }) {
    const snapshot: SubmissionSnapshot = {
      userId: input.userId,
      itemId: itemId(),
      content: input.content,
      language: input.language,
      revision: input.revision,
      clientRequestId: input.clientRequestId || newRequestKey(),
    };
    lastSnapshot.value = snapshot;
    const store = await draftStore();
    const stored = await store.saveUnconfirmed({
      userId: snapshot.userId,
      itemId: snapshot.itemId,
      language: snapshot.language ?? "subjective",
      content: snapshot.content,
      revision: snapshot.revision,
      clientRequestId: snapshot.clientRequestId,
    });
    if (!stored) error.value = "无法在本机记录待提交请求，刷新后需要重新确认。";
    await loadPending(snapshot.userId);
    return send(snapshot);
  }

  /** Retry an unknown-result request with the exact original snapshot. */
  async function retry(request: UnconfirmedRequest) {
    return send({
      userId: request.userId,
      itemId: request.itemId,
      content: request.content,
      language: request.language === "subjective" ? null : request.language,
      revision: request.revision,
      clientRequestId: request.clientRequestId,
    });
  }

  async function discard(request: UnconfirmedRequest) {
    const store = await draftStore();
    await store.removeUnconfirmed(request.userId, request.clientRequestId);
    await loadPending(request.userId);
  }

  /** The editor content differs from the acknowledged snapshot. */
  function dirtySinceReceipt(current: string, language: string | null) {
    if (!receipt.value) return false;
    return (
      current !== receiptContent.value ||
      language !== (lastSnapshot.value?.language ?? null)
    );
  }

  return {
    busy,
    receipt,
    error,
    unknownResult,
    pending,
    accepted,
    needsNewKey,
    lastSnapshot,
    loadPending,
    submit,
    retry,
    discard,
    dirtySinceReceipt,
  };
}
