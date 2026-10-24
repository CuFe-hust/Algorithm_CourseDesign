<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { AlertTriangle, ArrowLeft, History, Send } from "@lucide/vue";
import { errorText } from "../../shared/api";
import { session } from "../../shared/session";
import { notifyActivity } from "../../shared/activity";
import * as api from "./api";
import ProblemStatement from "./components/ProblemStatement.vue";
import ProgrammingEditor from "./components/ProgrammingEditor.vue";
import SubjectiveEditor from "./components/SubjectiveEditor.vue";
import DraftStatus from "./components/DraftStatus.vue";
import JudgeFeedback from "./components/JudgeFeedback.vue";
import SubmissionStatus from "./components/SubmissionStatus.vue";
import { useDraft } from "./composables/useDraft";
import { useSubmission } from "./composables/useSubmission";
import { useJudgePolling } from "./composables/useJudgePolling";
import {
  SUBJECTIVE_LANGUAGE,
  draftStore,
  type DraftRecord,
} from "./draft-store";
import type { ItemDetail, SubmissionDetail } from "./types";

const route = useRoute();
const router = useRouter();
const courseId = computed(() => String(route.params.courseId));
const assignmentId = computed(() => String(route.params.assignmentId));
const itemId = computed(() => String(route.params.itemId));
const userId = computed(() => session.user?.id || "__anonymous__");

const item = ref<ItemDetail | null>(null);
const language = ref("");
const loading = ref(true);
const error = ref("");
const notice = ref("");
const detail = ref<SubmissionDetail | null>(null);
const versions = ref<
  {
    submission_id: string;
    version_no: number;
    submitted_at: string;
    status: string;
  }[]
>([]);
const restoredFrom = ref<string | null>(null);
const degraded = ref(false);
const dirty = ref(false);
const pendingLoad = ref<SubmissionDetail | null>(null);

const programming = computed(() => item.value?.question_type === "PROGRAMMING");
const draftContext = () => ({
  userId: userId.value,
  itemId: itemId.value,
  itemVersion: item.value?.problem_version_id || "",
});
const draft = useDraft(draftContext);
const submission = useSubmission(() => itemId.value);

const editorValue = computed({
  get: () => draft.content.value,
  set: (value: string) => {
    draft.setValue(value);
    dirty.value = true;
    notifyActivity();
  },
});

const polling = useJudgePolling({
  ids: () =>
    detail.value && ["PENDING", "RUNNING"].includes(detail.value.job_status)
      ? [detail.value.submission_id]
      : [],
  onChange: (entries) => {
    const entry = entries.find(
      (row) => row.submission_id === detail.value?.submission_id,
    );
    if (entry && detail.value) {
      detail.value = {
        ...detail.value,
        status: entry.status as SubmissionDetail["status"],
        job_status: entry.job?.status ?? entry.status,
        job: entry.job,
        result: entry.result,
      };
      if (!["PENDING", "RUNNING"].includes(entry.job?.status ?? entry.status))
        polling.stop();
    }
  },
  onResync: () => void refreshDetail(),
});

async function refreshDetail() {
  if (!detail.value) return;
  try {
    detail.value = await api.getSubmission(detail.value.submission_id);
    if (["PENDING", "RUNNING"].includes(detail.value.job_status))
      polling.start();
  } catch (e) {
    error.value = errorText(e);
  }
}

async function loadVersions() {
  const page = await api.mySubmissions({
    course_id: courseId.value,
    assignment_item_id: itemId.value,
    limit: 5,
  });
  versions.value = page.items.map((entry) => ({
    submission_id: entry.submission_id,
    version_no: entry.version_no,
    submitted_at: entry.submitted_at,
    status: entry.status,
  }));
}

async function adoptDraftLanguage(target: string) {
  await draft.flush();
  const record = await draft.load(target);
  language.value = target;
  dirty.value = false;
  if (!record) {
    const page = await api.mySubmissions({
      course_id: courseId.value,
      assignment_item_id: itemId.value,
      language: target === SUBJECTIVE_LANGUAGE ? undefined : target,
      limit: 1,
    });
    const latest = page.items[0];
    if (latest) {
      const source = await api.getSubmission(latest.submission_id);
      draft.apply(source.content);
      draft.status.value = "idle";
      restoredFrom.value = `第 ${source.version_no} 版提交`;
    } else {
      draft.apply("");
      restoredFrom.value = null;
    }
  } else {
    restoredFrom.value = record.lastSubmissionId ? "本机草稿" : null;
  }
}

