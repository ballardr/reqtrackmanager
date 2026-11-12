import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, within } from "storybook/test";

import { api } from "../../api/client";
import { requiredCaptions } from "../../testing/requiredMarkers";
import { buildConnection, buildElement, CONNECTION_TYPES, PROJECT_ID } from "./architectureFixtures";
import { ConnectionFormModal } from "./ConnectionFormModal";

const ELEMENTS = [
  buildElement(),
  buildElement({ id: "el-2", unique_code: "ELM-002", name: "Orders", ports: [] }),
  buildElement({ id: "el-9", project_id: "project-2", shared: true, unique_code: "ELM-009", name: "Identity", ports: [] }),
  buildElement({ id: "el-8", unique_code: "ELM-008", name: "Old bus", status: "retired", ports: [] }),
];

const meta: Meta<typeof ConnectionFormModal> = {
  title: "Modules/Architecture/ConnectionFormModal",
  component: ConnectionFormModal,
  args: { connectionTypes: CONNECTION_TYPES, elements: ELEMENTS, projectId: PROJECT_ID, onCancel: fn(), onSave: fn() },
  beforeEach: () => { spyOn(api, "get").mockResolvedValue({ members: [], external: null } as never); },
};
export default meta;

type Story = StoryObj<typeof ConnectionFormModal>;

const dialog = () => within(within(document.body).getByRole("dialog"));

export const CreateNeedsTypeAndTwoDifferentElements: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await expect(requiredCaptions(within(document.body).getByRole("dialog"))).toEqual(["Connection type", "Source element", "Target element"]);
    await expect(d.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.selectOptions(d.getByLabelText("Source element"), "el-1");
    await userEvent.selectOptions(d.getByLabelText("Target element"), "el-1");
    await expect(d.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.selectOptions(d.getByLabelText("Target element"), "el-2");
    await userEvent.selectOptions(d.getByLabelText("Source port"), "port-1");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ connection_type_id: "ct-1", source_element_id: "el-1", source_port_id: "port-1", target_element_id: "el-2" }),
      { activate: false, quickLinks: [], tags: [] },
    );
  },
};

/** Retired elements are not offered, shared ones are marked, and changing an end clears its port. */
export const PickerHidesRetiredMarksSharedAndClearsThePort: Story = {
  play: async () => {
    const d = dialog();
    const source = d.getByLabelText("Source element");
    await expect(within(source).queryByText(/Old bus/)).not.toBeInTheDocument();
    await expect(within(source).getByText(/Identity \(shared\)/)).toBeInTheDocument();
    await userEvent.selectOptions(source, "el-1");
    await userEvent.selectOptions(d.getByLabelText("Source port"), "port-1");
    await userEvent.selectOptions(source, "el-2");
    await expect(d.getByLabelText("Source port")).toHaveValue("");
  },
};

export const EditHasNoActivateButton: Story = {
  args: { initial: buildConnection() },
  play: async () => {
    const d = dialog();
    await expect(d.getByLabelText("Protocol")).toHaveValue("HTTPS/1.1");
    await expect(d.queryByRole("button", { name: "Save and activate" })).not.toBeInTheDocument();
  },
};

/** The type is chosen from the tree (a group is a usable type) and can be found by searching. */
export const TypeIsChosenFromTheTreeAndSearched: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await userEvent.selectOptions(d.getByLabelText("Source element"), "el-1");
    await userEvent.selectOptions(d.getByLabelText("Target element"), "el-2");
    await userEvent.click(d.getByRole("button", { name: "Connection type" }));
    const popover = within(document.body);
    await userEvent.type(popover.getByRole("searchbox", { name: "Search Connection type" }), "i2c");
    await userEvent.click(popover.getByRole("radio", { name: "I2C" }));
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({ connection_type_id: "ct-2" }), expect.anything());
  },
};
