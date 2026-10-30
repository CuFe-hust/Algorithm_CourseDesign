<script setup lang="ts">
/**
 * Workload-versus-n chart for a trace report.
 *
 * x is log2(n), y is log2(work). The counted work of the algorithm alone is
 * ``max(1, work - baseline_work)``: the reader baseline is exact arithmetic on
 * counts, so subtracting it removes "reading the input" without touching the
 * machine. On that view a power law is a straight line, so the empirical slope
 * is visible instead of being asserted by a badge.
 *
 * The reference curve is the fitted class scaled to the last measured point: it
 * answers "does the published class follow the counts". Without a fit only the
 * measured points are drawn.
 *
 * Pure SVG and no chart library: the data is small and every pixel stays
 * assertable in a test.
 */
import { computed } from "vue";
import type {
  ComplexityClass,
  ComplexityTime,
  ComplexityTrace,
  TracePoint,
} from "../types";

const props = defineProps<{
  trace: ComplexityTrace | null;
  time?: ComplexityTime | null;
}>();

const WIDTH = 620;
const HEIGHT = 260;
const PAD = { left: 70, right: 24, top: 18, bottom: 42 };
const PLOT_W = WIDTH - PAD.left - PAD.right;
const PLOT_H = HEIGHT - PAD.top - PAD.bottom;

/** Growth bases, mirroring the backend class catalogue. */
const BASES: Record<string, (n: number) => number> = {
  "O(1)": () => 1,
  "O(log n)": (n) => Math.max(1, Math.log2(n)),
  "O(n)": (n) => n,
  "O(n log n)": (n) => n * Math.max(1, Math.log2(n)),
  "O(n^2)": (n) => n * n,
  "O(n^2 log n)": (n) => n * n * Math.max(1, Math.log2(n)),
  "O(n^3)": (n) => n ** 3,
  "O(2^n)": (n) => Math.min(2 ** n, 2 ** 60),
  "O(n!)": (n) => factorial(n),
};

function factorial(n: number): number {
  // Only the shape is drawn, so the double range is a fine ceiling.
  if (n > 170) return 2 ** 60;
  let value = 1;
  for (let index = 2; index <= Math.floor(n); index++) value *= index;
  return value;
}

interface Sample {
  n: number;
  value: number;
  point: TracePoint;
}

/** A point is drawable only when both coordinates are finite positive numbers. */
function drawable(n: number, value: number): boolean {
  return Number.isFinite(n) && n > 1 && Number.isFinite(value) && value > 0;
}

const samples = computed<Sample[]>(() =>
  (props.trace?.points ?? [])
    .filter((point) => point.verdict === "OK")
    .map((point) => {
      const baseline = Number.isFinite(point.baseline_work)
        ? point.baseline_work
        : 0;
      return {
        point,
        n: point.n,
        // A program whose own work never rises above the reader is at least
        // constant; log2 of zero would drop the point entirely.
        value: Math.max(1, point.work - baseline),
      };
    })
    .filter((row) => drawable(row.n, row.value))
    .sort((left, right) => left.n - right.n),
);

const fitClass = computed<ComplexityClass | null>(() => {
  const time = props.time ?? props.trace?.time ?? null;
  return time?.fit?.best?.class ?? null;
});

const curve = computed<{ n: number; value: number }[]>(() => {
  const rows = samples.value;
  const name = fitClass.value;
  if (!name || rows.length < 2) return [];
  const base = BASES[name];
  if (!base) return [];
  const last = rows[rows.length - 1]!;
  const anchor = base(last.n);
  if (!Number.isFinite(anchor) || anchor <= 0) return [];
  const low = Math.log2(rows[0]!.n);
  const high = Math.log2(last.n);
  if (!(high > low)) return [];
  const steps = 48;
  const out: { n: number; value: number }[] = [];
  for (let index = 0; index <= steps; index++) {
    const n = 2 ** (low + ((high - low) * index) / steps);
    // Scale the class to the last measured point so both curves end together.
    const value = (base(n) / anchor) * last.value;
    if (drawable(n, value)) out.push({ n, value });
  }
  return out;
});

const bounds = computed(() => {
  const xs = samples.value.map((row) => Math.log2(row.n));
  const ys = [
    ...samples.value.map((row) => Math.log2(row.value)),
    ...curve.value.map((row) => Math.log2(row.value)),
  ].filter((value) => Number.isFinite(value));
  let xLow = Math.min(...xs);
  let xHigh = Math.max(...xs);
  if (!(xHigh - xLow > 1e-9)) {
    xLow -= 0.5;
    xHigh += 0.5;
  }
  let yLow = Math.min(...ys);
  let yHigh = Math.max(...ys);
  if (!(yHigh - yLow > 1e-9)) {
    yLow -= 0.5;
    yHigh += 0.5;
  }
  const yPad = (yHigh - yLow) * 0.08;
  return {
    xLow,
    xHigh,
    yLow: yLow - yPad,
    yHigh: yHigh + yPad,
  };
});

