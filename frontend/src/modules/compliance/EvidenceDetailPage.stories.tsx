import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildGraph, buildGraphNode } from "../../testing/artefactLinksFixtures";
import { chooseRecordAction } from "../../testing/recordActions";
import { buildFileAsset, buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { EvidenceDetailPage } from "./EvidenceDetailPage";
import type { ComplianceEvidence, ComplianceEvidenceRevalidation } from "./types";

const PROJECT_ID = "proj-1";
const EVIDENCE_ID = "ev-1";
const BASE = `/api/v1/projects/${PROJECT_ID}/modules/compliance/evidence/${EVIDENCE_ID}`;

function evidence(overrides: Partial<ComplianceEvidence> = {}): ComplianceEvidence {
  return {
    id: EVIDENCE_ID, project_id: PROJECT_ID, unique_code: "EVD-001", title: "IPX6 Test Certificate", description: "Lab certificate for the housing.",
    issuing_organisation: "TÜV", issued_date: "2026-01-01", expiry_date: "2026-12-31",
    provided_by: "user-1", provided_at: "2026-01-01T00:00:00Z", notes: "", validity_state: "valid",
    is_archived: false, archived_at: null, archived_by: null,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    linked_requirement_ids: [], linked_required_action_assessment_ids: [], ...overrides,
  };
}

const REVALIDATION: ComplianceEvidenceRevalidation = {
  id: "rv-1", evidence_id: EVIDENCE_ID, revalidated_by: "user-1", revalidated_at: "2026-06-01T00:00:00Z",
  previous_expiry_date: "2026-06-30", new_expiry_date: "2026-12-31", justification: "Re-tested", created_at: "2026-06-01T00:00:00Z",
};

/** Mocks the reads the page makes; `current` is returned for the evidence itself. */
function mockApis(current: ComplianceEvidence, revalidations: ComplianceEvidenceRevalidation[] = []) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === BASE) return current;
    if (path === `${BASE}/files`) return [buildFileAsset({ id: "f-1", filename: "certificate.pdf" })];
    if (path === `${BASE}/revalidations`) return revalidations;
    if (path.includes(`/artefacts/compliance_evidence/${EVIDENCE_ID}/link-graph`)) {
      return buildGraph([[buildGraphNode({ type: "requirement", id: "r-9", type_label: "Requirement", label: "SW-SEC-014 Encrypt at rest", status: null })]]);
    }
    if (path.endsWith(`/projects/${PROJECT_ID}`)) return { id: PROJECT_ID, organization_id: "org-1" };
    throw new Error(`Unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof EvidenceDetailPage> = {
  title: "Modules/Compliance/EvidenceDetailPage",
  component: EvidenceDetailPage,
  decorators: [
    withAuth(buildUser({ id: "user-1", display_name: "Alex Morgan" })),
    withRouter(`/projects/${PROJECT_ID}/modules/compliance/evidence/${EVIDENCE_ID}`, "/projects/:projectId/modules/compliance/evidence/:evidenceId"),
    withToast(),
  ],
};
export default meta;

type Story = StoryObj<typeof EvidenceDetailPage>;

export const ShowsFieldsFilesLinksAndHistory: Story = {
  beforeEach: () => mockApis(evidence(), [REVALIDATION]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("heading", { name: "IPX6 Test Certificate" })).toBeInTheDocument());
    await expect(canvas.getByText(/EVD-001/)).toBeInTheDocument();
    await expect(canvas.getByText("Valid")).toHaveClass("badge--accent");
    await expect(canvas.getByText("Lab certificate for the housing.")).toBeInTheDocument();
    await expect(await canvas.findByText("certificate.pdf")).toBeInTheDocument();
    await expect(await canvas.findByText(/Re-tested/)).toBeInTheDocument();
    await waitFor(() => expect(canvas.getByRole("link", { name: "SW-SEC-014 Encrypt at rest" })).toBeInTheDocument());
    await expect(canvas.getByRole("link", { name: "← Evidence" })).toHaveAttribute("href", `/projects/${PROJECT_ID}/modules/compliance?tab=evidence`);
  },
};

export const ExpiredAndArchivedAreFlagged: Story = {
  beforeEach: () => mockApis(evidence({ validity_state: "expired", is_archived: true })),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("Expired")).toHaveClass("badge--danger"));
    await expect(canvas.getByText("Archived")).toBeInTheDocument();
    await expect(canvas.queryByRole("button", { name: "Edit" })).not.toBeInTheDocument();
  },
};

export const RevalidatePostsTheNewExpiry: Story = {
  beforeEach: () => {
    mockApis(evidence());
    spyOn(api, "post").mockResolvedValue(evidence({ expiry_date: "2027-12-31" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await userEvent.click(await canvas.findByRole("button", { name: "Revalidate" }));
    const dialog = await waitFor(() => body.getByRole("dialog", { name: "Revalidate evidence" }));
    await userEvent.type(within(dialog).getByLabelText("New expiry date"), "2027-12-31");
    await userEvent.click(within(dialog).getByRole("button", { name: "Revalidate" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${BASE}/revalidate`, { new_expiry_date: "2027-12-31", justification: "" }));
  },
};

export const EditSavesTheChangedFields: Story = {
  beforeEach: () => {
    mockApis(evidence());
    spyOn(api, "patch").mockResolvedValue(evidence({ title: "IPX7 Test Certificate" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await userEvent.click(await canvas.findByRole("button", { name: "Edit" }));
    const title = await waitFor(() => body.getByLabelText("Evidence title"));
    await userEvent.clear(title);
    await userEvent.type(title, "IPX7 Test Certificate");
    await userEvent.click(body.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(api.patch).toHaveBeenCalledWith(BASE, expect.objectContaining({ title: "IPX7 Test Certificate" })));
    await waitFor(() => expect(canvas.getByRole("heading", { name: "IPX7 Test Certificate" })).toBeInTheDocument());
  },
};

export const ArchiveAsksForConfirmation: Story = {
  beforeEach: () => {
    mockApis(evidence());
    spyOn(api, "post").mockResolvedValue(evidence({ is_archived: true }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await canvas.findByRole("heading", { name: "IPX6 Test Certificate" });
    await chooseRecordAction(canvas, "Evidence", "Archive");
    const dialog = await waitFor(() => body.getByRole("dialog", { name: /Archive this evidence/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Archive" }));
    await waitFor(() => expect(api.post).toHaveBeenCalledWith(`${BASE}/archive`));
    await waitFor(() => expect(canvas.getByText("Archived")).toBeInTheDocument());
  },
};

export const LightTheme: Story = { ...ShowsFieldsFilesLinksAndHistory };
export const DarkTheme: Story = { ...ShowsFieldsFilesLinksAndHistory, globals: { theme: "dark" } };
