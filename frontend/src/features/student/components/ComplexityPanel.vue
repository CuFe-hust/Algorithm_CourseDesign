<script setup lang="ts">
/**
 * Complexity panel shown for an accepted submission.
 *
 * The panel is explicit about what it knows and what it only estimates: the
 * class, the source (measured growth or code structure), the confidence, the
 * structural evidence with line numbers, and the measurement's limitations.
 * A student must never read this panel as a proof or as a grade.
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import {
  Activity,
  AlertTriangle,
  Gauge,
  RefreshCw,
  Sparkles,
} from "@lucide/vue";
import { errorText } from "../../../shared/api";
import * as api from "../api";
import GrowthChart from "./GrowthChart.vue";
import type { ComplexityReport, ComplexityResponse } from "../types";

const props = defineProps<{ submissionId: string; autoLoad?: boolean }>();

const response = ref<ComplexityResponse | null>(null);
const loading = ref(false);
const requesting = ref(false);
const error = ref("");
let timer: ReturnType<typeof setTimeout> | undefined;

const report = computed<ComplexityReport | null>(
  () => response.value?.report ?? null,
);
const busy = computed(
  () =>
    response.value?.status === "PENDING" ||
    response.value?.status === "RUNNING",
);

const confidenceText: Record<string, string> = {
  HIGH: "高",
  MEDIUM: "中",
  LOW: "低",
};
const confidenceTone: Record<string, string> = {
  HIGH: "green",
  MEDIUM: "amber",
  LOW: "gray",
};
const sourceText: Record<string, string> = {
  DYNAMIC: "实测增长",
  STATIC: "代码结构",
};

function schedule(delay = 1500) {
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => void load(), delay);
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    response.value = await api.getComplexity(props.submissionId);
    if (busy.value) schedule();
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loading.value = false;
  }
}

async function request() {
  requesting.value = true;
  error.value = "";
  try {
    await api.requestComplexity(props.submissionId);
    await load();
    if (busy.value) schedule(1200);
  } catch (e) {
    error.value = errorText(e);
  } finally {
    requesting.value = false;
  }
}

const evidence = computed(() =>
  (report.value?.static?.evidence ?? []).filter(
    (row) => row.kind !== "LEXICAL_ONLY",
  ),
);

onMounted(async () => {
  await load();
  if ((props.autoLoad ?? false) && !response.value?.report && !busy.value) {
    await request();
  }
});

onBeforeUnmount(() => {
  if (timer) clearTimeout(timer);
});
</script>

<template>
  <section class="card complexity-panel">
    <div class="card-heading">
      <h2><Activity :size="17" /> 复杂度分析</h2>
      <span v-if="report" class="badge" :class="busy ? 'amber' : 'type'">
        {{
          busy
            ? "分析中"
            : report.status === "STATIC_ONLY"
              ? "仅结构分析"
              : "已完成"
        }}
      </span>
    </div>

    <div v-if="error" class="alert error">{{ error }}</div>

    <p v-if="loading && !response" class="loading">正在读取复杂度报告…</p>
    <p v-else-if="busy" class="loading">
      正在测量运行时间，通常需要几秒到一分钟。
    </p>

    <template v-else-if="!report">
      <p class="muted">
        这段代码已经真实通过。可以让平台测一下它随输入规模的增长速度，画出增长曲线，并给出时间、空间复杂度的估计。
      </p>
      <p class="hint">
        分析只读取你自己的代码，不会改动提交和评测结果。结论是估计值，不是形式化证明。
      </p>
      <button class="primary" :disabled="requesting" @click="request">
        <Sparkles :size="16" />{{
          requesting ? "正在提交分析…" : "分析这段代码的复杂度"
        }}
      </button>
    </template>

    <template v-else>
      <div v-if="report.status === 'INELIGIBLE'" class="alert warning">
        <AlertTriangle :size="15" />{{ report.error }}
      </div>
      <div v-else-if="report.status === 'FAILED'" class="alert error">
        <AlertTriangle :size="15" />分析失败：{{ report.error }}
        <button class="small" @click="request">
          <RefreshCw :size="14" />重试
        </button>
      </div>
      <template v-else>
        <div class="complexity-badges">
          <div class="complexity-badge">
            <span class="small-label"><Gauge :size="13" /> 时间</span>
            <strong class="mono">{{ report.time.class }}</strong>
            <span
              class="badge"
              :class="confidenceTone[report.time.confidence] || 'gray'"
            >
              置信度
              {{
                confidenceText[report.time.confidence] || report.time.confidence
              }}
            </span>
            <small class="muted"
              >依据：{{
                sourceText[report.time.source] || report.time.source
              }}</small
            >
          </div>
          <div class="complexity-badge">
            <span class="small-label"><Gauge :size="13" /> 空间</span>
            <strong class="mono">{{ report.space.class }}</strong>
            <span
              class="badge"
              :class="confidenceTone[report.space.confidence] || 'gray'"
            >
              置信度
              {{
                confidenceText[report.space.confidence] ||
                report.space.confidence
              }}
            </span>
            <small class="muted"
              >依据：{{
                sourceText[report.space.source] || report.space.source
              }}</small
            >
          </div>
        </div>

        <p v-if="report.time.agreement === false" class="alert warning">
          <AlertTriangle :size="15" />
          代码结构看是 {{ report.time.static_class }}，实测增长是
          {{
            report.time.measured_class
          }}，两者不一致。报告按规则取舍，并把两者都保留下来。
        </p>

        <GrowthChart :dynamic="report.dynamic" />

        <details class="complexity-details" open>
          <summary>结构证据（代码结构给出的依据）</summary>
          <ul v-if="evidence.length">
            <li v-for="row in evidence" :key="`${row.line}-${row.kind}`">
              <span v-if="row.line" class="mono line-chip"
                >第 {{ row.line }} 行</span
              >
              {{ row.reason }}
            </li>
          </ul>
          <p v-else class="muted">结构分析没有发现会改变复杂度的构造。</p>
          <p v-if="report.static.recursive" class="muted">
            递归形态：{{ report.static.recursion_kind }}；循环嵌套
            {{ report.static.loop_depth }} 层。
          </p>
        </details>

        <details
          v-if="report.dynamic?.rungs?.length"
          class="complexity-details"
        >
          <summary>每档实测数据</summary>
          <div class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>输入规模 n</th>
                  <th>运行时间</th>
                  <th>纯读取输入</th>
                  <th>峰值内存</th>
                  <th>状态</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="rung in report.dynamic.rungs" :key="rung.n">
                  <td class="mono">{{ rung.n }}</td>
                  <td class="mono">{{ rung.wall_ms.toFixed(1) }} ms</td>
                  <td class="mono">
                    {{
                      rung.reference_ms != null
                        ? `${rung.reference_ms.toFixed(1)} ms`
                        : "—"
                    }}
                  </td>
                  <td class="mono">
                    {{
                      rung.peak_rss_kib != null
                        ? `${Math.round(rung.peak_rss_kib / 1024)} MiB`
                        : "—"
                    }}
                  </td>
                  <td>{{ rung.verdict }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </details>

        <details class="complexity-details">
          <summary>这份结论的适用范围</summary>
          <ul class="limitations">
            <li v-for="text in report.limitations" :key="text">{{ text }}</li>
          </ul>
          <p class="hint">
            复杂度分析不参与评分，也不改变评测结果。实现版本
            {{ report.implementation_name }} v{{
              report.implementation_version
            }}。
          </p>
        </details>

        <button class="small" :disabled="requesting" @click="request">
          <RefreshCw :size="14" />重新分析
        </button>
      </template>
    </template>
  </section>
</template>
