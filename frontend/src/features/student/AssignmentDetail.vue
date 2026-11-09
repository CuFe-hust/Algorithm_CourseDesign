<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { ArrowLeft, ArrowRight } from "@lucide/vue";
import { errorText } from "../../shared/api";
import MarkdownPreview from "../../shared/MarkdownPreview.vue";
import * as api from "./api";
import { formatDateTime } from "./format";
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
const scores = ref<Record<string, string | null>>({});
const submitted = computed(
  () =>
    assignment.value?.items.filter(
      (item) => entries.value.get(item.id)?.has_submitted,
    ).length ?? 0,
);
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
    void api
      .fixedScores(courseId.value, assignmentId.value)
      .then((value) => {
        scores.value = value;
      })
      .catch(() => {});
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
      <h1>{{ assignment.title }}</h1>
    </div>
    <section class="student-task-strip" aria-label="作业进度">
      <div class="task-tile">
        <span
          ><strong
            >{{ submitted }} / {{ assignment.items.length }} 题已提交</strong
          >
          <span>{{
            submitted === assignment.items.length
              ? "已交齐"
              : `还差 ${assignment.items.length - submitted} 题`
          }}</span>
        </span>
      </div>
      <div class="task-tile">
        <span
          ><strong
            >截止 {{ formatDateTime(assignment.submission_deadline) }}</strong
          >
          <span class="status-dot" :data-tone="open ? 'green' : 'gray'">{{
            open ? "可提交" : "提交已关闭"
          }}</span>
        </span>
      </div>
    </section>
    <div v-if="assignment.description_md" class="card">
      <MarkdownPreview :source="assignment.description_md" />
    </div>
    <ul class="student-card-list">
      <li v-for="item in assignment.items" :key="item.id">
        <RouterLink
          class="student-record"
          :to="`/student/courses/${courseId}/assignments/${assignment.id}/items/${item.id}`"
        >
          <span class="record-main"
            ><strong>{{ item.title }}</strong
            ><span>{{ typeName(item.question_type) }}</span></span
          >
          <span class="record-outcome">
            <strong class="record-score"
              >{{ scores[item.id] ?? "—" }} / {{ item.max_score }} 分</strong
            >
            <span class="status-dot" :data-tone="state(item.id).tone">{{
              state(item.id).label
            }}</span>
          </span>
          <ArrowRight :size="18" aria-hidden="true" />
        </RouterLink>
      </li>
    </ul>
  </template>
</template>
