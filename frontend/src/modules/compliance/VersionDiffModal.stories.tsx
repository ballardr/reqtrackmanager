import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, fn, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { VersionDiffModal } from "./VersionDiffModal";
import type { ComplianceRequirementSummary, ComplianceStandardVersion, StandardVersionDiff } from "./types";

const ORG_ID = "org-1";
const STANDARD_ID = "std-1";
const BASE = `/api/v1/orgs/${ORG_ID}/modules/compliance`;

function version(overrides: Partial<ComplianceStandardVersion> & { id: string; version_label: string }): ComplianceStandardVersion {
  return {
    standard_id: STANDARD_ID, version_number: 1, status: "draft", effective_date: null, change_note: "", summary: "",
    created_by: "user-1", published_at: null, published_by: null, retired_at: null, retired_by: null,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...overrides,
  };
}

const V1 = version({ id: "ver-1", version_label: "v1.0" });
const V2 = version({ id: "ver-2", version_label: "v2.0", version_number: 2 });

function reqSummary(overrides: Partial<ComplianceRequirementSummary> & { id: string; name: string }): ComplianceRequirementSummary {
  return { standard_version_id: "ver-2", reference: null, ...overrides };
}

const FULL_DIFF: StandardVersionDiff = {
  old_version_id: "ver-1",
  new_version_id: "ver-2",
  added: [{ requirement: reqSummary({ id: "req-new", reference: "A.9.1", name: "Vendor risk assessment" }) }],
  removed: [{ requirement: reqSummary({ id: "req-gone", standard_version_id: "ver-1", reference: "A.4.2", name: "Legacy asset register" }) }],
  modified: [{
    old_requirement: reqSummary({ id: "req-mod", standard_version_id: "ver-1", reference: "A.5.1", name: "Access control" }),
    new_requirement: reqSummary({ id: "req-mod-2", reference: "A.5.1", name: "Access control policy" }),
    changed_fields: ["name", "description"],
  }],
  replaced: [{
    old_requirement: reqSummary({ id: "req-old", standard_version_id: "ver-1", reference: "A.6.1", name: "Screening" }),
    new_requirement: reqSummary({ id: "req-new-2", reference: "A.6.1", name: "Background verification" }),
    mapping_id: "map-1",
    relationship_type_id: "mt-1",
    implies_equivalence: true,
  }],
  re_mapped: [{
    old_requirement: reqSummary({ id: "req-remap-old", standard_version_id: "ver-1", reference: "A.7.1", name: "Physical security" }),
    new_requirement: reqSummary({ id: "req-remap-new", reference: "A.7.1", name: "Physical and environmental security" }),
    old_mapping_target_requirement_ids: ["req-x"],
    new_mapping_target_requirement_ids: ["req-y", "req-z"],
  }],
};

const EMPTY_DIFF: StandardVersionDiff = {
  old_version_id: "ver-1", new_version_id: "ver-2",
  added: [], removed: [], modified: [], replaced: [], re_mapped: [],
};

function mockDiffApi(diffsByOtherVersion: Record<string, StandardVersionDiff | "error">) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    const otherVersionId = path.split("/diff/")[1];
    const diff = diffsByOtherVersion[otherVersionId];
    if (diff === "error" || diff === undefined) throw new Error("Could not compute diff.");
    return diff;
  });
}

const meta: Meta<typeof VersionDiffModal> = {
  title: "Modules/Compliance/VersionDiffModal",
  component: VersionDiffModal,
  args: { orgId: ORG_ID, standardId: STANDARD_ID, fromVersionId: "ver-1", onClose: fn() },
};
export default meta;

type Story = StoryObj<typeof VersionDiffModal>;

