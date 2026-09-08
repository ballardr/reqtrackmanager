import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import type { Organization } from "../../api/types";
import { withRouter, withToast } from "../../testing/storybook-helpers";
import { ComplianceSettingsPage } from "./ComplianceSettingsPage";
import type { ComplianceActionType, ComplianceMappingRelationshipType } from "./types";

const ORG: Organization = {
  id: "org-1", name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
  default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
  disabled_at: null, accent_color_hex: null, header_title: null,
  email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
};
const ACTION_TYPES: ComplianceActionType[] = [{ id: "at-1", organization_id: ORG.id, name: "Review", sort_order: 0 }];
const MAPPING_TYPES: ComplianceMappingRelationshipType[] = [
  { id: "mt-1", organization_id: ORG.id, name: "Equivalent to", implies_equivalence: true, sort_order: 0 },
];

function mockSettingsApis() {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === `/api/v1/orgs/${ORG.id}`) return ORG;
    if (path.endsWith("/action-types")) return ACTION_TYPES;
    if (path.endsWith("/mapping-relationship-types")) return MAPPING_TYPES;
    throw new Error(`unmocked GET: ${path}`);
  });
}

/**
 * `ComplianceSettingsPage` — org-level compliance settings at `/standards/
 * settings/:orgId` (docs/compliance-module-plan.md Phase 18), the two
 * extensible vocabularies (`ActionTypesPanel`, `MappingTypesPanel`) that
 * used to be tabs inside the now-deleted `ComplianceAdminPanel.tsx`,
 * re-hosted behind a `ResourceMenu` instead — a fixed pair of org-wide
 * settings screens, not a project-like drill-down entity, so this gets a
 * `ResourceMenu`, not a nav-rail section (see docs/ux-style-guide.md's
 * "Pattern: project-like drill-down entities").
 */
const meta: Meta<typeof ComplianceSettingsPage> = {
  title: "Modules/Compliance/ComplianceSettingsPage",
  component: ComplianceSettingsPage,
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof ComplianceSettingsPage>;

export const ActionTypesGroup: Story = {
  decorators: [withRouter(`/standards/settings/${ORG.id}`, "/standards/settings/:orgId/:group?")],
  beforeEach: mockSettingsApis,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByText(/Acme Corp — Compliance settings/)).toBeInTheDocument());
    await expect(canvas.getByDisplayValue("Review")).toBeInTheDocument();
    await expect(canvas.getByRole("link", { name: "Action types" })).toHaveAttribute("aria-current", "page");
  },
};

export const MappingTypesGroup: Story = {
  decorators: [withRouter(`/standards/settings/${ORG.id}/mappingTypes`, "/standards/settings/:orgId/:group?")],
  beforeEach: mockSettingsApis,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Equivalent to")).toBeInTheDocument());
    await expect(canvas.getByRole("link", { name: "Mapping types" })).toHaveAttribute("aria-current", "page");
  },
};

export const NavigateBetweenGroups: Story = {
  decorators: [withRouter(`/standards/settings/${ORG.id}`, "/standards/settings/:orgId/:group?")],
  beforeEach: mockSettingsApis,
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByDisplayValue("Review")).toBeInTheDocument());

    await userEvent.click(canvas.getByRole("link", { name: "Mapping types" }));
    await waitFor(() => expect(canvas.getByDisplayValue("Equivalent to")).toBeInTheDocument());
  },
};
