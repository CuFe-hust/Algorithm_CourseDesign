<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ArrowLeft, RotateCcw, Undo2 } from "@lucide/vue";
import { errorText } from "../../shared/api";
import { renderCode } from "../../shared/markdown";
import * as api from "./api";
import JudgeFeedback from "./components/JudgeFeedback.vue";
import SubmissionStatus from "./components/SubmissionStatus.vue";
import ComplexityPanel from "./components/ComplexityPanel.vue";
import { newRequestKey } from "./composables/useSubmission";
import type { SubmissionDetail } from "./types";

const route = useRoute();
const router = useRouter();
const courseId = computed(() => String(route.params.courseId));
const submissionId = computed(() => String(route.params.submissionId));
const detail = ref<SubmissionDetail | null>(null);
const loading = ref(true);
const error = ref("");
const notice = ref("");
const busy = ref(false);

const code = computed(() =>
  detail.value?.language
    ? renderCode(detail.value.content, detail.value.language)
    : "",
);

/** Only a real full pass can be analysed; the backend re-checks this. */
const analysable = computed(
  () =>
    detail.value?.result?.verdict === "ACCEPTED" &&
    !detail.value.result.is_mock &&
    detail.value.result.total_cases !== null &&
    detail.value.result.passed_cases === detail.value.result.total_cases,
);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    detail.value = await api.getSubmission(submissionId.value);
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loading.value = false;
  }
}

async function withdraw() {
  if (!detail.value) return;
  busy.value = true;
  try {
    await api.withdrawSubmission(detail.value.submission_id);
    notice.value = "已撤回该版本，历史记录仍然保留。";
    detail.value = await api.getSubmission(detail.value.submission_id);
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}

async function rejudge() {
  if (!detail.value) return;
  busy.value = true;
  error.value = "";
  try {
    await api.rejudgeSubmission(detail.value.submission_id, newRequestKey());
    notice.value = "已接受重评请求，任务重新排队。";
    detail.value = await api.getSubmission(detail.value.submission_id);
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}

function loadIntoEditor() {
  if (!detail.value) return;
  void router.push({
    path: `/student/courses/${courseId.value}/assignments/${detail.value.assignment_id}/items/${detail.value.assignment_item_id}`,
    query: { load: detail.value.submission_id },
  });
}
function backToItem() {
  if (!detail.value) return;
  void router.push({
    path: `/student/courses/${courseId.value}/assignments/${detail.value.assignment_id}/items/${detail.value.assignment_item_id}`,
  });
}
onMounted(load);
</script>
<template>
  <RouterLink
    :to="`/student/courses/${courseId}/submissions`"
    class="back-link"
  >
    <ArrowLeft :size="15" />返回提交历史
  </RouterLink>
  <div v-if="error" class="alert error">{{ error }}</div>
  <div v-if="notice" class="alert success">{{ notice }}</div>
  <div v-if="loading" class="loading">正在读取版本…</div>
  <template v-else-if="detail">
    <div class="page-heading">
      <span class="eyebrow">VERSION</span>
      <h1>第 {{ detail.version_no }} 版</h1>
      <p class="muted">
        提交于 {{ new Date(detail.submitted_at).toLocaleString() }} ·
        {{ detail.language || "主观题" }} · 只读
      </p>
    </div>
    <section class="card">
      <div class="card-heading">
        <h2>提交状态</h2>
        <SubmissionStatus
          :status="detail.status"
          :phase="detail.job?.phase"
          :queue-reason="detail.job?.queue_reason"
        />
      </div>
      <dl class="meta-row">
        <div>
          <dt>任务</dt>
          <dd>{{ detail.job_status }}</dd>
        </div>
        <div>
          <dt>尝试次数</dt>
          <dd>{{ detail.job?.attempt_no ?? "—" }}</dd>
        </div>
        <div>
          <dt>恢复周期</dt>
          <dd>{{ detail.job?.recovery_cycle_no ?? 0 }}</dd>
        </div>
        <div>
          <dt>撤回时间</dt>
          <dd>
            {{
              detail.withdrawn_at
                ? new Date(detail.withdrawn_at).toLocaleString()
                : "—"
            }}
          </dd>
        </div>
      </dl>
      <div class="answer-actions">
        <button
          v-if="detail.status === 'SUBMITTED'"
          class="small"
          :disabled="busy || detail.job_status === 'RUNNING'"
          @click="withdraw"
        >
          <Undo2 :size="15" />撤回该版本
        </button>
        <button
          v-if="detail.job?.status === 'FAILED'"
          class="small"
          :disabled="busy || !detail.job.can_retry"
          @click="rejudge"
        >
          <RotateCcw :size="15" />申请重评
        </button>
        <button class="small" @click="loadIntoEditor">载入到编辑器</button>
        <button class="small" @click="backToItem">返回题目</button>
      </div>
      <p
        v-if="detail.job?.status === 'FAILED' && detail.job.retry_block_reason"
        class="muted"
      >
        当前不可重评：{{ detail.job.retry_block_reason }}
        <template v-if="detail.job.retry_after_at">
          （{{ new Date(detail.job.retry_after_at).toLocaleString() }}
          后可重试）
        </template>
      </p>
    </section>
    <section class="card">
      <div class="card-heading"><h2>提交内容</h2></div>
      <pre v-if="detail.language" class="mono code-block" v-html="code"></pre>
      <pre v-else class="mono code-block">{{ detail.content }}</pre>
    </section>
    <JudgeFeedback :result="detail.result" :job-status="detail.job_status" />
    <ComplexityPanel
      v-if="analysable"
      :submission-id="detail.submission_id"
      auto-load
    />
    <p v-else-if="detail.result && !detail.result.is_mock" class="hint">
      复杂度分析只对真实通过（全部测试点通过）的代码开放。
    </p>
  </template>
</template>
