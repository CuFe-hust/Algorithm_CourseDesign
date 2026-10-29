<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ChartNoAxesCombined, RefreshCw } from "@lucide/vue";
import { errorText } from "../../shared/api";
import {
  baselineValue,
  myAbility,
  percent,
  percentagePointDifference,
  radarGeometry,
  radarPoint,
  scoreValue,
  statusLabel,
  visibleChapters,
  type AbilityModel,
  type AbilityReport,
} from "./ability";

const route = useRoute();
const router = useRouter();
const demo = computed(() => route.query.demo === "1");
const model = computed<AbilityModel>(() =>
  route.query.model === "d1" ? "d1" : "b0",
);
const difficultyModel = computed(() => model.value === "d1");
const valueLabel = computed(() =>
  difficultyModel.value ? "模型参考表现" : "已评分题目均值",
);
const report = ref<AbilityReport | null>(null);
const fixedItemDifficulty = computed(
  () =>
    report.value?.model_parameters?.calibrate_items === false ||
    report.value?.model_diagnostics?.difficulty_source ===
      "FIXED_TEACHER_PRIOR",
);
const loading = ref(false);
const error = ref("");
const chapters = computed(() => visibleChapters(report.value?.estimates ?? []));
const geometry = computed(() => radarGeometry(chapters.value));
const baselineGeometry = computed(() =>
  radarGeometry(
    chapters.value.map((chapter) => ({
      ...chapter,
      value: chapter.baseline_value ?? null,
    })),
  ),
);
const synthetic = computed(() => demo.value || report.value?.is_mock === true);
const processItems = computed(() =>
  difficultyModel.value && report.value?.process_diagnostics?.available
    ? report.value.process_diagnostics.items
    : null,
);
const hasSnapshot = computed(
  () =>
    !!report.value &&
    ["OK", "INSUFFICIENT_DATA"].includes(report.value.status) &&
    !!report.value.estimates?.length,
);
const emptyState = computed(() => {
  switch (report.value?.status) {
    case "ANALYSIS_PENDING":
      return {
        title: "章节分析正在处理中",
        description: "服务端正在生成本批次的分析结果，完成后点击刷新查看。",
      };
    case "ANALYSIS_FAILED":
      return {
        title: "本次章节分析未完成",
        description:
          "分析任务运行失败，请联系教师或管理员检查并重新生成，再刷新此页。",
      };
    case "NOT_IN_SCOPE":
      return {
        title: "本批次未包含你的分析结果",
        description:
          "请联系教师核对本批次的学生范围；这不表示你的章节表现为零。",
      };
    case "INSUFFICIENT_DATA":
      return {
        title: "当前有效评分证据不足",
        description:
          "尚无可展示的章节证据。补充作答与评分，并由教师生成分析后，再查看此页。",
      };
    default:
      return demo.value
        ? {
            title: "暂时没有合成演示批次",
            description:
              "请由教师或管理员生成本课程的合成演示批次，完成后刷新此页。",
          }
        : {
            title: "正式章节分析尚未生成",
            description:
              "正式分析需要可用的题目章节映射与评分结果。教师生成正式分析后，你可以在这里查看本人各章节的表现和证据。",
          };
  }
});
const dateLabel = computed(() =>
  report.value?.computed_at
    ? new Date(report.value.computed_at).toLocaleString("zh-CN")
    : "—",
);
let generation = 0;
async function load() {
  const current = ++generation;
  loading.value = true;
  error.value = "";
  report.value = null;
  try {
    const result = await myAbility(
      String(route.params.courseId),
      demo.value,
      model.value,
    );
    if (current === generation) report.value = result;
  } catch (e) {
    if (current === generation) error.value = errorText(e);
  } finally {
    if (current === generation) loading.value = false;
  }
}
function switchMode() {
  void router.replace({
    query: { ...route.query, demo: demo.value ? undefined : "1" },
  });
}
function switchModel(nextModel: AbilityModel) {
  void router.replace({
    query: { ...route.query, model: nextModel === "d1" ? "d1" : undefined },
  });
}
function showDifficultyDemo() {
  void router.replace({ query: { ...route.query, demo: "1", model: "d1" } });
}
function ring(value: number) {
  return chapters.value
    .map((_, index) => {
      const point = radarPoint(index, chapters.value.length, value);
      return `${point.x},${point.y}`;
    })
    .join(" ");
}
function labelPosition(index: number) {
  return radarPoint(index, chapters.value.length, 1, 164);
}
watch(
  () => [route.params.courseId, demo.value, model.value],
  () => void load(),
  { immediate: true },
);
</script>

