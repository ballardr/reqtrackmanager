import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { EditHistoryButtons } from "./EditHistoryButtons";
import { historyButtonHelp } from "../utils/historyButtonHelp";
import { isApplePlatform } from "../utils/platform";

/** A tiny editor: Add pushes a step, and the buttons and keys walk the history. */
function Harness({ editable = true, withDialog = false }: { editable?: boolean; withDialog?: boolean }) {
  const [past, setPast] = useState<number[]>([]);
  const [future, setFuture] = useState<number[]>([]);
  const [text, setText] = useState("");
  return (
    <div>
      <div role="toolbar" aria-label="Editing" className="row">
        <EditHistoryButtons
          editable={editable} canUndo={past.length > 0} canRedo={future.length > 0}
          undo={() => { setFuture([past[past.length - 1], ...future]); setPast(past.slice(0, -1)); }}
          redo={() => { setPast([...past, future[0]]); setFuture(future.slice(1)); }}
        />
        <button type="button" className="btn btn-sm" onClick={() => { setPast([...past, past.length + 1]); setFuture([]); }}>Add step</button>
      </div>
      <p data-testid="steps">{past.join(",")}</p>
      <label>Name <input value={text} onChange={(e) => setText(e.target.value)} /></label>
      {withDialog && <div role="dialog" aria-label="Open dialog">A dialog</div>}
    </div>
  );
}

const meta: Meta<typeof Harness> = { title: "Components/EditHistoryButtons", component: Harness };
export default meta;

type Story = StoryObj<typeof Harness>;

/** The platform's own modifier, held while a letter is pressed. */
const chord = (letter: string, shift = false) => `{${isApplePlatform() ? "Meta" : "Control"}>}${shift ? "{Shift>}" : ""}${letter}${shift ? "{/Shift}" : ""}{/${isApplePlatform() ? "Meta" : "Control"}}`;

export const KeysWalkTheHistory: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const add = canvas.getByRole("button", { name: "Add step" });
    await userEvent.click(add);
    await userEvent.click(add);
    await expect(canvas.getByTestId("steps")).toHaveTextContent("1,2");
    await userEvent.keyboard(chord("z"));
    await expect(canvas.getByTestId("steps")).toHaveTextContent("1");
    await userEvent.keyboard(chord("z"));
    await expect(canvas.getByTestId("steps")).toHaveTextContent("");
    // Nothing left to undo: the key does nothing.
    await userEvent.keyboard(chord("z"));
    await expect(canvas.getByTestId("steps")).toHaveTextContent("");
    await userEvent.keyboard(chord("z", true));
    await expect(canvas.getByTestId("steps")).toHaveTextContent("1");
    await userEvent.keyboard(chord("z", true));
    await expect(canvas.getByTestId("steps")).toHaveTextContent("1,2");
    await userEvent.keyboard(chord("z"));
    if (!isApplePlatform()) {
      await userEvent.keyboard(chord("y"));
      await expect(canvas.getByTestId("steps")).toHaveTextContent("1,2");
    }
  },
};

/** In a text field the key stays the field's own: the history is untouched. */
export const KeysLeftToATextField: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add step" }));
    await userEvent.click(canvas.getByRole("textbox", { name: "Name" }));
    await userEvent.keyboard("abc");
    await userEvent.keyboard(chord("z"));
    await expect(canvas.getByTestId("steps")).toHaveTextContent("1");
  },
};

/** An open dialog owns the keyboard. */
export const KeysLeftToAnOpenDialog: Story = {
  args: { withDialog: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add step" }));
    await userEvent.keyboard(chord("z"));
    await expect(canvas.getByTestId("steps")).toHaveTextContent("1");
  },
};

/** A read-only editor takes neither the buttons nor the keys. */
export const ReadOnlyTakesNoKeys: Story = {
  args: { editable: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Undo" })).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Redo" })).toBeDisabled();
  },
};

/** The tooltips name the platform's key and say what Undo does not reach. */
export const TooltipsNameTheKeys: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add step" }));
    const help = historyButtonHelp(isApplePlatform());
    await userEvent.hover(canvas.getByRole("button", { name: "Undo" }));
    const bubble = await within(document.body).findByRole("tooltip", { hidden: true });
    await expect(bubble).toHaveTextContent(help.undo);
    await expect(bubble).toHaveTextContent(isApplePlatform() ? "Cmd+Z" : "Ctrl+Z");
    await expect(bubble).toHaveTextContent("Undo does not remove it");
    await userEvent.unhover(canvas.getByRole("button", { name: "Undo" }));
    await waitFor(() => expect(within(document.body).queryByRole("tooltip", { hidden: true })).not.toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "Undo" })).toHaveAttribute("aria-keyshortcuts", help.undoKeys);
    await expect(historyButtonHelp(false).redo).toContain("Ctrl+Shift+Z or Ctrl+Y");
    await expect(historyButtonHelp(true).redo).toBe("Redo the change that was undone (Cmd+Shift+Z).");
  },
};
