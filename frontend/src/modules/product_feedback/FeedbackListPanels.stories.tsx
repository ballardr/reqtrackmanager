import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import type { EffectiveTypeRow, OrgTypeRow } from "../../components/TypeVocabularyPanels";
import { withToast } from "../../testing/storybook-helpers";
import { OrgExternalSystemsPanel, ProjectRequestChannelsPanel } from "./FeedbackListPanels";

const SYSTEMS: OrgTypeRow[] = [
  { id: "s1", name: "Jira", is_active: true },
  { id: "s2", name: "ServiceNow", is_active: true },
];
const CHANNELS: EffectiveTypeRow[] = [
  { id: "c1", name: "Support ticket", display_order: 0, is_enabled: true, source: "org" },
  { id: "c2", name: "Hallway", display_order: 1, is_enabled: true, source: "project_local" },
];

const meta: Meta = { title: "Modules/ProductFeedback/FeedbackListPanels", decorators: [withToast()] };
export default meta;

type Story = StoryObj;

/** The organisation's external systems list uses the module's own endpoint. */
export const OrganisationSystemsAreAddedThroughTheModuleEndpoint: Story = {
  render: () => <OrgExternalSystemsPanel orgId="org-1" />,
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(SYSTEMS);
    spyOn(api, "post").mockResolvedValue({ id: "s3", name: "Linear", is_active: true });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Jira")).toBeInTheDocument());
    await userEvent.type(canvas.getByPlaceholderText("External system type name"), "Linear");
    await userEvent.click(canvas.getByRole("button", { name: "Add External system type" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/orgs/org-1/modules/product_feedback/external-systems", { name: "Linear" }));
  },
};

/** A project's channels list shows its own entry beside the organisation's, and deleting its own entry deletes it. */
export const ProjectChannelsListOrganisationAndOwnEntries: Story = {
  render: () => <ProjectRequestChannelsPanel projectId="project-1" />,
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => (path.endsWith("/hidden") ? [] : CHANNELS) as never);
    spyOn(api, "delete").mockResolvedValue(undefined as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Support ticket")).toBeInTheDocument());
    await expect(canvas.getByDisplayValue("Hallway")).toBeInTheDocument();
    await expect(canvas.getByText("Org default")).toBeInTheDocument();
    await expect(canvas.getByText("Project only")).toBeInTheDocument();
  },
};
