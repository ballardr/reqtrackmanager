import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { expectTextRows } from "../../testing/menuRows";
import { openAddDialog, withToast } from "../../testing/storybook-helpers";
import { ArchitectureTypesPanel } from "./ArchitectureTypesPanel";
import { mockArchitectureReads, ORG_ID, PROJECT_ID } from "./architectureFixtures";

const meta: Meta<typeof ArchitectureTypesPanel> = {
  title: "Modules/Architecture/ArchitectureTypesPanel",
  component: ArchitectureTypesPanel,
  decorators: [withToast()],
  beforeEach: () => {
    const get = mockArchitectureReads();
    return () => get.mockRestore();
  },
};
export default meta;

type Story = StoryObj<typeof ArchitectureTypesPanel>;

/** In a project an organisation default is read-only and shows where it comes from; the project's own row can be edited. */
export const ProjectListsDefaultsReadOnlyAndOwnRowsEditable: Story = {
  args: { scope: { kind: "project", projectId: PROJECT_ID }, kind: "element" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const service = await canvas.findAllByLabelText("Element type name");
    await waitFor(() => expect(service.length).toBeGreaterThan(0));
    const names = canvas.getAllByLabelText("Element type name", { selector: "input:not([placeholder])" }) as HTMLInputElement[];
    await expect(names.map((n) => [n.value, n.disabled])).toEqual([["Service", true], ["Board", true], ["Custom block", false]]);
    await expect(canvas.getAllByText("Org default")).toHaveLength(2);
    await expect(canvas.getByText("Software · Rounded rectangle")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Edit Service" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Edit Custom block" })).toBeInTheDocument();
  },
};

/** Deleting an organisation default only hides it, after a confirmation that says so. */
export const DeletingAnOrganisationDefaultHidesItAfterConfirming: Story = {
  args: { scope: { kind: "project", projectId: PROJECT_ID }, kind: "element" },
  beforeEach: () => {
    const del = spyOn(api, "delete").mockResolvedValue(undefined as never);
    return () => del.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const [hide] = await canvas.findAllByRole("button", { name: "Hide element type in this project" });
    await userEvent.click(hide);
    const dialog = within(within(document.body).getByRole("dialog"));
    await expect(dialog.getByText(/organisation default/)).toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Hide" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/modules/architecture/element-types/et-1`));
  },
};

/** The edit dialog changes shape, domain and colours of a row the project owns. */
export const EditDialogSavesTheOtherAttributes: Story = {
  args: { scope: { kind: "project", projectId: PROJECT_ID }, kind: "element" },
  beforeEach: () => {
    const patch = spyOn(api, "patch").mockResolvedValue({} as never);
    return () => patch.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Edit Custom block" }));
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.selectOptions(dialog.getByLabelText("Shape"), "cylinder");
    await userEvent.click(dialog.getByRole("button", { name: "Domains" }));
    await userEvent.click(within(document.body).getByRole("checkbox", { name: "Hardware" }));
    await userEvent.keyboard("{Escape}");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/architecture/element-types/et-3`,
      expect.objectContaining({ name: "Custom block", shape: "cylinder", domain_ids: ["dm-2"], symbol_id: null }),
    ));
  },
};

/** A connection type adds a line style, whether it is one-way, its default protocol when it has one, and the groups it sits under. */
export const ConnectionTypesShowLineStyleAndDirection: Story = {
  args: { scope: { kind: "org", organizationId: ORG_ID }, kind: "connection" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Software · Solid, one-way")).toBeInTheDocument();
    await expect(canvas.getByText("Hardware · Dashed, two-way, default protocol I2C 400 kHz · Under Serial bus")).toBeInTheDocument();
  },
};

/** The one Add button sits above the list and opens the form with every field; there is no second create below the list. */
export const OneAddButtonOpensTheFullForm: Story = {
  args: { scope: { kind: "org", organizationId: ORG_ID }, kind: "connection" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const add = await canvas.findByRole("button", { name: "Add connection type" });
    await expect(canvas.getAllByRole("button", { name: /^Add connection type$/ })).toHaveLength(1);
    await expect(canvas.queryByRole("button", { name: /with details/ })).not.toBeInTheDocument();
    // Above the list: the button precedes the first row of the grid.
    const grid = canvasElement.querySelector(".definition-grid") as HTMLElement;
    await expect(add.compareDocumentPosition(grid) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await userEvent.click(add);
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Add connection type" }));
    for (const field of ["Name", "Domains", "Line style", "Colour (light theme)", "Colour (dark theme)", "Sits under", "Default protocol", "One-way"]) {
      await expect(dialog.getAllByText(field, { exact: false }).length).toBeGreaterThan(0);
    }
    await expect(dialog.getByRole("textbox", { name: "Name" })).toHaveFocus();
    await expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
  },
};

/** An element type's Add button opens the same form as Edit, with the shape, symbol and suggested connection types. */
export const ElementTypeAddOpensTheFullForm: Story = {
  args: { scope: { kind: "org", organizationId: ORG_ID }, kind: "element" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const dialog = await openAddDialog(canvas, "Add element type");
    for (const field of ["Name", "Domains", "Shape", "Symbol", "Suggested connection types"]) {
      await expect(dialog.getAllByText(field, { exact: false }).length).toBeGreaterThan(0);
    }
  },
};

/** A new connection type is created in one step with every value of the form, at the top level by default. */
export const ANewConnectionTypeStartsAtTheTopLevel: Story = {
  args: { scope: { kind: "org", organizationId: ORG_ID }, kind: "connection" },
  beforeEach: () => {
    const post = spyOn(api, "post").mockResolvedValue({} as never);
    return () => post.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const dialog = await openAddDialog(canvas, "Add connection type");
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Radio link");
    await userEvent.selectOptions(dialog.getByLabelText("Line style"), "dashed");
    await userEvent.type(dialog.getByRole("textbox", { name: "Default protocol" }), "LoRa");
    await userEvent.click(dialog.getByRole("switch", { name: "One-way" }));
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/architecture/connection-types`,
      expect.objectContaining({ name: "Radio link", line_style: "dashed", directional: false, default_protocol: "LoRa", parent_ids: [] }),
    ));
  },
};

