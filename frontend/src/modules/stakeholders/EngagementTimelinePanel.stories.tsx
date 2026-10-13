import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";
import { MemoryRouter } from "react-router-dom";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { buildEngagement } from "./fixtures";
import { EngagementTimelinePanel } from "./EngagementTimelinePanel";
import type { StakeholderEngagement } from "./types";

const TIMELINE: StakeholderEngagement[] = [
  { id: "e2", title: "Evidence follow-up", channel: "email", engagement_date: "2026-04-02" },
  { id: "e1", title: "Quarterly review", channel: "meeting", engagement_date: "2026-03-12" },
];

const meta: Meta<typeof EngagementTimelinePanel> = {
  title: "Modules/Stakeholders/EngagementTimelinePanel",
  component: EngagementTimelinePanel,
  decorators: [
    withToast(),
    (Story) => (
      <MemoryRouter>
        <Story />
      </MemoryRouter>
    ),
  ],
  args: {
    projectId: "project-1",
    subject: { kind: "stakeholder", id: "stakeholder-1", name: "Pat Regulator" },
    load: fn(async () => TIMELINE),
  },
};
export default meta;

type Story = StoryObj<typeof EngagementTimelinePanel>;

export const ListsEngagementsNewestFirstWithLabelledChannels: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "2026-04-02 · Email · Evidence follow-up" })).toHaveAttribute(
      "href", "/projects/project-1/modules/stakeholders/engagements/e2",
    ));
    await expect(canvas.getByRole("link", { name: "2026-03-12 · Meeting · Quarterly review" })).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  args: { load: fn(async () => []) },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("No engagements logged yet.")).toBeInTheDocument());
  },
};

/** The organisation route has no project, so engagements (project-scoped) are not shown there. */
export const RendersNothingOutsideAProject: Story = {
  args: { projectId: undefined },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button", { name: "Log contact" })).not.toBeInTheDocument();
  },
};

export const LogContactAttachesTheStakeholder: Story = {
  beforeEach: () => {
    spyOn(api, "post").mockResolvedValue(buildEngagement());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Log contact" }));
    await userEvent.click(canvas.getByRole("button", { name: "Log contact" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Log contact with Pat Regulator" }));
    await expect(dialog.getByLabelText("Engagement title")).toHaveValue("Contact with Pat Regulator");
    await userEvent.type(dialog.getByLabelText("Summary"), "Asked for the export.");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        "/api/v1/projects/project-1/modules/stakeholders/engagements",
        expect.objectContaining({ title: "Contact with Pat Regulator", channel: "email", summary: "Asked for the export.", stakeholder_ids: ["stakeholder-1"] }),
      ),
    );
    await waitFor(() => expect(within(document.body).getByText("Contact logged.")).toBeInTheDocument());
  },
};

export const LogContactForAPersonaCoversIt: Story = {
  args: { subject: { kind: "persona", id: "persona-1", name: "Field Technician" } },
  beforeEach: () => {
    spyOn(api, "post").mockResolvedValue(buildEngagement());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Log contact" }));
    await userEvent.click(canvas.getByRole("button", { name: "Log contact" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Log contact with Field Technician" }));
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ persona_ids: ["persona-1"] })),
    );
  },
};

export const DarkTheme: Story = { ...ListsEngagementsNewestFirstWithLabelledChannels, globals: { theme: "dark" } };
