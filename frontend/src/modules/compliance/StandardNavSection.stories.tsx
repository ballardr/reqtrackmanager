import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildUser, withRouter, withStatefulAuth } from "../../testing/storybook-helpers";
import { StandardNavSection } from "./StandardNavSection";
import type { ComplianceStandard, ComplianceStandardVersion } from "./types";

const STANDARD: ComplianceStandard = {
  id: "std-1", organization_id: "org-1", reference: "ISO-27001", name: "ISO 27001",
  description: "", issuing_organisation: null, owner_id: "user-1", creator_id: "user-1",
  is_archived: false, archived_at: null, archived_by: null, applicability_default: "opt_in",
  created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
};

function version(overrides: Partial<ComplianceStandardVersion> & { id: string; version_number: number; version_label: string }): ComplianceStandardVersion {
  return {
    standard_id: STANDARD.id, status: "draft", effective_date: null, change_note: "", summary: "", created_by: "user-1",
    published_at: null, published_by: null, retired_at: null, retired_by: null,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...overrides,
  };
}

function mockNavApis(versions: ComplianceStandardVersion[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/compliance/standards/${STANDARD.id}`) return STANDARD;
    if (path.endsWith("/versions")) return versions;
    throw new Error(`unmocked GET: ${path}`);
  });
}

/**
 * The "Standard" left-nav section (docs/compliance-module-plan.md Phase 18)
 * — Overview/Details, Versions, History — registered via `module.ts`'s
 * `standaloneWorkspaces`, rendered by `Layout.tsx` as a sibling structural
 * pattern to its own "Project" section, never imported by `Layout.tsx`
 * directly.
 *
 * Phase 23 adds this app's first expandable nav-rail group: "Versions"
 * gains a disclosure toggle that lists one link per version underneath.
 * Resolving `organization_id` and the version list are this component's
 * own fetches (`standaloneWorkspaces.render` only passes `entityId`/
 * `railCollapsed`), so every story here mocks those two `GET`s.
 */
const meta: Meta<typeof StandardNavSection> = {
  title: "Modules/Compliance/StandardNavSection",
  component: StandardNavSection,
  args: { entityId: STANDARD.id, railCollapsed: false },
  decorators: [withRouter(`/standards/${STANDARD.id}`), withStatefulAuth(buildUser({ id: "user-1" }))],
};
export default meta;

type Story = StoryObj<typeof StandardNavSection>;

export const Default: Story = {
  beforeEach: () => mockNavApis([version({ id: "ver-1", version_number: 1, version_label: "v1.0", status: "published" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await expect(canvas.getByText("Standard")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Overview" })).toHaveAttribute("href", "/standards/std-1");
    await expect(canvas.getByRole("link", { name: "Versions" })).toHaveAttribute("href", "/standards/std-1/versions");
    await expect(canvas.getByRole("link", { name: "History" })).toHaveAttribute("href", "/standards/std-1/history");
    // Has at least one version, so the disclosure toggle appears once the
    // version list resolves.
    await waitFor(() => expect(canvas.getByRole("button", { name: "Expand versions" })).toBeInTheDocument());
  },
};

export const ExpandingListsVersions: Story = {
  beforeEach: () => mockNavApis([
    version({ id: "ver-1", version_number: 1, version_label: "v1.0", status: "published" }),
    version({ id: "ver-2", version_number: 2, version_label: "v2.0", status: "draft" }),
  ]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("button", { name: "Expand versions" })).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Expand versions" }));
    await expect(canvas.getByRole("link", { name: /v1\.0/ })).toHaveAttribute("href", "/standards/std-1/versions/ver-1");
    await expect(canvas.getByRole("link", { name: /v2\.0/ })).toHaveAttribute("href", "/standards/std-1/versions/ver-2");
    await expect(canvas.getByText("Published")).toBeInTheDocument();
    await expect(canvas.getByText("Draft")).toBeInTheDocument();

    // Collapses back on a second click, persisted via `useUiPreference`.
    await userEvent.click(canvas.getByRole("button", { name: "Collapse versions" }));
    await expect(canvas.queryByRole("link", { name: /v1\.0/ })).not.toBeInTheDocument();
  },
};

export const NoVersionsHidesExpandToggle: Story = {
  beforeEach: () => mockNavApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("link", { name: "Versions" })).toBeInTheDocument());
    await expect(canvas.queryByRole("button", { name: "Expand versions" })).not.toBeInTheDocument();
  },
};

export const Collapsed: Story = {
  args: { railCollapsed: true },
  beforeEach: () => mockNavApis([version({ id: "ver-1", version_number: 1, version_label: "v1.0", status: "published" })]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Collapsed rows keep their accessible name but hide the visible text
    // label (`.nav-label`, hidden via CSS in icon-only mode) — same
    // convention every other `NavRailLink` follows. The expandable-versions
    // toggle doesn't apply to a collapsed, icons-only rail at all.
    await expect(canvas.getByRole("link", { name: "Overview" })).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Expand versions" })).not.toBeInTheDocument();
  },
};
