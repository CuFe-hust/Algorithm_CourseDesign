// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import {
  DraftStore,
  MemoryBackend,
  SUBJECTIVE_LANGUAGE,
  draftKey,
  type KeyValueBackend,
} from "./draft-store";

function store(writerId = "writer-a") {
  return new DraftStore(new MemoryBackend(), writerId);
}

class BrokenBackend extends MemoryBackend {
  async set(): Promise<void> {
    throw new Error("QuotaExceededError");
  }
}

describe("draft storage (AC08–AC09, AC33)", () => {
  it("isolates drafts by account, item and language", async () => {
    const drafts = store();
    await drafts.saveDraft({
      userId: "1",
      itemId: "10",
      language: "python3",
      content: "print(1)",
      revision: 0,
      itemVersion: "v1",
    });
    await drafts.saveDraft({
      userId: "1",
      itemId: "10",
      language: "cpp",
      content: "#include <iostream>",
      revision: 0,
      itemVersion: "v1",
    });
    await drafts.saveDraft({
      userId: "2",
      itemId: "10",
      language: "python3",
      content: "print(2)",
      revision: 0,
      itemVersion: "v1",
    });
    expect((await drafts.loadDraft("1", "10", "python3"))?.content).toBe(
      "print(1)",
    );
    expect((await drafts.loadDraft("1", "10", "cpp"))?.content).toContain(
      "include",
    );
    expect((await drafts.loadDraft("2", "10", "python3"))?.content).toBe(
      "print(2)",
    );
    // C++ must never inherit Python source when it has no draft of its own.
    expect(await drafts.loadDraft("2", "10", "cpp")).toBeNull();
    expect(draftKey("1", "10", SUBJECTIVE_LANGUAGE)).toBe(
      "draft:1:10:subjective",
    );
  });

  it("keeps the newest draft per language available for language switching", async () => {
    const drafts = store();
    await drafts.saveDraft({
      userId: "1",
      itemId: "10",
      language: "python3",
      content: "py",
      revision: 0,
      itemVersion: "v1",
    });
    const list = await drafts.listDrafts("1", "10");
    expect(list.map((record) => record.language)).toEqual(["python3"]);
  });

  it("increments the revision and detects multi-tab conflicts", async () => {
    // Two tabs share one browser storage backend but have distinct writer ids.
    const backend = new MemoryBackend();
    const first = new DraftStore(backend, "tab-a");
    const second = new DraftStore(backend, "tab-b");
    const saved = await first.saveDraft({
      userId: "1",
      itemId: "10",
      language: "python3",
      content: "a",
      revision: 0,
      itemVersion: "v1",
    });
    expect(saved.ok && saved.revision).toBe(1);
    const conflict = await second.saveDraft({
      userId: "1",
      itemId: "10",
      language: "python3",
      content: "b",
      revision: 0,
      itemVersion: "v1",
    });
    expect(conflict.ok).toBe(false);
    expect(conflict.conflict?.content).toBe("a");
    const safe = await second.saveDraft({
      userId: "1",
      itemId: "10",
      language: "python3",
      content: "c",
      revision: conflict.conflict!.revision,
      itemVersion: "v1",
    });
    expect(safe.ok).toBe(true);
  });

  it("reports a storage failure instead of pretending the draft was saved", async () => {
    const drafts = new DraftStore(new BrokenBackend(), "writer-a");
    const result = await drafts.saveDraft({
      userId: "1",
      itemId: "10",
      language: "python3",
      content: "x",
      revision: 0,
      itemVersion: "v1",
    });
    expect(result.ok).toBe(false);
    expect(result.error).toContain("Quota");
  });

  it("records unconfirmed requests per account and clears them on confirmation", async () => {
    const drafts = store();
    await drafts.saveUnconfirmed({
      userId: "1",
      itemId: "10",
      language: "python3",
      content: "print(1)",
      revision: 3,
      clientRequestId: "req-1",
    });
    expect(await drafts.listUnconfirmed("2")).toEqual([]);
    const mine = await drafts.listUnconfirmed("1");
    expect(mine).toHaveLength(1);
    expect(mine[0]!.content).toBe("print(1)");
    await drafts.removeUnconfirmed("1", "req-1");
    expect(await drafts.listUnconfirmed("1")).toEqual([]);
  });

  it("falls back to memory storage when a backend cannot be opened", async () => {
    const backend: KeyValueBackend = new MemoryBackend();
    const drafts = new DraftStore(backend, "writer", true);
    expect(drafts.degraded).toBe(true);
  });
});
