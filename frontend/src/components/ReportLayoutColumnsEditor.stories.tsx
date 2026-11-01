import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import { buildBlockCatalogue, buildFieldCatalogue } from "../testing/reportLayoutFixtures";
import type { NameInScope } from "../utils/reportLayoutTree";
import { ReportLayoutColumnsEditor, ReportLayoutJoinsEditor } from "./ReportLayoutColumnsEditor";

const catalogue = buildFieldCatalogue();

type Column = { field?: string; label?: string; from?: string; width?: string; link?: { sheet: string } };
type Join = { as?: string; source?: Record<string, unknown> };

function ColumnsHarness({ initial, names, sheets }: { initial: Column[]; names: NameInScope[]; sheets?: { name: string; recordType: string | null }[] }) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <ReportLayoutColumnsEditor value={value} onChange={setValue} names={names} catalogue={catalogue} sheets={sheets} />
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

/** The settings of a column are behind its gear; the popover is portalled to the page, so it is found from `document.body`. */
const popover = (name: string) => within(document.body).findByRole("dialog", { name });
const body = () => within(document.body);

/** A new column's settings open at once; the list shows its name once a field is chosen and has no inline "Column 1 field" boxes. */
export const ColumnsAreAddedChosenAndHeaded: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add column" }));
    const dialog = within(await popover("Settings for column Choose a field"));
    const field = dialog.getByRole("combobox", { name: "Field" }) as HTMLSelectElement;
    await expect(Array.from(field.options).map((o) => o.value)).toEqual(["", "code", "title", "status", "description"]);
    await userEvent.selectOptions(field, "title");
    await userEvent.type(dialog.getByRole("textbox", { name: "Heading" }), "Requirement");
    await waitFor(() => expect(valueOf(canvasElement)).toEqual([{ field: "title", label: "Requirement" }]));
    // The row reads as a name with the field's code muted beside it.
    await expect(within(canvas.getByRole("list", { name: "Columns" })).getByText("Requirement")).toBeInTheDocument();
    await expect(canvas.queryByRole("combobox", { name: /field/i })).toBeNull();
    // An emptied heading is removed, not stored as an empty string.
    await userEvent.clear(dialog.getByRole("textbox", { name: "Heading" }));
    await waitFor(() => expect(valueOf(canvasElement)).toEqual([{ field: "title" }]));
  },
};

export const ColumnsMoveAndAreRemoved: Story = {
  args: { initial: [{ field: "code" }, { field: "title" }, { field: "status" }] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Move column Code up" })).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Move column Status down" })).toBeDisabled();
    await userEvent.click(canvas.getByRole("button", { name: "Move column Title up" }));
    await waitFor(() => expect(valueOf(canvasElement).map((c: { field: string }) => c.field)).toEqual(["title", "code", "status"]));
    await userEvent.click(canvas.getByRole("button", { name: "Remove column Title" }));
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
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Settings for column Title" }));
    const dialog = within(await popover("Settings for column Title"));
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Reads from" }), "pain");
    // Moving to the joined record clears the field, and offers that type's fields.
    await waitFor(() => expect(valueOf(canvasElement)).toEqual([{ field: "", from: "pain" }]));
    const field = body().getByRole("combobox", { name: "Field" }) as HTMLSelectElement;
    await expect(Array.from(field.options).map((o) => o.value)).toEqual(["", "code", "title", "severity"]);
  },
};

/** In a sheet, a column can open its record's row on another sheet that lists the same kind of record. */
export const AColumnCanLinkToASheetThatListsItsRecordType: Story = {
  args: {
    initial: [{ field: "code" }],
    sheets: [
      { name: "Requirements", recordType: "requirement" },
      { name: "Pain points", recordType: "pain_point" },
      { name: "Archive", recordType: "requirement" },
    ],
  },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Settings for column Code" }));
    await popover("Settings for column Code");
    const select = body().getByRole("combobox", { name: "Links to sheet" }) as HTMLSelectElement;
    // Only the sheets that list requirements are offered, never the pain points sheet.
    await expect(Array.from(select.options).map((o) => o.value)).toEqual(["", "Requirements", "Archive"]);
    await userEvent.selectOptions(select, "Requirements");
    await waitFor(() => expect(valueOf(canvasElement)).toEqual([{ field: "code", link: { sheet: "Requirements" } }]));
    // Choosing "No link" removes the setting rather than storing an empty name.
    await userEvent.selectOptions(select, "");
    await waitFor(() => expect(valueOf(canvasElement)).toEqual([{ field: "code" }]));
  },
};

/** A column's width is typed as a share of the table or a length; emptying it goes back to automatic and removes the setting. */
export const AColumnWidthIsSetAndCleared: Story = {
  args: { initial: [{ field: "code" }, { field: "title" }] },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Settings for column Code" }));
    await popover("Settings for column Code");
    const width = body().getByRole("textbox", { name: "Width" });
    await expect(width).toHaveAttribute("placeholder", "auto");
    await userEvent.type(width, "12%");
    await waitFor(() => expect(valueOf(canvasElement)).toEqual([{ field: "code", width: "12%" }, { field: "title" }]));
    await userEvent.clear(width);
    await waitFor(() => expect(valueOf(canvasElement)).toEqual([{ field: "code" }, { field: "title" }]));
  },
};

/** A column with a non-default setting shows it on the closed gear, so a setting is never hidden invisibly. */
export const AColumnWithASettingMarksItsGear: Story = {
  args: { initial: [{ field: "code", width: "12%" }, { field: "title" }] },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Settings for column Code" })).toHaveClass("btn-marked");
    await expect(canvas.getByRole("button", { name: "Settings for column Title" })).not.toHaveClass("btn-marked");
  },
};

/** A long heading wraps in its row rather than pushing the buttons out of reach. */
export const ALongHeadingWrapsInItsRow: Story = {
  args: { initial: [{ field: "code", label: "A very long column heading that goes on and on and on and on and on and on and on" }] },
  render: (args) => <div style={{ width: 320 }}><ColumnsHarness {...args} /></div>,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: /^Remove column A very long/ })).toBeVisible();
    await expect(canvas.getByRole("button", { name: /^Settings for column A very long/ })).toBeVisible();
  },
};

/** A sheet that is gone from the layout still shows as the column's choice, so the problem is visible rather than hidden. */
export const ALinkToARemovedSheetStaysVisible: Story = {
  args: { initial: [{ field: "code", link: { sheet: "Old" } }], sheets: [{ name: "Requirements", recordType: "requirement" }] },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Settings for column Code" }));
    await popover("Settings for column Code");
    const link = body().getByRole("combobox", { name: "Links to sheet" }) as HTMLSelectElement;
    await expect(link.value).toBe("Old");
  },
};

/** No other sheet lists the column's record type, or the block is a document table: there is nothing to link to, so no choice. */
export const NoLinkChoiceWithoutASheetOfTheSameType: Story = {
  args: { initial: [{ field: "title" }], sheets: [{ name: "Pain points", recordType: "pain_point" }] },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Settings for column Title" }));
    await popover("Settings for column Title");
    await expect(body().queryByRole("combobox", { name: "Links to sheet" })).toBeNull();
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
