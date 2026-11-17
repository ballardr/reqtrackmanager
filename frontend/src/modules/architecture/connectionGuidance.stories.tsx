import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import { defaultConnectionType, domainsFit, guideConnectionTypes, mismatchWarning, suggestedGroup, SUGGESTED_GROUP_ID } from "./connectionGuidance";
import type { ArchitectureDomain, ConnectionType, ElementType } from "./types";

/** The domains of the examples: a custom one beside the two a new organisation has. */
const DOMAINS: ArchitectureDomain[] = [
  { id: "sw", name: "Software", project_id: null, organization_id: "org", sort_order: 0 },
  { id: "hw", name: "Hardware", project_id: null, organization_id: "org", sort_order: 1 },
  { id: "mech", name: "Mechanical", project_id: null, organization_id: "org", sort_order: 2 },
];

const connection = (id: string, name: string, domain_ids: string[]): ConnectionType => ({
  id, name, domain_ids, sort_order: 0, parent_ids: [], project_id: null, organization_id: "org", line_style: "solid",
  directional: true, default_protocol: "", color_light: null, color_dark: null,
});
const element = (id: string, name: string, domain_ids: string[], suggested: string[] = []): ElementType => ({
  id, name, domain_ids, sort_order: 0, project_id: null, organization_id: "org", shape: "rectangle", symbol_id: null,
  color_light: null, color_dark: null, suggested_connection_type_ids: suggested,
});

const TYPES = [connection("rest", "REST API", ["sw"]), connection("i2c", "I2C", ["hw"]), connection("eth", "Ethernet", [])];
const BOARD = element("board", "Board", ["hw"], ["i2c"]);
const SERVICE = element("service", "Service", ["sw"], ["rest"]);
const SYSTEM = element("system", "System", []);

function Host() {
  return <p>Checks the connection type guidance rules.</p>;
}

const meta: Meta<typeof Host> = { title: "Modules/Architecture/ConnectionGuidance", component: Host };
export default meta;

type Story = StoryObj<typeof Host>;

export const NoDomainFitsEverythingAndASharedDomainFits: Story = {
  play: async () => {
    await expect(domainsFit([], ["hw"])).toBe(true);
    await expect(domainsFit(["sw"], [])).toBe(true);
    await expect(domainsFit([], [])).toBe(true);
    await expect(domainsFit(["hw"], ["hw"])).toBe(true);
    await expect(domainsFit(["hw"], ["sw"])).toBe(false);
  },
};

/** A type or element in several domains fits whatever shares any one of them. */
export const SeveralDomainsFitWhateverSharesOneOfThem: Story = {
  play: async () => {
    await expect(domainsFit(["sw", "hw"], ["hw"])).toBe(true);
    await expect(domainsFit(["sw", "hw"], ["mech"])).toBe(false);
    await expect(domainsFit(["sw", "hw"], ["mech", "sw"])).toBe(true);
    const gateway = connection("gw", "Gateway link", ["sw", "hw"]);
    await expect(guideConnectionTypes([gateway, ...TYPES], [BOARD, BOARD]).offered.map((t) => t.name)).toEqual(["Gateway link", "I2C", "Ethernet"]);
    await expect(guideConnectionTypes([gateway, ...TYPES], [element("m", "Frame", ["mech"]), BOARD]).offered.map((t) => t.name)).toEqual(["Ethernet"]);
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
    await expect(mismatchWarning(TYPES[0], [BOARD, BOARD], DOMAINS)).toBe(
      "REST API is in Software, but the source element (Board) is in Hardware and the target element (Board) is in Hardware. The connection can still be saved.",
    );
    // The service suggests REST API, which excuses the pair; a type neither end suggests is warned about per end.
    await expect(mismatchWarning(TYPES[0], [SERVICE, BOARD], DOMAINS)).toBeNull();
    await expect(mismatchWarning(TYPES[0], [SYSTEM, BOARD], DOMAINS)).toBe(
      "REST API is in Software, but the target element (Board) is in Hardware. The connection can still be saved.",
    );
    await expect(mismatchWarning(TYPES[1], [BOARD, BOARD], DOMAINS)).toBeNull();
    await expect(mismatchWarning(TYPES[2], [BOARD, SERVICE], DOMAINS)).toBeNull();
    await expect(mismatchWarning(undefined, [BOARD, BOARD], DOMAINS)).toBeNull();
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

/** A connection created by drawing a line starts with the type the ends suggest, then the first top-level type that fits. */
export const ADrawnConnectionStartsWithTheSuggestedTypeElseTheFirstFittingTopLevelType: Story = {
  play: async () => {
    await expect(defaultConnectionType(TYPES, [BOARD, BOARD])?.name).toBe("I2C");
    await expect(defaultConnectionType(TYPES, [SERVICE, BOARD])?.name).toBe("REST API"); // the source's suggestion comes first
    await expect(defaultConnectionType(TYPES, [SYSTEM, SYSTEM])?.name).toBe("REST API"); // nothing suggested: first fitting top-level
    const nested: ConnectionType[] = [{ ...connection("child", "Child", []), parent_ids: ["rest"] }, ...TYPES];
    await expect(defaultConnectionType(nested, [SYSTEM, SYSTEM])?.name).toBe("REST API"); // a nested type is not the default
  },
};

export const WithNoConnectionTypeThereIsNoDefault: Story = {
  play: async () => {
    await expect(defaultConnectionType([], [SERVICE, BOARD])).toBeUndefined();
  },
};
