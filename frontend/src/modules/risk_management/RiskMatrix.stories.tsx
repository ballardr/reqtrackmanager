import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildRisk, buildRiskScheme } from "./riskFixtures";
import { RiskMatrix } from "./RiskMatrix";

const RISKS = [
  buildRisk({ id: "r1", unique_code: "RSK-001", title: "Supplier firmware may be late" }),
  buildRisk({
    id: "r2", unique_code: "RSK-002", title: "Test rig unavailable",
    inherent_likelihood_level_id: "lik-1", inherent_consequence_level_id: "con-5",
    residual_likelihood_level_id: "lik-1", residual_consequence_level_id: "con-2",
  }),
  buildRisk({ id: "r3", unique_code: "RSK-003", title: "Unscored risk", inherent_likelihood_level_id: null, inherent_consequence_level_id: null }),
];

const meta: Meta<typeof RiskMatrix> = {
  title: "Modules/RiskManagement/RiskMatrix",
  component: RiskMatrix,
  args: { scheme: buildRiskScheme(), risks: RISKS, basis: "inherent" },
};
export default meta;

type Story = StoryObj<typeof RiskMatrix>;

/** Rows are Likelihood (top level first), columns Consequence; a risk is a dot in its cell. */
export const PlotsRisksByInherentRating: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText(/Likelihood Likely, Consequence Major: High, 1 item/)).toBeInTheDocument();
    await expect(canvas.getByTitle("RSK-001 Supplier firmware may be late")).toBeInTheDocument();
    // A risk with no levels is not plotted.
    await expect(canvas.queryByTitle("RSK-003 Unscored risk")).not.toBeInTheDocument();
  },
};

/** Rare × Catastrophic scores Medium by product (5 of 25) but the project pins it High. */
export const PinnedCellKeepsItsRating: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByLabelText(/Likelihood Rare, Consequence Catastrophic: High, 1 item/)).toBeInTheDocument();
  },
};

export const ResidualBasisMovesTheDot: Story = {
  args: { basis: "residual" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByLabelText(/Likelihood Rare, Consequence Minor: Low, 1 item/)).toBeInTheDocument();
    await expect(canvas.queryByTitle("RSK-001 Supplier firmware may be late")).not.toBeInTheDocument();
  },
};

/** The detail page plots one risk's inherent and residual points together. */
export const BothRatingsOfOneRisk: Story = {
  args: { basis: "both", risks: [RISKS[1]] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByTitle("RSK-002 Test rig unavailable (inherent)")).toBeInTheDocument();
    await expect(canvas.getByTitle("RSK-002 Test rig unavailable (residual)")).toBeInTheDocument();
  },
};

/** The callback receives (likelihood level id, consequence level id) — rows first. */
export const CellClickReportsLikelihoodThenConsequence: Story = {
  args: { onCellClick: fn() },
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: /Likelihood Likely, Consequence Major/ }));
    await expect(args.onCellClick).toHaveBeenCalledWith("lik-4", "con-4");
  },
};

export const RendersNothingWithoutAScheme: Story = {
  args: { scheme: null },
  play: async ({ canvasElement }) => {
    await expect(canvasElement.querySelector("table")).toBeNull();
  },
};

export const DarkTheme: Story = { ...PlotsRisksByInherentRating, globals: { theme: "dark" } };