function px(n: number): number {
  const { xLow, xHigh } = bounds.value;
  const ratio = (Math.log2(Math.max(2, n)) - xLow) / (xHigh - xLow);
  return PAD.left + Math.min(1, Math.max(0, ratio)) * PLOT_W;
}

function py(value: number): number {
  const { yLow, yHigh } = bounds.value;
  const ratio = (Math.log2(Math.max(1, value)) - yLow) / (yHigh - yLow);
  return HEIGHT - PAD.bottom - Math.min(1, Math.max(0, ratio)) * PLOT_H;
}

const dots = computed(() =>
  samples.value.map((row) => ({
    n: row.n,
    value: row.value,
    point: row.point,
    x: px(row.n),
    y: py(row.value),
  })),
);

const path = computed(() => {
  if (curve.value.length < 2) return "";
  return curve.value
    .map(
      (row, index) =>
        `${index === 0 ? "M" : "L"}${px(row.n).toFixed(1)},${py(row.value).toFixed(1)}`,
    )
    .join(" ");
});

const xTicks = computed(() =>
  tickValues(
    samples.value.map((row) => row.n),
    px,
  ),
);
const yTicks = computed(() =>
  tickValues(
    [
      ...samples.value.map((row) => row.value),
      ...curve.value.map((row) => row.value),
    ],
    py,
  ),
);

/**
 * Pick at most six label positions and drop any that would land on top of the
 * previous one: a log axis compresses small values into a few pixels, so two
 * distinct numbers can share a coordinate.
 */
function tickValues(
  values: number[],
  position: (value: number) => number,
): number[] {
  const sorted = [
    ...new Set(values.filter((value) => Number.isFinite(value) && value > 0)),
  ].sort((a, b) => a - b);
  if (!sorted.length) return [];
  const step = Math.max(1, Math.ceil(sorted.length / 6));
  const picked: number[] = [];
  for (const value of sorted.filter((_, index) => index % step === 0)) {
    if (
      picked.length &&
      Math.abs(position(value) - position(picked[picked.length - 1]!)) < 14
    ) {
      continue;
    }
    picked.push(value);
    if (picked.length === 6) break;
  }
  return picked;
}

function formatCount(value: number): string {
  if (value >= 1000000) return `${(value / 1000000).toFixed(1)}M`;
  if (value >= 1000) return `${Math.round(value / 1000)}k`;
  if (value >= 10) return String(Math.round(value));
  return value.toFixed(1);
}

const hasData = computed(() => samples.value.length >= 2);
</script>

<template>
  <figure class="growth-chart">
    <figcaption>
      <strong>工作量随 n 增长</strong>
      <span class="muted">
        横轴 log2(n)，纵轴 log2(工作量)；双对数下的直线表示幂律增长
      </span>
    </figcaption>
    <div v-if="!hasData" class="growth-empty">
      <p class="muted">
        暂无可用档位。至少需要两个完成的测量档位才能画出增长趋势。
      </p>
    </div>
    <svg
      v-else
      :viewBox="`0 0 ${WIDTH} ${HEIGHT}`"
      role="img"
      aria-label="工作量随输入规模增长的曲线"
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
          {{ formatCount(tick) }}
        </text>
      </g>
      <g v-for="tick in xTicks" :key="`x-${tick}`">
        <text
          :x="px(tick)"
          :y="HEIGHT - PAD.bottom + 18"
          text-anchor="middle"
          class="tick"
        >
          {{ formatCount(tick) }}
        </text>
      </g>
      <path v-if="path" :d="path" class="curve" />
      <circle
        v-for="dot in dots"
        :key="dot.n"
        :cx="dot.x"
        :cy="dot.y"
        r="4.6"
        class="point"
        :data-n="dot.n"
        :data-work="dot.value"
      >
        <title>
          n={{ dot.n }} · 工作量 {{ formatCount(dot.value) }}（已减去读入基准
          {{ formatCount(dot.point.baseline_work) }}）
        </title>
      </circle>
      <text
        :x="WIDTH - PAD.right"
        :y="PAD.top + 10"
        text-anchor="end"
        class="axis-label"
      >
        工作量（log2）
      </text>
      <text
        :x="WIDTH - PAD.right"
        :y="HEIGHT - 8"
        text-anchor="end"
        class="axis-label"
      >
        输入规模 n（log2）
      </text>
    </svg>
    <div v-if="hasData" class="legend">
      <span><i class="dot" />实测点（算法自身工作量）</span>
      <span v-if="path && fitClass"
        ><i class="line" />参考曲线 {{ fitClass }}</span
      >
    </div>
  </figure>
</template>
