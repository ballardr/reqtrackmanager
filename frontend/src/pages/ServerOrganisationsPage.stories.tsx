import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, userEvent, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { Organization, OrgCreationChoice } from "../api/types";
import { withRouter, withToast } from "../testing/storybook-helpers";
import { ServerOrganisationsPage } from "./ServerOrganisationsPage";

function org(overrides: Partial<Organization>): Organization {
  return {
    id: "org-1", name: "Acme Corp", created_at: "2026-01-01T00:00:00Z", logo_file_id: null,
    default_template_project_id: null, login_background_file_id: null, slug: "acme", is_active: true,
    disabled_at: null, accent_color_hex: null, header_title: null,
    email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
  force_require_change_request_for_approved_links: false,
  allow_ai_approvals: false,
    ...overrides,
  };
}

// Module 4 (Decision Management) Phase 1 — this page's own `useEffect`
// fetches `/api/v1/orgs/creation-choices` unconditionally on mount,
// alongside the `/api/v1/orgs` list, so every story's `api.get` mock must
// branch on the requested path rather than returning one fixed value for
// every call. `choices` defaults to empty (a plain "no module offers
// anything" org-creation flow); stories that exercise the picker itself
// pass a non-empty list explicitly.
function mockOrgsGet(orgs: Organization[], choices: OrgCreationChoice[] = []) {
  spyOn(api, "get").mockImplementation(async (path: string) =>
    path === "/api/v1/orgs/creation-choices" ? choices : orgs
  );
}

const DECISION_TEMPLATE_CHOICES: OrgCreationChoice[] = [
  {
    key: "decisions:adr_nygard", group_label: "Decision Templates", label: "Nygard (Classic ADR)",
    description: "Michael Nygard's original, minimal ADR format.", default_selected: true,
  },
  {
    key: "decisions:adr_madr", group_label: "Decision Templates",
    label: "MADR (Markdown Architectural Decision Records)",
    description: "The fuller ADR format.", default_selected: true,
  },
  {
    key: "decisions:adr_y_statement", group_label: "Decision Templates", label: "Y-Statement",
    description: "The compressed, single-sentence ADR form.", default_selected: false,
  },
];

const meta: Meta<typeof ServerOrganisationsPage> = {
  title: "Pages/ServerOrganisationsPage",
  component: ServerOrganisationsPage,
  decorators: [withRouter("/server/organisations"), withToast()],
};
export default meta;

type Story = StoryObj<typeof ServerOrganisationsPage>;

export const ActiveOrganisations: Story = {
  beforeEach: () => {
    mockOrgsGet([
      org({ id: "org-1", name: "Acme Corp", is_active: true }),
      org({ id: "org-2", name: "Beta Inc", is_active: false }),
    ]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    // Defaults to the "active" filter — the disabled org is hidden.
    await expect(canvas.getByText("Acme Corp")).toBeInTheDocument();
    await expect(canvas.queryByText("Beta Inc")).not.toBeInTheDocument();
  },
};

/** Style guide "Pattern: action menu"'s per-row addendum — Edit/Disable/
 * Delete now sit behind one `ActionMenu` in the row's actions column
 * instead of three standalone buttons. */
export const RowActionsOpenInActionMenu: Story = {
  beforeEach: () => {
    mockOrgsGet([org({ id: "org-1", name: "Acme Corp", is_active: true })]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await expect(body.queryByRole("menu")).not.toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: "Acme Corp actions" }));
    const menu = body.getByRole("menu", { name: "Acme Corp actions" });
    await expect(within(menu).getByRole("menuitem", { name: "Edit" })).toBeInTheDocument();
    await expect(within(menu).getByRole("menuitem", { name: "Disable" })).toBeInTheDocument();
    await expect(within(menu).getByRole("menuitem", { name: "Delete" })).toBeInTheDocument();
  },
};

