<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { ArrowRight, Clock, FileText } from "@lucide/vue";
import { errorText, request } from "../../shared/api";
import type { Page, Task } from "../analytics/peer-review/types";
import * as api from "./api";
import { formatDateTime, remainingLabel } from "./format";
import { useJudgePolling } from "./composables/useJudgePolling";
import type {
  AssignmentSummary,
  ProgressEntry,
  ProgressResponse,
} from "./types";

const route = useRoute();
const courseId = computed(() => String(route.params.courseId));
const assignments = ref<AssignmentSummary[]>([]);
const progress = ref<ProgressResponse | null>(null);
const loading = ref(true);
const error = ref("");

const progressMap = computed(() => {
  const map = new Map<string, ProgressEntry>();
  for (const entry of progress.value?.items ?? [])
    map.set(entry.assignment_item_id, entry);
  return map;
});
const reviewTasks = ref<Task[] | null>(null);
const now = computed(() =>
  new Date(progress.value?.as_of ?? Date.now()).getTime(),
);
const pendingReviews = computed(() =>
  (reviewTasks.value ?? [])
    .filter(
      (task) =>
        task.status !== "SUBMITTED" &&
        task.round_status === "OPEN" &&
        Date.parse(task.review_deadline) > now.value,
    )
    .sort(
      (a, b) => Date.parse(a.review_deadline) - Date.parse(b.review_deadline),
    ),
);
const assignmentCards = computed(() =>
  assignments.value
    .map((assignment) => {
      const remaining = assignment.items.filter(
        (item) => !progressMap.value.get(item.id)?.has_submitted,
      );
      const open =
        assignment.submission_status === "OPEN" &&
        Date.parse(assignment.submission_deadline) > now.value;
      const complete = assignment.items.length > 0 && remaining.length === 0;
      return {
        ...assignment,
        remaining,
        open,
        complete,
        submitted: assignment.items.length - remaining.length,
      };
    })
    .sort(
      (a, b) =>
        Number(b.open && !b.complete) - Number(a.open && !a.complete) ||
        Date.parse(a.submission_deadline) - Date.parse(b.submission_deadline),
    ),
);
const pendingQuestions = computed(() =>
  assignmentCards.value.reduce(
    (total, assignment) =>
      total + (assignment.open ? assignment.remaining.length : 0),
    0,
  ),
);
const nextAssignment = computed(() =>
  assignmentCards.value.find((a) => a.open && a.remaining.length),
);
async function loadReviews() {
  try {
    const tasks: Task[] = [];
    let offset = 0;
    for (;;) {
      const page = await request<Page<Task>>(
        `/peer-review/courses/${courseId.value}/my-tasks?limit=50&offset=${offset}`,
      );
      tasks.push(...page.items);
      offset += page.items.length;
      if (!page.items.length || offset >= page.total) break;
    }
    reviewTasks.value = tasks;
  } catch {
    reviewTasks.value = null;
  }
}

// Authoritative discovery: page through the keyset scan instead of trusting the
// progress snapshot, so more than 100 jobs and jobs restored by an operator are
// still found.
const activeJobIds = ref<string[]>([]);
const scanning = ref(false);
let rescanTimer: ReturnType<typeof setInterval> | undefined;
let refreshTimer: ReturnType<typeof setTimeout> | undefined;

async function scanJobs() {
  if (scanning.value) return;
  scanning.value = true;
  try {
    const ids = new Set<string>();
    let cursor: string | undefined;
    for (let page = 0; page < 50; page += 1) {
      const result = await api.discoverJobs(courseId.value, cursor, 100);
      for (const item of result.items) {
        const status = item.job?.status;
        if (status === "PENDING" || status === "RUNNING")
          ids.add(item.submission_id);
      }
      if (!result.has_more || !result.next_cursor) break;
      cursor = result.next_cursor;
    }
    activeJobIds.value = [...ids];
    if (activeJobIds.value.length) polling.start();
    else polling.stop();
  } catch (e) {
    error.value = errorText(e);
  } finally {
    scanning.value = false;
  }
}

function scheduleRefresh() {
  if (refreshTimer) return;
  refreshTimer = setTimeout(() => {
    refreshTimer = undefined;
    void refresh();
  }, 300);
}

