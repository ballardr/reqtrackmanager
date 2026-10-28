import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, userEvent, within } from "storybook/test";

import { ReportFolderField } from "./ReportFolderField";

/** Hosts the field with state, as a form does. */
function Host({ initial = "" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return <ReportFolderField value={value} onChange={setValue} suggestions={["Handover", "Handover/Quarterly", "Risk"]} />;
}

/** The folder input of a layout, a pack or a placement: suggests existing folders and flags a path that would be refused. */
const meta: Meta<typeof ReportFolderField> = {
  title: "Components/Reports/ReportFolderField",
  component: ReportFolderField,
  render: () => <Host />,
};
export default meta;

type Story = StoryObj<typeof ReportFolderField>;

/** It is optional, so it carries no required marker, and it offers the folders in use as suggestions. */
export const OffersTheFoldersInUse: Story = {
  play: async ({ canvasElement }) => {
    const input = within(canvasElement).getByRole("combobox", { name: "Folder" });
    await expect(input).not.toBeRequired();
    await expect(Array.from(canvasElement.querySelectorAll("datalist option")).map((o) => o.getAttribute("value"))).toEqual(["Handover", "Handover/Quarterly", "Risk"]);
    await expect(within(canvasElement).getByText(/Use \/ for a folder inside a folder/)).toBeInTheDocument();
  },
};

export const FlagsAPathThatIsTooDeep: Story = {
  play: async ({ canvasElement }) => {
    const input = within(canvasElement).getByRole("combobox", { name: "Folder" });
    await userEvent.type(input, "a/b/c");
    await expect(within(canvasElement).queryByRole("alert")).not.toBeInTheDocument();
    await userEvent.type(input, "/d");
    await expect(within(canvasElement).getByRole("alert")).toHaveTextContent("at most 3 levels");
  },
};

export const FlagsALevelThatIsTooLong: Story = {
  play: async ({ canvasElement }) => {
    await userEvent.type(within(canvasElement).getByRole("combobox", { name: "Folder" }), "x".repeat(41));
    await expect(within(canvasElement).getByRole("alert")).toHaveTextContent("at most 40 characters");
  },
};

export const LightTheme: Story = { ...OffersTheFoldersInUse, globals: { theme: "light" } };
export const DarkTheme: Story = { ...OffersTheFoldersInUse, globals: { theme: "dark" } };
