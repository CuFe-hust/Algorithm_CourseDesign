/**
 * Local-only draft and unconfirmed-request storage.
 *
 * Drafts are keyed by account + item + language, so switching language never
 * borrows another language's source text and a different account never loads the
 * previous user's work. Storage failures are reported, never silently swallowed.
 */
export const SUBJECTIVE_LANGUAGE = "subjective";

export interface DraftRecord {
  key: string;
  userId: string;
  itemId: string;
  language: string;
  content: string;
  revision: number;
  updatedAt: number;
  writerId: string;
  itemVersion: string;
  lastSubmissionId: string | null;
}

export interface UnconfirmedRequest {
  key: string;
  userId: string;
  itemId: string;
  language: string;
  content: string;
  revision: number;
  clientRequestId: string;
  createdAt: number;
}

export interface SaveResult {
  ok: boolean;
  revision?: number;
  conflict?: DraftRecord;
  error?: string;
}

export interface DraftInput {
  userId: string;
  itemId: string;
  language: string;
  content: string;
  revision: number;
  itemVersion: string;
  lastSubmissionId?: string | null;
}

export interface KeyValueBackend {
  get(key: string): Promise<unknown>;
  set(key: string, value: unknown): Promise<void>;
  delete(key: string): Promise<void>;
  keys(prefix: string): Promise<string[]>;
}

export function draftKey(userId: string, itemId: string, language: string) {
  return `draft:${userId}:${itemId}:${language}`;
}
function unconfirmedKey(userId: string, clientRequestId: string) {
  return `pending:${userId}:${clientRequestId}`;
}

export class MemoryBackend implements KeyValueBackend {
  private data = new Map<string, unknown>();
  async get(key: string) {
    return this.data.get(key) ?? null;
  }
  async set(key: string, value: unknown) {
    this.data.set(key, value);
  }
  async delete(key: string) {
    this.data.delete(key);
  }
  async keys(prefix: string) {
    return [...this.data.keys()].filter((key) => key.startsWith(prefix));
  }
}

export class IndexedDbBackend implements KeyValueBackend {
  constructor(private db: IDBDatabase) {}
  private tx(mode: IDBTransactionMode) {
    return this.db.transaction("records", mode).objectStore("records");
  }
  private wrap<T>(request: IDBRequest<T>): Promise<T> {
    return new Promise((resolve, reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }
  async get(key: string) {
    const row = await this.wrap(this.tx("readonly").get(key));
    return row ? (row as { value: unknown }).value : null;
  }
  async set(key: string, value: unknown) {
    await this.wrap(this.tx("readwrite").put({ key, value }));
  }
  async delete(key: string) {
    await this.wrap(this.tx("readwrite").delete(key));
  }
  async keys(prefix: string) {
    const all = (await this.wrap(
      this.tx("readonly").getAllKeys(),
    )) as IDBValidKey[];
    return all.map(String).filter((key) => key.startsWith(prefix));
  }
}

export function openIndexedDb(
  name = "algoclass-drafts",
  timeoutMs = 1500,
): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    if (typeof indexedDB === "undefined") {
      reject(new Error("当前浏览器不支持 IndexedDB"));
      return;
    }
    const timer = setTimeout(
      () => reject(new Error("IndexedDB 打开超时")),
      timeoutMs,
    );
    const request = indexedDB.open(name, 1);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains("records"))
        db.createObjectStore("records", { keyPath: "key" });
    };
    request.onsuccess = () => {
      clearTimeout(timer);
      resolve(request.result);
    };
    request.onerror = () => {
      clearTimeout(timer);
      reject(request.error || new Error("IndexedDB 不可用"));
    };
    request.onblocked = () => {
      clearTimeout(timer);
      reject(new Error("IndexedDB 被其他页面阻塞"));
    };
  });
}

export class DraftStore {
  constructor(
    private backend: KeyValueBackend,
    readonly writerId: string,
    readonly degraded = false,
  ) {}

  private key(userId: string, itemId: string, language: string) {
    return draftKey(userId, itemId, language);
  }

  async loadDraft(
    userId: string,
    itemId: string,
    language: string,
  ): Promise<DraftRecord | null> {
    const record = (await this.backend.get(
      this.key(userId, itemId, language),
    )) as DraftRecord | null;
    if (!record || record.userId !== userId || record.itemId !== itemId)
      return null;
    return record;
  }

  async saveDraft(input: DraftInput): Promise<SaveResult> {
    const key = this.key(input.userId, input.itemId, input.language);
    try {
      const existing = (await this.backend.get(key)) as DraftRecord | null;
      if (
        existing &&
        existing.writerId !== this.writerId &&
        existing.revision > input.revision
      ) {
        return { ok: false, conflict: existing };
      }
      const revision = Math.max(input.revision, existing?.revision ?? 0) + 1;
      const record: DraftRecord = {
        key,
        userId: input.userId,
        itemId: input.itemId,
        language: input.language,
        content: input.content,
        revision,
        updatedAt: Date.now(),
        writerId: this.writerId,
        itemVersion: input.itemVersion,
        lastSubmissionId: input.lastSubmissionId ?? null,
      };
      await this.backend.set(key, record);
      return { ok: true, revision };
    } catch (error) {
      return { ok: false, error: describe(error) };
    }
  }

  async removeDraft(userId: string, itemId: string, language: string) {
    await this.backend.delete(this.key(userId, itemId, language));
  }

  async listDrafts(userId: string, itemId: string): Promise<DraftRecord[]> {
    const keys = await this.backend.keys(`draft:${userId}:${itemId}:`);
    const records: DraftRecord[] = [];
    for (const key of keys) {
      const record = (await this.backend.get(key)) as DraftRecord | null;
      if (record) records.push(record);
    }
    return records.sort((a, b) => b.updatedAt - a.updatedAt);
  }

  async saveUnconfirmed(
    request: Omit<UnconfirmedRequest, "key" | "createdAt">,
  ): Promise<boolean> {
    const key = unconfirmedKey(request.userId, request.clientRequestId);
    try {
      await this.backend.set(key, {
        ...request,
        key,
        createdAt: Date.now(),
      } satisfies UnconfirmedRequest);
      return true;
    } catch {
      return false;
    }
  }

  async listUnconfirmed(userId: string): Promise<UnconfirmedRequest[]> {
    const keys = await this.backend.keys(`pending:${userId}:`);
    const rows: UnconfirmedRequest[] = [];
    for (const key of keys) {
      const row = (await this.backend.get(key)) as UnconfirmedRequest | null;
      if (row) rows.push(row);
    }
    return rows.sort((a, b) => b.createdAt - a.createdAt);
  }

  async removeUnconfirmed(userId: string, clientRequestId: string) {
    await this.backend.delete(unconfirmedKey(userId, clientRequestId));
  }
}

function describe(error: unknown) {
  if (error instanceof Error) return error.message;
  return "本地存储不可用";
}

let shared: Promise<DraftStore> | null = null;

export function newWriterId() {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto)
    return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

export function createDraftStore(
  writerId = newWriterId(),
): Promise<DraftStore> {
  return openIndexedDb()
    .then((db) => new DraftStore(new IndexedDbBackend(db), writerId))
    .catch(() => new DraftStore(new MemoryBackend(), writerId, true));
}

export function draftStore(): Promise<DraftStore> {
  if (!shared) shared = createDraftStore();
  return shared;
}

export function resetDraftStoreForTests(store: DraftStore | null) {
  shared = store ? Promise.resolve(store) : null;
}