async function initialLanguage(): Promise<string> {
  if (!item.value) return SUBJECTIVE_LANGUAGE;
  if (item.value.question_type !== "PROGRAMMING") return SUBJECTIVE_LANGUAGE;
  const allowed = item.value.allowed_languages.length
    ? item.value.allowed_languages
    : ["python3"];
  const store = await draftStore();
  const drafts = await store.listDrafts(userId.value, itemId.value);
  const remembered = drafts.find((record: DraftRecord) =>
    allowed.includes(record.language),
  );
  return remembered?.language || allowed[0]!;
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    item.value = await api.getItem(itemId.value);
    degraded.value = (await draftStore()).degraded;
    const target = await initialLanguage();
    await adoptDraftLanguage(target);
    await submission.loadPending(userId.value);
    await loadVersions();
    const loadId = String(route.query.load || "");
    if (loadId) {
      const source = await api.getSubmission(loadId);
      pendingLoad.value = source;
    }
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loading.value = false;
  }
}

async function switchLanguage(next: string) {
  if (next === language.value) return;
  await adoptDraftLanguage(next);
  notice.value = "";
}

async function submit() {
  error.value = "";
  notice.value = "";
  if (!item.value || !session.user) return;
  if (!draft.content.value.trim()) {
    error.value = "作答内容不能为空。";
    return;
  }
  await draft.flush();
  const receipt = await submission.submit({
    userId: session.user.id,
    content: draft.content.value,
    language: programming.value ? language.value : null,
    revision: draft.revision.value,
  });
  if (!receipt) {
    error.value = submission.error.value;
    return;
  }
  dirty.value = false;
  notice.value = `已接收第 ${receipt.version_no} 版，${receipt.job_status === "AWAITING_REVIEW" ? "等待后续处理" : "任务已排队"}。`;
  detail.value = await api.getSubmission(receipt.submission_id);
  await draft.flush();
  await loadVersions();
  if (["PENDING", "RUNNING"].includes(detail.value.job_status)) polling.start();
}

async function retryPending(clientRequestId: string) {
  const request = submission.pending.value.find(
    (row) => row.clientRequestId === clientRequestId,
  );
  if (!request) return;
  const receipt = await submission.retry(request);
  if (receipt) {
    notice.value = "原请求已确认，未生成重复版本。";
    detail.value = await api.getSubmission(receipt.submission_id);
    if (["PENDING", "RUNNING"].includes(detail.value.job_status))
      polling.start();
  } else {
    error.value = submission.error.value;
  }
}

async function confirmLoad() {
  if (!pendingLoad.value) return;
  if (programming.value && pendingLoad.value.language)
    language.value = pendingLoad.value.language;
  draft.apply(pendingLoad.value.content);
  await draft.flush();
  restoredFrom.value = `第 ${pendingLoad.value.version_no} 版提交`;
  pendingLoad.value = null;
  notice.value = "已载入所选版本，继续编辑会覆盖当前草稿。";
  await router.replace({ query: {} });
}

async function withdrawCurrent() {
  if (!detail.value) return;
  try {
    await api.withdrawSubmission(detail.value.submission_id);
    detail.value = await api.getSubmission(detail.value.submission_id);
    await loadVersions();
    notice.value = "已撤回该版本，历史仍保留。";
  } catch (e) {
    error.value = errorText(e);
  }
}

watch(
  () => route.query.load,
  async (value) => {
    if (!value) return;
    try {
      pendingLoad.value = await api.getSubmission(String(value));
    } catch (e) {
      error.value = errorText(e);
    }
  },
);