export const RendersAllFiveDiffCategories: Story = {
  args: { versions: [V1, V2] },
  beforeEach: () => mockDiffApi({ "ver-2": FULL_DIFF }),
  play: async () => {
    const body = within(document.body);
    await waitFor(() => expect(body.getByText("Comparing v1.0 (older) to v2.0 (newer).")).toBeInTheDocument());

    await expect(body.getByText("Added (1)")).toBeInTheDocument();
    await expect(body.getByText("A.9.1 — Vendor risk assessment")).toBeInTheDocument();

    await expect(body.getByText("Removed (1)")).toBeInTheDocument();
    await expect(body.getByText("A.4.2 — Legacy asset register")).toBeInTheDocument();

    // Each of these list items also carries a trailing `<span>` (changed
    // fields / carry-forward eligibility / re-mapping note) as a separate
    // text node inside the same `<li>`, so the `<li>`'s own full text is
    // longer than just the requirement name — match it as a substring via
    // regex rather than `getByText`'s default exact-string-per-element
    // match, which would find no element at all.
    await expect(body.getByText("Modified (1)")).toBeInTheDocument();
    await expect(body.getByText(/A\.5\.1 — Access control policy/)).toBeInTheDocument();
    await expect(body.getByText("(changed: name, description)")).toBeInTheDocument();

    await expect(body.getByText("Replaced (1)")).toBeInTheDocument();
    await expect(body.getByText(/Screening → Background verification/)).toBeInTheDocument();
    await expect(body.getByText("(eligible for assessment carry-forward)")).toBeInTheDocument();

    await expect(body.getByText("Re-mapped (1)")).toBeInTheDocument();
    await expect(body.getByText(/A\.7\.1 — Physical and environmental security/)).toBeInTheDocument();
    await expect(body.getByText("— mapping links may need re-establishing")).toBeInTheDocument();
  },
};

export const EmptyDiffShowsNoneForEveryCategory: Story = {
  args: { versions: [V1, V2] },
  beforeEach: () => mockDiffApi({ "ver-2": EMPTY_DIFF }),
  play: async () => {
    const body = within(document.body);
    await waitFor(() => expect(body.getByText("Added (0)")).toBeInTheDocument());
    await expect(body.getAllByText("None.")).toHaveLength(5);
  },
};

export const SwitchingComparisonVersionRefetches: Story = {
  args: { versions: [V1, V2, version({ id: "ver-3", version_label: "v3.0", version_number: 3 })] },
  beforeEach: () => mockDiffApi({ "ver-2": EMPTY_DIFF, "ver-3": { ...EMPTY_DIFF, new_version_id: "ver-3", added: [{ requirement: reqSummary({ id: "req-only-in-3", standard_version_id: "ver-3", name: "New in v3" }) }] } }),
  play: async () => {
    const body = within(document.body);
    await waitFor(() => expect(body.getByText("Comparing v1.0 (older) to v2.0 (newer).")).toBeInTheDocument());
    await expect(body.getByText("Added (0)")).toBeInTheDocument();

    await userEvent.selectOptions(body.getByLabelText("Compare with version"), "ver-3");
    await waitFor(() => expect(api.get).toHaveBeenCalledWith(`${BASE}/standards/${STANDARD_ID}/versions/ver-1/diff/ver-3`));
    await waitFor(() => expect(body.getByText("Added (1)")).toBeInTheDocument());
    await expect(body.getByText("New in v3")).toBeInTheDocument();
  },
};

export const ErrorLoadingDiffShowsInlineMessage: Story = {
  args: { versions: [V1, V2] },
  beforeEach: () => mockDiffApi({ "ver-2": "error" }),
  play: async () => {
    const body = within(document.body);
    await waitFor(() => expect(body.getByText("Could not compute diff.")).toBeInTheDocument());
    await expect(body.queryByText(/Comparing/)).not.toBeInTheDocument();
  },
};

export const NoOtherVersionsAvailable: Story = {
  args: { versions: [V1] },
  play: async () => {
    const body = within(document.body);
    const select = body.getByLabelText("Compare with version") as HTMLSelectElement;
    await expect(select).toHaveValue("");
    await expect(within(select).getAllByRole("option")).toHaveLength(1);
    await expect(body.queryByText(/Comparing/)).not.toBeInTheDocument();
  },
};

export const LightTheme: Story = { ...RendersAllFiveDiffCategories };
export const DarkTheme: Story = { ...RendersAllFiveDiffCategories, globals: { theme: "dark" } };
