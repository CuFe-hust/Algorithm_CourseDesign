<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import { useRoute, onBeforeRouteLeave } from "vue-router";
import { request, post, errorText } from "../../../shared/api";
import { confirmAction } from "../../../shared/confirm";
import MarkdownPreview from "../../../shared/MarkdownPreview.vue";
import {
  type Round,
  type TeacherTask,
  type Page,
  type Decision,
  type TaskDetail,
  type Analysis,
  label,
  localDate,
} from "./types";
const route = useRoute(),
  r = ref<Round | null>(null),
  tasks = ref<TeacherTask[]>([]),
  taskTotal = ref(0),
  offset = ref(0),
  error = ref(""),
  busy = ref(false),
  reason = ref(""),
  deadline = ref(""),
  acceptMissing = ref(false),
  ack = ref<Record<string, boolean>>({}),
  decisions = ref<Decision[]>([]),
  supplement = ref(false),
  detail = ref<TaskDetail | null>(null),
  historical = ref<Analysis | null>(null);
const evaluationId = ref(""),
  answerKey = ref(""),
  action = ref<Decision["action"]>("KEEP"),
  weight = ref("0.5"),
  override = ref(""),
  decisionReason = ref("");
const detectors = computed(
  () =>
    r.value?.latest_analysis?.runs.filter((x) =>
      ["deviation", "reviewer_bias", "review_timing", "relationship"].includes(
        x.key,
      ),
    ) || [],
);
const canResolve = computed(
  () =>
    r.value?.latest_analysis?.kind === "INITIAL" &&
    !r.value.latest_analysis.resolved_at &&
    detectors.value.length === 4 &&
    detectors.value.every((x) => x.status === "SUCCEEDED" && ack.value[x.key]),
);
let stopped = false;
let timer: ReturnType<typeof setTimeout> | undefined;
let pending: { signature: string; id: string } | null = null;
async function load() {
  try {
    const [next, t] = await Promise.all([
      request<Round>(`/peer-review/teacher/rounds/${route.params.id}`),
      request<Page<TeacherTask>>(
        `/peer-review/teacher/rounds/${route.params.id}/tasks?limit=20&offset=${offset.value}`,
      ),
    ]);
    if (stopped) return;
    if (next.latest_analysis?.id !== r.value?.latest_analysis?.id) {
      ack.value = {};
      historical.value = null;
    }
    r.value = next;
    tasks.value = t.items;
    taskTotal.value = t.total;
    if (!deadline.value) deadline.value = localDate(next.review_deadline);
  } catch (e) {
    if (!stopped) error.value = errorText(e);
  }
}
function poll() {
  timer = setTimeout(async () => {
    if (
      r.value &&
      (r.value.allocation.status === "READY" ||
        r.value.allocation.status === "RUNNING" ||
        r.value.latest_analysis?.runs.some(
          (s) => s.status === "READY" || s.status === "RUNNING",
        ))
    )
      await load();
    if (!stopped) poll();
  }, 2500);
}
async function command(operation: string, extra: Record<string, unknown> = {}) {
  if (!r.value || busy.value) return;
  if (
    !(await confirmAction(
      operation === "publish"
        ? "确认按冻结映射向学生开放互评？"
        : operation === "resolve"
          ? "确认保存本次复核、理由和新版本结果？"
          : "确认执行此操作？",
    ))
  )
    return;
  busy.value = true;
  error.value = "";
  try {
    let path = `/peer-review/teacher/rounds/${r.value.id}/${operation}`;
    const body: Record<string, unknown> = {
      expected_revision: r.value.revision,
      ...extra,
    };
    if (operation === "publish")
      body.expected_source_hash = r.value.source_hash;
    else body.reason = reason.value;
    if (operation === "resolve") {
      const a = r.value.latest_analysis!;
      path = `/peer-review/teacher/analyses/${a.id}/resolve`;
      body.expected_revision = r.value.root_revision;
      body.expected_source_hash = a.source_hash;
      body.acknowledged_statuses = Object.fromEntries(
        detectors.value.map((x) => [x.key, x.business_status]),
      );
      body.decisions = decisions.value;
      body.request_supplement = supplement.value;
      if (supplement.value)
        body.supplement_deadline = new Date(deadline.value).toISOString();
    }
    const signature = JSON.stringify({ path, body });
    if (!pending || pending.signature !== signature)
      pending = { signature, id: crypto.randomUUID() };
    await post(path, { ...body, request_id: pending.id });
    pending = null;
    decisions.value = [];
    reason.value = "";
    ack.value = {};
    await load();
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
function addDecision() {
  error.value = "";
  const d: Decision = {
    action: action.value,
    reason: decisionReason.value.trim(),
  };
  if (!d.reason) {
    error.value = "请填写本条处置理由";
    return;
  }
  if (action.value === "OVERRIDE" || (!evaluationId.value && answerKey.value)) {
    d.answer_key = answerKey.value;
    if (!d.answer_key) {
      error.value = "请选择作品";
      return;
    }
  } else {
    if (!/^\d+$/.test(evaluationId.value)) {
      error.value = "请从评价表选择评价ID";
      return;
    }
    d.evaluation_id = evaluationId.value;
  }
  if (d.action === "DOWNWEIGHT") d.weight = weight.value;
  if (d.action === "OVERRIDE") d.override_score = override.value;
  const target = (x: Decision) =>
    x.evaluation_id ? `e${x.evaluation_id}` : `a${x.answer_key}`;
  decisions.value = decisions.value.filter((x) => target(x) !== target(d));
  decisions.value.push(d);
  decisionReason.value = "";
}
async function inspect(id: string) {
  try {
    detail.value = await request<TaskDetail>(
      `/peer-review/teacher/tasks/${id}`,
    );
  } catch (e) {
    error.value = errorText(e);
  }
}
async function history(id: string) {
  try {
    historical.value = await request<Analysis>(
      `/peer-review/teacher/analyses/${id}`,
    );
  } catch (e) {
    error.value = errorText(e);
  }
}
async function retry(batch: string, run: string) {
  busy.value = true;
  try {
    await post(`/analysis/batches/${batch}/runs/${run}/retry`, {
      request_id: crypto.randomUUID(),
    });
    await load();
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
const dirty = computed(
  () => decisions.value.length > 0 || reason.value.trim().length > 0,
);
onBeforeRouteLeave(
  async () =>
    !dirty.value || (await confirmAction("尚有未提交的复核内容，确认离开？")),
);
const unload = (e: BeforeUnloadEvent) => {
  if (dirty.value) {
    e.preventDefault();
    e.returnValue = "";
  }
};
onMounted(async () => {
  window.addEventListener("beforeunload", unload);
  await load();
  poll();
});
onUnmounted(() => {
  stopped = true;
  clearTimeout(timer);
  window.removeEventListener("beforeunload", unload);
});
</script>
<template>
  <section class="review-page">
    <RouterLink to="/teacher/reviews">← 互评轮次</RouterLink>
    <header class="page-heading">
      <div>
        <p class="eyebrow">链路 ③ / ④ · {{ r?.assignment_title }}</p>
        <h1>{{ r?.question.title || "互评详情" }}</h1>
      </div>
      <button class="button" :disabled="busy" @click="load">刷新</button>
    </header>
    <p v-if="error" role="alert" class="alert error">{{ error }}</p>
    <template v-if="r"
      ><section class="card review-card">
        <h2>第 {{ r.round_no }} 轮 · {{ label(r.status) }}</h2>
        <p>
          {{ r.answer_count }} 份待评作品 · {{ r.reviewer_count }} 位可用评审人
          · 已提交 {{ r.task_counts.SUBMITTED || 0 }} /
          {{ (r.task_counts.SUBMITTED || 0) + (r.task_counts.ASSIGNED || 0) }}
        </p>
        <p>
          截止：{{ new Date(r.review_deadline).toLocaleString() }} · 本题满分
          {{ r.item_max_score }}
        </p>
        <div class="review-actions">
          <RouterLink
            v-for="x in r.rounds"
            :key="x.id"
            :to="`/teacher/reviews/${x.id}`"
            >第{{ x.round_no }}轮（{{ label(x.status) }}）</RouterLink
          >
        </div>
        <details>
          <summary>冻结范围与量表</summary>
          <p>输入摘要：{{ r.source_hash }}</p>
          <pre>{{ JSON.stringify(r.rubric, null, 2) }}</pre>
        </details>
        <div v-if="r.status === 'PREVIEW'" class="review-status">
          <strong
            >分配：{{ label(r.allocation.status) }} ·
            {{ label(r.allocation.business_status) }}</strong
          >
          <p>确认前会重新校验输入摘要。不可行时不创建任何部分任务。</p>
          <details v-if="r.allocation.output">
            <summary>可行性与负载明细</summary>
            <pre>{{ JSON.stringify(r.allocation.output, null, 2) }}</pre>
          </details>
          <button
            class="button primary"
            :disabled="busy || r.allocation.business_status !== 'OK'"
            @click="command('publish')"
          >
            确认并开放互评
          </button>
        </div>
        <label
          >操作理由（取消、延长、封存或复核时必填）<textarea
            v-model="reason"
            maxlength="2000"
            rows="2"
          /></label
        ><label v-if="r.status === 'OPEN' || supplement"
          >新的互评截止（本地时间）<input
            v-model="deadline"
            type="datetime-local"
        /></label>
        <div class="review-actions">
          <button
            v-if="r.status === 'PREVIEW'"
            class="button"
            :disabled="busy || !reason.trim()"
            @click="command('cancel')"
          >
            取消此预览</button
          ><template v-if="r.status === 'OPEN'"
            ><button
              class="button"
              :disabled="busy || !reason.trim() || !deadline"
              @click="
                command('deadline', {
                  review_deadline: new Date(deadline).toISOString(),
                })
              "
            >
              延长截止</button
            ><label class="check"
              ><input
                v-model="acceptMissing"
                type="checkbox"
              />提前封存时明确接受未完成任务</label
            ><button
              class="button primary"
              :disabled="busy || !reason.trim()"
              @click="command('close', { accept_incomplete: acceptMissing })"
            >
              封存原始评价并分析
            </button></template
          >
        </div>
      </section>
      <section v-if="tasks.length" class="card review-card">
        <h2>原始任务与评价</h2>
        <p>教师查看不会启动学生评审计时。原始评价提交后只读。</p>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>任务 / 评价ID</th>
                <th>作品代号</th>
                <th>评审学生ID</th>
                <th>原分 / 秒</th>
                <th>查看</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in tasks" :key="t.task_id">
                <td>{{ t.task_id }} / {{ t.evaluation_id || "未提交" }}</td>
                <td>{{ t.answer_key.slice(-10) }}</td>
                <td>{{ t.reviewer_id }}</td>
                <td>
                  {{ t.total_score ?? "—" }} / {{ t.elapsed_seconds ?? "—" }}
                </td>
                <td>
                  <button class="button" @click="inspect(t.task_id)">
                    查看作品与评语</button
                  ><button
                    v-if="t.evaluation_id"
                    class="button"
                    @click="evaluationId = t.evaluation_id"
                  >
                    选择处置
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <div class="review-actions">
          <button
            class="button"
            :disabled="offset === 0"
            @click="
              offset -= 20;
              load();
            "
          >
            上一页</button
          ><span
            >{{ offset + 1 }}–{{ Math.min(offset + 20, taskTotal) }} /
            {{ taskTotal }}</span
          ><button
            class="button"
            :disabled="offset + 20 >= taskTotal"
            @click="
              offset += 20;
              load();
            "
          >
            下一页
          </button>
        </div>
        <div v-if="detail" class="answer">
          <button class="button" @click="detail = null">收起</button
          ><MarkdownPreview :source="detail.answer_content" />
          <p v-if="detail.evaluation">
            原始总分 {{ detail.evaluation.total_score }} /
            {{ detail.rubric_max }}
          </p>
          <p v-if="detail.evaluation">{{ detail.evaluation.comment }}</p>
          <pre v-if="detail.evaluation">{{
            JSON.stringify(detail.evaluation.scores, null, 2)
          }}</pre>
        </div>
      </section>
      <section v-if="r.latest_analysis" class="card review-card">
        <h2>
          分析 v{{ r.latest_analysis.version }} ·
          {{ label(r.latest_analysis.kind) }}
        </h2>
        <p>异常信号只提供复核线索，不会自动扣分；证据不足也需要显式确认。</p>
        <div v-for="run in r.latest_analysis.runs" :key="run.id" class="signal">
          <strong
            >{{ label(run.key) }} · {{ label(run.status) }} ·
            {{ label(run.business_status) }}</strong
          ><small class="muted">
            · {{ run.implementation }} v{{ run.implementation_version }}</small
          >
          <p v-for="note in run.limitations" :key="note" class="muted">
            {{ note }}
          </p>
          <details v-if="run.output">
            <summary>证据与样本覆盖</summary>
            <pre>{{ JSON.stringify(run.output, null, 2) }}</pre>
          </details>
          <label
            v-if="
              detectors.some((d) => d.id === run.id) &&
              !r.latest_analysis.resolved_at
            "
            class="check"
            ><input
              v-model="ack[run.key]"
              type="checkbox"
              :disabled="run.status !== 'SUCCEEDED'"
            />已查看并确认 {{ label(run.key) }} 的实际证据状态</label
          ><button
            v-if="run.status === 'FAILED'"
            class="button"
            :disabled="busy"
            @click="retry(r.latest_analysis.batch_id, run.id)"
          >
            显式重试
          </button>
        </div>
        <template
          v-if="
            r.latest_analysis.kind === 'INITIAL' &&
            !r.latest_analysis.resolved_at
          "
          ><h3>添加处置</h3>
          <div class="review-grid">
            <label
              >操作<select v-model="action">
                <option value="KEEP">保留 / 恢复原权重或清除作品改分</option>
                <option value="DOWNWEIGHT">降权</option>
                <option value="INVALIDATE">作废</option>
                <option value="OVERRIDE">教师按本题满分改分</option>
              </select></label
            ><label v-if="action !== 'OVERRIDE'"
              >评价ID（留空时保留作品）<input
                v-model="evaluationId"
                inputmode="numeric" /></label
            ><label
              >作品（改分 / 清除改分时选择）<select v-model="answerKey">
                <option value="">选择作品</option>
                <option
                  v-for="s in r.candidates.rows.filter((s) => s.answer_key)"
                  :key="s.student_id"
                  :value="s.answer_key!"
                >
                  学生ID {{ s.student_id }} · {{ s.answer_key?.slice(-10) }}
                </option>
              </select></label
            ><label v-if="action === 'DOWNWEIGHT'"
              >新权重（绝对值，0～1）<input
                v-model="weight"
                type="number"
                min="0.000001"
                max="1"
                step="0.000001" /></label
            ><label v-if="action === 'OVERRIDE'"
              >本题得分（满分 {{ r.item_max_score }}）<input
                v-model="override"
                type="number"
                min="0"
                :max="r.item_max_score"
                step="0.01"
            /></label>
          </div>
          <label
            >本条处置理由<input
              v-model="decisionReason"
              maxlength="2000" /></label
          ><button class="button" :disabled="busy" @click="addDecision">
            加入待提交处置
          </button>
          <ul>
            <li v-for="(d, i) in decisions" :key="i">
              {{ d.action }} ·
              {{ d.evaluation_id || d.answer_key?.slice(-10) }} · {{ d.reason }}
              <button class="button" @click="decisions.splice(i, 1)">
                移除
              </button>
            </li>
          </ul>
          <label class="check"
            ><input
              v-model="supplement"
              type="checkbox"
            />本次处置后发起补评（排除作者及已分配评审人）</label
          >
          <p>
            未添加处置即保留全部现有权重；仍须填写本次复核理由并确认四类状态。
          </p>
          <button
            class="button primary"
            :disabled="
              busy || !canResolve || !reason.trim() || (supplement && !deadline)
            "
            @click="command('resolve')"
          >
            提交复核并{{ supplement ? "生成补评预览" : "新建重算版本" }}
          </button></template
        ><button
          v-else-if="r.status === 'CLOSED'"
          class="button"
          :disabled="busy || !reason.trim()"
          @click="command('analyses')"
        >
          按当前原始数据新建分析版本
        </button>
      </section>
      <section class="card review-card">
        <h2>本题候选结果 · {{ label(r.candidates.status) }}</h2>
        <p>
          缺评、未交、待复核保留为空；本页结果供第⑤条链路读取，发布由后续业务完成。
        </p>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>学生ID</th>
                <th>有效评价数</th>
                <th>候选题目分</th>
                <th>来源 / 原因</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in r.candidates.rows" :key="s.student_id">
                <td>{{ s.student_id }}</td>
                <td>{{ s.valid_count }}</td>
                <td>{{ s.item_score ?? "—" }}</td>
                <td>{{ label(s.source_type || s.reason) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <details>
          <summary>历史版本（只读）</summary>
          <div class="review-actions">
            <button
              v-for="a in r.analyses"
              :key="a.id"
              class="button"
              @click="history(a.id)"
            >
              v{{ a.version }} {{ label(a.kind) }}
            </button>
          </div>
          <pre v-if="historical">{{ JSON.stringify(historical, null, 2) }}</pre>
        </details>
      </section></template
    >
  </section>
</template>
<style src="./review.css"></style>
