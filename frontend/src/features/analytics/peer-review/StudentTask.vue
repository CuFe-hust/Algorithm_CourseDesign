<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from "vue";
import { useRoute, onBeforeRouteLeave } from "vue-router";
import { request, post, errorText } from "../../../shared/api";
import { confirmAction } from "../../../shared/confirm";
import MarkdownPreview from "../../../shared/MarkdownPreview.vue";
import { type TaskDetail } from "./types";
const route = useRoute(),
  task = ref<TaskDetail | null>(null),
  scores = ref<Record<string, string>>({}),
  comment = ref(""),
  error = ref(""),
  busy = ref(false),
  requestId = ref(crypto.randomUUID());
const dirty = computed(
  () =>
    !!task.value &&
    !task.value.evaluation &&
    (!!comment.value || Object.values(scores.value).some((v) => v !== "")),
);
async function load() {
  try {
    task.value = await request<TaskDetail>(
      `/peer-review/tasks/${route.params.taskId}`,
    );
    if (task.value.evaluation) {
      comment.value = task.value.evaluation.comment;
      scores.value = Object.fromEntries(
        task.value.evaluation.scores.map((s) => [
          String(s.rubric_item_id),
          s.score,
        ]),
      );
    } else
      scores.value = Object.fromEntries(
        task.value.rubric.map((d) => [d.id, ""]),
      );
  } catch (e) {
    error.value = errorText(e);
  }
}
function changed() {
  requestId.value = crypto.randomUUID();
}
async function submit() {
  if (!task.value || busy.value) return;
  error.value = "";
  for (const d of task.value.rubric) {
    const v = String(scores.value[d.id] ?? "");
    if (!/^\d+(\.\d{1,2})?$/.test(v) || Number(v) > Number(d.max_score)) {
      error.value = `请填写「${d.name}」0～${d.max_score} 范围内、最多两位小数的得分`;
      return;
    }
  }
  if (!comment.value.trim()) {
    error.value = "请写出具体的评审意见";
    return;
  }
  if (
    !(await confirmAction("确认提交本次评价？提交后原始分项分与评语不可修改。"))
  )
    return;
  busy.value = true;
  try {
    task.value = await post<TaskDetail>(
      `/peer-review/tasks/${task.value.id}/evaluation`,
      {
        client_request_id: requestId.value,
        scores: task.value.rubric.map((d) => ({
          rubric_item_id: d.id,
          score: String(scores.value[d.id]),
        })),
        comment: comment.value.trim(),
      },
    );
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
onBeforeRouteLeave(
  async () =>
    !dirty.value ||
    (await confirmAction("评分尚未提交，离开会丢失本页输入。确认离开？")),
);
const unload = (e: BeforeUnloadEvent) => {
  if (dirty.value) {
    e.preventDefault();
    e.returnValue = "";
  }
};
onMounted(() => {
  window.addEventListener("beforeunload", unload);
  void load();
});
onUnmounted(() => window.removeEventListener("beforeunload", unload));
</script>
<template>
  <section class="review-page">
    <RouterLink :to="`/student/courses/${route.params.courseId}/reviews`"
      >← 我的互评任务</RouterLink
    >
    <p v-if="task" class="muted">{{ task.assignment_title }}</p>
    <h1>{{ task?.question.title || "评审任务" }}</h1>
    <p v-if="error" role="alert" class="alert error">{{ error }}</p>
    <template v-if="task"
      ><div class="review-status">
        第 {{ task.round_no }} 轮 · 截止
        {{ new Date(task.review_deadline).toLocaleString() }}
        <p>
          {{
            task.evaluation
              ? "评价已提交，以下为原始记录。"
              : task.can_submit
                ? "已开始记录服务器评审时长，请认真阅读后提交。"
                : "此任务已截止或封存，无法继续提交。"
          }}
        </p>
      </div>
      <section class="card review-card">
        <h2>题目与作答要求</h2>
        <MarkdownPreview :source="task.question.statement_md" /><MarkdownPreview
          v-if="task.question.answer_requirements_md"
          :source="task.question.answer_requirements_md"
        />
      </section>
      <section class="card review-card">
        <h2>待评作品</h2>
        <div class="answer">
          <MarkdownPreview :source="task.answer_content" />
        </div>
      </section>
      <section class="card review-card">
        <h2>量表评分 · 满分 {{ task.rubric_max }}</h2>
        <form @submit.prevent="submit" @input="changed">
          <fieldset :disabled="busy || !!task.evaluation || !task.can_submit">
            <div v-for="d in task.rubric" :key="d.id" class="signal">
              <label :for="`dimension-${d.id}`"
                >{{ d.name }}（0～{{ d.max_score }} 分）</label
              >
              <p>{{ d.description }}</p>
              <input
                :id="`dimension-${d.id}`"
                v-model="scores[d.id]"
                type="number"
                min="0"
                :max="d.max_score"
                step="0.01"
                required
              />
            </div>
            <label
              >具体评审意见<textarea
                v-model="comment"
                rows="5"
                maxlength="8192"
                required
                placeholder="说明依据、指出不足，并给出可操作的改进建议。"
              />
            </label>
          </fieldset>
          <p v-if="task.evaluation">
            原始总分 {{ task.evaluation.total_score }} / {{ task.rubric_max }} ·
            服务器记录时长 {{ task.evaluation.elapsed_seconds }} 秒
          </p>
          <button
            v-else
            class="button primary"
            :disabled="busy || !task.can_submit"
          >
            {{ busy ? "提交中…" : "确认提交评价" }}
          </button>
        </form>
      </section></template
    >
  </section>
</template>
<style src="./review.css"></style>
