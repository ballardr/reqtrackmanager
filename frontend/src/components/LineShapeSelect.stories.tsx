import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { LineShapeSelect } from "./LineShapeSelect";
import type { LineShape } from "./graphLinePath";

/** Hosts the select with real state, as an editor page does, and prints the value last chosen. */
function Host({ initial = null, fallback, disabled = false }: { initial?: LineShape | null; fallback?: LineShape; disabled?: boolean }) {
  const [value, setValue] = useState<LineShape | null>(initial);
  return (
    <div style={{ maxWidth: "20rem" }}>
      <LineShapeSelect value={value} fallback={fallback} disabled={disabled} onChange={setValue} />
      <span data-testid="chosen">{String(value)}</span>
    </div>
  );
}

/** The one choice of a line's shape: the diagram's default in the settings gear, and a line's own shape in its Selection card. */
const meta: Meta<typeof Host> = { title: "Components/LineShapeSelect", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

export const TheDiagramDefaultListsThreeShapesAndNoLeadingEntry: Story = {
  args: { initial: "straight" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = canvas.getByRole("combobox", { name: "Default line shape" });
    await expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["Straight", "Curved", "Spline"]);
    await userEvent.selectOptions(select, "spline");
    await expect(canvas.getByTestId("chosen")).toHaveTextContent("spline");
  },
};

export const ALineLeadsWithTheShapeItFollowsAndCanFollowItAgain: Story = {
  args: { initial: "curved", fallback: "spline" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = canvas.getByRole("combobox", { name: "Line shape" });
    await expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual(["Diagram default (Spline)", "Straight", "Curved", "Spline"]);
    await expect(select).toHaveValue("curved");
    await userEvent.selectOptions(select, "");
    await expect(canvas.getByTestId("chosen")).toHaveTextContent("null");
    await expect(select).toHaveDisplayValue("Diagram default (Spline)");
  },
};

export const TheHelpNamesEveryOptionOnItsOwnLine: Story = {
  args: { initial: null, fallback: "straight" },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: /^Help: Line shape/ }));
    const tip = await within(document.body).findByRole("tooltip");
    await expect(tip).toHaveTextContent("Diagram default: the line follows the shape chosen for the diagram.");
    await expect(tip).toHaveTextContent("Straight: segments through the line's vertices.");
    await expect(tip).toHaveTextContent("Curved: one arc bowed to the left of the line's direction");
    await expect(tip).toHaveTextContent("Spline: a curve through the line's vertices");
  },
};

export const ItCannotBeChangedWhenDisabled: Story = {
  args: { initial: "straight", fallback: "straight", disabled: true },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("combobox", { name: "Line shape" })).toBeDisabled();
  },
};
