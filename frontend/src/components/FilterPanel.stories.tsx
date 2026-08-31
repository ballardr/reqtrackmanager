import type { Meta, StoryObj } from "@storybook/react-vite";
import { page } from "vitest/browser";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { FilterCheckbox, FilterField, FilterPanel } from "./FilterPanel";

/** Wraps `FilterPanel` the way `RequirementsPage`/`ProjectListPage`
 * actually compose it post-restructure (2026-08 UX audit roadmap: a
 * `ResultCount` + relocated search field in the always-visible header,
 * and the dropdown/checkbox filters as the collapsible body). Needs a
 * real, stateful `AuthContext` (`withStatefulAuth`, not the no-op stub
 * `withAuth` defaults to) because the collapsible body goes through
 * `CollapsibleSection`, which persists collapsed/expanded state via
 * `useUiPreference` → `useAuth()`. */
function Interactive({ matching = 57, total = 57, layout }: { matching?: number; total?: number; layout?: "side" | "top" }) {
  const [search, setSearch] = useState("");
  const [archived, setArchived] = useState(false);
  return (
    <FilterPanel
      layout={layout}
      sectionKey="storyFilters"
      matching={matching}
      total={total}
      search={search}
      onSearchChange={setSearch}
      searchPlaceholder="Search"
    >
      <FilterField label="Status">
        <FilterCheckbox label="Include archived" checked={archived} onChange={setArchived} />
      </FilterField>
    </FilterPanel>
  );
}

const meta: Meta<typeof Interactive> = {
  title: "Components/FilterPanel",
  component: Interactive,
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} }))],
};
export default meta;

type Story = StoryObj<typeof Interactive>;

/** Desktop/wide viewport, above `FilterPanel`'s 860px mobile breakpoint
 * (theme.css's own `.side-grid` collapse width): the result count and the
 * relocated search field sit in the always-visible header, and the filter
 * body renders fully expanded with no toggle affordance at all — "no
 * visible toggle friction" on desktop, per the 2026-08 UX audit roadmap. */
export const DesktopAlwaysExpanded: Story = {
  play: async ({ canvasElement }) => {
    await page.viewport(1280, 800);
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("57 total")).toBeInTheDocument());
    await expect(canvas.getByPlaceholderText("Search")).toBeInTheDocument();
    await expect(canvas.getByText("Include archived")).toBeInTheDocument();
    // No collapse toggle exists at all on desktop — the body isn't behind
    // a `CollapsibleSection` there, just a plain heading + the filters.
    await expect(canvas.queryByRole("button", { name: "Filters section" })).not.toBeInTheDocument();
  },
};

/** `ResultCount`'s two display states, exercised through `FilterPanel`
 * itself (`ResultCount.stories.tsx` covers the component in isolation) —
 * this pins that the header actually renders the `matching`/`total` props
 * each of the three consuming pages passes through, the same way a real
 * search/filter narrowing the list would drive it. */
export const MatchingCountShownWhenFiltered: Story = {
  args: { matching: 12, total: 57 },
  play: async ({ canvasElement }) => {
    await page.viewport(1280, 800);
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Showing 12 matching · 57 total")).toBeInTheDocument());
  },
};

/** Below the mobile breakpoint, the filter body defaults to collapsed —
 * the header (result count + search) stays visible regardless, and a
 * click on the "Filters" toggle expands it — matching
 * `CollapsibleSection`'s own accordion behaviour
 * (`CollapsibleSection.stories.tsx`'s `CollapsedByDefault`). */
export const MobileCollapsedByDefault: Story = {
  play: async ({ canvasElement }) => {
    await page.viewport(400, 800);
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("57 total")).toBeInTheDocument());
    await expect(canvas.getByPlaceholderText("Search")).toBeInTheDocument();
    // The `matchMedia` "change" listener that flips `useNarrowViewport`'s
    // state fires asynchronously relative to `page.viewport()` resolving,
    // so the collapse (and the toggle it introduces) may not be reflected
    // in the DOM the instant control returns here.
    const toggle = await waitFor(() => canvas.getByRole("button", { name: "Filters section" }));
    await waitFor(() => expect(toggle).toHaveAttribute("aria-expanded", "false"));
    await expect(canvas.queryByText("Include archived")).not.toBeInTheDocument();

    await userEvent.click(toggle);
    await expect(canvas.getByText("Include archived")).toBeInTheDocument();
    // `CollapsibleSection` renders an entirely new node for its expanded
    // state rather than toggling an attribute on the same one (mirrors
    // `CollapsibleSection.stories.tsx`'s own collapsed/expanded pair), so
    // the pre-click `toggle` reference is stale here — re-query it.
    await expect(canvas.getByRole("button", { name: "Filters section" })).toHaveAttribute("aria-expanded", "true");
  },
};

export const LightTheme: Story = { ...DesktopAlwaysExpanded, globals: { theme: "light" } };
export const DarkTheme: Story = { ...DesktopAlwaysExpanded, globals: { theme: "dark" } };

/** `layout="top"` (follow-up UX fix, see docs/decisions.md and
 * docs/ux-style-guide.md's "Pattern: filter panel placement — side vs.
 * top") — used above wide, many-column tables (Org Users, Server Admin's
 * Access Review, `ProjectMembersTable`) instead of the default `"side"`
 * sidebar shell. On desktop, the header (result count + search) and the
 * filter fields both render in a single wrapping horizontal row, and —
 * unlike `"side"` — there's no `"Filters"` heading above the fields, since
 * a horizontal bar of visible controls doesn't need one. */
export const TopLayoutDesktop: Story = {
  args: { layout: "top" },
  play: async ({ canvasElement }) => {
    await page.viewport(1280, 800);
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("57 total")).toBeInTheDocument());
    await expect(canvas.getByPlaceholderText("Search")).toBeInTheDocument();
    await expect(canvas.getByText("Include archived")).toBeInTheDocument();
    // No "Filters" heading in top layout, unlike the default side layout.
    await expect(canvas.queryByRole("heading", { name: "Filters" })).not.toBeInTheDocument();
    // No collapse toggle either, same as side layout at this width.
    await expect(canvas.queryByRole("button", { name: "Filters section" })).not.toBeInTheDocument();
  },
};

/** `layout="top"` below the mobile breakpoint still collapses the filter
 * fields behind the same `CollapsibleSection` accordion `"side"` uses — the
 * header (result count + search) stays visible regardless. */
export const TopLayoutMobileCollapsedByDefault: Story = {
  args: { layout: "top" },
  play: async ({ canvasElement }) => {
    await page.viewport(400, 800);
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("57 total")).toBeInTheDocument());
    await expect(canvas.getByPlaceholderText("Search")).toBeInTheDocument();
    const toggle = await waitFor(() => canvas.getByRole("button", { name: "Filters section" }));
    await waitFor(() => expect(toggle).toHaveAttribute("aria-expanded", "false"));
    await expect(canvas.queryByText("Include archived")).not.toBeInTheDocument();

    await userEvent.click(toggle);
    await expect(canvas.getByText("Include archived")).toBeInTheDocument();
  },
};