const polling = useJudgePolling({
  ids: () => activeJobIds.value,
  onChange: (entries) => {
    activeJobIds.value = entries
      .filter((entry) =>
        ["PENDING", "RUNNING"].includes(entry.job?.status ?? ""),
      )
      .map((entry) => entry.submission_id);
    scheduleRefresh();
  },
  onResync: () => {
    // One invisible id fails the whole batch: rebuild the visible set instead of probing.
    activeJobIds.value = [];
    void scanJobs();
    scheduleRefresh();
  },
});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [list, report] = await Promise.all([
      api.listAssignments(courseId.value),
      api.myProgress(courseId.value),
    ]);
    assignments.value = list.items;
    progress.value = report;
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loading.value = false;
  }
}
async function refresh() {
  try {
    progress.value = await api.myProgress(courseId.value);
  } catch {
    /* keep the previous snapshot; the poller retries */
  }
}

onMounted(async () => {
  await Promise.all([load(), loadReviews()]);
  await scanJobs();
  // Periodic keyset rescan finds jobs that an operator or another page resumed.
  rescanTimer = setInterval(() => void scanJobs(), 60_000);
});

onBeforeUnmount(() => {
  if (rescanTimer !== undefined) clearInterval(rescanTimer);
  if (refreshTimer !== undefined) clearTimeout(refreshTimer);
});
</script>
<template>
  <div class="page-heading"><h1>课程作业</h1></div>
  <div v-if="error" class="alert error" role="alert">
    {{ error }} <button @click="load">重试</button>
  </div>
  <div v-if="loading" class="loading">正在读取作业…</div>
  <template v-else>
    <section class="student-task-strip" aria-label="我的待办">
      <RouterLink
        v-if="nextAssignment"
        class="task-tile"
        :to="`/student/courses/${courseId}/assignments/${nextAssignment.id}/items/${nextAssignment.remaining[0]!.id}`"
      >
        <FileText :size="20" aria-hidden="true" />
        <span
          ><strong>待作答 {{ pendingQuestions }} 题</strong
          ><span>{{ nextAssignment.title }}</span></span
        >
        <ArrowRight :size="18" aria-hidden="true" />
      </RouterLink>
      <div v-else class="task-tile">
        <FileText :size="20" aria-hidden="true" /><strong>{{
          progress ? "没有待作答的题目" : "作业进度暂不可用"
        }}</strong>
      </div>
      <RouterLink
        class="task-tile"
        :to="
          pendingReviews[0]
            ? `/student/courses/${courseId}/reviews/${pendingReviews[0].id}`
            : `/student/courses/${courseId}/reviews`
        "
      >
        <Clock :size="20" aria-hidden="true" />
        <span
          ><strong>{{
            reviewTasks ? `待互评 ${pendingReviews.length} 项` : "查看互评任务"
          }}</strong>
          <span v-if="pendingReviews[0]"
            >最早截止
            {{ formatDateTime(pendingReviews[0].review_deadline) }}</span
          >
        </span>
        <ArrowRight :size="18" aria-hidden="true" />
      </RouterLink>
    </section>
    <p v-if="polling.error.value" class="alert warning">
      {{ polling.error.value }}
    </p>
    <p v-if="!assignments.length && !error" class="empty">暂无已发布作业</p>
    <ul v-else class="student-card-list">
      <li v-for="assignment in assignmentCards" :key="assignment.id">
        <RouterLink
          class="student-record"
          :to="`/student/courses/${courseId}/assignments/${assignment.id}`"
        >
          <span class="record-main">
            <strong>{{ assignment.title }}</strong>
            <span class="record-deadline"
              >截止
              <time :datetime="assignment.submission_deadline">{{
                formatDateTime(assignment.submission_deadline)
              }}</time></span
            >
            <span v-if="assignment.open">{{
              remainingLabel(assignment.submission_deadline, now)
            }}</span>
          </span>
          <span class="record-outcome">
            <strong v-if="progress"
              >{{ assignment.submitted }} /
              {{ assignment.items.length }} 题已提交</strong
            >
            <span
              class="status-dot"
              :data-tone="
                !progress
                  ? 'gray'
                  : assignment.complete
                    ? 'green'
                    : assignment.open
                      ? 'amber'
                      : 'red'
              "
            >
              {{
                !progress
                  ? "进度未知"
                  : assignment.complete
                    ? "已交齐"
                    : assignment.open
                      ? `还差 ${assignment.remaining.length} 题`
                      : "已关闭 · 未交齐"
              }}
            </span>
          </span>
          <ArrowRight :size="18" aria-hidden="true" />
        </RouterLink>
      </li>
    </ul>
  </template>
</template>
