<script setup lang="ts">
import { ref, computed, onMounted, watch } from "vue";
import { useRoute } from "vue-router";
import { BarChart3, Layers, Info, FileSearch } from "@lucide/vue";
import { request, post, errorText, ApiError } from "../../shared/api";
import { session } from "../../shared/session";
import { confirmAction } from "../../shared/confirm";
import AbilityGeneration from "./AbilityGeneration.vue";
interface Row {
  student_id?: string;
  student_name?: string;
  assignment_item_id: string;
  title: string;
  question_type: string;
  max_score: string;
  submission_id: string | null;
  normalized_score: string | null;
  item_score: string | null;
  reason: string | null;
  source: null | { kind: string; version?: number; policy?: string };
}
interface Report {
  id: string;
  assignment_id: string;
  assignment_title: string;
  results_snapshot_version: string;
  created_at: string;
  role: string;
  is_mock: boolean;
  known_count: number;
  missing_count: number;
  total: number;
  limit: number;
  offset: number;
  rows: Row[];
  per_item: {
    id: string;
    title: string;
    known: number;
    missing: number;
    normalized_mean: string | null;
  }[];
  event_counts: Record<string, number>;
  model_status: Record<string, string>;
}
const route = useRoute();
const teacher = computed(() => route.path.startsWith("/teacher"));
const courseId = computed(() =>
  teacher.value ? session.courseId : String(route.params.courseId),
);
const assignments = ref<
    { id: string; title: string; submission_status: string }[]
  >([]),
  assignment = ref(""),
  report = ref<Report | null>(null),
  error = ref(""),
  busy = ref(false),
  reason = ref(""),
  notice = ref(""),
  offset = ref(0);
