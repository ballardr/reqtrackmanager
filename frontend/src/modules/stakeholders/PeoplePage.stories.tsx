import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../../api/client";
import type { OrgUser } from "../../api/types";
import { buildRecordColumns } from "../../testing/recordTablesFixtures";
import { buildProject, withRouter, withToast } from "../../testing/storybook-helpers";
import { buildPersona, buildStakeholder, buildStakeholderGroup, buildStakeholderScheme } from "./fixtures";
import { PeoplePage } from "./PeoplePage";
import type { EffectivePersonaType, Persona, Stakeholder, StakeholderGroup } from "./types";
import { openListMenu, chooseExport } from "../../testing/listActionsMenu";

const PROJECT_ID = "project-1";
const BASE = `/api/v1/projects/${PROJECT_ID}/modules/stakeholders`;
const ROUTE = "/projects/:projectId/modules/stakeholders/people";

const PERSONA_TYPES: EffectivePersonaType[] = [
  { id: "type-primary", name: "Primary", display_order: 0, is_enabled: true, source: "org" },
  { id: "type-off", name: "Switched off", display_order: 1, is_enabled: false, source: "project_override" },
];
const STAKEHOLDER_TYPES: EffectivePersonaType[] = [
  { id: "stype-regulator", name: "Regulator", display_order: 0, is_enabled: true, source: "org" },
];
const ORG_USERS: OrgUser[] = [
  {
    user_id: "user-2", email: "jamie.lee@example.com", display_name: "Jamie Lee", is_active: true, is_archived: false,
    roles: ["member"], display_name_locked: false, last_login_at: null, is_2fa_enabled: false, module_roles: [], custom_roles: [],
  },
];

const ORG = { scope: "organization", organization_id: "org-1", project_id: null } as const;
const PERSONA = buildPersona();
const ORG_PERSONA = buildPersona({
  ...ORG, id: "persona-2", name: "Compliance Auditor", status: "draft", weight: null, effective_weight: 5, persona_type_name: "Secondary",
});
const STAKEHOLDER = buildStakeholder();
const GROUP = buildStakeholderGroup({ id: "group-1", name: "Client", scope: "project", organization_id: null, project_id: "project-1", member_count: 3 });

interface Data {
  personas: Persona[];
  hiddenPersonas: Persona[];
  stakeholders: Stakeholder[];
  groups: StakeholderGroup[];
  /** `disabled_sub_components` the project reports for the module. */
  disabled: string[];
}

function mockApis(data: Partial<Data> = {}) {
  const d: Data = {
    personas: [PERSONA, ORG_PERSONA], hiddenPersonas: [], stakeholders: [STAKEHOLDER], groups: [GROUP],
    disabled: [], ...data,
  };
  spyOn(api, "get").mockImplementation(async (path: string) => {
    const [route] = path.split("?");
    if (/\/records\/[a-z_]+\/columns$/.test(route)) return buildRecordColumns({ label: "Records" });
    if (route === `/api/v1/projects/${PROJECT_ID}/enabled-modules`) {
      return [{ module_key: "stakeholders", name: "Stakeholders & Personas", frontend_manifest: null, disabled_sub_components: d.disabled }];
    }
    if (route === `${BASE}/personas`) return path.includes("include_hidden=true") ? [...d.personas, ...d.hiddenPersonas] : d.personas;
    if (route === `${BASE}/persona-types`) return PERSONA_TYPES;
    if (route === `${BASE}/stakeholders`) return d.stakeholders;
    if (route === `${BASE}/stakeholder-types`) return STAKEHOLDER_TYPES;
    if (route === `${BASE}/stakeholder-groups`) return d.groups;
    if (route === `/api/v1/projects/${PROJECT_ID}/scoring-schemes/stakeholder`) return buildStakeholderScheme();
    if (route === `/api/v1/projects/${PROJECT_ID}`) return buildProject({ id: PROJECT_ID, organization_id: "org-1" });
    if (route === "/api/v1/orgs/org-1/users") return ORG_USERS;
    if (route.startsWith("/api/v1/orgs/org-1/users/search")) return { members: ORG_USERS, external: null };
    throw new Error(`Unmocked GET: ${path}`);
  });
}

/** Mounts the page at its route; a story's `parameters.kind` becomes the `?kind=` query (all kinds when unset). */
const withPeopleRoute: Decorator = (Story, context) => {
  const kind = context.parameters.kind as string | undefined;
  const path = `/projects/${PROJECT_ID}/modules/stakeholders/people${kind ? `?kind=${kind}` : ""}`;
  return withRouter(path, ROUTE)(Story, context);
};

