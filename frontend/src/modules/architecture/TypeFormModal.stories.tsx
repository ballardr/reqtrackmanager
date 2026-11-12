import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { requiredCaptions } from "../../testing/requiredMarkers";
import { CONNECTION_TYPES, ELEMENT_TYPES, mockArchitectureReads, SYMBOLS } from "./architectureFixtures";
import { TypeFormModal } from "./TypeFormModal";

const meta: Meta<typeof TypeFormModal> = {
  title: "Modules/Architecture/TypeFormModal",
  component: TypeFormModal,
  args: { kind: "element", symbols: SYMBOLS, symbolUrl: (id) => `/symbols/${id}`, onCancel: fn(), onSave: fn() },
  beforeEach: () => { mockArchitectureReads(); },
};
export default meta;

type Story = StoryObj<typeof TypeFormModal>;

const dialog = () => within(within(document.body).getByRole("dialog"));

export const ElementTypeNeedsANameAndSavesShapeAndSymbol: Story = {
  play: async ({ args }) => {
    const d = dialog();
    await expect(requiredCaptions(within(document.body).getByRole("dialog"))).toEqual(["Name"]);
    await expect(d.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.type(d.getByLabelText("Name"), "Sensor");
    await userEvent.selectOptions(d.getByLabelText("Shape"), "hexagon");
    await userEvent.selectOptions(d.getByLabelText("Symbol"), "sym-1");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith({
      name: "Sensor", domain: "any", shape: "hexagon", color_light: null, color_dark: null, symbol_id: "sym-1",
    });
  },
};

export const ConnectionTypeSavesLineStyleAndDirection: Story = {
  args: { kind: "connection", initial: CONNECTION_TYPES[1] },
  play: async ({ args }) => {
    const d = dialog();
    await expect(d.queryByLabelText("Shape")).not.toBeInTheDocument();
    await expect(d.getByLabelText("Line style")).toHaveValue("dashed");
    await userEvent.selectOptions(d.getByLabelText("Line style"), "dotted");
    await userEvent.click(d.getByRole("button", { name: "Save" }));
    await expect(args.onSave).toHaveBeenCalledWith(expect.objectContaining({
      name: "I2C", domain: "hardware", line_style: "dotted", directional: false, color_light: "#065f46", color_dark: "#6ee7b7",
    }));
  },
};

export const EditKeepsTheStoredColours: Story = {
  args: { initial: ELEMENT_TYPES[0] },
  play: async () => {
    await expect(dialog().getByLabelText("Colour (light theme) (hex code)")).toHaveValue("#dbeafe");
  },
};
