import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, within } from "storybook/test";

import { collectOrgResourceSections, CORE_ORG_RESOURCE_GROUP_KEYS, orgResourcesPath } from "./orgResources";
import { installedModules } from "./registry";
import type { OrgAdminSectionDef, TierAModuleDefinition } from "./types";

/** Prints the result as text so the stories assert on what the page would read. */
function Result({ value }: { value: unknown }) {
  return <pre aria-label="result">{JSON.stringify(value)}</pre>;
}

const meta: Meta<typeof Result> = { title: "Modules/orgResources", component: Result };
export default meta;
type Story = StoryObj<typeof Result>;

const read = (canvasElement: HTMLElement) => JSON.parse(within(canvasElement).getByLabelText("result").textContent ?? "null");

const section = (key: string, extra: Partial<OrgAdminSectionDef> = {}): OrgAdminSectionDef => ({
  key, label: key, render: () => null, ...extra,
});
const module = (key: string, sections: OrgAdminSectionDef[]): TierAModuleDefinition => ({ key, orgResourceSections: sections });
const keys = (sections: OrgAdminSectionDef[]) => sections.map((s) => s.key);

/** Only enabled modules contribute, in module order. */
export const OnlyEnabledModulesContribute: Story = {
  args: {
    value: keys(collectOrgResourceSections(
      [module("a", [section("a1")]), module("b", [section("b1")]), module("c", [section("c1")])], new Set(["a", "c"]), {},
    )),
  },
  play: async ({ canvasElement }) => {
    await expect(read(canvasElement)).toEqual(["a1", "c1"]);
  },
};

/** A section tied to a sub-component is left out only while that sub-component is listed as off. */
export const SubComponentStateFiltersASection: Story = {
  args: {
    value: [
      keys(collectOrgResourceSections([module("m", [section("s", { subComponent: "x" })])], new Set(["m"]), { m: ["x"] })),
      keys(collectOrgResourceSections([module("m", [section("s", { subComponent: "x" })])], new Set(["m"]), { m: [] })),
      keys(collectOrgResourceSections([module("m", [section("s", { subComponent: "x" })])], new Set(["m"]), {})),
    ],
  },
  play: async ({ canvasElement }) => {
    await expect(read(canvasElement)).toEqual([[], ["s"], ["s"]]);
  },
};

/** A repeated key, a key equal to another's group, a group equal to another's key and a reserved key are each dropped. */
export const CollidingSectionsAreDropped: Story = {
  beforeEach: () => {
    spyOn(console, "error").mockImplementation(() => undefined);
  },
  args: {
    value: keys(collectOrgResourceSections(
      [
        module("a", [section("one"), section("grp-a", { group: { key: "grp", label: "Group" } })]),
        module("b", [
          section("one"), // repeated section key
          section("grp"), // equals a group key
          section("two", { group: { key: "one", label: "Clash" } }), // group key equals a section key
          section("grp-b", { group: { key: "grp", label: "Group" } }), // shares a group: allowed
          section("kept"),
          section("any", { group: { key: "reserved", label: "Reserved" } }),
        ]),
      ],
      new Set(["a", "b"]), {}, ["reserved"],
    )),
  },
  play: async ({ canvasElement }) => {
    await expect(read(canvasElement)).toEqual(["one", "grp-a", "grp-b", "kept"]);
  },
};

/** Addresses: the page and a section by key. */
export const AddressesAreStable: Story = {
  args: { value: [orgResourcesPath("o1"), orgResourcesPath("o1", "x")] },
  play: async ({ canvasElement }) => {
    const [page, bySection] = read(canvasElement);
    await expect(page).toBe("/orgs/o1/resources");
    await expect(bySection).toBe("/orgs/o1/resources/x");
  },
};

/** The sections every real module declares contribute without collision: none is dropped by the page. */
export const InstalledModuleSectionsDoNotCollide: Story = {
  beforeEach: () => {
    spyOn(console, "error").mockImplementation(() => undefined);
  },
  args: {
    value: (() => {
      const declared = installedModules.flatMap((m) => m.orgResourceSections ?? []).length;
      const enabled = new Set(installedModules.map((m) => m.key));
      return { declared, offered: collectOrgResourceSections(installedModules, enabled, {}).length };
    })(),
  },
  play: async ({ canvasElement }) => {
    const { declared, offered } = read(canvasElement);
    await expect(declared).toBeGreaterThan(0);
    await expect(offered).toBe(declared);
  },
};

/** Settings and Resources never share a key or a group key, so a moved address cannot swallow a Settings one, and no
 * module section uses a key core reserves for Reports or Tags. */
export const SettingsAndResourcesKeysAreDisjoint: Story = {
  args: {
    value: (() => {
      const settings = new Set(installedModules.flatMap((m) => m.orgAdminSections ?? []).flatMap((s) => [s.key, s.group?.key ?? s.key]));
      const resources = installedModules.flatMap((m) => m.orgResourceSections ?? []).flatMap((s) => [s.key, s.group?.key ?? s.key]);
      return { shared: resources.filter((k) => settings.has(k)), reserved: resources.filter((k) => CORE_ORG_RESOURCE_GROUP_KEYS.includes(k)) };
    })(),
  },
  play: async ({ canvasElement }) => {
    await expect(read(canvasElement)).toEqual({ shared: [], reserved: [] });
  },
};

/** The Compliance status views have one home: tabs of the Standards page, so the module contributes no Org Resources
 * section, and each tab has a route of its own. */
export const ComplianceStatusViewsAreStandardsTabsOnly: Story = {
  args: {
    value: (() => {
      const compliance = installedModules.find((m) => m.key === "compliance");
      return {
        resourceSections: (compliance?.orgResourceSections ?? []).map((s) => s.key),
        routes: (compliance?.globalRoutes ?? []).map((r) => r.path).filter((path) => path.startsWith("/standards/")).sort(),
      };
    })(),
  },
  play: async ({ canvasElement }) => {
    const r = read(canvasElement);
    await expect(r.resourceSections).toEqual([]);
    await expect(r.routes).toEqual(expect.arrayContaining(["/standards/by-standard", "/standards/outstanding"]));
  },
};