const meta: Meta<typeof PeoplePage> = {
  title: "Modules/Stakeholders/PeoplePage",
  component: PeoplePage,
  decorators: [withPeopleRoute, withToast()],
};
export default meta;

type Story = StoryObj<typeof PeoplePage>;

/** With the page rendered inside the dialog portal: the create forms live in `document.body`. */
const dialog = () => within(within(document.body).getByRole("dialog"));
const newMenuItem = async (canvas: ReturnType<typeof within>, name: string) => {
  await userEvent.click(await canvas.findByRole("button", { name: "New" }));
  await userEvent.click(within(document.body).getByRole("menuitem", { name }));
};

export const ListsEveryKindTogether: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Field Technician")).toBeInTheDocument());
    const table = within(canvas.getByRole("table", { name: "People" }));
    for (const name of ["Field Technician", "Pat Regulator", "Client"]) {
      await expect(table.getByText(name)).toBeInTheDocument();
    }
    // Kind, scope and status go through their label maps, never the raw wire value.
    for (const kind of ["Persona", "Stakeholder", "Stakeholder Group"]) {
      await expect(table.getAllByText(kind).length).toBeGreaterThan(0);
    }
    await expect(table.getByText("Organisation")).toBeInTheDocument();
    await expect(table.getByText("Draft")).toBeInTheDocument();
    await expect(canvas.queryByText("organization")).not.toBeInTheDocument();
    await expect(canvas.queryByText("stakeholder_need")).not.toBeInTheDocument();
    // Needs are not people: they are a tab, not a row.
    await expect(table.queryByText("Diagnose faults quickly")).not.toBeInTheDocument();
    await expect(canvas.getByRole("tab", { name: "Needs" })).toBeInTheDocument();
    await expect(canvas.getByRole("tab", { name: "People" })).toHaveAttribute("aria-selected", "true");
    // Every row carries its kind's icon, named by the kind (never colour or shape alone).
    for (const kind of ["Persona", "Stakeholder", "Stakeholder Group"]) {
      await expect(table.getAllByRole("img", { name: kind }).length).toBeGreaterThan(0);
    }
    // A group row says how many members it has; the list has no create button of its own.
    await expect(table.getByText("3 members")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "New Persona" })).not.toBeInTheDocument();
  },
};

export const KindChipsNarrowTheList: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByText("Field Technician"));
    const chips = within(canvas.getByRole("group", { name: "Kinds of record" }));
    for (const name of [/Personas/, /Stakeholders/, /Groups/]) {
      await expect(chips.getByRole("button", { name })).toHaveAttribute("aria-pressed", "true");
    }
    await userEvent.click(chips.getByRole("button", { name: /Groups/ }));
    await waitFor(() => expect(canvas.queryByText("Client")).not.toBeInTheDocument());
    await expect(canvas.getByText("Field Technician")).toBeInTheDocument();
    await expect(canvas.getByText("Pat Regulator")).toBeInTheDocument();
    await expect(chips.getByRole("button", { name: /Groups/ })).toHaveAttribute("aria-pressed", "false");
  },
};

/** The last chip cannot be turned off: an empty selection would mean an empty page. */
export const TheLastKindCannotBeTurnedOff: Story = {
  parameters: { kind: "group" },
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const groups = await canvas.findByRole("button", { name: /Groups/ });
    await userEvent.click(groups);
    await expect(groups).toHaveAttribute("aria-pressed", "true");
  },
};

/** Exactly one kind shows that kind's own list: Personas gain Weight, Stakeholders gain levels and last engaged. */
export const OneKindShowsItsOwnColumns: Story = {
  parameters: { kind: "persona" },
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByText("Field Technician"));
    const table = within(canvas.getByRole("table", { name: "Personas" }));
    await expect(table.getByRole("columnheader", { name: "Weight" })).toBeInTheDocument();
    // The org persona's weight column shows this project's effective weight.
    await expect(table.getByText("5")).toBeInTheDocument();
    await expect(canvas.queryByText("Pat Regulator")).not.toBeInTheDocument();
  },
};

