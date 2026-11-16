import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildConnection, buildViewNode } from "./architectureFixtures";
import { DiagramLeaderEditor } from "./DiagramLeaderEditor";
import { boxFromNode } from "./diagramEditorModel";
import { boxName } from "./diagramOutlineModel";
import { leaderTargetFields, newLeader, type EditorLeader, type NoteLeaderTarget } from "./noteModel";

const BOXES = [boxFromNode(buildViewNode()), boxFromNode(buildViewNode({ element_id: "el-2", unique_code: "ELM-002", name: "Orders" }))];
const LINK = buildConnection();
const TARGETS = [
  ...BOXES.map((b) => ({ value: `element:${b.elementId}`, label: `Box: ${boxName(b)}` })),
  { value: `connection:${LINK.id}`, label: `Connection: ${LINK.unique_code} ${LINK.name}` },
];

/** Hosts the card with real state, as the editor page does, and reports each callback. */
function Host({ initial, editable = true, drawn = true, onRemove = fn(), onOpenNote = fn() }: {
  initial: EditorLeader; editable?: boolean; drawn?: boolean; onRemove?: () => void; onOpenNote?: () => void;
}) {
  const [leader, setLeader] = useState(initial);
  const target = (t: NoteLeaderTarget) => setLeader((l) => ({ ...l, ...leaderTargetFields(t) }));
  return (
    <div style={{ maxWidth: "22rem" }}>
      <DiagramLeaderEditor
        leader={leader} index={1} editable={editable} targets={TARGETS} drawn={drawn} newPoint={{ x: 120, y: 80 }}
        onTarget={target} onChange={(change) => setLeader((l) => ({ ...l, ...change }))} onOpenNote={onOpenNote} onRemove={onRemove}
      />
    </div>
  );
}

/** The Selection card of one leader line of a note: where it ends, where it starts, its two ends and its vertices. */
const meta: Meta<typeof Host> = { title: "Modules/Architecture/DiagramLeaderEditor", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

const SPOT = newLeader("ld-1", { kind: "point", x: 300, y: 40 });

export const ASpotLeaderShowsXAndYAndTheDefaultEnds: Story = {
  args: { initial: SPOT },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Leader 1")).toBeInTheDocument();
    await expect(canvas.getByRole("combobox", { name: "Points at" })).toHaveDisplayValue("A spot on the canvas");
    await expect(canvas.getByRole("spinbutton", { name: "Spot X" })).toHaveValue(300);
    await expect(canvas.getByRole("spinbutton", { name: "Spot Y" })).toHaveValue(40);
    await expect(canvas.getByRole("combobox", { name: "Starts at" })).toHaveDisplayValue("Automatic");
    await expect(canvas.getByRole("combobox", { name: "Start style" })).toHaveDisplayValue("None");
    await expect(canvas.getByRole("combobox", { name: "End style" })).toHaveDisplayValue("Arrow");
  },
};

export const ChangingTheSpotStartPointAndBothEndsAppliesAtOnce: Story = {
  args: { initial: SPOT },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const x = canvas.getByRole("spinbutton", { name: "Spot X" });
    await userEvent.clear(x);
    await userEvent.type(x, "512");
    await userEvent.tab();
    await expect(canvas.getByRole("spinbutton", { name: "Spot X" })).toHaveValue(512);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Starts at" }), "top_left");
    await expect(canvas.getByRole("combobox", { name: "Starts at" })).toHaveDisplayValue("Top left");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Start style" }), "dot");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "End style" }), "none");
    await expect(canvas.getByRole("combobox", { name: "Start style" })).toHaveDisplayValue("Dot");
    await expect(canvas.getByRole("combobox", { name: "End style" })).toHaveDisplayValue("None");
  },
};

export const ABoxOrAConnectionCanBeChosenAndTheSpotFieldsGoAway: Story = {
  args: { initial: SPOT },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const pointsAt = canvas.getByRole("combobox", { name: "Points at" });
    await userEvent.selectOptions(pointsAt, "element:el-2");
    await expect(canvas.queryByRole("spinbutton", { name: "Spot X" })).toBeNull();
    await expect(pointsAt).toHaveDisplayValue(/ELM-002/);
    await userEvent.selectOptions(pointsAt, within(pointsAt).getByRole("option", { name: /^Connection: CON-001/ }));
    await expect(pointsAt).toHaveDisplayValue(/^Connection: CON-001/);
  },
};

export const VerticesAreAddedWithTheSharedSectionAndSmoothingNeedsOne: Story = {
  args: { initial: SPOT },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("switch", { name: "Smooth curve" })).toBeDisabled();
    await userEvent.click(canvas.getByRole("button", { name: "Add vertex" }));
    await expect(canvas.getByRole("spinbutton", { name: "Vertex 1 X" })).toHaveValue(120);
    await userEvent.click(canvas.getByRole("switch", { name: "Smooth curve" }));
    await expect(canvas.getByRole("switch", { name: "Smooth curve" })).toBeChecked();
  },
};

export const ALeaderToSomethingNotDrawnSaysSo: Story = {
  args: { initial: newLeader("ld-1", { kind: "element", elementId: "el-gone" }), drawn: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/points at something that is not drawn/)).toBeInTheDocument();
    await expect(canvas.getByRole("combobox", { name: "Points at" })).toHaveDisplayValue("An item not on this diagram");
  },
};

export const ARemovedLeaderAndTheWayBackToTheNoteAreActions: Story = {
  args: { initial: SPOT, onRemove: fn(), onOpenNote: fn() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Select note" }));
    await expect(args.onOpenNote).toHaveBeenCalledTimes(1);
    await userEvent.click(canvas.getByRole("button", { name: "Remove leader" }));
    await expect(args.onRemove).toHaveBeenCalledTimes(1);
  },
};

export const ReadOnlyShowsTheLeaderWithNoControlsToChangeIt: Story = {
  args: { initial: SPOT, editable: false },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("combobox", { name: "Points at" })).toBeDisabled();
    await expect(canvas.getByRole("combobox", { name: "Starts at" })).toBeDisabled();
    await expect(canvas.queryByRole("button", { name: "Remove leader" })).toBeNull();
    await expect(canvas.queryByRole("button", { name: "Add vertex" })).toBeNull();
    await expect(canvas.getByRole("button", { name: "Select note" })).toBeInTheDocument();
  },
};
