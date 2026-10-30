<script setup lang="ts">
import { computed } from "vue";
import MarkdownPreview from "../../../shared/MarkdownPreview.vue";
import type { ItemDetail } from "../types";
const props = defineProps<{ item: ItemDetail }>();
const meta = computed(() => [
  { label: "题型", value: typeName(props.item.question_type) },
  { label: "满分", value: props.item.max_score },
  { label: "难度", value: `${props.item.difficulty_level} / 5` },
  { label: "题面版本", value: `v${props.item.version_no}` },
]);
function typeName(type: string) {
  return (
    {
      PROGRAMMING: "编程题",
      ALGORITHM_ANALYSIS: "算法分析",
      PROOF: "证明题",
      OPEN_QUESTION: "开放题",
    }[type] || type
  );
}
</script>
<template>
  <article class="card statement">
    <div class="card-heading">
      <div>
        <span class="small-label">{{ item.problem_code }}</span>
        <h1>{{ item.title }}</h1>
      </div>
    </div>
    <dl class="meta-row">
      <div v-for="entry in meta" :key="entry.label">
        <dt>{{ entry.label }}</dt>
        <dd>{{ entry.value }}</dd>
      </div>
    </dl>
    <MarkdownPreview :source="item.statement_md" />
    <section v-if="item.answer_requirements_md">
      <h3>作答要求</h3>
      <MarkdownPreview :source="item.answer_requirements_md" />
    </section>
    <section v-if="item.input_spec_md || item.output_spec_md" class="split">
      <div v-if="item.input_spec_md">
        <h3>输入格式</h3>
        <MarkdownPreview :source="item.input_spec_md" />
      </div>
      <div v-if="item.output_spec_md">
        <h3>输出格式</h3>
        <MarkdownPreview :source="item.output_spec_md" />
      </div>
    </section>
    <section v-if="item.data_constraints_md">
      <h3>数据范围</h3>
      <MarkdownPreview :source="item.data_constraints_md" />
    </section>
    <section v-if="item.public_examples_md">
      <h3>题面样例</h3>
      <MarkdownPreview :source="item.public_examples_md" />
    </section>
    <section v-if="item.public_test_cases.length">
      <h3>公开测试点</h3>
      <p class="muted">
        仅显示教师标记为公开的测试点，隐藏测试不会出现在这里。
      </p>
      <div
        v-for="sample in item.public_test_cases"
        :key="sample.case_no"
        class="sample"
      >
        <span class="small-label">测试点 {{ sample.case_no }}</span>
        <div class="split">
          <div>
            <span class="small-label">输入</span>
            <pre class="mono">{{ sample.input_text || "（空）" }}</pre>
          </div>
          <div>
            <span class="small-label">期望输出</span>
            <pre class="mono">{{ sample.expected_output || "（空）" }}</pre>
          </div>
        </div>
      </div>
    </section>
    <section v-if="item.rubric.length">
      <h3>评分维度</h3>
      <ul class="rubric-list">
        <li v-for="dimension in item.rubric" :key="dimension.id">
          <strong>{{ dimension.name }}（{{ dimension.max_score }} 分）</strong>
          <p class="muted">{{ dimension.description }}</p>
        </li>
      </ul>
    </section>
  </article>
</template>
