<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from "vue";
import { onBeforeRouteLeave } from "vue-router";
import { Upload, Search, Users } from "@lucide/vue";
import { request, post, query, errorText } from "../../shared/api";
import { confirmAction } from "../../shared/confirm";
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
  updated_at: string;
  must_change_password: boolean;
}
interface Credential {
  student_id: string;
  student_no: string;
  full_name: string;
  login_name: string;
  initial_password: string;
}
const selected = ref<string[]>([]),
  issuing = ref(false),
  credentials = ref<Credential[]>([]);
async function issue(action: "ACTIVATE" | "RESET", single?: Student) {
  const targets = single
    ? [single]
    : (data.value?.items || []).filter((s) => selected.value.includes(s.id));
  if (!targets.length || issuing.value) return;
  if (
    !(await confirmAction(
      action === "ACTIVATE"
        ? `确认开通 ${targets.length} 个账号并生成独立初始密码？`
        : `确认重置 ${targets.length} 个账号？旧密码和全部旧会话将失效，学生需重新改密。`,
    ))
  )
    return;
  issuing.value = true;
  error.value = "";
  credentials.value = [];
  try {
    const result = await post<{ credentials: Credential[] }>(
      `/teacher/courses/${session.courseId}/students/credentials`,
      {
        action,
        students: targets.map((s) => ({
          student_id: s.id,
          expected_updated_at: s.updated_at,
        })),
      },
    );
    credentials.value = result.credentials;
    await load(offset.value);
  } catch (e) {
    error.value = errorText(e);
  } finally {
    issuing.value = false;
  }
}
function downloadCredentials() {
  const text = credentials.value
    .map(
      (c) =>
        `学号：${c.student_no}\n姓名：${c.full_name}\n登录名：${c.login_name}\n初始密码：${c.initial_password}\n首次登录必须改密\n`,
    )
    .join("\n");
  const url = URL.createObjectURL(
    new Blob([text], { type: "text/plain;charset=utf-8" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = "student-initial-passwords.txt";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
onBeforeRouteLeave(async () => {
  if (issuing.value) return false;
  if (
    credentials.value.length &&
    !(await confirmAction(
      "初始密码仅在本页显示一次，确认已妥善发放或保存后离开？",
    ))
  )
    return false;
  credentials.value = [];
  return true;
});
onBeforeUnmount(() => {
  credentials.value = [];
  window.removeEventListener("beforeunload", protectCredentials);
});
function protectCredentials(event: BeforeUnloadEvent) {
  if (credentials.value.length || issuing.value) {
    event.preventDefault();
    event.returnValue = "";
  }
}
onMounted(() => window.addEventListener("beforeunload", protectCredentials));
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
  selected.value = [];
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
    导入后仍需开通账号。开通或重置将生成独立初始密码，学生首次登录必须改密；重复导入不改密码。
  </div>
  <section
    v-if="credentials.length"
    class="card teacher-form"
    aria-label="初始密码发放"
  >
    <h2>初始密码已生成 · {{ credentials.length }} 人</h2>
    <p>
      仅本次响应展示，请分别发放给对应学生。离开本页后无法再次查询明文；遗失时需重新重置。
    </p>
    <div class="table-scroll">
      <table>
        <thead>
          <tr>
            <th>学号</th>
            <th>姓名</th>
            <th>登录名</th>
            <th>初始密码</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in credentials" :key="c.student_id">
            <td>{{ c.student_no }}</td>
            <td>{{ c.full_name }}</td>
            <td>{{ c.login_name }}</td>
            <td>
              <code>{{ c.initial_password }}</code>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
    <div class="action-row">
      <button @click="downloadCredentials">下载发放清单</button
      ><button @click="credentials = []">已保存，清除本页明文</button>
    </div>
  </section>
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
    <div class="toolbar">
      <span>当前页已选 {{ selected.length }} 人</span
      ><button
        :disabled="issuing || !selected.length || Boolean(credentials.length)"
        @click="issue('ACTIVATE')"
      >
        开通所选账号</button
      ><button
        :disabled="issuing || !selected.length || Boolean(credentials.length)"
        @click="issue('RESET')"
      >
        重置所选密码</button
      ><span v-if="credentials.length" class="hint"
        >请先保存并清除上次明文，再进行下一批。</span
      >
    </div>
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
              <th>选择</th>
              <th>学号</th>
              <th>姓名</th>
              <th>班级</th>
              <th>登录名</th>
              <th>账户状态</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="student in data.items" :key="student.id">
              <td>
                <input
                  v-model="selected"
                  type="checkbox"
                  :value="student.id"
                  :aria-label="`选择 ${student.full_name}`"
                  :disabled="issuing || student.status === 'DISABLED'"
                />
              </td>
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
                    { ACTIVE: "已开通", PENDING: "待开通", DISABLED: "已停用" }[
                      student.status
                    ] || student.status
                  }}</span
                >
              </td>
              <td>
                <div class="action-row">
                  <button
                    v-if="student.status === 'PENDING'"
                    :disabled="issuing || Boolean(credentials.length)"
                    @click="issue('ACTIVATE', student)"
                  >
                    开通账号</button
                  ><button
                    v-if="student.status === 'ACTIVE'"
                    :disabled="issuing || Boolean(credentials.length)"
                    @click="issue('RESET', student)"
                  >
                    重置密码</button
                  ><RouterLink :to="`/teacher/students/${student.id}/progress`"
                    >提交进度</RouterLink
                  >
                </div>
                <small
                  v-if="student.must_change_password"
                  class="secondary-line"
                  >下次登录需改密</small
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
