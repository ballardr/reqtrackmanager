import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import type { Organization } from "../../api/types";
import { buildUser, withRouter, withStatefulAuth, withToast } from "../../testing/storybook-helpers";
import { StandardListPage } from "./StandardListPage";
import type { ComplianceStandard } from "./types";

function org(overrides: Partial<Organization> = {}): Organization {
  return {
    id: "org-1", name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
    default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
    disabled_at: null, accent_color_hex: null, header_title: null,
    email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
    ...overrides,
  };
}

function standard(overrides: Partial<ComplianceStandard> = {}): ComplianceStandard {
  return {
    id: "std-1", organization_id: "org-1", reference: "ISO-27001", name: "ISO 27001",
    description: "", issuing_organisation: "ISO", owner_id: "user-1", creator_id: "user-1",
    is_archived: false, archived_at: null, archived_by: null, applicability_default: "opt_in",
    created_at: "2026-01-01T00:00:00Z", updated_at: "2026-01-01T00:00:00Z", ...overrides,
  };
}

/**
 * `StandardListPage` — the cross-org `/standards` tab (docs/compliance-
 * module-plan.md Phase 18), modelled on `ProjectListPage.tsx`. No cross-org
 * backend listing endpoint exists, so the page fans out `listStandards`
 * per org (`GET /orgs?mine=true`) — mocked here per org id below.
 */
function mockStandardListApis(orgs: Organization[], standardsByOrg: Record<string, ComplianceStandard[]>) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === "/api/v1/orgs?mine=true") return orgs;
    const match = /\/api\/v1\/orgs\/([^/]+)\/modules\/compliance\/standards/.exec(path);
    if (match) return standardsByOrg[match[1]] ?? [];
    throw new Error(`unmocked GET: ${path}`);
  });
  spyOn(api, "post").mockImplementation(async (path: string, body?: unknown) => {
    const match = /\/api\/v1\/orgs\/([^/]+)\/modules\/compliance\/standards$/.exec(path);
    if (match) {
      const payload = body as { reference: string; name: string };
      return standard({ id: "std-new", organization_id: match[1], reference: payload.reference, name: payload.name });
    }
    throw new Error(`unmocked POST: ${path}`);
  });
  spyOn(api, "postFile").mockImplementation(async (path: string) => {
    const match = /\/api\/v1\/orgs\/([^/]+)\/modules\/compliance\/standards\/import$/.exec(path);
    if (match) {
      return {
        standard: standard({ id: "std-imported", organization_id: match[1], reference: "SOC2", name: "SOC 2 Type II" }),
        skipped: false, warnings: [],
      };
    }
    throw new Error(`unmocked postFile: ${path}`);
  });
}

const meta: Meta<typeof StandardListPage> = {
  title: "Modules/Compliance/StandardListPage",
  component: StandardListPage,
  // `withStatefulAuth`, not the plain no-op `withAuth`: Phase 35a's
  // `ViewToggle` reads/writes `useUiPreference`, so switching tiles/list
  // needs a real `setUiPreference` for the UI to actually change.
  decorators: [withToast(), withStatefulAuth(buildUser({ is_server_admin: false })), withRouter("/standards")],
};
export default meta;

type Story = StoryObj<typeof StandardListPage>;

export const SingleOrgList: Story = {
  beforeEach: () => mockStandardListApis([org()], { "org-1": [standard()] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("ISO 27001")).toBeInTheDocument());
    // Only one org — no "Organisation" column, but a "Compliance settings"
    // link for it is still offered.
    await expect(canvas.queryByText("Organisation")).not.toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Acme Corp" })).toHaveAttribute("href", "/standards/settings/org-1");
  },
};

