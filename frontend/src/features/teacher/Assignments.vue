<script setup lang="ts">
import { onMounted, ref } from "vue";
import { Plus, ClipboardList } from "@lucide/vue";
import { request, errorText } from "../../shared/api";
import { session } from "../../shared/session";
import { assignmentStates } from "./assignmentTypes";
import { dateText, type Page } from "./types";
import Pagination from "../../shared/Pagination.vue";
interface Row {
  id: string;
  title: string;
  submission_status: keyof typeof assignmentStates;
  submission_deadline: string;
  item_count: number;
  participant_count: number;
}
const data = ref<Page<Row>>(),
  error = ref(""),
  busy = ref(false),
  offset = ref(0);
async function load(next = 0) {
  busy.value = true;
  error.value = "";
  offset.value = next;
  try {
    data.value = await request(
      `/teacher/courses/${session.courseId}/assignments?limit=20&offset=${next}`,
    );
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
onMounted(() => load());
</script>
<template>
  <div class="page-heading">
    <div>
      <span class="eyebrow">ASSIGNMENTS</span>
      <h1>作业管理</h1>
      <p>固定题目版本与应交名单，再决定何时开放提交。</p>
    </div>
    <RouterLink class="button primary" to="/teacher/assignments/new"
      ><Plus :size="18" />创建作业</RouterLink
    >
  </div>
  <div v-if="error" class="alert error" role="alert">
    {{ error }}<button @click="load(offset)">重试</button>
  </div>
  <section class="card table-card">
    <div v-if="busy" class="loading">正在读取作业…</div>
    <template v-else-if="data"
      ><div v-if="!data.total" class="empty">
        <ClipboardList :size="36" />
        <h3>还没有作业</h3>
        <p>从已冻结题目选题，保存草稿后检查并发布。</p>
      </div>
      <div v-else class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>作业</th>
              <th>状态</th>
              <th>题目 / 应交人数</th>
              <th>提交截止</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="a in data.items" :key="a.id">
              <td>
                <strong>{{ a.title }}</strong>
              </td>
              <td>
                <span
                  class="badge"
                  :class="a.submission_status === 'OPEN' ? 'green' : 'gray'"
                  >{{ assignmentStates[a.submission_status] }}</span
                >
              </td>
              <td>{{ a.item_count }} 题 / {{ a.participant_count }} 人</td>
              <td>{{ dateText(a.submission_deadline) }}</td>
              <td>
                <RouterLink :to="`/teacher/assignments/${a.id}`">{{
                  a.submission_status === "DRAFT" ? "编辑草稿" : "查看与管理"
                }}</RouterLink>
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
</template>
