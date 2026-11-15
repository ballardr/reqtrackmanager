import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { LineVertexFields } from "./LineVertexFields";
import type { LineWaypoint } from "./types";

/** Hosts the section with real state, as an editor would, and prints the last change reported. */
function Host({ initial = [], smooth = false, editable = true }: { initial?: LineWaypoint[]; smooth?: boolean; editable?: boolean }) {
  const [points, setPoints] = useState(initial);
  const [curve, setCurve] = useState(smooth);
  return (
    <div style={{ maxWidth: "22rem" }}>
      <LineVertexFields
        points={points} smooth={curve} editable={editable} newPoint={{ x: 100, y: 140 }}
        onChange={(change) => { if (change.points) setPoints(change.points); if (change.smooth !== undefined) setCurve(change.smooth); }}
      />
    </div>
  );
}

/** The "Vertices" section of a line's Selection card, for a block diagram connection and a state machine transition alike. */
const meta: Meta<typeof Host> = { title: "Modules/Architecture/LineVertexFields", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

export const NoVerticesSaysTheLineIsStraight: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("No vertices. The line is straight.")).toBeInTheDocument();
    await expect(canvas.getByRole("switch", { name: "Smooth curve" })).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Reset vertices" })).toBeDisabled();
  },
};

export const AddingEditingAndRemovingAVertex: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add vertex" }));
    await expect(canvas.getByRole("spinbutton", { name: "Vertex 1 X" })).toHaveValue(100);
    await expect(canvas.getByRole("spinbutton", { name: "Vertex 1 Y" })).toHaveValue(140);
    const x = canvas.getByRole("spinbutton", { name: "Vertex 1 X" });
    await userEvent.clear(x);
    await userEvent.type(x, "225.4");
    // A value is applied when the field is left, whole units; text that is not a number keeps the old value.
    await userEvent.tab();
    await expect(canvas.getByRole("spinbutton", { name: "Vertex 1 X" })).toHaveValue(225);
    await userEvent.clear(canvas.getByRole("spinbutton", { name: "Vertex 1 Y" }));
    await userEvent.tab();
    await expect(canvas.getByRole("spinbutton", { name: "Vertex 1 Y" })).toHaveValue(140);
    await userEvent.click(canvas.getByRole("button", { name: "Remove vertex 1" }));
    await expect(canvas.getByText("No vertices. The line is straight.")).toBeInTheDocument();
  },
};

export const TheCurveSwitchNeedsAVertexAndResetClearsThem: Story = {
  args: { initial: [{ x: 10, y: 20 }, { x: 30, y: 40 }] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const smooth = canvas.getByRole("switch", { name: "Smooth curve" });
    await expect(smooth).toBeEnabled();
    await userEvent.click(smooth);
    await expect(smooth).toBeChecked();
    await userEvent.click(canvas.getByRole("button", { name: "Reset vertices" }));
    await expect(canvas.queryByRole("spinbutton", { name: "Vertex 1 X" })).not.toBeInTheDocument();
  },
};

export const AtTheCapNoMoreCanBeAdded: Story = {
  args: { initial: Array.from({ length: 16 }, (_, i) => ({ x: i * 10, y: i * 10 })) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Add vertex" })).toBeDisabled();
  },
};

export const ReadOnlyListsThePointsAndOffersNoAction: Story = {
  args: { initial: [{ x: 10, y: 20 }], editable: false, smooth: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("spinbutton", { name: "Vertex 1 X" })).toBeDisabled();
    await expect(canvas.queryByRole("button", { name: "Add vertex" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Remove vertex 1" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("switch", { name: "Smooth curve" })).toBeDisabled();
  },
};

export const AReadOnlyStraightLineShowsNothing: Story = {
  args: { editable: false },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByText("Vertices")).not.toBeInTheDocument();
  },
};
