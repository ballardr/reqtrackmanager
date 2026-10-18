import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { ActionMenu } from "./ActionMenu";
import { useArchiveAction, useConfirmedAction } from "./useConfirmedAction";

function Harness({
  archived,
  onArchive,
  onErase,
}: {
  archived: boolean;
  onArchive: () => void;
  onErase: () => void;
}) {
  const archive = useArchiveAction({
    noun: "Persona", isArchived: archived, archiveBody: "It leaves the active list.", onToggle: onArchive,
  });
  const erase = useConfirmedAction({
    label: "Delete permanently", danger: true, title: "Permanently delete Ada?", message: "This cannot be undone.",
    requireTypedText: "Ada", onConfirm: onErase,
  });
  const hidden = useConfirmedAction({
    label: "Hidden", hidden: true, title: "x", message: "x", onConfirm: () => undefined,
  });
  const items = [archive.item, erase.item, hidden.item].filter((i) => i !== null);
  return (
    <>
      <ActionMenu triggerLabel="Persona actions" items={items} />
      {archive.dialog}
      {erase.dialog}
    </>
  );
}

const meta: Meta<typeof Harness> = {
  title: "Components/useConfirmedAction",
  component: Harness,
  args: { archived: false, onArchive: fn(), onErase: fn() },
};
export default meta;
type Story = StoryObj<typeof Harness>;

const body = () => within(document.body);

export const ArchiveConfirmsThenRuns: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Persona actions" }));
    await expect(body().queryByRole("menuitem", { name: "Hidden" })).not.toBeInTheDocument();
    await userEvent.click(body().getByRole("menuitem", { name: "Archive" }));
    await userEvent.click(within(body().getByRole("dialog", { name: "Archive this Persona?" })).getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(args.onArchive).toHaveBeenCalled());
  },
};

export const ArchivedOffersUnarchive: Story = {
  args: { archived: true },
  play: async ({ canvasElement }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Persona actions" }));
    await expect(body().getByRole("menuitem", { name: "Unarchive" })).toBeInTheDocument();
  },
};

export const DeleteNeedsTheTypedName: Story = {
  play: async ({ canvasElement, args }) => {
    await userEvent.click(within(canvasElement).getByRole("button", { name: "Persona actions" }));
    await userEvent.click(body().getByRole("menuitem", { name: "Delete permanently" }));
    const dialog = within(body().getByRole("dialog", { name: "Permanently delete Ada?" }));
    const confirm = dialog.getByRole("button", { name: "Delete permanently" });
    await expect(confirm).toBeDisabled();
    await userEvent.type(dialog.getByRole("textbox"), "Ada");
    await userEvent.click(confirm);
    await waitFor(() => expect(args.onErase).toHaveBeenCalled());
  },
};
