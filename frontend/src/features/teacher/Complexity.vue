<script setup lang="ts">
/**
 * Teacher overview of complexity reports for one programming item.
 *
 * One row per student: the merged verdict the platform published, never the raw
 * measurements. The page is deliberately not a grade book. A row without a
 * class shows an em dash, not O(1); a failed row shows the stored reason; a
 * report that could not measure growth is labelled 无法给出结论 rather than
 * borrowing a class from anywhere. Reports exist only after a student (or the
 * teacher, through the API) requests one, so the empty state says who can
 * request.
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { Activity, AlertTriangle, RefreshCw, Table2 } from "@lucide/vue";
import { errorText, query, request } from "../../shared/api";
import { session } from "../../shared/session";
import type { ComplexityResponse } from "../student/types";
import { dateText } from "./types";

interface ComplexityItem {
  item_id: string;
  assignment_id: string;
  assignment_title: string;
  problem_code: string;
  title: string;
  profile_family: string | null;
}

interface OverviewRow {
  student_id: string;
  student_no: string | null;
  name: string | null;
  assignment_item_id: string;
  title: string | null;
  submission_id: string;
  status: string;
  time_class: string | null;
  space_class: string | null;
  time_confidence: string | null;
  time_source: string | null;
  requested_at: string | null;
}

const OVERVIEW_LIMIT = 100;
const POLL_MS = 5000;
// A measurement budget is 150 s. Poll slightly longer so a report that finishes
// inside the budget still lands without the teacher pressing anything.
const POLL_LIMIT = 45;
const REASON_UNAVAILABLE = "原因读取失败，请刷新重试。";

const confidenceText: Record<string, string> = {
  HIGH: "高",
  MEDIUM: "中",
  LOW: "低",
};
const confidenceTone: Record<string, string> = {
  HIGH: "green",
  MEDIUM: "amber",
  LOW: "gray",
};
const sourceText: Record<string, string> = {
  TRACE: "执行轨迹",
  NONE: "未采集",
};
const statusText: Record<string, string> = {
  SUCCEEDED: "已完成",
  NOT_MEASURABLE: "无法给出结论",
  PENDING: "分析中",
  RUNNING: "分析中",
  FAILED: "分析失败",
  INELIGIBLE: "无法分析",
};
const statusTone: Record<string, string> = {
  SUCCEEDED: "type",
  NOT_MEASURABLE: "gray",
  PENDING: "amber",
  RUNNING: "amber",
  FAILED: "red",
  INELIGIBLE: "amber",
};

const items = ref<ComplexityItem[]>([]);
const assignmentId = ref("");
const itemId = ref("");
const rows = ref<OverviewRow[]>([]);
const total = ref(0);
const reasons = ref<Record<string, string>>({});
const loading = ref(true);
const loadingRows = ref(false);
const error = ref("");

let pollTimer: ReturnType<typeof setTimeout> | undefined;
const pollAttempts = ref(0);
let tableToken = 0;
/**
 * Set on teardown. ``schedulePoll`` runs after an await, so clearing the pending
 * timer is not enough: a response that lands after the page is gone would queue
 * the next poll. Review measured 24 further overview requests in 120 s after
 * navigating away mid-request.
 */
let unmounted = false;

const currentItem = computed(
  () => items.value.find((item) => item.item_id === itemId.value) ?? null,
);
const hasProfile = computed(() => Boolean(currentItem.value?.profile_family));
const visibleItems = computed(() =>
  items.value.filter(
    (item) => !assignmentId.value || item.assignment_id === assignmentId.value,
  ),
);
const assignmentOptions = computed(() => {
  const options: { id: string; title: string }[] = [];
  for (const item of items.value)
    if (!options.some((option) => option.id === item.assignment_id))
      options.push({ id: item.assignment_id, title: item.assignment_title });
  return options;
});
const pendingCount = computed(
  () =>
    rows.value.filter(
      (row) => row.status === "PENDING" || row.status === "RUNNING",
    ).length,
);
/**
 * True once automatic refresh is over: either the bounded window closed or a poll
 * failed. Without the error case the page kept promising "页面会自动刷新" while
 * polling had already stopped.
 */
