import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { requiredCaptions } from "../../testing/requiredMarkers";
import { buildElement, buildStateMachine } from "./architectureFixtures";
import { StateMachineFormModal } from "./StateMachineFormModal";

const ELEMENTS = [
  buildElement(),
  buildElement({ id: "el-2", unique_code: "ELM-002", name: "Orders", ports: [] }),
  buildElement({ id: "el-8", unique_code: "ELM-008", name: "Old bus", status: "retired", ports: [] }),
];

const meta: Meta<typeof StateMachineFormModal> = {
  title: "Modules/Architecture/StateMachineFormModal",
  component: StateMachineFormModal,
  args: { initial: buildStateMachine(), elements: ELEMENTS, onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof StateMachineFormModal>;

const dialog = () => within(within(document.body).getByRole("dialog"));

/** The name and the element are required, a retired element is not offered, and the edit starts from the diagram's values. */
export const EditsTheNameDescriptionAndElement: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await expect(requiredCaptions(within(document.body).getByRole("dialog"))).toEqual(["Name", "Element"]);
    await expect(d.getByLabelText(/^Name/)).toHaveValue("Gateway modes");
    await expect(d.queryByRole("option", { name: /Old bus/ })).not.toBeInTheDocument();
    await userEvent.selectOptions(d.getByLabelText(/^Element/), "el-2");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith({
      name: "Gateway modes", description: "The operating modes of the gateway.", element_id: "el-2",
    });
  },
};

/** A diagram that already describes a now-retired element keeps it in the list, so the form still shows it. */
export const ARetiredCurrentElementStaysInTheList: Story = {
  args: { initial: buildStateMachine({ element_id: "el-8", element_code: "ELM-008", element_name: "Old bus" }) },
  play: async () => {
    await expect(dialog().getByRole("option", { name: /Old bus/ })).toBeInTheDocument();
  },
};
