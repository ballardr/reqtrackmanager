import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, within } from "storybook/test";

import { buildFolder, mockArchitectureReads, PROJECT_ID } from "./architectureFixtures";
import { FolderField } from "./FolderField";
import { FolderFormModal } from "./FolderFormModal";
import { MoveToFolderDialog } from "./MoveToFolderDialog";
import type { ArchitectureFolder } from "./types";

const FOLDERS: ArchitectureFolder[] = [
  buildFolder({ id: "sw", name: "Software", path: "Software" }),
  buildFolder({ id: "mod", name: "Modules", path: "Software/Modules", parent_id: "sw" }),
  buildFolder({ id: "hw", name: "Hardware", path: "Hardware", sort_order: 1 }),
];

function Host() {
  return <p>Folder form pieces.</p>;
}

const meta: Meta<typeof Host> = { title: "Modules/Architecture/FolderForms", component: Host };
export default meta;
type Story = StoryObj<typeof Host>;

/** The field with its value held in state, as a form holds it. */
function FolderFieldDemo() {
  const [value, setValue] = useState<string | null>(null);
  return (
    <>
      <FolderField kind="element" owner={{ projectId: PROJECT_ID }} value={value} onChange={setValue} />
      <output aria-label="Chosen">{value ?? "none"}</output>
    </>
  );
}

const body = (canvasElement: HTMLElement) => within(canvasElement.ownerDocument.body);

export const FolderFieldChoosesAFolderAndClearsToTheTopLevel: Story = {
  beforeEach: () => { mockArchitectureReads({ folders: FOLDERS }); },
  render: () => <FolderFieldDemo />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Folder" }));
    await userEvent.click(await body(canvasElement).findByRole("radio", { name: "Hardware" }));
    await expect(canvas.getByLabelText("Chosen")).toHaveTextContent("hw");
    await userEvent.click(canvas.getByRole("button", { name: "Folder" }));
    await userEvent.click(await body(canvasElement).findByRole("radio", { name: "Top level (no folder)" }));
    await expect(canvas.getByLabelText("Chosen")).toHaveTextContent("none");
  },
};

export const FolderFormRefusesASlashAndNeverOffersTheFoldersOwnSubtreeAsParent: Story = {
  render: () => <FolderFormModal initial={FOLDERS[0]} folders={FOLDERS} onCancel={fn()} onSave={fn()} />,
  play: async ({ canvasElement }) => {
    const dialog = within(await body(canvasElement).findByRole("dialog"));
    const name = dialog.getByRole("textbox", { name: /Name/ });
    await userEvent.clear(name);
    await userEvent.type(name, "A/B");
    await expect(dialog.getByText("A folder name cannot contain a slash.")).toBeVisible();
    await expect(dialog.getByRole("button", { name: "Save" })).toBeDisabled();
    await userEvent.click(dialog.getByRole("button", { name: "Parent folder" }));
    // Software is being edited, so neither it nor Modules (below it) is a parent choice; Hardware is.
    await expect(await body(canvasElement).findByRole("radio", { name: "Hardware" })).toBeVisible();
    await expect(body(canvasElement).queryByRole("radio", { name: "Modules" })).toBeNull();
  },
};

export const FolderFormSavesTheTrimmedNameAndParent: Story = {
  render: () => <FolderFormModal folders={FOLDERS} defaultParentId="hw" onCancel={fn()} onSave={saved} />,
  play: async ({ canvasElement }) => {
    saved.mockClear();
    const dialog = within(await body(canvasElement).findByRole("dialog"));
    await userEvent.type(dialog.getByRole("textbox", { name: /Name/ }), "  Boards  ");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await expect(saved).toHaveBeenCalledWith({ name: "Boards", parent_id: "hw" });
  },
};

export const MoveDialogMovesToTheChosenFolderOrTheTopLevel: Story = {
  render: () => <MoveToFolderDialog count={2} noun="elements" folders={FOLDERS} onCancel={fn()} onMove={moved} />,
  play: async ({ canvasElement }) => {
    moved.mockClear();
    const dialog = within(await body(canvasElement).findByRole("dialog"));
    await expect(dialog.getByRole("heading", { name: "Move 2 elements to a folder" })).toBeVisible();
    await userEvent.click(dialog.getByRole("button", { name: "Folder" }));
    await userEvent.click(await body(canvasElement).findByRole("radio", { name: "Hardware" }));
    await userEvent.click(dialog.getByRole("button", { name: "Move" }));
    await expect(moved).toHaveBeenCalledWith("hw");
  },
};

const saved = fn();
const moved = fn();
