import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { DetailCard } from "./DetailCard";
import { RecordField } from "./RecordDetailParts";

/**
 * The card a detail page puts a record's own fields (or a panel) in, under a heading. The page header
 * stays on the background above it.
 */
const meta: Meta<typeof DetailCard> = {
  title: "Components/DetailCard",
  component: DetailCard,
  args: {
    children: (
      <>
        <RecordField label="Description" value="Field reports queue for days when connectivity is poor." />
        <RecordField label="Rationale" value="Operators decide on stale data." />
      </>
    ),
  },
};
export default meta;

type Story = StoryObj<typeof DetailCard>;

/** "Details" is the default heading and names the section. */
export const DefaultIsDetails: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("heading", { level: 2, name: "Details" })).toBeInTheDocument();
    await expect(canvas.getByRole("region", { name: "Details" })).toHaveClass("card");
    await expect(canvas.getByText("Rationale")).toBeInTheDocument();
  },
};

/** A second group of fields (or a panel) takes its own heading. */
export const OwnHeading: Story = {
  args: { heading: "Scoring" },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("heading", { name: "Scoring" })).toBeInTheDocument();
  },
};

/** A control can sit on the heading's line, so adding to a list costs no extra row. */
export const ActionOnTheHeadingLine: Story = {
  args: { heading: "Stakeholders with this need", action: <button className="btn btn-sm btn-icon" aria-label="Add stakeholder">+</button> },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const heading = canvas.getByRole("heading", { name: "Stakeholders with this need" });
    await expect(heading.parentElement).toContainElement(canvas.getByRole("button", { name: "Add stakeholder" }));
  },
};

/** A long heading wraps inside the card; the action stays on the line. */
export const LongHeadingNarrow: Story = {
  args: { heading: "Requirements it gave rise to, including those from related projects", action: <button className="btn btn-sm">Add</button> },
  decorators: [(Story) => <div style={{ width: 280 }}><Story /></div>],
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Add" })).toBeVisible();
  },
};
