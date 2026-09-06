import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { ApiError, api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { StandardsPanel } from "./StandardsPanel";
import type { ComplianceActionType, ComplianceStandard, ComplianceStandardVersion } from "./types";

const ORG_ID = "org-1";
const ACTION_TYPES: ComplianceActionType[] = [{ id: "at-1", organization_id: ORG_ID, name: "Review", sort_order: 0 }];

function standard(overrides: Partial<ComplianceStandard> = {}): ComplianceStandard {
  return {
    id: "std-1", organization_id: ORG_ID, reference: "ISO-27001", name: "ISO 27001",
    description: "Information security management.", issuing_organisation: "ISO", owner_id: "user-1",
    creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...overrides,
  };
}

function version(overrides: Partial<ComplianceStandardVersion> = {}): ComplianceStandardVersion {
  return {
    id: "ver-1", standard_id: "std-1", version_number: 1, version_label: "v1.0", status: "draft",
    effective_date: null, change_note: "", created_by: "user-1", published_at: null, published_by: null,
    retired_at: null, retired_by: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

/**
 * `StandardsPanel` is the largest of the compliance module's org-admin
 * panels — the standards directory/search, create `Modal`, detail
 * `SidePanel` (edit, archive/unarchive, version list), and the "New
 * version" `Modal`. It also drills into `VersionWorkspace` when a version
 * is selected; that transition is this panel's own responsibility (it owns
 * the `selected`/`activeVersion` state that decides which one renders), so
 * one story here proves the drill-in actually happens — but
 * `VersionWorkspace`'s own publish/retire/diff/requirement-tree behaviour
 * is exercised in `VersionWorkspace.stories.tsx`, not duplicated here.
 *
 * Requirements/required-action fetches triggered by the nested
 * `VersionWorkspace` -> `RequirementTree` are mocked to resolve empty so
 * that drill-in story settles cleanly, matching how `ComplianceAdminPanel
 * .stories.tsx`'s own `StandardDetailAndVersionWorkspace` story does the
 * same thing.
 */
function mockStandardsApis(overrides: {
  standards?: ComplianceStandard[];
  versions?: ComplianceStandardVersion[];
} = {}) {
  let standards = overrides.standards ?? [standard()];
  const versions = overrides.versions ?? [version()];

  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/requirements") && !path.includes("required-actions")) return [];
    if (path.includes("/required-actions")) return [];
    if (path.includes("/versions")) return versions;
    if (path.includes("/standards?")) return standards;
    throw new Error(`unmocked GET: ${path}`);
  });
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/standards")) {
      const payload = body as { reference: string; name: string; description?: string; issuing_organisation?: string | null };
      const created = standard({
        id: "std-new", reference: payload.reference, name: payload.name,
        description: payload.description ?? "", issuing_organisation: payload.issuing_organisation ?? null,
      });
      standards = [...standards, created];
      return created;
    }
    if (path.includes("/versions") && !path.includes("/publish") && !path.includes("/retire")) {
      const payload = body as { version_label: string; effective_date: string | null; change_note: string; clone_from_version_id: string | null };
      return version({ id: "ver-new", version_label: payload.version_label, change_note: payload.change_note });
    }
    if (path.endsWith("/archive")) {
      const target = standards.find((s) => path.includes(s.id))!;
      const updated = { ...target, is_archived: true };
      standards = standards.map((s) => (s.id === updated.id ? updated : s));
      return updated;
    }
    if (path.endsWith("/unarchive")) {
      const target = standards.find((s) => path.includes(s.id))!;
      const updated = { ...target, is_archived: false };
      standards = standards.map((s) => (s.id === updated.id ? updated : s));
      return updated;
    }
    throw new Error(`unmocked POST: ${path}`);
  });
  spyOn(api, "patch").mockImplementation(async (path: string, body?: unknown) => {
    const target = standards.find((s) => path.includes(s.id))!;
    const payload = body as { name: string; description?: string; issuing_organisation?: string | null; owner_id: string };
    const updated = { ...target, ...payload };
    standards = standards.map((s) => (s.id === updated.id ? updated : s));
    return updated;
  });
}

const meta: Meta<typeof StandardsPanel> = {
  title: "Modules/Compliance/StandardsPanel",
  component: StandardsPanel,
  args: { orgId: ORG_ID, actionTypes: ACTION_TYPES },
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof StandardsPanel>;

export const ListAndSearch: Story = {
  beforeEach: () => mockStandardsApis({
    standards: [standard(), standard({ id: "std-2", reference: "SOC2", name: "SOC 2 Type II", issuing_organisation: "AICPA" })],
  }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("ISO 27001")).toBeInTheDocument());
    await expect(canvas.getByText("SOC 2 Type II")).toBeInTheDocument();

    await userEvent.type(canvas.getByPlaceholderText("Search standards…"), "soc2");
    await waitFor(() => expect(canvas.queryByText("ISO 27001")).not.toBeInTheDocument());
    await expect(canvas.getByText("SOC 2 Type II")).toBeInTheDocument();
  },
};

