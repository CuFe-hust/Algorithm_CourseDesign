<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { History } from "@lucide/vue";
import { errorText } from "../../shared/api";
import * as api from "./api";
import { formatDateTime } from "./format";
import type {
  AssignmentSummary,
  ComplexityResponse,
  HistoryEntry,
} from "./types";

const route = useRoute();
const courseId = computed(() => String(route.params.courseId));
const assignments = ref<AssignmentSummary[]>([]);
const entries = ref<HistoryEntry[]>([]);
const total = ref(0);
const limit = 20;
const offset = ref(0);
const assignmentId = ref("");
const language = ref("");
const status = ref("");
const loading = ref(true);
const error = ref("");

const items = computed(() => {
  const map = new Map<string, string>();
  for (const assignment of assignments.value)
    for (const item of assignment.items) map.set(item.id, item.title);
  return map;
});
const pages = computed(() => Math.max(1, Math.ceil(total.value / limit)));

/**
 * Complexity verdict per submission, fetched only for rows that are really
 * accepted. The list stays readable without it: a missing entry simply renders
 * no badge, it never guesses a class.
 */
const complexity = ref<Record<string, ComplexityResponse>>({});
const COMPLEXITY_BATCH = 8;

function analysable(entry: HistoryEntry) {
  const summary = entry.summary;
  return Boolean(
    entry.status === "SUBMITTED" &&
    summary &&
    summary.verdict === "ACCEPTED" &&
    !summary.is_mock &&
    summary.total_cases !== null &&
    summary.passed_cases === summary.total_cases,
  );
}

async function loadComplexity(entries: HistoryEntry[]) {
  const targets = entries
    .filter(analysable)
    .map((entry) => entry.submission_id);
  for (let index = 0; index < targets.length; index += COMPLEXITY_BATCH) {
    const chunk = targets.slice(index, index + COMPLEXITY_BATCH);
    const results = await Promise.all(
      chunk.map((id) =>
        api
          .getComplexity(id)
          .then((value) => [id, value] as const)
          .catch(() => null),
      ),
    );
    const next = { ...complexity.value };
    for (const row of results) if (row) next[row[0]] = row[1];
    complexity.value = next;
  }
}

/**
 * Short complexity hint for a history row.
 *
 * The backend omits ``report`` entirely while a report is PENDING/RUNNING and
 * writes an empty ``summary`` for INELIGIBLE, so the label is derived from the
 * response ``status`` first. Interpolating a missing class produced
 * "时间 undefined · 空间 undefined" in review.
 */
function complexityLabel(entry: HistoryEntry): string {
  const response = complexity.value[entry.submission_id];
  if (!response || response.status === "NONE") return "";
  if (response.status === "PENDING" || response.status === "RUNNING")
    return "分析中";
  if (response.status === "FAILED") return "分析失败";
  if (response.status === "INELIGIBLE") return "无法分析";
  const timeClass = response.report?.time?.class;
  const spaceClass = response.report?.space?.class;
  if (!timeClass || !spaceClass) {
    return response.status === "STATIC_ONLY" ? "仅结构分析" : "";
  }
  return `时间 ${timeClass} · 空间 ${spaceClass}`;
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const page = await api.mySubmissions({
      course_id: courseId.value,
      assignment_id: assignmentId.value || undefined,
      language: language.value || undefined,
      status: status.value || undefined,
      limit,
      offset: offset.value,
    });
    entries.value = page.items;
    total.value = page.total;
    void loadComplexity(page.items);
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loading.value = false;
  }
}

