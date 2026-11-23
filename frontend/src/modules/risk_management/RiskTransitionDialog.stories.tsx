import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { ApiError } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { buildRisk } from "./riskFixtures";
import { RiskTransitionDialog } from "./RiskTransitionDialog";

const meta: Meta<typeof RiskTransitionDialog> = {
  title: "Modules/RiskManagement/RiskTransitionDialog",
  component: RiskTransitionDialog,
  args: { risk: buildRisk(), target: "treatment_planned", onTransition: fn(async () => undefined), onClose: fn() },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof RiskTransitionDialog>;

const dialog = (name: string) => within(within(document.body).getByRole("dialog", { name }));

export const MovesWithAComment: Story = {
  play: async ({ args }) => {
    const d = dialog("Move RSK-001 to Treatment planned");
    await expect(d.getByText(/Currently Assessed/)).toBeInTheDocument();
    await userEvent.type(d.getByLabelText("Status change comment"), "Owner agreed a plan");
    await userEvent.click(d.getByRole("button", { name: "Move to Treatment planned" }));
    await waitFor(() => expect(args.onTransition).toHaveBeenCalledWith("treatment_planned", "Owner agreed a plan"));
    await waitFor(() => expect(args.onClose).toHaveBeenCalled());
  },
};

/** A refused move (an unmet guard) keeps the dialog open and shows why. */
export const RefusedMoveShowsTheReason: Story = {
  args: { target: "accepted", onTransition: fn(async () => { throw new ApiError(409, "A residual rating is needed to accept."); }) },
  play: async ({ args }) => {
    const d = dialog("Move RSK-001 to Accepted");
    await expect(d.getByText(/needs the Risk Acceptor role/)).toBeInTheDocument();
    await userEvent.click(d.getByRole("button", { name: "Move to Accepted" }));
    await expect(await d.findByText("A residual rating is needed to accept.")).toBeInTheDocument();
    await expect(args.onClose).not.toHaveBeenCalled();
  },
};

export const DarkTheme: Story = { ...MovesWithAComment, globals: { theme: "dark" } };