export const StakeholdersOnlyKeepsGroupFilteringAndLastEngaged: Story = {
  parameters: { kind: "stakeholder" },
  beforeEach: () => mockApis({ stakeholders: [buildStakeholder({ last_engaged: "2026-04-02" })], groups: [GROUP] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByText("Pat Regulator"));
    const table = within(canvas.getByRole("table", { name: "Stakeholders" }));
    for (const column of ["Last engaged", "Influence", "Interest", "Cadence", "Groups"]) {
      await expect(table.getByRole("columnheader", { name: column })).toBeInTheDocument();
    }
    await expect(table.getByText("2026-04-02")).toBeInTheDocument();
    await expect(canvas.getByLabelText("Group by")).toBeInTheDocument();
  },
};

/** A kind whose sub-component is off is not a chip and not in the New menu. */
export const DisabledSubComponentRemovesItsKind: Story = {
  beforeEach: () => mockApis({ disabled: ["persona"], personas: [] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByText("Pat Regulator"));
    const chips = within(canvas.getByRole("group", { name: "Kinds of record" }));
    await expect(chips.queryByRole("button", { name: /Personas/ })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "New" }));
    const menu = within(within(document.body).getByRole("menu"));
    await expect(menu.getByRole("menuitem", { name: "Stakeholder" })).toBeInTheDocument();
    await expect(menu.queryByRole("menuitem", { name: "Persona" })).not.toBeInTheDocument();
    await expect(api.get).not.toHaveBeenCalledWith(expect.stringContaining(`${BASE}/personas`));
  },
};

/** With Needs switched off there is nothing to tab to, so no tab strip. */
export const WithoutNeedsThereAreNoTabs: Story = {
  beforeEach: () => mockApis({ disabled: ["stakeholder_need"] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByText("Field Technician"));
    await expect(canvas.queryByRole("tablist")).not.toBeInTheDocument();
  },
};

export const NewMenuOffersEveryKind: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "New" }));
    const menu = within(within(document.body).getByRole("menu", { name: "New person or group" }));
    for (const name of ["Persona", "Stakeholder", "Stakeholder from organisation user", "Stakeholder Group"]) {
      await expect(menu.getByRole("menuitem", { name })).toBeInTheDocument();
    }
    // Needs are created from the Needs tab, not from People.
    await expect(menu.queryByRole("menuitem", { name: "Stakeholder Need" })).not.toBeInTheDocument();
  },
};

export const CreatePersonaOffersOnlyEnabledTypes: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await newMenuItem(canvas, "Persona");
    await expect(dialog().getByRole("option", { name: "Primary" })).toBeInTheDocument();
    await expect(dialog().queryByRole("option", { name: "Switched off" })).not.toBeInTheDocument();
  },
};

