<script setup lang="ts">
/**
 * Teacher view of code similarity for one assignment.
 *
 * The page is deliberately an *evidence* view: it shows the pairs, the matched
 * line ranges, and the code side by side. It never prints "plagiarised". The
 * teacher compares the code and decides; the platform only saves the run so the
 * numbers cannot change between page loads.
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { AlignLeft, Copy, Play, ShieldAlert } from "@lucide/vue";
import { errorText, query, request } from "../../shared/api";
import { session } from "../../shared/session";
import CodePreview from "../../shared/CodePreview.vue";
import type { SubmissionDetail } from "../student/types";
import {
  insufficientLabels,
  percent,
  personLabel,
  type SimilarityCluster,
  type SimilarityEvidence,
  type SimilarityItem,
  type SimilarityPair,
  type SimilarityScopeAssignment,
} from "./similarityTypes";

const route = useRoute();
const router = useRouter();
const assignments = ref<SimilarityScopeAssignment[]>([]);
const assignmentId = ref("");
const itemFilter = ref("");
const threshold = ref("0.5");
const evidence = ref<SimilarityEvidence | null>(null);
const activeItem = ref(0);
const selected = ref<SimilarityPair | null>(null);
const leftCode = ref<SubmissionDetail | null>(null);
const rightCode = ref<SubmissionDetail | null>(null);
const loading = ref(true);
const running = ref(false);
/**
 * Set when the component goes away. Every await in the polling loop re-checks it,
 * otherwise navigating to another page leaves a timer chain firing requests
 * against a batch nobody is looking at.
 */
let unmounted = false;
const error = ref("");
const notice = ref("");

const scopeItems = computed<SimilarityScopeAssignment["items"]>(
  () =>
    assignments.value.find((row) => row.id === assignmentId.value)?.items ?? [],
);
const currentItem = computed<SimilarityItem | null>(
  () => evidence.value?.items[activeItem.value] ?? null,
);
const assignmentTitle = computed(
  () =>
    assignments.value.find((row) => row.id === assignmentId.value)?.title ?? "",
);

/** True while the worker has not finished; that is "still computing", not "failed". */
function stillComputing(item: SimilarityItem): boolean {
  return ["READY", "RUNNING", "WAITING_INPUT"].includes(item.status);
}

/** A run can succeed technically while the business outcome has no usable data. */
function businessWarning(item: SimilarityItem): boolean {
  return Boolean(item.business_status && item.business_status !== "OK");
}

/** Highlight the matched lines of both submissions for a chosen pair. */
function markedLines(span: { start: number; end: number } | null): string {
  if (!span) return "";
  return span.start === span.end
    ? `第 ${span.start} 行`
    : `第 ${span.start}–${span.end} 行`;
}

async function loadScope() {
  loading.value = true;
  error.value = "";
  try {
    const result = await request<{ items: SimilarityScopeAssignment[] }>(
      `/analysis/courses/${session.courseId}/code-similarity/scope`,
    );
    assignments.value = result.items;
    if (!assignmentId.value && result.items.length)
      assignmentId.value = result.items[0]!.id;
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loading.value = false;
  }
}

async function runComparison() {
  if (!assignmentId.value) return;
  running.value = true;
  error.value = "";
  notice.value = "";
  evidence.value = null;
  try {
    const body: Record<string, unknown> = {
      request_id: `sim-${Date.now()}`,
      assignment_id: assignmentId.value,
      threshold: threshold.value,
    };
    if (itemFilter.value) body.assignment_item_id = itemFilter.value;
    const batch = await request<{ id: string }>(
      `/analysis/courses/${session.courseId}/code-similarity/batches`,
      { method: "POST", body: JSON.stringify(body) },
    );
    await router.replace({ query: { ...route.query, batch: batch.id } });
    await pollBatch(batch.id);
  } catch (e) {
    error.value = errorText(e);
  } finally {
    running.value = false;
  }
}

/**
 * A stored batch is evidence: reopening the page must show the same numbers, not
 * start a new comparison. The batch id therefore lives in the URL.
 */
