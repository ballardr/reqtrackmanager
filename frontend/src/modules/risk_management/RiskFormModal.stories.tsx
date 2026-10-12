import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildRisk, buildRiskScheme, ORG_USERS, RISK_TYPES } from "./riskFixtures";
import { RiskFormModal } from "./RiskFormModal";

const userOptions = ORG_USERS.map((u) => ({ id: u.user_id, display_name: u.display_name }));

const meta: Meta<typeof RiskFormModal> = {
  title: "Modules/RiskManagement/RiskFormModal",
  component: RiskFormModal,
  args: {
    scheme: buildRiskScheme(), riskTypes: RISK_TYPES, userOptions, currentUserId: "user-1",
    onCancel: fn(), onSave: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof RiskFormModal>;

const dialog = () => within(within(document.body).getByRole("dialog"));

export const CreateRequiresATitleAndDefaultsTheOwner: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await expect(d.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(d.getByLabelText("Risk title"), "Supplier may slip");
    await userEvent.selectOptions(d.getByLabelText("Inherent likelihood"), "lik-4");
    await userEvent.selectOptions(d.getByLabelText("Inherent consequence"), "con-4");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        title: "Supplier may slip", owner_id: "user-1",
        inherent_likelihood_level_id: "lik-4", inherent_consequence_level_id: "con-4", residual_likelihood_level_id: null,
      }),
      "",
    );
  },
};

export const EditPrefillsAndTakesAChangeNote: Story = {
  args: { initial: buildRisk() },
  play: async ({ args }) => {
    const d = dialog();
    await expect(d.getByLabelText("Risk title")).toHaveValue("Supplier firmware may be late");
    await expect(d.getByLabelText("Inherent likelihood")).toHaveValue("lik-4");
    await userEvent.type(d.getByLabelText("Change note"), "Reassessed after supplier call");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ title: "Supplier firmware may be late" }), "Reassessed after supplier call");
  },
};

/** The backend refuses level, strategy and criteria changes on an Accepted risk, so the form disables them. */
export const AcceptedRiskLocksLevelsStrategyAndCriteria: Story = {
  args: { initial: buildRisk({ status: "accepted", acceptance_criteria: "Tolerable if the date holds." }) },
  play: async () => {
    const d = dialog();
    await expect(d.getByLabelText("Inherent likelihood")).toBeDisabled();
    await expect(d.getByLabelText("Treatment strategy")).toBeDisabled();
    await expect(d.getByLabelText("Acceptance criteria")).toBeDisabled();
    await expect(d.getByLabelText("Risk title")).toBeEnabled();
    await expect(d.getByText(/levels, treatment strategy and acceptance criteria are locked/)).toBeInTheDocument();
  },
};

export const ShowsASaveError: Story = {
  args: { error: "Could not create risk." },
  play: async () => {
    await expect(dialog().getByText("Could not create risk.")).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...CreateRequiresATitleAndDefaultsTheOwner, globals: { theme: "dark" } };
