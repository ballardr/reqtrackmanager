import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, screen, userEvent, waitFor, within } from "storybook/test";

import { ApiError } from "../api/client";
import { buildStructureApi, buildStructureTree, STRUCTURE_PROJECT_ID } from "../testing/structureFixtures";
import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { StructurePanel } from "./StructurePanel";

/**
 * The Structure page of project administration: components and their categories as a collapsible tree in the tree's own
 * order, with each row's actions in a menu and create and edit in a side panel. The calls are a stateful fake, so a
 * created, moved or deleted node shows in the next read.
 */
const meta: Meta<typeof StructurePanel> = {
  title: "Components/StructurePanel",
  component: StructurePanel,
  decorators: [withStatefulAuth(buildUser({ ui_preferences: {} }))],
  args: { projectId: STRUCTURE_PROJECT_ID, onChanged: fn() },
};
export default meta;

type Story = StoryObj<typeof StructurePanel>;

const openMenu = async (canvas: ReturnType<typeof within>, name: string) =>
  userEvent.click(await canvas.findByRole("button", { name: `Actions for ${name}` }));

/** Components are shown closed; a component's row opens to its categories, and shows its prefix and counts. */
export const ComponentsStartClosedAndOpenOnClick: Story = {
  args: { api: buildStructureApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(await canvas.findByRole("button", { name: "Expand Hardware" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Cooling" })).not.toBeInTheDocument();
    await expect(canvas.getByText("2 categories")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Expand Hardware" }));
    await expect(await canvas.findByRole("button", { name: "Cooling" })).toBeInTheDocument();
    await expect(canvas.getByText("COOL")).toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Collapse Hardware" }));
    await expect(canvas.queryByRole("button", { name: "Cooling" })).not.toBeInTheDocument();
  },
};

/** A component is not a folder: its row shows the component icon, the same whether it is closed or open, and no folder icon is drawn. */
export const ComponentRowsShowTheComponentIconNotAFolder: Story = {
  args: { api: buildStructureApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const toggle = await canvas.findByRole("button", { name: "Expand Hardware" });
    await expect(toggle.querySelector(".folder-tree-folder-icon svg")).toHaveClass("lucide-boxes");
    await userEvent.click(toggle);
    await expect(canvas.getByRole("button", { name: "Collapse Hardware" }).querySelector(".folder-tree-folder-icon svg")).toHaveClass("lucide-boxes");
    await expect(canvasElement.querySelector(".lucide-folder, .lucide-folder-open")).toBeNull();
  },
};

/** A search opens every component that holds a match and hides the others. */
export const SearchOpensEveryMatch: Story = {
  args: { api: buildStructureApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.type(await canvas.findByRole("textbox", { name: "Search components and categories" }), "perf");
    await expect(await canvas.findByRole("button", { name: "Performance" })).toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Collapse Software" })).toBeInTheDocument();
    await expect(canvas.queryByText("Hardware")).not.toBeInTheDocument();
    await userEvent.clear(canvas.getByRole("textbox", { name: "Search components and categories" }));
    await userEvent.type(canvas.getByRole("textbox", { name: "Search components and categories" }), "zzz");
    await expect(await canvas.findByText("Nothing matches the search.")).toBeInTheDocument();
  },
};

/** An empty open component says so, and a project with no components says that. */
export const EmptyStates: Story = {
  args: { api: buildStructureApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Expand Operations" }));
    await expect(await canvas.findByText("No categories yet.")).toBeInTheDocument();
  },
};

export const ProjectWithNoComponents: Story = {
  args: { api: buildStructureApi({ components: [], categories: [] }) },
  play: async ({ canvasElement }) => {
    await expect(await within(canvasElement).findByText("This project has no components yet.")).toBeInTheDocument();
  },
};

/** Add component: the prefix is suggested from the name, and Save creates it with the suggestion. */
export const AddingAComponentUsesTheSuggestedPrefix: Story = {
  args: { api: buildStructureApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Add component" }));
    const panel = within(await screen.findByRole("dialog", { name: "Add component" }));
    await userEvent.type(panel.getByRole("textbox", { name: "Name" }), "Power Supply");
    await waitFor(() => expect(panel.getByRole("textbox", { name: "Prefix" })).toHaveValue("PS"));
    await userEvent.click(panel.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.api!.createComponent).toHaveBeenCalledWith(STRUCTURE_PROJECT_ID, { name: "Power Supply", prefix: "PS" }));
    await expect(await canvas.findByRole("button", { name: "Expand Power Supply" })).toBeInTheDocument();
    await expect(args.onChanged).toHaveBeenCalled();
  },
};

/** Add category on a component row creates it under that component, and leaves the component open. */
export const AddingACategoryNumbersACollidingPrefix: Story = {
  args: { api: buildStructureApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await openMenu(canvas, "Software");
    await userEvent.click(await screen.findByRole("menuitem", { name: "Add category to Software" }));
    const panel = within(await screen.findByRole("dialog", { name: "Add category to Software" }));
    await userEvent.type(panel.getByRole("textbox", { name: "Name" }), "Perf");
    await waitFor(() => expect(panel.getByRole("textbox", { name: "Prefix" })).toHaveValue("PERF2"));
    await userEvent.click(panel.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.api!.createCategory).toHaveBeenCalledWith(STRUCTURE_PROJECT_ID, "c-sw", { name: "Perf", prefix: "PERF2" }));
    await expect(await canvas.findByRole("button", { name: "Perf" })).toBeInTheDocument();
  },
};

/** A refusal (a prefix already in use) stays in the panel, where the prefix can be changed. */
export const ADuplicatePrefixIsShownInThePanel: Story = {
  args: { api: buildStructureApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Add component" }));
    const panel = within(await screen.findByRole("dialog", { name: "Add component" }));
    await userEvent.type(panel.getByRole("textbox", { name: "Name" }), "Another");
    const prefix = panel.getByRole("textbox", { name: "Prefix" });
    await userEvent.clear(prefix);
    await userEvent.type(prefix, "hw");
    await expect(prefix).toHaveValue("HW");
    await userEvent.click(panel.getByRole("button", { name: "Save" }));
    await expect(await screen.findByText("A component with this prefix already exists.")).toBeInTheDocument();
  },
};

/** Edit opens the same form with the stored name and prefix, which does not follow the name. */
export const EditingKeepsTheStoredPrefix: Story = {
  args: { api: buildStructureApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await openMenu(canvas, "Hardware");
    await userEvent.click(await screen.findByRole("menuitem", { name: "Edit" }));
    const panel = within(await screen.findByRole("dialog", { name: "Edit component Hardware" }));
    await expect(panel.getByRole("textbox", { name: "Prefix" })).toHaveValue("HW");
    const name = panel.getByRole("textbox", { name: "Name" });
    await userEvent.clear(name);
    await userEvent.type(name, "Electronics");
    await expect(panel.getByRole("textbox", { name: "Prefix" })).toHaveValue("HW");
    await userEvent.click(panel.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(args.api!.update).toHaveBeenCalledWith(STRUCTURE_PROJECT_ID, "component", "c-hw", { name: "Electronics", prefix: "HW" }));
  },
};

/** Opening a category row edits it. */
export const OpeningACategoryEditsIt: Story = {
  args: { api: buildStructureApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Expand Hardware" }));
    await userEvent.click(await canvas.findByRole("button", { name: "Cooling" }));
    await expect(await screen.findByRole("dialog", { name: "Edit category Cooling" })).toBeInTheDocument();
  },
};

/** Move up and Move down reorder among siblings; the first and last are unavailable in their direction. */
export const ReorderingComponents: Story = {
  args: { api: buildStructureApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await openMenu(canvas, "Hardware");
    await expect(await screen.findByRole("menuitem", { name: "Move up" })).toBeDisabled();
    await userEvent.click(screen.getByRole("menuitem", { name: "Move down" }));
    await waitFor(() => expect(args.api!.move).toHaveBeenCalledWith(STRUCTURE_PROJECT_ID, "component", "c-hw", "down"));
    await waitFor(() => {
      const names = canvas.getAllByRole("button", { name: /^(Expand|Collapse) / }).map((b) => b.textContent);
      expect(names.indexOf("Software")).toBeLessThan(names.indexOf("Hardware"));
    });
  },
};

/** A component that still has categories cannot be deleted; an empty one is deleted after one confirmation. */
export const DeletingAnEmptyComponentOnly: Story = {
  args: { api: buildStructureApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await openMenu(canvas, "Hardware");
    await expect(await screen.findByRole("menuitem", { name: "Delete" })).toBeDisabled();
    await userEvent.keyboard("{Escape}");
    await openMenu(canvas, "Operations");
    await userEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
    await userEvent.click(await screen.findByRole("button", { name: "Confirm delete" }));
    await waitFor(() => expect(args.api!.remove).toHaveBeenCalledWith(STRUCTURE_PROJECT_ID, "component", "c-ops"));
    await waitFor(() => expect(canvas.queryByText("Operations")).not.toBeInTheDocument());
  },
};

/** A category in use is refused with the counts, then deleted with a replacement the person chooses. */
export const DeletingACategoryInUseOffersAReplacement: Story = {
  args: {
    api: buildStructureApi(undefined, {
      remove: fn(async (_p: string, _k: string, _id: string, reassignTo?: string) => {
        if (!reassignTo) throw new ApiError(409, "This category is still in use (requirements: 2, placed records: 0).");
      }),
    }),
  },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Expand Software" }));
    await openMenu(canvas, "Performance");
    await userEvent.click(await screen.findByRole("menuitem", { name: "Delete" }));
    await userEvent.click(await screen.findByRole("button", { name: "Confirm delete" }));
    const dialog = within(await screen.findByRole("dialog", { name: /Delete .Performance.\?/ }));
    await expect(dialog.getByText(/still in use/)).toBeInTheDocument();
    await userEvent.selectOptions(dialog.getByRole("combobox"), "Hardware / Cooling");
    await userEvent.click(dialog.getByRole("button", { name: "Confirm delete" }));
    await waitFor(() => expect(args.api!.remove).toHaveBeenLastCalledWith(STRUCTURE_PROJECT_ID, "category", "k-perf", "k-cool"));
  },
};

/** Move to another component names how many requirements go with the category and what happens to their codes. */
export const MovingACategoryToAnotherComponent: Story = {
  args: { api: buildStructureApi() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Expand Software" }));
    await openMenu(canvas, "Performance");
    await userEvent.click(await screen.findByRole("menuitem", { name: "Move to another component…" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Move Performance to another component" }));
    await expect(dialog.getByText(/The 2 requirements in Performance move with it/)).toBeInTheDocument();
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: /New component/ }), "Hardware (HW)");
    await userEvent.click(dialog.getByRole("button", { name: "Move" }));
    await waitFor(() => expect(args.api!.moveCategoryTo).toHaveBeenCalledWith(STRUCTURE_PROJECT_ID, "k-perf", "c-hw"));
    await expect(await canvas.findByRole("button", { name: "Collapse Hardware" })).toBeInTheDocument();
    await expect(await canvas.findByRole("button", { name: "Performance" })).toBeInTheDocument();
  },
};

/** A move the server refuses (the prefix is already used there) is shown in the dialog. */
export const AMoveClashIsShownInTheDialog: Story = {
  args: {
    api: buildStructureApi({
      ...buildStructureTree(),
      categories: [...buildStructureTree().categories, { id: "k-perf-hw", project_id: STRUCTURE_PROJECT_ID, component_id: "c-hw", name: "Perf", prefix: "PERF", sort_order: 2 }],
    }),
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Expand Software" }));
    await openMenu(canvas, "Performance");
    await userEvent.click(await screen.findByRole("menuitem", { name: "Move to another component…" }));
    const dialog = within(await screen.findByRole("dialog", { name: "Move Performance to another component" }));
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: /New component/ }), "Hardware (HW)");
    await userEvent.click(dialog.getByRole("button", { name: "Move" }));
    await expect(await dialog.findByText("A category with this prefix already exists under this component.")).toBeInTheDocument();
  },
};

/** With one component there is nowhere to move a category to. */
export const MoveToIsUnavailableWithOneComponent: Story = {
  args: { api: buildStructureApi({ components: buildStructureTree().components.slice(0, 1), categories: buildStructureTree().categories.slice(0, 2) }) },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(await canvas.findByRole("button", { name: "Expand Hardware" }));
    await openMenu(canvas, "Cooling");
    await expect(await screen.findByRole("menuitem", { name: "Move to another component…" })).toBeDisabled();
  },
};

/** The tree is a keyboard tree grid: Down moves between rows and Right opens a component. */
export const KeyboardOpensAndMoves: Story = {
  args: { api: buildStructureApi() },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const first = (await canvas.findByRole("button", { name: "Expand Hardware" })).closest<HTMLElement>("[data-ftl-row]")!;
    first.focus();
    await userEvent.keyboard("{ArrowRight}");
    await expect(await canvas.findByRole("button", { name: "Cooling" })).toBeInTheDocument();
    await userEvent.keyboard("{ArrowDown}");
    await expect(canvas.getByRole("button", { name: "Cooling" }).closest("[data-ftl-row]")).toHaveFocus();
  },
};
