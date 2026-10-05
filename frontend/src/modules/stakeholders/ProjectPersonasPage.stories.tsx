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

const ORG = { scope: "organization", organization_id: "org-1", project_id: null } as const;
const HIDDEN_BY_PROJECT = buildPersona({
  ...ORG, id: "persona-hidden", name: "Hidden Technician", project_hidden: true, hidden_override: true, hidden_source: "project",
});
const HIDDEN_BY_PARENT = buildPersona({
  ...ORG, id: "persona-parent", name: "Parent-hidden Operator", project_hidden: true, hidden_override: null,
  hidden_source: "ancestor_project",
});

/** The list mock honouring `include_hidden`: hidden personas only come back when asked for. */
function mockListWithHidden() {
  const visible = buildPersona({ ...ORG, id: "persona-visible", name: "Visible Persona", project_hidden: false });
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.startsWith(`${BASE}/personas`)) {
      return path.includes("include_hidden=true") ? [visible, HIDDEN_BY_PROJECT, HIDDEN_BY_PARENT] : [visible];
    }
    if (path === `${BASE}/persona-types`) return TYPES;
    throw new Error(`Unmocked GET: ${path}`);
  });
}

export const HiddenPersonasAreOnlyListedOnRequest: Story = {
  beforeEach: () => mockListWithHidden(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Visible Persona")).toBeInTheDocument());
    await expect(canvas.queryByText("Hidden Technician")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByLabelText("Show hidden"));
    await waitFor(() => expect(canvas.getByText("Hidden Technician")).toBeInTheDocument());
    // Who hid each one goes through the label map; no raw enum value appears.
    await expect(canvas.getByText("Hidden by this project")).toBeInTheDocument();
    await expect(canvas.getByText("Hidden by a parent project")).toBeInTheDocument();
    await expect(canvas.queryByText("ancestor_project")).not.toBeInTheDocument();
  },
};

export const ShowingAProjectHiddenPersonaDropsTheOverride: Story = {
  beforeEach: () => {
    mockListWithHidden();
    spyOn(api, "delete").mockResolvedValue(buildPersona({ ...ORG, id: "persona-hidden", project_hidden: false }));
    spyOn(api, "put").mockResolvedValue(buildPersona());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Show hidden"));
    await userEvent.click(canvas.getByLabelText("Show hidden"));
    await userEvent.click(await canvas.findByRole("button", { name: "Show Hidden Technician in this project" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${BASE}/personas/persona-hidden/visibility`));
    await expect(api.put).not.toHaveBeenCalled();
  },
};

export const ShowingAParentHiddenPersonaOverridesIt: Story = {
  beforeEach: () => {
    mockListWithHidden();
    spyOn(api, "delete").mockResolvedValue(buildPersona());
    spyOn(api, "put").mockResolvedValue(buildPersona({ ...ORG, project_hidden: false, hidden_override: false }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByLabelText("Show hidden"));
    await userEvent.click(canvas.getByLabelText("Show hidden"));
    await userEvent.click(await canvas.findByRole("button", { name: "Show Parent-hidden Operator in this project" }));
    await waitFor(() => expect(api.put).toHaveBeenCalledWith(`${BASE}/personas/persona-parent/visibility`, { hidden: false }));
    await expect(api.delete).not.toHaveBeenCalled();
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
