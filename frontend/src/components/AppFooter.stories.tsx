import type { Meta, StoryObj } from "@storybook/react-vite";
import { expect, spyOn, waitFor, within } from "storybook/test";

import { api } from "../api/client";
import type { ServerSettings } from "../api/types";
import { buildMemberPolicy, buildPublicPolicy, buildUser, withAuth, withRouter } from "../testing/storybook-helpers";
import { AppFooter } from "./AppFooter";

/** The footer every page ends with: server company details, the policies link and the versions, separated by `|`. */
const meta: Meta<typeof AppFooter> = { title: "Components/AppFooter", component: AppFooter, decorators: [withRouter("/")] };
export default meta;

type Story = StoryObj<typeof AppFooter>;

const SETTINGS: ServerSettings = {
  accent_color_hex: "#475569", default_logo_file_id: null, default_header_title: null, default_login_background_file_id: null,
  logo_band_color_hex: null, logo_band_text_color_hex: null,
  email_footer_company_name: null, email_footer_website: null, email_footer_address: null,
  footer_prefix: null, company_id_label: null, company_id: null,
  org_label_singular: null, org_label_plural: null, file_uploads_enabled: true,
};

/** Routes the footer's reads by path. */
function mockReads(settings: Partial<ServerSettings>, policies: unknown[], memberPolicies: unknown[] = []) {
  spyOn(api, "get").mockImplementation(async (path: string): Promise<unknown> => {
    if (path === "/api/v1/system/branding") return { ...SETTINGS, ...settings };
    if (path === "/api/v1/public/policies") return policies;
    if (path === "/api/v1/policies/mine") return memberPolicies;
    if (path === "/api/v1/system/version") return { version: "1.4.0", git_sha: "abc1234", build_date: "2026-08-15T09:00:00Z" };
    throw new Error(`unmocked path in AppFooter story: ${path}`);
  });
}

/** Signed out: the application version only (the API version needs a session), no company details when unset. */
export const SignedOutWithNothingElse: Story = {
  beforeEach: () => {
    mockReads({}, []);
  },
  play: async ({ canvasElement }) => {
    const footer = within(canvasElement).getByRole("contentinfo", { name: "Page footer" });
    await expect(within(footer).getByText("Version: vdev")).toBeInTheDocument();
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/v1/system/branding"));
    await expect(within(footer).queryByRole("link")).not.toBeInTheDocument();
    await expect(within(footer).queryByText(/\/v/)).not.toBeInTheDocument();
  },
};

/** Prefix and name (linking to the website, which gets https:// when it has no scheme), address, company identifier, policies, versions, with `|` between. */
export const SignedInWithEverything: Story = {
  decorators: [withAuth(buildUser())],
  beforeEach: () => {
    mockReads(
      { email_footer_company_name: "Acme Pty Ltd", email_footer_website: "www.acme.example.com", email_footer_address: "1 Main Street\nSydney NSW 2000",
        footer_prefix: "Hosted by", company_id_label: "ABN", company_id: "12 345 678 901" },
      [buildPublicPolicy()],
    );
  },
  play: async ({ canvasElement }) => {
    const footer = within(canvasElement).getByRole("contentinfo", { name: "Page footer" });
    const company = await within(footer).findByRole("link", { name: "Acme Pty Ltd" });
    await expect(company).toHaveAttribute("href", "https://www.acme.example.com");
    await expect(within(footer).getByText("1 Main Street, Sydney NSW 2000")).toBeInTheDocument();
    await expect(within(footer).getByRole("link", { name: "Policies" })).toHaveAttribute("href", "/policies");
    await expect(await within(footer).findByText("Version: vdev/v1.4.0")).toBeInTheDocument();
    // Four groups, three separators; the policies sit between the address and the versions.
    await expect(footer.textContent).toBe("Hosted by Acme Pty Ltd|1 Main Street, Sydney NSW 2000|ABN 12 345 678 901|Policies|Version: vdev/v1.4.0");
  },
};

/** A group that is absent leaves no separator: only the address and versions here. */
export const AddressOnlyHasNoStraySeparators: Story = {
  beforeEach: () => {
    mockReads({ email_footer_address: "1 Main Street" }, []);
  },
  play: async ({ canvasElement }) => {
    const footer = within(canvasElement).getByRole("contentinfo", { name: "Page footer" });
    await waitFor(() => expect(footer.textContent).toBe("1 Main Street|Version: vdev"));
  },
};

/** An organisation policy alone is enough for the link. */
export const OrganisationPolicyShowsTheLink: Story = {
  decorators: [withAuth(buildUser())],
  beforeEach: () => {
    mockReads({}, [], [buildMemberPolicy()]);
  },
  play: async ({ canvasElement }) => {
    const footer = within(canvasElement).getByRole("contentinfo", { name: "Page footer" });
    await expect(await within(footer).findByRole("link", { name: "Policies" })).toHaveAttribute("href", "/policies");
  },
};

/** A website with another scheme is shown as text and never becomes a link. */
export const UnsafeWebsiteIsNotALink: Story = {
  beforeEach: () => {
    mockReads({ email_footer_website: "javascript:alert(1)" }, []);
  },
  play: async ({ canvasElement }) => {
    const footer = within(canvasElement).getByRole("contentinfo", { name: "Page footer" });
    await expect(await within(footer).findByText("javascript:alert(1)")).toBeInTheDocument();
    await expect(within(footer).queryByRole("link")).not.toBeInTheDocument();
  },
};

/** The prefix needs a company name, and an identifier with no label is shown on its own. */
export const PrefixNeedsANameAndTheIdentifierNeedsNoLabel: Story = {
  beforeEach: () => {
    mockReads({ footer_prefix: "Hosted by", company_id: "99 888" }, []);
  },
  play: async ({ canvasElement }) => {
    const footer = within(canvasElement).getByRole("contentinfo", { name: "Page footer" });
    await waitFor(() => expect(footer.textContent).toBe("99 888|Version: vdev"));
  },
};
