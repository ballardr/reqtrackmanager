import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, userEvent, within } from "storybook/test";

import type { ComplianceStandard } from "./types";
import { StandardFormModal } from "./StandardFormModal";

function standard(overrides: Partial<ComplianceStandard> = {}): ComplianceStandard {
  return {
    id: "std-1", organization_id: "org-1", reference: "ISO-27001", name: "ISO 27001",
    description: "Information security management.", issuing_organisation: "ISO", owner_id: "user-1",
    creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null, applicability_default: "opt_in",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...overrides,
  };
}

/**
 * `StandardFormModal` — extracted from `StandardsPanel.tsx` (docs/compliance
 * -module-plan.md Phase 18) so both `StandardListPage.tsx` (create, with an
 * optional multi-org picker) and `StandardWorkspacePage.tsx` (edit, single
 * fixed org) share one dialog rather than each keeping its own copy.
 */
const meta: Meta<typeof StandardFormModal> = {
  title: "Modules/Compliance/StandardFormModal",
  component: StandardFormModal,
  args: { onCancel: fn(), onSave: fn() },
};
export default meta;

type Story = StoryObj<typeof StandardFormModal>;

export const CreateSingleOrg: Story = {
  args: { orgs: [{ id: "org-1", name: "Acme Corp" }] },
  play: async ({ canvasElement, args }) => {
    const body = within(document.body);
    // A single candidate org renders no picker at all.
    await expect(body.queryByLabelText("Organisation")).not.toBeInTheDocument();

    await userEvent.type(body.getByLabelText("Standard reference"), "NIST-CSF");
    await userEvent.type(body.getByLabelText("Standard name"), "NIST Cybersecurity Framework");
    await userEvent.type(body.getByLabelText("Initial version label"), "1.0");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await expect(args.onSave).toHaveBeenCalledWith(
      expect.objectContaining({ reference: "NIST-CSF", name: "NIST Cybersecurity Framework", initial_version_label: "1.0" }),
      "org-1"
    );
    void canvasElement;
  },
};

export const CreateMultiOrgShowsPicker: Story = {
  args: { orgs: [{ id: "org-1", name: "Acme Corp" }, { id: "org-2", name: "Beta Industries" }] },
  play: async () => {
    const body = within(document.body);
    const picker = body.getByLabelText("Organisation") as HTMLSelectElement;
    await expect(picker).toBeInTheDocument();
    await expect(picker.value).toBe("org-1");

    await userEvent.selectOptions(picker, "org-2");
    await userEvent.type(body.getByLabelText("Standard reference"), "SOC2");
    await userEvent.type(body.getByLabelText("Standard name"), "SOC 2 Type II");
    await userEvent.type(body.getByLabelText("Initial version label"), "1.0");
    await expect(body.getByRole("button", { name: "Save" })).not.toBeDisabled();
  },
};

export const EditModeHidesReferenceAndVersionFields: Story = {
  args: { initial: standard(), orgId: "org-1" },
  play: async () => {
    const body = within(document.body);
    await expect(body.getByRole("heading", { name: "Edit standard" })).toBeInTheDocument();
    await expect(body.queryByLabelText("Standard reference")).not.toBeInTheDocument();
    await expect(body.queryByLabelText("Initial version label")).not.toBeInTheDocument();
    await expect(body.getByLabelText("Standard name")).toHaveValue("ISO 27001");
  },
};

export const ShowsInlineError: Story = {
  args: { orgs: [{ id: "org-1", name: "Acme Corp" }], error: "A standard with this reference already exists." },
  play: async () => {
    const body = within(document.body);
    await expect(body.getByText("A standard with this reference already exists.")).toBeInTheDocument();
  },
};
