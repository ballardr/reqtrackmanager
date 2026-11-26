import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { openAddDialog, withToast } from "../testing/storybook-helpers";
import { OrgRequirementTypesPanel, ProjectRequirementTypesPanel } from "./RequirementTypesPanels";
import type { EffectiveTypeRow, OrgTypeRow } from "./TypeVocabularyPanels";

const ORG_TYPES: OrgTypeRow[] = [
  { id: "t1", name: "Business Requirement", is_active: true, rank: 1 },
  { id: "t2", name: "Stakeholder Requirement", is_active: true, rank: 2 },
  { id: "t3", name: "Project Requirement", is_active: true, rank: 3 },
];
const PROJECT_TYPES: EffectiveTypeRow[] = [
  { id: "t1", name: "Business Requirement", display_order: 0, is_enabled: true, source: "org", rank: 1 },
  { id: "t3", name: "Project Requirement", display_order: 2, is_enabled: true, source: "org", rank: 3 },
  { id: "p1", name: "Interface", display_order: 3, is_enabled: true, source: "project_local", rank: null },
];

const meta: Meta = { title: "Components/RequirementTypesPanels", decorators: [withToast()] };
export default meta;

type Story = StoryObj;

/** The organisation's list shows the default types in order and adds one through the shared endpoint. */
export const OrganisationListShowsAndAddsTypes: Story = {
  render: () => <OrgRequirementTypesPanel orgId="org-1" />,
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(ORG_TYPES);
    spyOn(api, "post").mockResolvedValue({ id: "t4", name: "Regulatory", is_active: true });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Business Requirement")).toBeInTheDocument());
    await expect(canvas.getByDisplayValue("Project Requirement")).toBeInTheDocument();
    const dialog = await openAddDialog(canvas, "Add Requirement type");
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Regulatory");
    await userEvent.type(dialog.getByRole("spinbutton", { name: "Rank" }), "2");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/orgs/org-1/requirement-types", { name: "Regulatory", rank: 2 }));
  },
};

/** A project lists the organisation's types beside its own, with where each comes from. */
export const ProjectListsOrganisationAndOwnTypes: Story = {
  render: () => <ProjectRequirementTypesPanel projectId="project-1" />,
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => (path.endsWith("/hidden") ? [] : PROJECT_TYPES) as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Business Requirement")).toBeInTheDocument());
    await expect(canvas.getByDisplayValue("Interface")).toBeInTheDocument();
    await expect(canvas.getAllByText("Org default")).toHaveLength(2);
    await expect(canvas.getByText("Project only")).toBeInTheDocument();
  },
};

/** Hiding an organisation default asks first, then removes it from this project only. */
export const HidingAnOrganisationDefaultAsksFirst: Story = {
  render: () => <ProjectRequirementTypesPanel projectId="project-1" />,
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => (path.endsWith("/hidden") ? [] : PROJECT_TYPES) as never);
    spyOn(api, "delete").mockResolvedValue(undefined as never);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Business Requirement")).toBeInTheDocument());
    await userEvent.click(canvas.getAllByRole("button", { name: "Hide Requirement type in this project" })[0]);
    const dialog = within(await within(document.body).findByRole("dialog"));
    await userEvent.click(dialog.getByRole("button", { name: "Hide" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/api/v1/projects/project-1/requirement-types/t1"));
  },
};

/** Changing a rank saves it as a whole number with the name; emptying it makes the type unranked. */
export const ChangingARankSavesItAndEmptyingItClearsIt: Story = {
  render: () => <OrgRequirementTypesPanel orgId="org-1" />,
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue(ORG_TYPES);
    spyOn(api, "patch").mockResolvedValue({ id: "t1", name: "Business Requirement", is_active: true });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Business Requirement")).toBeInTheDocument());
    const [first] = canvas.getAllByRole("spinbutton", { name: "Rank" });
    await userEvent.clear(first);
    await userEvent.type(first, "5");
    await userEvent.click(canvas.getAllByRole("button", { name: "Rename" })[0]);
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith("/api/v1/orgs/org-1/requirement-types/t1", { name: "Business Requirement", rank: 5 }));
  },
};
