<script setup lang="ts">
/**
 * Complexity panel shown for an accepted submission.
 *
 * Every number here comes from a real execution: the platform runs the program
 * on a ladder of generated inputs, counts the work it performed, fits the growth
 * and, for recursive programs, reads the recurrence out of the call trace. The
 * panel is explicit about what it knows (the counted points, the evidence, the
 * limitations) and what it only estimates (the published class). A student must
 * never read this panel as a proof or as a grade.
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
import type {
  ComplexityReport,
  ComplexityResponse,
  TracePoint,
} from "../types";

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
  TRACE: "执行轨迹",
  NONE: "未采集",
};
/** How the published class was derived, in the order the backend can report. */
const methodText: Record<string, string> = {
  RECURRENCE: "递推推断",
  CLOSED_FORM: "闭式拟合",
  SUMMATION: "求和推断",
  EXPONENTIAL: "指数增长推断",
  MASTER: "主定理求解",
  UNKNOWN: "未能还原",
};
const shrinkText: Record<string, string> = {
  HALVING: "规模每层减半",
  DECREMENT: "规模每层减 1",
  CONSTANT: "规模每层不变",
  DATA_DEPENDENT: "规模变化视数据而定",
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

// Same wording as the teacher overview: a report that could not measure must
// never be labelled 已完成.
const headerText = computed(() => {
  if (busy.value) return stopping.value ? "已停止自动刷新" : "分析中";
  const status = report.value?.status;
  if (status === "NOT_MEASURABLE") return "无法给出结论";
  if (status === "FAILED") return "分析失败";
  if (status === "INELIGIBLE") return "无法分析";
  return "已完成";
});
const headerTone = computed(() => {
  const status = report.value?.status;
  if (busy.value) return "amber";
  if (status === "FAILED") return "red";
  if (status === "INELIGIBLE") return "amber";
  if (status === "NOT_MEASURABLE") return "gray";
  return "type";
});

/**
 * The backend publishes the recurrence as the expression string. An older
 * payload shape nested it in an object; reading both keeps the panel from
 * printing "[object Object]" if a report predates the flattening.
 */
function recurrenceText(value: unknown): string {
  if (typeof value === "string") return value.trim();
  if (value && typeof value === "object") {
    const expression = (value as { expression?: unknown }).expression;
    if (typeof expression === "string") return expression.trim();
  }
  return "";
}

const recurrence = computed(() =>
  recurrenceText(report.value?.time?.recurrence),
);

const evidence = computed(() =>
  (report.value?.trace?.evidence ?? []).map((row, index) => ({
    ...row,
    key:
      row.kind === "LINE"
        ? `LINE:${row.location}`
        : `RECURSION:${row.function}:${index}`,
  })),
);

const points = computed<TracePoint[]>(() => report.value?.trace?.points ?? []);

function theta(name: string): string {
  if (name.startsWith("O(") && name.endsWith(")")) {
    return `Θ(${name.slice(2, -1)})`;
  }
  return name === "UNKNOWN" ? "无法归类" : name;
}

/**
 * Counts are exact integers: rounding them would hide the very growth the table
 * is meant to show, so only thousands are grouped.
 */
function formatWork(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return String(Math.round(value)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** The algorithm's own work: the total minus the cost of reading the input. */
function ownWork(point: TracePoint): string {
  const baseline = Number.isFinite(point.baseline_work)
    ? point.baseline_work
    : 0;
  return formatWork(Math.max(0, point.work - baseline));
}

function formatBytes(value: number | null): string {
  if (value === null || !Number.isFinite(value) || value <= 0) return "—";
  const kib = value / 1024;
  if (kib >= 1024) return `${(kib / 1024).toFixed(1)} MiB`;
  return `${Math.round(kib)} KiB`;
}

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
      <template v-else>
        正在按题目的伸缩档运行代码并统计执行轨迹，通常需要几秒到一分钟。
      </template>
    </p>

    <template v-else-if="!report">
      <p class="muted">
        这段代码已经真实通过。可以让平台按题目的伸缩档真实运行它，统计执行轨迹里的工作量，据此推断时间与空间复杂度并画出增长趋势。
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
      <div v-else-if="report.status === 'NOT_MEASURABLE'" class="alert warning">
        <AlertTriangle :size="15" />
        无法给出结论：{{
          report.error || "没有可用的伸缩档，平台无法测量增长。"
        }}
      </div>

      <template v-if="report.status === 'SUCCEEDED'">
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
            <small class="muted">
              方法：{{
                methodText[report.time.method] || report.time.method || "—"
              }}
              · 来源：{{ sourceText[report.time.source] || report.time.source }}
            </small>
            <small v-if="report.time.closed_form" class="muted">
              闭式：<span class="mono">{{ report.time.closed_form }}</span>
            </small>
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
            <small class="muted">
              来源：{{ sourceText[report.space.source] || report.space.source }}
            </small>
          </div>
        </div>

        <p v-if="recurrence" class="mono">递推式：{{ recurrence }}</p>

        <details class="complexity-details" open>
          <summary>逐档计数</summary>
          <p v-if="report.trace" class="hint">
            采集器 {{ report.trace.adapter }}；工作量单位：{{
              report.trace.work_unit
            }}。
          </p>
          <div v-if="points.length" class="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>输入规模 n</th>
                  <th>总工作量</th>
                  <th>减去读入基准</th>
                  <th>峰值内存</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="point in points" :key="point.n">
                  <td class="mono">
                    {{ point.n }}
                    <small v-if="point.verdict !== 'OK'" class="muted">
                      {{ point.verdict }}
                    </small>
                  </td>
                  <td class="mono">{{ formatWork(point.work) }}</td>
                  <td class="mono">{{ ownWork(point) }}</td>
                  <td class="mono">{{ formatBytes(point.peak_bytes) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-else class="muted">这份报告没有留下可用的测量档位。</p>
          <GrowthChart :trace="report.trace" :time="report.time" />
        </details>

        <details class="complexity-details" open>
          <summary>轨迹证据（哪些代码贡献了工作量）</summary>
          <ul v-if="evidence.length">
            <li v-for="row in evidence" :key="row.key">
              <template v-if="row.kind === 'LINE'">
                <span class="mono line-chip">{{ row.location }}</span
                >执行次数
                {{ theta(row.class) }}
              </template>
              <template v-else>
                递归函数 <span class="mono">{{ row.function }}</span
                >：每层分 {{ row.branching }} 支，{{
                  shrinkText[row.shrink] || row.shrink
                }}
                <span v-if="row.expression" class="mono">
                  递推式 {{ row.expression }}
                </span>
                <span v-if="row.solution">，闭式 {{ row.solution }}</span>
              </template>
            </li>
          </ul>
          <p v-else class="muted">轨迹里没有可归因到具体代码行的增长证据。</p>
        </details>
      </template>

      <details v-if="report.limitations.length" class="complexity-details">
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

      <button
        v-if="
          report.status === 'SUCCEEDED' || report.status === 'NOT_MEASURABLE'
        "
        class="small"
        :disabled="requesting"
        @click="request"
      >
        <RefreshCw :size="14" />重新分析
      </button>
    </template>
  </section>
</template>
