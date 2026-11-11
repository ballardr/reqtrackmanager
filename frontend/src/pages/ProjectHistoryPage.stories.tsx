import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ChangeEntry, Principal } from "../api/types";
import { buildChangeEntry, withRouter } from "../testing/storybook-helpers";
import { ProjectHistoryPage } from "./ProjectHistoryPage";

const meta: Meta<typeof ProjectHistoryPage> = {
  title: "Pages/ProjectHistoryPage",
  component: ProjectHistoryPage,
};
export default meta;

type Story = StoryObj<typeof ProjectHistoryPage>;

/** The page's route, at `search` (a story that opens from a link sets the query), declared per story because a story-level
 * decorator would otherwise nest a second router inside the page's. */
const at = (search = "") => [withRouter(`/projects/project-1/history${search}`, "/projects/:projectId/history")];

const facets = { entity_types: ["requirement", "change_request", "tag"], total: 40 };

/** Serves the facets and the person labels; the list itself is each story's `getPage` fake. */
function mockSideReads(actors: Principal[] = []) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/changes/facets")) return facets as never;
    if (path.includes("/changes/actors")) return actors as never;
    return [] as never;
  });
}

const pageOf = (items: ChangeEntry[], total = items.length) => ({ items, total });

/** The table: one line per event with Time, Type, Event, Record and Person; a requirement and a change request open
 * their own page, and an entry of another registered type is named by the server's `record_label`. */
export const ChangeHistory: Story = {
  decorators: at(),
  beforeEach: () => {
    mockSideReads();
    spyOn(api, "getPage").mockResolvedValue(pageOf([
      buildChangeEntry({
        entity_id: "requirement-1", action: "updated", actor_display_name: "Alex Morgan",
        detail: { unique_code: "SW-PERF-014", name: "Response time budget" },
      }),
      buildChangeEntry({
        entity_type: "change_request", entity_id: "cr-1", action: "approved", actor_display_name: "Jamie Lee", kind: "status",
        detail: { proposed_name: "Loosen the budget" },
      }),
      buildChangeEntry({ entity_type: "requirement_action", entity_id: "act-1", action: "created", kind: "created", record_label: "ACT-004 Audit supplier" }),
      buildChangeEntry({ entity_type: "tag", entity_id: "tag-1", action: "created", kind: "created", actor_id: null, actor_display_name: null }),
    ]));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Project history" });
    for (const heading of ["Time", "Type", "Event", "Record", "Person"]) {
      await expect(within(table).getByRole("columnheader", { name: new RegExp(`^${heading}`) })).toBeInTheDocument();
    }
    await expect(canvas.getByRole("link", { name: "SW-PERF-014 — Response time budget" })).toHaveAttribute(
      "href", "/projects/project-1/requirements/requirement-1",
    );
    await expect(canvas.getByRole("link", { name: "Loosen the budget" })).toHaveAttribute("href", "/projects/project-1/change-requests/cr-1");
    await expect(canvas.getByText("ACT-004 Audit supplier")).toBeInTheDocument();
    await expect(canvas.getAllByText("Alex Morgan").length).toBeGreaterThan(0);
    // An event with no person (the system) says so rather than leaving the cell blank.
    await expect(canvas.getByText("System")).toBeInTheDocument();
    await expect(canvas.getByText("40 total", { exact: false })).toBeInTheDocument();
  },
};

/** A link event reads the verb and relationship in the Event column and names both records, stacked, in the Record column, each a link; a record the viewer cannot
 * open shows only its type, and another project's record is followed by that project's name. */
