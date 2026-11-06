import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { OrgPainPointSubmissionPanel, ProjectPainPointSubmissionPanel } from "./PainPointSubmissionPanel";
import type { PainPointSubmissionSettings } from "./types";

const PROJECT_ID = "project-1";
const ORG_ID = "org-1";

function settings(overrides: Partial<PainPointSubmissionSettings> = {}): PainPointSubmissionSettings {
  return {
    submission_policy: "managers", source: "default", own_policy: null, organization_default: null, can_submit: false,
    restriction_message: "Pain Points are submitted by Pain Point Managers in this project.", ...overrides,
  };
}

const meta: Meta<typeof ProjectPainPointSubmissionPanel> = {
  title: "Modules/ContextStrategy/PainPointSubmissionPanel",
  component: ProjectPainPointSubmissionPanel,
  args: { projectId: PROJECT_ID },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof ProjectPainPointSubmissionPanel>;

/** A project with no setting of its own shows where its policy comes from. */
export const InheritedShowsTheSource: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(settings({ submission_policy: "members", source: "organization", organization_default: "members", can_submit: true }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = await canvas.findByLabelText("Who can submit a Pain Point");
    await expect(select).toHaveValue("");
    await expect(canvas.getByTestId("pain-point-submission-inherited")).toHaveTextContent(
      "Inherited from the organisation: Any project member.",
    );
  },
};

/** Choosing a value saves it at once and says so; the inherited line goes away. */
export const ChoosingAValueSavesAndConfirms: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(settings());
    spyOn(api, "put").mockResolvedValue(settings({ submission_policy: "members", source: "project", own_policy: "members", can_submit: true }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = await canvas.findByLabelText("Who can submit a Pain Point");
    await userEvent.selectOptions(select, "members");
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/context_strategy/pain-point-settings`, { submission_policy: "members" },
    ));
    await expect(await within(document.body).findByText("Submission setting saved.")).toBeInTheDocument();
    await expect(select).toHaveValue("members");
    await expect(canvas.queryByTestId("pain-point-submission-inherited")).toBeNull();
  },
};

/** Choosing Inherit removes the project's own setting (the server receives null). */
export const InheritClearsTheOverride: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(settings({ submission_policy: "members", source: "project", own_policy: "members", can_submit: true }));
    spyOn(api, "put").mockResolvedValue(settings());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = await canvas.findByLabelText("Who can submit a Pain Point");
    await userEvent.selectOptions(select, "");
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(expect.stringContaining("/pain-point-settings"), { submission_policy: null }));
    await expect(await canvas.findByTestId("pain-point-submission-inherited")).toBeInTheDocument();
  },
};

/** A refused save (the caller lacks permission) is reported and the control keeps its value. */
export const AFailedSaveIsReported: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(settings());
    spyOn(api, "put").mockRejectedValue(new Error("Insufficient project permissions."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByLabelText("Who can submit a Pain Point"), "members");
    await expect(await within(document.body).findByText("Insufficient project permissions.")).toBeInTheDocument();
  },
};

/** The organisation's default can be set and cleared. */
export const OrganisationDefaultSavesAndConfirms: Story = {
  render: () => <OrgPainPointSubmissionPanel orgId={ORG_ID} />,
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ submission_policy: null });
    spyOn(api, "put").mockResolvedValue({ submission_policy: "members" });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = await canvas.findByLabelText("Who can submit a Pain Point by default");
    await expect(select).toHaveValue("");
    await userEvent.selectOptions(select, "members");
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/context_strategy/pain-point-settings`, { submission_policy: "members" },
    ));
    await expect(await within(document.body).findByText("Submission default saved.")).toBeInTheDocument();
  },
};