export const ShowArchivedTogglesQuery: Story = {
  beforeEach: () => mockStandardsApis({ standards: [standard({ is_archived: true })] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Archived not shown by default — the mocked `GET` still returns the
    // one (archived) standard regardless of query string, so this proves
    // the *request*, not client-side filtering, is what's gated.
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining("include_archived=false")));

    await userEvent.click(canvas.getByRole("checkbox", { name: "Show archived" }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(expect.stringContaining("include_archived=true")));
  },
};

export const CreateStandard: Story = {
  beforeEach: () => mockStandardsApis({ standards: [] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No compliance standards yet.")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "New standard" }));
    const body = within(document.body);
    await userEvent.type(body.getByLabelText("Standard reference"), "NIST-CSF");
    await userEvent.type(body.getByLabelText("Standard name"), "NIST Cybersecurity Framework");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/standards`,
      { reference: "NIST-CSF", name: "NIST Cybersecurity Framework", description: "", issuing_organisation: null }
    ));
    await waitFor(() => expect(canvas.getByText("NIST Cybersecurity Framework")).toBeInTheDocument());
  },
};

export const StandardDetailEditAndArchive: Story = {
  beforeEach: () => mockStandardsApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await waitFor(() => expect(canvas.getByText("ISO 27001")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: /ISO-27001/ }));
    await waitFor(() => expect(body.getByText("Information security management.")).toBeInTheDocument());

    // Edit: the reference field is not offered on the edit form (only on
    // create) — the standard's `owner_id` is resubmitted unchanged
    // (deliberate Phase 12 scope trim, see this component's own docstring).
    await userEvent.click(body.getByRole("button", { name: "Edit" }));
    await expect(body.queryByLabelText("Standard reference")).not.toBeInTheDocument();
    const nameInput = body.getByLabelText("Standard name");
    await userEvent.clear(nameInput);
    await userEvent.type(nameInput, "ISO/IEC 27001");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    // `reference` is immutable after creation (backend's `ComplianceStandardUpdate`
    // deliberately excludes it) and must not be sent on an edit, even though
    // `StandardFormModal`'s `onSave` payload type is shared with the create
    // form and therefore still carries a `reference` field — `StandardsPanel`
    // destructures only the fields `updateStandard` actually declares.
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/standards/std-1`,
      { name: "ISO/IEC 27001", description: "Information security management.", issuing_organisation: "ISO", owner_id: "user-1" }
    ));

    // Archive: Tier 1 confirmation (recoverable via unarchive) — no
    // typed-confirmation requirement, matching this app's other
    // archive/unarchive flows.
    await userEvent.click(body.getByRole("button", { name: "Archive" }));
    const confirmDialog = body.getByRole("dialog", { name: /Archive/ });
    await userEvent.click(within(confirmDialog).getByRole("button", { name: "Archive" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`/api/v1/orgs/${ORG_ID}/modules/compliance/standards/std-1/archive`));
    // The side panel closes after archiving.
    await waitFor(() => expect(body.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument());
  },
};

export const CreateVersionClonedFromExisting: Story = {
  beforeEach: () => mockStandardsApis({ versions: [version(), version({ id: "ver-2", version_label: "v1.1", version_number: 2 })] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await waitFor(() => expect(canvas.getByText("ISO 27001")).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: /ISO-27001/ }));
    await waitFor(() => expect(body.getByRole("button", { name: "v1.0" })).toBeInTheDocument());

    await userEvent.click(body.getByRole("button", { name: "New version" }));
    await userEvent.type(body.getByLabelText("Version label"), "v2.0");
    await userEvent.selectOptions(body.getByLabelText("Clone requirements from"), "v1.1");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/standards/std-1/versions`,
      { version_label: "v2.0", effective_date: null, change_note: "", clone_from_version_id: "ver-2" }
    ));
  },
};

export const DrillIntoVersionOpensWorkspace: Story = {
  beforeEach: () => mockStandardsApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await waitFor(() => expect(canvas.getByText("ISO 27001")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: /ISO-27001/ }));
    await waitFor(() => expect(body.getByRole("button", { name: "v1.0" })).toBeInTheDocument());
    await userEvent.click(body.getByRole("button", { name: "v1.0" }));

    // The Standards tab's own list/SidePanel is replaced in place by
    // `VersionWorkspace` — its "Back to <standard>" control is enough to
    // prove the transition; the workspace's own behaviour is
    // `VersionWorkspace.stories.tsx`'s job.
    await waitFor(() => expect(canvas.getByRole("button", { name: "← Back to ISO 27001" })).toBeInTheDocument());
    await expect(canvas.getByText("ISO-27001 — v1.0")).toBeInTheDocument();
  },
};

export const LoadErrorShowsInlineMessage: Story = {
  beforeEach: () => {
    spyOn(api, "get").mockRejectedValue(new ApiError(404, "Compliance module is not enabled for this organisation."));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() =>
      expect(canvas.getByText(/Compliance module is not enabled for this organisation/)).toBeInTheDocument()
    );
  },
};

export const LightTheme: Story = { ...ListAndSearch };
export const DarkTheme: Story = { ...ListAndSearch, globals: { theme: "dark" } };
