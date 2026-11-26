import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import { expectStressStable, stressText } from "../../testing/stressFixtures";
import { withRouter } from "../../testing/storybook-helpers";
import { TextStress } from "../../testing/TextStress";
import { PolicyTable, type PolicyColumn, type PolicyRow } from "./PolicyTable";

interface Row extends PolicyRow {
  days: number | null;
}

const ROWS: Row[] = [
  { artefact_type: "risk", label: "Risk", days: 90 },
  { artefact_type: "decision", label: "Decision", days: null },
  { artefact_type: "requirement", label: "Requirement", days: 30 },
];

const COLUMNS: PolicyColumn<Row>[] = [
  { key: "days", label: "Interval", render: (row) => (row.days === null ? "Not set" : `${row.days} days`), sortValue: (row) => row.days },
];

const meta: Meta<typeof PolicyTable<Row>> = {
  title: "Modules/Governance/PolicyTable",
  decorators: [withRouter("/")],
  component: PolicyTable<Row>,
  args: {
    ariaLabel: "Review policy by record type",
    rows: ROWS,
    columns: COLUMNS,
    emptyText: "No record type has a review schedule.",
    rowMenu: () => [{ label: "Edit review settings", onSelect: fn() }],
    rowMenuLabel: (row) => `Actions for ${row.label}`,
  },
};
export default meta;

type Story = StoryObj<typeof PolicyTable<Row>>;

/** Rows appear in the order given; a row with a menu shows one named for its record type. */
export const Default: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("table", { name: "Review policy by record type" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Actions for Risk" })).toBeInTheDocument();
  },
};

/** A header click orders the rows by that column; an empty value sorts last. */
export const SortsByAColumn: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /Interval/ }));
    const first = canvas.getAllByRole("row")[1];
    await expect(within(first).getByText("Requirement")).toBeInTheDocument();
  },
};

/** A read-only table has no row menu. */
export const ReadOnly: Story = {
  args: { rowMenu: undefined },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button", { name: /Actions for/ })).toBeNull();
  },
};

/** No record type has such a policy. */
export const Empty: Story = {
  args: { rows: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("No record type has a review schedule.")).toBeInTheDocument();
  },
};

export const DarkTheme: Story = { ...Default, globals: { theme: "dark" } };

/** Long record type names keep every row's columns and menu aligned. */
export const LongText: Story = {
  render: (args) => (
    <TextStress
      render={(long) => (
        <PolicyTable<Row>
          {...args}
          rows={ROWS.map((row, index) => ({ ...row, label: index === 0 ? stressText(long, row.label) : row.label }))}
        />
      )}
    />
  ),
  play: async ({ canvasElement }) => {
    await expectStressStable(canvasElement);
  },
};
