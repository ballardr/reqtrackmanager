import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { domainFits, guideConnectionTypes, mismatchWarning, suggestedGroup, SUGGESTED_GROUP_ID } from "./connectionGuidance";
import type { ConnectionType, Domain, ElementType } from "./types";

const connection = (id: string, name: string, domain: Domain): ConnectionType => ({
  id, name, domain, sort_order: 0, parent_ids: [], project_id: null, organization_id: "org", line_style: "solid",
  directional: true, color_light: null, color_dark: null,
});
const element = (id: string, name: string, domain: Domain, suggested: string[] = []): ElementType => ({
  id, name, domain, sort_order: 0, project_id: null, organization_id: "org", shape: "rectangle", symbol_id: null,
  color_light: null, color_dark: null, suggested_connection_type_ids: suggested,
});

const TYPES = [connection("rest", "REST API", "software"), connection("i2c", "I2C", "hardware"), connection("eth", "Ethernet", "any")];
const BOARD = element("board", "Board", "hardware", ["i2c"]);
const SERVICE = element("service", "Service", "software", ["rest"]);
const SYSTEM = element("system", "System", "any");

function Host() {
  return <p>Checks the connection type guidance rules.</p>;
}

const meta: Meta<typeof Host> = { title: "Modules/Architecture/ConnectionGuidance", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

export const AnyFitsEverythingAndEqualDomainsFit: Story = {
  play: async () => {
    await expect(domainFits("any", "hardware")).toBe(true);
    await expect(domainFits("software", "any")).toBe(true);
    await expect(domainFits("hardware", "hardware")).toBe(true);
    await expect(domainFits("hardware", "software")).toBe(false);
  },
};

export const TwoBoardsHideTheSoftwareTypeAndSuggestTheirs: Story = {
  play: async () => {
    const guidance = guideConnectionTypes(TYPES, [BOARD, BOARD]);
    await expect(guidance.offered.map((t) => t.name)).toEqual(["I2C", "Ethernet"]);
    await expect(guidance.hidden.map((t) => t.name)).toEqual(["REST API"]);
    await expect(guidance.suggested.map((t) => t.name)).toEqual(["I2C"]); // listed once for two ends
  },
};

export const AServiceAndABoardOfferOnlyTheTypesThatFitBoth: Story = {
  play: async () => {
    const guidance = guideConnectionTypes(TYPES, [SERVICE, BOARD]);
    await expect(guidance.offered.map((t) => t.name)).toEqual(["Ethernet"]);
    // Each end's suggestion is still listed first, whatever its domain.
    await expect(guidance.suggested.map((t) => t.name)).toEqual(["REST API", "I2C"]);
  },
};

export const AnEndNotChosenOrUnknownImposesNothing: Story = {
  play: async () => {
    await expect(guideConnectionTypes(TYPES, [undefined, undefined]).hidden).toEqual([]);
    await expect(guideConnectionTypes(TYPES, [SYSTEM, BOARD]).offered.map((t) => t.name)).toEqual(["I2C", "Ethernet"]);
    await expect(guideConnectionTypes(TYPES, [BOARD, undefined]).offered.map((t) => t.name)).toEqual(["I2C", "Ethernet"]);
  },
};

export const ASuggestionNotInTheListIsDropped: Story = {
  play: async () => {
    await expect(guideConnectionTypes(TYPES.slice(1), [SERVICE, SERVICE]).suggested).toEqual([]);
  },
};

export const TheWarningNamesEachEndThatDoesNotFit: Story = {
  play: async () => {
    await expect(mismatchWarning(TYPES[0], [BOARD, BOARD])).toBe(
      "REST API is a software connection type, but the source element (Board) is hardware and the target element (Board) is hardware. The connection can still be saved.",
    );
    // The service suggests REST API, which excuses the pair; a type neither end suggests is warned about per end.
    await expect(mismatchWarning(TYPES[0], [SERVICE, BOARD])).toBeNull();
    await expect(mismatchWarning(TYPES[0], [SYSTEM, BOARD])).toBe(
      "REST API is a software connection type, but the target element (Board) is hardware. The connection can still be saved.",
    );
    await expect(mismatchWarning(TYPES[1], [BOARD, BOARD])).toBeNull();
    await expect(mismatchWarning(TYPES[2], [BOARD, SERVICE])).toBeNull();
    await expect(mismatchWarning(undefined, [BOARD, BOARD])).toBeNull();
  },
};

export const TheSuggestedGroupHoldsEachTypeOnceAndCannotBeChosen: Story = {
  play: async () => {
    await expect(suggestedGroup([])).toEqual([]);
    const [group] = suggestedGroup([TYPES[1], TYPES[0]]);
    await expect(group.id).toBe(SUGGESTED_GROUP_ID);
    await expect(group.disabled).toBe(true);
    await expect(group.children.map((c) => c.label)).toEqual(["I2C", "REST API"]);
  },
};
