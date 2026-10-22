// @vitest-environment jsdom
import { createApp, nextTick } from "vue";
import { it, expect } from "vitest";
import ConfirmDialog from "./ConfirmDialog.vue";
import { confirmAction, finishConfirmation } from "./confirm";

it("requires an explicit confirmation and supports keyboard cancellation", async () => {
  const host = document.createElement("div");
  document.body.append(host);
  const app = createApp(ConfirmDialog);
  app.mount(host);
  try {
    const pending = confirmAction("冻结此版本？");
    await nextTick();
    await nextTick();
    const dialog = document.querySelector('[role="alertdialog"]')!;
    expect(dialog.textContent).toContain("冻结此版本？");
    const buttons = dialog.querySelectorAll("button");
    expect(document.activeElement).toBe(buttons[0]);
    buttons[0]!.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Tab", bubbles: true }),
    );
    expect(document.activeElement).toBe(buttons[1]);
    buttons[1]!.dispatchEvent(
      new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
    );
    expect(await pending).toBe(false);
    await nextTick();
    expect(document.querySelector('[role="alertdialog"]')).toBeNull();
    const accepted = confirmAction("确认导入？");
    await nextTick();
    document
      .querySelectorAll<HTMLButtonElement>('[role="alertdialog"] button')[1]!
      .click();
    expect(await accepted).toBe(true);
  } finally {
    finishConfirmation(false);
    app.unmount();
    host.remove();
  }
});
