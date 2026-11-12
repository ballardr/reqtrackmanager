import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
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
    await userEvent.selectOptions(dialog.getByLabelText("Domain"), "hardware");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/architecture/element-types/et-3`,
      expect.objectContaining({ name: "Custom block", shape: "cylinder", domain: "hardware", symbol_id: null }),
    ));
  },
};

/** A connection type adds a line style and whether it is one-way, and the groups it sits under. */
export const ConnectionTypesShowLineStyleAndDirection: Story = {
  args: { scope: { kind: "org", organizationId: ORG_ID }, kind: "connection" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Software · Solid, one-way")).toBeInTheDocument();
    await expect(canvas.getByText("Hardware · Dashed, two-way · Under Serial bus")).toBeInTheDocument();
  },
};

/** A new connection type is created at the top level, and a group's edit dialog lists the tree to sit under. */
export const ANewConnectionTypeStartsAtTheTopLevel: Story = {
  args: { scope: { kind: "org", organizationId: ORG_ID }, kind: "connection" },
  beforeEach: () => {
    const post = spyOn(api, "post").mockResolvedValue({} as never);
    return () => post.mockRestore();
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await canvas.findByPlaceholderText("Connection type name"), "Radio link");
    await userEvent.click(canvas.getByRole("button", { name: "Add connection type" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/architecture/connection-types`, expect.objectContaining({ name: "Radio link", parent_ids: [] }),
    ));
  },
};