async function loadExistingBatch(batchId: string) {
  running.value = true;
  error.value = "";
  try {
    evidence.value = await request<SimilarityEvidence>(
      `/analysis/batches/${batchId}/similarity`,
    );
    activeItem.value = 0;
    notice.value = "";
  } catch (e) {
    error.value = errorText(e);
  } finally {
    running.value = false;
  }
}

/**
 * The worker computes in the background. Poll at a bounded rate and stop as soon
 * as the batch settles.
 *
 * Two rules found in review: the deadline bounds the *polling*, so hitting it
 * must not be reported as a finished comparison -- a batch that is still running
 * gets told to the teacher as still running and the evidence request is skipped.
 * And every wait re-checks ``unmounted`` so leaving the page stops the chain.
 */
async function pollBatch(batchId: string) {
  const deadline = Date.now() + 90_000;
  let settled = false;
  let lastStatus = "UNKNOWN";
  while (Date.now() < deadline && !unmounted) {
    const view = await request<{ status: string; steps: { status: string }[] }>(
      `/analysis/batches/${batchId}`,
    );
    if (unmounted) return;
    lastStatus = view.status;
    const pending = view.steps.some((step) =>
      ["READY", "RUNNING", "WAITING_INPUT"].includes(step.status),
    );
    if (!pending || view.status === "COMPLETE") {
      settled = true;
      break;
    }
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }
  if (unmounted) return;
  if (!settled) {
    notice.value = `比对仍在进行（批次状态 ${lastStatus}）。页面已停止自动刷新，请稍后重新打开本页查看同一批结果。`;
    return;
  }
  evidence.value = await request<SimilarityEvidence>(
    `/analysis/batches/${batchId}/similarity`,
  );
  if (unmounted) return;
  activeItem.value = 0;
  selected.value = null;
  leftCode.value = null;
  rightCode.value = null;
  const pendingItems = evidence.value.items.filter(
    (item) => item.status !== "SUCCEEDED",
  );
  if (pendingItems.length) {
    notice.value =
      "比对任务已创建，但计算还没完成。请确认分析 worker 正在运行（python -m scripts.run_analysis --watch），完成后重新打开本页即可看到同一批结果。";
    return;
  }
  const pairs = evidence.value.items.reduce(
    (sum, item) => sum + item.pairs.length,
    0,
  );
  notice.value = pairs
    ? `完成：共 ${pairs} 对相似证据。相似度是线索，需要你核对代码后再判断。`
    : "完成：没有达到阈值的相似对。可以降低阈值重新运行，或核对过短提交的说明。";
}

async function selectPair(pair: SimilarityPair) {
  selected.value = pair;
  error.value = "";
  try {
    const [left, right] = await Promise.all([
      request<SubmissionDetail>(`/submissions/${pair.left.submission_id}`),
      request<SubmissionDetail>(`/submissions/${pair.right.submission_id}`),
    ]);
    if (
      left.course_id !== session.courseId ||
      right.course_id !== session.courseId
    ) {
      throw new Error("提交不属于当前课程。");
    }
    leftCode.value = left;
    rightCode.value = right;
  } catch (e) {
    error.value = errorText(e);
  }
}

function selectCluster(cluster: SimilarityCluster) {
  const item = currentItem.value;
  if (!item) return;
  const pair = item.pairs.find(
    (row) =>
      cluster.members.some((m) => m.submission_id === row.left.submission_id) &&
      cluster.members.some((m) => m.submission_id === row.right.submission_id),
  );
  if (pair) void selectPair(pair);
  else notice.value = "该簇内没有达到阈值的单对证据。";
}

function changeAssignment(value: string) {
  assignmentId.value = value;
  itemFilter.value = "";
  evidence.value = null;
  selected.value = null;
}

onBeforeUnmount(() => {
  unmounted = true;
});

onMounted(async () => {
  await loadScope();
  const batchId =
    typeof route.query.batch === "string" ? route.query.batch : "";
  if (batchId) await loadExistingBatch(batchId);
});
</script>

