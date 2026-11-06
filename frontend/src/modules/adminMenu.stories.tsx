import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { buildAdminMenuEntries, resolveAdminSection, type AdminSectionLike } from "./adminMenu";
import { installedModules } from "./registry";

const BASE = "/projects/p1/admin";
const RISK = { key: "risk-management", label: "Risk Management" };
const SECTIONS: AdminSectionLike[] = [
  { key: "decision-types", label: "Decision Types" },
  { key: "risk-types", label: "Risk Types", group: RISK },
  { key: "risk-scoring", label: "Risk Scoring", group: RISK },
  { key: "solo-settings", label: "Solo Settings", group: { key: "solo", label: "Solo" } },
];

/** Prints the result as text so the stories assert on what the page would read. */
function Result({ value }: { value: unknown }) {
  return <pre aria-label="result">{JSON.stringify(value)}</pre>;
}

const meta: Meta<typeof Result> = { title: "Modules/adminMenu", component: Result };
export default meta;
type Story = StoryObj<typeof Result>;

const read = (canvasElement: HTMLElement) => JSON.parse(within(canvasElement).getByLabelText("result").textContent ?? "null");

/** Sections sharing a group are one entry with sub-pages, placed where the group's first section was declared. */
export const GroupedSectionsBecomeOneExpandableEntry: Story = {
  args: { value: buildAdminMenuEntries(SECTIONS, BASE) },
  play: async ({ canvasElement }) => {
    const entries = read(canvasElement);
    await expect(entries.map((e: { key: string }) => e.key)).toEqual(["decision-types", "risk-management", "solo-settings"]);
    await expect(entries[1].children.map((c: { href: string }) => c.href)).toEqual([
      `${BASE}/risk-management/risk-types`,
      `${BASE}/risk-management/risk-scoring`,
    ]);
    await expect(entries[1].href).toBe(`${BASE}/risk-management/risk-types`);
  },
};

/** A group left with one visible section (the other is switched off) is a plain entry, so a lone sub-page has no parent. */
export const AGroupWithOneVisibleSectionIsSingleLevel: Story = {
  args: { value: buildAdminMenuEntries(SECTIONS, BASE).filter((e) => e.key === "solo-settings") },
  play: async ({ canvasElement }) => {
    const [entry] = read(canvasElement);
    await expect(entry).toEqual({ key: "solo-settings", label: "Solo Settings", href: `${BASE}/solo/solo-settings` });
  },
};

export const ResolvesGroupAndSection: Story = {
  args: { value: resolveAdminSection(SECTIONS, BASE, "risk-management", "risk-scoring") },
  play: async ({ canvasElement }) => {
    const route = read(canvasElement);
    await expect(route.section.key).toBe("risk-scoring");
    await expect(route.redirectTo).toBeNull();
  },
};

/** A bookmark from before groups existed (`/admin/<section>`) is sent to the grouped address. */
export const EarlierFlatAddressRedirects: Story = {
  args: { value: resolveAdminSection(SECTIONS, BASE, "risk-scoring", undefined) },
  play: async ({ canvasElement }) => {
    const route = read(canvasElement);
    await expect(route.section).toBeNull();
    await expect(route.redirectTo).toBe(`${BASE}/risk-management/risk-scoring`);
  },
};

export const GroupAddressRedirectsToFirstSection: Story = {
  args: { value: resolveAdminSection(SECTIONS, BASE, "risk-management", undefined) },
  play: async ({ canvasElement }) => {
    await expect(read(canvasElement).redirectTo).toBe(`${BASE}/risk-management/risk-types`);
  },
};

export const UnknownSectionUnderAGroupRedirectsToFirstSection: Story = {
  args: { value: resolveAdminSection(SECTIONS, BASE, "risk-management", "nope") },
  play: async ({ canvasElement }) => {
    await expect(read(canvasElement).redirectTo).toBe(`${BASE}/risk-management/risk-types`);
  },
};

/** An ungrouped section keeps its one-level address; a core group key or an unknown segment names no module section. */
export const UngroupedSectionAndCoreKeysResolve: Story = {
  args: {
    value: [
      resolveAdminSection(SECTIONS, BASE, "decision-types", undefined),
      resolveAdminSection(SECTIONS, BASE, "members", undefined),
      resolveAdminSection(SECTIONS, BASE, undefined, undefined),
    ],
  },
  play: async ({ canvasElement }) => {
    const [ungrouped, core, none] = read(canvasElement);
    await expect(ungrouped.section.key).toBe("decision-types");
    await expect(ungrouped.redirectTo).toBeNull();
    await expect(core).toEqual({ section: null, redirectTo: null });
    await expect(none).toEqual({ section: null, redirectTo: null });
  },
};

/**
 * Every installed module's declared groups: a group key never equals a section key (a URL segment would be ambiguous),
 * and one group key always carries one label.
 */
export const InstalledModuleGroupsAreUnambiguous: Story = {
  args: {
    value: (() => {
      const problems: string[] = [];
      for (const tier of ["orgAdminSections", "projectAdminSections"] as const) {
        const sections: AdminSectionLike[] = installedModules.flatMap((m): AdminSectionLike[] => m[tier] ?? []);
        const sectionKeys = new Set(sections.map((s) => s.key));
        const labels = new Map<string, string>();
        for (const s of sections) {
          if (!s.group) continue;
          if (sectionKeys.has(s.group.key)) problems.push(`${tier}: group ${s.group.key} equals a section key`);
          const seen = labels.get(s.group.key);
          if (seen !== undefined && seen !== s.group.label) problems.push(`${tier}: group ${s.group.key} has two labels`);
          labels.set(s.group.key, s.group.label);
        }
      }
      return problems;
    })(),
  },
  play: async ({ canvasElement }) => {
    await expect(read(canvasElement)).toEqual([]);
  },
};
