import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildUser, withStatefulAuth, withToast } from "../../testing/storybook-helpers";
import { VersionWorkspace } from "./VersionWorkspace";
import type { ComplianceActionType, ComplianceStandard, ComplianceStandardVersion, StandardVersionDiff } from "./types";

const ORG_ID = "org-1";
const ACTION_TYPES: ComplianceActionType[] = [{ id: "at-1", organization_id: ORG_ID, name: "Review", sort_order: 0 }];

const STANDARD: ComplianceStandard = {
  id: "std-1", organization_id: ORG_ID, reference: "ISO-27001", name: "ISO 27001",
  description: "Information security management.", issuing_organisation: "ISO", owner_id: "user-1",
  creator_id: "user-1", is_archived: false, archived_at: null, archived_by: null, applicability_default: "opt_in",
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};

function version(overrides: Partial<ComplianceStandardVersion> = {}): ComplianceStandardVersion {
  return {
    id: "ver-1", standard_id: "std-1", version_number: 1, version_label: "v1.0", status: "draft",
    effective_date: null, change_note: "", created_by: "user-1", published_at: null, published_by: null,
    retired_at: null, retired_by: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

const EMPTY_DIFF: StandardVersionDiff = {
  old_version_id: "ver-1", new_version_id: "ver-2",
  added: [], removed: [], modified: [], replaced: [], re_mapped: [],
};

/**
 * `VersionWorkspace` renders `RequirementTree` unconditionally underneath
 * its own status/publish/retire header, and opens `VersionDiffModal` on
 * "Compare versions" — both of those components' own detailed behaviour is
 * covered by their own dedicated story files
 * (`RequirementTree.stories.tsx`, `VersionDiffModal.stories.tsx`). Here,
 * `requirements`/`diff` fetches are mocked to resolve trivially (empty)
 * just so those children mount cleanly; these stories exercise what's
 * specific to `VersionWorkspace` itself: the status-driven publish/retire/
 * immutability-note logic and the "Compare versions" entry point.
 */
function mockWorkspaceApis() {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/requirements") && !path.includes("required-actions")) return [];
    if (path.includes("/required-actions")) return [];
    if (path.includes("/diff/")) return EMPTY_DIFF;
    throw new Error(`unmocked GET: ${path}`);
  });
  spyOn(api, "post").mockImplementation(async (path: string) => {
    if (path.endsWith("/publish")) return version({ status: "published" });
    if (path.endsWith("/retire")) return version({ status: "retired" });
    throw new Error(`unmocked POST: ${path}`);
  });
}

const meta: Meta<typeof VersionWorkspace> = {
  title: "Modules/Compliance/VersionWorkspace",
  component: VersionWorkspace,
  args: { orgId: ORG_ID, standard: STANDARD, actionTypes: ACTION_TYPES, onBack: fn(), onVersionChanged: fn() },
  decorators: [withToast(), withStatefulAuth(buildUser({ id: "user-1" }))],
};
export default meta;

type Story = StoryObj<typeof VersionWorkspace>;

export const DraftVersionOffersPublishAndRetire: Story = {
  args: { version: version(), versions: [version()] },
  beforeEach: () => mockWorkspaceApis(),
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("ISO-27001 — v1.0")).toBeInTheDocument();
    await expect(canvas.getByText("Draft")).toBeInTheDocument();
    await expect(canvas.queryByText(/its requirements and required actions are immutable/)).not.toBeInTheDocument();

    const publishButton = canvas.getByRole("button", { name: "Publish" });
    await expect(canvas.getByRole("button", { name: "Retire" })).toBeInTheDocument();
    await userEvent.click(publishButton);

    const body = within(document.body);
    await expect(body.getByRole("dialog", { name: "Publish this version?" })).toBeInTheDocument();
    await userEvent.click(within(body.getByRole("dialog")).getByRole("button", { name: "Publish" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/standards/std-1/versions/ver-1/publish`
    ));
    await waitFor(() => expect(args.onVersionChanged).toHaveBeenCalledOnce());
  },
};

export const PublishedVersionShowsImmutableNoteAndRetireOnly: Story = {
  args: { version: version({ status: "published" }), versions: [version({ status: "published" })] },
  beforeEach: () => mockWorkspaceApis(),
  play: async ({ canvasElement, args }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: "Publish" })).not.toBeInTheDocument();
    await expect(canvas.getByRole("button", { name: "Retire" })).toBeInTheDocument();
    await expect(canvas.getByText(/This version is published — its requirements and required actions are immutable/)).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Retire" }));
    const body = within(document.body);
    await userEvent.click(within(body.getByRole("dialog")).getByRole("button", { name: "Retire" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/standards/std-1/versions/ver-1/retire`
    ));
    await waitFor(() => expect(args.onVersionChanged).toHaveBeenCalledOnce());
  },
};

export const RetiredVersionOffersNeitherAction: Story = {
  args: { version: version({ status: "retired" }), versions: [version({ status: "retired" })] },
  beforeEach: () => mockWorkspaceApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.queryByRole("button", { name: "Publish" })).not.toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Retire" })).not.toBeInTheDocument();
    await expect(canvas.getByText(/This version is retired/)).toBeInTheDocument();
  },
};

export const CompareVersionsDisabledWithOnlyOneVersion: Story = {
  args: { version: version(), versions: [version()] },
  beforeEach: () => mockWorkspaceApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByRole("button", { name: "Compare versions" })).toBeDisabled();
  },
};

export const CompareVersionsOpensDiffModal: Story = {
  args: {
    version: version(),
    versions: [version(), version({ id: "ver-2", version_label: "v1.1", version_number: 2 })],
  },
  beforeEach: () => mockWorkspaceApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const compareButton = canvas.getByRole("button", { name: "Compare versions" });
    await expect(compareButton).toBeEnabled();
    await userEvent.click(compareButton);

    // Proves the transition only — `VersionDiffModal`'s own diff-rendering
    // behaviour is `VersionDiffModal.stories.tsx`'s job.
    await expect(within(document.body).getByRole("dialog", { name: "Compare versions" })).toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...DraftVersionOffersPublishAndRetire };
export const DarkTheme: Story = { ...DraftVersionOffersPublishAndRetire, globals: { theme: "dark" } };
