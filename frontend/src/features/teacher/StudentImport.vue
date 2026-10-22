<script setup lang="ts">
import { computed, ref } from "vue";
import {
  ArrowLeft,
  Download,
  UploadCloud,
  FileSpreadsheet,
  CheckCircle2,
  ArrowRight,
  RefreshCw,
} from "@lucide/vue";
import { onBeforeRouteLeave } from "vue-router";
import { confirmAction } from "../../shared/confirm";
import { session } from "../../shared/session";
import { request, token, errorText, ApiError } from "../../shared/api";
interface ImportRow {
  row_number: number;
  student_no: string;
  full_name: string;
  class_name: string;
  action: string;
  errors: string[];
  changes: unknown[];
}
interface Preview {
  valid: boolean;
  rows: ImportRow[];
  summary: Record<string, number>;
  requires_update_confirmation: boolean;
  preview_token: string | null;
  content_sha256: string;
  expires_at: string;
}
interface Result {
  summary: Record<string, number>;
  rows: number;
  replayed: boolean;
}
const file = ref<File>(),
  data = ref<Preview>(),
  result = ref<Result>(),
  allowUpdates = ref(false),
  busy = ref(false),
  error = ref(""),
  limit = ref(50),
  dragging = ref(false);
const labels: Record<string, string> = {
  created_students: "新增学生",
  enrolled_students: "关联课程",
  updated_profiles: "更新资料",
  unchanged_students: "无需修改",
  created_classes: "新增班级",
};
const actions: Record<string, string> = {
  CREATE: "新增学生",
  ENROLL: "关联课程",
  UPDATE: "更新资料",
  UNCHANGED: "无需修改",
  ERROR: "需修正",
};
const canConfirm = computed(
  () =>
    data.value?.valid &&
    (!data.value.requires_update_confirmation || allowUpdates.value) &&
    !busy.value &&
    !result.value,
);
function choose(selected?: File) {
  if (busy.value) return;
  file.value = selected;
  data.value = undefined;
  result.value = undefined;
  allowUpdates.value = false;
  error.value = "";
  limit.value = 50;
  if (selected && selected.size > 2 * 1024 * 1024)
    error.value = "文件不能超过 2 MiB。";
}
function drop(event: DragEvent) {
  dragging.value = false;
  choose(event.dataTransfer?.files[0]);
}
async function download() {
  error.value = "";
  try {
    const response = await fetch(
      `/api/v1/teacher/courses/${session.courseId}/students/import/template`,
      { headers: { Authorization: `Bearer ${token()}` } },
    );
    if (!response.ok) throw new Error("模板下载失败，请确认登录有效后重试。");
    const url = URL.createObjectURL(await response.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = "students-template.csv";
    a.click();
    URL.revokeObjectURL(url);
  } catch (e) {
    error.value = errorText(e);
  }
}
async function preview() {
  if (!file.value || file.value.size > 2 * 1024 * 1024) return;
  busy.value = true;
  error.value = "";
  result.value = undefined;
  data.value = undefined;
  allowUpdates.value = false;
  try {
    const body = new FormData();
    body.append("file", file.value);
    data.value = await request(
      `/teacher/courses/${session.courseId}/students/import/preview`,
      { method: "POST", body },
    );
  } catch (e) {
    error.value = errorText(e);
  } finally {
    busy.value = false;
  }
}
async function confirm() {
  if (!canConfirm.value || !data.value?.preview_token || !file.value) return;
  busy.value = true;
  error.value = "";
  try {
    const body = new FormData();
    body.append("file", file.value);
    body.append("expected_sha256", data.value.content_sha256);
    body.append("preview_token", data.value.preview_token);
    body.append("allow_updates", String(allowUpdates.value));
    result.value = await request(
      `/teacher/courses/${session.courseId}/students/import/confirm`,
      { method: "POST", body },
    );
  } catch (e) {
    error.value = errorText(e);
    if (e instanceof ApiError && e.status === 409) data.value = undefined;
  } finally {
    busy.value = false;
  }
}
onBeforeRouteLeave(
  async () =>
    !busy.value ||
    (await confirmAction(
      "导入请求正在处理中，离开后可在学生名单中核对结果。确认离开？",
    )),
);
</script>
<template>
  <RouterLink to="/teacher/students" class="back-link"
    ><ArrowLeft :size="16" />返回学生名单</RouterLink
  >
  <div class="page-heading">
    <div>
      <span class="eyebrow">IMPORT STUDENTS</span>
      <h1>导入学生名单</h1>
      <p>先检查，再入库。让每一次数据变更清晰可见。</p>
    </div>
    <button :disabled="busy" @click="download">
      <Download :size="16" />下载 CSV 模板
    </button>
  </div>
  <ol class="steps">
    <li class="active"><span>1</span>上传文件</li>
    <li :class="{ active: data || result }"><span>2</span>预览与校验</li>
    <li :class="{ active: result }"><span>3</span>确认导入</li>
  </ol>
  <div v-if="error" class="alert error" role="alert">{{ error }}</div>
  <section v-if="result" class="card import-success" role="status">
    <CheckCircle2 :size="44" />
    <h2>{{ result.replayed ? "名单已是最新状态" : "学生名单导入完成" }}</h2>
    <p>
      已处理 {{ result.rows }} 行记录。{{
        result.replayed
          ? "没有产生重复学生或课程成员。"
          : "所有变更已在同一事务中保存。"
      }}
    </p>
    <div class="import-summary">
      <div v-for="(value, key) in result.summary" :key="key">
        <strong>{{ value }}</strong
        ><span>{{ labels[key] || key }}</span>
      </div>
    </div>
    <RouterLink to="/teacher/students" class="button primary"
      >查看学生名单<ArrowRight :size="16"
    /></RouterLink>
  </section>
  <template v-else
    ><div class="import-layout">
      <section class="card upload-card">
        <div class="card-heading">
          <h2>上传 CSV 文件</h2>
          <span class="small-label">UTF-8 · 最大 2 MiB</span>
        </div>
        <div class="form-body">
          <label
            class="dropzone"
            :class="{ dragging, disabled: busy }"
            @dragover.prevent="dragging = true"
            @dragleave.prevent="dragging = false"
            @drop.prevent="drop"
            ><input
              type="file"
              accept=".csv,text/csv"
              :disabled="busy"
              aria-label="上传学生 CSV 文件"
              @change="choose(($event.target as HTMLInputElement).files?.[0])"
            /><UploadCloud :size="32" /><strong>{{
              file ? file.name : "点击选择，或将 CSV 文件拖放至此"
            }}</strong
            ><span>{{
              file
                ? `${(file.size / 1024).toFixed(1)} KiB · 点击重新选择`
                : "建议先下载模板，按列填写后另存为 CSV UTF-8"
            }}</span></label
          ><button
            class="primary full"
            :disabled="
              !file || busy || Boolean(file && file.size > 2 * 1024 * 1024)
            "
            @click="preview"
          >
            <RefreshCw v-if="data" :size="16" /><FileSpreadsheet
              v-else
              :size="17"
            />{{ busy ? "正在处理…" : data ? "重新预览" : "预览并校验" }}
          </button>
        </div>
      </section>
      <section class="import-instructions">
        <h3>填写说明</h3>
        <p>
          <code>student_no</code> 学号 · <code>full_name</code> 姓名<br /><code
            >class_name</code
          >
          班级名称 · 均为必填
        </p>
        <p>
          <code>class_code</code> 班级编号为选填；同名班级存在歧义时必须填写。
        </p>
        <p>
          每次最多 2,000
          行。请将学号列设为文本，保留前导零。模板中的示例行请替换为实际学生。
        </p>
        <p>跨课程的姓名、班级冲突会阻止导入；未出现在文件中的学生会保留。</p>
      </section>
    </div>
    <section v-if="data" class="card table-card preview-card">
      <div class="card-heading">
        <h2>
          校验结果
          <span class="badge" :class="data.valid ? 'green' : 'amber'">{{
            data.valid ? "全部通过" : "需要修正"
          }}</span>
        </h2>
        <span class="small-label">共 {{ data.rows.length }} 行</span>
      </div>
      <div class="import-summary">
        <div v-for="(value, key) in data.summary" :key="key">
          <strong>{{ value }}</strong
          ><span>{{ labels[key] || key }}</span>
        </div>
      </div>
      <div v-if="!data.valid" class="alert warning">
        文件包含错误，本次不会写入任何数据。请修正文件后重新预览。
      </div>
      <div class="table-scroll">
        <table>
          <thead>
            <tr>
              <th>行号</th>
              <th>学号</th>
              <th>姓名</th>
              <th>班级</th>
              <th>处理方式</th>
              <th>校验 / 变更详情</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in data.rows.slice(0, limit)" :key="row.row_number">
              <td class="muted">{{ row.row_number }}</td>
              <td class="mono">{{ row.student_no }}</td>
              <td>{{ row.full_name }}</td>
              <td>{{ row.class_name }}</td>
              <td>
                <span
                  class="badge"
                  :class="
                    row.errors.length
                      ? 'red'
                      : row.action === 'UPDATE'
                        ? 'amber'
                        : row.action === 'UNCHANGED'
                          ? 'gray'
                          : 'green'
                  "
                  >{{
                    row.errors.length
                      ? "需修正"
                      : actions[row.action] || row.action
                  }}</span
                >
              </td>
              <td>
                <div
                  v-for="(err, i) in row.errors"
                  :key="i"
                  class="danger-text"
                >
                  {{ err }}
                </div>
                <div v-if="row.changes?.length" class="change-detail">
                  {{ row.changes.join("；") }}
                </div>
                <span
                  v-if="!row.errors.length && !row.changes?.length"
                  class="muted"
                  >—</span
                >
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="limit < data.rows.length" class="load-more">
        <button @click="limit += 100">
          继续显示 100 行（剩余 {{ data.rows.length - limit }} 行）
        </button>
      </div>
      <div class="import-confirm">
        <label v-if="data.requires_update_confirmation" class="check-label"
          ><input
            v-model="allowUpdates"
            type="checkbox"
            :disabled="busy"
          />我已核对并同意更新本课程已有学生的姓名、班级信息</label
        >
        <p class="hint">
          预览有效期为 15 分钟。文件或数据库资料变化后，需要重新预览。
        </p>
        <button class="primary" :disabled="!canConfirm" @click="confirm">
          确认导入<ArrowRight :size="16" />
        </button>
      </div></section
  ></template>
</template>
