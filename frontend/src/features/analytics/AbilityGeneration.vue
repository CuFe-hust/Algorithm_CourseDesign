<script setup lang="ts">
import { onMounted, ref } from "vue";
import { ChartNoAxesCombined, RefreshCw } from "@lucide/vue";
import { request, post, errorText } from "../../shared/api";
import { confirmAction } from "../../shared/confirm";
import { session } from "../../shared/session";

interface ModelStatus {
  model: string;
  id: string | null;
  status: string;
  business_status: string | null;
}
const models = ref<ModelStatus[]>([]);
const busy = ref(false),
  reason = ref(""),
  error = ref(""),
  notice = ref("");
let pending: {
  signature: string;
  courseRequest: string;
  b0: string;
  d1: string;
} | null = null;
const labels: Record<string, string> = {
  NOT_GENERATED: "尚未生成",
  READY: "排队中",
  RUNNING: "计算中",
  WAITING_INPUT: "等待有效输入",
  SUCCEEDED: "已完成",
  FAILED: "计算失败",
  INSUFFICIENT_DATA: "有效证据不足",
};
async function load() {
  try {
    const result = await request<{ models: ModelStatus[] }>(
      `/analysis/courses/${session.courseId}/student-ability/status`,
    );
    models.value = result.models || [];
  } catch (e) {
    error.value = errorText(e);
  }
}
async function generate() {
  if (busy.value || !reason.value.trim()) return;
  if (
    !(await confirmAction(
      "采用每次作业最新的已固定结果，生成课程快照及 B0、D1 两份章节分析？未固定的作业不会纳入。",
    ))
  )
    return;
  busy.value = true;
  error.value = "";
  notice.value = "";
  try {
    const signature = JSON.stringify({
      course: session.courseId,
      reason: reason.value.trim(),
    });
    if (!pending || pending.signature !== signature)
      pending = {
        signature,
        courseRequest: crypto.randomUUID(),
        b0: crypto.randomUUID(),
        d1: crypto.randomUUID(),
      };
    const source = await post<{
      id: string;
      source_count: number;
      known_count: number;
      total: number;
    }>(`/analysis/courses/${session.courseId}/course-results`, {
      request_id: pending.courseRequest,
      reason: reason.value.trim(),
    });
    for (const model of ["b0", "d1"] as const) {
      await post(
        `/analysis/courses/${session.courseId}/student-ability/${model === "b0" ? "b0" : "difficulty"}-batches`,
        {
          request_id: pending[model],
          mode: "REAL_INPUT",
          seed: 20261030,
          source_batch_id: source.id,
        },
      );
    }
    notice.value = `已提交 B0 与 D1 分析：包含 ${source.source_count} 次已固定作业，${source.known_count} / ${source.total} 个有效评分样本。计算完成后，学生可在“个人章节表现”查看本人结果。`;
    pending = null;
    reason.value = "";
    await load();
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
onMounted(load);
</script>

<template>
  <section class="card chapter-generation">
    <div class="card-heading">
      <h2><ChartNoAxesCombined :size="20" />课程章节分析</h2>
      <button class="small" :disabled="busy" @click="load">
        <RefreshCw :size="14" />刷新状态
      </button>
    </div>
    <div class="chapter-body">
      <p class="result-note">
        将每次作业最新的逐题快照汇合，生成原始表现 B0 与难度感知模型
        D1。仅采用已固定的真实评分，缺失保持为空；学生只能查看本人章节结果。
      </p>
      <div class="chapter-models">
        <article v-for="m in models" :key="m.model">
          <strong>{{
            m.model === "b0" ? "原始表现 B0" : "难度感知 D1"
          }}</strong>
          <span
            >{{
              labels[
                m.business_status === "INSUFFICIENT_DATA"
                  ? m.business_status
                  : m.status
              ] || m.status
            }}<small v-if="m.id"> · 批次 #{{ m.id }}</small></span
          >
        </article>
      </div>
      <form class="chapter-form" @submit.prevent="generate">
        <label
          >生成理由<input
            v-model="reason"
            maxlength="2000"
            placeholder="例如：本轮互评复核完成，更新课程章节表现"
        /></label>
        <button class="primary" :disabled="busy || !reason.trim()">
          {{ busy ? "正在固定与提交…" : "生成课程章节分析" }}
        </button>
      </form>
      <p v-if="error" class="alert error" role="alert">{{ error }}</p>
      <p v-if="notice" class="alert success" role="status">{{ notice }}</p>
      <p class="hint">
        新增评分或补评后，先重新固定对应作业的逐题结果，再生成新分析。B0
        是已评分题的章节均值，D1
        是模型参考表现；二者都不是作业总分或知识掌握概率。
      </p>
    </div>
  </section>
</template>

<style scoped>
.chapter-body {
  padding: 22px 24px;
}
.chapter-body > .result-note {
  padding: 0;
  margin: 0;
}
.chapter-body > .hint {
  margin-bottom: 0;
}
.card-heading h2 {
  display: flex;
  align-items: center;
  gap: 8px;
}
.chapter-models {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin: 20px 0;
}
.chapter-models article {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 18px;
  background: #f7f9fd;
  border: 1px solid #e5eaf3;
  border-radius: 12px;
}
.chapter-models span {
  color: #5c6d83;
  font-size: 14px;
}
.chapter-form {
  display: flex;
  align-items: end;
  gap: 16px;
  margin: 20px 0;
}
.chapter-form label {
  flex: 1;
  margin: 0;
}
.chapter-form input {
  width: 100%;
}
@media (max-width: 700px) {
  .chapter-models {
    grid-template-columns: 1fr;
  }
  .chapter-form {
    align-items: stretch;
    flex-direction: column;
  }
}
</style>
