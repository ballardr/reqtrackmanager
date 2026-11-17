import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { LineVertexFields } from "./LineVertexFields";
import type { LineShape } from "../../components/graphLinePath";
import type { LineWaypoint } from "./types";

/** Hosts the section with real state, as an editor would, and prints the last change reported. */
function Host({ initial = [], shape = null, defaultShape = "straight", editable = true }: {
  initial?: LineWaypoint[]; shape?: LineShape | null; defaultShape?: LineShape; editable?: boolean;
}) {
  const [points, setPoints] = useState(initial);
  const [own, setOwn] = useState<LineShape | null>(shape);
  return (
    <div style={{ maxWidth: "22rem" }}>
      <LineVertexFields
        points={points} lineShape={own} defaultShape={defaultShape} editable={editable} newPoint={{ x: 100, y: 140 }}
        onChange={(change) => { if (change.points) setPoints(change.points); if (change.lineShape !== undefined) setOwn(change.lineShape); }}
      />
    </div>
  );
}

/** The "Vertices" section of a line's Selection card, for a block diagram connection and a state machine transition alike. */
const meta: Meta<typeof Host> = { title: "Modules/Architecture/LineVertexFields", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

export const NoVerticesIsSaidAndNothingCanBeReset: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("No vertices.")).toBeInTheDocument();
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
    await expect(canvas.getByText("No vertices.")).toBeInTheDocument();
  },
};

export const ResetClearsTheVertices: Story = {
  args: { initial: [{ x: 10, y: 20 }, { x: 30, y: 40 }] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Reset vertices" }));
    await expect(canvas.queryByRole("spinbutton", { name: "Vertex 1 X" })).not.toBeInTheDocument();
  },
};

/** A line's shape does not depend on vertices: a line with none can be Curved, and "Diagram default" names what it follows. */
export const TheShapeIsChosenWithOrWithoutVertices: Story = {
  args: { defaultShape: "spline" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const shape = canvas.getByRole("combobox", { name: "Line shape" });
    await expect(shape).toBeEnabled();
    await expect(shape).toHaveValue("");
    await expect(within(shape).getAllByRole("option").map((o) => o.textContent)).toEqual(["Diagram default (Spline)", "Straight", "Curved", "Spline"]);
    await userEvent.selectOptions(shape, "curved");
    await expect(shape).toHaveValue("curved");
    await userEvent.selectOptions(shape, "");
    await expect(shape).toHaveValue("");
  },
};

/** The help of the select describes every option, one line each. */
export const TheShapeHelpNamesEveryOption: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: /^Help: Line shape/ }));
    const tip = await within(document.body).findByRole("tooltip");
    await expect(tip).toHaveTextContent("Diagram default: the line follows the shape chosen for the diagram.");
    await expect(tip).toHaveTextContent("Curved: leaves each box straight out");
  },
};

export const AtTheCapNoMoreCanBeAdded: Story = {
  args: { initial: Array.from({ length: 16 }, (_, i) => ({ x: i * 10, y: i * 10 })) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Add vertex" })).toBeDisabled();
  },
};

export const ReadOnlyListsThePointsAndOffersNoAction: Story = {
  args: { initial: [{ x: 10, y: 20 }], editable: false, shape: "spline" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("spinbutton", { name: "Vertex 1 X" })).toBeDisabled();
    await expect(canvas.queryByRole("button", { name: "Add vertex" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Remove vertex 1" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("combobox", { name: "Line shape" })).toBeDisabled();
  },
};

export const AReadOnlyLineThatFollowsTheDiagramWithNoVerticesShowsNothing: Story = {
  args: { editable: false },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByText("Vertices")).not.toBeInTheDocument();
  },
};
