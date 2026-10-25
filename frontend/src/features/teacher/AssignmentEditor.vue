<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref } from "vue";
import { onBeforeRouteLeave, useRoute, useRouter } from "vue-router";
import {
  request,
  post,
  errorText,
  ApiError,
  query,
  validationMessages,
} from "../../shared/api";
import { session } from "../../shared/session";
import { confirmAction } from "../../shared/confirm";
import { typeNames, type Page, dateText } from "./types";
import {
  type AssignmentChoice,
  type AssignmentItem,
  type AssignmentDetail,
  type RosterStudent,
  assignmentPayload,
  assignmentStates,
  localDate,
  equalWeights,
  utcDate,
} from "./assignmentTypes";
import Pagination from "../../shared/Pagination.vue";
import MarkdownPreview from "../../shared/MarkdownPreview.vue";
const route = useRoute(),
  router = useRouter(),
  detail = ref<AssignmentDetail>(),
  loading = ref(true),
  busy = ref(false),
  error = ref(""),
  success = ref(""),
  issues = ref<string[]>([]);
const title = ref(""),
  description = ref(""),
  deadline = ref(localDate(new Date(Date.now() + 7 * 86400000).toISOString())),
  review = ref(""),
  items = ref<AssignmentItem[]>([]),
  selected = ref<string[]>([]);
const choices = ref<Page<AssignmentChoice>>(),
  students = ref<Page<RosterStudent>>(),
  questionSearch = ref(""),
  studentSearch = ref(""),
  studentClass = ref(""),
  studentClasses = ref<{ id: string; name: string; code: string }[]>([]),
  choiceOffset = ref(0),
  studentOffset = ref(0),
  names = ref<Record<string, string>>({}),
  publishState = ref<"OPEN" | "CLOSED">("CLOSED");
const draft = computed(
  () => !detail.value || detail.value.submission_status === "DRAFT",
);
const fingerprint = () =>
  JSON.stringify({
    title: title.value,
    description: description.value,
    deadline: deadline.value,
    review: review.value,
    items: items.value,
    selected: selected.value,
    publishState: draft.value ? null : publishState.value,
  });
const original = ref("");
const dirty = computed(
  () => Boolean(original.value) && original.value !== fingerprint(),
);
function apply(a: AssignmentDetail) {
  detail.value = a;
  title.value = a.title;
  description.value = a.description_md || "";
  deadline.value = localDate(a.submission_deadline);
  review.value = a.review_deadline ? localDate(a.review_deadline) : "";
  items.value = a.items;
  selected.value = a.student_ids;
  publishState.value = a.submission_status === "OPEN" ? "OPEN" : "CLOSED";
  for (const p of a.participants)
    names.value[p.student_id] = `${p.student_no || ""} ${p.full_name}`;
  original.value = fingerprint();
}
function fail(e: unknown) {
  success.value = "";
  error.value = errorText(e);
  issues.value = e instanceof ApiError ? validationMessages(e.details) : [];
}
let choiceSequence = 0,
  studentSequence = 0;
