import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildGraph, buildGraphNode } from "../../testing/artefactLinksFixtures";
import { buildRecordColumns } from "../../testing/recordTablesFixtures";
import { buildFileAsset, withRouter, withToast } from "../../testing/storybook-helpers";
import { EvidencePanel } from "./EvidencePanel";
import type { ComplianceEvidence } from "./types";
import { openListMenu, chooseExport } from "../../testing/listActionsMenu";

const PROJECT_ID = "proj-1";

function evidence(overrides: Partial<ComplianceEvidence> = {}): ComplianceEvidence {
  return {
    id: "ev-1", project_id: PROJECT_ID, unique_code: "EVD-001", title: "IPX6 Test Certificate", description: "",
    issuing_organisation: "TÜV", issued_date: "2026-01-01", expiry_date: "2026-12-31",
    provided_by: "user-1", provided_at: "2026-01-01T00:00:00Z", notes: "", validity_state: "valid",
    is_archived: false, archived_at: null, archived_by: null,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    linked_requirement_ids: [], linked_required_action_assessment_ids: [], ...overrides,
  };
}

/**
 * The project's evidence library (§13-§15) — the list, search and creation.
 * Archive, revalidate, edit and files live on `EvidenceDetailPage` (its own
 * stories).
 */
function mockApis(initial: ComplianceEvidence[]) {
  let items = initial;
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path.endsWith("/records/compliance_evidence/columns")) return buildRecordColumns({ label: "Evidence" });
    if (path.includes("/link-graph")) {
      return buildGraph([[buildGraphNode({ type: "requirement", id: "r-9", type_label: "Requirement", label: "SW-SEC-014 Encrypt at rest", status: null })]]);
    }
    if (path.endsWith("/files")) return [];
    if (path.endsWith("/revalidations")) return [];
    if (path.endsWith("/evidence")) return items;
    throw new Error(`unmocked GET: ${path}`);
  });
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    if (path.endsWith("/evidence")) {
      const payload = body as { title: string; description?: string; issuing_organisation?: string | null; issued_date?: string | null; expiry_date?: string | null; notes?: string };
      const created = evidence({ id: "ev-new", title: payload.title, description: payload.description ?? "", issuing_organisation: payload.issuing_organisation ?? null, issued_date: payload.issued_date ?? null, expiry_date: payload.expiry_date ?? null, notes: payload.notes ?? "" });
      items = [...items, created];
      return created;
    }
    if (path.endsWith("/archive")) {
      const id = path.split("/evidence/")[1].split("/archive")[0];
      items = items.map((e) => (e.id === id ? { ...e, is_archived: true } : e));
      return items.find((e) => e.id === id);
    }
    if (path.endsWith("/unarchive")) {
      const id = path.split("/evidence/")[1].split("/unarchive")[0];
      items = items.map((e) => (e.id === id ? { ...e, is_archived: false } : e));
      return items.find((e) => e.id === id);
    }
    if (path.endsWith("/revalidate")) {
      const id = path.split("/evidence/")[1].split("/revalidate")[0];
      const payload = body as { new_expiry_date: string | null };
      items = items.map((e) => (e.id === id ? { ...e, expiry_date: payload.new_expiry_date } : e));
      return items.find((e) => e.id === id);
    }
    throw new Error(`unmocked POST: ${path}`);
  });
  spyOn(api, "patch").mockImplementation(async (path: string, body?: unknown) => {
    const id = path.split("/evidence/")[1];
    const payload = body as { title: string; description?: string };
    items = items.map((e) => (e.id === id ? { ...e, ...payload } : e));
    return items.find((e) => e.id === id);
  });
  spyOn(api, "postFile").mockImplementation(async (path: string, file: File) => {
    if (path.endsWith("/files")) return buildFileAsset({ id: `file-${file.name}`, filename: file.name });
    throw new Error(`unmocked postFile: ${path}`);
  });
}

const meta: Meta<typeof EvidencePanel> = {
  title: "Modules/Compliance/EvidencePanel",
  component: EvidencePanel,
  decorators: [withToast(), withRouter("/")],
  args: { projectId: PROJECT_ID },
};
export default meta;

type Story = StoryObj<typeof EvidencePanel>;

