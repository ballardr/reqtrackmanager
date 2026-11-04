import type { Decorator, Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildRecordColumns } from "../../testing/recordTablesFixtures";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { buildNeed, buildPersona } from "./fixtures";
import { NeedsPage } from "./NeedsPage";
import type { Need } from "./types";
import { openListMenu, chooseExport } from "../../testing/listActionsMenu";

const PROJECT_ID = "project-1";
const BASE = `/api/v1/projects/${PROJECT_ID}/modules/stakeholders`;
const ROUTE = "/projects/:projectId/modules/stakeholders/needs";

function mockApis(disabled: string[] = [], needs: Need[] = [buildNeed()]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    const [route] = path.split("?");
    if (/\/records\/[a-z_]+\/columns$/.test(route)) return buildRecordColumns({ label: "Records" });
    if (route === `/api/v1/projects/${PROJECT_ID}/enabled-modules`) {
      return [{ module_key: "stakeholders", name: "Stakeholders & Personas", frontend_manifest: null, disabled_sub_components: disabled }];
    }
    if (route === `${BASE}/needs`) return needs;
    if (route === `${BASE}/personas`) return [buildPersona()];
    if (route === `${BASE}/persona-types` || route === `${BASE}/stakeholder-types`) return [];
    if (route === `${BASE}/stakeholders` || route === `${BASE}/stakeholder-groups`) return [];
    if (route === `/api/v1/projects/${PROJECT_ID}/scoring-schemes/stakeholder`) return {};
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const withNeedsRoute: Decorator = (Story, context) =>
  withRouter(`/projects/${PROJECT_ID}/modules/stakeholders/needs`, ROUTE)(Story, context);

const meta: Meta<typeof NeedsPage> = {
  title: "Modules/Stakeholders/NeedsPage",
  component: NeedsPage,
  decorators: [withNeedsRoute, withToast()],
};
export default meta;

type Story = StoryObj<typeof NeedsPage>;

/** The Needs tab lists Stakeholder Needs on their own, beside the People tab, with a New button of their own. */
export const ListsNeedsUnderTheNeedsTab: Story = {
  beforeEach: () => mockApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Diagnose faults quickly")).toBeInTheDocument());
    await expect(canvas.getByRole("tab", { name: "Needs" })).toHaveAttribute("aria-selected", "true");
    await expect(canvas.getByRole("tab", { name: "People" })).toHaveAttribute("aria-selected", "false");
    const table = within(canvas.getByRole("table", { name: "Stakeholder Needs" }));
    await expect(table.getAllByText(/NEED-001/).length).toBeGreaterThan(0);
    await expect(table.queryByRole("columnheader", { name: "Type" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "New Stakeholder Need" })).toBeInTheDocument();
  },
};

export const CreateNeed: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "post").mockResolvedValue(buildNeed());
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "New Stakeholder Need" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.type(dialog.getByLabelText("Need name"), "Offline access");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${BASE}/needs`, expect.objectContaining({ name: "Offline access" })));
    await waitFor(() => expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument());
  },
};

export const EmptyState: Story = {
  beforeEach: () => mockApis([], []),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("No Stakeholder Needs recorded for this project yet.")).toBeInTheDocument());
  },
};

/** With every people kind off, Needs is the only tab: no strip, and the page is titled Needs. */
export const NeedsAloneHasNoTabs: Story = {
  beforeEach: () => mockApis(["persona", "stakeholder"]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByText("Diagnose faults quickly"));
    await expect(canvas.queryByRole("tablist")).not.toBeInTheDocument();
    await expect(canvas.getByRole("heading", { name: "Needs" })).toBeInTheDocument();
  },
};

export const SwitchedOffSaysSo: Story = {
  beforeEach: () => mockApis(["stakeholder_need"]),
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText(/Stakeholder Needs aren't enabled/)).toBeInTheDocument());
  },
};

/** The Needs list offers the shared Export and Import, narrowed by its own filters. */
export const ExportAndImportAreOnTheTitleRow: Story = {
  beforeEach: () => {
    mockApis();
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["code\n"], { type: "text/csv" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Diagnose faults quickly")).toBeInTheDocument());
    await expect((await openListMenu(canvas)).getByRole("menuitem", { name: "Import from CSV" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await chooseExport(canvas, "CSV");
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/records/stakeholder_need/export`));
  },
};
