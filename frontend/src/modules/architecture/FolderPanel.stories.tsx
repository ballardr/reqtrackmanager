import type { Meta, StoryObj } from "@storybook/react-vite";
import { useState } from "react";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { FilterPanel } from "../../components/FilterPanel";
import { ToastProvider } from "../../context/ToastContext";
import { buildFolder } from "./architectureFixtures";
import { FolderPanel } from "./FolderPanel";
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

/** The panel with its choice held in state, as a list page holds it in the address. */
function Harness({ folders = FOLDERS, calls = makeCalls(), onChanged = fn() }: { folders?: ArchitectureFolder[]; calls?: ReturnType<typeof makeCalls>; onChanged?: () => void }) {
  const [path, setPath] = useState("");
  const [include, setInclude] = useState(true);
  return (
    <ToastProvider>
      <FilterPanel sectionKey="folders.story" total={0} search="" onSearchChange={() => undefined} searchPlaceholder="Search" searchAriaLabel="Search">
        <FolderPanel
          noun="elements" folders={folders} calls={calls} selectedPath={path} onSelect={setPath} includeSub={include}
          onIncludeSubChange={setInclude} onChanged={onChanged}
        />
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

export const WithNoFoldersOnlyOffersNewFolder: Story = {
  render: () => <Harness folders={[]} />,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "New folder" })).toBeVisible();
    await expect(canvas.queryByRole("button", { name: "Edit folder" })).toBeNull();
    await expect(canvas.queryByRole("button", { name: "Delete folder" })).toBeNull();
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
    await userEvent.click(canvas.getByRole("button", { name: "New folder" }));
    const dialog = within(await within(canvasElement.ownerDocument.body).findByRole("dialog"));
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
    await userEvent.click(canvas.getByRole("button", { name: "Delete folder" }));
    const body = within(canvasElement.ownerDocument.body);
    const dialog = within(await body.findByRole("dialog"));
    await expect(dialog.getByText(/sub-folders move up to its parent folder\. Nothing else is deleted/)).toBeVisible();
    await userEvent.click(dialog.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(canvas.getByLabelText("Chosen folder")).toHaveTextContent("none"));
  },
};
