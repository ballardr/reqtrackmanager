import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";

import { DiagramNoteEditor } from "./DiagramNoteEditor";
import { newNote, type EditorNote, type NotePatch } from "./diagramEditorModel";

/** Hosts the note card with real state, as the Selection card does, and reports each change it makes. */
function Host({ initial, editable = true, onChange }: { initial: EditorNote; editable?: boolean; onChange: (patch: NotePatch) => void }) {
  const [note, setNote] = useState(initial);
  return (
    <DiagramNoteEditor
      note={note} editable={editable} leaders={[]} autoFocusText={false} onFocused={() => undefined}
      onChange={(patch) => { onChange(patch); setNote((n) => ({ ...n, ...patch })); }}
      onAddLeader={() => undefined} onOpenLeader={() => undefined} onRemove={() => undefined}
    />
  );
}

const meta: Meta<typeof Host> = {
  title: "Modules/Architecture/DiagramNoteEditor",
  component: Host,
  args: { initial: { ...newNote("k", { x: 0, y: 0 }), text: "Check with ops" }, onChange: fn() },
};
export default meta;

type Story = StoryObj<typeof Host>;

export const TitleTextAndAlignmentAreEdited: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const title = canvas.getByRole("textbox", { name: "Title" });
    expect(title).toHaveAttribute("maxlength", "120");
    await userEvent.type(title, "Heading");
    // One edit is one change: the title applies when the field loses focus, not per keystroke.
    expect(args.onChange).not.toHaveBeenCalled();
    await userEvent.tab();
    expect(args.onChange).toHaveBeenCalledWith({ title: "Heading" });
    const text = canvas.getByRole("textbox", { name: "Note text" });
    await userEvent.type(text, "{Enter}{Enter}Second paragraph");
    await userEvent.tab();
    expect(args.onChange).toHaveBeenLastCalledWith({ text: "Check with ops\n\nSecond paragraph" });
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Alignment" }), "Centre");
    expect(args.onChange).toHaveBeenLastCalledWith({ textAlign: "center" });
    expect(canvas.getByRole("combobox", { name: "Alignment" })).toHaveValue("center");
  },
};

/** An Undo changes the note under the card, and the fields show the note again, not what was typed before. */
function UndoHost() {
  const [note, setNote] = useState<EditorNote>({ ...newNote("k", { x: 0, y: 0 }), title: "Head", text: "Body" });
  return (
    <>
      <button type="button" onClick={() => setNote((n) => ({ ...n, title: "", text: "Earlier" }))}>Undo</button>
      <DiagramNoteEditor
        note={note} editable leaders={[]} autoFocusText={false} onFocused={() => undefined} onChange={() => undefined}
        onAddLeader={() => undefined} onOpenLeader={() => undefined} onRemove={() => undefined}
      />
    </>
  );
}

export const AnUndoShowsTheEarlierTitleAndText: Story = {
  render: () => <UndoHost />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(canvas.getByRole("textbox", { name: "Title" }), " typed");
    await userEvent.click(canvas.getByRole("button", { name: "Undo" }));
    expect(canvas.getByRole("textbox", { name: "Title" })).toHaveValue("");
    expect(canvas.getByRole("textbox", { name: "Note text" })).toHaveValue("Earlier");
  },
};

export const EveryAlignmentIsOffered: Story = {
  play: async ({ canvasElement }) => {
    const options = within(within(canvasElement).getByRole("combobox", { name: "Alignment" })).getAllByRole("option");
    expect(options.map((o) => o.textContent)).toEqual(["Left", "Centre", "Right"]);
  },
};

/** Choosing Manual keeps the size the note is drawn at now; choosing Automatic leaves the stored size for a return. */
export const SizeIsAutomaticOrManualAndManualKeepsTheDrawnSize: Story = {
  play: async ({ canvasElement, args }) => {
    const size = within(canvasElement).getByRole("combobox", { name: "Size" });
    expect(within(size).getAllByRole("option").map((o) => o.textContent)).toEqual(["Automatic", "Manual"]);
    expect(size).toHaveValue("automatic");
    // "Check with ops" with a neutral tone is drawn at its content frame (117 x 42, caption included), not at the stored 160 x 60.
    await userEvent.selectOptions(size, "Manual");
    expect(args.onChange).toHaveBeenLastCalledWith({ sizeMode: "manual", width: 117, height: 42 });
    await userEvent.selectOptions(size, "Automatic");
    expect(args.onChange).toHaveBeenLastCalledWith({ sizeMode: "automatic" });
  },
};

export const ReadOnlyFieldsCannotBeEdited: Story = {
  args: { editable: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (const name of ["Title", "Note text", "Alignment", "Tone", "Size"]) {
      expect(canvas.getByRole(["Alignment", "Tone", "Size"].includes(name) ? "combobox" : "textbox", { name })).toBeDisabled();
    }
  },
};