export const MultiOrgShowsOrgColumnAndDropsDisabledOrg: Story = {
  beforeEach: () =>
    mockStandardListApis(
      [org(), org({ id: "org-2", name: "Beta Industries" }), org({ id: "org-3", name: "No Compliance Org" })],
      {
        "org-1": [standard()],
        "org-2": [standard({ id: "std-2", organization_id: "org-2", reference: "SOC2", name: "SOC 2 Type II" })],
        // org-3 has no entry at all — `listStandards` 404s there (module
        // disabled), and it's dropped from the results silently.
      }
    ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("ISO 27001")).toBeInTheDocument());
    await expect(canvas.getByText("SOC 2 Type II")).toBeInTheDocument();
    // "Acme Corp"/"Beta Industries" each appear twice — once in the
    // "Compliance settings" link row, once in the table's own Organisation
    // column — so `getAllByText`, not `getByText`, for both.
    await expect(canvas.getAllByText("Acme Corp").length).toBeGreaterThan(0);
    await expect(canvas.getAllByText("Beta Industries").length).toBeGreaterThan(0);
  },
};

export const CreateStandardWithOrgPicker: Story = {
  beforeEach: () => mockStandardListApis([org(), org({ id: "org-2", name: "Beta Industries" })], { "org-1": [], "org-2": [] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No compliance standards yet.")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("button", { name: "New standard" }));
    const body = within(document.body);
    await userEvent.selectOptions(body.getByLabelText("Organisation"), "org-2");
    await userEvent.type(body.getByLabelText("Standard reference"), "NIST-CSF");
    await userEvent.type(body.getByLabelText("Standard name"), "NIST Cybersecurity Framework");
    await userEvent.type(body.getByLabelText("Initial version label"), "1.0");
    await userEvent.click(body.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith(
      "/api/v1/orgs/org-2/modules/compliance/standards",
      expect.objectContaining({ reference: "NIST-CSF", name: "NIST Cybersecurity Framework" })
    ));
  },
};

/** Phase 35a: `ViewToggle` brings this page into line with
 * `docs/ux-style-guide.md`'s "Pattern: view toggle" — the same tile/list
 * split `ProjectListPage.tsx` already offers. Defaults to tiles; switching
 * to list shows the pre-existing `DirectoryTable`. */
export const TogglesBetweenTilesAndListView: Story = {
  beforeEach: () =>
    mockStandardListApis(
      [org(), org({ id: "org-2", name: "Beta Industries" })],
      {
        "org-1": [standard()],
        "org-2": [standard({ id: "std-2", organization_id: "org-2", reference: "SOC2", name: "SOC 2 Type II" })],
      }
    ),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("ISO 27001")).toBeInTheDocument());

    // Defaults to tiles: no table role, but the standard's card is a link.
    await expect(canvas.queryByRole("table")).not.toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: /ISO 27001/ })).toHaveAttribute("href", "/standards/std-1");

    await userEvent.click(canvas.getByRole("button", { name: "List view" }));
    await expect(canvas.getByRole("table")).toBeInTheDocument();
    await expect(canvas.getByText("SOC 2 Type II")).toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Tile view" }));
    await expect(canvas.queryByRole("table")).not.toBeInTheDocument();
  },
};

export const ImportStandardViaSplitButtonMenu: Story = {
  beforeEach: () => mockStandardListApis([org()], { "org-1": [] }),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText("No compliance standards yet.")).toBeInTheDocument());

    // The rarer "Import standard" path lives behind the split button's
    // chevron, not as a second, permanently-visible button next to
    // "New standard" (docs/ux-style-guide.md's "one door" pattern).
    await expect(canvas.queryByRole("button", { name: "Import standard" })).not.toBeInTheDocument();
    await userEvent.click(canvas.getByRole("button", { name: "More options" }));
    const body = within(document.body);
    await userEvent.click(body.getByRole("button", { name: "Import standard" }));

    const dialog = within(document.body);
    const file = new File([JSON.stringify({ format: "reqtrackmanager.compliance_standard.v1" })], "SOC2-export.json", {
      type: "application/json",
    });
    await userEvent.upload(dialog.getByLabelText("Standard export file") as HTMLInputElement, file);
    await userEvent.click(dialog.getByRole("button", { name: "Import" }));

    await waitFor(() => expect(api.postFile).toHaveBeenCalledWith(
      "/api/v1/orgs/org-1/modules/compliance/standards/import", file, undefined
    ));
  },
};