export const LinkEvents: Story = {
  decorators: at(),
  beforeEach: () => {
    mockSideReads();
    const requirement = {
      role: "source" as const, entity_type: "requirement", entity_type_label: "Requirement", entity_id: "requirement-1",
      label: "SW-PERF-014 Response time budget", project_id: "project-1", project_name: "Alpha",
    };
    spyOn(api, "getPage").mockResolvedValue(pageOf([
      buildChangeEntry({
        entity_type: "artefact_link", entity_id: "link-1", action: "created", kind: "links", link_type_label: "Depends on",
        linked_records: [requirement, {
          role: "target", entity_type: "decision", entity_type_label: "Decision", entity_id: "decision-1",
          label: "DEC-007 Use a queue", project_id: "project-1", project_name: "Alpha",
        }],
      }),
      buildChangeEntry({
        entity_type: "artefact_link", entity_id: "link-2", action: "deleted", kind: "links",
        linked_records: [requirement, {
          role: "target", entity_type: "decision", entity_type_label: "Decision", entity_id: null, label: null,
          project_id: null, project_name: null,
        }],
      }),
      buildChangeEntry({
        entity_type: "artefact_link", entity_id: "link-3", action: "created", kind: "links",
        linked_records: [requirement, {
          role: "target", entity_type: "requirement", entity_type_label: "Requirement", entity_id: "requirement-9",
          label: "HW-FN-002 Power budget", project_id: "project-2", project_name: "Parent programme",
        }],
      }),
    ]));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = await canvas.findByRole("table", { name: "Project history" });
    const created = within(table.querySelector("tbody tr:nth-of-type(1)") as HTMLElement);
    await expect(created.getByText("created a link (Depends on)")).toBeInTheDocument();
    await expect(created.getByRole("link", { name: "DEC-007 Use a queue" })).toHaveAttribute("href", "/projects/project-1/modules/decisions/decision-1");
    // The hidden end is named by its type only, and no link is drawn for it.
    const removed = within(table.querySelector("tbody tr:nth-of-type(2)") as HTMLElement);
    await expect(removed.getByText("removed a link")).toBeInTheDocument();
    await expect(removed.getByText("Decision (unavailable)")).toBeInTheDocument();
    await expect(removed.queryByRole("link", { name: /Decision/ })).not.toBeInTheDocument();
    // A record of another project opens in that project and names it.
    const elsewhere = within(table.querySelector("tbody tr:nth-of-type(3)") as HTMLElement);
    await expect(elsewhere.getByRole("link", { name: "HW-FN-002 Power budget (Parent programme)" })).toHaveAttribute(
      "href", "/projects/project-2/requirements/requirement-9",
    );
  },
};

/** The day is written once, on the first row of each local day; the rows below it carry the time alone. */
export const DaysAreGrouped: Story = {
  decorators: at(),
  beforeEach: () => {
    mockSideReads();
    spyOn(api, "getPage").mockResolvedValue(pageOf([
      buildChangeEntry({ timestamp: "2026-02-03T12:30:00" , action: "updated" }),
      buildChangeEntry({ timestamp: "2026-02-03T09:15:00", action: "created", kind: "created" }),
      buildChangeEntry({ timestamp: "2026-02-02T16:00:00", action: "approved", kind: "status" }),
    ]));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("table", { name: "Project history" });
    const dayCells = canvasElement.querySelectorAll("tbody time strong");
    await expect(dayCells.length).toBe(2);
  },
};

export const Empty: Story = {
  decorators: at(),
  beforeEach: () => {
    mockSideReads();
    spyOn(api, "getPage").mockResolvedValue(pageOf([]));
  },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("No changes in this range.")).toBeInTheDocument();
  },
};

/** With a filter set and nothing matching, the message names the filters and offers Clear filters. */
export const EmptyWhenFiltered: Story = {
  decorators: at("?kind=status&type=tag"),
  beforeEach: () => {
    mockSideReads();
    spyOn(api, "getPage").mockResolvedValue(pageOf([]));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("No events match these filters.")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Clear filters" }));
    await waitFor(() => expect(api.getPage).toHaveBeenLastCalledWith(expect.not.stringContaining("kind=status")));
  },
};

export const FilterByEntityType: Story = {
  decorators: at(),
  beforeEach: () => {
    mockSideReads();
    spyOn(api, "getPage").mockResolvedValue(pageOf([]));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const select = await canvas.findByLabelText("Type");
    await waitFor(() => expect(within(select).getByRole("option", { name: "Requirement" })).toBeInTheDocument());
    await userEvent.selectOptions(select, "Requirement");
    await waitFor(() => expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("entity_type=requirement")));
  },
};

/** The Event filter: ticking Status changes sends `kind=status`; the choices are the fixed kinds. */
export const FilterByKindOfEvent: Story = {
  decorators: at(),
  beforeEach: () => {
    mockSideReads();
    spyOn(api, "getPage").mockResolvedValue(pageOf([]));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Event" }));
    const popover = within(document.body);
    await userEvent.click(await popover.findByRole("checkbox", { name: "Status changes" }));
    await waitFor(() => expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("kind=status")));
  },
};

