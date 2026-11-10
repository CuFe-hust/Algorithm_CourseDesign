<script setup lang="ts">
import { computed, ref, onMounted } from "vue";
import { useRoute } from "vue-router";
import { request, errorText } from "../../../shared/api";
import { type Page, type Task, label } from "./types";
const route = useRoute(),
  items = ref<Task[]>([]),
  total = ref(0),
  offset = ref(0),
  error = ref(""),
  busy = ref(false);
const pendingCount = computed(
  () => items.value.filter((task) => task.status !== "SUBMITTED").length,
);
const submittedCount = computed(
  () => items.value.filter((task) => task.status === "SUBMITTED").length,
);
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
        <h1>我的互评任务</h1>
      </div>
      <button class="button" :disabled="busy" :aria-busy="busy" @click="load">
        刷新任务
      </button>
    </header>
    <p v-if="error" class="alert error" role="alert">{{ error }}</p>
    <section class="card review-card">
      <p v-if="!items.length">
        {{ busy ? "正在读取任务…" : "当前没有分配给你的互评任务。" }}
      </p>
      <div v-else class="review-summary" aria-label="本页互评任务摘要">
        <div>
          <strong>{{ items.length }}</strong
          ><span>本页任务</span>
        </div>
        <div>
          <strong>{{ pendingCount }}</strong
          ><span>待评审</span>
        </div>
        <div>
          <strong>{{ submittedCount }}</strong
          ><span>已提交</span>
        </div>
        <div>
          <strong>{{ total }}</strong
          ><span>全部任务</span>
        </div>
      </div>
      <div v-for="t in items" :key="t.id" class="signal task-card">
        <div class="task-card-head">
          <p class="muted">{{ t.assignment_title }}</p>
          <span
            class="badge"
            :class="t.status === 'SUBMITTED' ? 'green' : 'amber'"
            >{{ label(t.status) }}</span
          >
        </div>
        <h2>{{ t.title }}</h2>
        <p class="task-meta">
          第 {{ t.round_no }} 轮 · {{ label(t.round_status) }} · 截止
          {{ new Date(t.review_deadline).toLocaleString() }}
        </p>
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
