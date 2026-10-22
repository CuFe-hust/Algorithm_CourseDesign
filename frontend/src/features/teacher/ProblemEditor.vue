<script setup lang="ts">
import { computed, onMounted, onBeforeUnmount, ref, watch, toRaw } from "vue";
import { onBeforeRouteLeave, useRoute, useRouter } from "vue-router";
import {
  ArrowLeft,
  Save,
  LockKeyhole,
  CopyPlus,
  Archive,
  RotateCcw,
  Plus,
  Trash2,
  Eye,
  PencilLine,
} from "@lucide/vue";
import {
  request,
  post,
  errorText,
  validationMessages,
  ApiError,
} from "../../shared/api";
import { session } from "../../shared/session";
import {
  newVersion,
  editable,
  typeNames,
  type Version,
  type VersionInput,
  type Problem,
  type QuestionType,
} from "./types";
import { confirmAction } from "../../shared/confirm";
import MarkdownPreview from "../../shared/MarkdownPreview.vue";
import CodePreview from "../../shared/CodePreview.vue";
const route = useRoute(),
  router = useRouter(),
  existing = computed(() => Boolean(route.params.id));
const detail = ref<Problem>(),
  current = ref<Version>(),
  form = ref<VersionInput>(newVersion()),
  code = ref(""),
  type = ref<QuestionType>("ALGORITHM_ANALYSIS");
const tags = ref<{ id: string; name: string }[]>([]),
  newTag = ref(""),
  busy = ref(false),
  loading = ref(true),
  error = ref(""),
  success = ref(""),
  errors = ref<unknown>(),
  tab = ref("content"),
  preview = ref(false),
  original = ref("");
const locked = computed(
  () =>
    current.value?.status === "FROZEN" || detail.value?.status === "ARCHIVED",
);
const issues = computed(() => validationMessages(errors.value));
const fingerprint = () =>
  JSON.stringify({ form: form.value, code: code.value, type: type.value });
