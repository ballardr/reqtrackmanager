import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../../api/client";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { buildPersona } from "./fixtures";
import { ProjectPersonasPage } from "./ProjectPersonasPage";
import type { EffectivePersonaType, Persona } from "./types";

const PROJECT_ID = "project-1";
const BASE = `/api/v1/projects/${PROJECT_ID}/modules/stakeholders`;

const TYPES: EffectivePersonaType[] = [
  { id: "type-primary", name: "Primary", display_order: 0, is_enabled: true, source: "org" },
  { id: "type-off", name: "Switched off", display_order: 1, is_enabled: false, source: "project_override" },
];

function mockPageApis(personas: Persona[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.startsWith(`${BASE}/personas`)) return personas;
    if (path === `${BASE}/persona-types`) return TYPES;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof ProjectPersonasPage> = {
  title: "Modules/Stakeholders/ProjectPersonasPage",
  component: ProjectPersonasPage,
  decorators: [
    withRouter(`/projects/${PROJECT_ID}/modules/stakeholders/personas`, "/projects/:projectId/modules/stakeholders/personas"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof ProjectPersonasPage>;

export const ListsProjectAndOrgPersonas: Story = {
  beforeEach: () =>
    mockPageApis([
      buildPersona(),
      buildPersona({
        id: "persona-2", scope: "organization", organization_id: "org-1", project_id: null, name: "Compliance Auditor",
        status: "draft", weight: null, effective_weight: 5, persona_type_name: "Secondary",
      }),
    ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Field Technician")).toBeInTheDocument());
    await expect(canvas.getByText("Compliance Auditor")).toBeInTheDocument();
    // Scope and status go through their label maps, never the raw wire value.
    const table = within(canvas.getByRole("table", { name: "Personas" }));
    await expect(table.getByText("Organisation")).toBeInTheDocument();
    await expect(table.getByText("Project")).toBeInTheDocument();
    await expect(table.getByText("Draft")).toBeInTheDocument();
    await expect(canvas.queryByText("organization")).not.toBeInTheDocument();
    // The org persona's weight column shows this project's effective weight.
    await expect(table.getByText("5")).toBeInTheDocument();
  },
};

export const StatusBadgeFiltersTheList: Story = {
  beforeEach: () => mockPageApis([buildPersona(), buildPersona({ id: "persona-2", name: "Compliance Auditor", status: "draft" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByText("Compliance Auditor"));
    await userEvent.click(canvas.getByRole("button", { name: "Draft" }));
    await waitFor(() => expect(canvas.queryByText("Field Technician")).not.toBeInTheDocument());
    await expect(canvas.getByText("Compliance Auditor")).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("No Personas recorded for this project yet.")).toBeInTheDocument());
  },
};

export const CreateOffersOnlyEnabledTypes: Story = {
  beforeEach: () => mockPageApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Persona" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Persona" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await expect(dialog.getByRole("option", { name: "Primary" })).toBeInTheDocument();
    await expect(dialog.queryByRole("option", { name: "Switched off" })).not.toBeInTheDocument();
  },
};

export const CreatePersona: Story = {
  beforeEach: () => {
    mockPageApis([]);
    spyOn(api, "post").mockResolvedValue(buildPersona());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Persona" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Persona" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("Persona name"), "Field Technician");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`${BASE}/personas`, expect.objectContaining({ name: "Field Technician" })),
    );
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
  },
};

export const CreateErrorKeepsModalOpen: Story = {
  beforeEach: () => {
    mockPageApis([]);
    spyOn(api, "post").mockRejectedValue(new ApiError(403, "Only a Persona Owner (or admin/manager) may do this."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "New Persona" }));
    await userEvent.click(canvas.getByRole("button", { name: "New Persona" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("Persona name"), "X");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(dialog.getByText("Only a Persona Owner (or admin/manager) may do this.")).toBeInTheDocument());
  },
};

export const LoadErrorShowsMessage: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new ApiError(404, "Module is not enabled."));
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("Module is not enabled.")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...ListsProjectAndOrgPersonas };
export const DarkTheme: Story = { ...ListsProjectAndOrgPersonas, globals: { theme: "dark" } };
