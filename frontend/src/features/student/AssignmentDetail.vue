<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { ArrowLeft, Clock } from "@lucide/vue";
import { errorText } from "../../shared/api";
import MarkdownPreview from "../../shared/MarkdownPreview.vue";
import * as api from "./api";
import { formatDateTime, remainingLabel } from "./format";
import type {
  AssignmentDetail,
  ProgressEntry,
  ProgressResponse,
} from "./types";

const route = useRoute();
const courseId = computed(() => String(route.params.courseId));
const assignmentId = computed(() => String(route.params.assignmentId));
const assignment = ref<AssignmentDetail | null>(null);
const progress = ref<ProgressResponse | null>(null);
const loading = ref(true);
const error = ref("");

const entries = computed(() => {
  const map = new Map<string, ProgressEntry>();
  for (const entry of progress.value?.items ?? [])
    map.set(entry.assignment_item_id, entry);
  return map;
});
const open = computed(() => {
  if (!assignment.value) return false;
  return (
    assignment.value.submission_status === "OPEN" &&
    new Date(assignment.value.submission_deadline) >
      new Date(assignment.value.server_time)
  );
});
const remaining = computed(() => {
  if (!assignment.value) return "";
  return remainingLabel(
    assignment.value.submission_deadline,
    assignment.value.server_time,
  );
});
function state(itemId: string) {
  const entry = entries.value.get(itemId);
  if (!entry?.has_submitted) return { label: "未提交", tone: "gray" };
  if (entry.failed_job_count) return { label: "评测故障", tone: "red" };
  if (entry.running_job_count || entry.pending_job_count)
    return { label: "评测中", tone: "amber" };
  if (entry.has_passed) return { label: "已通过", tone: "green" };
  if (entry.question_type !== "PROGRAMMING")
    return { label: "已提交", tone: "type" };
  return { label: "未通过", tone: "amber" };
}
function typeName(type: string) {
  return (
    {
      PROGRAMMING: "编程",
      ALGORITHM_ANALYSIS: "算法分析",
      PROOF: "证明",
      OPEN_QUESTION: "开放",
    }[type] || type
  );
}
async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [detail, report] = await Promise.all([
      api.getAssignment(assignmentId.value),
      api.myProgress(courseId.value, assignmentId.value),
    ]);
    assignment.value = detail;
    progress.value = report;
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loading.value = false;
  }
}
onMounted(load);
</script>
<template>
  <RouterLink :to="`/student/courses/${courseId}`" class="back-link">
    <ArrowLeft :size="15" />返回课程作业
  </RouterLink>
  <div v-if="error" class="alert error">
    {{ error }}<button @click="load">重试</button>
  </div>
  <div v-if="loading" class="loading">正在读取作业…</div>
  <template v-else-if="assignment">
    <div class="page-heading">
      <span class="eyebrow">ASSIGNMENT</span>
      <h1>{{ assignment.title }}</h1>
      <p class="muted">
        <Clock :size="14" />
        截止 {{ formatDateTime(assignment.submission_deadline) }} ·
        {{ remaining }} ·
        <span class="badge" :class="open ? 'green' : 'gray'">{{
          open ? "可提交" : "不可提交新版本"
        }}</span>
      </p>
    </div>
    <div v-if="assignment.description_md" class="card">
      <MarkdownPreview :source="assignment.description_md" />
    </div>
    <div v-if="!open" class="alert warning">
      作业已关闭或截止。已接收的提交仍会继续评测，历史版本可在「本人提交」中查看；如需再次提交请联系任课教师。
    </div>
    <ul class="item-list large">
      <li v-for="item in assignment.items" :key="item.id">
        <RouterLink
          :to="`/student/courses/${courseId}/assignments/${assignment.id}/items/${item.id}`"
          class="item-row"
        >
          <span class="item-index">{{
            (item.sort_order ?? 0).toString().padStart(2, "0")
          }}</span>
          <span class="item-main">
            <strong>{{ item.title }}</strong>
            <small>
              {{ typeName(item.question_type) }} · 满分 {{ item.max_score }}
              <template v-if="entries.get(item.id)">
                · 已提交 {{ entries.get(item.id)?.submission_count ?? 0 }} 次
              </template>
            </small>
          </span>
          <span class="badge" :class="state(item.id).tone">{{
            state(item.id).label
          }}</span>
        </RouterLink>
      </li>
    </ul>
  </template>
</template>