function verdict(entry: HistoryEntry) {
  if (entry.status === "WITHDRAWN") return { label: "已撤回", tone: "gray" };
  if (!entry.summary) {
    if (entry.job_status === "PENDING")
      return { label: "排队中", tone: "amber" };
    if (entry.job_status === "RUNNING")
      return { label: "评测中", tone: "amber" };
    if (entry.job_status === "FAILED")
      return { label: "服务故障", tone: "red" };
    return { label: "等待处理", tone: "gray" };
  }
  const map: Record<string, { label: string; tone: string }> = {
    ACCEPTED: { label: "通过", tone: "green" },
    WRONG_ANSWER: { label: "答案错误", tone: "red" },
    COMPILATION_ERROR: { label: "编译错误", tone: "amber" },
    TIME_LIMIT_EXCEEDED: { label: "超时", tone: "amber" },
    RUNTIME_ERROR: { label: "运行错误", tone: "red" },
    OUTPUT_LIMIT_EXCEEDED: { label: "输出超限", tone: "amber" },
    MOCK_ACCEPTED: { label: "模拟通过", tone: "gray" },
  };
  const base = map[entry.summary.verdict] || {
    label: entry.summary.verdict,
    tone: "gray",
  };
  return entry.summary.total_cases !== null
    ? {
        label: `${base.label} ${entry.summary.passed_cases ?? 0}/${entry.summary.total_cases}`,
        tone: base.tone,
      }
    : base;
}

watch([assignmentId, language, status], () => {
  offset.value = 0;
  void load();
});

onMounted(async () => {
  try {
    assignments.value = (await api.listAssignments(courseId.value)).items;
  } catch {
    /* the history list can still load without the assignment filter */
  }
  await load();
});
</script>
<template>
  <div class="page-heading">
    <span class="eyebrow">MY SUBMISSIONS</span>
    <h1>本人提交</h1>
    <p class="muted">列表只显示摘要；正文与编译诊断请进入版本详情查看。</p>
  </div>
  <div v-if="error" class="alert error">
    {{ error }}<button @click="load">重试</button>
  </div>
  <div class="toolbar">
    <select v-model="assignmentId" aria-label="按作业筛选">
      <option value="">全部作业</option>
      <option
        v-for="assignment in assignments"
        :key="assignment.id"
        :value="assignment.id"
      >
        {{ assignment.title }}
      </option>
    </select>
    <select v-model="language" aria-label="按语言筛选">
      <option value="">全部语言</option>
      <option value="python3">Python 3</option>
      <option value="cpp">C++</option>
      <option value="c">C</option>
      <option value="java">Java</option>
      <option value="subjective">主观题</option>
    </select>
    <select v-model="status" aria-label="按状态筛选">
      <option value="">全部状态</option>
      <option value="SUBMITTED">已提交</option>
      <option value="WITHDRAWN">已撤回</option>
    </select>
    <span class="toolbar-meta">共 {{ total }} 条</span>
  </div>
  <div v-if="loading" class="loading">正在读取提交历史…</div>
  <div v-else-if="!entries.length" class="empty">
    <History :size="28" />
    <h3>没有符合条件的提交</h3>
    <p>换一个筛选条件，或先完成一次作答。</p>
  </div>
  <div v-else class="card">
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>题目</th>
            <th>版本</th>
            <th>语言</th>
            <th>提交时间</th>
            <th>状态</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="entry in entries" :key="entry.submission_id">
            <td>
              <RouterLink
                class="table-title"
                :to="`/student/courses/${courseId}/submissions/${entry.submission_id}`"
              >
                {{ items.get(entry.assignment_item_id) || entry.title }}
              </RouterLink>
              <small class="secondary-line">{{ entry.assignment_title }}</small>
            </td>
            <td>v{{ entry.version_no }}</td>
            <td>{{ entry.language || "主观题" }}</td>
            <td class="nowrap">
              {{ formatDateTime(entry.submitted_at) }}
            </td>
            <td>
              <span class="badge" :class="verdict(entry).tone">{{
                verdict(entry).label
              }}</span>
              <small
                v-if="complexityLabel(entry)"
                class="secondary-line complexity-hint mono"
              >
                {{ complexityLabel(entry) }}
              </small>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="pagination">
      <span>第 {{ Math.floor(offset / limit) + 1 }} / {{ pages }} 页</span>
      <div>
        <button
          class="small"
          :disabled="offset === 0"
          @click="
            offset = Math.max(0, offset - limit);
            load();
          "
        >
          上一页
        </button>
        <button
          class="small"
          :disabled="offset + limit >= total"
          @click="
            offset += limit;
            load();
          "
        >
          下一页
        </button>
      </div>
    </div>
  </div>
</template>
