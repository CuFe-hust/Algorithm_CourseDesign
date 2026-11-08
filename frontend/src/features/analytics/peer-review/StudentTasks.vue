<script setup lang="ts">
import { ref, onMounted } from "vue";
import { useRoute } from "vue-router";
import { request, errorText } from "../../../shared/api";
import { type Page, type Task, label } from "./types";
const route = useRoute(),
  items = ref<Task[]>([]),
  total = ref(0),
  offset = ref(0),
  error = ref(""),
  busy = ref(false);
async function load() {
  busy.value = true;
  try {
    const r = await request<Page<Task>>(
      `/peer-review/courses/${route.params.courseId}/my-tasks?limit=20&offset=${offset.value}`,
    );
    items.value = r.items;
    total.value = r.total;
    error.value = "";
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
onMounted(load);
</script>
<template>
  <section class="review-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">PEER REVIEW</p>
        <h1>我的互评任务</h1>
        <p>独立阅读作品，按冻结量表逐项评分，并写出具体改进建议。</p>
      </div>
      <button class="button" :disabled="busy" @click="load">刷新任务</button>
    </header>
    <p v-if="error" class="alert error" role="alert">{{ error }}</p>
    <section class="card review-card">
      <p v-if="!items.length">
        {{ busy ? "正在读取任务…" : "当前没有分配给你的互评任务。" }}
      </p>
      <div v-for="t in items" :key="t.id" class="signal">
        <p class="muted">{{ t.assignment_title }}</p>
        <h2>{{ t.title }}</h2>
        <p>
          第 {{ t.round_no }} 轮 · {{ label(t.status) }} ·
          {{ label(t.round_status) }}
        </p>
        <p>截止 {{ new Date(t.review_deadline).toLocaleString() }}</p>
        <RouterLink
          class="button primary"
          :to="`/student/courses/${route.params.courseId}/reviews/${t.id}`"
          >{{
            t.status === "SUBMITTED" ? "查看已提交评价" : "打开评审任务"
          }}</RouterLink
        >
      </div>
      <div class="review-actions">
        <button
          class="button"
          :disabled="busy || offset === 0"
          @click="
            offset -= 20;
            load();
          "
        >
          上一页</button
        ><span>{{ total }} 个任务</span
        ><button
          class="button"
          :disabled="busy || offset + 20 >= total"
          @click="
            offset += 20;
            load();
          "
        >
          下一页
        </button>
      </div>
    </section>
  </section>
</template>
<style src="./review.css"></style>
