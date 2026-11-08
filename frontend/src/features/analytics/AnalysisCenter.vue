<script setup lang="ts">
import { ref, onMounted } from "vue";
import {
  ArrowUpRight,
  Workflow,
  Layers,
  CheckCircle2,
  Clock3,
} from "@lucide/vue";
import { request, errorText } from "../../shared/api";
import { session } from "../../shared/session";
interface Status {
  chains: {
    number: number;
    title: string;
    state: string;
    description: string;
    href: string;
  }[];
  counts: {
    assignments: number;
    review_rounds: number;
    analysis_versions: number;
    result_snapshots: number;
  };
  unimplemented: { key: string; label: string }[];
}
const data = ref<Status | null>(null),
  error = ref(""),
  busy = ref(false);
async function load() {
  busy.value = true;
  error.value = "";
  try {
    data.value = await request<Status>(
      `/analysis/courses/${session.courseId}/workflow-status`,
    );
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
onMounted(load);
</script>
<template>
  <header class="page-heading">
    <div>
      <span class="eyebrow">COURSE INSIGHTS</span>
      <h1>分析中心</h1>
      <p>从提交到互评、从证据到结果，在同一课程中查看六条业务链路。</p>
    </div>
    <button :disabled="busy" @click="load">刷新状态</button>
  </header>
  <p v-if="error" role="alert" class="alert error">{{ error }}</p>
  <section class="analysis-intro">
    <div>
      <h2>每一份结果，都有可追溯的依据。</h2>
      <p>
        评测、互评和教师复核共用版本化数据。尚未接入的模型会明确显示，待评与缺失不会被换成零分。
      </p>
    </div>
    <Workflow class="hero-icon" :size="72" />
  </section>
  <div v-if="!data && busy" class="loading">正在汇总课程链路…</div>
  <template v-if="data"
    ><section class="stats-grid">
      <article
        v-for="metric in [
          { label: '已建作业', value: data.counts.assignments },
          { label: '互评轮次', value: data.counts.review_rounds },
          { label: '复核分析版本', value: data.counts.analysis_versions },
          { label: '逐题结果快照', value: data.counts.result_snapshots },
        ]"
        :key="metric.label"
        class="card stat"
      >
        <div>{{ metric.label }}<Layers :size="17" /></div>
        <strong>{{ metric.value }}</strong
        ><small>当前课程 · 数据库实际记录</small>
      </article>
    </section>
    <section class="chain-grid">
      <article v-for="c in data.chains" :key="c.number" class="card chain-card">
        <div class="chain-top">
          <span class="chain-number">WORKFLOW / 0{{ c.number }}</span
          ><span class="badge" :class="c.state === 'READY' ? 'green' : 'amber'"
            ><CheckCircle2 v-if="c.state === 'READY'" :size="12" /><Clock3
              v-else
              :size="12"
            />{{ c.state === "READY" ? "已接入" : "部分接入" }}</span
          >
        </div>
        <h2>{{ c.title }}</h2>
        <p>{{ c.description }}</p>
        <RouterLink :to="c.href" class="text-link"
          >进入工作区 <ArrowUpRight :size="15"
        /></RouterLink>
      </article>
    </section>
    <section class="card">
      <div class="card-heading">
        <h2>研究模型接入状态</h2>
        <span class="badge amber"
          >{{ data.unimplemented.length }} 项待接入</span
        >
      </div>
      <p class="result-note">
        {{ data.unimplemented.map((x) => x.label).join("、") }}
        仍为占位接口。已有流程可保存输入并区分等待状态，但不会产生虚构的模型结论。
      </p>
      <div class="result-note">
        <RouterLink to="/teacher/complexity" class="text-link"
          >查看执行轨迹复杂度分析 <ArrowUpRight :size="15"
        /></RouterLink>
        <p class="hint">
          复杂度报告独立于分数，只描述代码在所选输入族上的增长证据。
        </p>
      </div>
    </section></template
  >
</template>
