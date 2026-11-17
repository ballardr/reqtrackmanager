import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { blankConnectionValues, defaultElementName, protocolAfterTypeChange } from "./architectureFields";
import type { ConnectionType } from "./types";

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

const type = (default_protocol: string): ConnectionType => ({
  id: "t", name: "T", domain_ids: [], sort_order: 0, parent_ids: [], project_id: null, organization_id: "org", line_style: "solid",
  directional: true, default_protocol, color_light: null, color_dark: null,
});

/** The rule for a type change: the new default replaces only an empty protocol or the previous type's own default. */
export const ATypeChangeReplacesOnlyAnEmptyOrDefaultProtocol: Story = {
  play: async () => {
    await expect(protocolAfterTypeChange("", type("SPI"), type("UART"))).toBe("UART");
    await expect(protocolAfterTypeChange("   ", undefined, type("UART"))).toBe("UART");
    await expect(protocolAfterTypeChange("SPI", type("SPI"), type("UART"))).toBe("UART");
    await expect(protocolAfterTypeChange("SPI", type("SPI"), type(""))).toBe("");
    await expect(protocolAfterTypeChange("MAVLink 2", type("SPI"), type("UART"))).toBe("MAVLink 2");
    await expect(protocolAfterTypeChange("MAVLink 2", type("SPI"), undefined)).toBe("MAVLink 2");
  },
};

export const ABlankConnectionStartsWithTheGivenProtocol: Story = {
  play: async () => {
    await expect(blankConnectionValues("t", "a", "b", null, "SPI mode 0").protocol).toBe("SPI mode 0");
    await expect(blankConnectionValues("t", "a", "b").protocol).toBe("");
  },
};