export const ListsEvidence: Story = {
  beforeEach: () => mockApis([evidence()]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("IPX6 Test Certificate")).toBeInTheDocument());
    await expect(canvas.getByRole("columnheader", { name: "Code" })).toBeInTheDocument();
    await expect(canvas.getByText(/EVD-001/)).toBeInTheDocument();
  },
};

export const AddEvidence: Story = {
  beforeEach: () => mockApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await waitFor(() => expect(canvas.getByText("No evidence recorded for this project yet.")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Add evidence" }));
    await userEvent.type(body.getByLabelText("Evidence title"), "IP67 Water Ingress Report");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/evidence`,
      expect.objectContaining({ title: "IP67 Water Ingress Report" })
    ));
  },
};

/** Attaching file(s) at evidence
 * creation time itself, rather than saving first and attaching afterwards
 * from the newly-created record's own Files section. One staged file is
 * removed before save (proving the local staging list, not just the upload
 * call), and the remaining file is uploaded immediately after the evidence
 * record is created — one user action, not two. */
export const AddEvidenceWithFileAttachment: Story = {
  beforeEach: () => mockApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await waitFor(() => expect(canvas.getByText("No evidence recorded for this project yet.")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "Add evidence" }));
    const dialog = await waitFor(() => body.getByRole("dialog", { name: "Add evidence" }));
    const dialogScope = within(dialog);
    await userEvent.type(dialogScope.getByLabelText("Evidence title"), "IP67 Water Ingress Report");

    const input = dialog.querySelector('input[type="file"]') as HTMLInputElement;
    const removedFile = new File(["data"], "draft.pdf", { type: "application/pdf" });
    const keptFile = new File(["data"], "certificate.pdf", { type: "application/pdf" });
    await userEvent.upload(input, removedFile);
    await userEvent.upload(input, keptFile);
    await expect(dialogScope.getByText("draft.pdf")).toBeInTheDocument();
    await expect(dialogScope.getByText("certificate.pdf")).toBeInTheDocument();

    await userEvent.click(dialogScope.getByRole("button", { name: "Remove draft.pdf" }));
    await expect(dialogScope.queryByText("draft.pdf")).not.toBeInTheDocument();

    await userEvent.click(dialogScope.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/evidence`,
      expect.objectContaining({ title: "IP67 Water Ingress Report" })
    ));
    await waitFor(() => expect(api.postFile).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/evidence/ev-new/files`, keptFile
    ));
    // Removing draft.pdf before save means only the kept file was ever
    // uploaded — a single postFile call, not two.
    await expect(api.postFile).toHaveBeenCalledTimes(1);
  },
};

/** A row is a real link to the evidence's own detail page. */
export const RowsLinkToTheDetailPage: Story = {
  beforeEach: () => mockApis([evidence()]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const link = await canvas.findByRole("link", { name: "IPX6 Test Certificate" });
    await expect(link).toHaveAttribute("href", `/projects/${PROJECT_ID}/modules/compliance/evidence/ev-1`);
    // No side panel opens in place any more.
    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
  },
};

/** Export and Import sit beside Add evidence; Export carries the list's search and archived filters. */
export const ExportCarriesTheListsFilters: Story = {
  beforeEach: () => {
    mockApis([evidence()]);
    spyOn(api, "getForBlob").mockResolvedValue(new Blob(["code\n"], { type: "text/csv" }));
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByRole("link", { name: "IPX6 Test Certificate" });
    await userEvent.type(canvas.getByLabelText("Search evidence"), "IPX");
    await userEvent.click(canvas.getByRole("checkbox", { name: "Show archived" }));
    await expect((await openListMenu(canvas)).getByRole("menuitem", { name: "Import from CSV" })).toBeInTheDocument();
    await userEvent.keyboard("{Escape}");
    await chooseExport(canvas, "CSV");
    await waitFor(() =>
      expect(api.getForBlob).toHaveBeenCalledWith(`/api/v1/projects/${PROJECT_ID}/records/compliance_evidence/export?search=IPX&include_archived=true`),
    );
  },
};

export const LightTheme: Story = { ...ListsEvidence };
export const DarkTheme: Story = { ...ListsEvidence, globals: { theme: "dark" } };
