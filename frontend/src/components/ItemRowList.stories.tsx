import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, within } from "storybook/test";

import { expectStressStable, stressText } from "../testing/stressFixtures";
import { TextStress } from "../testing/TextStress";
import { ItemRowList } from "./ItemRowList";

/** A flat list of editable items: a name with a muted detail, and the row's own controls on the right. */
const meta: Meta<typeof ItemRowList> = {
  title: "Components/ItemRowList",
  component: ItemRowList,
  args: {
    label: "Columns",
    emptyName: "Choose a field",
    items: [
      { id: "1", name: "Code", actions: <button type="button" className="btn btn-sm">Edit Code</button> },
      { id: "2", name: "Requirement", detail: "title", actions: <button type="button" className="btn btn-sm">Edit Requirement</button> },
      { id: "3", name: "", actions: <button type="button" className="btn btn-sm">Edit unnamed</button> },
    ],
  },
};
export default meta;

type Story = StoryObj<typeof ItemRowList>;

export const RowsShowTheirNameDetailAndActions: Story = {
  play: async ({ canvasElement }) => {
    const list = within(canvasElement).getByRole("list", { name: "Columns" });
    await expect(within(list).getAllByRole("listitem")).toHaveLength(3);
    await expect(within(list).getByText("title")).toHaveClass("text-muted");
    // A row with no name yet says what is missing instead of rendering blank.
    await expect(within(list).getByText("Choose a field")).toBeInTheDocument();
    await expect(within(list).getByRole("button", { name: "Edit Requirement" })).toBeVisible();
  },
};

/** A long name, an unbroken word and a long detail in several rows: the Edit button stays at the end of its own row. */
export const LongText: Story = {
  render: () => (
    <TextStress
      width={560}
      render={(long) => (
        <ItemRowList
          label="Long text columns"
          emptyName="Choose a field"
          items={[
            { id: "1", name: stressText(long, "Code"), actions: <button type="button" className="btn btn-sm">Edit one</button> },
            { id: "2", name: stressText(long, "Requirement", "word"), detail: stressText(long, "title", "summary"), actions: <button type="button" className="btn btn-sm">Edit two</button> },
            { id: "3", name: "Status", detail: stressText(long, "status", "word"), actions: <button type="button" className="btn btn-sm">Edit three</button> },
          ]}
        />
      )}
    />
  ),
  play: async ({ canvasElement }) => {
    await expectStressStable(canvasElement);
  },
};