const pollError = ref(false);
const pollStopped = computed(
  () =>
    pendingCount.value > 0 &&
    (pollAttempts.value >= POLL_LIMIT || pollError.value),
);

function shown(value: string | null | undefined): string {
  return value === null || value === undefined || value === "" ? "—" : value;
}

/** Statuses whose stored error message is worth showing next to the badge. */
const REASON_STATUSES = ["FAILED", "INELIGIBLE", "NOT_MEASURABLE"];

function reasonFor(row: OverviewRow): string {
  if (!REASON_STATUSES.includes(row.status)) return "";
  return reasons.value[row.submission_id] ?? "正在读取原因…";
}

function clearPoll() {
  if (pollTimer) {
    clearTimeout(pollTimer);
    pollTimer = undefined;
  }
}

/**
 * PENDING and RUNNING rows settle on the server without a user action. Poll at
 * a bounded rate and stop as soon as every row is terminal: an unbounded loop
 * would keep hammering the server while the page stays open.
 */
function schedulePoll() {
  clearPoll();
  if (unmounted) return;
  if (!pendingCount.value || pollAttempts.value >= POLL_LIMIT) return;
  pollTimer = setTimeout(() => {
    pollAttempts.value += 1;
    void loadRows(true);
  }, POLL_MS);
}

function resetRows() {
  clearPoll();
  pollError.value = false;
  pollAttempts.value = 0;
  rows.value = [];
  total.value = 0;
  reasons.value = {};
}

async function loadReasons(list: OverviewRow[], token: number) {
  // Reasons for a finished failure do not change between polls; re-fetching them
  // every 5 s turned a 10-row table into 10 extra requests per cycle in review.
  const next: Record<string, string> = { ...reasons.value };
  const targets = list.filter(
    (row) =>
      REASON_STATUSES.includes(row.status) &&
      next[row.submission_id] === undefined,
  );
  if (!targets.length) {
    reasons.value = next;
    return;
  }
  await Promise.all(
    targets.map(async (row) => {
      try {
        const detail = await request<ComplexityResponse>(
          `/analysis/submissions/${row.submission_id}/complexity`,
        );
        // A report that could not measure stores its cause on the report, while
        // INELIGIBLE/FAILED also mirror it in the response-level reason.
        next[row.submission_id] =
          detail.reason ?? detail.report?.error ?? "平台没有记录原因。";
      } catch {
        next[row.submission_id] = REASON_UNAVAILABLE;
      }
    }),
  );
  // A newer table must not receive reasons for the rows it no longer holds.
  if (token === tableToken) reasons.value = next;
}

/** Queue analysis for every really accepted submission of this item. */
const queueing = ref(false);
const queueNotice = ref("");

async function queueBatch() {
  if (!itemId.value) return;
  queueing.value = true;
  queueNotice.value = "";
  try {
    const result = await request<{
      queued: number;
      skipped: number;
      ineligible: number;
    }>(`/analysis/courses/${session.courseId}/complexity/batch`, {
      method: "POST",
      body: JSON.stringify({
        request_id: `batch-${Date.now()}`,
        assignment_item_id: itemId.value,
      }),
    });
    queueNotice.value =
      result.queued > 0
        ? `已为 ${result.queued} 份提交排队分析，${result.skipped} 份已有报告，${result.ineligible} 份未通过不参与。`
        : `没有新排队的提交：${result.skipped} 份已有报告，${result.ineligible} 份未通过不参与。`;
    await loadRows();
  } catch (e) {
    error.value = errorText(e);
  } finally {
    queueing.value = false;
  }
}

async function loadRows(silent = false) {
  const target = itemId.value;
  if (!target || unmounted) return;
  const token = ++tableToken;
  if (!silent) {
    loadingRows.value = true;
    error.value = "";
  }
  try {
    const result = await request<{ items: OverviewRow[]; total: number }>(
      `/analysis/courses/${session.courseId}/complexity?${query({
        assignment_item_id: target,
        limit: OVERVIEW_LIMIT,
      })}`,
    );
    // A fast filter switch, or a page that has been left, must not let an older
    // response overwrite state or queue another poll.
    if (unmounted || token !== tableToken) return;
    rows.value = result.items;
    total.value = result.total;
    pollError.value = false;
    void loadReasons(result.items, token);
    schedulePoll();
  } catch (e) {
    if (unmounted || token !== tableToken) return;
    clearPoll();
    pollError.value = true;
    error.value = errorText(e);
  } finally {
    if (!unmounted && token === tableToken) loadingRows.value = false;
  }
}