export const ShowAllIncludesDisabled: Story = {
  beforeEach: () => {
    mockOrgsGet([
      org({ id: "org-1", name: "Acme Corp", is_active: true }),
      org({ id: "org-2", name: "Beta Inc", is_active: false }),
    ]);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.selectOptions(canvas.getByLabelText("Status"), "All");
    await expect(canvas.getByText("Acme Corp")).toBeInTheDocument();
    await expect(canvas.getByText("Beta Inc")).toBeInTheDocument();
  },
};

/** Style guide "Pattern: modal dialog for entity create/rename" — "New
 * organisation" opens a `Modal` instead of a permanently-visible inline
 * block that reflows the list underneath it. */
export const CreateOrganisation: Story = {
  beforeEach: () => {
    mockOrgsGet([org({})]);
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    const body = within(document.body);
    await expect(body.queryByRole("dialog")).not.toBeInTheDocument();

    await userEvent.click(canvas.getByRole("button", { name: /New organisation/ }));
    const dialog = body.getByRole("dialog", { name: "New organisation" });
    await userEvent.type(within(dialog).getByLabelText("Organisation name"), "New Co");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create" }));
    // No module offers any org-creation choices in this story (empty
    // `creation-choices` mock) — `module_choice_keys` still resolves to an
    // empty array, not `undefined`, once the picker's own fetch settles.
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/v1/orgs", { name: "New Co", module_choice_keys: [] })
    );
    await expect(body.getByText("Organisation created")).toBeInTheDocument();
    await expect(body.queryByRole("dialog")).not.toBeInTheDocument();
  },
};

/** Module 4 (Decision Management) Phase 1 — a module's optional
 * org-creation seeding choices (e.g. Decision Management's three ADR
 * template packs) render generically, grouped by `group_label`, with only
 * each option's own `default_selected` value pre-checked. */
export const CreateOrganisationWithTemplateChoices: Story = {
  beforeEach: () => {
    mockOrgsGet([org({})], DECISION_TEMPLATE_CHOICES);
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New organisation/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "New organisation" });
    const dialogScope = within(dialog);

    await expect(dialogScope.getByText("Decision Templates")).toBeInTheDocument();
    const nygard = dialogScope.getByRole("checkbox", { name: /Nygard/ });
    const madr = dialogScope.getByRole("checkbox", { name: /MADR/ });
    const yStatement = dialogScope.getByRole("checkbox", { name: /Y-Statement/ });
    await expect(nygard).toBeChecked();
    await expect(madr).toBeChecked();
    await expect(yStatement).not.toBeChecked();

    // Uncheck one default-selected pack, check the non-default one.
    await userEvent.click(madr);
    await userEvent.click(yStatement);
    await userEvent.type(dialogScope.getByLabelText("Organisation name"), "New Co");
    await userEvent.click(dialogScope.getByRole("button", { name: "Create" }));

    // Insertion order into `selectedChoiceKeys` (a `Set`) is deterministic:
    // Nygard was already selected (never toggled), so it stays first;
    // Y-Statement was just added, so it's last.
    await waitFor(() =>
      expect(api.post).toHaveBeenCalledWith("/api/v1/orgs", {
        name: "New Co",
        module_choice_keys: ["decisions:adr_nygard", "decisions:adr_y_statement"],
      })
    );
  },
};

/** The picker is hidden entirely for the bundle-import path — an imported
 * organisation carries its own already-existing settings, there is
 * nothing fresh to seed. */
export const CreateOrganisationImportHidesTemplateChoices: Story = {
  beforeEach: () => {
    mockOrgsGet([org({})], DECISION_TEMPLATE_CHOICES);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New organisation/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "New organisation" });
    const dialogScope = within(dialog);
    await expect(dialogScope.getByText("Decision Templates")).toBeInTheDocument();

    const file = new File(["{}"], "bundle.zip", { type: "application/zip" });
    await userEvent.upload(dialogScope.getByLabelText(/Or import from an exported/), file);

    await expect(dialogScope.queryByText("Decision Templates")).not.toBeInTheDocument();
  },
};

