import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api, ApiError } from "../../api/client";
import { StandardImportModal } from "./StandardImportModal";
import type { ComplianceStandard, StandardImportResult } from "./types";

function standard(overrides: Partial<ComplianceStandard> = {}): ComplianceStandard {
  return {
    id: "std-2", organization_id: "org-1", reference: "SOC2", name: "SOC 2 Type II",
    description: "", issuing_organisation: null, owner_id: "user-1", creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null, applicability_default: "opt_in",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...overrides,
  };
}

function exportFile(): File {
  return new File([JSON.stringify({ format: "reqtrackmanager.compliance_standard.v1" })], "SOC2-export.json", {
    type: "application/json",
  });
}

/**
 * `StandardImportModal` (docs/compliance-module-plan.md Phase 21) — the
 * "Import standard" dialog reached from `StandardListPage.tsx`'s "New
 * standard" split-button trigger. Mirrors `StandardFormModal.stories.tsx`'s
 * org-picker coverage one level down, plus the 409-conflict retry flow this
 * dialog owns that `StandardFormModal` has no equivalent of.
 */
const meta: Meta<typeof StandardImportModal> = {
  title: "Modules/Compliance/StandardImportModal",
  component: StandardImportModal,
  args: { onCancel: fn(), onImported: fn() },
};
export default meta;

type Story = StoryObj<typeof StandardImportModal>;

export const SingleOrgImports: Story = {
  args: { orgId: "org-1" },
  play: async ({ args }) => {
    spyOn(api, "postFile").mockResolvedValue(
      { standard: standard(), skipped: false, warnings: [] } satisfies StandardImportResult
    );
    const body = within(document.body);
    // A single candidate org renders no picker at all.
    await expect(body.queryByLabelText("Organisation")).not.toBeInTheDocument();

    await userEvent.upload(body.getByLabelText("Standard export file") as HTMLInputElement, exportFile());
    await userEvent.click(body.getByRole("button", { name: "Import" }));

    await waitFor(() =>
      expect(args.onImported).toHaveBeenCalledWith(
        expect.objectContaining({ skipped: false, standard: expect.objectContaining({ reference: "SOC2" }) })
      )
    );
  },
};

export const MultiOrgShowsPickerAndDisablesUntilFileChosen: Story = {
  args: { orgs: [{ id: "org-1", name: "Acme Corp" }, { id: "org-2", name: "Beta Industries" }] },
  play: async () => {
    const body = within(document.body);
    const picker = body.getByLabelText("Organisation") as HTMLSelectElement;
    await expect(picker).toBeInTheDocument();
    await expect(picker.value).toBe("");
    await expect(body.getByRole("button", { name: "Import" })).toBeDisabled();
  },
};

export const ReferenceConflictOffersSkipOrCopy: Story = {
  args: { orgId: "org-1" },
  play: async ({ args }) => {
    let attempts = 0;
    spyOn(api, "postFile").mockImplementation(async () => {
      attempts += 1;
      if (attempts === 1) {
        throw new ApiError(
          409,
          "A standard with reference 'SOC2' already exists in this organisation. "
            + "Choose whether to skip this import or import it as a copy."
        );
      }
      return { standard: null, skipped: true, warnings: [] } satisfies StandardImportResult;
    });
    const body = within(document.body);
    await userEvent.upload(body.getByLabelText("Standard export file") as HTMLInputElement, exportFile());
    await userEvent.click(body.getByRole("button", { name: "Import" }));

    await expect(body.getByText(/already exists in this organisation/)).toBeInTheDocument();
    // The plain "Import" action is replaced by the two conflict choices while unresolved.
    await expect(body.queryByRole("button", { name: "Import" })).not.toBeInTheDocument();

    await userEvent.click(body.getByRole("button", { name: "Skip import" }));
    await waitFor(() => expect(args.onImported).toHaveBeenCalledWith(expect.objectContaining({ skipped: true })));
  },
};