let pending: { signature: string; id: string } | null = null;
const reasonText: Record<string, string> = {
  NO_SUBMISSION: "未交作品",
  REVIEW_PENDING: "等待互评处理",
  MINIMUM_SAMPLES_NOT_MET: "有效评价不足",
  JUDGE_EVIDENCE_UNAVAILABLE: "缺少当前环境的真实评测证据",
  WEIGHTED_CASE_EVIDENCE_UNAVAILABLE: "缺少加权测试点计分依据",
};
const formatDate = (s: string) => new Date(s).toLocaleString();
async function load() {
  busy.value = true;
  error.value = "";
  try {
    const q = new URLSearchParams({
      limit: "20",
      offset: String(offset.value),
    });
    if (assignment.value) q.set("assignment_id", assignment.value);
    report.value = await request<Report>(
      `/analysis/courses/${courseId.value}/question-results/latest?${q}`,
    );
  } catch (e) {
    if (e instanceof ApiError && e.code === "QUESTION_RESULTS_REQUIRED")
      report.value = null;
    else error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
async function create() {
  if (!teacher.value || !assignment.value || busy.value) return;
  if (
    !(await confirmAction(
      "固定当前逐题候选、来源和版本？后续评分变化需另外生成新快照。",
    ))
  )
    return;
  busy.value = true;
  error.value = "";
  try {
    const body = {
      assignment_id: assignment.value,
      reason: reason.value.trim(),
    };
    const signature = JSON.stringify(body);
    if (!pending || pending.signature !== signature)
      pending = { signature, id: crypto.randomUUID() };
    await post<Report>(`/analysis/courses/${courseId.value}/question-results`, {
      ...body,
      request_id: pending.id,
    });
    pending = null;
    notice.value = "已固定新结果快照。缺失保留为空，原评价与旧快照均未改写。";
    reason.value = "";
    offset.value = 0;
    await load();
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
onMounted(async () => {
  try {
    assignments.value = (
      await request<{ items: typeof assignments.value }>(
        `/courses/${courseId.value}/assignments`,
      )
    ).items;
    await load();
  } catch (e) {
    error.value = errorText(e);
  }
});
watch(assignment, () => {
  offset.value = 0;
  notice.value = "";
  void load();
});
</script>
<template>
  <header class="page-heading">
    <div>
      <span class="eyebrow">{{
        teacher ? "QUESTION RESULTS" : "MY LEARNING"
      }}</span>
      <h1>{{ teacher ? "逐题结果与学习分析" : "我的学习报告" }}</h1>
      <p>
        {{
          teacher
            ? "将真实评测与复核后的主观结果汇合，按题目保留每一项来源。"
            : "查看本人逐题结果、数据覆盖和已记录的学习行为。"
        }}
      </p>
    </div>
    <button :disabled="busy" @click="load">刷新报告</button>
  </header>
  <p v-if="error" class="alert error" role="alert">{{ error }}</p>
  <p v-if="notice" class="alert success" role="status">{{ notice }}</p>
  <section class="card report-controls">
    <label
      >作业范围<select v-model="assignment">
        <option value="">最近的可访问结果</option>
        <option v-for="a in assignments" :key="a.id" :value="a.id">
          {{ a.title }}
        </option>
      </select></label
    ><template v-if="teacher"
      ><label
        >固定快照的理由<input
          v-model="reason"
          maxlength="2000"
          placeholder="说明本次范围及采用依据" /></label
      ><button
        class="primary"
        :disabled="busy || !assignment || !reason.trim()"
        @click="create"
      >
        <Layers :size="16" />固定当前逐题结果
      </button></template
    >
  </section>
  <section v-if="!report" class="card integration-empty">
    <FileSearch :size="42" />
    <h2>{{ busy ? "正在读取结果…" : "此范围还没有固定的逐题结果" }}</h2>
    <p>
      {{
        teacher
          ? "先完成提交截止和相应互评复核，再选择作业固定结果。缺评或缺少真实评测的题目会保留空值。"
          : "教师固定结果后，本页会显示你自己的题目表现；你仍可在提交记录查看实时评测和历史版本。"
      }}
    </p>
  </section>
  <template v-else
    ><div class="page-heading">
      <div>
        <h2>{{ report.assignment_title }}</h2>
        <p class="snapshot-version">
          固定于 {{ formatDate(report.created_at) }} ·
          {{ report.results_snapshot_version }}
        </p>
      </div>
      <span class="badge type">真实来源快照 · 逐题候选</span>
    </div>
    <section class="report-metrics">
      <article class="card report-metric">
        <span>可用题目样本</span><strong>{{ report.known_count }}</strong>
      </article>
      <article class="card report-metric">
        <span>缺失或待处理</span><strong>{{ report.missing_count }}</strong>
      </article>
      <article class="card report-metric">
        <span>已记录提交事件</span
        ><strong>{{ report.event_counts.SUBMITTED || 0 }}</strong>
      </article>
    </section>
    <section class="card">
      <div class="card-heading">
        <h2>
          <BarChart3 :size="17" />
          {{ teacher ? "各题结果概览" : "我的题目表现" }}
        </h2>
        <span class="small-label">按本题满分归一化</span>
      </div>
      <div class="report-chart">
        <div v-for="q in report.per_item" :key="q.id" class="result-bar">
          <span
            >{{ q.title
            }}<small class="report-source">
              · {{ q.known }} 可用 / {{ q.missing }} 缺失</small
            ></span
          >
          <div class="result-bar-track">
            <div
              v-if="q.normalized_mean !== null"
              class="result-bar-fill"
              :style="{ width: `${Number(q.normalized_mean) * 100}%` }"
            />
          </div>
          <strong>{{
            q.normalized_mean === null
              ? "暂无结果"
              : `${(Number(q.normalized_mean) * 100).toFixed(1)}%`
          }}</strong>
        </div>
      </div>
      <p class="result-note">
        {{
          teacher
            ? "图中为各题已知样本的均值，缺失不纳入计算；样本不足时不代表班级真实水平。"
            : "每道题独立展示，待处理为缺失，实际零分保持为零。"
        }}
        不计算作业总分。
      </p>
    </section>
    <section class="card">
      <div class="card-heading">
        <h2>逐题结果明细</h2>
        <span class="small-label">{{ report.total }} 个样本</span>
      </div>
      <div class="table-wrap">
        <table class="report-table">
          <thead>
            <tr>
              <th v-if="teacher">学生</th>
              <th>题目</th>
              <th>题目分 / 满分</th>
              <th>来源或待处理原因</th>
              <th>查看</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="(r, i) in report.rows"
              :key="`${r.assignment_item_id}-${r.student_id || i}`"
            >
              <td v-if="teacher">
                {{ r.student_name
                }}<small class="report-source"> · ID {{ r.student_id }}</small>
              </td>
              <td>{{ r.title }}</td>
              <td>
                <strong>{{ r.item_score ?? "—" }}</strong> / {{ r.max_score }}
              </td>
              <td>
                {{
                  r.item_score === null
                    ? reasonText[r.reason || ""] || r.reason || "数据待补齐"
                    : r.source?.kind === "REVIEW_ANALYSIS"
                      ? `主观复核 v${r.source.version}`
                      : "真实编程评测"
                }}<small v-if="r.source?.policy" class="report-source">
                  ·
                  {{
                    r.source.policy === "VERIFIED_UNIFORM_CASE_WEIGHTS"
                      ? "已验证等权测试点"
                      : r.source.policy === "ALL_CASES_ACCEPTED"
                        ? "全部测试点通过"
                        : ""
                  }}</small
                >
              </td>
              <td>
                <RouterLink
                  v-if="r.submission_id"
                  class="text-link"
                  :to="
                    teacher
                      ? `/teacher/students/${r.student_id}/progress`
                      : `/student/courses/${courseId}/submissions/${r.submission_id}`
                  "
                  >查看来源</RouterLink
                ><span v-else class="muted">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="pagination">
        <button
          :disabled="busy || offset === 0"
          @click="
            offset -= 20;
            load();
          "
        >
          上一页</button
        ><span
          >{{ offset + 1 }}–{{ Math.min(offset + 20, report.total) }} /
          {{ report.total }}</span
        ><button
          :disabled="busy || offset + 20 >= report.total"
          @click="
            offset += 20;
            load();
          "
        >
          下一页
        </button>
      </div>
    </section>
    <section class="card">
      <div class="card-heading">
        <h2>学习分析与数据边界</h2>
        <span class="badge amber">模型尚未全部接入</span>
      </div>
      <div class="model-pending">
        <Info :size="20" />
        <div>
          <h3>章节表现已接入，知识掌握与经验难度仍待完善</h3>
          <p>
            章节表现支持原始均值 B0 和难度感知
            D1，可从同一份课程快照生成。当前报告另提供逐题表现、覆盖情况和已记录的提交/撤回次数。不会从完成快慢推断学习态度或AI使用，也不以模拟结果补齐缺失。
          </p>
          <p>
            本范围提交 {{ report.event_counts.SUBMITTED || 0 }} 次，撤回
            {{ report.event_counts.WITHDRAWN || 0 }} 次。
          </p>
          <RouterLink
            v-if="!teacher"
            class="text-link"
            :to="`/student/courses/${courseId}/ability`"
            >查看个人章节表现 →</RouterLink
          >
        </div>
      </div>
    </section></template
  >
  <AbilityGeneration v-if="teacher" />
</template>
