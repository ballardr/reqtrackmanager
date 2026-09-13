import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";
import { useParams } from "react-router-dom";

import { api } from "../../api/client";
import { buildUser, withRouter, withToast, withStatefulAuth } from "../../testing/storybook-helpers";
import { StandardVersionsSection } from "./StandardVersionsSection";
import type { ComplianceActionType, ComplianceStandard, ComplianceStandardVersion } from "./types";

const ORG_ID = "org-1";
const STANDARD: ComplianceStandard = {
  id: "std-1", organization_id: ORG_ID, reference: "ISO-27001", name: "ISO 27001",
  description: "", issuing_organisation: null, owner_id: "user-1", creator_id: "user-1",
  is_archived: false, archived_at: null, archived_by: null, applicability_default: "opt_in",
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};
const ACTION_TYPES: ComplianceActionType[] = [{ id: "at-1", organization_id: ORG_ID, name: "Review", sort_order: 0 }];

function version(overrides: Partial<ComplianceStandardVersion> = {}): ComplianceStandardVersion {
  return {
    id: "ver-1", standard_id: STANDARD.id, version_number: 1, version_label: "v1.0", status: "draft",
    effective_date: null, change_note: "", summary: "", created_by: "user-1", published_at: null, published_by: null,
    retired_at: null, retired_by: null, created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function mockVersionApis(versions: ComplianceStandardVersion[] = [version()]) {
  let current = versions;
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.includes("/requirements") && !path.includes("required-actions")) return [];
    if (path.includes("/required-actions")) return [];
    if (path.includes("/versions")) return current;
    throw new Error(`unmocked GET: ${path}`);
  });
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    if (path.includes("/versions") && !path.includes("/publish") && !path.includes("/retire")) {
      const payload = body as { version_label: string; change_note: string; clone_from_version_id: string | null };
      const created = version({ id: "ver-new", version_label: payload.version_label, change_note: payload.change_note });
      current = [...current, created];
      return created;
    }
    throw new Error(`unmocked POST: ${path}`);
  });
}

/**
 * `StandardVersionsSection` — the "Versions" content of `StandardWorkspacePage
 * .tsx` (docs/compliance-module-plan.md Phase 18), extracted from
 * `StandardsPanel.tsx`'s old `SidePanel`/`VersionWorkspace` drill-in.
 * `VersionWorkspace`'s own publish/retire/requirement-tree behaviour is
 * covered by `VersionWorkspace.stories.tsx`, not duplicated here.
 *
 * Phase 23 moved "which version is open" from local state to the URL
 * (`initialVersionId`, the real `StandardWorkspacePage.tsx`'s own
 * `:versionId?` route param) — `Harness` below stands in for that parent,
 * reading the same param straight out of a real router so a story can
 * exercise the full open/navigate/back round trip, not just call the
 * prop directly.
 */
function Harness(props: { orgId: string; standard: ComplianceStandard; actionTypes: ComplianceActionType[] }) {
  const { versionId } = useParams<{ versionId?: string }>();
  return <StandardVersionsSection {...props} initialVersionId={versionId ?? null} />;
}

const meta: Meta<typeof StandardVersionsSection> = {
  title: "Modules/Compliance/StandardVersionsSection",
  component: StandardVersionsSection,
  args: { orgId: ORG_ID, standard: STANDARD, actionTypes: ACTION_TYPES, initialVersionId: null },
  render: (args) => <Harness orgId={args.orgId} standard={args.standard} actionTypes={args.actionTypes} />,
  decorators: [withToast(), withStatefulAuth(buildUser({ id: "user-1" }))],
};
export default meta;

type Story = StoryObj<typeof StandardVersionsSection>;

const VERSIONS_ROUTE = "/standards/:standardId/versions/:versionId?";

export const ListsVersions: Story = {
  decorators: [withRouter(`/standards/${STANDARD.id}/versions`, VERSIONS_ROUTE)],
  beforeEach: () => mockVersionApis([version(), version({ id: "ver-2", version_label: "v1.1", version_number: 2 })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "v1.0" })).toBeInTheDocument());
    await expect(canvas.getByRole("button", { name: "v1.1" })).toBeInTheDocument();
  },
};

export const CreateVersionClonedFromExisting: Story = {
  decorators: [withRouter(`/standards/${STANDARD.id}/versions`, VERSIONS_ROUTE)],
  beforeEach: () => mockVersionApis([version(), version({ id: "ver-2", version_label: "v1.1", version_number: 2 })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await waitFor(() => expect(canvas.getByRole("button", { name: "v1.0" })).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "New version" }));
    await userEvent.type(body.getByLabelText("Version label"), "v2.0");
    await userEvent.selectOptions(body.getByLabelText("Clone requirements from"), "v1.1");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/orgs/${ORG_ID}/modules/compliance/standards/${STANDARD.id}/versions`,
      { version_label: "v2.0", effective_date: null, change_note: "", clone_from_version_id: "ver-2" }
    ));
  },
};

export const DrillIntoVersionOpensWorkspace: Story = {
  decorators: [withRouter(`/standards/${STANDARD.id}/versions`, VERSIONS_ROUTE)],
  beforeEach: () => mockVersionApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "v1.0" })).toBeInTheDocument());
    await userEvent.click(canvas.getByRole("button", { name: "v1.0" }));

    // Opening a version navigates to its own URL (`/versions/:versionId`)
    // rather than only flipping local state — `Harness` re-derives
    // `initialVersionId` from that same route param.
    await waitFor(() => expect(canvas.getByRole("button", { name: "← Back to ISO 27001" })).toBeInTheDocument());
    await expect(canvas.getByText("ISO-27001 — v1.0")).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "← Back to ISO 27001" }));
    await waitFor(() => expect(canvas.getByRole("button", { name: "v1.0" })).toBeInTheDocument());
  },
};

export const DeepLinksDirectlyIntoVersionWorkspace: Story = {
  decorators: [withRouter(`/standards/${STANDARD.id}/versions/ver-1`, VERSIONS_ROUTE)],
  beforeEach: () => mockVersionApis(),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Landing on the URL directly (e.g. from `StandardNavSection.tsx`'s
    // expandable Versions group) opens the workspace straight away, never
    // showing the plain version list first.
    await waitFor(() => expect(canvas.getByText("ISO-27001 — v1.0")).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "v1.0" })).not.toBeInTheDocument();
  },
};
