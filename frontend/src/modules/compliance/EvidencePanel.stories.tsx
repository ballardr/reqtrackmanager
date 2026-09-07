import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { withToast } from "../../testing/storybook-helpers";
import { EvidencePanel } from "./EvidencePanel";
import type { ComplianceEvidence } from "./types";

const PROJECT_ID = "proj-1";
const ORG_ID = "org-1";

function evidence(overrides: Partial<ComplianceEvidence> = {}): ComplianceEvidence {
  return {
    id: "ev-1", project_id: PROJECT_ID, title: "IPX6 Test Certificate", description: "",
    issuing_organisation: "TÜV", issued_date: "2026-01-01", expiry_date: "2026-12-31",
    provided_by: "user-1", provided_at: "2026-01-01T00:00:00Z", notes: "", validity_state: "valid",
    is_archived: false, archived_at: null, archived_by: null,
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z",
    linked_requirement_ids: [], linked_required_action_assessment_ids: [], ...overrides,
  };
}

/**
 * The project's evidence library (§13-§15) — creation, the archive/
 * revalidate/edit `SidePanel` actions, and §15's append-only revalidation
 * history. File-attachment upload/link is exercised via `FileAttachmentList
 * .stories.tsx`/`ResourcePickerModal.stories.tsx`'s own dedicated coverage
 * of that shared mechanism — this file proves the wiring (correct evidence
 * id, correct endpoint), not the attachment widgets' own internals again.
 */
function mockApis(initial: ComplianceEvidence[]) {
  let items = initial;
  spyOn(api, "get").mockImplementation(async (path: string) => {
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
}

const meta: Meta<typeof EvidencePanel> = {
  title: "Modules/Compliance/EvidencePanel",
  component: EvidencePanel,
  decorators: [withToast()],
  args: { projectId: PROJECT_ID, orgId: ORG_ID },
};
export default meta;

type Story = StoryObj<typeof EvidencePanel>;

export const ListsEvidence: Story = {
  beforeEach: () => mockApis([evidence()]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("IPX6 Test Certificate")).toBeInTheDocument());
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

export const RevalidateEvidence: Story = {
  beforeEach: () => mockApis([evidence()]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await userEvent.click(canvas.getByText("IPX6 Test Certificate"));
    await userEvent.click(body.getByRole("button", { name: "Revalidate" }));
    const dialog = await waitFor(() => body.getByRole("dialog", { name: "Revalidate evidence" }));
    const dialogScope = within(dialog);
    await userEvent.type(dialogScope.getByLabelText("New expiry date (optional)"), "2027-12-31");
    await userEvent.click(dialogScope.getByRole("button", { name: "Revalidate" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/evidence/ev-1/revalidate`,
      { new_expiry_date: "2027-12-31", justification: "" }
    ));
  },
};

export const ArchiveEvidence: Story = {
  beforeEach: () => mockApis([evidence()]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await userEvent.click(canvas.getByText("IPX6 Test Certificate"));
    await userEvent.click(body.getByRole("button", { name: "Archive" }));
    const confirmDialog = await waitFor(() => body.getByRole("dialog", { name: /Archive/ }));
    await userEvent.click(within(confirmDialog).getByRole("button", { name: "Archive" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      `/api/v1/projects/${PROJECT_ID}/modules/compliance/evidence/ev-1/archive`
    ));
  },
};

export const LightTheme: Story = { ...ListsEvidence };
export const DarkTheme: Story = { ...ListsEvidence, globals: { theme: "dark" } };