<template>
  <div class="page-heading ability-heading">
    <div>
      <span class="eyebrow">CHAPTER PERFORMANCE</span>
      <h1>个人章节表现</h1>
      <p class="muted">
        {{
          difficultyModel
            ? "结合题目难度查看参考表现，同时对照已评分题目的原始均值与证据。"
            : "从已评分题目了解各章节的作答表现，同时查看支撑它的证据。"
        }}
      </p>
    </div>
    <button :disabled="loading" @click="load">
      <RefreshCw :size="16" />刷新
    </button>
  </div>

  <div class="ability-model-controls" role="group" aria-label="章节分析模型">
    <button :aria-pressed="!difficultyModel" @click="switchModel('b0')">
      原始表现 B0
    </button>
    <button :aria-pressed="difficultyModel" @click="switchModel('d1')">
      难度感知模型
    </button>
    <button
      v-if="!synthetic"
      class="ability-demo-link"
      @click="showDifficultyDemo"
    >
      查看难度模型演示
    </button>
  </div>

  <div v-if="synthetic" class="ability-demo" role="status">
    <span class="badge amber">合成演示</span>
    <div>
      <strong>当前展示合成数据，不代表你的真实学习表现。</strong>
      <p>数据由服务端演示批次生成，与正式分析分开展示。</p>
    </div>
    <button @click="switchMode">返回正式分析</button>
  </div>
  <div v-if="error" class="alert error" role="alert">
    {{ error }}<button @click="load">重试</button>
  </div>
  <div v-if="loading" class="loading" role="status">正在读取章节表现…</div>
  <template v-else-if="report">
    <section v-if="!hasSnapshot" class="card ability-empty">
      <ChartNoAxesCombined :size="34" />
      <h2>{{ emptyState.title }}</h2>
      <p class="muted">{{ emptyState.description }}</p>
      <p v-if="report.reason" class="muted">说明：{{ report.reason }}</p>
      <button v-if="!demo" class="primary" @click="switchMode">
        切换合成演示
      </button>
    </section>
    <template v-else>
      <div v-if="report.status === 'INSUFFICIENT_DATA'" class="alert warning">
        当前有效评分证据不足。缺失章节保留为空，已有结果请结合题目数量与覆盖率阅读。
      </div>
      <div
        v-if="difficultyModel && report.model_diagnostics?.converged === false"
        class="alert warning ability-model-warning"
        role="status"
      >
        模型优化尚未收敛，以下模型参考表现为暂定结果，请联系教师检查批次并重新生成。
      </div>
      <section v-if="difficultyModel" class="card ability-model-explanation">
        <h2>参考难度下的模型表现</h2>
        <p>
          模型以教师 1–5 级难度为先验，{{
            fixedItemDifficulty
              ? "本批次题目难度固定在教师先验；"
              : "在冻结批次的全体评分证据上校准题目难度；"
          }}
          图中的模型参考表现，是参考难度 0 上的模型期望得分。
        </p>
        <p>
          已评分题目均值 B0
          记录本批次实际题目的得分表现；两者的差异来自题目难度、
          模型拟合与正则化，不能直接解释为学习进步。
        </p>
        <p class="muted">
          模型参考表现不代表掌握概率、置信区间或排名。证据较少时估计更依赖先验与正则化，
          请结合题量、覆盖率及原始均值阅读；缺失证据不补零。
        </p>
      </section>
      <section class="card ability-overview">
        <div class="card-heading">
          <div>
            <h2>{{ difficultyModel ? "模型参考表现分布" : "章节表现分布" }}</h2>
            <p class="muted">
              {{ synthetic ? "合成演示快照" : "正式分析快照" }} ·
              {{ dateLabel }}
            </p>
          </div>
          <span class="badge" :class="synthetic ? 'amber' : 'type'">{{
            synthetic ? "合成演示" : "正式分析"
          }}</span>
        </div>
        <div v-if="chapters.length" class="ability-chart-layout">
          <svg
            v-if="chapters.length >= 3"
            class="ability-radar"
            viewBox="0 0 440 420"
            role="img"
            aria-labelledby="ability-chart-title ability-chart-description"
          >
            <title id="ability-chart-title">各章节表现雷达图</title>
            <desc id="ability-chart-description">
              统一使用 0 到 1 的刻度。实心圆点表示{{ valueLabel }}，
              {{
                difficultyModel ? "空心圆点与虚线表示已评分题目均值 B0。" : ""
              }}
              空缺章节不连线。详细数值与证据见下方表格。
            </desc>
            <polygon
              v-for="level in [0.25, 0.5, 0.75, 1]"
              :key="level"
              :points="ring(level)"
              class="ability-ring"
            />
            <g v-for="(chapter, index) in chapters" :key="chapter.dimension">
              <line
                x1="220"
                y1="205"
                :x2="radarPoint(index, chapters.length, 1).x"
                :y2="radarPoint(index, chapters.length, 1).y"
                class="ability-axis"
              />
              <text
                :x="labelPosition(index).x"
                :y="labelPosition(index).y"
                text-anchor="middle"
                dominant-baseline="middle"
                class="ability-axis-label"
              >
                <title>
                  {{ chapter.dimension }} · {{ chapter.dimension_label }}
                </title>
                {{ chapter.dimension_label }}
              </text>
            </g>
            <text
              v-for="level in [0, 0.25, 0.5, 0.75, 1]"
              :key="`scale-${level}`"
              x="226"
              :y="205 - 132 * level - 4"
              class="ability-scale"
            >
              {{ level }}
            </text>
            <line
              v-for="(segment, index) in difficultyModel
                ? baselineGeometry.segments
                : []"
              :key="`baseline-edge-${index}`"
              :x1="segment.from.x"
              :y1="segment.from.y"
              :x2="segment.to.x"
              :y2="segment.to.y"
              class="ability-baseline-edge"
            />
            <template
              v-for="point in difficultyModel ? baselineGeometry.points : []"
              :key="`baseline-point-${point.chapter.dimension}`"
            >
              <circle
                v-if="point.position"
                :cx="point.position.x"
                :cy="point.position.y"
                r="5"
                class="ability-baseline-point"
              >
                <title>
                  {{ point.chapter.dimension_label }} 已评分题目均值 B0：{{
                    percent(point.value)
                  }}
                </title>
              </circle>
            </template>
            <line
              v-for="(segment, index) in geometry.segments"
              :key="`edge-${index}`"
              :x1="segment.from.x"
              :y1="segment.from.y"
              :x2="segment.to.x"
              :y2="segment.to.y"
              class="ability-edge"
            />
            <template
              v-for="point in geometry.points"
              :key="`point-${point.chapter.dimension}`"
            >
              <circle
                v-if="point.position"
                :cx="point.position.x"
                :cy="point.position.y"
                r="5"
                class="ability-point"
                :class="{ low: point.chapter.status === 'LOW_EVIDENCE' }"
              >
                <title>
                  {{ point.chapter.dimension_label }} {{ valueLabel }}：{{
                    percent(point.value)
                  }}，{{ statusLabel[point.chapter.status] }}
                </title>
              </circle>
            </template>
          </svg>
          <div
            v-else
            class="ability-bars"
            aria-label="章节表现条形图，统一刻度 0 到 1"
          >
            <div
              v-for="chapter in chapters"
              :key="chapter.dimension"
              class="ability-bar-item"
            >
              <strong
                >{{ chapter.dimension }} · {{ chapter.dimension_label }}</strong
              >
              <div class="ability-track">
                <span
                  v-if="scoreValue(chapter) !== null"
                  :style="{ width: `${scoreValue(chapter)! * 100}%` }"
                  class="ability-bar-fill"
                ></span>
              </div>
              <span>{{
                scoreValue(chapter) === null
                  ? "暂无有效证据"
                  : percent(scoreValue(chapter))
              }}</span>
              <small v-if="difficultyModel" class="ability-bar-baseline muted">
                已评分题目均值 B0：{{ percent(baselineValue(chapter)) }} · 差值
                {{ percentagePointDifference(chapter) }}
              </small>
            </div>
            <p class="muted">0 ───────────────────── 1</p>
          </div>
          <div class="ability-reading">
            <h3>如何阅读这张图</h3>
            <p v-if="difficultyModel">
              各章节按课程章节顺序排列，量尺统一为 0–1；蓝点为模型参考表现，
              空心点与虚线为已评分题目均值 B0。
            </p>
            <p v-else>
              各章节按课程章节顺序排列，量尺统一为
              0–1；数值是该章节已评分证据的加权表现。
            </p>
            <p>
              <span class="ability-key"></span
              >{{ valueLabel }}使用实心点；橙点表示证据较少。
              {{
                difficultyModel
                  ? "原始零分仍显示为 0，模型值可能因正则化而不同。"
                  : "真实的零分仍显示在 0 处。"
              }}
            </p>
            <p>暂无有效证据的章节不绘点、不补零。未被作业覆盖的章节已隐藏。</p>
            <p class="muted">
              不同章节的题量、题型和覆盖率可能不同，结合下方明细理解数值。
            </p>
          </div>
        </div>
        <p v-else class="ability-no-chapters muted">
          当前作业尚未覆盖可展示的章节。覆盖章节并产生评分后再查看。
        </p>
      </section>

      <section v-if="chapters.length" class="card ability-evidence">
        <div class="card-heading">
          <div>
            <h2>章节证据明细</h2>
            <p class="muted">
              缺失的评分不计入均值；“—”表示没有可用数值。
              {{
                difficultyModel
                  ? "题型列保留原始观察均值；差值为模型参考表现减去 B0。"
                  : ""
              }}
            </p>
          </div>
        </div>
        <div class="ability-table-scroll">
          <table>
            <caption class="sr-only">
              本人各章节表现、题型子均值与证据覆盖情况
            </caption>
            <thead>
              <tr>
                <th scope="col">章节</th>
                <th scope="col">{{ valueLabel }} / 状态</th>
                <th v-if="difficultyModel" scope="col">已评分题目均值 B0</th>
                <th v-if="difficultyModel" scope="col">差值</th>
                <th scope="col">
                  {{ difficultyModel ? "编程题原始均值" : "编程题" }}
                </th>
                <th scope="col">
                  {{ difficultyModel ? "主观题原始均值" : "主观题" }}
                </th>
                <th scope="col">评分 / 布置</th>
                <th scope="col">题量 / 权重覆盖</th>
                <th scope="col">缺失证据</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="chapter in chapters" :key="chapter.dimension">
                <th scope="row">
                  <span class="ability-chapter-code">{{
                    chapter.dimension
                  }}</span
                  >{{ chapter.dimension_label }}
                </th>
                <td>
                  <strong class="ability-value">{{
                    percent(scoreValue(chapter))
                  }}</strong
                  ><small
                    :class="
                      chapter.status === 'LOW_EVIDENCE'
                        ? 'ability-low'
                        : 'muted'
                    "
                    >{{ statusLabel[chapter.status] }}</small
                  >
                </td>
                <td v-if="difficultyModel" class="ability-baseline">
                  {{ percent(baselineValue(chapter)) }}
                </td>
                <td v-if="difficultyModel" class="ability-difference">
                  {{ percentagePointDifference(chapter) }}
                </td>
                <td>
                  {{ percent(chapter.by_type?.PROGRAMMING?.value)
                  }}<small class="muted"
                    >{{ chapter.by_type?.PROGRAMMING?.n_items ?? 0 }} 题</small
                  >
                </td>
                <td>
                  {{ percent(chapter.by_type?.SUBJECTIVE?.value)
                  }}<small class="muted"
                    >{{ chapter.by_type?.SUBJECTIVE?.n_items ?? 0 }} 题</small
                  >
                </td>
                <td>
                  {{ chapter.scored_items }} / {{ chapter.assigned_items
                  }}<small class="muted"
                    >有效证据 {{ chapter.n_items }} 题</small
                  >
                </td>
                <td>
                  {{ percent(chapter.coverage_items) }} /
                  {{ percent(chapter.coverage_weight) }}
                </td>
                <td>
                  <small>待评分 {{ chapter.missing?.pending ?? 0 }}</small
                  ><small
                    >未提交 {{ chapter.missing?.not_submitted ?? 0 }} · 无效
                    {{ chapter.missing?.invalid ?? 0 }}</small
                  >
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
      <section v-if="processItems" class="card ability-process">
        <div class="card-heading">
          <div>
            <h2>作答过程观察</h2>
            <p class="muted">
              以下仅描述有记录的提交与得分变化，提交次数和重复失败不作为能力扣分。
              相邻同类失败对指连续两次提交出现相同的未通过判定。
            </p>
          </div>
        </div>
        <div v-if="processItems.length" class="ability-table-scroll">
          <table>
            <caption class="sr-only">
              本人题目提交次数、得分变化与首次通过观察
            </caption>
            <thead>
              <tr>
                <th scope="col">题目</th>
                <th scope="col">提交次数</th>
                <th scope="col">首次 / 最近 / 最佳得分</th>
                <th scope="col">首次通过</th>
                <th scope="col">相邻同类失败对</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="item in processItems" :key="item.item_key">
                <th scope="row">{{ item.item_key }}</th>
                <td>{{ item.submission_count }}</td>
                <td>
                  {{ percent(item.first_score) }} /
                  {{ percent(item.latest_score) }} /
                  {{ percent(item.best_score) }}
                </td>
                <td>
                  {{
                    item.first_accepted_attempt == null
                      ? "未观察到"
                      : `第 ${item.first_accepted_attempt} 次`
                  }}
                </td>
                <td>{{ item.repeated_failure_pairs }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="ability-process-empty muted">
          本批次没有可展示的题目提交记录。
        </p>
      </section>
      <details class="ability-provenance">
        <summary>查看分析来源与版本</summary>
        <dl>
          <dt>批次</dt>
          <dd>{{ report.batch_id || "—" }}</dd>
          <dt>数据来源</dt>
          <dd>{{ report.source_kind }}</dd>
          <dt>结果快照</dt>
          <dd>{{ report.results_snapshot_version || "—" }}</dd>
          <dt>计分策略</dt>
          <dd>{{ report.scoring_policy_version || "—" }}</dd>
          <dt>章节映射</dt>
          <dd>{{ report.chapter_mapping_version || "—" }}</dd>
          <dt>实现版本</dt>
          <dd>{{ report.implementation_version || "—" }}</dd>
          <template v-if="difficultyModel">
            <dt>模型方法</dt>
            <dd>{{ report.method || "—" }}</dd>
            <dt>题目难度</dt>
            <dd>
              {{ fixedItemDifficulty ? "固定在教师先验" : "随冻结批次校准" }}
            </dd>
            <template v-if="report.model_parameters">
              <dt>模型参数</dt>
              <dd>
                learner_l2={{ report.model_parameters.learner_l2 }} · item_l2={{
                  report.model_parameters.item_l2
                }}
                · difficulty_scale={{
                  report.model_parameters.difficulty_scale
                }}
                · max_iterations={{ report.model_parameters.max_iterations }} ·
                tolerance={{ report.model_parameters.tolerance }}
              </dd>
            </template>
            <template v-if="report.model_diagnostics">
              <dt>优化结果</dt>
              <dd>
                {{ report.model_diagnostics.converged ? "已收敛" : "未收敛" }} ·
                {{ report.model_diagnostics.iterations }} 次迭代 · loss={{
                  report.model_diagnostics.loss
                }}
              </dd>
            </template>
          </template>
        </dl>
      </details>
      <button v-if="!synthetic" class="ability-demo-switch" @click="switchMode">
        切换合成演示
      </button>
    </template>
  </template>
</template>

<style scoped>
.ability-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 20px;
}
.ability-model-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 22px;
}
.ability-model-controls button[aria-pressed="true"] {
  color: var(--blue);
  background: #edf3ff;
  border-color: #b8cdfa;
}
.ability-demo-link {
  margin-left: auto;
}
.ability-model-explanation {
  margin-bottom: 24px;
  padding: 22px 26px;
  font-size: 13px;
  line-height: 1.7;
}
.ability-model-explanation h2 {
  font-size: 16px;
  margin-bottom: 12px;
}
.ability-model-explanation p:last-child {
  margin-bottom: 0;
}
.ability-demo {
  display: flex;
  align-items: center;
  gap: 16px;
  border: 1px solid #e6c877;
  background: #fffaeb;
  padding: 16px 20px;
  border-radius: 9px;
  margin-bottom: 22px;
  color: #755514;
}
.ability-demo p {
  margin: 3px 0 0;
  font-size: 12px;
}
.ability-demo button {
  margin-left: auto;
}
.ability-empty {
  padding: 48px 24px;
  text-align: center;
}
.ability-empty > svg {
  color: var(--blue);
  margin-bottom: 18px;
}
.ability-empty h2 {
  margin-bottom: 12px;
}
.ability-empty p {
  max-width: 560px;
  margin: 0 auto 24px;
}
.ability-overview,
.ability-evidence,
.ability-process {
  margin-bottom: 24px;
}
.card-heading p {
  font-size: 12px;
  margin: 5px 0 0;
}
.ability-chart-layout {
  display: grid;
  grid-template-columns: minmax(270px, 1.3fr) minmax(240px, 1fr);
  align-items: center;
  padding: 0 28px 18px;
  gap: 26px;
}
.ability-radar {
  display: block;
  width: 100%;
  max-width: 490px;
  margin: auto;
}
.ability-ring {
  fill: none;
  stroke: #e1e7f1;
}
.ability-axis {
  stroke: #e1e7f1;
}
.ability-axis-label {
  fill: #43516a;
  font-size: 11px;
  font-weight: 600;
}
.ability-scale {
  fill: #7e8ba2;
  font-size: 10px;
}
.ability-edge {
  stroke: var(--blue);
  stroke-width: 2;
}
.ability-baseline-edge {
  stroke: #8290a7;
  stroke-width: 1.5;
  stroke-dasharray: 4 4;
}
.ability-baseline-point {
  fill: white;
  stroke: #657188;
  stroke-width: 1.5;
}
.ability-point {
  fill: var(--blue);
  stroke: white;
  stroke-width: 1.5;
}
.ability-point.low {
  fill: #c88713;
}
.ability-reading {
  border-left: 3px solid #dce5fd;
  padding: 6px 0 6px 22px;
  max-width: 370px;
  font-size: 13px;
}
.ability-reading h3 {
  margin-bottom: 14px;
}
.ability-reading p:last-child {
  margin-bottom: 0;
}
.ability-key {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--blue);
  margin-right: 4px;
}
.ability-bars {
  padding: 30px 0;
}
.ability-bar-item {
  margin-bottom: 22px;
  font-size: 12px;
}
.ability-bar-baseline {
  display: block;
  margin-top: 6px;
}
.ability-track {
  position: relative;
  height: 9px;
  border-radius: 8px;
  background: #edf1f7;
  margin: 10px 0 6px;
}
.ability-bar-fill {
  position: absolute;
  height: 9px;
  min-width: 3px;
  background: var(--blue);
  border-radius: 8px;
}
.ability-no-chapters {
  padding: 28px;
}
.ability-table-scroll {
  overflow-x: auto;
}
.ability-evidence table,
.ability-process table {
  min-width: 920px;
  width: 100%;
  border-collapse: collapse;
  text-align: left;
  font-size: 12px;
}
.ability-evidence th,
.ability-evidence td,
.ability-process th,
.ability-process td {
  padding: 15px 18px;
  border-bottom: 1px solid var(--border);
  vertical-align: middle;
}
.ability-evidence thead th,
.ability-process thead th {
  color: #657188;
  font-weight: 500;
  background: #f8fafd;
  white-space: nowrap;
}
.ability-evidence tbody th,
.ability-process tbody th {
  min-width: 150px;
  font-weight: 500;
}
.ability-evidence small {
  display: block;
  font-size: 11px;
  margin-top: 3px;
  white-space: nowrap;
}
.ability-chapter-code {
  display: block;
  font-size: 10px;
  letter-spacing: 1px;
  color: var(--muted);
}
.ability-value {
  font-variant-numeric: tabular-nums;
  font-size: 16px;
}
.ability-low {
  color: #986614;
}
.ability-baseline,
.ability-difference {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.ability-process-empty {
  padding: 0 24px 20px;
}
.ability-provenance {
  font-size: 12px;
  color: #657188;
  margin: 18px 0;
}
.ability-provenance summary {
  cursor: pointer;
  padding: 6px 0;
}
.ability-provenance dl {
  display: grid;
  grid-template-columns: 90px 1fr;
  gap: 6px 12px;
}
.ability-provenance dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.ability-demo-switch {
  margin-bottom: 20px;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
}
@media (max-width: 760px) {
  .ability-heading {
    align-items: flex-start;
  }
  .ability-demo {
    align-items: flex-start;
    flex-wrap: wrap;
    gap: 10px;
  }
  .ability-demo button {
    margin-left: 0;
  }
  .ability-demo-link {
    margin-left: 0;
  }
  .ability-chart-layout {
    grid-template-columns: 1fr;
    padding: 0 16px 24px;
    gap: 0;
  }
  .ability-reading {
    max-width: none;
  }
}
</style>
