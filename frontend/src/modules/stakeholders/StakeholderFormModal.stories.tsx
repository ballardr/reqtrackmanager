import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { buildStakeholder, buildStakeholderScheme } from "./fixtures";
import { StakeholderFormModal } from "./StakeholderFormModal";
import type { CadenceHint } from "./types";

const TYPE_OPTIONS = [
  { value: "stype-regulator", label: "Regulator" },
  { value: "stype-customer", label: "Customer" },
];

const HINT: CadenceHint = { quadrant: "manage_closely", suggested_cadence: "monthly" };

const meta: Meta<typeof StakeholderFormModal> = {
  title: "Modules/Stakeholders/StakeholderFormModal",
  component: StakeholderFormModal,
  args: {
    scopeLabel: "project", typeOptions: TYPE_OPTIONS, scheme: buildStakeholderScheme(),
    loadHint: fn(async () => HINT), onCancel: fn(), onSave: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof StakeholderFormModal>;

// The modal portals to `document.body`.
const dialog = () => within(within(document.body).getByRole("dialog"));

export const CreateNeedsAName: Story = {
  play: async () => {
    await expect(within(document.body).getByRole("heading", { name: "New Stakeholder (project)" })).toBeInTheDocument();
    await expect(dialog().getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(dialog().getByLabelText("Stakeholder name"), "Pat Regulator");
    await expect(dialog().getByRole("button", { name: "Save" })).toBeEnabled();
    await expect(dialog().queryByLabelText("Change note")).not.toBeInTheDocument();
  },
};

export const SavesEnteredValues: Story = {
  play: async ({ args }) => {
    await userEvent.type(dialog().getByLabelText("Stakeholder name"), "Pat Regulator");
    await userEvent.type(dialog().getByLabelText("Interests"), "Evidence of compliance");
    await userEvent.selectOptions(dialog().getByLabelText("Type"), "stype-regulator");
    await userEvent.selectOptions(dialog().getByLabelText("Target engagement cadence"), "quarterly");
    await userEvent.selectOptions(dialog().getByLabelText("Influence"), "infl-high");
    await userEvent.selectOptions(dialog().getByLabelText("Interest"), "int-low");
    await userEvent.click(dialog().getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({
        name: "Pat Regulator", interests: "Evidence of compliance", stakeholder_type_id: "stype-regulator",
        target_cadence: "quarterly", influence_level_id: "infl-high", interest_level_id: "int-low",
      }),
    );
  },
};

export const BlankOptionalsSaveAsNull: Story = {
  play: async ({ args }) => {
    await userEvent.type(dialog().getByLabelText("Stakeholder name"), "Pat Regulator");
    await userEvent.click(dialog().getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ stakeholder_type_id: null, target_cadence: null, influence_level_id: null, interest_level_id: null }),
    );
  },
};

/** The hint appears once both levels are set, names the grid position, and never touches the cadence field. */
export const CadenceHintIsSuggestionOnly: Story = {
  play: async ({ args }) => {
    await userEvent.type(dialog().getByLabelText("Stakeholder name"), "Pat");
    await expect(dialog().queryByTestId("cadence-hint")).not.toBeInTheDocument();
    await userEvent.selectOptions(dialog().getByLabelText("Influence"), "infl-high");
    await userEvent.selectOptions(dialog().getByLabelText("Interest"), "int-high");
    await waitFor(() => expect(dialog().getByTestId("cadence-hint")).toHaveTextContent("Suggested: Monthly (Manage closely)"));
    await expect(args.loadHint).toHaveBeenCalledWith("infl-high", "int-high");
    await expect(dialog().getByLabelText("Target engagement cadence")).toHaveValue("");
  },
};

export const ContactInfoIsFlaggedConfidential: Story = {
  play: async () => {
    await expect(dialog().getByText(/Confidential personal data/)).toBeInTheDocument();
  },
};

export const WithoutAScoringSchemeOmitsTheLevelPickers: Story = {
  args: { scheme: null },
  play: async () => {
    await expect(dialog().queryByLabelText("Influence")).not.toBeInTheDocument();
    await expect(dialog().getByLabelText("Target engagement cadence")).toBeInTheDocument();
  },
};

export const EditPrefillsAndShowsChangeNote: Story = {
  args: { initial: buildStakeholder() },
  play: async () => {
    await expect(within(document.body).getByRole("heading", { name: "Edit Pat Regulator" })).toBeInTheDocument();
    await expect(dialog().getByLabelText("Stakeholder name")).toHaveValue("Pat Regulator");
    await expect(dialog().getByLabelText("Target engagement cadence")).toHaveValue("quarterly");
    await expect(dialog().getByLabelText("Influence")).toHaveValue("infl-high");
    await expect(dialog().getByLabelText("Change note")).toBeInTheDocument();
  },
};

export const EditKeepsDisabledCurrentTypeSelectable: Story = {
  args: { initial: buildStakeholder({ stakeholder_type_id: "stype-gone", stakeholder_type_name: "Retired type" }) },
  play: async () => {
    await expect(dialog().getByRole("option", { name: "Retired type (disabled)" })).toBeInTheDocument();
  },
};

export const ShowsError: Story = {
  args: { error: "Could not create Stakeholder." },
  play: async () => {
    await expect(dialog().getByText("Could not create Stakeholder.")).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...CreateNeedsAName, globals: { theme: "dark" } };