/** A custom period shows the two date-time inputs; the range is sent as UTC instants and its end is the end of the minute. */
export const CustomPeriod: Story = {
  decorators: at(),
  beforeEach: () => {
    mockSideReads();
    spyOn(api, "getPage").mockResolvedValue(pageOf([]));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(await canvas.findByLabelText("Period"), "Custom range");
    await userEvent.type(canvas.getByLabelText("From"), "2026-02-03T09:00");
    await userEvent.type(canvas.getByLabelText("To"), "2026-02-03T17:00");
    await waitFor(() => {
      const url = new URL(String((api.getPage as unknown as { mock: { lastCall: string[] } }).mock.lastCall[0]), "http://x");
      expect(url.searchParams.get("since")).toBe(new Date("2026-02-03T09:00").toISOString());
      expect(url.searchParams.get("until")).toBe(new Date(new Date("2026-02-03T17:00").getTime() + 59_999).toISOString());
    });
  },
};

/** A person filter restored from the link shows the names the server returns, and the list asks for them. */
export const PersonFilterFromLink: Story = {
  decorators: at("?actor=user:u1&actor=project_group:g1"),
  beforeEach: () => {
    mockSideReads([
      { type: "user", id: "u1", label: "Alex Morgan", member_count: null, exists: true },
      { type: "project_group", id: "g1", label: "Review board", member_count: 3, exists: true },
    ]);
    spyOn(api, "getPage").mockResolvedValue(pageOf([]));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByText("Alex Morgan")).toBeInTheDocument();
    await expect(canvas.getByText("Review board", { exact: false })).toBeInTheDocument();
    await waitFor(() => expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("actor=user%3Au1")));
    await expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("actor=project_group%3Ag1"));
  },
};

/** Sorting by Time flips the order the server is asked for. */
export const OldestFirst: Story = {
  decorators: at(),
  beforeEach: () => {
    mockSideReads();
    spyOn(api, "getPage").mockResolvedValue(pageOf([buildChangeEntry({ action: "created", kind: "created" })]));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: /Time/ }));
    await waitFor(() => expect(api.getPage).toHaveBeenLastCalledWith(expect.stringContaining("order=oldest")));
  },
};

/** "Show more" requests the next page at the correct offset and appends it below the first. */
export const LoadMoreAppendsTheNextPage: Story = {
  decorators: at(),
  beforeEach: () => {
    mockSideReads();
    spyOn(api, "getPage").mockImplementation(async (path: string) => {
      const offset = Number(new URL(path, "http://x").searchParams.get("offset"));
      if (offset === 0) return pageOf([buildChangeEntry({ entity_id: "req-1", action: "created", actor_display_name: "Alex Morgan" })], 2);
      return pageOf([buildChangeEntry({ entity_id: "req-2", action: "updated", actor_display_name: "Jamie Lee" })], 2);
    });
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Alex Morgan")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: /Load more/ }));
    await waitFor(() => expect(canvas.getByText("Jamie Lee")).toBeInTheDocument());
    await expect(canvas.getByText("Alex Morgan")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Load more/ })).not.toBeInTheDocument();
  },
};

/** The List actions menu offers Download shown items in every format, each narrowed by the page's filters. */
export const ExportMenuSendsTheFilters: Story = {
  decorators: at("?kind=status"),
  beforeEach: () => {
    mockSideReads();
    spyOn(api, "getPage").mockResolvedValue(pageOf([buildChangeEntry({ action: "approved", kind: "status" })]));
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["x"], { type: "text/csv" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "List actions" }));
    const body = within(document.body);
    await userEvent.click(await body.findByRole("menuitem", { name: "Download shown items" }));
    const submenu = within(await body.findByRole("menu", { name: "Download shown items" }));
    await userEvent.click(submenu.getByRole("menuitem", { name: /CSV/ }));
    await waitFor(() => expect(api.getForBlob).toHaveBeenCalledWith(expect.stringMatching(/changes\/export\?.*kind=status.*format=csv|changes\/export\?.*format=csv.*kind=status/)));
  },
};

export const LightTheme: Story = { ...ChangeHistory, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ChangeHistory, globals: { theme: "dark" } };
