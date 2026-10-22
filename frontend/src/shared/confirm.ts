import { ref } from "vue";
export const confirmation = ref<string | null>(null);
let resolve: ((value: boolean) => void) | undefined;
export function confirmAction(message: string): Promise<boolean> {
  resolve?.(false);
  confirmation.value = message;
  return new Promise<boolean>((done) => {
    resolve = done;
  });
}
export function finishConfirmation(value: boolean) {
  const done = resolve;
  resolve = undefined;
  confirmation.value = null;
  done?.(value);
}
