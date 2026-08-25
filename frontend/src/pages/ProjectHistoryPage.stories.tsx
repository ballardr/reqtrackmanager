import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import { buildChangeEntry, withRouter } from "../testing/storybook-helpers";
import { ProjectHistoryPage } from "./ProjectHistoryPage";

const meta: Meta<typeof ProjectHistoryPage> = {
  title: "Pages/ProjectHistoryPage",
  component: ProjectHistoryPage,
  decorators: [withRouter("/projects/project-1/history", "/projects/:projectId/history")],
};
export default meta;

type Story = StoryObj<typeof ProjectHistoryPage>;

/** Converted onto the shared `ActivityPanel` component (2026-08 UX audit
 * roadmap row 515), replacing this page's previous hand-rolled list
 * markup — each row now also carries a link to the item it's about
 * (`getLink`/`activityEntryLink`), which the old markup already had but
 * this asserts explicitly now that it's `ActivityPanel`'s own `getLink`
 * prop rendering it, not page-local JSX. */
export const ChangeHistory: Story = {
  beforeEach: () => {
    spyOn(api, "getPage").mockResolvedValue({
      items: [
        buildChangeEntry({ entity_id: "requirement-1", action: "updated", actor_display_name: "Alex Morgan" }),
        buildChangeEntry({
          entity_type: "change_request",
          entity_id: "cr-1",
          action: "approved",
          actor_display_name: "Jamie Lee",
        }),
      ],
      total: 2,
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Alex Morgan updated")).toBeInTheDocument();
    await expect(canvas.getByText("Jamie Lee approved")).toBeInTheDocument();
    // Falls back to the entity id as the link label since no `detail` was
    // provided (see `activityEntryLink` in api/types.ts).
    await expect(canvas.getByRole("link", { name: "requirement-1" })).toHaveAttribute(
      "href",
      "/projects/project-1/requirements/requirement-1"
    );
    await expect(canvas.getByRole("link", { name: "cr-1" })).toHaveAttribute(
      "href",
      "/projects/project-1/change-requests/cr-1"
    );
  },
};

export const FilterByEntityType: Story = {
  beforeEach: () => {
    spyOn(api, "getPage").mockResolvedValue({ items: [], total: 0 });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("No changes in this range.")).toBeInTheDocument();
    const select = canvas.getByLabelText("Type");
    await userEvent.selectOptions(select, "Requirement");
    await expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("entity_type=requirement"));
  },
};

/** U-P-06 / 2026-08 UX audit "Scale: two unbounded lists" — this timeline
 * previously fetched every change with no `limit`/`offset` at all. Clicking
 * "Load more" requests the next page at the correct offset and appends its
 * items below the first page's, rather than replacing them. */
export const LoadMoreAppendsTheNextPage: Story = {
  beforeEach: () => {
    spyOn(api, "getPage").mockImplementation(async (path: string) => {
      const offset = Number(new URL(path, "http://x").searchParams.get("offset"));
      if (offset === 0) {
        return { items: [buildChangeEntry({ entity_id: "req-1", action: "created", actor_display_name: "Alex Morgan" })], total: 2 };
      }
      return { items: [buildChangeEntry({ entity_id: "req-2", action: "updated", actor_display_name: "Jamie Lee" })], total: 2 };
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Alex Morgan created")).toBeInTheDocument());
    const loadMore = canvas.getByRole("button", { name: /Load more/ });
    await expect(loadMore).toBeInTheDocument();

    await userEvent.click(loadMore);
    await waitFor(() => expect(canvas.getByText("Jamie Lee updated")).toBeInTheDocument());
    // The first page's entry is still there — appended, not replaced.
    await expect(canvas.getByText("Alex Morgan created")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Load more/ })).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...ChangeHistory, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ChangeHistory, globals: { theme: "dark" } };
