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
// A measurement may legitimately run for 150 s, so poll at 1.5 s intervals but
// only this many times. Review measured 401 requests in ten minutes without a
// cap, and requests kept firing after the component was gone.
const MAX_POLLS = 45;
const POLL_MS = 1500;
let polls = 0;
let sequence = 0;
let unmounted = false;

const report = computed<ComplexityReport | null>(
  () => response.value?.report ?? null,
);
const busy = computed(
  () =>
    response.value?.status === "PENDING" ||
    response.value?.status === "RUNNING",
);
/** True once automatic refresh gave up; the panel says so instead of spinning. */
const stopping = ref(false);

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

function schedule(delay = POLL_MS) {
  if (unmounted) return;
  if (polls >= MAX_POLLS) {
    stopping.value = true;
    return;
  }
  polls += 1;
  if (timer) clearTimeout(timer);
  timer = setTimeout(() => void load(), delay);
}

async function load() {
  const token = ++sequence;
  loading.value = true;
  error.value = "";
  try {
    const value = await api.getComplexity(props.submissionId);
    // A late response from an earlier request, or from a component that has been
    // torn down, must not overwrite state nor start another timer.
    if (unmounted || token !== sequence) return;
    response.value = value;
    if (busy.value) schedule();
  } catch (e) {
    if (unmounted || token !== sequence) return;
    error.value = errorText(e);
  } finally {
    if (!unmounted && token === sequence) loading.value = false;
  }
}

async function request() {
  requesting.value = true;
  error.value = "";
  polls = 0;
  stopping.value = false;
  try {
    await api.requestComplexity(props.submissionId);
    if (unmounted) return;
    await load();
  } catch (e) {
    if (!unmounted) error.value = errorText(e);
  } finally {
    if (!unmounted) requesting.value = false;
  }
}

// Same wording as the teacher overview: a failed or ineligible report must never
// be labelled 已完成.
const headerText = computed(() => {
  if (busy.value) return stopping.value ? "已停止自动刷新" : "分析中";
  const status = report.value?.status;
  if (status === "STATIC_ONLY") return "仅结构分析";
  if (status === "FAILED") return "分析失败";
  if (status === "INELIGIBLE") return "无法分析";
  return "已完成";
});
const headerTone = computed(() => {
  const status = report.value?.status;
  if (busy.value) return "amber";
  if (status === "FAILED") return "red";
  if (status === "INELIGIBLE") return "amber";
  return "type";
});

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
  unmounted = true;
  sequence += 1;
  if (timer) clearTimeout(timer);
});
</script>

<template>
  <section class="card complexity-panel">
    <div class="card-heading">
      <h2><Activity :size="17" /> 复杂度分析</h2>
      <span v-if="report" class="badge" :class="headerTone">
        {{ headerText }}
      </span>
    </div>

    <div v-if="error" class="alert error">{{ error }}</div>

    <p v-if="loading && !response" class="loading">正在读取复杂度报告…</p>
    <p v-else-if="busy" class="loading">
      <template v-if="stopping">
        已停止自动刷新（等待超过 {{ Math.round((MAX_POLLS * POLL_MS) / 1000) }}
        秒）。分析可能仍在进行，稍后手动刷新本页即可。
        <button class="small" @click="request">
          <RefreshCw :size="14" />继续等待
        </button>
      </template>
      <template v-else>正在测量运行时间，通常需要几秒到一分钟。</template>
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
