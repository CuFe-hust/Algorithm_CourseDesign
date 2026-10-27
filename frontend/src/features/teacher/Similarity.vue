<script setup lang="ts">
/**
 * Teacher view of code similarity for one assignment.
 *
 * The page is deliberately an *evidence* view: it shows the pairs, the matched
 * line ranges, and the code side by side. It never prints "plagiarised". The
 * teacher compares the code and decides; the platform only saves the run so the
 * numbers cannot change between page loads.
 */
import { computed, onMounted, ref } from "vue";
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
 * The worker computes in the background. Poll at a bounded rate and stop as
 * soon as the batch settles: an unbounded polling loop would keep hammering the
 * server while a teacher leaves the tab open.
 */
async function pollBatch(batchId: string) {
  const deadline = Date.now() + 90_000;
  while (Date.now() < deadline) {
    const view = await request<{ status: string; steps: { status: string }[] }>(
      `/analysis/batches/${batchId}`,
    );
    const pending = view.steps.some((step) =>
      ["READY", "RUNNING", "WAITING_INPUT"].includes(step.status),
    );
    if (!pending || view.status === "COMPLETE") break;
    await new Promise((resolve) => setTimeout(resolve, 1200));
  }
  evidence.value = await request<SimilarityEvidence>(
    `/analysis/batches/${batchId}/similarity`,
  );
  activeItem.value = 0;
  selected.value = null;
  leftCode.value = null;
  rightCode.value = null;
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
        <select v-model="itemFilter">
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
        <select v-model="threshold">
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
        <p v-if="currentItem.status !== 'SUCCEEDED'" class="alert warning">
          该题比对尚未完成（状态
          {{ currentItem.status }}）。稍后重新打开本页或再次查询。
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
            <div v-else class="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>提交 A</th>
                    <th>提交 B</th>
                    <th>相似度</th>
                    <th>包含度</th>
                    <th>连续匹配</th>
                    <th></th>
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
