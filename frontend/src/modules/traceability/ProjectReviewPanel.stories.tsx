import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildProject, buildUser, withRouter, withStatefulAuth, withToast } from "../../testing/storybook-helpers";
import { expectStressStable, STRESS_TEXT } from "../../testing/stressFixtures";
import { TextStress } from "../../testing/TextStress";
import { buildProjectReview, mockGets, ORG_ID, ORG_USERS, ORG_USERS_URL, PMO, PROJECT_ID, projectReviewUrl } from "./policyFixtures";
import { ProjectReviewPanel } from "./ProjectReviewPanel";

const PROJECT_URL = `/api/v1/projects/${PROJECT_ID}`;
const reads = (canManage = true) => ({
  [projectReviewUrl]: buildProjectReview(canManage),
  [PROJECT_URL]: buildProject({ id: PROJECT_ID, organization_id: ORG_ID }),
  [ORG_USERS_URL]: ORG_USERS,
});

const meta: Meta<typeof ProjectReviewPanel> = {
  title: "Modules/Governance/ProjectReviewPanel",
  component: ProjectReviewPanel,
  args: { projectId: PROJECT_ID },
  decorators: [withRouter("/"), withToast(), withStatefulAuth(buildUser({ ui_preferences: {} }))],
  beforeEach: () => mockGets(reads()),
};
export default meta;

type Story = StoryObj<typeof ProjectReviewPanel>;

export const ShowsTheEffectiveSettingsAndTheProjectsOwn: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const own = (await canvas.findByRole("cell", { name: "Requirement" })).closest("tr")!;
    await expect(within(own).getByText("60")).toBeInTheDocument();
    await expect(within(own).getByText("Own")).toBeInTheDocument();
    const inherited = canvas.getByRole("cell", { name: "Risk" }).closest("tr")!;
    await expect(within(inherited).getByText("Inherited from Programme Atlas")).toBeInTheDocument();
    await expect(within(inherited).getByText("30")).toBeInTheDocument();
  },
};

export const EditingSavesTheProjectsOwnSettings: Story = {
  play: async ({ canvasElement }) => {
    spyOn(api, "put").mockResolvedValue(buildProjectReview());
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Actions for Requirement" }));
    await userEvent.click(await within(document.body).findByRole("menuitem", { name: "Edit review settings" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Edit review settings: Requirement" }));
    const lead = dialog.getByLabelText("Reminder lead (days)");
    await userEvent.clear(lead);
    await userEvent.type(lead, "10");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(
      `${projectReviewUrl}/requirement`, { settings: { interval_days: 60, lead_days: 10, default_owner: { type: "org_group", id: PMO.id } } },
    ));
    await expect(await within(document.body).findByText("Review settings for Requirement saved.")).toBeInTheDocument();
  },
};

export const UseInheritedValueFollowsTheParentProject: Story = {
  play: async ({ canvasElement }) => {
    spyOn(api, "put").mockResolvedValue(buildProjectReview());
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Actions for Requirement" }));
    await userEvent.click(await within(document.body).findByRole("menuitem", { name: "Edit review settings" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Edit review settings: Requirement" }));
    await userEvent.click(dialog.getByRole("button", { name: "Use inherited value" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${projectReviewUrl}/requirement`, { settings: null }));
  },
};

export const AReaderWhoCannotManageSeesNoEditControls: Story = {
  beforeEach: () => mockGets(reads(false)),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("cell", { name: "Requirement" });
    await expect(canvas.queryByRole("button", { name: /Actions for/ })).not.toBeInTheDocument();
  },
};

export const NoRecordTypeHasASchedule: Story = {
  beforeEach: () => mockGets({ ...reads(), [projectReviewUrl]: { can_manage: true, types: [] } }),
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("No record type has a review schedule.")).toBeInTheDocument();
  },
};

export const LongText: Story = {
  beforeEach: () => {
    let calls = 0;
    mockGets({
      ...reads(),
      [projectReviewUrl]: () => {
        const long = calls++ % 2 === 1;
        const review = buildProjectReview();
        if (long) {
          review.types[0].label = STRESS_TEXT.name;
          review.types[1].label = STRESS_TEXT.word;
          review.types[1].inherited_from = STRESS_TEXT.name;
          review.types[0].effective.default_owner = { ...PMO, label: STRESS_TEXT.word };
        }
        return review;
      },
    });
  },
  render: (args) => <TextStress render={() => <ProjectReviewPanel {...args} />} width={900} />,
  play: async ({ canvasElement }) => {
    await within(canvasElement).findAllByText("Own");
    await expectStressStable(canvasElement);
  },
};

export const DarkTheme: Story = { ...ShowsTheEffectiveSettingsAndTheProjectsOwn, globals: { theme: "dark" } };