/** In a project that hid a default, the list's actions menu offers Add organisation defaults as a text row; the one primary button stays Add. */
export const ProjectActionsMenuRestoresHiddenDefaults: Story = {
  args: { scope: { kind: "project", projectId: PROJECT_ID }, kind: "connection" },
  beforeEach: () => {
    const get = mockArchitectureReads({ hiddenDefinitions: [{ id: "ct-hidden", name: "Radio" }] });
    const post = spyOn(api, "post").mockResolvedValue({} as never);
    return () => { get.mockRestore(); post.mockRestore(); };
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "List actions" }));
    const menu = await within(document.body).findByRole("menu");
    await expectTextRows(menu);
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Add organisation defaults (1)" }));
    const dialog = within(await within(document.body).findByRole("dialog", { name: "Add organisation defaults" }));
    await userEvent.click(dialog.getByRole("button", { name: "Add 1 default" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/architecture/connection-types/restore`, expect.anything(),
    ));
  },
};

/** With nothing hidden there is no actions menu, only the Add button. */
export const NoActionsMenuWhenNothingIsHidden: Story = {
  args: { scope: { kind: "project", projectId: PROJECT_ID }, kind: "connection" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("button", { name: "Add connection type" });
    await expect(canvas.queryByRole("button", { name: "List actions" })).not.toBeInTheDocument();
  },
};

/** The domains are a vocabulary of their own: a name each, an organisation default read-only in a project and hidden there. */
export const DomainsAreListedByNameAndAnOrganisationDefaultIsHiddenNotDeleted: Story = {
  args: { scope: { kind: "project", projectId: PROJECT_ID }, kind: "domain" },
  beforeEach: () => {
    const del = spyOn(api, "delete").mockResolvedValue(undefined as never);
    return () => del.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getAllByLabelText("Domain name", { selector: "input:not([placeholder])" }).length).toBe(2));
    const names = canvas.getAllByLabelText("Domain name", { selector: "input:not([placeholder])" }) as HTMLInputElement[];
    await expect(names.map((n) => [n.value, n.disabled])).toEqual([["Software", true], ["Hardware", true]]);
    // A domain is only a name: there is no details dialog.
    await expect(canvas.queryByRole("button", { name: /^Edit / })).not.toBeInTheDocument();
    const [hide] = await canvas.findAllByRole("button", { name: "Hide domain in this project" });
    await userEvent.click(hide);
    const dialog = within(within(document.body).getByRole("dialog"));
    await userEvent.click(dialog.getByRole("button", { name: "Hide" }));
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/modules/architecture/domains/dm-1`));
  },
};

/** A new domain is created with only its name. */
export const ANewDomainIsCreatedWithItsName: Story = {
  args: { scope: { kind: "org", organizationId: ORG_ID }, kind: "domain" },
  beforeEach: () => {
    const post = spyOn(api, "post").mockResolvedValue({} as never);
    return () => post.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const dialog = await openAddDialog(canvas, "Add domain");
    // The domain's dialog is the name alone.
    await expect(dialog.getAllByRole("textbox")).toHaveLength(1);
    await userEvent.type(dialog.getByRole("textbox", { name: "Name" }), "Mechanical");
    await userEvent.click(dialog.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/architecture/domains`, { name: "Mechanical" },
    ));
  },
};
