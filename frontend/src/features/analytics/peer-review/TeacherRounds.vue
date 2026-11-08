<script setup lang="ts">
import { ref, onMounted } from "vue";
import { request, post, errorText } from "../../../shared/api";
import { session } from "../../../shared/session";
import { useRouter } from "vue-router";
import type { Round, RoundSummary, Page } from "./types";
import { label } from "./types";
const router = useRouter(),
  rows = ref<RoundSummary[]>([]),
  assignments = ref<
    {
      id: string;
      title: string;
      submission_status: string;
      items: { id: string; title: string; question_type: string }[];
    }[]
  >([]),
  item = ref(""),
  deadline = ref(""),
  minimum = ref(2),
  method = ref("weighted_mean"),
  maxLoad = ref(""),
  forbidden = ref(""),
  reason = ref("初次互评分配预览"),
  error = ref(""),
  busy = ref(false),
  offset = ref(0),
  total = ref(0);
const requestId = ref(crypto.randomUUID());
async function load() {
  try {
    const [r, a] = await Promise.all([
      request<Page<RoundSummary>>(
        `/peer-review/teacher/courses/${session.courseId}/rounds?limit=20&offset=${offset.value}`,
      ),
      request<{ items: typeof assignments.value }>(
        `/courses/${session.courseId}/assignments`,
      ),
    ]);
    rows.value = r.items;
    total.value = r.total;
    assignments.value = a.items;
  } catch (e) {
    error.value = errorText(e);
  }
}
async function create() {
  busy.value = true;
  error.value = "";
  try {
    const pairs = forbidden.value.trim()
      ? forbidden.value
          .trim()
          .split("\n")
          .map((line) => {
            const ids = line.trim().split(/[,，\s]+/);
            if (ids.length !== 2 || ids.some((v) => !/^\d+$/.test(v)))
              throw Error("禁止关系每行填写两个学生ID，以空格分隔");
            return {
              student_a_id: ids[0],
              student_b_id: ids[1],
            };
          })
      : [];
    const r = await post<Round>(
      `/peer-review/teacher/assignment-items/${item.value}/previews`,
      {
        request_id: requestId.value,
        review_deadline: new Date(deadline.value).toISOString(),
        reason: reason.value,
        forbidden_pairs: pairs,
        policy: {
          minimum_samples: minimum.value,
          aggregation_method: method.value,
          max_tasks_per_reviewer: maxLoad.value ? Number(maxLoad.value) : null,
        },
      },
    );
    await router.push(`/teacher/reviews/${r.id}`);
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
function changed() {
  requestId.value = crypto.randomUUID();
}
onMounted(load);
</script>
<template>
  <section class="review-page">
    <header class="page-heading">
      <div>
        <p class="eyebrow">主观互评 / 聚合与异常</p>
        <h1>互评与复核</h1>
        <p>先冻结答案与量表，再确认分配；所有异常信号交由教师复核。</p>
      </div>
      <button class="button" @click="load">刷新</button>
    </header>
    <p v-if="error" role="alert" class="alert error">{{ error }}</p>
    <section class="card review-card">
      <h2>创建分配预览</h2>
      <p>
        需先关闭作业提交，并等待提交截止到达。每份作品的评审人数沿用作业题目设置。
      </p>
      <form @submit.prevent="create" @input="changed">
        <label
          >主观题<select v-model="item" required>
            <option value="">选择作业题目</option>
            <optgroup
              v-for="a in assignments"
              :key="a.id"
              :label="`${a.title} · ${{ OPEN: '提交开放', CLOSED: '提交关闭', DRAFT: '草稿' }[a.submission_status] || a.submission_status}`"
            >
              <option
                v-for="q in a.items.filter(
                  (q) => q.question_type !== 'PROGRAMMING',
                )"
                :key="q.id"
                :value="q.id"
              >
                {{ q.title }}
              </option>
            </optgroup>
          </select></label
        >
        <div class="review-grid">
          <label
            >互评截止（本地时间）<input
              v-model="deadline"
              type="datetime-local"
              required /></label
          ><label
            >最低有效评价数<input
              v-model.number="minimum"
              type="number"
              min="1"
              max="10"
              required /></label
          ><label
            >聚合方法<select v-model="method">
              <option value="weighted_mean">显式加权均值</option>
              <option value="weighted_median">显式加权中位数</option>
            </select></label
          ><label
            >每位学生任务总上限（含补评）<input
              v-model="maxLoad"
              type="number"
              min="1"
              max="2000"
              placeholder="自动均衡，无硬上限"
          /></label>
        </div>
        <label
          >禁止互评关系（可选，每行两个学生ID）<textarea
            v-model="forbidden"
            rows="2"
            placeholder="从学生名单查看ID；例如：12 34"
          /></label
        ><label
          >创建理由<input v-model="reason" required maxlength="2000" /></label
        ><button class="button primary" :disabled="busy || !item">
          {{ busy ? "生成中…" : "冻结输入并生成预览" }}
        </button>
      </form>
    </section>
    <section class="card review-card">
      <h2>互评轮次</h2>
      <p v-if="!rows.length">暂无互评轮次。</p>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>轮次</th>
              <th>题目ID</th>
              <th>状态</th>
              <th>截止</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in rows" :key="r.id">
              <td>#{{ r.id }} · 第{{ r.round_no }}轮</td>
              <td>{{ r.assignment_item_id }}</td>
              <td>{{ label(r.status) }}</td>
              <td>{{ new Date(r.review_deadline).toLocaleString() }}</td>
              <td>
                <RouterLink :to="`/teacher/reviews/${r.id}`"
                  >查看与处理</RouterLink
                >
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div class="review-actions">
        <button
          class="button"
          :disabled="offset === 0"
          @click="
            offset -= 20;
            load();
          "
        >
          上一页</button
        ><span
          >{{ offset + 1 }}–{{ Math.min(offset + 20, total) }} /
          {{ total }}</span
        ><button
          class="button"
          :disabled="offset + 20 >= total"
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
