import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect } from "storybook/test";

import {
  arrangeProjectNav,
  isNavPathActive,
  layoutProjectNav,
  navPrefFromArrangement,
  parseNavPref,
  resolveNavPref,
  type NavItemLike,
} from "./projectNav";

/**
 * Pure layout logic for the Project nav section — exercised as play functions (this repo has no
 * separate unit-test runner). The component renders nothing; the assertions are the point.
 */
function Noop() {
  return <div>projectNav logic — see the play functions</div>;
}

const meta: Meta<typeof Noop> = {
  title: "Navigation/projectNav",
  component: Noop,
};
export default meta;

type Story = StoryObj<typeof Noop>;

const ITEMS: NavItemLike[] = [
  { key: "overview", to: "/p", exact: true },
  { key: "requirements", to: "/p/requirements" },
  { key: "actions", to: "/p/actions" },
  { key: "reports", to: "/p/reports" },
  { key: "admin", to: "/p/admin" },
];

const keys = (items: NavItemLike[]) => items.map((item) => item.key);

export const NoPreferenceIsProductDefault: Story = {
  play: async () => {
    const { main, more } = arrangeProjectNav(ITEMS, null);
    await expect(keys(main)).toEqual(keys(ITEMS));
    await expect(more).toEqual([]);
  },
};

export const OrderAndMoreAreApplied: Story = {
  play: async () => {
    const pref = { order: ["overview", "reports", "requirements", "admin", "actions"], more: ["actions"] };
    const { main, more } = arrangeProjectNav(ITEMS, pref);
    await expect(keys(main)).toEqual(["overview", "reports", "requirements", "admin"]);
    await expect(keys(more)).toEqual(["actions"]);
  },
};

export const UnknownKeysAreIgnoredAndNewItemsLandAtDefaultPosition: Story = {
  play: async () => {
    // "gone" no longer exists (module disabled); "actions" and "reports" are newer than the preference.
    const pref = { order: ["admin", "gone", "requirements", "overview"], more: ["gone"] };
    const { main, more } = arrangeProjectNav(ITEMS, pref);
    // actions follows its default predecessor (requirements); reports follows actions.
    await expect(keys(main)).toEqual(["admin", "requirements", "actions", "reports", "overview"]);
    await expect(more).toEqual([]);
  },
};

export const NewItemWithNoEarlierNeighbourGoesFirst: Story = {
  play: async () => {
    const pref = { order: ["requirements", "actions"], more: [] };
    const { main } = arrangeProjectNav(ITEMS, pref);
    await expect(keys(main)).toEqual(["overview", "requirements", "actions", "reports", "admin"]);
  },
};

export const PinnedItemsCannotBeMovedToMore: Story = {
  play: async () => {
    const pref = { order: keys(ITEMS), more: ["overview", "admin", "reports"] };
    const { main, more } = arrangeProjectNav(ITEMS, pref);
    await expect(keys(more)).toEqual(["reports"]);
    await expect(keys(main)).toContain("overview");
    await expect(keys(main)).toContain("admin");
  },
};

export const DuplicateStoredKeysAreCollapsed: Story = {
  play: async () => {
    const pref = { order: ["actions", "actions", "overview"], more: [] };
    const { main } = arrangeProjectNav(ITEMS, pref);
    await expect(keys(main).filter((key) => key === "actions")).toHaveLength(1);
    await expect(keys(main)).toHaveLength(ITEMS.length);
  },
};

export const ActiveRouteItemIsLiftedOutOfMore: Story = {
  play: async () => {
    const pref = { order: keys(ITEMS), more: ["actions", "reports"] };
    const { main, more } = layoutProjectNav(ITEMS, pref, "/p/reports/some-report");
    await expect(keys(main)).toEqual(["overview", "requirements", "admin", "reports"]);
    await expect(keys(more)).toEqual(["actions"]);
    // Off those routes nothing is lifted.
    await expect(keys(layoutProjectNav(ITEMS, pref, "/p/requirements").more)).toEqual(["actions", "reports"]);
  },
};

export const ActiveMatchingHonoursExact: Story = {
  play: async () => {
    await expect(isNavPathActive("/p/requirements/1", "/p/requirements")).toBe(true);
    await expect(isNavPathActive("/p/requirements", "/p", true)).toBe(false);
    await expect(isNavPathActive("/p", "/p", true)).toBe(true);
  },
};

export const MalformedStoredValuesAreRejected: Story = {
  play: async () => {
    await expect(parseNavPref(null)).toBeNull();
    await expect(parseNavPref("overview")).toBeNull();
    await expect(parseNavPref([])).toBeNull();
    await expect(parseNavPref({ order: ["a"] })).toBeNull();
    await expect(parseNavPref({ order: ["a", 1], more: [] })).toBeNull();
    await expect(parseNavPref({ order: ["a"], more: [] })).toEqual({ order: ["a"], more: [] });
  },
};

export const OverrideBeatsDefaultAndMalformedOverrideFallsThrough: Story = {
  play: async () => {
    const userDefault = { order: ["a"], more: [] };
    const override = { order: ["b"], more: [] };
    await expect(resolveNavPref(userDefault, override)).toEqual(override);
    await expect(resolveNavPref(userDefault, undefined)).toEqual(userDefault);
    await expect(resolveNavPref(userDefault, { order: "nope" })).toEqual(userDefault);
    await expect(resolveNavPref(undefined, undefined)).toBeNull();
  },
};

export const PrefFromArrangementRoundTrips: Story = {
  play: async () => {
    const pref = { order: ["overview", "reports", "requirements", "admin", "actions"], more: ["actions"] };
    const { main, more } = arrangeProjectNav(ITEMS, pref);
    await expect(navPrefFromArrangement(main, more)).toEqual(pref);
  },
};
