<script setup lang="ts">
import { ref, onMounted } from "vue";
import { Upload, Search, Users } from "@lucide/vue";
import { request, query, errorText } from "../../shared/api";
import { session } from "../../shared/session";
import type { Page } from "./types";
import Pagination from "../../shared/Pagination.vue";
interface Student {
  id: string;
  student_no: string | null;
  full_name: string;
  login_name: string;
  status: string;
  class_name: string | null;
  class_code: string | null;
}
const data = ref<Page<Student>>(),
  classes = ref<{ id: string; name: string; code: string }[]>([]),
  search = ref(""),
  classId = ref(""),
  busy = ref(false),
  error = ref(""),
  offset = ref(0);
let sequence = 0;
async function load(next = 0) {
  const seq = ++sequence;
  offset.value = next;
  error.value = "";
  busy.value = true;
  try {
    const result = await request<Page<Student>>(
      `/teacher/courses/${session.courseId}/students?${query({ q: search.value, class_id: classId.value, limit: 20, offset: next })}`,
    );
    if (seq === sequence) data.value = result;
  } catch (e) {
    if (seq === sequence) error.value = errorText(e);
  } finally {
    if (seq === sequence) busy.value = false;
  }
}
onMounted(async () => {
  await load();
  try {
    classes.value = (
      await request<{ items: typeof classes.value }>(
        `/teacher/courses/${session.courseId}/classes`,
      )
    ).items;
  } catch (e) {
    error.value = errorText(e);
  }
});
</script>
<template>
  <div class="page-heading">
    <div>
      <span class="eyebrow">STUDENT ROSTER</span>
      <h1>学生名单</h1>
      <p>管理本课程的学生信息与班级归属。</p>
    </div>
    <RouterLink to="/teacher/students/import" class="button primary"
      ><Upload :size="17" />导入学生</RouterLink
    >
  </div>
  <div class="inline-note roster-note">
    新导入的账户为“待激活”。账户激活和密码管理沿用共享平台流程。
  </div>
  <section class="card table-card">
    <form class="toolbar" @submit.prevent="load()">
      <div class="search-input">
        <Search :size="17" /><input
          v-model="search"
          aria-label="搜索学生"
          placeholder="搜索学号或姓名"
          maxlength="100"
        />
      </div>
      <select v-model="classId" aria-label="筛选班级" @change="load()">
        <option value="">全部班级</option>
        <option v-for="c in classes" :key="c.id" :value="c.id">
          {{ c.name }} · {{ c.code }}
        </option></select
      ><button>搜索</button
      ><span v-if="data" class="toolbar-meta">{{ data.total }} 位学生</span>
    </form>
    <div v-if="error" class="alert error" role="alert">
      {{ error }}<button @click="load(offset)">重试</button>
    </div>
    <div v-if="busy" class="loading" role="status">正在读取名单…</div>
    <template v-else-if="data"
      ><div v-if="!data.total" class="empty">
        <Users :size="35" />
        <h3>暂无符合条件的学生</h3>
        <p>调整筛选条件，或使用 CSV 导入名单。</p>
      </div>
      <div v-else class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>学号</th>
              <th>姓名</th>
              <th>班级</th>
              <th>登录名</th>
              <th>账户状态</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="student in data.items" :key="student.id">
              <td class="mono">{{ student.student_no || "—" }}</td>
              <td>
                <strong>{{ student.full_name }}</strong>
              </td>
              <td>
                {{ student.class_name || "未分配"
                }}<small class="secondary-line mono">{{
                  student.class_code
                }}</small>
              </td>
              <td class="mono muted">{{ student.login_name }}</td>
              <td>
                <span
                  class="badge"
                  :class="
                    student.status === 'ACTIVE'
                      ? 'green'
                      : student.status === 'PENDING'
                        ? 'amber'
                        : 'gray'
                  "
                  >{{
                    { ACTIVE: "已激活", PENDING: "待激活", DISABLED: "已停用" }[
                      student.status
                    ] || student.status
                  }}</span
                >
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
  <p class="hint">
    学生身份和班级信息由三个模块共用。导入前可查看每一行将新增、关联或更新的内容。
  </p>
</template>
