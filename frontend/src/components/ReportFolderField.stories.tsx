import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";

import type { ReportFolderApi } from "../api/reportFolders";
import { buildFolderApi, openFolderPopover } from "../testing/reportFolderFixtures";
import { ReportFolderField } from "./ReportFolderField";

/** Hosts the field with state, as a layout or pack form does. */
function Host({ initial = "", api, onChanged, width = "22rem" }: { initial?: string; api: ReportFolderApi; onChanged?: () => void; width?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <div style={{ width, padding: "var(--space-5)" }}>
      <ReportFolderField value={value} onChange={setValue} api={api} onChanged={onChanged} />
      <output aria-label="Value">{value}</output>
    </div>
  );
}

/** The folder field of a layout or pack form: it says where the report is and opens a popover to move it. */
const meta: Meta<typeof ReportFolderField> = {
  title: "Components/Reports/ReportFolderField",
  component: ReportFolderField,
  render: () => <Host api={buildFolderApi()} />,
};
export default meta;

type Story = StoryObj<typeof ReportFolderField>;

/** With no folder the field reads "No folder"; the tree is not shown until it is pressed. */
export const ShowsWhereTheReportIsAndHidesTheTree: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Folder: No folder" })).toHaveTextContent("No folder");
    await expect(canvas.queryByRole("radiogroup")).not.toBeInTheDocument();
  },
};

/** Choosing a folder closes the popover and the field shows the path. */
export const ChoosingAFolderClosesThePopoverAndSetsTheValue: Story = {
  render: () => <Host api={buildFolderApi()} initial="Shared" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const popover = await openFolderPopover(canvas, "Shared");
    await expect(await popover.findByRole("radio", { name: "Shared" })).toBeChecked();
    await userEvent.click(popover.getByRole("radio", { name: "Quarterly" }));
    await waitFor(() => expect(screen.queryByRole("dialog", { name: "Move to a folder" })).not.toBeInTheDocument());
    await expect(canvas.getByLabelText("Value")).toHaveTextContent("Handover/Quarterly");
    await expect(canvas.getByRole("button", { name: "Folder: Handover/Quarterly" })).toBeInTheDocument();
  },
};

/** Adding a folder keeps the popover open (the person may still choose), tells the page, and the new folder is the value. */
export const AddingAFolderKeepsThePopoverOpen: Story = {
  render: () => <Host api={buildFolderApi()} onChanged={fn()} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const popover = await openFolderPopover(canvas);
    await userEvent.click(await popover.findByRole("button", { name: "New folder" }));
    await userEvent.type(popover.getByRole("textbox", { name: "Name of the new folder" }), "Annual");
    await userEvent.click(popover.getByRole("button", { name: "Add" }));
    await expect(await popover.findByRole("radio", { name: "Annual" })).toBeChecked();
    await expect(canvas.getByLabelText("Value")).toHaveTextContent("Annual");
  },
};

/** In a field the width of a dialog the popover opens at the field's left edge, not at its far end. */
export const PopoverOpensAtTheLeftEdgeOfAWideField: Story = {
  render: () => <Host api={buildFolderApi()} width="70rem" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const trigger = canvas.getByRole("button", { name: "Folder: No folder" });
    await userEvent.click(trigger);
    const panel = await screen.findByRole("dialog", { name: /folder/i });
    await expect(Math.abs(panel.getBoundingClientRect().left - trigger.getBoundingClientRect().left)).toBeLessThan(2);
    await expect(panel.getBoundingClientRect().width).toBeLessThanOrEqual(449);
  },
};
