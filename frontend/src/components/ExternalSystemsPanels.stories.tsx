import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import {withToast, openAddDialog } from "../testing/storybook-helpers";
import { OrgExternalSystemsPanel, ProjectExternalSystemsPanel } from "./ExternalSystemsPanels";
import type { EffectiveTypeRow, OrgTypeRow } from "./TypeVocabularyPanels";

const TEMPLATE = "https://tracker.example/browse/{key}";
const ORG_SYSTEMS: OrgTypeRow[] = [
  { id: "s1", name: "Jira", is_active: true, url_template: TEMPLATE },
  { id: "s2", name: "ServiceNow", is_active: true, url_template: null },
];
const PROJECT_SYSTEMS: EffectiveTypeRow[] = [
  { id: "s1", name: "Jira", display_order: 0, is_enabled: true, source: "org", url_template: TEMPLATE },
  { id: "p1", name: "Internal tracker", display_order: 1, is_enabled: true, source: "project_local", url_template: null },
];

const meta: Meta = { title: "Components/ExternalSystemsPanels", decorators: [withToast()] };
export default meta;

type Story = StoryObj;

/** The organisation's list shows each system's link template and adds a system with one through the shared endpoint. */
export const OrganisationListShowsAndAddsTemplates: Story = {
  render: () => <OrgExternalSystemsPanel orgId="org-1" />,
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(ORG_SYSTEMS);
    spyOn(api, "post").mockResolvedValue({ id: "s3", name: "Linear", is_active: true });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Jira")).toBeInTheDocument());
    await expect(canvas.getByDisplayValue(TEMPLATE)).toBeInTheDocument();
    const dialog = await openAddDialog(canvas, "Add External system type");
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Linear");
    await userEvent.type(dialog.getByRole("textbox", { name: "Link template" }), "https://linear.example/{{key}");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/v1/orgs/org-1/external-systems", { name: "Linear", url_template: "https://linear.example/{key}" }),
    );
  },
};

/** Changing a template saves it with the name; an emptied template clears it (null follows the organisation's). */
export const ChangingATemplateSavesItAndEmptyingItClearsIt: Story = {
  render: () => <OrgExternalSystemsPanel orgId="org-1" />,
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(ORG_SYSTEMS);
    spyOn(api, "patch").mockResolvedValue({ id: "s1", name: "Jira", is_active: true });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue(TEMPLATE)).toBeInTheDocument());
    const field = canvas.getByDisplayValue(TEMPLATE);
    await userEvent.clear(field);
    await userEvent.click(canvas.getByRole("button", { name: "Rename" }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith("/api/v1/orgs/org-1/external-systems/s1", { name: "Jira", url_template: null }));
  },
};

/** A project lists the organisation's systems beside its own, with where each comes from. */
export const ProjectListsOrganisationAndOwnSystems: Story = {
  render: () => <ProjectExternalSystemsPanel projectId="project-1" />,
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => (path.endsWith("/hidden") ? [] : PROJECT_SYSTEMS) as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Jira")).toBeInTheDocument());
    await expect(canvas.getByDisplayValue("Internal tracker")).toBeInTheDocument();
    await expect(canvas.getByText("Org default")).toBeInTheDocument();
    await expect(canvas.getByText("Project only")).toBeInTheDocument();
  },
};

/** Hiding an organisation default asks first, then removes it from this project only. */
export const HidingAnOrganisationDefaultAsksFirst: Story = {
  render: () => <ProjectExternalSystemsPanel projectId="project-1" />,
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => (path.endsWith("/hidden") ? [] : PROJECT_SYSTEMS) as never);
    spyOn(api, "delete").mockResolvedValue(undefined as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Jira")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "Hide External system type in this project" }));
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.click(dialog.getByRole("button", { name: "Hide" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/api/v1/projects/project-1/external-systems/s1"));
  },
};