const dirty = computed(
  () =>
    !locked.value && original.value !== "" && original.value !== fingerprint(),
);
function setVersion(v: Version) {
  current.value = v;
  type.value = v.question_type;
  code.value = v.code;
  form.value = editable(v);
  if (type.value === "PROGRAMMING" && !form.value.test_suite)
    form.value.test_suite = newVersion(true).test_suite;
  if (type.value !== "PROGRAMMING" && !form.value.rubric)
    form.value.rubric = newVersion().rubric;
  original.value = fingerprint();
}
async function reload(versionId?: string) {
  loading.value = true;
  error.value = "";
  try {
    tags.value = (
      await request<{ items: typeof tags.value }>(
        `/teacher/courses/${session.courseId}/knowledge-points`,
      )
    ).items;
    if (existing.value) {
      const data = await request<Problem>(
        `/teacher/problems/${route.params.id}`,
      );
      if (data.course_id !== session.courseId) {
        throw new Error("该题目不属于当前课程，请切换课程后访问。");
      }
      detail.value = data;
      setVersion(
        versionId
          ? await request<Version>(`/teacher/problem-versions/${versionId}`)
          : data.latest_version,
      );
    } else original.value = fingerprint();
  } catch (e) {
    error.value = errorText(e);
  } finally {
    loading.value = false;
  }
}
function changeType() {
  form.value.test_suite =
    type.value === "PROGRAMMING" ? newVersion(true).test_suite : null;
  form.value.rubric = type.value === "PROGRAMMING" ? null : newVersion().rubric;
}
function displayError(e: unknown) {
  success.value = "";
  error.value = errorText(e);
  errors.value = e instanceof ApiError ? e.details : null;
}
async function save(): Promise<boolean> {
  busy.value = true;
  error.value = "";
  success.value = "";
  errors.value = null;
  try {
    const version = editable(toRaw(form.value));
    if (!existing.value) {
      const result = await post<Version>(
        `/teacher/courses/${session.courseId}/problems`,
        { code: code.value.trim(), question_type: type.value, version },
      );
      original.value = fingerprint();
      await router.replace(`/teacher/problems/${result.problem_id}`);
    } else {
      const result = await request<Version>(
        `/teacher/problem-versions/${current.value!.id}`,
        {
          method: "PUT",
          body: JSON.stringify({
            expected_updated_at: current.value!.updated_at,
            version,
          }),
        },
      );
      setVersion(result);
    }
    success.value = "草稿已保存";
    return true;
  } catch (e) {
    displayError(e);
    return false;
  } finally {
    busy.value = false;
  }
}
async function freeze() {
  if (dirty.value) {
    error.value = "请先保存草稿，再冻结此版本。";
    return;
  }
  if (
    !(await confirmAction(
      "冻结后此版本将只读，后续修改需创建新版本。确认冻结？",
    ))
  )
    return;
  busy.value = true;
  error.value = "";
  errors.value = null;
  try {
    const v = await post<Version>(
      `/teacher/problem-versions/${current.value!.id}/freeze`,
      { expected_updated_at: current.value!.updated_at },
    );
    setVersion(v);
    success.value = "此版本已冻结，可供作业模块引用。";
    await reload(v.id);
  } catch (e) {
    displayError(e);
  } finally {
    busy.value = false;
  }
}
async function fork() {
  busy.value = true;
  error.value = "";
  try {
    const v = await post<Version>(
      `/teacher/problems/${detail.value!.id}/versions`,
      { source_version_id: current.value!.id },
    );
    await reload(v.id);
    success.value = `已创建 v${v.version_no} 草稿`;
  } catch (e) {
    displayError(e);
  } finally {
    busy.value = false;
  }
}
async function archive() {
  const archived = detail.value?.status === "ARCHIVED";
  if (
    !(await confirmAction(
      archived ? "确认恢复此题目？" : "确认归档此题目？已有作业仍保留原版本。",
    ))
  )
    return;
  busy.value = true;
  error.value = "";
  try {
    await post(
      `/teacher/problems/${detail.value!.id}/${archived ? "restore" : "archive"}`,
    );
    await reload(current.value?.id);
    success.value = archived ? "题目已恢复" : "题目已归档";
  } catch (e) {
    displayError(e);
  } finally {
    busy.value = false;
  }
}
async function addTag() {
  if (!newTag.value.trim()) return;
  busy.value = true;
  try {
    const tag = await post<{ id: string; name: string }>(
      `/teacher/courses/${session.courseId}/knowledge-points`,
      { name: newTag.value.trim() },
    );
    if (!tags.value.some((t) => t.id === tag.id)) tags.value.push(tag);
    if (!form.value.knowledge_point_ids.includes(tag.id))
      form.value.knowledge_point_ids.push(tag.id);
    newTag.value = "";
  } catch (e) {
    displayError(e);
  } finally {
    busy.value = false;
  }
}
async function chooseVersion(event: Event) {
  const target = event.target as HTMLSelectElement;
  if (
    dirty.value &&
    !(await confirmAction("草稿尚未保存，确认切换版本并放弃修改？"))
  ) {
    target.value = current.value!.id;
    return;
  }
  await reload(target.value);
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (dirty.value) {
    event.preventDefault();
    event.returnValue = "";
  }
}
onBeforeRouteLeave(
  async () =>
    !dirty.value || (await confirmAction("草稿尚未保存，确认离开并放弃修改？")),
);
onMounted(() => {
  void reload();
  window.addEventListener("beforeunload", beforeUnload);
});
onBeforeUnmount(() => window.removeEventListener("beforeunload", beforeUnload));
watch(tab, () => {
  preview.value = false;
});
</script>
<template>
  <RouterLink to="/teacher/problems" class="back-link"
    ><ArrowLeft :size="16" />返回题库</RouterLink
  >
  <div class="page-heading editor-heading">
    <div>
      <span class="eyebrow">QUESTION EDITOR</span>
      <h1>
        {{ existing ? "题目详情" : "创建题目"
        }}<span
          v-if="current"
          class="badge"
          :class="locked ? 'green' : 'amber'"
          >{{
            detail?.status === "ARCHIVED"
              ? "已归档"
              : current.status === "FROZEN"
                ? "已冻结"
                : "草稿"
          }}</span
        >
      </h1>
      <p>
        {{
          locked
            ? "此版本只读，内容和配置完整保留。"
            : "先保存草稿，完善配置后再冻结版本。"
        }}<span v-if="dirty" class="unsaved"> · 有未保存修改</span>
      </p>
    </div>
    <div class="button-row">
      <template v-if="existing && current"
        ><button :disabled="busy || dirty" @click="archive">
          <RotateCcw v-if="detail?.status === 'ARCHIVED'" :size="16" /><Archive
            v-else
            :size="16"
          />{{ detail?.status === "ARCHIVED" ? "恢复" : "归档" }}</button
        ><button
          v-if="current.status === 'FROZEN' && detail?.status !== 'ARCHIVED'"
          class="primary"
          :disabled="busy"
          @click="fork"
        >
          <CopyPlus :size="16" />创建新版本</button
        ><button v-if="!locked" :disabled="busy || dirty" @click="freeze">
          <LockKeyhole :size="16" />冻结版本
        </button></template
      ><button
        v-if="!locked"
        class="primary"
        :disabled="busy || loading || (!current && existing)"
        form="question-form"
      >
        <Save :size="16" />{{ busy ? "正在处理…" : "保存草稿" }}
      </button>
    </div>
  </div>
  <div v-if="error" class="alert error" role="alert">
    {{ error }}
    <ul v-if="issues.length">
      <li v-for="issue in issues" :key="issue">{{ issue }}</li>
    </ul>
    <button v-if="!current && existing" @click="reload()">重试</button>
  </div>
  <div v-if="success" class="alert success" role="status">{{ success }}</div>
  <div v-if="loading" class="loading">正在读取题目…</div>
  <form
    v-else-if="!existing || current"
    id="question-form"
    @submit.prevent="save"
  >
    <div class="editor-layout">
      <div class="editor-main">
        <section class="card">
          <div class="card-heading">
            <h2>基本信息</h2>
            <span v-if="current" class="mono small-label"
              >{{ code }} · v{{ current.version_no }}</span
            >
          </div>
          <fieldset :disabled="locked || busy" class="form-body">
            <label
              >题目名称 <span class="required">*</span
              ><input
                v-model="form.title"
                required
                maxlength="200"
                placeholder="用清晰的标题描述问题"
            /></label>
            <div class="form-grid">
              <label
                >题目编号 <span class="required">*</span
                ><input
                  v-model="code"
                  :disabled="existing"
                  required
                  pattern="[A-Za-z0-9][A-Za-z0-9_.\-]{0,31}"
                  maxlength="32"
                  placeholder="例如 ANALYSIS-021"
                /><small>创建后固定，课程内唯一</small></label
              ><label
                >题型<select
                  v-model="type"
                  aria-label="题型"
                  :disabled="existing"
                  @change="changeType"
                >
                  <option
                    v-for="(name, key) in typeNames"
                    :key="key"
                    :value="key"
                  >
                    {{ name }}
                  </option>
                </select></label
              >
            </div>
          </fieldset>
        </section>
        <section class="card editor-content">
          <div class="editor-tabs" role="tablist" aria-label="编辑内容">
            <button
              v-for="t in [
                { id: 'content', label: '题目内容' },
                { id: 'answer', label: '参考答案' },
                {
                  id: 'config',
                  label: type === 'PROGRAMMING' ? '测试配置' : '评分量表',
                },
              ]"
              :key="t.id"
              type="button"
              role="tab"
              :aria-selected="tab === t.id"
              :class="{ active: tab === t.id }"
              @click="tab = t.id"
            >
              {{ t.label }}
            </button>
          </div>
          <fieldset :disabled="locked || busy" class="form-body">
            <template v-if="tab === 'content'"
              ><div class="field-heading">
                <strong>题干 <span class="required">*</span></strong
                ><button
                  type="button"
                  class="small"
                  v-if="!locked"
                  @click="preview = !preview"
                >
                  <PencilLine v-if="preview" :size="14" /><Eye
                    v-else
                    :size="14"
                  />{{ preview ? "编辑" : "预览" }}
                </button>
              </div>
              <MarkdownPreview
                v-if="preview || locked"
                :source="form.statement_md" /><textarea
                v-else
                v-model="form.statement_md"
                aria-label="题干"
                required
                rows="13"
                maxlength="262144"
                class="code-input"
                placeholder="支持 Markdown、代码块和 $LaTeX$ 公式"
              ></textarea
              ><label
                >作答要求<textarea
                  v-model="form.answer_requirements_md"
                  rows="3"
                  maxlength="65536"
                  placeholder="说明需要提交的内容、证明步骤或复杂度分析要求"
                ></textarea></label
              ><template v-if="type === 'PROGRAMMING'"
                ><div class="form-grid">
                  <label
                    >输入格式<textarea
                      v-model="form.input_spec_md"
                      rows="4"
                      maxlength="65536"
                    ></textarea></label
                  ><label
                    >输出格式<textarea
                      v-model="form.output_spec_md"
                      rows="4"
                      maxlength="65536"
                    ></textarea>
                  </label>
                </div>
                <label
                  >数据范围<textarea
                    v-model="form.data_constraints_md"
                    rows="3"
                    maxlength="65536"
                  ></textarea></label></template
              ><label
                >公开示例（Markdown）<textarea
                  v-model="form.public_examples_md"
                  class="code-input"
                  rows="4"
                  maxlength="65536"
                  placeholder="可使用代码块展示输入输出"
                ></textarea></label></template
            ><template v-if="tab === 'answer'"
              ><p class="inline-note">
                参考答案仅通过教师接口返回，不会在学生题目响应中公开。
              </p>
              <div
                v-for="(answer, i) in form.reference_solutions"
                :key="i"
                class="subcard"
              >
                <div class="field-heading">
                  <strong>参考答案 {{ i + 1 }}</strong
                  ><button
                    v-if="!locked"
                    class="danger-text small"
                    type="button"
                    :aria-label="`删除参考答案 ${i + 1}`"
                    @click="form.reference_solutions.splice(i, 1)"
                  >
                    <Trash2 :size="15" />删除
                  </button>
                </div>
                <label
                  >语言<select
                    v-model="answer.language"
                    :aria-label="`参考答案语言 ${i + 1}`"
                  >
                    <option :value="null">文字 / Markdown</option>
                    <option value="python3">Python 3</option>
                    <option value="cpp">C++</option>
                    <option value="c">C</option>
                    <option value="java">Java</option>
                    <option
                      v-if="
                        answer.language &&
                        !['python3', 'cpp', 'c', 'java'].includes(
                          answer.language,
                        )
                      "
                      :value="answer.language"
                    >
                      {{ answer.language }}
                    </option>
                  </select></label
                ><template v-if="locked">
                  <CodePreview
                    v-if="answer.language"
                    :source="answer.content"
                    :language="answer.language"
                  />
                  <MarkdownPreview v-else :source="answer.content" /> </template
                ><textarea
                  v-else
                  v-model="answer.content"
                  :aria-label="`参考答案内容 ${i + 1}`"
                  class="code-input"
                  rows="12"
                  maxlength="262144"
                  placeholder="填写完整解答、推导过程或参考代码"
                ></textarea>
              </div>
              <button
                v-if="!locked"
                type="button"
                class="dashed full"
                :disabled="form.reference_solutions.length >= 20"
                @click="
                  form.reference_solutions.push({ language: null, content: '' })
                "
              >
                <Plus :size="16" />添加参考答案
              </button>
              <p v-if="!form.reference_solutions.length" class="hint">
                冻结前至少需要一份非空参考答案。
              </p></template
            ><template v-if="tab === 'config'"
              ><template v-if="form.test_suite"
                ><div class="form-grid">
                  <label
                    >CPU 时限（ms）<input
                      v-model.number="form.test_suite.cpu_limit_ms"
                      type="number"
                      min="100"
                      max="30000" /></label
                  ><label
                    >内存上限（KiB）<input
                      v-model.number="form.test_suite.memory_limit_kib"
                      type="number"
                      min="16384"
                      max="1048576"
                  /></label>
                </div>
                <label>允许语言</label>
                <div class="check-row">
                  <label
                    v-for="(label, value) in {
                      python3: 'Python 3',
                      cpp: 'C++',
                      c: 'C',
                      java: 'Java',
                    }"
                    :key="value"
                    ><input
                      v-model="form.test_suite.allowed_languages"
                      type="checkbox"
                      :value="value"
                    />{{ label }}</label
                  >
                </div>
                <p class="hint">
                  比较方式：忽略每行末尾空白。冻结前至少一个测试点，权重之和必须为
                  1。
                </p>
                <div
                  v-for="(test, i) in form.test_suite.cases"
                  :key="i"
                  class="subcard"
                >
                  <div class="field-heading">
                    <strong>测试点 {{ i + 1 }}</strong
                    ><button
                      v-if="!locked"
                      type="button"
                      class="danger-text small"
                      @click="form.test_suite.cases.splice(i, 1)"
                    >
                      <Trash2 :size="15" />删除
                    </button>
                  </div>
                  <div class="form-grid">
                    <label
                      >输入<textarea
                        v-model="test.input_text"
                        rows="4"
                        class="code-input"
                        maxlength="262144"
                      ></textarea></label
                    ><label
                      >期望输出<textarea
                        v-model="test.expected_output"
                        rows="4"
                        class="code-input"
                        maxlength="262144"
                      ></textarea></label
                    ><label
                      >权重（最多六位小数）<input
                        v-model="test.weight"
                        type="text"
                        inputmode="decimal"
                        pattern="(?:0(?:\.[0-9]{1,6})?|1(?:\.0{1,6})?)" /></label
                    ><label class="check-label"
                      ><input
                        v-model="test.is_public"
                        type="checkbox"
                      />公开测试点</label
                    >
                  </div>
                </div>
                <button
                  v-if="!locked"
                  type="button"
                  class="dashed full"
                  :disabled="form.test_suite.cases.length >= 200"
                  @click="
                    form.test_suite.cases.push({
                      input_text: '',
                      expected_output: '',
                      weight: '1',
                      is_public: false,
                    })
                  "
                >
                  <Plus :size="16" />添加测试点
                </button></template
              ><template v-else-if="form.rubric"
                ><label
                  >量表名称<input v-model="form.rubric.name" maxlength="100"
                /></label>
                <p class="hint">
                  按独立维度描述评分标准。冻结前至少一项，每项需有名称、描述和正分值。
                </p>
                <div
                  v-for="(item, i) in form.rubric.items"
                  :key="i"
                  class="subcard"
                >
                  <div class="field-heading">
                    <strong>评分维度 {{ i + 1 }}</strong
                    ><button
                      v-if="!locked"
                      type="button"
                      class="danger-text small"
                      @click="form.rubric.items.splice(i, 1)"
                    >
                      <Trash2 :size="15" />删除
                    </button>
                  </div>
                  <div class="form-grid">
                    <label
                      >维度名称<input
                        v-model="item.name"
                        maxlength="100" /></label
                    ><label
                      >满分<input
                        v-model="item.max_score"
                        inputmode="decimal"
                        pattern="[0-9]+(?:\.[0-9]{1,2})?"
                    /></label>
                  </div>
                  <label
                    >评分描述<textarea
                      v-model="item.description"
                      rows="3"
                      maxlength="8192"
                      placeholder="描述得分依据，便于教师和互评模块使用"
                    ></textarea>
                  </label>
                </div>
                <button
                  v-if="!locked"
                  type="button"
                  class="dashed full"
                  :disabled="form.rubric.items.length >= 30"
                  @click="
                    form.rubric.items.push({
                      name: '',
                      description: '',
                      max_score: '10.00',
                    })
                  "
                >
                  <Plus :size="16" />添加评分维度
                </button></template
              ></template
            >
          </fieldset>
        </section>
      </div>
      <aside class="editor-aside">
        <section class="card">
          <div class="card-heading"><h2>题目属性</h2></div>
          <fieldset :disabled="locked || busy" class="form-body">
            <label
              >难度<select
                v-model.number="form.difficulty_level"
                aria-label="难度"
              >
                <option v-for="n in 5" :key="n" :value="n">
                  {{ n }} / 5 ·
                  {{ ["入门", "基础", "中等", "进阶", "挑战"][n - 1] }}
                </option>
              </select></label
            ><label>知识点 <span class="required">*</span></label>
            <div class="tag-options">
              <label v-for="tag in tags" :key="tag.id"
                ><input
                  v-model="form.knowledge_point_ids"
                  type="checkbox"
                  :value="tag.id"
                />{{ tag.name }}</label
              >
            </div>
            <div v-if="!locked" class="inline-input">
              <input
                v-model="newTag"
                maxlength="100"
                aria-label="新知识点"
                placeholder="添加知识点"
                @keydown.enter.prevent="addTag"
              /><button type="button" aria-label="添加知识点" @click="addTag">
                <Plus :size="16" />
              </button>
            </div>
            <label
              >来源与引用<textarea
                v-model="form.source_reference"
                rows="4"
                maxlength="65536"
                placeholder="记录来源网址、书籍或原创说明"
              ></textarea>
            </label>
          </fieldset>
        </section>
        <section v-if="detail" class="card">
          <div class="card-heading"><h2>版本记录</h2></div>
          <div class="form-body">
            <select
              :value="current?.id"
              aria-label="查看历史版本"
              :disabled="busy"
              @change="chooseVersion"
            >
              <option v-for="v in detail.versions" :key="v.id" :value="v.id">
                v{{ v.version_no }} ·
                {{ v.status === "FROZEN" ? "已冻结" : "草稿" }}
              </option>
            </select>
            <p class="hint">
              作业引用具体版本。冻结后新建草稿，旧版本保持原样。
            </p>
          </div>
        </section>
        <section class="editor-help">
          <LockKeyhole :size="19" />
          <h3>冻结前检查</h3>
          <p>完整题干、知识点和参考答案。</p>
          <p>
            {{
              type === "PROGRAMMING"
                ? "输入输出格式、有效测试点及总和为 1 的权重。"
                : "包含明确评分描述的评分量表。"
            }}
          </p>
        </section>
      </aside>
    </div>
  </form>
</template>
