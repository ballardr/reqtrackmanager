import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, waitFor, within } from "storybook/test";

import { DeleteInUseDialog } from "./DeleteInUseDialog";

const meta: Meta<typeof DeleteInUseDialog> = {
  title: "Components/DeleteInUseDialog",
  component: DeleteInUseDialog,
  args: {
    title: "Delete “Depends on”?",
    summary: "This link type is used by 12 link(s).",
    candidates: [
      { id: "related", label: "Related to" },
      { id: "derives", label: "Derives from", warning: "Its direction differs, so this changes what the moved links mean." },
      { id: "dec", label: "Addresses", disabledReason: "It cannot start from a requirement, which some links do." },
    ],
    onMove: fn(async () => {}),
    onClose: fn(),
  },
};
export default meta;

type Story = StoryObj<typeof DeleteInUseDialog>;

const body = () => within(document.body);

/** Move what uses the item to another one: confirm stays disabled until a
 * replacement is chosen, and a candidate that cannot take everything is shown
 * disabled with its reason rather than left out. */
export const MoveToAnotherItem: Story = {
  play: async ({ args }) => {
    const dialog = within(await body().findByRole("dialog", { name: "Delete “Depends on”?" }));
    await expect(dialog.getByText("This link type is used by 12 link(s).")).toBeInTheDocument();
    const confirm = dialog.getByRole("button", { name: "Confirm delete" });
    await expect(confirm).toBeDisabled();

    const select = dialog.getByRole("combobox", { name: "Reassign existing items to" });
    const blocked = dialog.getByRole("option", { name: /Addresses \(cannot be used: It cannot start from a requirement/ });
    await expect(blocked).toBeDisabled();

    await userEvent.selectOptions(select, "Related to");
    await expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    await waitFor(() => expect(args.onMove).toHaveBeenCalledWith("related"));
    await waitFor(() => expect(args.onClose).toHaveBeenCalled());
  },
};

/** A candidate with a caution (here a different direction) shows it as soon as it is chosen. */
export const CautionShownForChosenCandidate: Story = {
  play: async () => {
    const dialog = within(await body().findByRole("dialog"));
    await expect(dialog.queryByRole("status")).not.toBeInTheDocument();
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Reassign existing items to" }), "Derives from");
    await expect(dialog.getByRole("status")).toHaveTextContent("changes what the moved links mean");
  },
};

/** Usage facts are listed under the summary. */
export const ShowsUsageDetails: Story = {
  args: {
    details: ["2 pending change request(s) propose this link type.", "It is named in the link rule of: Requirement."],
  },
  play: async () => {
    const dialog = within(await body().findByRole("dialog"));
    await expect(dialog.getByRole("list")).toHaveTextContent("2 pending change request(s)");
    await expect(dialog.getByRole("list")).toHaveTextContent("link rule of: Requirement");
  },
};

/** With nothing to move to, the dialog says so instead of showing an empty picker. */
export const NoCandidates: Story = {
  args: { candidates: [] },
  play: async () => {
    const dialog = within(await body().findByRole("dialog"));
    await expect(dialog.getByText("There is nothing to move them to — create another first.")).toBeInTheDocument();
    await expect(dialog.queryByRole("combobox")).not.toBeInTheDocument();
  },
};

/** A failed move keeps the dialog open with the error, so nothing is lost. */
export const FailedMoveStaysOpenWithError: Story = {
  args: { onMove: fn(async () => { throw new Error("Related to cannot take these links."); }) },
  play: async ({ args }) => {
    const dialog = within(await body().findByRole("dialog"));
    await userEvent.selectOptions(dialog.getByRole("combobox", { name: "Reassign existing items to" }), "Related to");
    await userEvent.click(dialog.getByRole("button", { name: "Confirm delete" }));
    await expect(await dialog.findByRole("alert")).toHaveTextContent("Related to cannot take these links.");
    await expect(args.onClose).not.toHaveBeenCalled();
  },
};

const remove = {
  description: "Permanently deletes 12 link(s), then the link type.",
  confirmText: "Depends on",
  confirmMessage: "This permanently deletes the “Depends on” link type and its 12 link(s). This cannot be undone.",
  confirmLabel: "Delete links and link type",
};

/** Deleting what uses the item too is Tier 2: the exact name must be typed
 * before the destructive button enables. */
export const RemoveIsTier2TypeTheName: Story = {
  args: { remove: { ...remove, onRemove: fn(async () => {}) } },
  play: async ({ args }) => {
    const dialog = within(await body().findByRole("dialog", { name: "Delete “Depends on”?" }));
    await userEvent.click(dialog.getByRole("button", { name: "Delete the links too…" }));

    const confirm = within(document.body).getByRole("button", { name: "Delete links and link type" });
    await expect(confirm).toBeDisabled();
    await userEvent.type(within(document.body).getByLabelText('Type "Depends on" to confirm'), "Depends on");
    await expect(confirm).toBeEnabled();
    await userEvent.click(confirm);
    const onRemove = (args.remove as { onRemove: () => Promise<void> }).onRemove;
    await waitFor(() => expect(onRemove).toHaveBeenCalled());
  },
};

/** When removal is blocked (here by pending change requests), the button is
 * disabled and the reason is stated beside it. */
export const RemoveBlockedExplainsWhy: Story = {
  args: { remove: { ...remove, blockedReason: "2 pending change request(s) propose this link type.", onRemove: fn(async () => {}) } },
  play: async () => {
    const dialog = within(await body().findByRole("dialog"));
    await expect(dialog.getByRole("button", { name: "Delete the links too…" })).toBeDisabled();
    await expect(dialog.getByText(/Not available: 2 pending change request/)).toBeInTheDocument();
  },
};
