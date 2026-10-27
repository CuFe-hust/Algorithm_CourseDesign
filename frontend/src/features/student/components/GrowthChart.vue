<script setup lang="ts">
/**
 * Growth chart for a complexity report.
 *
 * Coordinates: x is log2(n), y is measured milliseconds. A log-log view is the
 * honest default for growth: a polynomial shows up as a straight line, so a
 * student can see *that* the curve bends instead of trusting a badge.
 *
 * The component renders pure SVG with no chart library: the data is small, the
 * bundle stays lean, and every pixel is inspectable in a test.
 */
import { computed } from "vue";
import type { DynamicAnalysis, GrowthCurvePoint, GrowthPoint } from "../types";

const props = defineProps<{
  dynamic: DynamicAnalysis | null;
  spacePoints?: GrowthPoint[];
}>();

const WIDTH = 620;
const HEIGHT = 260;
const PAD = { left: 62, right: 22, top: 18, bottom: 40 };

interface Dot {
  x: number;
  y: number;
  rung: GrowthPoint;
  ioDominated: boolean;
}

const rungs = computed<GrowthPoint[]>(() =>
  (props.dynamic?.rungs ?? []).filter(
    (rung) => rung.verdict === "OK" && rung.wall_ms > 0,
  ),
);

const curve = computed<GrowthCurvePoint[]>(() => props.dynamic?.curve ?? []);

const xMax = computed(() => {
  const values = [
    ...rungs.value.map((r) => r.n),
    ...curve.value.map((p) => p.n),
  ];
  return Math.max(1, ...values);
});
const xMin = computed(() => {
  const values = [
    ...rungs.value.map((r) => r.n),
    ...curve.value.map((p) => p.n),
  ].filter((value) => value > 0);
  return Math.min(xMax.value, ...(values.length ? values : [1]));
});
const yMax = computed(() => {
  const values = [
    ...rungs.value.map((r) => r.wall_ms),
    ...curve.value.map((p) => p.time_ms),
  ].filter((value) => Number.isFinite(value) && value > 0);
  return Math.max(1, ...values);
});

function logScale(value: number, min: number, max: number): number {
  const low = Math.log2(Math.max(1, min));
  const high = Math.log2(Math.max(2, max));
  if (high <= low) return 0.5;
  return (Math.log2(Math.max(1, value)) - low) / (high - low);
}

function px(n: number): number {
  return (
    PAD.left +
    logScale(n, xMin.value, xMax.value) * (WIDTH - PAD.left - PAD.right)
  );
}
function py(ms: number): number {
  const ratio = logScale(ms, 0.05, yMax.value * 1.05);
  return HEIGHT - PAD.bottom - ratio * (HEIGHT - PAD.top - PAD.bottom);
}

const dots = computed<Dot[]>(() =>
  rungs.value.map((rung) => ({
    x: px(rung.n),
    y: py(rung.wall_ms),
    rung,
    ioDominated: (rung.io_ratio ?? Number.POSITIVE_INFINITY) < 2,
  })),
);

const path = computed(() => {
  if (curve.value.length < 2) return "";
  return curve.value
    .map(
      (point, index) =>
        `${index === 0 ? "M" : "L"}${px(point.n).toFixed(1)},${py(point.time_ms).toFixed(1)}`,
    )
    .join(" ");
});

const xTicks = computed(() =>
  tickValues(rungs.value.map((r) => r.n).concat(curve.value.map((p) => p.n))),
);
const yTicks = computed(() =>
  tickValues(
    rungs.value.map((r) => r.wall_ms).concat(curve.value.map((p) => p.time_ms)),
  ),
);

function tickValues(values: number[]): number[] {
  if (!values.length) return [];
  const sorted = [...new Set(values.filter((value) => value > 0))].sort(
    (a, b) => a - b,
  );
  if (sorted.length <= 6) return sorted;
  const step = Math.ceil(sorted.length / 6);
  return sorted.filter((_, index) => index % step === 0).slice(0, 7);
}

function formatMs(value: number): string {
  if (value >= 1000) return `${(value / 1000).toFixed(1)} s`;
  if (value >= 10) return `${Math.round(value)} ms`;
  return `${value.toFixed(1)} ms`;
}
function formatN(value: number): string {
  if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
  if (value >= 1000) return `${Math.round(value / 1000)}k`;
  return String(value);
}

const hasData = computed(() => rungs.value.length >= 2);
const ioDominatedCount = computed(
  () => dots.value.filter((dot) => dot.ioDominated).length,
);
</script>

<template>
  <figure class="growth-chart">
    <figcaption>
      <strong>实测增长</strong>
      <span class="muted"> 横轴输入规模（对数），纵轴运行时间（对数） </span>
    </figcaption>
    <div v-if="!hasData" class="growth-empty">
      <p class="muted">
        没有可用的测量点。可能是程序在可测规模内都接近启动开销，或题目没有伸缩档案。
      </p>
    </div>
    <svg
      v-else
      :viewBox="`0 0 ${WIDTH} ${HEIGHT}`"
      role="img"
      aria-label="运行时间随输入规模的增长曲线"
    >
      <line
        :x1="PAD.left"
        :y1="HEIGHT - PAD.bottom"
        :x2="WIDTH - PAD.right"
        :y2="HEIGHT - PAD.bottom"
        class="axis"
      />
      <line
        :x1="PAD.left"
        :y1="PAD.top"
        :x2="PAD.left"
        :y2="HEIGHT - PAD.bottom"
        class="axis"
      />
      <g v-for="tick in yTicks" :key="`y-${tick}`">
        <line
          :x1="PAD.left"
          :x2="WIDTH - PAD.right"
          :y1="py(tick)"
          :y2="py(tick)"
          class="grid"
        />
        <text
          :x="PAD.left - 8"
          :y="py(tick) + 4"
          text-anchor="end"
          class="tick"
        >
          {{ formatMs(tick) }}
        </text>
      </g>
      <g v-for="tick in xTicks" :key="`x-${tick}`">
        <text
          :x="px(tick)"
          :y="HEIGHT - PAD.bottom + 18"
          text-anchor="middle"
          class="tick"
        >
          {{ formatN(tick) }}
        </text>
      </g>
      <path v-if="path" :d="path" class="curve" />
      <circle
        v-for="dot in dots"
        :key="dot.rung.n"
        :cx="dot.x"
        :cy="dot.y"
        :r="dot.ioDominated ? 3.2 : 4.6"
        :class="['point', { mutedPoint: dot.ioDominated }]"
      >
        <title>
          n={{ dot.rung.n }} · {{ formatMs(dot.rung.wall_ms) }} <template
          v-if="dot.rung.reference_ms"> · 纯读取
          {{ formatMs(dot.rung.reference_ms) }}
          </template>
        </title>
      </circle>
      <text
        :x="WIDTH - PAD.right"
        :y="PAD.top + 10"
        text-anchor="end"
        class="axis-label"
      >
        时间
      </text>
      <text
        :x="WIDTH - PAD.right"
        :y="HEIGHT - 8"
        text-anchor="end"
        class="axis-label"
      >
        输入规模 n
      </text>
    </svg>
    <div v-if="hasData" class="legend">
      <span><i class="dot" />实测点</span>
      <span v-if="curve.length"><i class="line" />拟合曲线</span>
      <span v-if="ioDominatedCount">
        <i class="dot dim" />小点：与纯读取输入同阶，仅作上界
      </span>
    </div>
  </figure>
</template>
