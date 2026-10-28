import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildBlockCatalogue, buildFieldCatalogue } from "../testing/reportLayoutFixtures";
import type { NameInScope } from "../utils/reportLayoutTree";
import { ReportLayoutColumnsEditor, ReportLayoutJoinsEditor } from "./ReportLayoutColumnsEditor";

const catalogue = buildFieldCatalogue();

type Column = { field?: string; label?: string; from?: string };
type Join = { as?: string; source?: Record<string, unknown> };

function ColumnsHarness({ initial, names }: { initial: Column[]; names: NameInScope[] }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <ReportLayoutColumnsEditor value={value} onChange={setValue} names={names} catalogue={catalogue} />
      <pre data-testid="value" hidden>{JSON.stringify(value)}</pre>
    </>
  );
}

/** The columns of a table or sheet: a field per column, a heading, and (with joins) which record it reads. */
const meta: Meta<typeof ColumnsHarness> = {
  title: "Components/ReportLayoutColumnsEditor",
  component: ColumnsHarness,
  args: { initial: [], names: [{ name: "record", kind: "record", recordType: "requirement" }] },
};
export default meta;

type Story = StoryObj<typeof ColumnsHarness>;

const valueOf = (el: HTMLElement) => JSON.parse(within(el).getByTestId("value").textContent ?? "null");

export const ColumnsAreAddedChosenAndHeaded: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add column" }));
    const field = canvas.getByRole("combobox", { name: "Column 1 field" }) as HTMLSelectElement;
    await expect(Array.from(field.options).map((o) => o.value)).toEqual(["", "code", "title", "status", "description"]);
    await userEvent.selectOptions(field, "title");
    await userEvent.type(canvas.getByRole("textbox", { name: "Column 1 heading" }), "Requirement");
    await waitFor(() => expect(valueOf(canvasElement)).toEqual([{ field: "title", label: "Requirement" }]));
    // An emptied heading is removed, not stored as an empty string.
    await userEvent.clear(canvas.getByRole("textbox", { name: "Column 1 heading" }));
    await waitFor(() => expect(valueOf(canvasElement)).toEqual([{ field: "title" }]));
  },
};

export const ColumnsMoveAndAreRemoved: Story = {
  args: { initial: [{ field: "code" }, { field: "title" }, { field: "status" }] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Move column 1 up" })).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Move column 3 down" })).toBeDisabled();
    await userEvent.click(canvas.getByRole("button", { name: "Move column 2 up" }));
    await waitFor(() => expect(valueOf(canvasElement).map((c: { field: string }) => c.field)).toEqual(["title", "code", "status"]));
    await userEvent.click(canvas.getByRole("button", { name: "Remove column 1" }));
    await waitFor(() => expect(valueOf(canvasElement).map((c: { field: string }) => c.field)).toEqual(["code", "status"]));
  },
};

/** With joins, a column says which record it reads and offers that record's fields. */
export const AJoinedSheetChoosesWhichRecordAColumnReads: Story = {
  args: {
    initial: [{ field: "title" }],
    names: [{ name: "record", kind: "record", recordType: "requirement" }, { name: "pain", kind: "record", recordType: "pain_point" }],
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Column 1 reads from" }), "pain");
    // Moving to the joined record clears the field, and offers that type's fields.
    await waitFor(() => expect(valueOf(canvasElement)).toEqual([{ field: "", from: "pain" }]));
    const field = canvas.getByRole("combobox", { name: "Column 1 field" }) as HTMLSelectElement;
    await expect(Array.from(field.options).map((o) => o.value)).toEqual(["", "code", "title", "severity"]);
  },
};

function JoinsHarness({ initial }: { initial: Join[] }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <ReportLayoutJoinsEditor
        value={value} onChange={setValue} rootName="record" rootType="requirement" catalogue={catalogue} blocks={buildBlockCatalogue()} variables={[]}
      />
      <pre data-testid="value" hidden>{JSON.stringify(value)}</pre>
    </>
  );
}

export const JoinsAreNamedAndFollowALinkFromAnEarlierName: Story = {
  render: () => <JoinsHarness initial={[]} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add join" }));
    await userEvent.click(canvas.getByRole("button", { name: "Add join" }));
    await waitFor(() => expect(valueOf(canvasElement).map((j: { as: string }) => j.as)).toEqual(["joined", "joined2"]));
    // The second join can link from the root or from the first join.
    const second = within(canvas.getByRole("group", { name: "Join 2 name" }));
    const from = second.getByRole("combobox", { name: "Linked from" }) as HTMLSelectElement;
    await userEvent.selectOptions(second.getByRole("combobox", { name: "Record type" }), "pain_point");
    await expect(Array.from(from.options).map((o) => o.value)).toEqual(["", "record", "joined"]);
    await userEvent.click(canvas.getByRole("button", { name: "Remove join 1" }));
    await waitFor(() => expect(valueOf(canvasElement)).toHaveLength(1));
  },
};