export const CreatePersona: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "post").mockResolvedValue(buildPersona());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await newMenuItem(canvas, "Persona");
    await userEvent.type(dialog().getByLabelText("Persona name"), "Safety Officer");
    await userEvent.click(dialog().getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${BASE}/personas`, expect.not.objectContaining({ activate: true })));
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
  },
};

export const SaveAndActivateCreatesAnActivePersona: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "post").mockResolvedValue(buildPersona());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await newMenuItem(canvas, "Persona");
    await userEvent.type(dialog().getByLabelText("Persona name"), "Safety Officer");
    await userEvent.click(dialog().getByRole("button", { name: "Save and activate" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`${BASE}/personas`, expect.objectContaining({ name: "Safety Officer", activate: true })),
    );
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
  },
};

export const CreateStakeholderAndActivate: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "post").mockResolvedValue(buildStakeholder());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await newMenuItem(canvas, "Stakeholder");
    await userEvent.type(dialog().getByLabelText("Stakeholder name"), "Pat Regulator");
    await userEvent.click(dialog().getByRole("button", { name: "Save and activate" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`${BASE}/stakeholders`, expect.objectContaining({ name: "Pat Regulator", activate: true })),
    );
  },
};

export const CreateGroup: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "post").mockResolvedValue(GROUP);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await newMenuItem(canvas, "Stakeholder Group");
    await userEvent.type(dialog().getByLabelText("Group name"), "Suppliers");
    await userEvent.click(dialog().getByRole("button", { name: "Save" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`${BASE}/stakeholder-groups`, expect.objectContaining({ name: "Suppliers" })),
    );
  },
};

export const AddStakeholderFromAnOrgUser: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "post").mockResolvedValue(buildStakeholder({ name: "Jamie Lee", user_id: "user-2" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await newMenuItem(canvas, "Stakeholder from organisation user");
    await userEvent.type(dialog().getByLabelText("Organisation user"), "Jamie");
    await waitFor(() => dialog().getByText(/Jamie Lee/));
    await userEvent.click(dialog().getByText(/Jamie Lee/));
    await userEvent.click(dialog().getByRole("button", { name: "Add Stakeholder" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(`${BASE}/stakeholders/from-user`, { user_id: "user-2", stakeholder_type_id: null, role: "" }),
    );
  },
};

export const CreateErrorKeepsTheFormOpen: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "post").mockRejectedValue(new ApiError(403, "Only a Persona Owner (or admin/manager) may do this."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await newMenuItem(canvas, "Persona");
    await userEvent.type(dialog().getByLabelText("Persona name"), "X");
    await userEvent.click(dialog().getByRole("button", { name: "Save and activate" }));
    await waitFor(() => expect(dialog().getByText("Only a Persona Owner (or admin/manager) may do this.")).toBeInTheDocument());
  },
};

const HIDDEN = buildPersona({
  ...ORG, id: "persona-hidden", name: "Hidden Technician", project_hidden: true, hidden_override: true, hidden_source: "project",
});

export const HiddenRecordsAreOnlyListedOnRequestAndCanBeShown: Story = {
  beforeEach: () => {
    mockApis({ hiddenPersonas: [HIDDEN] });
    spyOn(api, "delete").mockResolvedValue(buildPersona({ ...ORG, id: "persona-hidden", project_hidden: false }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByText("Field Technician"));
    await expect(canvas.queryByText("Hidden Technician")).not.toBeInTheDocument();
    await userEvent.click(canvas.getByLabelText("Show hidden"));
    await waitFor(() => expect(canvas.getByText("Hidden Technician")).toBeInTheDocument());
    // Who hid it goes through the label map.
    await expect(canvas.getByText("Hidden by this project")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Show Hidden Technician in this project" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`${BASE}/personas/persona-hidden/visibility`));
  },
};

export const StatusBadgeFiltersTheList: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByText("Compliance Auditor"));
    await userEvent.click(within(canvas.getByRole("table", { name: "People" })).getByRole("button", { name: "Draft" }));
    await waitFor(() => expect(canvas.queryByText("Field Technician")).not.toBeInTheDocument());
    await expect(canvas.getByText("Compliance Auditor")).toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockApis({ personas: [], stakeholders: [], groups: [] }),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("Nothing recorded for this project yet.")).toBeInTheDocument());
  },
};

export const LoadErrorShowsMessage: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.endsWith("/enabled-modules")) return [];
      throw new ApiError(404, "Module is not enabled.");
    });
  },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("Module is not enabled.")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...ListsEveryKindTogether };
export const DarkTheme: Story = { ...ListsEveryKindTogether, globals: { theme: "dark" } };

/** One kind: its own Export (and Import) with the list's filters. */
export const PersonasOnlyOffersTheirOwnExportWithTheFilters: Story = {
  parameters: { kind: "persona" },
  beforeEach: () => {
    mockApis();
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["code\n"], { type: "text/csv" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Field Technician")).toBeInTheDocument());
    await userEvent.selectOptions(canvas.getByLabelText("Status"), "draft");
    await chooseExport(canvas, "CSV");
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/records/persona/export?status=draft`));
  },
};

/** Several kinds: one menu with an Export and Import group per kind, each named, each acting on its own kind. */
export const SeveralKindsOfferAnExportEach: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["code\n"], { type: "text/csv" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Field Technician")).toBeInTheDocument());
    const menu = await openListMenu(canvas);
    for (const heading of ["Personas", "Stakeholders", "Groups"]) {
      await expect(await menu.findByText(heading)).toBeInTheDocument();
    }
    await userEvent.keyboard("{Escape}");
    await chooseExport(canvas, "CSV", "Stakeholders");
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/records/stakeholder/export`));
  },
};

/** Groups have no status or type, so while one of those filters is set there is no group export to offer. */
export const AGroupExportIsNotOfferedWhileAStatusFilterExcludesEveryGroup: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Field Technician")).toBeInTheDocument());
    await expect(await (await openListMenu(canvas)).findByText("Groups")).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await userEvent.selectOptions(canvas.getByLabelText("Status"), "draft");
    const menu = await openListMenu(canvas);
    await waitFor(() => expect(menu.queryByText("Groups")).not.toBeInTheDocument());
    await expect(menu.getByText("Personas")).toBeInTheDocument();
  },
};