function pickItem(pool: ComplexityItem[]) {
  if (pool.some((item) => item.item_id === itemId.value)) return;
  itemId.value =
    (pool.find((item) => item.profile_family) ?? pool[0])?.item_id ?? "";
}

async function loadItems() {
  loading.value = true;
  error.value = "";
  try {
    const result = await request<{ items: ComplexityItem[] }>(
      `/analysis/courses/${session.courseId}/complexity/items`,
    );
    items.value = result.items;
    pickItem(items.value);
    await loadRows();
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loading.value = false;
  }
}

function changeAssignment(value: string) {
  assignmentId.value = value;
  pickItem(visibleItems.value);
  resetRows();
  void loadRows();
}

function changeItem(value: string) {
  itemId.value = value;
  resetRows();
  void loadRows();
}

onMounted(() => {
  void loadItems();
});

onBeforeUnmount(() => {
  unmounted = true;
  tableToken += 1;
  clearPoll();
});
</script>

<template>
  <div class="page-heading">
    <div>
      <span class="eyebrow">COMPLEXITY</span>
      <h1>复杂度分析</h1>
      <p class="muted">
        每道编程题、每位学生最新一份复杂度报告。结论是估计值，不参与评分，也不改变评测结果。
      </p>
    </div>
  </div>

  <div v-if="error" class="alert error" role="alert">{{ error }}</div>

  <div
    v-if="currentItem && !hasProfile"
    class="alert warning complexity-warning"
  >
    <AlertTriangle :size="15" />
    <span>
      该题没有配置规模伸缩档，平台无法测量增长，报告的结论会是“无法给出结论”。请先为该题配置伸缩档，再请求复杂度分析。
    </span>
  </div>

  <p v-if="loading" class="loading">正在读取可分析的编程题…</p>

  <section v-else-if="!items.length && !error" class="card">
    <div class="empty">
      <Table2 :size="28" />
      <h3>当前课程还没有编程题</h3>
      <p>复杂度分析只支持编程题；发布编程题并让学生提交后才会出现报告。</p>
    </div>
  </section>

  <template v-else-if="items.length">
    <section class="card teacher-form">
      <div class="complexity-controls">
        <label>
          作业
          <select
            :value="assignmentId"
            aria-label="选择作业"
            @change="
              changeAssignment(($event.target as HTMLSelectElement).value)
            "
          >
            <option value="">全部作业</option>
            <option
              v-for="option in assignmentOptions"
              :key="option.id"
              :value="option.id"
            >
              {{ option.title }}
            </option>
          </select>
        </label>
        <label>
          题目
          <select
            :value="itemId"
            aria-label="选择题目"
            @change="changeItem(($event.target as HTMLSelectElement).value)"
          >
            <option
              v-for="item in visibleItems"
              :key="item.item_id"
              :value="item.item_id"
            >
              {{ item.problem_code }} · {{ item.title
              }}{{ item.profile_family ? "" : "（无伸缩档）" }}
            </option>
          </select>
        </label>
      </div>
      <div class="action-row">
        <button
          class="small"
          :disabled="loadingRows || !itemId"
          @click="loadRows()"
        >
          <RefreshCw :size="14" />刷新
        </button>
        <button
          class="small"
          :disabled="queueing || !itemId || !hasProfile"
          title="为该题全部真实通过的提交排队复杂度分析；已有报告的提交自动跳过"
          @click="queueBatch"
        >
          <Table2 :size="14" />{{
            queueing ? "正在排队…" : "为本题已通过提交排队分析"
          }}
        </button>
        <span v-if="queueNotice" class="muted">{{ queueNotice }}</span>
        <span v-if="loadingRows" class="muted">正在读取报告…</span>
        <span v-else-if="pollStopped" class="muted">
          有
          {{ pendingCount }}
          份仍在分析中，已停止自动刷新，请点“刷新”查看最新状态。
        </span>
        <span v-else-if="pendingCount" class="muted">
          有 {{ pendingCount }} 份仍在分析中，页面会自动刷新。
        </span>
        <span v-else-if="currentItem" class="muted">
          {{ currentItem.assignment_title }}
        </span>
      </div>
    </section>

    <section v-if="currentItem" class="card">
      <div class="card-heading">
        <h2>
          <Activity :size="17" /> {{ currentItem.problem_code }} ·
          {{ currentItem.title }}
        </h2>
        <span class="muted">
          {{ currentItem.assignment_title }} · 共 {{ total }} 份报告
        </span>
      </div>

      <p v-if="loadingRows && !rows.length" class="loading">
        正在读取复杂度报告…
      </p>
      <div v-else-if="!rows.length" class="empty complexity-empty">
        <Table2 :size="28" />
        <h3>还没有这道题的复杂度报告</h3>
        <p>
          学生通过真实评测后，可以在学生端的提交详情里请求分析，报告会出现在这里。
        </p>
        <p>
          教师也可以按单份提交调用分析接口触发，但平台没有批量触发接口，所以本页不提供批量分析按钮。
        </p>
        <RouterLink to="/teacher/students" class="button subtle"
          >查看学生名单</RouterLink
        >
      </div>
      <template v-else>
        <div class="table-scroll">
          <table>
            <thead>
              <tr>
                <th>学生</th>
                <th>题目</th>
                <th>状态</th>
                <th>时间类别</th>
                <th>置信度</th>
                <th>来源</th>
                <th>请求时间</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in rows" :key="row.student_id">
                <td>
                  <RouterLink
                    class="table-title"
                    :to="`/teacher/students/${row.student_id}/progress`"
                    >{{ shown(row.name) }}</RouterLink
                  >
                  <small class="secondary-line mono">{{
                    shown(row.student_no)
                  }}</small>
                </td>
                <td>{{ shown(row.title) }}</td>
                <td>
                  <span
                    class="badge"
                    :class="statusTone[row.status] || 'gray'"
                    >{{ statusText[row.status] || row.status }}</span
                  >
                  <small
                    v-if="reasonFor(row)"
                    class="secondary-line complexity-reason"
                    >{{ reasonFor(row) }}</small
                  >
                </td>
                <td class="mono">{{ shown(row.time_class) }}</td>
                <td>
                  <span
                    v-if="row.time_confidence"
                    class="badge"
                    :class="confidenceTone[row.time_confidence] || 'gray'"
                    >{{
                      confidenceText[row.time_confidence] || row.time_confidence
                    }}</span
                  >
                  <span v-else class="muted">—</span>
                </td>
                <td>
                  {{
                    row.time_source
                      ? sourceText[row.time_source] || row.time_source
                      : "—"
                  }}
                </td>
                <td class="nowrap">
                  {{ row.requested_at ? dateText(row.requested_at) : "—" }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="total > rows.length" class="hint complexity-hint-line">
          本页显示前 {{ rows.length }} 份，共 {{ total }} 份。
        </p>
        <p class="hint complexity-hint-line">
          “执行轨迹”表示平台按题目的伸缩档生成输入后真实运行程序，统计执行轨迹里的工作量再推断类别。没有可用伸缩档或该语言没有采集器时，报告状态是“无法给出结论”。置信度只描述结论的可信程度，不表示代码好坏。
        </p>
      </template>
    </section>

    <section class="card">
      <div class="card-heading"><h2>适用范围</h2></div>
      <ul class="complexity-limitations">
        <li>复杂度结论是估计值，不是形式化证明。</li>
        <li>
          轨迹结论来自平台按题目伸缩档合成的输入，覆盖常见规模，不代表最坏情况或全部合法输入。
        </li>
        <li>
          轨迹只统计程序真实的执行次数，等价改写可能得到不同类别；没有采集器的语言不给出类别。
        </li>
        <li>复杂度分析不参与评分，也不改变评测结果。</li>
      </ul>
    </section>
  </template>
</template>
