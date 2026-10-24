<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { AlertTriangle, ArrowRight, Clock, FileText } from "@lucide/vue";
import { errorText } from "../../shared/api";
import { session } from "../../shared/session";
import * as api from "./api";
import SubmissionStatus from "./components/SubmissionStatus.vue";
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
const summary = computed(() => progress.value?.summary);
const unresolvedIds = computed(() =>
  (progress.value?.items ?? [])
    .filter((entry) => entry.has_unresolved_jobs && entry.latest_submission_id)
    .map((entry) => entry.latest_submission_id as string),
);

const polling = useJudgePolling({
  ids: () => unresolvedIds.value,
  onChange: () => void refresh(),
  onResync: () => void load(),
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
    if (unresolvedIds.value.length) polling.start();
    else polling.stop();
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loading.value = false;
  }
}
async function refresh() {
  try {
    progress.value = await api.myProgress(courseId.value);
    if (!unresolvedIds.value.length) polling.stop();
  } catch {
    /* keep the previous snapshot; the poller retries */
  }
}
function deadlineLabel(value: string) {
  const deadline = new Date(value);
  const now = new Date(progress.value?.as_of || Date.now());
  const hours = Math.round((deadline.getTime() - now.getTime()) / 3_600_000);
  if (hours < 0) return "已截止";
  if (hours < 48) return `剩余约 ${hours} 小时`;
  return `剩余约 ${Math.round(hours / 24)} 天`;
}
function itemState(itemId: string) {
  const entry = progressMap.value.get(itemId);
  if (!entry || !entry.has_submitted) return { label: "未提交", tone: "gray" };
  if (entry.failed_job_count) return { label: "评测故障", tone: "red" };
  if (entry.running_job_count) return { label: "评测中", tone: "amber" };
  if (entry.pending_job_count) return { label: "排队中", tone: "amber" };
  if (entry.has_passed) return { label: "已通过", tone: "green" };
  if (entry.question_type !== "PROGRAMMING")
    return { label: "已提交", tone: "type" };
  return { label: "未通过", tone: "amber" };
}
onMounted(load);
</script>
<template>
  <div class="page-heading">
    <span class="eyebrow">COURSE HOME</span>
    <h1>课程作业</h1>
    <p class="muted">选择作业进入题目；草稿保存在本机，提交后生成新版本。</p>
  </div>
  <div v-if="error" class="alert error">
    {{ error }}<button @click="load">重试</button>
  </div>
  <div v-if="loading" class="loading">正在读取作业…</div>
  <template v-else>
    <section v-if="summary" class="stats-grid">
      <div class="stat">
        <div><FileText :size="18" /></div>
        <strong
          >{{ summary.submitted_item_count }} / {{ summary.item_count }}</strong
        >
        <small>已提交题目</small>
      </div>
      <div class="stat">
        <div><ArrowRight :size="18" /></div>
        <strong
          >{{ summary.passed_programming_item_count }} /
          {{ summary.programming_item_count }}</strong
        >
        <small>编程题已真实通过</small>
      </div>
      <div class="stat">
        <div><Clock :size="18" /></div>
        <strong>{{
          summary.pending_job_count + summary.running_job_count
        }}</strong>
        <small>待处理评测任务</small>
      </div>
    </section>
    <p v-if="polling.error.value" class="alert warning">
      {{ polling.error.value }}
    </p>
    <div v-if="!assignments.length" class="empty">
      <FileText :size="28" />
      <h3>这门课程还没有已发布的作业</h3>
      <p>教师发布后刷新页面即可看到。</p>
    </div>
    <section
      v-for="assignment in assignments"
      :key="assignment.id"
      class="card assignment-card"
    >
      <div class="card-heading">
        <div>
          <h2>
            <RouterLink
              :to="`/student/courses/${courseId}/assignments/${assignment.id}`"
            >
              {{ assignment.title }}
            </RouterLink>
          </h2>
          <p class="muted">
            截止
            {{ new Date(assignment.submission_deadline).toLocaleString() }} ·
            {{ deadlineLabel(assignment.submission_deadline) }}
          </p>
        </div>
        <span
          class="badge"
          :class="assignment.submission_status === 'OPEN' ? 'green' : 'gray'"
        >
          {{ assignment.submission_status === "OPEN" ? "进行中" : "已关闭" }}
        </span>
      </div>
      <ul class="item-list">
        <li v-for="item in assignment.items" :key="item.id">
          <RouterLink
            :to="`/student/courses/${courseId}/assignments/${assignment.id}/items/${item.id}`"
          >
            <span>{{ item.title }}</span>
            <span class="badge" :class="itemState(item.id).tone">{{
              itemState(item.id).label
            }}</span>
          </RouterLink>
        </li>
      </ul>
    </section>
    <p v-if="summary && summary.failed_job_count" class="alert warning">
      <AlertTriangle :size="15" />
      有
      {{ summary.failed_job_count }}
      个任务因评测服务故障失败，可进入对应题目查看并申请重评。
    </p>
    <p class="muted small-note">
      已通过仅在当前评测环境（{{
        progress?.evaluation_context.execution_mode
      }}）内计算，模拟结果不计入。
    </p>
  </template>
</template>
