import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { expectStressStable } from "../../testing/stressFixtures";
import { TextStress } from "../../testing/TextStress";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { profileApproval } from "./approvalFixtures";
import { ProfileApprovalTab } from "./ProfileApprovalTab";

const ORG_ID = "org-1";
const URL = `/api/v1/orgs/${ORG_ID}/modules/traceability/profiles/p-1/approval`;

const meta: Meta<typeof ProfileApprovalTab> = {
  title: "Modules/Governance/ProfileApprovalTab",
  component: ProfileApprovalTab,
  args: { orgId: ORG_ID, profileId: "p-1" },
  decorators: [withRouter("/"), withToast()],
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(profileApproval());
  },
};
export default meta;

type Story = StoryObj<typeof ProfileApprovalTab>;

/** One row per record type with a gate, listing the roles the profile adds. */
export const ListsTheTypes: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Approval policy by record type" });
    await expect(within(table).getByText("Quality Lead")).toBeInTheDocument();
    await expect(within(table).getByText("None")).toBeInTheDocument();
  },
};

/** Saving a type's roles sends the chosen roles and shows the response. */
export const EditsOneTypesApprovers: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(profileApproval());
    spyOn(api, "put").mockResolvedValue(profileApproval({
      types: [{ artefact_type: "requirement", label: "Requirement", module_key: "", roles: [{ kind: "project", key: "project_manager", label: "Project Manager" }] }],
    }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await userEvent.click(await canvas.findByRole("button", { name: "Actions for Requirement approvers" }));
    await userEvent.click(await body.findByRole("menuitem", { name: "Edit approvers" }));
    const dialog = within(await body.findByRole("dialog", { name: "Approvers: Requirement" }));
    await userEvent.click(dialog.getByRole("button", { name: "Additional approvers" }));
    await userEvent.click(await body.findByRole("checkbox", { name: "Additional approvers: Project Manager" }));
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${URL}/requirement`, { roles: [{ kind: "project", key: "project_manager" }] }));
    await expect(await body.findByText("Approvers of Requirement saved.")).toBeInTheDocument();
  },
};

/** An organisation with no record type that has a gate says so. */
export const NoGatedTypes: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(profileApproval({ types: [] }));
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("No record type of this organisation has an approval gate.")).toBeInTheDocument();
  },
};

/** A failed read shows the reason and a Retry. */
export const LoadFails: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new Error("Forbidden"));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("The approval policy could not be loaded.")).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...ListsTheTypes, globals: { theme: "dark" } };

/** Long type and role names keep every row's columns and menu aligned. */
export const LongText: Story = {
  beforeEach: () => {
    const long = "An exceptionally long record type name that keeps going well past any sensible single line of text";
    const role = "Supercalifragilisticexpialidocious_Supercalifragilisticexpial";
    spyOn(api, "get").mockImplementation(async (path: string) => profileApproval({
      types: ["Risk", "Decision", "Requirement"].map((label, i) => ({
        artefact_type: `type-${i}`, label: path.includes("p-long") ? `${long} ${i}` : label, module_key: "",
        roles: [{ kind: "custom" as const, key: `r${i}`, label: path.includes("p-long") ? role : "Lead" }],
      })),
    }));
  },
  render: () => <TextStress render={(long) => <ProfileApprovalTab orgId={ORG_ID} profileId={long ? "p-long" : "p-short"} />} />,
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getAllByRole("table")).toHaveLength(2));
    await expectStressStable(canvasElement);
  },
};
