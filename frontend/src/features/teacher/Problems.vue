<script setup lang="ts">
import { ref, onMounted } from "vue";
import { Plus, Search, LibraryBig, ArrowUpRight } from "@lucide/vue";
import { request, errorText, query } from "../../shared/api";
import { session } from "../../shared/session";
import { typeNames, dateText, type Page, type QuestionType } from "./types";
import Pagination from "../../shared/Pagination.vue";
interface Row {
  id: string;
  code: string;
  question_type: QuestionType;
  title: string;
  difficulty_level: number;
  version_no: number;
  version_status: string;
  updated_at: string;
}
const data = ref<Page<Row>>(),
  busy = ref(false),
  error = ref(""),
  search = ref(""),
  type = ref(""),
  status = ref("ACTIVE"),
  offset = ref(0);
let sequence = 0;
async function load(next = 0) {
  const seq = ++sequence;
  offset.value = next;
  busy.value = true;
  error.value = "";
  try {
    const result = await request<Page<Row>>(
      `/teacher/courses/${session.courseId}/problems?${query({ q: search.value, question_type: type.value, status: status.value, limit: 20, offset: next })}`,
    );
    if (seq === sequence) data.value = result;
  } catch (e) {
    if (seq === sequence) error.value = errorText(e);
  } finally {
    if (seq === sequence) busy.value = false;
  }
}
onMounted(() => load());
</script>
<template>
  <div class="page-heading">
    <div>
      <span class="eyebrow">QUESTION LIBRARY</span>
      <h1>题库管理</h1>
      <p>统一维护题目内容、参考答案和评分配置。</p>
    </div>
    <RouterLink to="/teacher/problems/new" class="button primary"
      ><Plus :size="17" />创建题目</RouterLink
    >
  </div>
  <section class="card table-card">
    <form class="toolbar" @submit.prevent="load()">
      <div class="search-input">
        <Search :size="17" /><input
          v-model="search"
          aria-label="搜索题目"
          placeholder="搜索题目名称或编号"
          maxlength="100"
        />
      </div>
      <select v-model="type" aria-label="筛选题型" @change="load()">
        <option value="">全部题型</option>
        <option v-for="(label, key) in typeNames" :key="key" :value="key">
          {{ label }}
        </option></select
      ><select v-model="status" aria-label="题目状态" @change="load()">
        <option value="ACTIVE">在用题目</option>
        <option value="ARCHIVED">已归档</option></select
      ><button>搜索</button>
    </form>
    <div v-if="error" class="alert error" role="alert">
      {{ error }}<button @click="load(offset)">重试</button>
    </div>
    <div v-if="busy" class="loading" role="status">正在加载题库…</div>
    <template v-else-if="data"
      ><div v-if="!data.total" class="empty">
        <LibraryBig :size="35" />
        <h3>这里还没有题目</h3>
        <p>尝试调整筛选条件，或创建第一道题。</p>
      </div>
      <div v-else class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>题目</th>
              <th>题型</th>
              <th>难度</th>
              <th>最新版本</th>
              <th>最近更新</th>
              <th class="right">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="p in data.items" :key="p.id">
              <td>
                <RouterLink
                  :to="`/teacher/problems/${p.id}`"
                  class="table-title"
                  >{{ p.title }}</RouterLink
                ><small class="mono secondary-line">{{ p.code }}</small>
              </td>
              <td>
                <span class="badge type">{{ typeNames[p.question_type] }}</span>
              </td>
              <td>
                <span
                  class="difficulty"
                  :aria-label="`难度 ${p.difficulty_level}/5`"
                  ><i
                    v-for="i in 5"
                    :key="i"
                    :class="{ filled: i <= p.difficulty_level }"
                  ></i
                ></span>
              </td>
              <td>
                <span class="mono version">v{{ p.version_no }}</span
                ><span
                  class="badge"
                  :class="p.version_status === 'DRAFT' ? 'amber' : 'green'"
                  >{{ p.version_status === "DRAFT" ? "草稿" : "已冻结" }}</span
                >
              </td>
              <td class="muted nowrap">{{ dateText(p.updated_at) }}</td>
              <td class="right">
                <RouterLink :to="`/teacher/problems/${p.id}`" class="text-link"
                  >查看 / 编辑<ArrowUpRight :size="14"
                /></RouterLink>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <Pagination
        :total="data.total"
        :offset="offset"
        :limit="20"
        @change="load"
    /></template>
  </section>
  <p class="hint">已冻结版本保留原有内容。修改时创建新草稿，不影响已有作业。</p>
</template>