/** Cancelling the modal creates nothing and leaves the list untouched. */
export const CreateOrganisationModalCancel: Story = {
  beforeEach: () => {
    mockOrgsGet([org({})]);
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: /New organisation/ }));
    const dialog = within(document.body).getByRole("dialog", { name: "New organisation" });
    await userEvent.type(within(dialog).getByLabelText("Organisation name"), "Discarded Co");
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    await expect(api.post).not.toHaveBeenCalled();
  },
};

/** Disable opens the shared `ConfirmDialog` (2026-08 UX audit, sixth pass —
 * this used to fire via `window.confirm`), then shows a success toast
 * (Principle 7) once the action completes. Reached via the row's
 * `ActionMenu` now, not a standalone "Disable" button — the menu is just
 * the entry point, it doesn't replace the confirmation itself. */
export const DisableOrganisation: Story = {
  beforeEach: () => {
    mockOrgsGet([org({ id: "org-1", name: "Acme Corp", is_active: true })]);
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Acme Corp actions" }));
    const menu = within(document.body).getByRole("menu", { name: "Acme Corp actions" });
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Disable" }));

    const dialog = within(document.body).getByRole("dialog", { name: 'Disable "Acme Corp"?' });
    await userEvent.click(within(dialog).getByRole("button", { name: "Disable" }));

    await waitFor(() => expect(api.post).toHaveBeenCalledWith("/api/v1/orgs/org-1/disable"));
    await expect(within(document.body).getByText("Organisation disabled")).toBeInTheDocument();
  },
};

/** Cancelling the disable confirmation leaves the organisation untouched —
 * the pilot pattern's paired cancel story (`RequirementDetailPage`'s
 * `ArchivingConfirmsAndShowsToast`/cancel pair) applied here. */
export const DisableOrganisationCancelled: Story = {
  beforeEach: () => {
    mockOrgsGet([org({ id: "org-1", name: "Acme Corp", is_active: true })]);
    spyOn(api, "post").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Acme Corp actions" }));
    const menu = within(document.body).getByRole("menu", { name: "Acme Corp actions" });
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Disable" }));

    const dialog = within(document.body).getByRole("dialog", { name: 'Disable "Acme Corp"?' });
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    await expect(within(document.body).queryByRole("dialog")).not.toBeInTheDocument();
    await expect(api.post).not.toHaveBeenCalled();
  },
};

/** Deleting requires typing the organisation's exact name — the confirm
 * button stays disabled until the typed text matches. Reached via the
 * row's `ActionMenu` now, not a standalone "Delete" button. */
export const DeleteRequiresTypedConfirmation: Story = {
  beforeEach: () => {
    mockOrgsGet([org({ id: "org-1", name: "Acme Corp", is_active: true })]);
    spyOn(api, "delete").mockResolvedValue(undefined);
  },
  play: async ({ canvasElement }) => {
    const canvas = within(canvasElement);
    await userEvent.click(canvas.getByRole("button", { name: "Acme Corp actions" }));
    const menu = within(document.body).getByRole("menu", { name: "Acme Corp actions" });
    await userEvent.click(within(menu).getByRole("menuitem", { name: "Delete" }));

    // The confirmation is now the shared `ConfirmDialog`, portalled into
    // document.body rather than rendered inline in the page.
    const dialog = within(document.body).getByRole("dialog");
    const confirmButton = within(dialog).getByRole("button", { name: "Permanently delete" });
    await expect(confirmButton).toBeDisabled();
    await userEvent.type(within(dialog).getByLabelText('Type "Acme Corp" to confirm'), "Acme Corp");
    await expect(confirmButton).toBeEnabled();
    await userEvent.click(confirmButton);
    await waitFor(() => expect(api.delete).toHaveBeenCalledWith("/api/v1/orgs/org-1", { confirm_name: "Acme Corp" }));
  },
};

export const LightTheme: Story = { ...ActiveOrganisations, globals: { theme: "light" } };
export const DarkTheme: Story = { ...ActiveOrganisations, globals: { theme: "dark" } };