async function loadChoices(next = 0) {
  const seq = ++choiceSequence;
  choiceOffset.value = next;
  try {
    const result = await request<Page<AssignmentChoice>>(
      `/teacher/courses/${session.courseId}/assignment-choices?${query({ q: questionSearch.value, offset: next, limit: 20 })}`,
    );
    if (seq === choiceSequence) choices.value = result;
  } catch (e) {
    fail(e);
  }
}
async function loadStudents(next = 0) {
  const seq = ++studentSequence;
  studentOffset.value = next;
  try {
    const result = await request<Page<RosterStudent>>(
      `/teacher/courses/${session.courseId}/students?${query({ q: studentSearch.value, class_id: studentClass.value, offset: next, limit: 20 })}`,
    );
    if (seq !== studentSequence) return;
    students.value = result;
    for (const s of students.value!.items)
      names.value[s.id] = `${s.student_no || ""} ${s.full_name}`;
  } catch (e) {
    fail(e);
  }
}
async function reload() {
  loading.value = true;
  error.value = "";
  try {
    if (route.params.id) {
      const a = await request<AssignmentDetail>(
        `/teacher/assignments/${route.params.id}`,
      );
      if (a.course_id !== session.courseId)
        throw new Error("该作业不属于当前课程，请切换课程后访问。");
      apply(a);
    } else original.value = fingerprint();
    if (draft.value) {
      await Promise.all([loadChoices(), loadStudents()]);
      studentClasses.value = (
        await request<{ items: typeof studentClasses.value }>(
          `/teacher/courses/${session.courseId}/classes`,
        )
      ).items;
    }
  } catch (e) {
    fail(e);
  } finally {
    loading.value = false;
  }
}
function add(choice: AssignmentChoice) {
  if (
    items.value.some(
      (i) => i.problem_version_id === choice.problem_version_id,
    ) ||
    items.value.length >= 100
  )
    return;
  items.value.push({
    ...choice,
    max_score: "100.00",
    score_weight: "1.000000",
    required_reviewers: choice.question_type === "PROGRAMMING" ? 0 : 3,
  });
  equalWeights(items.value);
}
function remove(index: number) {
  items.value.splice(index, 1);
  equalWeights(items.value);
}
function selectPage() {
  for (const s of students.value?.items || [])
    if (
      s.status !== "DISABLED" &&
      !selected.value.includes(s.id) &&
      selected.value.length < 2000
    )
      selected.value.push(s.id);
}
async function selectFiltered() {
  if (
    !(await confirmAction(
      "将当前班级和搜索条件下的全部有效学生加入应交名单？最多 2000 人，其他已选学生会保留。",
    ))
  )
    return;
  busy.value = true;
  error.value = "";
  const filter = { q: studentSearch.value, class_id: studentClass.value };
  try {
    const ids = new Set(selected.value);
    for (let offset = 0; ; offset += 100) {
      const page = await request<Page<RosterStudent>>(
        `/teacher/courses/${session.courseId}/students?${query({ ...filter, limit: 100, offset })}`,
      );
      if (page.total > 2000)
        throw new Error("筛选结果超过 2000 人，请缩小班级或搜索范围。");
      for (const s of page.items)
        if (s.status !== "DISABLED") {
          ids.add(s.id);
          names.value[s.id] = `${s.student_no || ""} ${s.full_name}`;
        }
      if (ids.size > 2000)
        throw new Error("与已选名单合并后超过 2000 人，请减少已选学生。");
      if (offset + 100 >= page.total) break;
    }
    selected.value = [...ids];
  } catch (e) {
    fail(e);
  } finally {
    busy.value = false;
  }
}
async function save() {
  busy.value = true;
  error.value = "";
  issues.value = [];
  try {
    const payload = assignmentPayload(
      title.value,
      description.value,
      deadline.value,
      review.value,
      items.value,
      selected.value,
    );
    let result: AssignmentDetail;
    if (detail.value) {
      result = await request(`/teacher/assignments/${detail.value.id}`, {
        method: "PUT",
        body: JSON.stringify({
          expected_updated_at: detail.value.updated_at,
          assignment: payload,
        }),
      });
      apply(result);
    } else {
      result = await post(
        `/teacher/courses/${session.courseId}/assignments`,
        payload,
      );
      original.value = fingerprint();
      busy.value = false;
      await router.replace(`/teacher/assignments/${result.id}`);
    }
    success.value = "作业草稿已保存";
  } catch (e) {
    fail(e);
  } finally {
    busy.value = false;
  }
}
async function publish() {
  if (dirty.value) {
    error.value = "请先保存草稿，再发布。";
    return;
  }
  if (!detail.value) return;
  if (
    !(await confirmAction(
      publishState.value === "OPEN"
        ? "确认发布并开放提交？题目版本、分值和应交名单在发布后不可修改。"
        : "确认只读发布？学生可阅读，暂不能提交。题目版本、分值和应交名单将固定。",
    ))
  )
    return;
  busy.value = true;
  error.value = "";
  issues.value = [];
  try {
    apply(
      await post(`/teacher/assignments/${detail.value.id}/publish`, {
        expected_updated_at: detail.value.updated_at,
        submission_status: publishState.value,
      }),
    );
    success.value = "作业已发布，学生端将按应交名单读取。";
  } catch (e) {
    fail(e);
  } finally {
    busy.value = false;
  }
}
async function schedule() {
  if (!detail.value) return;
  if (
    !(await confirmAction(
      publishState.value === "OPEN"
        ? "确认更新截止并开放提交？"
        : "确认更新截止并关闭新提交？已接收的评测任务会继续处理。",
    ))
  )
    return;
  busy.value = true;
  error.value = "";
  issues.value = [];
  try {
    apply(
      await post(`/teacher/assignments/${detail.value.id}/schedule`, {
        expected_updated_at: detail.value.updated_at,
        submission_deadline: utcDate(deadline.value),
        review_deadline: review.value ? utcDate(review.value) : null,
        submission_status: publishState.value,
      }),
    );
    success.value = "提交截止和开关已更新。";
  } catch (e) {
    fail(e);
  } finally {
    busy.value = false;
  }
}
onBeforeRouteLeave(async () => {
  if (busy.value) return false;
  if (dirty.value) return confirmAction("尚有未保存的作业修改，确认离开？");
  return true;
});
function beforeUnload(event: BeforeUnloadEvent) {
  if (dirty.value) {
    event.preventDefault();
    event.returnValue = "";
  }
}
onMounted(() => {
  window.addEventListener("beforeunload", beforeUnload);
  void reload();
});
onBeforeUnmount(() => window.removeEventListener("beforeunload", beforeUnload));
</script>
<template>
  <div class="page-heading">
    <div>
      <RouterLink to="/teacher/assignments">← 作业管理</RouterLink>
      <h1>{{ detail ? title : "创建作业" }}</h1>
      <p>绑定冻结版本、设置分值并确认应交名单。时间按本机时区显示。</p>
    </div>
    <span v-if="detail" class="badge">{{
      assignmentStates[detail.submission_status]
    }}</span>
  </div>
  <div v-if="error" class="alert error" role="alert">
    {{ error }}
    <ul v-if="issues.length">
      <li v-for="issue in issues" :key="issue">{{ issue }}</li>
    </ul>
    <button v-if="!dirty" @click="reload">重新载入</button>
  </div>
  <div v-if="success" class="alert success" role="status">{{ success }}</div>
  <div v-if="loading" class="loading">正在读取作业…</div>
  <template v-else>
    <form
      class="card teacher-form"
      @submit.prevent="draft ? save() : schedule()"
    >
      <h2>作业信息</h2>
      <label
        >作业名称<input
          v-model="title"
          required
          maxlength="200"
          :disabled="!draft || busy" /></label
      ><label
        >作业说明（Markdown）<textarea
          v-model="description"
          rows="4"
          maxlength="65536"
          :disabled="!draft || busy"
        /></label
      ><MarkdownPreview v-if="description" :source="description" />
      <div class="form-grid">
        <label
          >提交截止<input
            v-model="deadline"
            type="datetime-local"
            required
            :disabled="busy" /></label
        ><label
          >评审截止（可选）<input
            v-model="review"
            type="datetime-local"
            :disabled="busy"
        /></label>
      </div>
      <p class="hint">
        评审截止若设置，需晚于提交截止。本次发布不会自动启动互评。
      </p>
      <div v-if="!draft" class="form-grid">
        <label
          >提交状态<select v-model="publishState" :disabled="busy">
            <option value="CLOSED">关闭提交（仍可阅读）</option>
            <option value="OPEN">开放提交</option>
          </select></label
        >
        <div>
          <p>
            首次发布：{{
              detail?.published_at ? dateText(detail.published_at) : "—"
            }}
          </p>
          <button type="submit" :disabled="busy">更新截止与开关</button>
        </div>
      </div>
      <button v-if="draft" type="submit" class="primary" :disabled="busy">
        保存草稿
      </button>
    </form>
    <section class="card teacher-form">
      <div class="section-heading">
        <h2>已选题目 · {{ items.length }} 题</h2>
        <button
          v-if="draft"
          :disabled="busy || !items.length"
          @click="equalWeights(items)"
        >
          平均分配权重
        </button>
      </div>
      <p class="hint">
        发布时各题权重之和须为 1。主观题的评审人数仅保留配置，不触发互评。
      </p>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>固定题目版本</th>
              <th>满分</th>
              <th>权重</th>
              <th>评审人数</th>
              <th v-if="draft">操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(item, index) in items" :key="item.problem_version_id">
              <td>
                {{ item.code }} · {{ item.title
                }}<small class="secondary-line"
                  >{{ typeNames[item.question_type] }} · v{{
                    item.version_no
                  }}</small
                >
              </td>
              <td>
                <input
                  v-model="item.max_score"
                  aria-label="题目满分"
                  type="number"
                  min="0.01"
                  step="0.01"
                  :disabled="!draft || busy"
                />
              </td>
              <td>
                <input
                  v-model="item.score_weight"
                  aria-label="题目权重"
                  type="number"
                  min="0.000001"
                  max="1"
                  step="0.000001"
                  :disabled="!draft || busy"
                />
              </td>
              <td>
                <input
                  v-model.number="item.required_reviewers"
                  aria-label="评审人数"
                  type="number"
                  min="1"
                  max="10"
                  :disabled="
                    !draft || busy || item.question_type === 'PROGRAMMING'
                  "
                />
              </td>
              <td v-if="draft">
                <button :disabled="busy" @click="remove(index)">移除</button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="!items.length" class="hint">
        还未选题，请先在题库完成题目冻结。
      </p>
      <template v-if="draft"
        ><form class="toolbar" @submit.prevent="loadChoices()">
          <input
            v-model="questionSearch"
            aria-label="搜索冻结题目"
            placeholder="按题号或标题搜索冻结版本"
            maxlength="100"
          /><button :disabled="busy">查找题目</button>
        </form>
        <div class="teacher-choice-list">
          <div
            v-for="choice in choices?.items"
            :key="choice.problem_version_id"
          >
            <span
              >{{ choice.code }} · {{ choice.title }} · v{{ choice.version_no
              }}<small class="secondary-line">{{
                typeNames[choice.question_type]
              }}</small></span
            ><button
              :disabled="
                busy ||
                items.some(
                  (i) => i.problem_version_id === choice.problem_version_id,
                ) ||
                items.length >= 100
              "
              @click="add(choice)"
            >
              添加
            </button>
          </div>
        </div>
        <Pagination
          v-if="choices"
          :total="choices.total"
          :offset="choiceOffset"
          :limit="20"
          @change="loadChoices"
      /></template>
    </section>
    <section class="card teacher-form">
      <h2>应交名单 · {{ selected.length }} 人</h2>
      <p class="hint">
        发布时保存班级快照；之后导入新学生不会自动加入这份作业。待开通学生需先在学生名单中开通账号。
      </p>
      <template v-if="draft"
        ><form class="toolbar" @submit.prevent="loadStudents()">
          <input
            v-model="studentSearch"
            aria-label="搜索应交学生"
            placeholder="搜索学号或姓名"
            maxlength="100"
            :disabled="busy"
          /><select
            v-model="studentClass"
            aria-label="筛选应交班级"
            :disabled="busy"
            @change="loadStudents()"
          >
            <option value="">全部班级</option>
            <option v-for="c in studentClasses" :key="c.id" :value="c.id">
              {{ c.name }} · {{ c.code }}
            </option></select
          ><button :disabled="busy">查找学生</button
          ><button type="button" :disabled="busy" @click="selectPage">
            选中当前页
          </button>
          <button type="button" :disabled="busy" @click="selectFiltered">
            加入全部筛选结果
          </button>
        </form>
        <div class="teacher-choice-list">
          <label v-for="student in students?.items" :key="student.id"
            ><input
              v-model="selected"
              type="checkbox"
              :value="student.id"
              :disabled="
                busy ||
                student.status === 'DISABLED' ||
                (!selected.includes(student.id) && selected.length >= 2000)
              "
            />{{ student.student_no }} · {{ student.full_name }} ·
            {{ student.class_name
            }}<span class="muted">{{
              student.status === "ACTIVE"
                ? "已开通"
                : student.status === "PENDING"
                  ? "待开通"
                  : "已停用"
            }}</span></label
          >
        </div>
        <Pagination
          v-if="students"
          :total="students.total"
          :offset="studentOffset"
          :limit="20"
          @change="loadStudents"
      /></template>
      <details v-if="selected.length">
        <summary>查看已选名单</summary>
        <div class="teacher-choice-list">
          <div v-for="id in selected" :key="id">
            <span>{{ names[id] || id }}</span
            ><button
              v-if="draft"
              :disabled="busy"
              @click="selected = selected.filter((v) => v !== id)"
            >
              取消选择</button
            ><RouterLink
              v-else
              :to="`/teacher/students/${id}/progress?assignment_id=${detail?.id}`"
              >查看提交进度</RouterLink
            >
          </div>
        </div>
      </details>
    </section>
    <section v-if="draft && detail" class="card teacher-form">
      <h2>发布检查</h2>
      <p>
        发布后题目、配置、分值和名单固定；可继续调整截止、关闭或重新开放提交。
      </p>
      <label
        >发布方式<select v-model="publishState" :disabled="busy">
          <option value="CLOSED">只读发布，暂不开放提交</option>
          <option value="OPEN">发布并开放提交</option>
        </select></label
      >
      <p class="hint">
        开放提交前会校验当前评测节点支持的语言和预算。LOCAL
        在服务主机运行程序，团队部署时需按评测运行说明配置隔离和执行环境。
      </p>
      <button class="primary" :disabled="busy || dirty" @click="publish">
        确认发布
      </button>
      <p v-if="dirty" class="hint">请先保存修改后再发布。</p>
    </section>
  </template>
</template>
