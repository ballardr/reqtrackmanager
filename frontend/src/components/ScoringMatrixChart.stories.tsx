import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildScoringScheme } from "../testing/storybook-helpers";
import { ScoringMatrixChart } from "./ScoringMatrixChart";

const scheme = buildScoringScheme();
const [severity, frequency] = scheme.axes;

const meta: Meta<typeof ScoringMatrixChart> = {
  title: "Components/Scoring/ScoringMatrixChart",
  component: ScoringMatrixChart,
  args: { xAxis: frequency, yAxis: severity, bands: scheme.models[0].bands, caption: "Severity × Frequency" },
};
export default meta;

type Story = StoryObj<typeof ScoringMatrixChart>;

/** Top level first; the Blocker × Constant cell is the top band. */
export const Bands: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const rows = canvas.getAllByRole("row");
    await expect(within(rows[1]).getByRole("rowheader")).toHaveTextContent("Blocker");
    await expect(canvas.getByLabelText(/Severity Blocker, Frequency Constant: Critical, 0 items/)).toBeInTheDocument();
    await expect(canvas.getByLabelText(/Severity Cosmetic, Frequency Rare: Low, 0 items/)).toBeInTheDocument();
  },
};

export const WithPointsAndCellClick: Story = {
  args: {
    points: [
      { id: "pp-1", label: "Checkout times out", xLevelId: "freq-4", yLevelId: "sev-5", size: 1 },
      { id: "pp-2", label: "Export is slow", xLevelId: "freq-4", yLevelId: "sev-5", size: 0.5 },
      { id: "pp-3", label: "Typo in footer", xLevelId: "freq-1", yLevelId: "sev-1" },
    ],
    onCellClick: fn(),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    const cell = canvas.getByRole("button", { name: /Severity Blocker, Frequency Constant: Critical, 2 items/ });
    await expect(canvas.getByTitle("Checkout times out")).toBeInTheDocument();
    await userEvent.click(cell);
    await expect(args.onCellClick).toHaveBeenCalledWith("freq-4", "sev-5");
  },
};

/** No bands configured: cells stay neutral but still name themselves. */
export const NoBands: Story = {
  args: { bands: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByLabelText(/Severity Blocker, Frequency Constant: no band/)).toBeInTheDocument();
  },
};

export const LightTheme: Story = { globals: { theme: "light" } };
export const DarkTheme: Story = { globals: { theme: "dark" } };
