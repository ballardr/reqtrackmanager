import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { ApiError } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { buildRisk } from "./riskFixtures";
import { RiskLifecycleControls } from "./RiskLifecycleControls";

const meta: Meta<typeof RiskLifecycleControls> = {
  title: "Modules/RiskManagement/RiskLifecycleControls",
  component: RiskLifecycleControls,
  args: { risk: buildRisk(), onTransition: fn(async () => undefined), onArchiveToggle: fn(async () => undefined) },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof RiskLifecycleControls>;

const dialog = (name: string) => within(within(document.body).getByRole("dialog", { name }));

/** The dialog offers exactly the backend's `allowed_next_statuses`, by label. */
export const OffersOnlyAllowedStatuses: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Change status" }));
    const d = dialog("Change status of RSK-001");
    const options = d.getAllByRole("option").map((o) => o.textContent);
    await expect(options).toEqual(["Select a status…", "Treatment planned", "Accepted", "Rejected"]);
  },
};

export const MovesWithAComment: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Change status" }));
    const d = dialog("Change status of RSK-001");
    await userEvent.selectOptions(d.getByLabelText("New status"), "treatment_planned");
    await userEvent.type(d.getByLabelText("Status change comment"), "Owner agreed a plan");
    await userEvent.click(d.getByRole("button", { name: "Change status" }));
    await waitFor(() => expect(args.onTransition).toHaveBeenCalledWith("treatment_planned", "Owner agreed a plan"));
  },
};

/** A refused move (an unmet guard) keeps the dialog open and shows why. */
export const RefusedMoveShowsTheReason: Story = {
  args: { onTransition: fn(async () => { throw new ApiError(409, "A residual rating is needed to accept."); }) },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Change status" }));
    const d = dialog("Change status of RSK-001");
    await userEvent.selectOptions(d.getByLabelText("New status"), "accepted");
    await expect(d.getByText(/needs the Risk Acceptor role/)).toBeInTheDocument();
    await userEvent.click(d.getByRole("button", { name: "Change status" }));
    await expect(await d.findByText("A residual rating is needed to accept.")).toBeInTheDocument();
  },
};

export const ClosedRiskWithNoMovesDisablesChange: Story = {
  args: { risk: buildRisk({ status: "closed", allowed_next_statuses: [] }) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Change status" })).toBeDisabled();
  },
};

export const ArchiveAsksForConfirmation: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Archive" }));
    await userEvent.click(dialog("Archive this Risk?").getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(args.onArchiveToggle).toHaveBeenCalled());
  },
};

export const ArchivedRiskOffersUnarchive: Story = {
  args: { risk: buildRisk({ is_archived: true }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Unarchive" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Change status" })).toBeDisabled();
  },
};

export const DarkTheme: Story = { ...OffersOnlyAllowedStatuses, globals: { theme: "dark" } };