<template>
  <div class="page-heading">
    <div>
      <span class="eyebrow">CODE SIMILARITY</span>
      <h1>相似代码检测</h1>
      <p class="muted">
        只比较同一道题内、截止前每人最后一次有效提交。相似度是证据，不是抄袭判定。
      </p>
    </div>
  </div>

  <div v-if="error" class="alert error">{{ error }}</div>
  <div v-if="notice" class="alert success">{{ notice }}</div>

  <section class="card teacher-form similarity-form">
    <div class="similarity-controls">
      <label>
        作业
        <select
          aria-label="作业"
          :value="assignmentId"
          @change="changeAssignment(($event.target as HTMLSelectElement).value)"
        >
          <option v-for="row in assignments" :key="row.id" :value="row.id">
            {{ row.title }}（{{ row.submission_status }}）
          </option>
        </select>
      </label>
      <label>
        题目
        <select v-model="itemFilter" aria-label="题目">
          <option value="">全部编程题</option>
          <option
            v-for="item in scopeItems"
            :key="item.item_id"
            :value="item.item_id"
          >
            {{ item.problem_code }} · {{ item.title }}（{{
              item.submitted_students
            }}
            人提交）
          </option>
        </select>
      </label>
      <label>
        相似度阈值
        <select v-model="threshold" aria-label="相似度阈值">
          <option value="0.4">40%（更宽，更多线索）</option>
          <option value="0.5">50%（默认）</option>
          <option value="0.7">70%（更严，只看高度相似）</option>
          <option value="0.85">85%</option>
        </select>
      </label>
    </div>
    <div class="action-row">
      <button
        class="primary"
        :disabled="running || !assignmentId"
        @click="runComparison"
      >
        <Play :size="16" />{{ running ? "正在比对…" : "开始比对" }}
      </button>
      <span v-if="loading" class="muted">正在读取可比较范围…</span>
      <span v-else-if="!assignments.length" class="muted">
        当前课程还没有包含编程题的作业。
      </span>
    </div>
  </section>

  <template v-if="evidence">
    <div v-if="!evidence.items.length" class="empty">
      <AlignLeft :size="28" />
      <h3>没有可比较的提交</h3>
      <p>学生提交后会出现在这里。</p>
    </div>
    <template v-else>
      <div class="tabs similarity-tabs">
        <button
          v-for="(item, index) in evidence.items"
          :key="item.item_id"
          :class="{ selected: index === activeItem }"
          @click="
            activeItem = index;
            selected = null;
            leftCode = null;
            rightCode = null;
          "
        >
          {{ item.problem_code }} · {{ item.title }}
          <span class="badge gray">{{ item.submission_count }} 份</span>
        </button>
      </div>

      <template v-if="currentItem">
        <p v-if="stillComputing(currentItem)" class="alert warning">
          该题比对仍在计算（运行状态
          {{ currentItem.status }}）。本页已停止自动刷新，
          稍后重新打开本页即可看到同一批结果。
        </p>
        <p
          v-else-if="
            currentItem.status !== 'SUCCEEDED' || businessWarning(currentItem)
          "
          class="alert warning"
        >
          该题比对没有可用结果（运行状态 {{ currentItem.status }}，业务状态
          {{
            currentItem.business_status || "未知"
          }}）。该批次已完成但未产出可比对的数据。
        </p>
        <template v-else>
          <section v-if="currentItem.clusters.length" class="card">
            <div class="card-heading">
              <h2><Copy :size="17" /> 相似簇</h2>
              <span class="muted">3 份及以上互相相似的提交</span>
            </div>
            <div class="cluster-list">
              <button
                v-for="(cluster, index) in currentItem.clusters"
                :key="index"
                class="cluster-row"
                @click="selectCluster(cluster)"
              >
                <span class="badge amber">{{ cluster.size }} 份</span>
                <span class="cluster-members">
                  {{ cluster.members.map(personLabel).join("、") }}
                </span>
                <span class="mono muted"
                  >最高 {{ percent(cluster.max_similarity) }}</span
                >
              </button>
            </div>
          </section>

          <section class="card">
            <div class="card-heading">
              <h2><ShieldAlert :size="17" /> 相似对</h2>
              <span class="muted">
                方法 {{ currentItem.method || "—" }}
                <template v-if="currentItem.parameters">
                  · k={{ currentItem.parameters.k }} · 窗口
                  {{ currentItem.parameters.window }} · 阈值
                  {{ percent(currentItem.parameters.threshold) }}
                </template>
              </span>
            </div>
            <p v-if="!currentItem.pairs.length" class="muted">
              没有达到阈值的相似对。
            </p>
            <template v-else>
              <p v-if="currentItem.pairs_truncated" class="alert warning">
                证据列表已截断：达到证据上限，这里只显示相似度最高的
                {{ currentItem.pairs.length }}
                对。下方的相似簇按全部配对计算，仍然完整。
              </p>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th>提交 A</th>
                      <th>提交 B</th>
                      <th>相似度</th>
                      <th>包含度</th>
                      <th>连续匹配</th>
                      <th aria-label="操作"></th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr
                      v-for="(pair, index) in currentItem.pairs"
                      :key="index"
                      :class="{ selected: selected === pair }"
                    >
                      <td>
                        <strong>{{ personLabel(pair.left) }}</strong>
                        <small class="secondary-line">{{
                          pair.left.student_no
                        }}</small>
                      </td>
                      <td>
                        <strong>{{ personLabel(pair.right) }}</strong>
                        <small class="secondary-line">{{
                          pair.right.student_no
                        }}</small>
                      </td>
                      <td>
                        <span class="badge amber">{{
                          percent(pair.similarity)
                        }}</span>
                      </td>
                      <td class="mono">
                        {{ percent(pair.containment_left) }} /
                        {{ percent(pair.containment_right) }}
                      </td>
                      <td class="mono">
                        {{ pair.longest_run_tokens ?? "—" }} 记号
                      </td>
                      <td>
                        <button class="small" @click="selectPair(pair)">
                          查看代码
                        </button>
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </template>
            <p class="hint">
              “包含度 A / B”表示 A 的指纹有多少出现在 B 里、B 的有多少出现在 A
              里。两边差距大，通常意味着一份代码被整段复制进了另一份。
            </p>
          </section>

          <section v-if="selected" class="card">
            <div class="card-heading">
              <h2>匹配证据</h2>
              <span class="muted">
                {{ personLabel(selected.left) }} 与
                {{ personLabel(selected.right) }}
              </span>
            </div>
            <div class="span-list">
              <div
                v-for="(span, index) in selected.spans"
                :key="index"
                class="span-row"
              >
                <span class="badge type">
                  {{
                    markedLines({
                      start: span.left_start_line,
                      end: span.left_end_line,
                    })
                  }}
                </span>
                <span class="muted">对应</span>
                <span class="badge type">
                  {{
                    markedLines({
                      start: span.right_start_line,
                      end: span.right_end_line,
                    })
                  }}
                </span>
                <span class="mono muted">
                  匹配 {{ span.matched_tokens }} 个记号，最长连续
                  {{ span.run_tokens }}
                </span>
              </div>
            </div>
            <div class="code-compare">
              <div>
                <h3>
                  {{ personLabel(selected.left) }}（v{{
                    selected.left.version_no
                  }}）
                </h3>
                <CodePreview
                  v-if="leftCode?.language"
                  :source="leftCode.content"
                  :language="leftCode.language"
                />
              </div>
              <div>
                <h3>
                  {{ personLabel(selected.right) }}（v{{
                    selected.right.version_no
                  }}）
                </h3>
                <CodePreview
                  v-if="rightCode?.language"
                  :source="rightCode.content"
                  :language="rightCode.language"
                />
              </div>
            </div>
          </section>

          <section v-if="currentItem.insufficient.length" class="card">
            <div class="card-heading"><h2>未参与比较的提交</h2></div>
            <ul class="limitations">
              <li
                v-for="row in currentItem.insufficient"
                :key="row.submission.submission_id"
              >
                {{ personLabel(row.submission) }}：
                {{ insufficientLabels[row.reason] || row.reason }}
                <template v-if="row.tokens"
                  >（{{ row.tokens }} 个记号）</template
                >
              </li>
            </ul>
          </section>
        </template>
      </template>

      <ul class="limitations similarity-limitations">
        <li v-for="text in evidence.limitations" :key="text">{{ text }}</li>
      </ul>
    </template>
  </template>
</template>
