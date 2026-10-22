<script setup lang="ts">
import { nextTick, ref, watch } from "vue";
import { confirmation, finishConfirmation } from "./confirm";
const cancel = ref<HTMLButtonElement>(),
  accept = ref<HTMLButtonElement>();
let previousFocus: HTMLElement | null = null;
watch(confirmation, async (message) => {
  if (message) {
    previousFocus = document.activeElement as HTMLElement;
    await nextTick();
    cancel.value?.focus();
  } else {
    await nextTick();
    previousFocus?.focus();
  }
});
function keyboard(event: KeyboardEvent) {
  if (event.key === "Escape") {
    event.preventDefault();
    finishConfirmation(false);
  }
  if (event.key === "Tab") {
    event.preventDefault();
    (document.activeElement === cancel.value
      ? accept.value
      : cancel.value
    )?.focus();
  }
}
</script>
<template>
  <Teleport to="body"
    ><div v-if="confirmation" class="modal-overlay" @keydown="keyboard">
      <section
        class="confirm-dialog card"
        role="alertdialog"
        aria-modal="true"
        aria-labelledby="confirm-title"
        aria-describedby="confirm-message"
      >
        <h2 id="confirm-title">确认操作</h2>
        <p id="confirm-message">{{ confirmation }}</p>
        <div class="button-row">
          <button ref="cancel" @click="finishConfirmation(false)">取消</button
          ><button
            ref="accept"
            class="primary"
            @click="finishConfirmation(true)"
          >
            确认
          </button>
        </div>
      </section>
    </div></Teleport
  >
</template>
