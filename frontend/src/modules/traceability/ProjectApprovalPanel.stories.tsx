import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { expectStressStable } from "../../testing/stressFixtures";
import { TextStress } from "../../testing/TextStress";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { projectApproval } from "./approvalFixtures";
import { ProjectApprovalPanel } from "./ProjectApprovalPanel";

const PROJECT_ID = "project-1";
const URL = `/api/v1/projects/${PROJECT_ID}/modules/traceability/approval-policies`;

const meta: Meta<typeof ProjectApprovalPanel> = {
  title: "Modules/Governance/ProjectApprovalPanel",
  component: ProjectApprovalPanel,
  args: { projectId: PROJECT_ID },
  decorators: [withRouter("/"), withToast()],
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(projectApproval());
  },
};
export default meta;

type Story = StoryObj<typeof ProjectApprovalPanel>;

/** Each type shows its effective approvers with where each comes from, and whether the project's own row, an ancestor's or only profiles supply them. */
export const ShowsEffectiveApproversAndSources: Story = {
  play: async ({ canvasElement }) => {
    const table = within(await within(canvasElement).findByRole("table", { name: "Approval policy by record type" }));
    await expect(table.getByText("Parent project, Regulated work")).toBeInTheDocument();
    await expect(table.getByText("This project")).toBeInTheDocument();
    await expect(table.getByText("Inherited from Programme Alpha")).toBeInTheDocument();
    await expect(table.getByText("Own")).toBeInTheDocument();
    await expect(table.getByText("Profiles only")).toBeInTheDocument();
  },
};

/** Saving the project's own roles sends them and shows the response. */
export const SavesTheProjectsOwnRoles: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(projectApproval());
    spyOn(api, "put").mockResolvedValue(projectApproval());
  },
  play: async ({ canvasElement }) => {
    const body = within(document.body);
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Actions for Strategy approvers" }));
    await userEvent.click(await body.findByRole("menuitem", { name: "Edit approvers" }));
    const dialog = within(await body.findByRole("dialog", { name: "Approvers: Strategy" }));
    await userEvent.click(dialog.getByRole("button", { name: "Additional approvers" }));
    await userEvent.click(await body.findByRole("checkbox", { name: "Additional approvers: Governance Manager" }));
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${URL}/strategy`, { roles: [{ kind: "module", key: "traceability:governance_manager" }] }));
    await expect(await body.findByText("Approvers of Strategy saved.")).toBeInTheDocument();
  },
};

/** A type that has its own roles can return to the inherited value, which sends `null`. */
export const ReturnsToTheInheritedValue: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(projectApproval());
    spyOn(api, "put").mockResolvedValue(projectApproval());
  },
  play: async ({ canvasElement }) => {
    const body = within(document.body);
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Actions for Decision approvers" }));
    await userEvent.click(await body.findByRole("menuitem", { name: "Edit approvers" }));
    const dialog = within(await body.findByRole("dialog", { name: "Approvers: Decision" }));
    await userEvent.click(dialog.getByRole("button", { name: "Use inherited value" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${URL}/decision`, { roles: null }));
    await expect(await body.findByText("Approvers of Decision now follow the inherited value.")).toBeInTheDocument();
  },
};

/** Without the permission to manage governance the table is read-only: no row menu. */
export const ReadOnlyWithoutPermission: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(projectApproval({ can_manage: false }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Approval policy by record type" });
    await expect(canvas.queryByRole("button", { name: /Actions for/ })).toBeNull();
  },
};

/** An organisation with no record type that has a gate says so. */
export const NoGatedTypes: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(projectApproval({ types: [] }));
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
    await expect(await within(canvasElement).findByText("The approval policy could not be loaded.")).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...ShowsEffectiveApproversAndSources, globals: { theme: "dark" } };

/** Long type, role and profile names keep every row's columns and menu aligned. */
export const LongText: Story = {
  beforeEach: () => {
    const long = "An exceptionally long record type name that keeps going well past any sensible single line of text";
    const word = "Supercalifragilisticexpialidocious_Supercalifragilisticexpial";
    spyOn(api, "get").mockImplementation(async (path: string) => {
      const isLong = path.includes("project-long");
      return projectApproval({
        types: ["Risk", "Decision", "Requirement"].map((label, i) => ({
          artefact_type: `type-${i}`, label: isLong ? `${long} ${i}` : label, module_key: "", own: null,
          inherited_from: isLong ? `Programme ${word}` : "Alpha",
          effective: [{ role: { kind: "custom" as const, key: `r${i}`, label: isLong ? word : "Lead" }, sources: [isLong ? long : "Profile"] }],
        })),
      });
    });
  },
  render: () => <TextStress render={(long) => <ProjectApprovalPanel projectId={long ? "project-long" : "project-short"} />} />,
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getAllByRole("table")).toHaveLength(2));
    await expectStressStable(canvasElement);
  },
};
