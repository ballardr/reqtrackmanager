import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, screen, userEvent, within } from "storybook/test";

import { DirectoryTable, type DirectoryColumn } from "../components/DirectoryTable";
import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { useOptionalColumns } from "./useOptionalColumns";

interface Diagram { name: string; kind: string; toggles: number | null }
const ROWS: Diagram[] = [{ name: "Order flow", kind: "Block", toggles: 4 }, { name: "Context", kind: "Layered", toggles: null }];

const COLUMNS: DirectoryColumn<Diagram>[] = [
  { key: "name", label: "Name", minWidth: "12rem", render: (d) => d.name },
  { key: "kind", label: "Kind", optional: true, render: (d) => d.kind },
  { key: "toggles", label: "Switches", optional: true, defaultHidden: true, render: (d) => d.toggles ?? "—" },
];

/** A list that offers its columns through the hook: the table draws what the hook returns and the chooser sits beside it. */
function Host({ listKey = "story_diagrams", columns = COLUMNS }: { listKey?: string; columns?: DirectoryColumn<Diagram>[] }) {
  const shown = useOptionalColumns(listKey, columns);
  return (
    <div className="stack">
      <div className="row">{shown.chooser}</div>
      <DirectoryTable ariaLabel="Diagrams" columns={shown.columns} rows={ROWS} rowKey={(d) => d.name} emptyState={null} />
    </div>
  );
}

/**
 * `useOptionalColumns` returns the columns to draw and the shared column chooser. A column that is not optional is
 * always drawn; an optional one follows the person's remembered choice, or the list's defaults until they choose.
 */
const meta: Meta<typeof Host> = {
  title: "Hooks/useOptionalColumns",
  component: Host,
  decorators: [withStatefulAuth(buildUser())],
};
export default meta;

type Story = StoryObj<typeof Host>;

/** A column marked `defaultHidden` is absent until chosen, and the reset puts it away again. */
export const HiddenByDefaultUntilChosen: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("columnheader", { name: "Kind" })).toBeInTheDocument();
    await expect(canvas.queryByRole("columnheader", { name: "Switches" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "Choose columns" }));
    const dialog = await screen.findByRole("dialog", { name: "Columns" });
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Switches" }));
    await expect(canvas.getByRole("columnheader", { name: "Switches" })).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Show the default columns" }));
    await expect(canvas.queryByRole("columnheader", { name: "Switches" })).not.toBeInTheDocument();
  },
};

/** A stored choice naming a column that no longer exists is ignored, and a column added since is off unless it is a default. */
export const StoredChoiceIgnoresRemovedAndNewColumns: Story = {
  decorators: [withStatefulAuth(buildUser({ ui_preferences: { column_choice_story_stored: ["removed_column", "kind"] } }))],
  args: { listKey: "story_stored" },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("columnheader", { name: "Kind" })).toBeInTheDocument();
    await expect(canvas.queryByRole("columnheader", { name: "Switches" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("columnheader", { name: "removed_column" })).not.toBeInTheDocument();
  },
};

/** One optional column that is on by default leaves nothing to choose, so the list shows no chooser. */
export const NoChooserForOneOptionalColumnOnByDefault: Story = {
  args: { columns: COLUMNS.slice(0, 2) },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).queryByRole("button", { name: "Choose columns" })).not.toBeInTheDocument();
  },
};

/** A list whose only optional column is off by default still offers the chooser, or that column could never be shown. */
export const ChooserForALoneColumnOffByDefault: Story = {
  args: { columns: [COLUMNS[0], COLUMNS[2]] },
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByRole("button", { name: "Choose columns" })).toBeInTheDocument();
  },
};
