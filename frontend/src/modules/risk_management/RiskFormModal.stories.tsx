import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import type { OrgGroup, ProjectGroup } from "../../api/types";
import { buildRisk, buildRiskScheme, ORG_USERS, PROJECT_ID, RISK_TYPES } from "./riskFixtures";
import { RiskFormModal } from "./RiskFormModal";

const ORG_GROUPS: OrgGroup[] = [
  { id: "group-1", name: "Safety Board", member_user_ids: ["user-1", "user-2"], member_org_group_ids: [], idp_synced_group_name: null, granted_org_role: null },
];
const PROJECT_GROUPS: ProjectGroup[] = [
  { id: "pgroup-1", name: "Release squad", roles: [], member_user_ids: ["user-2"], member_org_group_ids: [], member_source_project_ids: [] },
];

/** The owner picker lists the organisation's and project's groups and searches users server-side. */
function mockDirectory() {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/orgs/org-1/groups")) return ORG_GROUPS as never;
    if (path.endsWith(`/projects/${PROJECT_ID}/groups`)) return PROJECT_GROUPS as never;
    return { members: [], external: null } as never;
  });
}

const meta: Meta<typeof RiskFormModal> = {
  title: "Modules/RiskManagement/RiskFormModal",
  component: RiskFormModal,
  args: {
    scheme: buildRiskScheme(), riskTypes: RISK_TYPES, orgUsers: ORG_USERS, organizationId: "org-1", projectId: PROJECT_ID,
    currentUserId: "user-1", onCancel: fn(), onSave: fn(),
  },
  beforeEach: mockDirectory,
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
        title: "Supplier may slip", owner: { type: "user", id: "user-1" },
        inherent_likelihood_level_id: "lik-4", inherent_consequence_level_id: "con-4", residual_likelihood_level_id: null,
      }),
      "",
    );
  },
};

/** An organisation group can own the risk; the form sends it as a typed principal. */
export const ChoosesAGroupOwner: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await userEvent.type(d.getByLabelText("Risk title"), "Supplier may slip");
    await userEvent.type(d.getByRole("combobox", { name: "Owner" }), "safety");
    await userEvent.click(await d.findByText("Safety Board"));
    await expect(d.getByText("Org group")).toBeInTheDocument();
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ owner: { type: "org_group", id: "group-1" } }), "",
    ));
  },
};

/** A project group can own it too, and Clear leaves the risk unowned. */
export const ChoosesAProjectGroupThenClearsIt: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await userEvent.type(d.getByLabelText("Risk title"), "Supplier may slip");
    await userEvent.type(d.getByRole("combobox", { name: "Owner" }), "release");
    await userEvent.click(await d.findByText("Release squad"));
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ owner: { type: "project_group", id: "pgroup-1" } }), "",
    ));
    await userEvent.click(d.getByRole("button", { name: "Clear: Owner" }));
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.onSave).toHaveBeenLastCalledWith(expect.objectContaining({ owner: null }), ""));
  },
};

/** Editing a group-owned risk shows the group's name, kind and member count, and an unchanged owner is not re-sent. */
export const EditShowsAGroupOwner: Story = {
  args: {
    initial: buildRisk({ owner: { type: "org_group", id: "group-1", label: "Safety Board", member_count: 2, exists: true } }),
  },
  play: async () => {
    const d = dialog();
    await expect(d.getByText("Safety Board")).toBeInTheDocument();
    await expect(d.getByText("Org group · 2 members")).toBeInTheDocument();
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
