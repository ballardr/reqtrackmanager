import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";
import { MemoryRouter } from "react-router-dom";

import { withToast } from "../../testing/storybook-helpers";
import { RepresentationPanel } from "./RepresentationPanel";
import type { RepresentedLink } from "./types";

const LINKS: RepresentedLink[] = [
  { link_id: "l1", id: "persona-1", name: "Field Technician", scope: "project" },
  { link_id: "l2", id: "persona-2", name: "Safety Officer", scope: "organization" },
];

const meta: Meta<typeof RepresentationPanel> = {
  title: "Modules/Stakeholders/RepresentationPanel",
  component: RepresentationPanel,
  decorators: [
    withToast(),
    (Story) => (
      <MemoryRouter>
        <Story />
      </MemoryRouter>
    ),
  ],
  args: {
    heading: "Represents these Personas", emptyText: "Nothing linked yet.",
    load: fn(async () => LINKS), linkFor: (l: RepresentedLink) => `/personas/${l.id}`,
  },
};
export default meta;

type Story = StoryObj<typeof RepresentationPanel>;

export const ReadOnlyListLinksToEachRecord: Story = {
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Field Technician" })).toHaveAttribute("href", "/personas/persona-1"));
    await expect(canvas.getByRole("link", { name: "Safety Officer" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: /Remove/ })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Add" })).not.toBeInTheDocument();
  },
};

export const EmptyState: Story = {
  args: { load: fn(async () => []) },
  play: async ({ canvasElement }) => {
    await waitFor(() => expect(within(canvasElement).getByText("Nothing linked yet.")).toBeInTheDocument());
  },
};

/** The panel renders nothing when its list can't be loaded (e.g. the other sub-component is switched off). */
export const HidesItselfWhenTheListCannotLoad: Story = {
  args: { load: fn(async () => { throw new Error("404"); }) },
  play: async ({ canvasElement, args }) => {
    await waitFor(() => expect(args.load).toHaveBeenCalled());
    await expect(within(canvasElement).queryByText("Represents these Personas")).not.toBeInTheDocument();
  },
};

const editable = (onAdd = fn(async () => undefined), onRemove = fn(async () => undefined)) => ({
  options: [
    { value: "persona-1", label: "Field Technician" },
    { value: "persona-3", label: "Control Room Operator" },
  ],
  pickerLabel: "Persona to represent", onAdd, onRemove,
});

export const AddOffersOnlyUnlinkedCandidates: Story = {
  args: { edit: editable() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("combobox", { name: "Persona to represent" }));
    await expect(canvas.getByRole("button", { name: "Add" })).toBeDisabled();
    // Already-linked Field Technician is not offered again.
    await expect(canvas.queryByRole("option", { name: "Field Technician" })).not.toBeInTheDocument();
    await userEvent.selectOptions(canvas.getByRole("combobox", { name: "Persona to represent" }), "persona-3");
    await userEvent.click(canvas.getByRole("button", { name: "Add" }));
    await waitFor(() => expect(args.edit?.onAdd).toHaveBeenCalledWith("persona-3"));
    await waitFor(() => expect(canvas.getByRole("combobox", { name: "Persona to represent" })).toHaveValue(""));
  },
};

export const RemoveAsksForConfirmation: Story = {
  args: { edit: editable() },
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await waitFor(() => canvas.getByRole("button", { name: "Remove Field Technician" }));
    await userEvent.click(canvas.getByRole("button", { name: "Remove Field Technician" }));
    const dialog = within(within(document.body).getByRole("dialog", { name: "Remove Field Technician?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Remove" }));
    await waitFor(() => expect(args.edit?.onRemove).toHaveBeenCalledWith(LINKS[0]));
  },
};

export const DarkTheme: Story = { ...ReadOnlyListLinksToEachRecord, globals: { theme: "dark" } };
