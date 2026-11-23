import type { Meta, StoryObj } from "@storybook/react-vite";
import { page } from "vitest/browser";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { FilterCheckbox, FilterField, FilterPanel } from "./FilterPanel";

/** Wraps `FilterPanel` as the list pages compose it. Needs a stateful `AuthContext` (`withStatefulAuth`) because
 * the collapsible body goes through `CollapsibleSection`, which persists state via `useUiPreference`. */
function Interactive({
  matching = 57,
  total = 57,
  layout,
  noFilterFields = false,
}: {
  matching?: number;
  total?: number;
  layout?: "side" | "top";
  noFilterFields?: boolean;
}) {
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
      {noFilterFields ? null : (
        <FilterField label="Status">
          <FilterCheckbox label="Include archived" checked={archived} onChange={setArchived} />
        </FilterField>
      )}
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

/** Wide viewport, above `FilterPanel`'s 860px breakpoint (theme.css `.side-grid` collapse width): the result
 * count and search sit in the always-visible header and the body is fully expanded with no toggle. */
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

/** `ResultCount`'s two display states through `FilterPanel` (`ResultCount.stories.tsx` covers it alone): the
 * header renders the `matching` and `total` props the consuming pages pass. */
export const MatchingCountShownWhenFiltered: Story = {
  args: { matching: 12, total: 57 },
  play: async ({ canvasElement }) => {
    await page.viewport(1280, 800);
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Showing 12 matching · 57 total")).toBeInTheDocument());
  },
};

/** Below the mobile breakpoint the filter body defaults to collapsed, the header (result count and search)
 * stays visible, and the "Filters" toggle expands it, as `CollapsibleSection` does. */
export const MobileCollapsedByDefault: Story = {
  play: async ({ canvasElement }) => {
    await page.viewport(400, 800);
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("57 total")).toBeInTheDocument());
    await expect(canvas.getByPlaceholderText("Search")).toBeInTheDocument();
    // The `matchMedia` "change" listener behind `useNarrowViewport` fires asynchronously relative to
    // `page.viewport()`, so the collapse and its toggle may not be in the DOM immediately.
    const toggle = await waitFor(() => canvas.getByRole("button", { name: "Filters section" }));
    await waitFor(() => expect(toggle).toHaveAttribute("aria-expanded", "false"));
    await expect(canvas.queryByText("Include archived")).not.toBeInTheDocument();

    await userEvent.click(toggle);
    await expect(canvas.getByText("Include archived")).toBeInTheDocument();
    // `CollapsibleSection` renders a new node for its expanded state, so the pre-click `toggle` reference is
    // stale: re-query it.
    await expect(canvas.getByRole("button", { name: "Filters section" })).toHaveAttribute("aria-expanded", "true");
  },
};

/** `children={null}` (Org Groups, Project Groups, `OrgListPage.tsx`): a page with only the search box. `FilterPanel`
 * omits the "Filters" heading (and the mobile accordion) rather than a heading over an empty body (style guide
 * "Pattern: `FilterPanel`", "No filter fields beyond search"). */
export const NoFilterFieldsDesktop: Story = {
  args: { noFilterFields: true },
  play: async ({ canvasElement }) => {
    await page.viewport(1280, 800);
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("57 total")).toBeInTheDocument());
    await expect(canvas.getByPlaceholderText("Search")).toBeInTheDocument();
    await expect(canvas.queryByRole("heading", { name: "Filters" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("heading", { name: "Search" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Filters section" })).not.toBeInTheDocument();
  },
};

/** Same `children={null}` case below the mobile breakpoint — no collapse
 * toggle either, since there's nothing to collapse. */
export const NoFilterFieldsMobile: Story = {
  args: { noFilterFields: true },
  play: async ({ canvasElement }) => {
    await page.viewport(400, 800);
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("57 total")).toBeInTheDocument());
    await expect(canvas.getByPlaceholderText("Search")).toBeInTheDocument();
    await expect(canvas.queryByRole("heading", { name: "Filters" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("heading", { name: "Search" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Filters section" })).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...DesktopAlwaysExpanded, globals: { theme: "light" } };
export const DarkTheme: Story = { ...DesktopAlwaysExpanded, globals: { theme: "dark" } };

/** `layout="top"` (style guide "Pattern: filter panel placement - side vs. top"): above wide, many-column tables
 * (Org Users, Access Review, `ProjectMembersTable`). On desktop the header and filter fields render in one wrapping
 * horizontal row with no "Filters" heading. */
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
