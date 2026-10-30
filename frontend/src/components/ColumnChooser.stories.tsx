import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, screen, userEvent, within } from "storybook/test";

import { useColumnChoice } from "../hooks/useColumnChoice";
import { buildUser, withStatefulAuth } from "../testing/storybook-helpers";
import { ColumnChooser } from "./ColumnChooser";

const COLUMNS = [
  { id: "version", label: "Version" },
  { id: "kind", label: "Type" },
  { id: "updated", label: "Last changed" },
];
const IDS = COLUMNS.map((c) => c.id);
const DEFAULTS = ["updated"];

/** Hosts the chooser with the real preference hook and shows the columns it leaves on. */
function Host() {
  const choice = useColumnChoice("story_list", IDS, DEFAULTS);
  return (
    <div className="row">
      <ColumnChooser columns={COLUMNS} visible={choice.visible} onToggle={choice.toggle} onReset={choice.reset} isDefault={choice.isDefault} alwaysOn="Name" />
      <span data-testid="shown">{choice.visible.join(",")}</span>
    </div>
  );
}

/**
 * The one control for choosing a list's optional columns: a popover of checkboxes with the Name column locked on and
 * a reset to the defaults. The choice is remembered per person in `ui_preferences`.
 */
const meta: Meta<typeof Host> = {
  title: "Components/ColumnChooser",
  component: Host,
  decorators: [withStatefulAuth(buildUser())],
};
export default meta;

type Story = StoryObj<typeof Host>;

/** Only the default columns show, and the always-on column is ticked and locked. */
export const DefaultsAndLockedName: Story = {
  play: async ({ canvasElement }) => {
    await expect(within(canvasElement).getByTestId("shown")).toHaveTextContent("updated");
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Choose columns" }));
    const dialog = await screen.findByRole("dialog", { name: "Columns" });
    const name = within(dialog).getByRole("checkbox", { name: "Name" });
    await expect(name).toBeChecked();
    await expect(name).toBeDisabled();
    await expect(within(dialog).getByRole("checkbox", { name: "Last changed" })).toBeChecked();
    await expect(within(dialog).getByRole("checkbox", { name: "Version" })).not.toBeChecked();
    await expect(within(dialog).getByRole("button", { name: "Show the default columns" })).toBeDisabled();
  },
};

/** Ticking a column shows it, marks the button as changed, and the reset returns to the defaults. */
export const TickAndReset: Story = {
  play: async ({ canvasElement }) => {
    const button = within(canvasElement).getByRole("button", { name: "Choose columns" });
    await userEvent.click(button);
    const dialog = await screen.findByRole("dialog", { name: "Columns" });
    await userEvent.click(within(dialog).getByRole("checkbox", { name: "Version" }));
    await expect(within(canvasElement).getByTestId("shown")).toHaveTextContent("version,updated");
    await expect(button).toHaveClass("btn-marked");
    await userEvent.click(within(dialog).getByRole("button", { name: "Show the default columns" }));
    await expect(within(canvasElement).getByTestId("shown")).toHaveTextContent(/^updated$/);
    await expect(button).not.toHaveClass("btn-marked");
  },
};
