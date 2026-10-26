<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { request, query, errorText } from "../../shared/api";
import { session } from "../../shared/session";
import type { Page } from "./types";
import { typeNames, dateText } from "./types";
import type { ProgressResponse, SubmissionDetail } from "../student/types";
import Pagination from "../../shared/Pagination.vue";
import CodePreview from "../../shared/CodePreview.vue";
import MarkdownPreview from "../../shared/MarkdownPreview.vue";
import JudgeFeedback from "../student/components/JudgeFeedback.vue";
const route = useRoute(),
  progress = ref<
    ProgressResponse & {
      student?: { full_name: string; student_no: string | null };
    }
  >(),
  detail = ref<SubmissionDetail>(),
  error = ref(""),
  busy = ref(false),
  offset = ref(0),
  history = ref<
    Page<{
      submission_id: string;
      version_no: number;
      status: string;
      submitted_at: string;
    }>
  >(),
  historyItem = ref(""),
  historyOffset = ref(0);
async function load(next = 0) {
  busy.value = true;
  error.value = "";
  offset.value = next;
  try {
    progress.value = await request(
      `/teacher/courses/${session.courseId}/students/${route.params.studentId}/progress?${query({ assignment_id: typeof route.query.assignment_id === "string" ? route.query.assignment_id : undefined, limit: 20, offset: next })}`,
    );
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
let selection = 0;
async function show(id: string) {
  const seq = ++selection;
  detail.value = undefined;
  try {
    const value = await request<SubmissionDetail>(`/submissions/${id}`);
    if (
      value.course_id !== session.courseId ||
      value.student_id !== route.params.studentId
    )
      throw new Error("提交不属于当前课程学生。");
    if (seq === selection) detail.value = value;
  } catch (e) {
    if (seq === selection) error.value = errorText(e);
  }
}
async function versions(itemId: string, next = 0) {
  historyItem.value = itemId;
  historyOffset.value = next;
  try {
    history.value = await request(
      `/teacher/courses/${session.courseId}/submissions?${query({ assignment_item_id: itemId, student_id: String(route.params.studentId), limit: 20, offset: next })}`,
    );
  } catch (e) {
    error.value = errorText(e);
  }
}
onMounted(() => load());
</script>
<template>
  <div class="page-heading">
    <div>
      <RouterLink to="/teacher/students">← 学生名单</RouterLink>
      <h1>学生提交进度</h1>
      <p v-if="progress?.student">
        {{ progress.student.student_no }} · {{ progress.student.full_name }}
      </p>
      <p>采用结果与学生端共用选择服务；处理中与模拟结果不作为正式成绩。</p>
    </div>
    <button :disabled="busy" @click="load(offset)">刷新进度</button>
  </div>
  <div v-if="error" class="alert error" role="alert">{{ error }}</div>
  <div v-if="busy" class="loading">正在读取进度…</div>
  <template v-else-if="progress"
    ><p class="hint">
      当前评测环境：{{ progress.evaluation_context.execution_mode }} ·
      {{ progress.evaluation_context.runtime_profile }}。已提交
      {{ progress.summary.submitted_item_count }} /
      {{ progress.summary.item_count }} 题。
    </p>
    <section class="card table-card">
      <div v-if="!progress.total" class="empty">
        <h3>暂无已发布的应交题目</h3>
        <p>先为该学生发布作业，草稿不会出现在这里。</p>
      </div>
      <div v-else class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>作业 / 题目</th>
              <th>题型</th>
              <th>提交数</th>
              <th>采用与处理状态</th>
              <th>查看</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="entry in progress.items" :key="entry.assignment_item_id">
              <td>
                {{ entry.title
                }}<small class="secondary-line">{{
                  entry.assignment_title
                }}</small>
              </td>
              <td>{{ typeNames[entry.question_type] }}</td>
              <td>{{ entry.submission_count }}</td>
              <td>
                <span v-if="entry.has_unresolved_jobs" class="badge amber"
                  >处理中 / 存在服务故障</span
                ><span
                  v-else
                  class="badge"
                  :class="entry.effective_submission_id ? 'green' : 'gray'"
                  >{{
                    entry.effective_submission_id
                      ? "已有采用候选"
                      : entry.has_submitted
                        ? "暂无当前环境有效候选"
                        : "未提交"
                  }}</span
                ><small
                  v-if="entry.question_type === 'PROGRAMMING'"
                  class="secondary-line"
                  >{{ entry.has_passed ? "本环境已通过" : "尚未通过" }}</small
                >
              </td>
              <td>
                <div class="action-row">
                  <button
                    v-if="entry.effective_submission_id"
                    @click="show(entry.effective_submission_id)"
                  >
                    查看采用版本</button
                  ><button @click="versions(entry.assignment_item_id)">
                    提交历史
                  </button>
                </div>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <Pagination
        :total="progress.total"
        :offset="offset"
        :limit="20"
        @change="load"
      /></section
  ></template>
  <section v-if="history" class="card teacher-form">
    <h2>提交历史</h2>
    <p v-if="!history.total" class="hint">尚无提交。</p>
    <div class="teacher-choice-list">
      <div v-for="s in history.items" :key="s.submission_id">
        <span
          >第 {{ s.version_no }} 版 · {{ dateText(s.submitted_at) }} ·
          {{ s.status === "WITHDRAWN" ? "已撤回" : "已提交" }}</span
        ><button @click="show(s.submission_id)">查看快照</button>
      </div>
    </div>
    <Pagination
      :total="history.total"
      :offset="historyOffset"
      :limit="20"
      @change="versions(historyItem, $event)"
    />
  </section>
  <template v-if="detail"
    ><section class="card teacher-form">
      <h2>提交快照 · 第 {{ detail.version_no }} 版</h2>
      <p class="hint">
        {{ dateText(detail.submitted_at) }} ·
        {{ detail.language || "主观作答" }}
      </p>
      <CodePreview
        v-if="detail.language"
        :source="detail.content"
        :language="detail.language"
      /><MarkdownPreview v-else :source="detail.content" />
    </section>
    <JudgeFeedback
      v-if="detail.language"
      :result="detail.result"
      :job-status="detail.job?.status"
  /></template>
</template>
