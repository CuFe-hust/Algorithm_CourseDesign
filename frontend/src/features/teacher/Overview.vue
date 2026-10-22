<script setup lang="ts">
import { onMounted, ref } from "vue";
import {
  LibraryBig,
  FilePenLine,
  Users,
  School,
  ArrowUpRight,
  Plus,
  Upload,
  ArrowRight,
} from "@lucide/vue";
import { request, errorText } from "../../shared/api";
import { session } from "../../shared/session";
import { typeNames } from "./types";
const data = ref<{
    problems: number;
    drafts: number;
    students: number;
    classes: number;
    problems_by_type: Record<string, number>;
    students_by_status: Record<string, number>;
  }>(),
  error = ref(""),
  busy = ref(true);
async function load() {
  busy.value = true;
  error.value = "";
  try {
    data.value = await request(`/teacher/courses/${session.courseId}/overview`);
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
onMounted(load);
</script>
<template>
  <div class="page-heading">
    <div>
      <span class="eyebrow">COURSE OVERVIEW</span>
      <h1>课程概览</h1>
      <p>从这里开始今天的教学准备。</p>
    </div>
    <RouterLink to="/teacher/problems/new" class="button primary"
      ><Plus :size="17" />创建题目</RouterLink
    >
  </div>
  <div v-if="error" role="alert" class="alert error">
    {{ error }}<button @click="load">重试</button>
  </div>
  <div v-if="busy" class="loading" role="status">正在读取课程数据…</div>
  <template v-else-if="data"
    ><section class="stats-grid">
      <article
        v-for="s in [
          {
            label: '在用题目',
            value: data.problems,
            icon: LibraryBig,
            note: '覆盖四种题型',
          },
          {
            label: '待完善草稿',
            value: data.drafts,
            icon: FilePenLine,
            note: '冻结后可供作业引用',
          },
          {
            label: '课程学生',
            value: data.students,
            icon: Users,
            note: `${data.students_by_status.PENDING || 0} 人待激活`,
          },
          {
            label: '教学班级',
            value: data.classes,
            icon: School,
            note: '按学生当前班级统计',
          },
        ]"
        :key="s.label"
        class="card stat"
      >
        <div>
          <span>{{ s.label }}</span
          ><component :is="s.icon" :size="19" />
        </div>
        <strong>{{ s.value }}</strong
        ><small>{{ s.note }}</small>
      </article>
    </section>
    <div class="overview-grid">
      <section class="card">
        <div class="card-heading">
          <h2>题库分布</h2>
          <RouterLink to="/teacher/problems" class="text-link"
            >管理题库<ArrowUpRight :size="15"
          /></RouterLink>
        </div>
        <div class="distribution">
          <div
            v-for="(label, key) in typeNames"
            :key="key"
            class="distribution-row"
          >
            <span>{{ label }}</span>
            <div class="bar">
              <i
                :style="{
                  width: `${data.problems ? ((data.problems_by_type[key] || 0) / data.problems) * 100 : 0}%`,
                }"
              ></i>
            </div>
            <strong>{{ data.problems_by_type[key] || 0 }}</strong
            ><small>道</small>
          </div>
        </div>
      </section>
      <section class="card">
        <div class="card-heading">
          <h2>快捷操作</h2>
          <span class="small-label">教学准备</span>
        </div>
        <RouterLink to="/teacher/problems/new" class="quick-action"
          ><span class="action-icon"><Plus :size="21" /></span>
          <div>
            <strong>添加一道新题</strong>
            <p>题干、参考答案与评分配置</p>
          </div>
          <ArrowRight :size="18" /></RouterLink
        ><RouterLink to="/teacher/students/import" class="quick-action"
          ><span class="action-icon green"><Upload :size="20" /></span>
          <div>
            <strong>导入学生名单</strong>
            <p>上传 CSV，预览后确认入库</p>
          </div>
          <ArrowRight :size="18"
        /></RouterLink>
      </section>
    </div>
    <section class="notice">
      <BookNotice />
      <div>
        <strong>让修改留有记录</strong>
        <p>
          草稿支持反复编辑；已冻结的题目需创建新版本。学生导入只添加或确认更新，不会移除名单之外的学生。
        </p>
      </div>
    </section></template
  >
</template>
<script lang="ts">
import { defineComponent, h } from "vue";
import { ShieldCheck } from "@lucide/vue";
const BookNotice = defineComponent(() => () => h(ShieldCheck, { size: 23 }));
</script>
