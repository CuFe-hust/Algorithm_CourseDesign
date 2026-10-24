<script setup lang="ts">
import { computed, ref } from "vue";
import MarkdownPreview from "../../../shared/MarkdownPreview.vue";
const props = defineProps<{
  modelValue: string;
  readonly?: boolean;
  byteLimit?: number;
}>();
const emit = defineEmits<{ "update:modelValue": [string] }>();
const preview = ref(false);
const bytes = computed(() => new TextEncoder().encode(props.modelValue).length);
const limit = computed(() => props.byteLimit ?? 262144);
const over = computed(() => bytes.value > limit.value);
</script>
<template>
  <div class="subjective-editor">
    <div class="editor-tabs" role="tablist">
      <button
        :class="{ active: !preview }"
        role="tab"
        :aria-selected="!preview"
        @click="preview = false"
      >
        编辑
      </button>
      <button
        :class="{ active: preview }"
        role="tab"
        :aria-selected="preview"
        @click="preview = true"
      >
        预览
      </button>
      <span class="editor-count" :class="{ danger: over }"
        >{{ bytes }} / {{ limit }} 字节 · 支持 Markdown 与 $LaTeX$</span
      >
    </div>
    <textarea
      v-if="!preview"
      class="code-input"
      :value="modelValue"
      :readonly="readonly"
      rows="16"
      aria-label="作答编辑器"
      placeholder="在此作答，可使用 Markdown 与 $公式$。"
      @input="
        emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)
      "
    ></textarea>
    <div v-else class="preview-panel">
      <MarkdownPreview :source="modelValue" />
    </div>
    <p v-if="over" class="alert error">
      内容超过 {{ limit }} 字节，提交会被拒绝。
    </p>
  </div>
</template>
