import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { expectStressStable } from "../../testing/stressFixtures";
import { TextStress } from "../../testing/TextStress";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { profileLifecycle, profileStageWorkflow } from "./approvalFixtures";
import { ProfileLifecycleTab } from "./ProfileLifecycleTab";
import type { ProfileStageWorkflow } from "./types";

const ORG_ID = "org-1";
const URL = `/api/v1/orgs/${ORG_ID}/modules/traceability/profiles/p-1`;

/** Answers the two reads of the tab. */
function mockReads(workflow: ProfileStageWorkflow = profileStageWorkflow()) {
  spyOn(api, "get").mockImplementation(async (path: string) => (path.endsWith("/stage-workflow") ? workflow : profileLifecycle()));
}

const meta: Meta<typeof ProfileLifecycleTab> = {
  title: "Modules/Governance/ProfileLifecycleTab",
  component: ProfileLifecycleTab,
  args: { orgId: ORG_ID, profileId: "p-1" },
  decorators: [withRouter("/"), withToast()],
  beforeEach: () => mockReads(),
};
export default meta;

type Story = StoryObj<typeof ProfileLifecycleTab>;

/** The required states are listed by record type, and the two other settings are drawn beneath. */
export const ShowsThePolicy: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = within(await canvas.findByRole("table", { name: "Required states by record type" }));
    await expect(table.getByText("Reviewed")).toBeInTheDocument();
    await expect(table.getByText("None")).toBeInTheDocument();
    await expect(canvas.getByRole("checkbox", { name: "Forbid skipping steps" })).not.toBeChecked();
  },
};

/** Saving one type's required states sends the chosen keys and says so. */
export const EditsRequiredStates: Story = {
  beforeEach: () => {
    mockReads();
    spyOn(api, "put").mockResolvedValue(profileLifecycle());
  },
  play: async ({ canvasElement }) => {
    const body = within(document.body);
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Actions for Risk required states" }));
    await userEvent.click(await body.findByRole("menuitem", { name: "Edit required states" }));
    const dialog = within(await body.findByRole("dialog", { name: "Required states: Risk" }));
    await userEvent.click(dialog.getByRole("checkbox", { name: "Treated" }));
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${URL}/lifecycle/risk`, { required: ["treated"] }));
    await expect(await body.findByText("Required states of Risk saved.")).toBeInTheDocument();
  },
};

/** The rule on skipping steps acts at once and ends in a toast. */
export const ForbidsSkippingAtOnce: Story = {
  beforeEach: () => {
    mockReads();
    spyOn(api, "put").mockResolvedValue(profileLifecycle({ skip_forbidden: true }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("checkbox", { name: "Forbid skipping steps" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${URL}/lifecycle/skip`, { forbidden: true }));
    await expect(await within(document.body).findByText("Rule on skipping steps saved.")).toBeInTheDocument();
    await waitFor(() => expect(canvas.getByRole("checkbox", { name: "Forbid skipping steps" })).toBeChecked());
  },
};

/** Choosing a workflow enables Save, which sends the workflow and how it binds. */
export const RequiresAStageWorkflow: Story = {
  beforeEach: () => {
    mockReads();
    spyOn(api, "put").mockResolvedValue(profileStageWorkflow({ workflow_id: "wf-1", workflow_name: "Standard delivery" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const save = await canvas.findByRole("button", { name: "Save" });
    await expect(save).toBeDisabled();
    await userEvent.selectOptions(canvas.getByLabelText("Stage workflow"), "wf-1");
    await userEvent.click(save);
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${URL}/stage-workflow`, { workflow_id: "wf-1", mode: "default" }));
    await expect(await canvas.findByText("Standard delivery", { selector: ".badge" })).toBeInTheDocument();
  },
};

/** A required workflow can be removed after a confirmation. */
export const RemovesTheRequirement: Story = {
  beforeEach: () => {
    mockReads(profileStageWorkflow({ workflow_id: "wf-1", workflow_name: "Standard delivery" }));
    spyOn(api, "delete").mockResolvedValue(profileStageWorkflow());
  },
  play: async ({ canvasElement }) => {
    const body = within(document.body);
    await userEvent.click(await within(canvasElement).findByRole("button", { name: "Remove requirement" }));
    const dialog = within(await body.findByRole("dialog", { name: "Remove required stage workflow" }));
    await userEvent.click(dialog.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${URL}/stage-workflow`));
    await expect(await body.findByText("Required stage workflow removed.")).toBeInTheDocument();
  },
};

/** With no workflow in the organisation the section says so and offers no empty choice. */
export const NoStageWorkflows: Story = {
  beforeEach: () => mockReads(profileStageWorkflow({ options: [] })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText(/has no stage workflows/)).toBeInTheDocument();
    await expect(canvas.queryByLabelText("Stage workflow")).toBeNull();
  },
};

/** A failed read shows the reason and a Retry. */
export const LoadFails: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new Error("Forbidden"));
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("The lifecycle policy could not be loaded.")).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...ShowsThePolicy, globals: { theme: "dark" } };

/** Long type and state names keep every row's columns and menu aligned. */
export const LongText: Story = {
  beforeEach: () => {
    const long = "An exceptionally long record type name that keeps going well past any sensible single line of text";
    const word = "Supercalifragilisticexpialidocious_Supercalifragilisticexpial";
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/stage-workflow")) return profileStageWorkflow();
      const isLong = path.includes("p-long");
      return profileLifecycle({
        types: [0, 1, 2].map((i) => ({
          artefact_type: `type-${i}`, label: isLong ? `${long} ${i}` : `Type ${i}`, module_key: "",
          states: [{ key: "s", label: isLong ? word : "Reviewed" }], required: ["s"],
        })),
      });
    });
  },
  render: () => <TextStress render={(long) => <ProfileLifecycleTab orgId={ORG_ID} profileId={long ? "p-long" : "p-short"} />} />,
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getAllByRole("table")).toHaveLength(2));
    await expectStressStable(canvasElement);
  },
};
