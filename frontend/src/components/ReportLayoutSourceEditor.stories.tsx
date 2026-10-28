import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, waitFor, within } from "storybook/test";

import type { NameInScope } from "../utils/reportLayoutTree";
import { buildBlockCatalogue, buildFieldCatalogue } from "../testing/reportLayoutFixtures";
import { ReportLayoutSourceEditor } from "./ReportLayoutSourceEditor";

const NAMES: NameInScope[] = [
  { name: "req", kind: "record", recordType: "requirement" },
  { name: "grp", kind: "group", recordType: "requirement" },
];

/** Keeps the source in state and prints it, so a story can read what an edit produced. */
function Harness({ initial, names = NAMES, joinMode = false, variables = [] }: {
  initial: Record<string, unknown>; names?: NameInScope[]; joinMode?: boolean; variables?: string[];
}) {
  const [value, setValue] = useState(initial);
  return (
    <>
      <ReportLayoutSourceEditor
        value={value} onChange={setValue} names={names} catalogue={buildFieldCatalogue()} blocks={buildBlockCatalogue()}
        variables={variables} joinMode={joinMode}
      />
      <pre data-testid="value" hidden>{JSON.stringify(value)}</pre>
    </>
  );
}

/** Where a block's records come from: all of a type, records linked to an enclosing record, or a group's members. */
const meta: Meta<typeof Harness> = { title: "Components/ReportLayoutSourceEditor", component: Harness, args: { initial: {} } };
export default meta;

type Story = StoryObj<typeof Harness>;

const valueOf = (el: HTMLElement) => JSON.parse(within(el).getByTestId("value").textContent ?? "null");

export const AllRecordsOfATypeIsTheDefault: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect((canvas.getByRole("combobox", { name: "Records come from" }) as HTMLSelectElement).value).toBe("all");
    // No type yet, so nothing to filter or sort by.
    await expect(canvas.queryByText("Only records where")).not.toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Record type" }), "requirement");
    await waitFor(() => expect(valueOf(canvasElement)).toEqual({ record_type: "requirement" }));
    await expect(canvas.getByText("Only records where")).toBeInTheDocument();
  },
};

export const LinkedRecordsNameWhereTheyAreLinkedFrom: Story = {
  args: { initial: { record_type: "pain_point", linked_from: "req" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const from = canvas.getByRole("combobox", { name: "Linked from" }) as HTMLSelectElement;
    // Only record names are offered, not the group.
    await expect(Array.from(from.options).map((o) => o.value)).toEqual(["", "req"]);
    await userEvent.type(canvas.getByRole("textbox", { name: "Link types" }), "Causes, Blocks");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Direction" }), "incoming");
    await waitFor(() => expect(valueOf(canvasElement)).toEqual({
      record_type: "pain_point", linked_from: "req", link_types: ["Causes", "Blocks"], direction: "incoming",
    }));
    // Back to either way removes the key rather than storing the default.
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Direction" }), "both");
    await waitFor(() => expect(valueOf(canvasElement)).not.toHaveProperty("direction"));
  },
};

export const SwitchingModeDropsKeysThatNoLongerApply: Story = {
  args: { initial: { record_type: "pain_point", linked_from: "req", link_types: ["Causes"], direction: "incoming", sort: [{ field: "title" }] } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Records come from" }), "group");
    // A group source has no type or link; it keeps the sort the author set.
    await waitFor(() => expect(valueOf(canvasElement)).toEqual({ group: "grp", sort: [{ field: "title" }] }));
    await expect(canvas.queryByRole("combobox", { name: "Record type" })).not.toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Records come from" }), "all");
    await waitFor(() => expect(valueOf(canvasElement)).toEqual({ sort: [{ field: "title" }] }));
  },
};

export const ChangingTheTypeClearsFiltersAndSortThatNamedItsFields: Story = {
  args: { initial: { record_type: "requirement", where: [{ field: "status", op: "eq", value: "Draft" }], sort: [{ field: "title" }] } },
  play: async ({ canvasElement }) => {
    await userEvent.selectOptions(within(canvasElement).getByRole("combobox", { name: "Record type" }), "pain_point");
    await waitFor(() => expect(valueOf(canvasElement)).toEqual({ record_type: "pain_point" }));
  },
};

export const SortKeysAreCappedAtThreeAndOfferTheTypesFields: Story = {
  args: { initial: { record_type: "requirement" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    for (let i = 0; i < 3; i += 1) await userEvent.click(canvas.getByRole("button", { name: "Add sort" }));
    await expect(canvas.queryByRole("button", { name: "Add sort" })).not.toBeInTheDocument();
    const first = canvas.getByRole("combobox", { name: "Sort key 1" }) as HTMLSelectElement;
    await expect(Array.from(first.options).map((o) => o.value)).toEqual(["", "code", "title", "status", "description"]);
    await userEvent.selectOptions(first, "status");
    await userEvent.click(canvas.getByRole("checkbox", { name: "Sort key 1: Descending" }));
    await waitFor(() => expect(valueOf(canvasElement).sort[0]).toEqual({ field: "status", descending: true }));
    await userEvent.click(canvas.getByRole("button", { name: "Remove sort key 3" }));
    await waitFor(() => expect(valueOf(canvasElement).sort).toHaveLength(2));
  },
};

export const FiltersUseTheSourcesRecordType: Story = {
  args: { initial: { record_type: "requirement" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Add condition" }));
    const field = canvas.getByRole("combobox", { name: "Field" }) as HTMLSelectElement;
    await expect(Array.from(field.options).map((o) => o.value)).toContain("status");
    await userEvent.selectOptions(field, "status");
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Value" }), "Approved");
    await waitFor(() => expect(valueOf(canvasElement).where).toEqual([{ field: "status", op: "eq", value: "Approved" }]));
  },
};

export const ArchivedRecordsAreOptIn: Story = {
  args: { initial: { record_type: "requirement" } },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("checkbox", { name: "Include archived records" }));
    await waitFor(() => expect(valueOf(canvasElement)).toEqual({ record_type: "requirement", include_archived: true }));
    await userEvent.click(canvas.getByRole("checkbox", { name: "Include archived records" }));
    await waitFor(() => expect(valueOf(canvasElement)).toEqual({ record_type: "requirement" }));
  },
};

export const WithNoEnclosingNameThereIsNothingToLinkFrom: Story = {
  args: { initial: { record_type: "pain_point", linked_from: "" }, names: [] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByText("No enclosing block gives a name to link from.")).toBeInTheDocument();
  },
};

/** A sheet's join can only follow a link; there is no "all records" choice. */
export const AJoinOnlyFollowsALink: Story = {
  args: { initial: { linked_from: "req" }, joinMode: true },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("combobox", { name: "Records come from" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("combobox", { name: "Linked from" })).toBeInTheDocument();
  },
};
