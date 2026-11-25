import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { ActionMenu } from "../../components/ActionMenu";
import { FilterPanel } from "../../components/FilterPanel";
import { ToastProvider } from "../../context/ToastContext";
import { expectTextRows } from "../../testing/menuRows";
import { buildFolder } from "./architectureFixtures";
import { FolderPanel } from "./FolderPanel";
import { useFolderActions } from "./useFolderActions";
import type { ArchitectureFolder } from "./types";

const FOLDERS: ArchitectureFolder[] = [
  buildFolder({ id: "f-sw", name: "Software", path: "Software", record_count: 2 }),
  buildFolder({ id: "f-mod", name: "Modules", path: "Software/Modules", parent_id: "f-sw", record_count: 3 }),
  buildFolder({ id: "f-hw", name: "Hardware", path: "Hardware", sort_order: 1, record_count: 1 }),
];

function makeCalls() {
  return {
    list: fn(async () => FOLDERS),
    create: fn(async (values: { name: string; parent_id: string | null }) =>
      buildFolder({ id: "f-new", name: values.name, path: values.name, parent_id: values.parent_id })),
    update: fn(async (id: string, values: { name?: string; parent_id?: string | null }) =>
      buildFolder({ id, name: values.name ?? "Renamed", path: values.name ?? "Renamed" })),
    remove: fn(async () => undefined),
    moveRecords: fn(async () => ({ moved: 0 })),
  };
}

/** The tree in a filter panel and the folder actions in the page's actions menu, with the choice held in state as a list page holds it in the address. */
function Harness({ folders = FOLDERS, calls = makeCalls(), onChanged = fn() }: { folders?: ArchitectureFolder[]; calls?: ReturnType<typeof makeCalls>; onChanged?: () => void }) {
  const [path, setPath] = useState("");
  const [include, setInclude] = useState(true);
  const actions = useFolderActions({ noun: "elements", folders, calls, selectedPath: path, onSelect: setPath, onChanged });
  return (
    <ToastProvider>
      <ActionMenu triggerLabel="List actions" items={actions.menuItems} />
      {actions.dialogs}
      <FilterPanel sectionKey="folders.story" total={0} search="" onSearchChange={() => undefined} searchPlaceholder="Search" searchAriaLabel="Search">
        <FolderPanel folders={folders} selectedPath={path} onSelect={setPath} includeSub={include} onIncludeSubChange={setInclude} />
        <output aria-label="Chosen folder">{path || "none"}</output>
        <output aria-label="Include sub-folders state">{include ? "on" : "off"}</output>
      </FilterPanel>
    </ToastProvider>
  );
}

const meta: Meta<typeof Harness> = { title: "Architecture/FolderPanel", component: Harness };
export default meta;
type Story = StoryObj<typeof Harness>;

export const ChoosesAFolderAndShowsTheSubfolderChoice: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("checkbox", { name: /Include sub-folders/ })).toBeNull();
    await userEvent.click(canvas.getByRole("button", { name: "Folder Software" }));
    await expect(canvas.getByLabelText("Chosen folder")).toHaveTextContent("Software");
    const include = canvas.getByRole("checkbox", { name: /Include sub-folders/ });
    await expect(include).toBeChecked();
    await userEvent.click(include);
    await expect(canvas.getByLabelText("Include sub-folders state")).toHaveTextContent("off");
    // Choosing the same folder again clears the filter.
    await userEvent.click(canvas.getByRole("button", { name: "Folder Software" }));
    await expect(canvas.getByLabelText("Chosen folder")).toHaveTextContent("none");
  },
};

const body = (canvasElement: HTMLElement) => within(canvasElement.ownerDocument.body);

async function openMenu(canvasElement: HTMLElement) {
  await userEvent.click(within(canvasElement).getByRole("button", { name: "List actions" }));
}

export const WithNoFoldersTheMenuOnlyOffersNewFolder: Story = {
  render: () => <Harness folders={[]} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText(/No folders yet/)).toBeVisible();
    await expect(canvas.queryByRole("button", { name: "New folder" })).toBeNull();
    await openMenu(canvasElement);
    await expect(await body(canvasElement).findByRole("menuitem", { name: "New folder" })).toBeVisible();
    await expect(body(canvasElement).queryByRole("menuitem", { name: "Edit folder" })).toBeNull();
    await expect(body(canvasElement).queryByRole("menuitem", { name: "Delete folder" })).toBeNull();
  },
};

/** With no choice there is no Edit or Delete row, never a disabled one; a chosen folder adds both. */
export const AChosenFolderAddsEditAndDeleteToTheMenu: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await openMenu(canvasElement);
    await expect(await body(canvasElement).findByRole("menuitem", { name: "New folder" })).toBeVisible();
    await expect(body(canvasElement).queryByRole("menuitem", { name: "Edit folder" })).toBeNull();
    await userEvent.keyboard("{Escape}");
    await userEvent.click(canvas.getByRole("button", { name: "Folder Hardware" }));
    await openMenu(canvasElement);
    await expect(await body(canvasElement).findByRole("menuitem", { name: "Edit folder" })).toBeVisible();
    await expect(body(canvasElement).getByRole("menuitem", { name: "Delete folder" })).toBeVisible();
    await expectTextRows(body(canvasElement).getByRole("menu"));
  },
};

export const CreatesAFolderUnderTheChosenOne: Story = {
  render: () => {
    const calls = makeCalls();
    return <Harness calls={calls} />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Folder Hardware" }));
    await openMenu(canvasElement);
    await userEvent.click(await body(canvasElement).findByRole("menuitem", { name: "New folder" }));
    const dialog = within(await body(canvasElement).findByRole("dialog"));
    await userEvent.type(dialog.getByRole("textbox", { name: /Name/ }), "Boards");
    await expect(dialog.getByRole("button", { name: "Parent folder" })).toHaveTextContent("Hardware");
    await userEvent.click(dialog.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(within(canvasElement.ownerDocument.body).queryByRole("dialog")).toBeNull());
  },
};

export const DeletingAFolderAsksFirstAndSaysNothingElseIsDeleted: Story = {
  render: () => {
    const calls = makeCalls();
    const onChanged = fn();
    return <Harness calls={calls} onChanged={onChanged} />;
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Folder Hardware" }));
    await openMenu(canvasElement);
    await userEvent.click(await body(canvasElement).findByRole("menuitem", { name: "Delete folder" }));
    const dialog = within(await body(canvasElement).findByRole("dialog"));
    await expect(dialog.getByText(/sub-folders move up to its parent folder\. Nothing else is deleted/)).toBeVisible();
    await userEvent.click(dialog.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(canvas.getByLabelText("Chosen folder")).toHaveTextContent("none"));
  },
};
