import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, within } from "storybook/test";

import { api } from "../../api/client";
import { requiredCaptions } from "../../testing/requiredMarkers";
import { buildElement, CONNECTION_TYPES, ELEMENT_TYPES, ORG_ID, ORG_USERS, PROJECT_ID, SYMBOLS } from "./architectureFixtures";
import { ElementFormModal } from "./ElementFormModal";

const meta: Meta<typeof ElementFormModal> = {
  title: "Modules/Architecture/ElementFormModal",
  component: ElementFormModal,
  args: {
    elementTypes: ELEMENT_TYPES, connectionTypes: CONNECTION_TYPES, candidates: [buildElement(), buildElement({ id: "el-2", unique_code: "ELM-002", name: "Orders", parent_id: "el-1" })],
    symbols: SYMBOLS, symbolUrl: (id) => `/symbols/${id}`, orgUsers: ORG_USERS, organizationId: ORG_ID, projectId: PROJECT_ID,
    onCancel: fn(), onSave: fn(),
  },
  beforeEach: () => {
    spyOn(api, "get").mockImplementation(async (path: string) => {
      if (path.includes("/symbols/")) return new Blob(["<svg xmlns='http://www.w3.org/2000/svg'/>"], { type: "image/svg+xml" }) as never;
      return { members: [], external: null } as never;
    });
  },
};
export default meta;

type Story = StoryObj<typeof ElementFormModal>;

const dialog = () => within(within(document.body).getByRole("dialog"));

export const CreateRequiresANameAndMarksTheRequiredFields: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await expect(requiredCaptions(within(document.body).getByRole("dialog"))).toEqual(["Name", "Element type"]);
    await expect(d.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(d.getByLabelText("Name"), "Scheduler");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Scheduler", element_type_id: "et-1", parent_id: null, owner: null }),
      { ports: [], activate: false, quickLinks: [], tags: [] },
    );
  },
};

/** Save and activate creates the element active; ports added in the form travel with it. */
export const SaveAndActivateSendsThePortsAndTheFlag: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await userEvent.type(d.getByLabelText("Name"), "Scheduler");
    await userEvent.type(d.getByLabelText("Port name"), "Jobs");
    await userEvent.click(d.getByRole("button", { name: "Add port" }));
    await userEvent.selectOptions(await d.findByLabelText("Direction of Jobs"), "in");
    await userEvent.click(d.getByRole("button", { name: "Save and activate" }));
    await expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Scheduler" }),
      expect.objectContaining({ activate: true, ports: [{ name: "Jobs", direction: "in", connection_type_id: null }] }),
    );
  },
};

/** The parent choices leave out the element itself and everything below it, so a cycle cannot be chosen. */
export const EditOffersNoCycleAndNoPortsOrActivate: Story = {
  args: { initial: buildElement() },
  play: async () => {
    const d = dialog();
    await expect(d.getByLabelText("Name")).toHaveValue("Gateway");
    const parent = d.getByLabelText("Parent element");
    await expect(within(parent).queryByText(/Gateway/)).not.toBeInTheDocument();
    await expect(within(parent).queryByText(/Orders/)).not.toBeInTheDocument();
    await expect(d.queryByRole("button", { name: "Save and activate" })).not.toBeInTheDocument();
    await expect(d.queryByLabelText("Port name")).not.toBeInTheDocument();
  },
};

/** An organisation element has no project, so no links or tags are offered. */
export const OrganisationElementHasNoLinksOrTags: Story = {
  args: { projectId: undefined },
  play: async () => {
    const d = dialog();
    await expect(d.queryByText("Link to")).not.toBeInTheDocument();
    await expect(d.getByLabelText("Name")).toBeInTheDocument();
  },
};
