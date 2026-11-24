import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import type { ChangeEntry, LinkedRecord } from "../api/types";
import { expectStressStable, stressText } from "../testing/stressFixtures";
import { buildChangeEntry, withRouter } from "../testing/storybook-helpers";
import { TextStress } from "../testing/TextStress";
import { toActivityRows } from "../utils/activityRows";
import { ProjectActivityTable } from "./ProjectActivityTable";

const meta: Meta<typeof ProjectActivityTable> = {
  title: "Components/ProjectActivityTable",
  component: ProjectActivityTable,
  decorators: [withRouter("/projects/project-1", "/projects/:projectId")],
};
export default meta;

type Story = StoryObj<typeof ProjectActivityTable>;

const source: LinkedRecord = {
  role: "source", entity_type: "requirement", entity_type_label: "Requirement", entity_id: "requirement-1",
  label: "SW-PERF-014 Response time budget", project_id: "project-1", project_name: "Alpha",
};
const target: LinkedRecord = {
  role: "target", entity_type: "decision", entity_type_label: "Decision", entity_id: "decision-1",
  label: "DEC-007 Use a queue", project_id: "project-1", project_name: "Alpha",
};

/** One entry of each kind the table words: a record change, a status change with a note, a link event, a comment, a
 * record of a registered type and an event with no person. */
function entries(long = false): ChangeEntry[] {
  return [
    buildChangeEntry({
      timestamp: "2026-02-02T10:00:00Z", action: "updated", actor_display_name: stressText(long, "Alex Morgan", "word"),
      detail: { unique_code: "SW-PERF-014", name: stressText(long, "Response time budget") },
    }),
    buildChangeEntry({
      timestamp: "2026-02-02T09:30:00Z", entity_type: "change_request", entity_id: "cr-1", action: "approved", kind: "status",
      actor_display_name: "Jamie Lee", detail: { proposed_name: "Loosen the budget", comment: "Agreed in the weekly review." },
    }),
    buildChangeEntry({
      timestamp: "2026-02-01T16:00:00Z", entity_type: "artefact_link", entity_id: "link-1", action: "created", kind: "links",
      link_type_label: "Depends on", linked_records: [source, target],
    }),
    buildChangeEntry({
      timestamp: "2026-02-01T15:00:00Z", entity_type: "requirement", action: "comment_added", kind: "edited", actor_display_name: "Sam Lee",
      detail: { unique_code: "SW-PERF-014", name: "Response time budget" },
    }),
    buildChangeEntry({
      timestamp: "2026-02-01T14:00:00Z", entity_type: "requirement_action", entity_id: "act-1", action: "created", kind: "created",
      record_label: stressText(long, "ACT-004 Audit supplier", "summary"), actor_id: null, actor_display_name: null,
    }),
  ];
}

const empty = <p>No changes in this range.</p>;

function Wide({ long = false }: { long?: boolean }) {
  return <ProjectActivityTable rows={toActivityRows(entries(long))} projectId="project-1" ariaLabel="Project activity" emptyState={empty} />;
}

/** The History page's table without sorting: Time, Type, Event, Record and Person, a day written once. */
export const Columns: Story = {
  render: () => <Wide />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const table = canvas.getByRole("table", { name: "Project activity" });
    for (const heading of ["Time", "Type", "Event", "Record", "Person"]) {
      await expect(within(table).getByRole("columnheader", { name: new RegExp(`^${heading}`) })).toBeInTheDocument();
    }
    await expect(canvas.getByText("Updated")).toBeInTheDocument();
    await expect(canvas.getAllByRole("link", { name: "SW-PERF-014 — Response time budget" })[0].getAttribute("href")).toBe(
      "/projects/project-1/requirements/requirement-1",
    );
    await expect(canvas.getByText("Agreed in the weekly review.")).toBeInTheDocument();
    await expect(canvas.getByText("Created a link (Depends on)")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "DEC-007 Use a queue" })).toBeInTheDocument();
    await expect(canvas.getByText("System")).toBeInTheDocument();
    // A day is written once, on its first row: as many dates as there are local days among the entries.
    const days = new Set(entries().map((entry) => new Date(entry.timestamp).toLocaleDateString()));
    await expect(canvasElement.querySelectorAll(".activity-table__day")).toHaveLength(days.size);
  },
};