onMounted(load);
</script>
<template>
  <RouterLink
    :to="`/student/courses/${courseId}/assignments/${assignmentId}`"
    class="back-link"
  >
    <ArrowLeft :size="15" />返回作业
  </RouterLink>
  <div v-if="error" class="alert error">{{ error }}</div>
  <div v-if="notice" class="alert success">{{ notice }}</div>
  <div v-if="loading" class="loading">正在读取题目…</div>
  <div v-else-if="item" class="answer-layout">
    <div class="answer-main">
      <ProblemStatement :item="item" />
      <section v-if="pendingLoad" class="alert warning">
        即将载入第
        {{ pendingLoad.version_no }} 版内容。这会替换当前草稿，且不会自动提交。
        <button class="small" @click="confirmLoad">确认载入</button>
        <button class="small" @click="pendingLoad = null">取消</button>
      </section>
    </div>
    <div class="answer-side">
      <section class="card answer-card">
        <div class="card-heading">
          <h2>我的作答</h2>
          <span v-if="item.submission_open" class="badge green">可提交</span>
          <span v-else class="badge gray">不可提交</span>
        </div>
        <label v-if="programming && item.allowed_languages.length > 1">
          语言
          <select
            :value="language"
            @change="switchLanguage(($event.target as HTMLSelectElement).value)"
          >
            <option
              v-for="lang in item.allowed_languages"
              :key="lang"
              :value="lang"
            >
              {{ lang }}
            </option>
          </select>
        </label>
        <p v-else-if="programming" class="muted">
          本题仅允许 {{ item.allowed_languages.join("、") || "未配置语言" }}
        </p>
        <ProgrammingEditor
          v-if="programming"
          v-model="editorValue"
          :language="language"
          :readonly="!item.submission_open"
        />
        <SubjectiveEditor
          v-else
          v-model="editorValue"
          :readonly="!item.submission_open"
        />
        <DraftStatus
          :status="draft.status.value"
          :message="draft.message.value"
          :last-saved-at="draft.lastSavedAt.value"
          :degraded="degraded"
          :conflict="draft.conflict.value"
          @accept="draft.acceptConflict()"
          @dismiss="draft.dismissConflict()"
        />
        <p v-if="restoredFrom" class="muted">已恢复：{{ restoredFrom }}</p>
        <div class="answer-actions">
          <button
            class="primary"
            :disabled="submission.busy.value || !item.submission_open"
            @click="submit"
          >
            <Send :size="16" />{{
              submission.busy.value ? "正在提交…" : "提交新版本"
            }}
          </button>
          <span v-if="submission.receipt.value" class="badge type">
            已接收 v{{ submission.receipt.value.version_no }}
          </span>
          <span v-if="dirty && submission.receipt.value" class="badge amber"
            >有新修改未提交</span
          >
        </div>
        <p class="hint">
          提交后会生成新版本，旧代码保留。202
          只表示服务器已保存，不代表已经评测完成。
        </p>
      </section>

      <section v-if="submission.pending.value.length" class="card">
        <div class="card-heading"><h2>未确认的提交</h2></div>
        <p class="muted">
          上一次请求的结果未知，可用同一请求标识与相同内容重试，不会重复生成版本；修改内容需要新的提交。
        </p>
        <div
          v-for="request in submission.pending.value"
          :key="request.clientRequestId"
          class="pending-row"
        >
          <span class="mono">{{ request.clientRequestId.slice(0, 8) }}…</span>
          <span class="muted">{{
            new Date(request.createdAt).toLocaleString()
          }}</span>
          <button class="small" @click="retryPending(request.clientRequestId)">
            重试同一请求
          </button>
          <button class="small" @click="submission.discard(request)">
            放弃记录
          </button>
        </div>
      </section>

      <section v-if="detail" class="card">
        <div class="card-heading">
          <h2>第 {{ detail.version_no }} 版</h2>
          <SubmissionStatus
            :status="detail.status"
            :phase="detail.job?.phase"
            :queue-reason="detail.job?.queue_reason"
          />
        </div>
        <p class="muted">
          提交于 {{ new Date(detail.submitted_at).toLocaleString() }}
          <template v-if="detail.job">
            · 第 {{ detail.job.attempt_no }} 次尝试</template
          >
        </p>
        <div v-if="detail.job?.status === 'FAILED'" class="alert warning">
          <AlertTriangle :size="15" />
          评测服务故障：{{
            detail.job.message || detail.job.error_code || "未知原因"
          }}
          <button
            class="small"
            :disabled="!detail.job.can_retry"
            @click="refreshDetail"
          >
            刷新状态
          </button>
          <span v-if="detail.job.retry_block_reason" class="badge amber">{{
            detail.job.retry_block_reason
          }}</span>
        </div>
        <JudgeFeedback
          :result="detail.result"
          :job-status="detail.job_status"
        />
        <div class="answer-actions">
          <button
            v-if="
              detail.status === 'SUBMITTED' &&
              item.submission_open &&
              detail.job_status !== 'RUNNING'
            "
            class="small"
            @click="withdrawCurrent"
          >
            撤回该版本
          </button>
          <RouterLink
            class="button small"
            :to="`/student/courses/${courseId}/submissions/${detail.submission_id}`"
          >
            查看版本详情
          </RouterLink>
        </div>
      </section>

      <section class="card">
        <div class="card-heading">
          <h2><History :size="17" /> 最近版本</h2>
        </div>
        <ul v-if="versions.length" class="version-list">
          <li v-for="version in versions" :key="version.submission_id">
            <RouterLink
              :to="`/student/courses/${courseId}/submissions/${version.submission_id}`"
            >
              <span>v{{ version.version_no }}</span>
              <small>{{
                new Date(version.submitted_at).toLocaleString()
              }}</small>
              <span
                class="badge"
                :class="version.status === 'WITHDRAWN' ? 'gray' : 'type'"
              >
                {{ version.status === "WITHDRAWN" ? "已撤回" : "已提交" }}
              </span>
            </RouterLink>
          </li>
        </ul>
        <p v-else class="muted">还没有提交记录。</p>
      </section>
    </div>
  </div>
</template>
