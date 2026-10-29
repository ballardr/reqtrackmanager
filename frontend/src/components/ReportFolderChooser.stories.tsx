import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";

import type { ReportFolderApi } from "../api/reportFolders";
import { buildFolderApi } from "../testing/reportFolderFixtures";
import { ReportFolderChooser } from "./ReportFolderChooser";

/** Hosts the control with state, as a form does. */
function Host({ initial = "", api, onChanged }: { initial?: string; api: ReportFolderApi; onChanged?: () => void }) {
  const [value, setValue] = useState(initial);
  return (
    <div>
      <ReportFolderChooser value={value} onChange={setValue} api={api} onChanged={onChanged} />
      <output aria-label="Value">{value}</output>
    </div>
  );
}

/** The folder control of a layout, a pack or a placement: a tree to choose from, with New folder, Rename and Delete. */
const meta: Meta<typeof ReportFolderChooser> = {
  title: "Components/Reports/ReportFolderChooser",
  component: ReportFolderChooser,
  render: () => <Host api={buildFolderApi()} />,
};
export default meta;

type Story = StoryObj<typeof ReportFolderChooser>;

const choice = (canvas: ReturnType<typeof within>, name: string) => canvas.findByRole("radio", { name });

/** Folders appear as a tree with the "no folder" row first; the folders the scope inherits are listed too. */
export const ListsTheFoldersAsATree: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await choice(canvas, "No folder (the default)")).toBeChecked();
    for (const name of ["Handover", "Quarterly", "Shared"]) await expect(await choice(canvas, name)).not.toBeChecked();
    await expect(canvas.getByRole("radiogroup", { name: "Folder" })).toBeInTheDocument();
  },
};

/** Choosing a row sets the value; no folder clears it. */
export const ChoosingAFolderSetsTheValue: Story = {
  render: () => <Host api={buildFolderApi()} initial="Shared" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await choice(canvas, "Shared")).toBeChecked();
    await userEvent.click(await choice(canvas, "Quarterly"));
    await expect(canvas.getByLabelText("Value")).toHaveTextContent("Handover/Quarterly");
    await userEvent.click(await choice(canvas, "No folder (the default)"));
    await expect(canvas.getByLabelText("Value")).toHaveTextContent("");
  },
};

/** New folder adds under the chosen folder, chooses it and tells the person. */
export const AddingAFolderInsideTheChosenOne: Story = {
  render: () => <Host api={buildFolderApi()} initial="Handover" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "New folder inside" }));
    await userEvent.type(canvas.getByRole("textbox", { name: "Name of the new folder inside Handover" }), "Annual");
    await userEvent.click(canvas.getByRole("button", { name: "Add" }));
    await expect(await choice(canvas, "Annual")).toBeChecked();
    await expect(canvas.getByLabelText("Value")).toHaveTextContent("Handover/Annual");
    await expect(await within(document.body).findByText("Folder Handover/Annual added.")).toBeInTheDocument();
  },
};

/** Enter applies the name and does not submit the form the control sits in; the server's refusal shows in the control. */
export const ADuplicateNameIsRefusedAndEnterDoesNotSubmitTheForm: Story = {
  render: () => {
    const submitted = fn();
    return (
      <form onSubmit={(event) => { event.preventDefault(); submitted(); }} aria-label="Host form">
        <Host api={buildFolderApi()} />
      </form>
    );
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const form = canvas.getByRole("form", { name: "Host form" });
    const submit = fn();
    form.addEventListener("submit", submit);
    await userEvent.click(await canvas.findByRole("button", { name: "New folder" }));
    await userEvent.type(canvas.getByRole("textbox", { name: "Name of the new folder" }), "handover{Enter}");
    await expect(await canvas.findByRole("alert")).toHaveTextContent("already exists");
    await expect(submit).not.toHaveBeenCalled();
  },
};

/** A folder three levels deep cannot hold another. */
export const ADeepestFolderCannotHaveASubFolder: Story = {
  render: () => <Host api={buildFolderApi([{ path: "A", own: true }, { path: "A/B", own: true }, { path: "A/B/C", own: true }])} initial="A/B/C" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("button", { name: "New folder inside" })).toBeDisabled();
  },
};

/** Renaming changes the last level, keeps what is inside and moves the value with it. */
export const RenamingAFolderFollowsTheValue: Story = {
  render: () => <Host api={buildFolderApi()} initial="Handover/Quarterly" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Rename" }));
    const name = canvas.getByRole("textbox", { name: "New name for Handover/Quarterly" });
    await expect(name).toHaveValue("Quarterly");
    await userEvent.clear(name);
    await userEvent.type(name, "Yearly");
    await userEvent.click(canvas.getByRole("button", { name: "Save name" }));
    await expect(await choice(canvas, "Yearly")).toBeChecked();
    await expect(canvas.getByLabelText("Value")).toHaveTextContent("Handover/Yearly");
  },
};

/** Delete asks first, says nothing is deleted but moved, and then selects the parent. */
export const DeletingAFolderMovesWhatIsInItUpAfterAsking: Story = {
  render: () => <Host api={buildFolderApi(undefined, "organization", 2)} initial="Handover/Quarterly" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Delete" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Delete the folder Handover/Quarterly?" }));
    await expect(dialog.getByText(/move up to Handover\. No report is deleted\./)).toBeInTheDocument();
    await userEvent.click(dialog.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(canvas.queryByRole("radio", { name: "Quarterly" })).not.toBeInTheDocument());
    await expect(canvas.getByLabelText("Value")).toHaveTextContent("Handover");
    await expect(await within(document.body).findByText("Folder Handover/Quarterly deleted. 2 filed items moved up.")).toBeInTheDocument();
  },
};

/** A folder the scope only inherits can be filed under, but not renamed or deleted, and the reason is on the button. */
export const AnInheritedFolderCannotBeChanged: Story = {
  render: () => <Host api={buildFolderApi()} initial="Shared" />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const rename = await canvas.findByRole("button", { name: "Rename" });
    await expect(rename).toBeDisabled();
    await expect(rename).toHaveAttribute("title", expect.stringContaining("organisation or a parent project"));
    await expect(canvas.getByRole("button", { name: "Delete" })).toBeDisabled();
  },
};

/** With no folder chosen there is nothing to rename or delete; New folder adds at the top level. */
export const NothingChosenCanOnlyAddATopLevelFolder: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("button", { name: "New folder" })).toBeEnabled();
    await expect(canvas.getByRole("button", { name: "Rename" })).toBeDisabled();
    await expect(canvas.getByRole("button", { name: "Delete" })).toBeDisabled();
  },
};

export const LightTheme: Story = { ...ListsTheFoldersAsATree, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ListsTheFoldersAsATree, globals: { theme: "dark" } };