/** The widget's form: the table stacks when its own container is narrow, whatever the window is. */
export const NarrowWidget: Story = {
  render: () => (
    <div style={{ width: 340 }}>
      <ProjectActivityTable
        rows={toActivityRows(entries())} projectId="project-1" ariaLabel="Project activity" emptyState={empty} stacks
      />
    </div>
  ),
  play: async ({ canvasElement }) => {
    const header = canvasElement.querySelector("thead") as HTMLElement;
    await expect(getComputedStyle(header).display).toBe("none");
    const row = canvasElement.querySelector("tbody tr") as HTMLElement;
    await expect(getComputedStyle(row).display).toBe("flex");
    const cells = Array.from(row.querySelectorAll("td")).map((cell) => cell.getBoundingClientRect());
    // The event and the record each take a line of their own, below the type, time and person.
    await expect(cells[2].top).toBeGreaterThan(cells[0].bottom - 1);
    await expect(cells[3].top).toBeGreaterThan(cells[2].bottom - 1);
  },
};

/** The same container wide enough keeps the columns, in the same order. */
export const WideWidget: Story = {
  render: () => (
    <div style={{ width: 900 }}>
      <ProjectActivityTable
        rows={toActivityRows(entries())} projectId="project-1" ariaLabel="Project activity" emptyState={empty} stacks
      />
    </div>
  ),
  play: async ({ canvasElement }) => {
    await expect(getComputedStyle(canvasElement.querySelector("thead") as HTMLElement).display).not.toBe("none");
    const heads = Array.from(canvasElement.querySelectorAll("th")).map((th) => th.textContent);
    await expect(heads).toEqual(["Time", "Type", "Event", "Record(s)", "Person"]);
  },
};

/** The widget and the History page show the same wording for the same entries (they are one component). */
export const SameTextBothWays: Story = {
  render: () => (
    <div>
      <div data-form="page" style={{ width: 900 }}><Wide /></div>
      <div data-form="widget" style={{ width: 340 }}>
        <ProjectActivityTable rows={toActivityRows(entries())} projectId="project-1" ariaLabel="Widget activity" emptyState={empty} stacks />
      </div>
    </div>
  ),
  play: async ({ canvasElement }) => {
    const text = (form: string) => Array.from(canvasElement.querySelectorAll(`[data-form="${form}"] tbody tr`)).map(
      (row) => Array.from(row.querySelectorAll("td")).map((cell) => cell.textContent).join("|"),
    );
    await expect(text("widget")).toEqual(text("page"));
  },
};

/** An entry with no actor shows "System", and an entry with no openable record shows a dash, not a gap. */
export const RemovedPerson: Story = {
  render: () => (
    <ProjectActivityTable
      rows={toActivityRows([buildChangeEntry({ entity_type: "tag", entity_id: "tag-1", action: "created", kind: "created", actor_id: null, actor_display_name: null })])}
      projectId="project-1" ariaLabel="Project activity" emptyState={empty}
    />
  ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("System")).toBeInTheDocument();
    await expect(canvas.getByText("—")).toBeInTheDocument();
  },
};

export const Empty: Story = {
  render: () => <ProjectActivityTable rows={[]} projectId="project-1" ariaLabel="Project activity" emptyState={empty} stacks />,
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("No changes in this range.")).toBeInTheDocument();
  },
};

/** A long title, an unbroken word and a long record label in several rows: the columns stay in line. */
export const LongText: Story = {
  render: () => (
    <TextStress
      width={900}
      render={(long) => (
        <ProjectActivityTable rows={toActivityRows(entries(long))} projectId="project-1" ariaLabel="Long text activity" emptyState={empty} />
      )}
    />
  ),
  play: async ({ canvasElement }) => {
    await expectStressStable(canvasElement);
  },
};

/** The stacked form with long text: nothing sticks out of its card. */
export const LongTextNarrow: Story = {
  render: () => (
    <TextStress
      width={340}
      render={(long) => (
        <ProjectActivityTable rows={toActivityRows(entries(long))} projectId="project-1" ariaLabel="Long text activity" emptyState={empty} stacks />
      )}
    />
  ),
  play: async ({ canvasElement }) => {
    for (const box of canvasElement.querySelectorAll<HTMLElement>("[data-stress]")) {
      await expect(box.scrollWidth).toBeLessThanOrEqual(box.clientWidth + 1);
    }
  },
};

export const LightTheme: Story = { ...Columns, globals: { theme: "light" } };
export const DarkTheme: Story = { ...Columns, globals: { theme: "dark" } };
