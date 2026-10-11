import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../api/client";
import type { ProposedLinkPreviewRow } from "../api/types";
import { buildProposedLink, withToast } from "../testing/storybook-helpers";
import { ApproveChangeRequestDialog } from "./ApproveChangeRequestDialog";

const PROJECT = "project-1";
const CR = "cr-1";

const ROWS: ProposedLinkPreviewRow[] = [
  { link: buildProposedLink({ id: "a" }), selectable: true, already_linked: false, reason: null },
  {
    link: buildProposedLink({ id: "b", other_label: "Audit log retention", other_type: "decision", other_type_label: "Decision" }),
    selectable: true, already_linked: false, reason: null,
  },
];
const INVALID: ProposedLinkPreviewRow = {
  link: buildProposedLink({ id: "c", other_label: "AUTH-003 — Lockout after five failures" }),
  selectable: false, already_linked: true, reason: "These records are already linked this way.",
};
const HIDDEN: ProposedLinkPreviewRow = {
  link: buildProposedLink({ id: "d", other_label: null, other_type_label: "Decision" }),
  selectable: false, already_linked: false, reason: "You cannot view the linked record, so you cannot merge this link.",
};

function mockPreview(rows: ProposedLinkPreviewRow[]) {
  spyOn(api, "get").mockResolvedValue({ rows });
  spyOn(api, "post").mockResolvedValue({});
}

/**
 * The approver's dialog for a change request that proposes links
 * (docs/plans/platform-enhancements-2026-10-plan.md Phase 6b): every valid link ticked by default,
 * an invalid one disabled with its reason, and a primary button that says what approving will do.
 */
const meta: Meta<typeof ApproveChangeRequestDialog> = {
  title: "Components/ApproveChangeRequestDialog",
  component: ApproveChangeRequestDialog,
  decorators: [withToast()],
  args: { projectId: PROJECT, crId: CR, kind: "modify_requirement", note: "Looks right", onApproved: fn(), onClose: fn() },
};
export default meta;

type Story = StoryObj<typeof ApproveChangeRequestDialog>;

const dialogOf = async () => within(await within(document.body).findByRole("dialog", { name: "Approve change request" }));

export const AllValidLinksTickedByDefault: Story = {
  beforeEach: () => mockPreview(ROWS),
  play: async ({ args }) => {
    const dialog = await dialogOf();
    await expect(await dialog.findByRole("checkbox", { name: /Merge link: Depends on AUTH-002/ })).toBeChecked();
    await expect(dialog.getByRole("checkbox", { name: /Merge link: Depends on Audit log retention/ })).toBeChecked();
    await userEvent.click(dialog.getByRole("button", { name: "Approve and merge 2 links" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(
        `/api/v1/projects/${PROJECT}/change-requests/${CR}/decide`,
        expect.objectContaining({ approve: true, note: "Looks right", merge_link_ids: ["a", "b"] }),
      ),
    );
    await waitFor(() => expect(args.onApproved).toHaveBeenCalled());
  },
};

export const SelectNoneThenApproveWithoutLinks: Story = {
  beforeEach: () => mockPreview(ROWS),
  play: async () => {
    const dialog = await dialogOf();
    await userEvent.click(await dialog.findByRole("button", { name: "Select none" }));
    await expect(dialog.getByRole("checkbox", { name: /Merge link: Depends on AUTH-002/ })).not.toBeChecked();
    await userEvent.click(dialog.getByRole("button", { name: "Approve without links" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(expect.stringContaining("/decide"), expect.objectContaining({ merge_link_ids: [] })),
    );
  },
};

export const InvalidLinksAreDisabledWithTheirReason: Story = {
  beforeEach: () => mockPreview([...ROWS, INVALID, HIDDEN]),
  play: async () => {
    const dialog = await dialogOf();
    await dialog.findByRole("checkbox", { name: /Merge link: Depends on AUTH-002/ });
    await expect(dialog.getByRole("checkbox", { name: /Merge link: Depends on AUTH-003/ })).toBeDisabled();
    await expect(dialog.getByText("Already linked, will be skipped")).toBeInTheDocument();
    // A record the approver cannot see is a neutral placeholder, with the reason.
    await expect(dialog.getByText("A record you cannot see")).toBeInTheDocument();
    await expect(dialog.getByText(/you cannot merge this link/)).toBeInTheDocument();
    await expect(dialog.getByRole("button", { name: "Approve and merge 2 links" })).toBeInTheDocument();
  },
};

export const NoLinkIsValid: Story = {
  beforeEach: () => mockPreview([INVALID, HIDDEN]),
  play: async () => {
    const dialog = await dialogOf();
    await expect(await dialog.findByRole("button", { name: "Approve without links" })).toBeEnabled();
    await expect(dialog.getByRole("button", { name: "Select all" })).toBeDisabled();
  },
};

/** An add-link request with nothing ticked applies nothing, which the dialog says. */
export const AddLinkRequestWithNothingTickedPointsToReject: Story = {
  args: { kind: "add_link" },
  beforeEach: () => mockPreview([INVALID]),
  play: async () => {
    const dialog = await dialogOf();
    await expect(await dialog.findByText(/approving it changes nothing/)).toBeInTheDocument();
    await expect(dialog.getByText(/Use Reject to decline it/)).toBeInTheDocument();
  },
};

/** If a ticked link became invalid since the preview, the server answers 409 with a fresh preview:
 * the dialog shows it, drops that tick and asks for confirmation again. */
export const AStaleSelectionShowsTheFreshPreview: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockResolvedValue({ rows: ROWS });
    spyOn(api, "post").mockRejectedValue(
      new ApiError(409, "Some of the links you chose can no longer be merged.", {
        message: "Some of the links you chose can no longer be merged.",
        preview: { rows: [{ ...ROWS[0], selectable: false, already_linked: true, reason: "These records are already linked this way." }, ROWS[1]] },
      }),
    );
  },
  play: async () => {
    const dialog = await dialogOf();
    await userEvent.click(await dialog.findByRole("button", { name: "Approve and merge 2 links" }));
    await expect(await dialog.findByText(/The list was updated/)).toBeInTheDocument();
    await expect(dialog.getByRole("checkbox", { name: /Merge link: Depends on AUTH-002/ })).toBeDisabled();
    await expect(dialog.getByRole("checkbox", { name: /Merge link: Depends on Audit log retention/ })).toBeChecked();
    await expect(dialog.getByRole("button", { name: "Approve and merge 1 link" })).toBeInTheDocument();
  },
};

export const SendsTheClearCompletionFlag: Story = {
  args: { clearCompletion: true },
  beforeEach: () => mockPreview(ROWS),
  play: async () => {
    const dialog = await dialogOf();
    await userEvent.click(await dialog.findByRole("button", { name: "Approve and merge 2 links" }));
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith(expect.stringContaining("/decide"), expect.objectContaining({ clear_completion: true })),
    );
  },
};
