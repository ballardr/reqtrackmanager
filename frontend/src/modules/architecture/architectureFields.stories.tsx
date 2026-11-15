import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { defaultElementName } from "./architectureFields";

function Host() {
  return <p>Checks the architecture field helpers.</p>;
}

const meta: Meta<typeof Host> = { title: "Modules/Architecture/ArchitectureFields", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

export const ANewElementIsNamedForItsTypeWithTheFirstFreeNumber: Story = {
  play: async () => {
    await expect(defaultElementName("Sensor", [])).toBe("Sensor 1");
    await expect(defaultElementName("Sensor", ["Sensor 1", "Gateway"])).toBe("Sensor 2");
    await expect(defaultElementName("Sensor", ["Sensor 1", "Sensor 3"])).toBe("Sensor 2");
  },
};

export const TheNumberIsComparedWithoutCaseOrOuterSpaces: Story = {
  play: async () => {
    await expect(defaultElementName("Sensor", [" sensor 1 "])).toBe("Sensor 2");
  },
};
