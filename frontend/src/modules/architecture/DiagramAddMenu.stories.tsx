import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { DOMAINS, ELEMENT_TYPES } from "./architectureFixtures";
import { addMenuItems } from "./diagramAddItems";
import { DiagramAddMenu } from "./DiagramAddMenu";
import type { ArchitectureDomain, ElementType } from "./types";

const meta: Meta<typeof DiagramAddMenu> = {
  title: "Modules/Architecture/DiagramAddMenu",
  component: DiagramAddMenu,
  args: {
    elementTypes: ELEMENT_TYPES, domains: DOMAINS, disabled: false, onAddType: fn(), onAddExisting: fn(), onAddNote: fn(),
    outerConnections: [], onAddOuter: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof DiagramAddMenu>;

const handlers = {
  onAddType: () => undefined, onAddExisting: () => undefined, onAddNote: () => undefined, outerConnections: [], onAddOuter: () => undefined,
};

/** A type in several domains is listed under each of them, a type in none under "New element" after the domains. */
export const ATypeIsListedUnderEachOfItsDomainsAndATypeInNoneUnderNewElement: Story = {
  play: async () => {
    const mechanical: ArchitectureDomain = { id: "dm-3", project_id: null, organization_id: "org", name: "Mechanical", sort_order: 2 };
    const hybrid: ElementType = { ...ELEMENT_TYPES[0], id: "et-9", name: "Actuator", domain_ids: ["dm-2", "dm-3"] };
    const items = addMenuItems([...ELEMENT_TYPES, hybrid], [...DOMAINS, mechanical], handlers);
    const types = items.filter((item) => item.key?.startsWith("type:"));
    await expect(types.map((item) => `${item.group}: ${item.label}`)).toEqual([
      "New software element: Service",
      "New hardware element: Board",
      "New hardware element: Actuator",
      "New mechanical element: Actuator",
      "New element: Custom block",
    ]);
    await expect(new Set(types.map((item) => item.key)).size).toBe(types.length); // every entry has its own key
  },
};

/** The domains' order decides the groups' order, not the types'. */
export const TheDomainsOrderDecidesTheGroupOrder: Story = {
  play: async () => {
    const reversed = [...DOMAINS].reverse();
    const items = addMenuItems(ELEMENT_TYPES, reversed, handlers).filter((item) => item.key?.startsWith("type:"));
    await expect(items.map((item) => item.label)).toEqual(["Board", "Service", "Custom block"]);
  },
};

export const TheMenuShowsTheGroupsOfTheProjectsDomains: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Add to diagram" }));
    const menu = within(await within(document.body).findByRole("menu", { name: "Add to diagram" }));
    for (const heading of ["New software element", "New hardware element", "New element"]) {
      await expect(menu.getByText(heading)).toBeInTheDocument();
    }
  },
};
