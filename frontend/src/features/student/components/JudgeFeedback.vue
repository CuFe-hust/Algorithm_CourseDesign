<script setup lang="ts">
import { computed } from "vue";
import type { ResultSummary } from "../types";
const props = defineProps<{
  result: ResultSummary | null;
  jobStatus?: string;
}>();
const verdictLabels: Record<string, string> = {
  ACCEPTED: "通过",
  WRONG_ANSWER: "答案错误",
  COMPILATION_ERROR: "编译错误",
  TIME_LIMIT_EXCEEDED: "超时",
  MEMORY_LIMIT_EXCEEDED: "超出内存",
  RUNTIME_ERROR: "运行错误",
  OUTPUT_LIMIT_EXCEEDED: "输出超限",
  MOCK_ACCEPTED: "模拟通过（非真实评测）",
};
const tones: Record<string, string> = {
  ACCEPTED: "green",
  MOCK_ACCEPTED: "gray",
  WRONG_ANSWER: "red",
  COMPILATION_ERROR: "amber",
  TIME_LIMIT_EXCEEDED: "amber",
  MEMORY_LIMIT_EXCEEDED: "amber",
  RUNTIME_ERROR: "red",
  OUTPUT_LIMIT_EXCEEDED: "amber",
};
const modeLabel = computed(() => {
  if (!props.result) return "等待评测";
  const mode = props.result.execution_mode;
  if (props.result.is_mock || mode === "MOCK") return "模拟评测";
  if (mode === "LOCAL") return "本机真实执行";
  if (mode === "LINUX_SANDBOX") return "Linux 沙箱";
  return mode || "未标注";
});
const modeTone = computed(() => {
  if (!props.result) return "amber";
  if (props.result.is_mock) return "gray";
  return "type";
});
const measured = computed(
  () => props.result?.measurement_status === "MEASURED",
);
</script>
<template>
  <section class="card judge-feedback">
    <div class="card-heading">
      <h2>评测结果</h2>
      <span class="badge" :class="modeTone">{{ modeLabel }}</span>
    </div>
    <p v-if="!result" class="muted">
      {{
        jobStatus === "FAILED"
          ? "评测服务故障，还没有判定结果。"
          : "尚未生成评测结果。"
      }}
    </p>
    <template v-else>
      <div class="verdict-line">
        <span class="badge" :class="tones[result.verdict] || 'gray'">
          {{ verdictLabels[result.verdict] || result.verdict }}
        </span>
        <strong v-if="result.total_cases !== null">
          {{ result.passed_cases ?? 0 }} / {{ result.total_cases }} 个测试点通过
        </strong>
      </div>
      <dl class="meta-row">
        <div>
          <dt>运行环境</dt>
          <dd>{{ result.runtime_profile || "—" }}</dd>
        </div>
        <div>
          <dt>CPU 时间</dt>
          <dd>
            {{
              measured && result.cpu_time_ms !== null
                ? `${result.cpu_time_ms} ms`
                : "未测量"
            }}
          </dd>
        </div>
        <div>
          <dt>内存</dt>
          <dd>
            {{
              measured && result.memory_kib !== null
                ? `${result.memory_kib} KiB`
                : "未测量"
            }}
          </dd>
        </div>
        <div>
          <dt>执行测试点</dt>
          <dd>{{ result.executed_cases ?? 0 }}</dd>
        </div>
      </dl>
      <p v-if="result.message" class="muted">{{ result.message }}</p>
      <p v-if="result.is_mock" class="alert warning">
        这是模拟结果，不代表真实执行，也不会被计入已通过题数。
      </p>
      <details v-if="result.compiler_message" class="compiler-message" open>
        <summary>编译诊断（已截断并过滤宿主路径）</summary>
        <pre class="mono">{{ result.compiler_message }}</pre>
      </details>
      <p v-else-if="result.diagnostics_expired" class="muted">
        编译诊断已超过保留期并被清理，判定结果仍然有效。
      </p>
      <p v-if="result.verdict === 'COMPILATION_ERROR'" class="muted">
        编译失败不产生运行资源，也不代表设施故障。
      </p>
    </template>
  </section>
</template>
