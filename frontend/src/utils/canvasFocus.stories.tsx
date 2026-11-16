import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, within } from "storybook/test";

import { DetailCard } from "../components/DetailCard";
import { focusCanvasSelection, returnFocusToCanvas } from "./canvasFocus";
import { isTextEntryTarget, overlayIsOpen } from "./keyboardTargets";

/** A stand-in for the graph canvas (React Flow draws each node and line with its id in `data-id`) beside a Selection card. */
function Host({ selection, dialog = false }: { selection: { kind: string; id: string } | null; dialog?: boolean }) {
  return (
    <div className="stack">
      <div className="react-flow__node" data-id="idle" tabIndex={0} aria-label="Idle, node" />
      <div className="react-flow__edge" data-id="t1" tabIndex={0} aria-label="Idle to Running, connection" />
      <DetailCard heading="Selection" onKeyDown={(event) => returnFocusToCanvas(event, selection)}>
        <input aria-label="Name" className="input" defaultValue="Idle" />
        <select aria-label="Kind"><option>State</option></select>
      </DetailCard>
      {dialog && <div role="dialog" aria-label="Open dialog" />}
    </div>
  );
}

const meta: Meta<typeof Host> = { title: "Utils/CanvasFocus", component: Host, args: { selection: { kind: "node", id: "idle" } } };
export default meta;

type Story = StoryObj<typeof Host>;

/** Escape in a text field of the card focuses the selected node, so the keyboard continues on the canvas. */
export const EscapeInATextFieldFocusesTheSelectedNode: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("textbox", { name: "Name" }));
    await userEvent.keyboard("{Escape}");
    await expect(canvas.getByLabelText("Idle, node")).toHaveFocus();
  },
};

/** A selected line is focused the same way. */
export const EscapeFocusesASelectedLine: Story = {
  args: { selection: { kind: "edge", id: "t1" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("textbox", { name: "Name" }));
    await userEvent.keyboard("{Escape}");
    await expect(canvas.getByLabelText("Idle to Running, connection")).toHaveFocus();
  },
};

/** With nothing selected, an unknown item, a select or an open dialog, Escape is left alone and the focus stays where it was. */
export const EscapeIsLeftAloneWhereItHasAnotherMeaning: Story = {
  args: { selection: null },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const name = canvas.getByRole("textbox", { name: "Name" });
    await userEvent.click(name);
    await userEvent.keyboard("{Escape}");
    await expect(name).toHaveFocus();
    await expect(focusCanvasSelection({ kind: "node", id: "missing" })).toBe(false);
    await expect(focusCanvasSelection(null)).toBe(false);
  },
};

/** An open dialog or menu owns Escape, so the card does not move the focus. */
export const AnOpenDialogKeepsEscape: Story = {
  args: { dialog: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const name = canvas.getByRole("textbox", { name: "Name" });
    await userEvent.click(name);
    await userEvent.keyboard("{Escape}");
    await expect(name).toHaveFocus();
  },
};

/** The shared key-target rule: text entry and open overlays keep their keys; a button does not. */
export const KeyTargetRule: Story = {
  args: { dialog: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(isTextEntryTarget(canvas.getByRole("textbox", { name: "Name" }))).toBe(true);
    await expect(isTextEntryTarget(canvas.getByRole("combobox", { name: "Kind" }))).toBe(true);
    await expect(isTextEntryTarget(canvas.getByLabelText("Idle, node"))).toBe(false);
    await expect(isTextEntryTarget(null)).toBe(false);
    await expect(overlayIsOpen()).toBe(true);
  },
};
