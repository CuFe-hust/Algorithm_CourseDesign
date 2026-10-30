<script setup lang="ts">
import { computed, ref } from "vue";
const props = defineProps<{
  modelValue: string;
  language: string;
  readonly?: boolean;
  byteLimit?: number;
}>();
const emit = defineEmits<{ "update:modelValue": [string] }>();
const bytes = computed(() => new TextEncoder().encode(props.modelValue).length);
const limit = computed(() => props.byteLimit ?? 65536);
const over = computed(() => bytes.value > limit.value);
const lines = computed(() => Math.max(19, props.modelValue.split("\n").length));
const gutter = ref<HTMLElement | null>(null);
const numbers = computed(() =>
  Array.from({ length: lines.value }, (_, i) => i + 1).join("\n"),
);
function syncScroll(e: Event) {
  if (gutter.value)
    gutter.value.scrollTop = (e.target as HTMLTextAreaElement).scrollTop;
}
</script>
<template>
  <div class="code-editor">
    <div class="code-editor-bar">
      <span class="small-label">{{ language }}</span>
      <span :class="{ danger: over }">{{ bytes }} / {{ limit }} 字节</span>
    </div>
    <div class="code-edit-surface">
      <pre ref="gutter" class="code-gutter mono" aria-hidden="true">{{
        numbers
      }}</pre>
      <textarea
        class="mono code-input"
        :value="modelValue"
        :readonly="readonly"
        :rows="19"
        wrap="off"
        @scroll="syncScroll"
        spellcheck="false"
        autocapitalize="off"
        autocomplete="off"
        aria-label="代码编辑器"
        @input="
          emit(
            'update:modelValue',
            ($event.target as HTMLTextAreaElement).value,
          )
        "
      ></textarea>
    </div>
    <p v-if="over" class="alert error">
      内容超过 {{ limit }} 字节，提交会被拒绝。
    </p>
  </div>
</template>
