import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, userEvent, waitFor, within } from "storybook/test";

import {
  buildApprovalSeparationApi, buildProjectSeparation, buildProjectSeparations,
} from "../testing/approvalSeparationFixtures";
import { ApprovalSeparationSection } from "./ApprovalSeparationSection";

/**
 * The Approval section of the project Lifecycles group: for each record type with an approval step, whether the person
 * who created a record may approve it (default, submitter may approve with a comment, separate approver required).
 */
const meta: Meta<typeof ApprovalSeparationSection> = {
  title: "Components/ApprovalSeparationSection",
  component: ApprovalSeparationSection,
  args: { projectId: "project-1", api: buildApprovalSeparationApi() },
};
export default meta;

type Story = StoryObj<typeof ApprovalSeparationSection>;

export const EveryApprovalTypeIsOffered: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("combobox", { name: "Change request approval" })).toHaveValue("inherit");
    await expect(canvas.getByRole("combobox", { name: "Decision approval" })).toHaveValue("inherit");
    await expect(canvas.getAllByRole("option", { name: "Default: submitter may approve", selected: true })).toHaveLength(2);
  },
};

export const RequiringASeparateApproverSavesTheChoice: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Change request approval" }), "separate");
    await waitFor(() => expect(args.api!.setProject).toHaveBeenCalledWith("project-1", "change_request", true));
    await expect(await canvas.findByRole("combobox", { name: "Change request approval" })).toHaveValue("separate");
  },
};

export const LettingTheSubmitterApproveNeedsAComment: Story = {
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Decision approval" }), "creator");
    await waitFor(() => expect(args.api!.setProject).toHaveBeenCalledWith("project-1", "decision", false));
  },
};

export const GoingBackToTheDefaultStoresNothing: Story = {
  args: {
    api: buildApprovalSeparationApi(buildProjectSeparations([
      buildProjectSeparation({ own: true, chosen: true, separate: true, source: "project" }),
    ])),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByRole("combobox", { name: "Change request approval" }), "inherit");
    await waitFor(() => expect(args.api!.setProject).toHaveBeenCalledWith("project-1", "change_request", null));
  },
};

export const TheOrganisationsRequirementIsShownLocked: Story = {
  args: {
    api: buildApprovalSeparationApi(buildProjectSeparations([buildProjectSeparation({ required: true, separate: true })])),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = await canvas.findByRole("combobox", { name: "Change request approval" });
    await expect(select).toBeDisabled();
    await expect(select).toHaveValue("separate");
    await expect(canvas.getByText("Required by the organisation")).toBeInTheDocument();
  },
};

export const AnExemptProjectMayChoose: Story = {
  args: {
    api: buildApprovalSeparationApi(buildProjectSeparations([buildProjectSeparation({ exempt: true })])),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("combobox", { name: "Change request approval" })).toBeEnabled();
    await expect(canvas.getByText("Exempt from the organisation's requirement")).toBeInTheDocument();
  },
};

export const ANestedProjectFollowsItsParent: Story = {
  args: {
    api: buildApprovalSeparationApi(buildProjectSeparations(
      [buildProjectSeparation({ chosen: true, separate: true, source: "parent_project" })], { has_parent: true },
    )),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("option", { name: "Follow parent project" })).toBeInTheDocument();
    await expect(canvas.getByText("Inherited from parent project")).toBeInTheDocument();
  },
};

export const WithoutPermissionTheChoiceIsReadOnly: Story = {
  args: {
    api: buildApprovalSeparationApi(buildProjectSeparations([buildProjectSeparation()], { can_manage: false })),
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByRole("combobox", { name: "Change request approval" })).toBeDisabled();
  },
};

/** A type only an organisation administrator may self-approve names the administrator in its choices. */
export const ATypeLimitedToAdministratorsSaysSo: Story = {
  args: {
    api: buildApprovalSeparationApi(buildProjectSeparations([
      buildProjectSeparation({
        artefact_type: "traceability_exception", label: "Traceability exception", self_approval_org_admins_only: true,
      }),
    ])),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = await canvas.findByRole("combobox", { name: "Traceability exception approval" });
    await expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Default: organisation administrator who submitted it may approve",
      "Organisation administrator who submitted it may approve, with a comment",
      "Separate approver required",
    ]);
  },
};
