import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../../api/client";
import { buildUser, withAuth, withRouter, withToast } from "../../testing/storybook-helpers";
import { ComplianceStatusPage } from "./ComplianceStatusPage";

/**
 * The By standard and Outstanding tabs of the Standards page: the tab strip, the Organisation filter that appears
 * only for a person in more than one organisation, and the message for a person with no organisation to read.
 */
// Each story gives its own `buildUser()` (a fresh id): the nav-visibility answer is cached per user id, so a shared
// user would hand the second story the first one's answer.
const ORGS = [
  { id: "org-1", name: "Acme", is_active: true },
  { id: "org-2", name: "Globex", is_active: true },
];

function mockApis(statusOrganizationIds: string[]) {
  spyOn(api, "get").mockImplementation(async (path: string) => {
    if (path === "/api/v1/compliance/nav-visibility") return { visible: true, status_organization_ids: statusOrganizationIds };
    if (path.startsWith("/api/v1/orgs?mine=true")) return ORGS;
    if (path.includes("/project-compliance")) return [];
    if (path.includes("/non-compliant-requirements") || path.includes("/pending-approvals") ||
        path.includes("/outstanding-required-actions") || path.includes("/expiring-evidence") || path.includes("/reviews-due")) return [];
    throw new Error(`unmocked GET: ${path}`);
  });
}

const meta: Meta<typeof ComplianceStatusPage> = {
  title: "Modules/Compliance/ComplianceStatusPage",
  component: ComplianceStatusPage,
  decorators: [withToast()],
};
export default meta;

type Story = StoryObj<typeof ComplianceStatusPage>;

/** A person who reads the status of two organisations gets the three tabs and an Organisation filter. */
export const ByStandardWithOrganisationFilter: Story = {
  args: { view: "by-standard" },
  decorators: [withAuth(buildUser()), withRouter("/standards/by-standard")],
  beforeEach: () => mockApis(["org-1", "org-2"]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("tab", { name: "By standard" })).toHaveAttribute("aria-selected", "true"));
    await expect(canvas.getByRole("tab", { name: "Standards" })).toBeInTheDocument();
    await expect(canvas.getByRole("tab", { name: "Outstanding" })).toBeInTheDocument();
    const filter = await canvas.findByLabelText("Organisation");
    await expect(within(filter).getAllByRole("option").map((o) => o.textContent)).toEqual(["Acme", "Globex"]);
    // The first organisation is read until another is chosen; choosing one loads that organisation's rows.
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/v1/orgs/org-1/modules/compliance/project-compliance?include_archived=false"));
    await userEvent.selectOptions(filter, "org-2");
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/v1/orgs/org-2/modules/compliance/project-compliance?include_archived=false"));
  },
};

/** A person in one readable organisation sees no Organisation filter. */
export const OutstandingForOneOrganisation: Story = {
  args: { view: "outstanding" },
  decorators: [withAuth(buildUser()), withRouter("/standards/outstanding")],
  beforeEach: () => mockApis(["org-1"]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await waitFor(() => expect(canvas.getByRole("tab", { name: "Outstanding" })).toHaveAttribute("aria-selected", "true"));
    await canvas.findByText("Non-compliant requirements (0)");
    await expect(canvas.queryByLabelText("Organisation")).not.toBeInTheDocument();
  },
};

/** An address naming an organisation the person cannot read falls back to the first one they can. */
export const UnreadableOrganisationInTheAddressFallsBack: Story = {
  args: { view: "by-standard" },
  decorators: [withAuth(buildUser()), withRouter("/standards/by-standard?org=org-9")],
  beforeEach: () => mockApis(["org-1", "org-2"]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByLabelText("Organisation");
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/v1/orgs/org-1/modules/compliance/project-compliance?include_archived=false"));
    await expect(api.get).not.toHaveBeenCalledWith("/api/v1/orgs/org-9/modules/compliance/project-compliance?include_archived=false");
  },
};

/** A person who can only read standards is told so; the strip stays so they can return to the list. */
export const NoOrganisationToRead: Story = {
  args: { view: "by-standard" },
  decorators: [withAuth(buildUser()), withRouter("/standards/by-standard")],
  beforeEach: () => mockApis([]),
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await canvas.findByText("Compliance status is available to compliance managers.");
    await expect(canvas.getByRole("tab", { name: "Standards" })).toBeInTheDocument();
  },
};
