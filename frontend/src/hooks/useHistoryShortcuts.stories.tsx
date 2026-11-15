import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { historyAction, historyShortcutBlocked, type HistoryKeyEvent } from "./useHistoryShortcuts";
import { isApplePlatform, shortcutModifierLabel } from "../utils/platform";

function Host() {
  return <p>The Undo and Redo key rule: which key presses count, and where they are left alone.</p>;
}

const meta: Meta<typeof Host> = { title: "Hooks/useHistoryShortcuts", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

const press = (key: string, modifiers: Partial<HistoryKeyEvent> = {}): HistoryKeyEvent => ({
  key, ctrlKey: false, metaKey: false, shiftKey: false, altKey: false, ...modifiers,
});

/** Command is the modifier on Apple devices; Shift makes Z a Redo; Y is not a Redo there. */
export const AppleKeys: Story = {
  play: async () => {
    await expect(historyAction(press("z", { metaKey: true }), true)).toBe("undo");
    await expect(historyAction(press("Z", { metaKey: true, shiftKey: true }), true)).toBe("redo");
    await expect(historyAction(press("z", { metaKey: true, shiftKey: true }), true)).toBe("redo");
    await expect(historyAction(press("y", { metaKey: true }), true)).toBeNull();
    // Control alone, or with Command, is not the Apple shortcut.
    await expect(historyAction(press("z", { ctrlKey: true }), true)).toBeNull();
    await expect(historyAction(press("z", { ctrlKey: true, metaKey: true }), true)).toBeNull();
  },
};

/** Control is the modifier elsewhere; Redo is Shift+Z or Y; the Windows key is never taken. */
export const OtherPlatformKeys: Story = {
  play: async () => {
    await expect(historyAction(press("z", { ctrlKey: true }), false)).toBe("undo");
    await expect(historyAction(press("Z", { ctrlKey: true }), false)).toBe("undo");
    await expect(historyAction(press("z", { ctrlKey: true, shiftKey: true }), false)).toBe("redo");
    await expect(historyAction(press("y", { ctrlKey: true }), false)).toBe("redo");
    await expect(historyAction(press("Y", { ctrlKey: true }), false)).toBe("redo");
    await expect(historyAction(press("y", { ctrlKey: true, shiftKey: true }), false)).toBeNull();
    await expect(historyAction(press("z", { metaKey: true }), false)).toBeNull();
    await expect(historyAction(press("z", { ctrlKey: true, metaKey: true }), false)).toBeNull();
  },
};

/** A plain letter, another letter, or Alt held, is not a history key. */
export const OtherKeysAreIgnored: Story = {
  play: async () => {
    await expect(historyAction(press("z"), false)).toBeNull();
    await expect(historyAction(press("z", { shiftKey: true }), true)).toBeNull();
    await expect(historyAction(press("x", { ctrlKey: true }), false)).toBeNull();
    await expect(historyAction(press("z", { ctrlKey: true, altKey: true }), false)).toBeNull();
    await expect(historyAction(press("Control", { ctrlKey: true }), false)).toBeNull();
  },
};

/** Text being typed, an open dialog and an open menu all leave the key to the browser. */
export const LeftAloneWhereTextIsTypedOrAnOverlayIsOpen: Story = {
  play: async () => {
    const holder = document.createElement("div");
    document.body.appendChild(holder);
    const field = document.createElement("textarea");
    const select = document.createElement("select");
    const editable = document.createElement("div");
    editable.contentEditable = "true";
    const button = document.createElement("button");
    holder.append(field, select, editable, button);
    try {
      await expect(historyShortcutBlocked(field)).toBe(true);
      await expect(historyShortcutBlocked(select)).toBe(true);
      await expect(historyShortcutBlocked(editable)).toBe(true);
      await expect(historyShortcutBlocked(button)).toBe(false);
      await expect(historyShortcutBlocked(null)).toBe(false);
      for (const role of ["dialog", "alertdialog", "menu"]) {
        const overlay = document.createElement("div");
        overlay.setAttribute("role", role);
        holder.appendChild(overlay);
        await expect(historyShortcutBlocked(button)).toBe(true);
        overlay.remove();
      }
      await expect(historyShortcutBlocked(button)).toBe(false);
    } finally {
      holder.remove();
    }
  },
};

/** The modifier shown in a tooltip follows the platform. */
export const ModifierLabelFollowsThePlatform: Story = {
  play: async () => {
    await expect(shortcutModifierLabel(true)).toBe("Cmd");
    await expect(shortcutModifierLabel(false)).toBe("Ctrl");
    await expect(isApplePlatform({ platform: "MacIntel" })).toBe(true);
    await expect(isApplePlatform({ userAgentData: { platform: "macOS" }, platform: "" })).toBe(true);
    await expect(isApplePlatform({ platform: "iPad" })).toBe(true);
    await expect(isApplePlatform({ platform: "Win32" })).toBe(false);
    await expect(isApplePlatform({ userAgent: "Mozilla/5.0 (X11; Linux x86_64)" })).toBe(false);
    await expect(isApplePlatform({})).toBe(false);
  },
};
